import asyncio
import logging
import threading
import time
import math
from dataclasses import replace
from PySide6.QtCore import QObject, Signal
from .windows import CaptureService, PreviewCaptureService, active_window, window_identity, source_window_current
from .models import Rect, Translation
from .ocr import WindowsOcrProvider, OcrService
from .translation import HttpTranslationProvider, TranslationService, TranslationError
from .text import TextFilterService, belongs_to_region
from .detection import TextRegionDetector, RegionTracker
from .app_catalog import AppBlockService
from .anchors import VisualAnchors

log = logging.getLogger(__name__)


def whole_screen_tiles(bounds, preview_shape):
    """Partition a focused window using one low-resolution change preview.

    Each tile owns only its core pixels. The padded capture supplies OCR context
    across tile boundaries, without letting neighbouring motion dirty that tile.
    """
    height, width = preview_shape[:2]
    # A small document/dialogue is one semantic block; splitting it would
    # truncate long lines and numerical values at tile boundaries.
    if bounds.w < 1200 or bounds.h < 650:
        columns = rows = 1
    else:
        columns = max(1, min(6, math.ceil(bounds.w / 384)))
        rows = max(1, min(4, math.ceil(bounds.h / 360)))
    for row in range(rows):
        y0, y1 = bounds.y + bounds.h * row // rows, bounds.y + bounds.h * (row + 1) // rows
        py0, py1 = height * row // rows, height * (row + 1) // rows
        for column in range(columns):
            x0, x1 = bounds.x + bounds.w * column // columns, bounds.x + bounds.w * (column + 1) // columns
            px0, px1 = width * column // columns, width * (column + 1) // columns
            core = Rect(x0, y0, x1 - x0, y1 - y0)
            # Wide context keeps a dialogue/tweet line intact even when its
            # centre falls in one tile and its ends cross tile boundaries.
            padded = Rect(x0 - 256, y0 - 96, core.w + 512, core.h + 192).intersect(bounds)
            yield core, padded, (px0, py0, px1, py1)


def dirty_capture_rects(previous, current, bounds, preview_bounds=None, tracked=()):
    """Map changed preview islands to small physical OCR crops.

    A fullscreen tile previews only its non-overlapping core, while its OCR
    capture includes padding for sentences crossing tile edges. The mapping
    must therefore use *core* coordinates rather than padded-capture bounds.
    """
    import cv2
    import numpy as np

    if previous is None:
        return [bounds]
    mask = np.any(np.abs(current.astype(np.int16) - previous.astype(np.int16)) > 12, axis=2).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    view = preview_bounds or bounds
    height, width = mask.shape
    margin_x = min(256, max(64, round(view.w * .12)))
    margin_y = min(96, max(32, round(view.h * .09)))
    crops = []
    for x, y, w, h, area in stats[1:]:
        if area < 3:
            continue
        left = view.x + int(x * view.w / width) - margin_x
        top = view.y + int(y * view.h / height) - margin_y
        right = view.x + math.ceil((x + w) * view.w / width) + margin_x
        bottom = view.y + math.ceil((y + h) * view.h / height) + margin_y
        crop = Rect(left, top, right - left, bottom - top).intersect(bounds)
        if crop.w < 8 or crop.h < 8:
            continue
        # If one word within an existing sentence changed, read the entire
        # sentence again. A fixed crop around the changed letters can turn
        # "find the treasure" into just "treasure" and lose context.
        for old in tracked:
            if crop.intersect(old).w and crop.intersect(old).h:
                crop = crop.union(old).intersect(bounds)
        merged = True
        while merged:
            merged = False
            for index, existing in enumerate(crops):
                if crop.intersect(existing).w and crop.intersect(existing).h:
                    crop = crop.union(crops.pop(index))
                    merged = True
                    break
        crops.append(crop)
    if len(crops) > 8:
        return [bounds]
    return crops


def merge_dirty_rects(rects, bounds):
    merged = []
    for area in rects:
        combined = area
        again = True
        while again:
            again = False
            for index, existing in enumerate(merged):
                if combined.intersect(existing).w and combined.intersect(existing).h:
                    combined = combined.union(merged.pop(index))
                    again = True
                    break
        merged.append(combined)
        if len(merged) > 8:
            return [bounds]
    return merged


def contained_text(small_text, small_rect, large_text, large_rect):
    """A padded OCR tile may see just the final line of another tile's paragraph."""
    from .text import normalize
    small, large = normalize(small_text), normalize(large_text)
    area = small_rect.w * small_rect.h
    intersection = small_rect.intersect(large_rect)
    return (bool(small) and small != large and len(large) > len(small) + 3
        and small in large and intersection.w * intersection.h >= area * .9
        and large_rect.w * large_rect.h > area * 1.2)


def reconcile_zone_blocks(engine, state, bounds, blocks):
    """Suppress only overlapping fragments; never touch disjoint watch areas."""
    kept = []
    for block in blocks:
        absolute = Rect(bounds.x+block.rect.x,bounds.y+block.rect.y,block.rect.w,block.rect.h)
        duplicate = False
        for other in getattr(engine,'zone_states',{}).values():
            if other is state or 'bounds' not in other:
                continue
            other_bounds = other['bounds']
            for key, old in list(other.get('blocks',{}).items()):
                if key not in other['tracker'].regions:
                    continue
                old_rect = Rect(other_bounds.x+old.rect.x,other_bounds.y+old.rect.y,old.rect.w,old.rect.h)
                if contained_text(block.text,absolute,old.text,old_rect):
                    duplicate = True
                    break
                if contained_text(old.text,old_rect,block.text,absolute):
                    other['blocks'].pop(key,None)
                    other['tracker'].regions.pop(key,None)
                    job_key = other.get('namespace','')+key
                    task = engine.jobs.pop(job_key,None)
                    if task: task.cancel()
                    group = 'watch-'+job_key
                    engine.removed.emit(group)
                    for anchor in list(engine.anchors.items):
                        if anchor == group or anchor.startswith(group+':'):
                            engine.anchors.items.pop(anchor,None)
            if duplicate: break
        if not duplicate: kept.append(block)
    return kept


class Engine(QObject):
    translated = Signal(object)
    removed = Signal(str)
    cleared = Signal()
    status = Signal(str)
    diagnostics = Signal(object)
    progress = Signal(object)
    ignore_translated = Signal(str, str)
    watch_changed = Signal(bool)
    tested = Signal(bool, str)
    manual_failed = Signal(str, object, object)
    source_moved = Signal(str, object)
    source_lost = Signal(str)
    region_alive = Signal(str)

    def __init__(self, settings, store):
        super().__init__()
        self.settings, self.store = settings, store
        self.app_blocks = AppBlockService(settings)
        self.watch = False
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="Lens processing", daemon=True)
        self.thread.start()
        self.ready.wait(5)

    def _run(self):
        import winrt.runtime
        import cv2
        cv2.setNumThreads(1)  # Small crops should not fan out across every CPU core.
        winrt.runtime.init_apartment(winrt.runtime.ApartmentType.MULTI_THREADED)
        asyncio.set_event_loop(self.loop)
        self.capture = CaptureService()
        self.preview_capture = PreviewCaptureService()
        self.ocr = None
        self.ocr_lock = asyncio.Lock()
        from .offline import TranslationProvider
        self.provider = TranslationProvider(self.settings)
        self.translator = TranslationService(self.provider, self.store)
        self.tracker = RegionTracker()
        self.zone_states = {}
        self.detector = TextRegionDetector()
        self.ocr_zone_tracking = True
        self.jobs = {}
        self.manual = self.watcher = None
        self.context = None
        self.generation = 0
        self.backoff = 0
        self.anchors = VisualAnchors()
        self.anchor_watcher = None
        self.ready.set()
        try:
            self.loop.run_forever()
        finally:
            self.capture.close()
            self.preview_capture.close()
            winrt.runtime.uninit_apartment()
            self.loop.close()

    def _submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def _get_ocr(self):
        if self.ocr is None:
            self.ocr = OcrService(WindowsOcrProvider(), TextFilterService(self.settings))
        return self.ocr

    def translate_ignore_label(self, text):
        self._submit(self._translate_ignore_label(text))

    async def _translate_ignore_label(self, text):
        try:
            arabic, _ = await self.translator.translate(text)
            self.ignore_translated.emit(text, arabic)
        except Exception:
            self.ignore_translated.emit(text, '')

    def _progress(self, key, rect, percent, stage, source_window=None):
        if self.settings.show_translation_boxes:
            self.progress.emit({'id':key, 'rect':rect, 'percent':percent, 'stage':stage,'source_window':source_window})

    async def _translate_progress(self, source, key, rect, source_window=None):
        Engine._progress(self, key, rect, 50, 'Queued',source_window)
        if isinstance(self.translator, TranslationService):
            return await self.translator.translate(source,
                on_started=lambda: Engine._progress(self,key,rect,75,'Translating',source_window))
        return await self.translator.translate(source)

    def toggle(self):
        self.set_watch(not self.watch)

    def set_watch(self, enabled):
        self._submit(self._set_watch(enabled))

    async def _set_watch(self, enabled):
        self.anchors.clear()
        self.watch = enabled
        self.generation += 1
        if self.watcher:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)
            self.watcher = None
        self._cancel_jobs()
        self.tracker.clear()
        for state in self.zone_states.values():
            state['tracker'].clear()
        self.zone_states.clear()
        self.context = None
        self.cleared.emit()
        self.watch_changed.emit(enabled)
        if enabled:
            self.watcher = asyncio.create_task(self._watch_loop())

    def _cancel_jobs(self):
        for task in self.jobs.values():
            task.cancel()
        self.jobs.clear()

    async def _watch_loop(self):
        import numpy as np
        frame_generation = self.generation
        try:
            while self.watch:
                started = time.monotonic()
                if frame_generation != self.generation:
                    self.zone_states.clear()
                    frame_generation = self.generation
                active = active_window(False if self.settings.watch_fullscreen else self.settings.active_only)
                if active and self.app_blocks.blocked(active[0]):
                    # An explicit app exclusion is different from a transient
                    # focus gap. Stop that Watch context and its jobs without
                    # touching unrelated Quick Capture translations.
                    if self.context is not None:
                        self.generation += 1
                        self._cancel_jobs()
                        for state in self.zone_states.values():
                            for region in state['tracker'].regions.values():
                                self.removed.emit('watch-' + state.get('namespace', '') + region.id)
                        self.tracker.clear()
                        self.zone_states.clear()
                        for key in list(self.anchors.items):
                            if key.startswith('watch-'):
                                self.anchors.items.pop(key, None)
                        self.context = None
                        frame_generation = self.generation
                    await asyncio.sleep(max(.05, min(self.settings.scan_ms, 250) / 1000))
                    continue
                configured = [] if self.settings.watch_fullscreen else (self.settings.watch_areas or ([self.settings.watch_region] if self.settings.watch_region else []))
                zones = []
                if active:
                    # A manually selected rectangle belongs to the screen, not
                    # to whichever window happened to have focus on this tick.
                    # A click outside it cannot change its capture geometry.
                    zones = [Rect(*area) for area in configured] if configured else [active[1]]
                    zones = [zone for zone in zones if zone.w >= 8 and zone.h >= 8]
                if not active:
                    # Our own Settings window or a momentary focus transition
                    # must not clear unchanged translated text. Closed/minimized
                    # source windows are handled by SourceWindowMonitor.
                    await asyncio.sleep(max(.05, min(self.settings.scan_ms, 250) / 1000))
                    continue
                identity = (self.settings.watch_fullscreen, tuple(zones))
                if identity != self.context:
                    self.generation += 1
                    self._cancel_jobs()
                    self.tracker.clear()
                    self.zone_states.clear()
                    self.cleared.emit()
                    self.context = identity
                    self.anchors.clear()
                    frame_generation = self.generation
                if active and not (self.manual and not self.manual.done()):
                    scan_plan = []
                    index = 0
                    tiled = any(zone.w >= 1200 and zone.h >= 650 for zone in zones)
                    for bounds in zones:
                        if bounds.w >= 1200 and bounds.h >= 650 or not configured:
                            overview = self.preview_capture.capture(bounds).copy()
                            for core, padded, (x0,y0,x1,y1) in whole_screen_tiles(bounds,overview.shape):
                                scan_plan.append((index,padded,overview[y0:y1,x0:x1],core,True))
                                index += 1
                        else:
                            scan_plan.append((index,bounds,None,None,len(zones)>1 or tiled))
                            index += 1
                    # Rotate service order, keeping stable zone IDs. A busy feed
                    # near the top-left cannot monopolize every translation slot.
                    cursor = getattr(self,'scan_cursor',0) % max(1,len(scan_plan))
                    self.scan_cursor = cursor + 1
                    for index,bounds,preview,core,multiple in scan_plan[cursor:] + scan_plan[:cursor]:
                        if not self.watch or frame_generation != self.generation:
                            break
                        await self._scan_zone(index,bounds,active[0],active[2],np,started,
                            preview=preview,core=core,multiple=multiple)
                interval = min(self.settings.scan_ms, 250)
                await asyncio.sleep(max(.05, interval / 1000 - (time.monotonic() - started)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._report(exc)
            self.watch = False
            self._cancel_jobs()
            self.cleared.emit()
            self.watch_changed.emit(False)

    async def _scan_ocr_zone(self, index, bounds, hwnd, title, np, started,
            preview=None, core=None, multiple=None):
        """Track OCR text blocks inside one independent physical watch zone.

        The first frame reads the entire zone so no English line depends on an
        edge/contour heuristic. Later frames OCR only the preview's changed
        islands. Existing blocks outside those islands keep their identity and
        translation, including in fullscreen mode's independently previewed
        tiles. A mouse click by itself is never an invalidation signal.
        """
        if multiple is None:
            multiple = len(self.settings.watch_areas) > 1
        state = self.zone_states.setdefault(index, {'preview': None, 'image': None,
            'seen_ids': set(), 'last_alive': {}, 'blocks': {},
            'tracker': self.tracker if index == 0 else RegionTracker()})
        tracker = state['tracker']
        namespace = f'{index}-' if multiple else ''
        state['namespace'] = namespace
        state['bounds'] = bounds
        if self.settings.show_translation_boxes:
            state['source_window'] = window_identity(hwnd)
        if preview is None:
            preview = self.preview_capture.capture(bounds)
        previous_preview = state['preview']
        changed_pixels = max(8, min(64, preview.shape[0] * preview.shape[1] // 900))
        changed = previous_preview is None or np.count_nonzero(np.any(
            np.abs(preview.astype(np.int16) - previous_preview) > 12, axis=2)) >= changed_pixels
        now = time.monotonic()
        anchor_lost = []
        removed = []
        first_frame = previous_preview is None
        if changed:
            state['preview'] = preview.astype(np.int16)
            image = self.capture.capture(bounds).copy()
            state['image'] = image
            if self.settings.overlay.follow_content and self.anchors.items:
                anchor_lost = self._follow_sources(image, bounds, namespace=namespace,
                    tracker=tracker) or []
                state.setdefault('pending_anchor_lost', set()).update(anchor_lost)
            tracked = [Rect(bounds.x + r.rect.x, bounds.y + r.rect.y,
                r.rect.w, r.rect.h) for r in tracker.regions.values()]
            dirty = dirty_capture_rects(previous_preview, preview, bounds, core, tracked)
            if dirty:
                state['pending_dirty'] = merge_dirty_rects(
                    state.get('pending_dirty', []) + dirty, bounds)
                state['last_change'] = now
        pending = state.get('pending_dirty', [])
        # During continuous scrolling, cheap previews and visual anchor moves
        # continue every tick. OCR waits for a short quiet period, with a hard
        # cadence limit so animated backgrounds cannot starve new dialogue.
        read_now = bool(pending) and (first_frame
            or now - state.get('last_change', now) >= .18
            or now - state.get('last_ocr', now) >= 1.2)
        if read_now:
            removed = await self._read_dirty_zone(state, bounds, core, np, now)
            anchor_lost = list(state.pop('pending_anchor_lost', ()))
        else:
            anchor_lost = []
            for key in state['seen_ids']:
                region = tracker.regions.get(key)
                if region:
                    region.seen = now
            removed = tracker.expire(now)

        for key in removed:
            job_key = namespace + key
            state['last_alive'].pop(job_key, None)
            task = self.jobs.pop(job_key, None)
            if task:
                task.cancel()
            if key not in tracker.regions:
                state['blocks'].pop(key, None)
                self.removed.emit('watch-' + job_key)
        for key in anchor_lost:
            group = key.removeprefix('watch-' + namespace).split(':', 1)[0]
            region = tracker.regions.get(group)
            block = state['blocks'].get(group)
            from .text import normalize
            # A colour change or one missed OCR frame is not proof that the
            # source text vanished. Retire immediately only when OCR actually
            # reads different words in this same tracked position. A missing
            # block is handled by tracker expiry after the quiet OCR pass.
            confirmed_other_words = (region is not None and region.seen == now
                and block is not None and bool(getattr(region, 'confirmed_sources', ()))
                and normalize(block.text) not in region.confirmed_sources)
            if confirmed_other_words:
                self.source_lost.emit(key)

        if self.settings.overlay.persistence:
            interval = max(.5, min(2.0, self.settings.overlay.duration / 3))
            for region in tracker.regions.values():
                if not region.processed or not region.delivered or region.seen != now:
                    continue
                job_key = namespace + region.id
                if now - state['last_alive'].get(job_key, 0) < interval:
                    continue
                state['last_alive'][job_key] = now
                self.region_alive.emit('watch-' + job_key)

        if now >= self.backoff and state['image'] is not None:
            capacity = max(0, min(8, self.settings.max_regions) - len(self.jobs))
            # Reserve room for other zones; each scan revisits pending blocks.
            if multiple:
                capacity = min(2, capacity)
            stable = min(self.settings.stability_ms, 300)
            for region in tracker.ready(now, stable, self.settings.cooldown_ms, capacity):
                block = state['blocks'].get(region.id)
                if block is None:
                    continue
                region.processed, region.attempted = True, now
                job_key = namespace + region.id
                task = asyncio.create_task(self._region(region, state['image'], bounds,
                    title, self.generation, [], Rect(0, 0, bounds.w, bounds.h),
                    window_identity(hwnd), tracker, namespace, precomputed=[block]))
                self.jobs[job_key] = task
                task.add_done_callback(lambda completed, key=job_key:
                    self.jobs.pop(key, None) if self.jobs.get(key) is completed else None)
        if self.settings.debug:
            self.diagnostics.emit({'regions': [(namespace + r.id,
                Rect(bounds.x+r.rect.x, bounds.y+r.rect.y, r.rect.w, r.rect.h), r.revision)
                for r in tracker.regions.values()],
                'scan_ms': round((time.monotonic() - started)*1000)})

    async def _read_dirty_zone(self, state, bounds, core, np, now):
        """OCR only the accumulated changed islands of one Watch zone."""
        from .text import normalize
        tracker = state['tracker']
        image = state['image']
        previous_image = state.get('ocr_image')
        dirty = state.pop('pending_dirty', [])
        state['ocr_image'] = image
        state['last_ocr'] = now
        blocks = []
        for area in dirty:
            ox, oy = area.x - bounds.x, area.y - bounds.y
            crop = image[oy:oy + area.h, ox:ox + area.w]
            # Blank tiles contain no English and need no OCR runtime startup.
            if int(np.max(crop[:, :, :3])) - int(np.min(crop[:, :, :3])) < 12:
                continue
            async with self.ocr_lock:
                recognized = await self._get_ocr().read(crop)
            for block in recognized:
                moved = replace(block,
                    rect=Rect(ox + block.rect.x, oy + block.rect.y,
                        block.rect.w, block.rect.h),
                    container=Rect(ox + block.container.x, oy + block.container.y,
                        block.container.w, block.container.h) if block.container else None)
                center_x = bounds.x + moved.rect.x + moved.rect.w // 2
                center_y = bounds.y + moved.rect.y + moved.rect.h // 2
                if core is not None and not (core.x <= center_x < core.right
                        and core.y <= center_y < core.bottom):
                    continue
                if any(normalize(old.text) == normalize(moved.text)
                        and old.rect.overlap(moved.rect) > .65 for old in blocks):
                    continue
                blocks.append(moved)
        blocks = reconcile_zone_blocks(self,state,bounds,blocks)
        # A static block in a dirty crop is still present even if OCR misses
        # it on this pass; only pixels changing inside its own box can retire it.
        if previous_image is not None and previous_image.shape == image.shape:
            for region in tracker.regions.values():
                r = region.rect
                before = previous_image[r.y:r.bottom, r.x:r.right]
                after = image[r.y:r.bottom, r.x:r.right]
                unchanged_pixels = (before.shape == after.shape and np.count_nonzero(np.any(
                    np.abs(after.astype(np.int16) - before.astype(np.int16)) > 12,
                    axis=2)) < 3)
                same_letter_edges = False
                if not unchanged_pixels and before.shape == after.shape and before.size:
                    import cv2
                    color = cv2.COLOR_BGRA2GRAY if before.shape[2] == 4 else cv2.COLOR_BGR2GRAY
                    same_letter_edges = VisualAnchors.identical(
                        cv2.cvtColor(after, color), cv2.cvtColor(before, color))
                if unchanged_pixels or same_letter_edges:
                    region.seen = now
        removed = tracker.update([block.rect for block in blocks], image, now,
            previous_image=previous_image)
        for block in blocks:
            region = max((r for r in tracker.regions.values()
                if r.seen == now and r.rect.overlap(block.rect) > .65),
                key=lambda r: r.rect.overlap(block.rect), default=None)
            if region is None:
                continue
            state['blocks'][region.id] = block
            if self.settings.show_translation_boxes and not region.processed:
                self.progress.emit({'id':'watch-' + state['namespace'] + region.id,
                    'rect':Rect(bounds.x+block.rect.x,bounds.y+block.rect.y,block.rect.w,block.rect.h),
                    'percent':25,'stage':'Detected','source_window':state.get('source_window')})
            if region.processed and getattr(region, 'confirmed_sources', ()) != (normalize(block.text),):
                region.processed = False
                region.changed = now
                region.revision += 1
                region.delivered.clear()
        state['seen_ids'] = {key for key, region in tracker.regions.items()
            if region.seen == now}
        return removed

    async def _scan_zone(self, index, bounds, hwnd, title, np, started, preview=None, core=None, multiple=None):
        if getattr(self, 'ocr_zone_tracking', False):
            return await self._scan_ocr_zone(index, bounds, hwnd, title, np, started,
                preview=preview, core=core, multiple=multiple)
        if multiple is None:
            multiple = len(self.settings.watch_areas) > 1
        state = self.zone_states.setdefault(index, {'preview': None, 'image': None, 'detected': [],
            'seen_ids': set(), 'last_alive': {},
            'tracker': self.tracker if index == 0 else RegionTracker()})
        tracker = state['tracker']
        namespace = f'{index}-' if multiple else ''
        state['namespace'] = namespace
        if preview is None:
            preview = self.preview_capture.capture(bounds)
        # A few isolated pixels in recorded/streamed video are compression
        # noise, not a changed word. Scale the floor to preview size so small
        # fullscreen tiles still react to compact UI text.
        changed_pixels = max(8, min(64, preview.shape[0] * preview.shape[1] // 900))
        changed = state['preview'] is None or np.count_nonzero(np.any(
            np.abs(preview.astype(np.int16) - state['preview']) > 12, axis=2)) >= changed_pixels
        if changed:
            state['preview'] = preview.astype(np.int16)
            previous_image = state['image']
            frame = self.capture.capture(bounds)
            # The capture service reuses its DIB; another zone may resize it.
            # CaptureService lends one reusable DIB. Retain our own baseline
            # even for a single zone: a later Quick Capture or source follow
            # would otherwise overwrite it and manufacture false changes.
            state['image'] = frame.copy()
            anchor_lost = []
            if self.settings.overlay.follow_content and self.anchors.items:
                anchor_lost = self._follow_sources(state['image'], bounds, namespace=namespace, tracker=tracker) or []
            found = self.detector.detect(state['image'], self.settings.sensitivity)
            if core is not None:
                found = [rect for rect in found if core.x <= bounds.x + rect.x + rect.w // 2 < core.right
                    and core.y <= bounds.y + rect.y + rect.h // 2 < core.bottom]
            state['detected'] = found
        image, detected = state['image'], state['detected']
        now = time.monotonic()
        if changed:
            removed = tracker.update(detected[:self.settings.max_regions], image, now,
                previous_image=previous_image)
            state['seen_ids'] = {key for key, region in tracker.regions.items() if region.seen == now}
        else:
            anchor_lost = []
            for key in state['seen_ids']:
                region = tracker.regions.get(key)
                if region:
                    region.seen = now
            removed = tracker.expire(now)
        for key in anchor_lost:
            group = key.removeprefix('watch-' + namespace).split(':', 1)[0]
            region = tracker.regions.get(group)
            if region is None or region.seen != now:
                # A scrolled-out source has no text candidate at its former
                # position. Remove it promptly; a visual change still tracked
                # as the same region is left for OCR confirmation below.
                self.source_lost.emit(key)
        for key in removed:
            job_key = namespace + key
            state['last_alive'].pop(job_key, None)
            task = self.jobs.pop(job_key, None)
            if task:
                task.cancel()
            if key not in tracker.regions:
                self.removed.emit('watch-' + job_key)
            # A visual fingerprint changed, but the words may not have. Let
            # OCR confirm their identity before replacing the visible Arabic.
        # Keep only this zone's still-visible translations alive. Scrolling in
        # another zone never restarts OCR or expires a static sidebar overlay.
        if self.settings.overlay.persistence:
            interval = max(.5, min(2.0, self.settings.overlay.duration / 3))
            for region in tracker.regions.values():
                if not region.processed or not region.delivered or region.seen != now:
                    continue
                job_key = namespace + region.id
                if now - state['last_alive'].get(job_key, 0) < interval:
                    continue
                state['last_alive'][job_key] = now
                group = 'watch-' + job_key
                self.region_alive.emit(group)
        if now >= self.backoff:
            capacity = max(0, min(3, self.settings.max_regions) - len(self.jobs))
            stable = min(self.settings.stability_ms, 300) if multiple or self.settings.watch_areas else self.settings.stability_ms
            for region in tracker.ready(now, stable, self.settings.cooldown_ms, capacity):
                r = region.rect
                offset = Rect(max(0, r.x - 24), max(0, r.y - 64), 0, 0)
                offset = Rect(offset.x, offset.y,
                    min(image.shape[1], r.right + 24) - offset.x,
                    min(image.shape[0], r.bottom + 100) - offset.y)
                crop = image[offset.y:offset.bottom, offset.x:offset.right].copy()
                region.processed, region.attempted = True, now
                avoid = [Rect(bounds.x + b.x, bounds.y + b.y, b.w, b.h) for b in detected if b.overlap(r) < .55]
                job_key = namespace + region.id
                task = asyncio.create_task(self._region(region, crop, bounds, title, self.generation,
                    avoid, offset, window_identity(hwnd), tracker, namespace))
                self.jobs[job_key] = task
                task.add_done_callback(lambda completed, key=job_key: self.jobs.pop(key, None) if self.jobs.get(key) is completed else None)
        if self.settings.debug:
            self.diagnostics.emit({'regions': [(namespace + r.id,
                Rect(bounds.x+r.rect.x, bounds.y+r.rect.y, r.rect.w, r.rect.h), r.revision)
                for r in tracker.regions.values()], 'scan_ms': round((time.monotonic()-started)*1000)})

    async def _region(self, region, image, bounds, title, generation, avoid=None, capture_rect=None, source_window=None, tracker=None, namespace='', precomputed=None):
        tracker = tracker or self.tracker
        revision = region.revision
        offset = capture_rect or region.rect
        try:
            if source_window and (not source_window_current(source_window) or self.app_blocks.blocked(source_window[0])):
                return
            if precomputed is None:
                async with self.ocr_lock:
                    blocks = await self._get_ocr().read(image)
                    protected = list(self.ocr.last_lines)
            else:
                blocks = precomputed
                protected = []
            local_source = Rect(region.rect.x - offset.x, region.rect.y - offset.y, region.rect.w, region.rect.h)
            blocks = [b for b in blocks if belongs_to_region(b, local_source)]
            from .text import normalize
            sources = tuple(normalize(block.text[:6000]) for block in blocks)
            physical_boxes = tuple(Rect(bounds.x + offset.x + block.rect.x,
                bounds.y + offset.y + block.rect.y, block.rect.w, block.rect.h) for block in blocks)
            confirmed = getattr(region, 'confirmed_sources', ())
            if confirmed == sources and confirmed:
                # A click, hover, animation or compression artifact changed
                # pixels, yet OCR still reads the same words. Preserve the
                # existing translations and their IDs instead of flickering.
                for index, (old, new) in enumerate(zip(getattr(region, 'confirmed_boxes', ()), physical_boxes)):
                    if old != new:
                        result_id = 'watch-' + namespace + region.id + (':' + str(index) if index else '')
                        self.source_moved.emit(result_id, new)
                        anchor = self.anchors.items.get(result_id)
                        if anchor:
                            anchor.rect = new
                region.confirmed_boxes = physical_boxes
                region.delivered.update(getattr(region, 'confirmed_delivered', set()))
                if len(region.delivered) >= len(blocks):
                    return
            elif confirmed:
                self.removed.emit('watch-' + namespace + region.id)
                region.confirmed_delivered = set()
            region.confirmed_sources = sources
            region.confirmed_boxes = physical_boxes
            if not blocks:
                return
            # Translate spatial paragraphs/labels independently. Cache hits go
            # first, so an unavailable provider cannot delay known game text.
            indexed = list(enumerate(blocks))
            indexed.sort(key=lambda pair: not bool(self.store.get(pair[1].text)))
            for index, block in indexed:
                source, box = block.text[:6000], block.rect
                key = normalize(source)
                delivery_key = (index, key)
                if delivery_key in region.delivered:
                    continue
                if generation != self.generation or (source_window and (not source_window_current(source_window) or self.app_blocks.blocked(source_window[0]))):
                    return
                start = time.monotonic()
                result_id = 'watch-' + namespace + region.id + (':' + str(index) if index else '')
                physical = Rect(bounds.x + offset.x + box.x, bounds.y + offset.y + box.y, box.w, box.h)
                arabic, cached = await Engine._translate_progress(self, source, result_id, physical, source_window)
                if generation != self.generation or tracker.regions.get(region.id) is not region or region.revision != revision or not source_window_current(source_window) or (source_window and self.app_blocks.blocked(source_window[0])):
                    return
                physical = Rect(bounds.x + offset.x + box.x, bounds.y + offset.y + box.y, box.w, box.h)
                self.store.record(source, arabic, title)
                result_id = 'watch-' + namespace + region.id + (':' + str(index) if index else '')
                result = Translation(result_id, source, arabic, physical, title, cached, round((time.monotonic() - start) * 1000))
                result.source_window = source_window
                if block.container:
                    c = block.container
                    result.container = Rect(bounds.x + offset.x + c.x, bounds.y + offset.y + c.y, c.w, c.h)
                result.avoid_regions = list(avoid or []) + [Rect(bounds.x + offset.x + b.rect.x - 8,
                    bounds.y + offset.y + b.rect.y - 8, b.rect.w + 16, b.rect.h + 16)
                    for b in protected if b.rect.overlap(box) < .1]
                if self.settings.overlay.match_game:
                    from .appearance import sample_cell_style
                    result.style_hint = sample_cell_style(image, block)
                region.delivered.add(delivery_key)
                region.confirmed_delivered = set(region.delivered)
                self.translated.emit(result)
                if self.settings.overlay.follow_content:
                    self.anchors.add(result, image, box, float('inf'), capture_bounds=bounds)
                if self.settings.debug:
                    self.diagnostics.emit({'text': source, 'normalized': key, 'confidence': 'not provided by Windows OCR',
                        'cached': cached, 'latency_ms': result.latency_ms, 'id': result.id})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._report(exc)
            # A single untranslatable name must not stop every other region.
            if isinstance(exc, TranslationError) and exc.code == 'rate_limit':
                self.backoff = time.monotonic() + 30
            region.attempted = time.monotonic() + 2
            Engine._progress(self, 'watch-' + namespace + region.id,
                Rect(bounds.x+region.rect.x,bounds.y+region.rect.y,region.rect.w,region.rect.h),50,'Retrying',source_window)
            region.processed = False

    def translate_region(self, rect, title="", source_window=None):
        self._submit(self._manual_start(rect, title, source_window))

    async def _manual_start(self, rect, title, source_window=None):
        self.removed.emit('manual')
        for key in list(self.anchors.items):
            if key.startswith('manual'):
                self.anchors.items.pop(key, None)
        if self.anchor_watcher:
            self.anchor_watcher.cancel()
            self.anchor_watcher = None
        # A Quick Capture is independent of Watch. In particular it must not
        # change Watch's context tuple, clear a zone tracker or cancel its jobs;
        # doing so made the newly translated manual overlay vanish on the next
        # Watch tick and needlessly reprocessed every selected area.
        if self.manual:
            self.manual.cancel()
            await asyncio.gather(self.manual, return_exceptions=True)
        self.manual = asyncio.create_task(self._manual_translate(rect, title, source_window))

    async def _manual_translate(self, rect, title, source_window=None):
        try:
            if not source_window_current(source_window):
                return
            self.status.emit("reading")
            image = self.capture.capture(rect).copy()
            async with self.ocr_lock:
                blocks = await self._get_ocr().read(image, manual=True)
            if not blocks:
                self.status.emit("no_text")
                self.manual_failed.emit("no_text", rect, source_window)
                return
            tracked_keys = set()
            for index, block in enumerate(blocks):
                box = block.rect
                key = 'manual' if index == 0 else f'manual:{index}'
                Engine._progress(self,key,Rect(rect.x+box.x,rect.y+box.y,box.w,box.h),25,'Detected',source_window)
            if self.settings.overlay.follow_content:
                for index, block in enumerate(blocks):
                    box = block.rect
                    key = 'manual' if index == 0 else f'manual:{index}'
                    placeholder = Translation(key, block.text, '', Rect(rect.x+box.x,rect.y+box.y,box.w,box.h),source_window=source_window)
                    self.anchors.add(placeholder, image, box, float('inf'), capture_bounds=rect)
                    if key in self.anchors.items:
                        tracked_keys.add(key)
                if self.anchors.items:
                    self.anchor_watcher = asyncio.create_task(self._anchor_loop())
            self.status.emit("translating")
            failures = []
            for index, block in enumerate(blocks):
                source = block.text[:6000]
                started = time.monotonic()
                key = 'manual' if index == 0 else f'manual:{index}'
                box = block.rect
                physical = Rect(rect.x+box.x,rect.y+box.y,box.w,box.h)
                try:
                    arabic, cached = await Engine._translate_progress(self,source,key,physical,source_window)
                except TranslationError as exc:
                    self._report(exc)
                    failures.append(exc.code)
                    Engine._progress(self,key,physical,50,'Unavailable',source_window)
                    continue
                if not source_window_current(source_window):
                    return
                self.store.record(source, arabic, title)
                box = block.rect
                physical = Rect(rect.x + box.x, rect.y + box.y, box.w, box.h)
                key = 'manual' if index == 0 else f'manual:{index}'
                if key in tracked_keys:
                    anchor = self.anchors.items.get(key)
                    if anchor is None:
                        continue  # Source changed/scrolled out while translation ran.
                    physical = anchor.rect
                result = Translation(key, source, arabic, physical, title, cached, round((time.monotonic() - started) * 1000))
                result.source_window = source_window
                if self.settings.overlay.match_game:
                    from .appearance import sample_cell_style
                    result.style_hint = sample_cell_style(image, block)
                self.translated.emit(result)
            self.status.emit("ready")
            if len(failures) == len(blocks):
                self.manual_failed.emit(failures[0],rect,source_window)
            if self.anchors.items and (self.anchor_watcher is None or self.anchor_watcher.done()):
                self.anchor_watcher = asyncio.create_task(self._anchor_loop())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._report(exc)

            code = exc.code if isinstance(exc, TranslationError) else ("ocr_language" if str(exc) == "ocr_language" else "capture_failed")
            self.manual_failed.emit(code, rect, source_window)

    def hide(self):
        self._submit(self._hide())

    def invalidate_source(self):
        self._submit(self._invalidate_source())

    async def _invalidate_source(self):
        await self._hide()
        self.tracker.clear()
        self.zone_states.clear()
        self.context = None

    async def _hide(self):
        self.anchors.clear()
        if self.anchor_watcher:
            self.anchor_watcher.cancel()
        self.generation += 1
        self._cancel_jobs()
        if self.manual:
            self.manual.cancel()
        self.cleared.emit()

    def forget_anchor(self, key):
        async def forget():
            self.anchors.items.pop(key, None)
        self._submit(forget())

    def _follow_sources(self, image, bounds, namespace='', tracker=None, keys=None):
        tracker = tracker or self.tracker
        if keys is None:
            keys = {key for key in self.anchors.items if key.startswith('watch-' + namespace)}
        moved, lost = self.anchors.update(image, bounds, keys=keys)
        shifted = set()
        for key, old, new in moved:
            self.source_moved.emit(key, new)
            if key.startswith('watch-'):
                group = key[6:].split(':')[0]
                if namespace and group.startswith(namespace):
                    group = group[len(namespace):]
                region = tracker.regions.get(group)
                if region and group not in shifted:
                    r = region.rect
                    region.rect = Rect(r.x + new.x - old.x, r.y + new.y - old.y, r.w, r.h)
                    shifted.add(group)
        for key in lost:
            if not key.startswith('watch-'):
                self.source_lost.emit(key)
            # A hover/click can change the pixels under a Watch anchor without
            # changing its English. The region's OCR/tracker decides whether to
            # replace or retire that overlay; never remove it on pixels alone.
        return [key for key in lost if key.startswith('watch-')]

    async def _follow_manual_sources(self, image, bounds):
        """Confirm a missing Quick source with OCR before removing its Arabic.

        Cursor hover, focus and pressed-button colours can all change pixels
        without changing a word. Only suspicious patches enter this OCR path;
        unchanged captures and successfully followed scrolling use no OCR.
        """
        from .text import normalize
        keys = {key for key in self.anchors.items if key.startswith('manual')}
        originals = {key: self.anchors.items[key] for key in keys}
        moved, lost = self.anchors.update(image, bounds, keys=keys)
        for key, _, rect in moved:
            self.source_moved.emit(key, rect)
        for key in lost:
            anchor = originals[key]
            relative = Rect(anchor.rect.x - bounds.x, anchor.rect.y - bounds.y,
                anchor.rect.w, anchor.rect.h)
            probe = Rect(relative.x - 12, relative.y - 12,
                relative.w + 24, relative.h + 24).intersect(
                    Rect(0, 0, image.shape[1], image.shape[0]))
            same_text = False
            if anchor.source_text and probe.w >= 12 and probe.h >= 8:
                try:
                    async with self.ocr_lock:
                        blocks = await self._get_ocr().read(
                            image[probe.y:probe.bottom, probe.x:probe.right], manual=True)
                    same_text = any(normalize(block.text) == normalize(anchor.source_text)
                        for block in blocks)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # A transient OCR failure is not proof that text vanished.
                    same_text = True
            if same_text:
                result = Translation(key, anchor.source_text, '', anchor.rect,
                    source_window=anchor.source_window)
                self.anchors.add(result, image, relative, float('inf'), capture_bounds=bounds)
            else:
                self.source_lost.emit(key)

    async def _anchor_loop(self):
        previous = None
        try:
            while any(key.startswith('manual') for key in self.anchors.items):
                await asyncio.sleep(max(.25, self.settings.scan_ms / 1000))
                if not self.settings.overlay.follow_content:
                    for key in list(self.anchors.items):
                        if key.startswith('manual'):
                            self.anchors.items.pop(key, None)
                    break
                anchor = next((item for key, item in self.anchors.items.items()
                    if key.startswith('manual')), None)
                if anchor is None:
                    break
                if not source_window_current(anchor.source_window):
                    for key in list(self.anchors.items):
                        if key.startswith('manual'):
                            self.source_lost.emit(key)
                            self.anchors.items.pop(key, None)
                    break
                bounds = anchor.source_window[2] if anchor.source_window else anchor.capture_bounds
                if bounds is None:
                    key = next(key for key, item in self.anchors.items.items() if item is anchor)
                    self.anchors.items.pop(key, None)
                    self.source_lost.emit(key)
                    break
                preview = self.preview_capture.capture(bounds)
                import numpy as np
                if previous is None or np.count_nonzero(np.any(
                        np.abs(preview.astype(np.int16) - previous) > 12, axis=2)) >= 3:
                    previous = preview.astype(np.int16)
                    await self._follow_manual_sources(self.capture.capture(bounds).copy(), bounds)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed tracker must not leave stale translations pasted on top.
            for key in list(self.anchors.items):
                if key.startswith('manual'):
                    self.source_lost.emit(key)
                    self.anchors.items.pop(key, None)

    def test_provider(self, text=None):
        self._submit(self._test(text))

    async def _test(self, text=None):
        try:
            result = (await self.translator.translate(text))[0] if text else await self.provider.translate("You need to find the key before sunset.")
            self.tested.emit(True, result)
        except Exception as exc:
            code = exc.code if isinstance(exc, TranslationError) else "translation_failed"
            self.tested.emit(False, code)

    def _report(self, exc):
        code = exc.code if isinstance(exc, TranslationError) else ("ocr_language" if str(exc) == "ocr_language" else "capture_failed")
        # Log types/codes only: never API bodies, credentials, URLs, or screen text.
        log.warning("Processing failure: %s (%s)", code, type(exc).__name__)
        self.status.emit(code)

    def close(self):
        async def shutdown():
            await self._set_watch(False)
            if self.manual:
                self.manual.cancel()
                await asyncio.gather(self.manual, return_exceptions=True)
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await self.provider.close()
        try:
            self._submit(shutdown()).result(timeout=5)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(5)
