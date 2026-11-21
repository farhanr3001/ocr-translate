import asyncio
import logging
import threading
import time
import math
from dataclasses import replace
from PySide6.QtCore import QObject, Signal
from .windows import CaptureService, PreviewCaptureService, active_window, window_identity, source_window_current, window_at_rect
from .models import Rect, Translation
from .ocr import WindowsOcrProvider, OcrService
from .translation import HttpTranslationProvider, TranslationService, TranslationError
from .text import TextFilterService, belongs_to_region
from .detection import TextRegionDetector, RegionTracker
from .app_catalog import AppBlockService
from .anchors import VisualAnchors
from .scene import TextScene

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


def same_words(source, blocks):
    """Do OCR blocks still show `source`? Tolerates OCR noise (a caret read
    as a letter, punctuation) but not an edited or different sentence."""
    import re
    from .text import normalize
    from .scene import similarity
    key = normalize(source)
    if not key:
        return False
    compact = re.sub(r'[^a-z0-9]', '', key)
    candidates = [normalize(block.text) for block in blocks]
    if len(candidates) > 1:
        candidates.append(normalize(' '.join(block.text for block in blocks)))
    for text in candidates:
        if not text:
            continue
        letters = re.sub(r'[^a-z0-9]', '', text)
        if letters == compact or (len(compact) >= 8 and compact in letters):
            return True
        ratio = similarity(key, text)
        if ratio >= .94 or (len(key) >= 24 and ratio >= .9):
            return True
    return False


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


def typical_line_height(segment, segments):
    """One text size for a whole Watch area (or Quick selection).

    Every overlay in the area uses the same Arabic size. OCR boxes of one
    font read 12-16 px tall depending on their letters, and an inline emote
    can make a single line read taller, so the upper quartile of all lines
    in the area is used rather than any single line's measurement.
    """
    heights = sorted(s.line_height for s in segments) or [segment.line_height]
    return heights[min(len(heights) - 1, (len(heights) * 3) // 4)]


def readable_item(text):
    """Real on-screen text worth keeping clear of, not OCR noise from
    scenery (a single stray glyph, dashes, punctuation)."""
    import re
    return bool(re.search(r'[A-Za-z0-9]{2}', text))


def same_place_text(a_text, a_rect, b_text, b_rect):
    """Two units read the same words at the same place (OCR may differ by a
    letter or two, e.g. a tile edge cutting a glyph)."""
    from .text import normalize
    from .scene import text_related
    return a_rect.overlap(b_rect) >= .5 and text_related(normalize(a_text), normalize(b_text))


def reconcile_zone_blocks(engine, state, bounds, blocks):
    """Suppress only overlapping fragments; never touch disjoint watch areas.

    Fullscreen tiles overlap through their padding, and Watch areas may
    overlap. A block that is merely part of another unit's longer block is a
    duplicate; a shorter block held by another unit yields to the longer one.
    """
    kept = []
    for block in blocks:
        absolute = Rect(bounds.x+block.rect.x,bounds.y+block.rect.y,block.rect.w,block.rect.h)
        duplicate = False
        for other in getattr(engine,'zone_states',{}).values():
            if other is state or 'bounds' not in other or 'scene' not in other:
                continue
            other_bounds = other['bounds']
            for segment in list(other['scene'].segments.values()):
                old_rect = Rect(other_bounds.x+segment.rect.x,other_bounds.y+segment.rect.y,segment.rect.w,segment.rect.h)
                same = same_place_text(block.text, absolute, segment.text, old_rect)
                if contained_text(block.text,absolute,segment.text,old_rect) or (
                        same and len(block.text) <= len(segment.text) + 3):
                    duplicate = True
                    break
                if contained_text(segment.text,old_rect,block.text,absolute) or same:
                    engine._retire_segment(other, segment.id)
            if duplicate: break
        if not duplicate: kept.append(block)
    return kept


def line_strips(rects, bounds):
    """Widen changed crops to whole text lines across the unit's width.

    A keystroke changes a few pixels at the end of a line; OCR of only those
    pixels would read a fragment. Reading the full-width strip keeps the line
    (and its neighbours above/below, via the vertical margin) intact.
    """
    return [Rect(bounds.x, area.y, bounds.w, area.h).intersect(bounds) for area in rects]


def fill_own_overlays(image, bounds, rects):
    """Blank our own visible overlays out of a capture of `bounds`.

    Used only when Windows refuses capture exclusion. Returns the protected
    rectangles relative to `bounds` (full-resolution coordinates).
    """
    if not rects:
        return []
    h, w = image.shape[:2]
    scale_x, scale_y = w / max(1, bounds.w), h / max(1, bounds.h)
    fill = image.reshape(-1, image.shape[2]).mean(axis=0).astype(image.dtype)
    protected = []
    for rect in rects:
        inter = rect.intersect(bounds)
        if not inter.w or not inter.h:
            continue
        relative = Rect(inter.x - bounds.x, inter.y - bounds.y, inter.w, inter.h)
        protected.append(relative)
        x0, y0 = int(relative.x * scale_x), int(relative.y * scale_y)
        x1, y1 = math.ceil(relative.right * scale_x), math.ceil(relative.bottom * scale_y)
        image[max(0, y0):min(h, y1), max(0, x0):min(w, x1)] = fill
    return protected


class Engine(QObject):
    fast_watch = True
    fast_watch_removal = True
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
    watch_cleared = Signal()

    def __init__(self, settings, store):
        super().__init__()
        self.settings, self.store = settings, store
        self.app_blocks = AppBlockService(settings)
        # Physical rectangles of our overlays that screen capture can see
        # (only when Windows refuses capture exclusion). Set by the app.
        self.own_overlays = lambda: ()
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
        self.retire_probe = None
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

    def _drop_watch_anchors(self):
        for key in list(self.anchors.items):
            if key.startswith('watch-'):
                self.anchors.items.pop(key, None)

    async def _set_watch(self, enabled):
        # Quick Translate results are independent of Watch: toggling Watch
        # retires only Watch overlays and anchors.
        self._drop_watch_anchors()
        self.watch = enabled
        self.generation += 1
        if self.retire_probe:
            self.retire_probe.cancel()
            await asyncio.gather(self.retire_probe, return_exceptions=True)
            self.retire_probe = None
        if self.watcher:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)
            self.watcher = None
        self._cancel_jobs()
        self.tracker.clear()
        self.zone_states.clear()
        self.context = None
        self.watch_cleared.emit()
        self.watch_changed.emit(enabled)
        if enabled:
            self.watcher = asyncio.create_task(self._watch_loop())
            if self.fast_watch_removal:
                self.retire_probe = asyncio.create_task(self._probe_watch_sources())

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
                            for segment_id in list(state['scene'].segments) if 'scene' in state else []:
                                self.removed.emit(segment_id)
                        self.tracker.clear()
                        self.zone_states.clear()
                        self._drop_watch_anchors()
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
                    self.watch_cleared.emit()
                    self.context = identity
                    self._drop_watch_anchors()
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
                        owner = active[0]
                        if configured:
                            # A drawn area belongs to the window visible beneath
                            # it, not to whichever app has focus at the moment.
                            beneath = window_at_rect(bounds)
                            if beneath:
                                owner = beneath[0]
                        await self._scan_zone(index,bounds,owner,active[2],np,started,
                            preview=preview,core=core,multiple=multiple)
                fast_watch = self.fast_watch and self.settings.provider == 'Built-in offline' and self.settings.scan_ms == 500
                interval = 100 if fast_watch else min(self.settings.scan_ms, 250)
                await asyncio.sleep(max(.05, interval / 1000 - (time.monotonic() - started)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception('Watch loop stopped')
            self._report(exc)
            self.watch = False
            self._cancel_jobs()
            self.watch_cleared.emit()
            self.watch_changed.emit(False)

    def _masked(self, image, bounds):
        """Hide our own capture-visible overlays from a capture (rare fallback)."""
        rects = tuple(self.own_overlays() or ())
        if not rects:
            return image, []
        return image, fill_own_overlays(image, bounds, rects)

    async def _scan_ocr_zone(self, index, bounds, hwnd, title, np, started,
            preview=None, core=None, multiple=None):
        """Keep one Watch unit's on-screen text and Arabic overlays in sync.

        A cheap preview detects pixel changes. Changed areas, widened to whole
        lines, are OCR'd after a short quiet period (with a cadence cap during
        continuous change). Each read is reconciled into the unit's TextScene:
        grown/edited lines keep their overlay and are retranslated once their
        words settle, absorbed fragments and vanished text are retired at once.
        Unchanged units cost one preview per tick and never OCR again.
        """
        if multiple is None:
            multiple = len(self.settings.watch_areas) > 1
        namespace = f'{index}-' if multiple else ''
        state = self.zone_states.setdefault(index, {'preview': None, 'image': None,
            'scene': TextScene('watch-' + namespace)})
        scene = state['scene']
        state['namespace'] = namespace
        state['bounds'] = bounds
        state['core'] = core
        if preview is None:
            preview = self.preview_capture.capture(bounds)
        preview, _ = self._masked(preview.copy(), bounds)
        previous_preview = state['preview']
        changed_pixels = max(8, min(64, preview.shape[0] * preview.shape[1] // 900))
        changed = previous_preview is None or np.count_nonzero(np.any(
            np.abs(preview.astype(np.int16) - previous_preview) > 12, axis=2)) >= changed_pixels
        now = time.monotonic()
        first_frame = previous_preview is None
        if changed:
            state['preview'] = preview.astype(np.int16)
            state['verify_count'] = 0
            image = self.capture.capture(bounds).copy()
            image, state['protected'] = self._masked(image, bounds)
            state['image'] = image
            if self.settings.overlay.follow_content:
                self._follow_scene(state, image, bounds)
            tracked = [Rect(bounds.x + s.rect.x, bounds.y + s.rect.y, s.rect.w, s.rect.h)
                for s in scene.segments.values()]
            dirty = dirty_capture_rects(previous_preview, preview, bounds, core, tracked)
            if dirty:
                if not first_frame:
                    dirty = line_strips(dirty, bounds)
                state['pending_dirty'] = merge_dirty_rects(
                    state.get('pending_dirty', []) + dirty, bounds)
                state['last_change'] = now
        elif (not state.get('pending_dirty') and scene.segments
                and now - state.get('audit_at', now if first_frame else 0) >= 1.5):
            # Light audit: one full-resolution capture checks that every known
            # line still has the pixels it was read with. Small changes (a few
            # letters, a short word vanishing) can stay under the preview's
            # noise threshold; without this they would never be re-read.
            state['audit_at'] = now
            self._audit_scene(state, bounds, now)
        elif not state.get('pending_dirty') and state.get('verify_at') and now >= state['verify_at']:
            # The 320x180 change preview deliberately ignores a few pixels of
            # video noise, which also hides the final keystroke or two ("e.",
            # "?"). Re-check the lines just read at full resolution once the
            # area is quiet, and read them again if they really changed.
            state['verify_at'] = None
            self._verify_read(state, bounds, np, now)
        pending = state.get('pending_dirty', [])
        # During continuous change (typing, scrolling, video) OCR waits for a
        # short quiet period, with a cadence cap so text is never starved.
        read_now = bool(pending) and (first_frame
            or now - state.get('last_change', now) >= .16
            or now - state.get('last_ocr', now) >= .7)
        if read_now:
            state['audit_at'] = now
            await self._read_scene(state, bounds, core, np, now, hwnd)
        if now >= self.backoff:
            self._schedule_scene(state, bounds, title, hwnd, now)
        if self.settings.debug:
            self.diagnostics.emit({'regions': [(s.id,
                Rect(bounds.x+s.rect.x, bounds.y+s.rect.y, s.rect.w, s.rect.h), s.key[:12])
                for s in scene.segments.values()],
                'scan_ms': round((time.monotonic() - started)*1000)})

    def _audit_scene(self, state, bounds, now):
        from .scene import _gray, blank, crop, locate
        scene = state['scene']
        image = self.capture.capture(bounds).copy()
        image, protected = self._masked(image, bounds)
        stale = []
        for segment in scene.segments.values():
            if segment.pixels is None:
                continue
            if any(segment.rect.intersect(p).w * segment.rect.intersect(p).h >= segment.rect.w * segment.rect.h * .5
                   for p in protected):
                continue
            current = _gray(crop(image, segment.rect))
            if current is not None and not blank(current) and VisualAnchors.identical(current, segment.pixels):
                continue
            if locate(segment, image) is not None:
                continue  # Same words, moved: anchors/next read handle it.
            stale.append(Rect(bounds.x, bounds.y + segment.rect.y - 6, bounds.w, segment.rect.h + 12).intersect(bounds))
        state['audit_at'] = now
        if stale:
            state['image'] = image
            state['pending_dirty'] = merge_dirty_rects(state.get('pending_dirty', []) + stale, bounds)
            state['last_change'] = now - 1  # Quiet already: read on this tick.

    def _verify_read(self, state, bounds, np, now):
        image = state.get('image')
        strips = state.get('last_dirty') or []
        if image is None or not strips or state.get('verify_count', 0) >= 3:
            return
        changed = []
        for area in strips:
            absolute = Rect(bounds.x + area.x, bounds.y + area.y, area.w, area.h).intersect(bounds)
            if not absolute.w or not absolute.h:
                continue
            current = self.capture.capture(absolute).copy()
            current, _ = self._masked(current, absolute)
            before = image[absolute.y - bounds.y:absolute.bottom - bounds.y, absolute.x - bounds.x:absolute.right - bounds.x]
            if before.shape != current.shape:
                continue
            if np.count_nonzero(np.any(np.abs(current.astype(np.int16) - before.astype(np.int16)) > 24, axis=2)) > 4:
                image[absolute.y - bounds.y:absolute.bottom - bounds.y, absolute.x - bounds.x:absolute.right - bounds.x] = current
                changed.append(absolute)
        if changed:
            state['verify_count'] = state.get('verify_count', 0) + 1
            state['pending_dirty'] = merge_dirty_rects(changed, bounds)
            state['last_change'] = now - 1  # Already quiet: read on this tick.

    def _follow_scene(self, state, image, bounds):
        """Move overlays with scrolling text between OCR reads (no OCR)."""
        scene = state['scene']
        verified = state.get('verified_rows', {})
        if verified and not state.get('protected'):
            from .scene import _gray, crop
            gray = _gray(image)
            for identifier, evidence in list(verified.items()):
                segment = scene.segments.get(identifier)
                if segment is None or not segment.shown_key:
                    verified.pop(identifier, None)
                    continue
                moved = self._find_watch_row(gray, evidence)
                if moved is None:
                    rect, top, pixels = evidence
                    offset = rect.y - top
                    glyphs = pixels[offset:offset + rect.h, max(0, rect.x):rect.right]
                    on_screen = crop(gray, rect)
                    if on_screen is not None and VisualAnchors.identical(on_screen, glyphs):
                        continue
                    # This overlay was published against exact source pixels.
                    # Leave ordinary OCR reconciliation to recognize any edit.
                    segment.shown_key = segment.shown_source = ''
                    verified.pop(identifier, None)
                    self.anchors.items.pop(identifier, None)
                    self.removed.emit(identifier)
                elif moved != evidence[0]:
                    rect, top, pixels = evidence
                    verified[identifier] = (moved, top + moved.y - rect.y, pixels)
                    segment.rect = moved
                    self.source_moved.emit(identifier, Rect(
                        bounds.x + moved.x, bounds.y + moved.y, moved.w, moved.h))
        keys = {key for key in self.anchors.items if key in scene.segments and key not in verified}
        if not keys:
            return
        moved, _lost = self.anchors.update(image, bounds, keys=keys)
        # A lost anchor is not proof the words vanished (hover, caret, colour);
        # the next OCR read of that area decides.
        for key, old, new in moved:
            segment = scene.segments.get(key)
            if segment is None:
                continue
            segment.rect = Rect(new.x - bounds.x, new.y - bounds.y, segment.rect.w, segment.rect.h)
            self.source_moved.emit(key, new)

    async def _probe_watch_sources(self):
        """Confirm strong changes to visible text without waiting for OCR."""
        import numpy as np
        from .scene import _gray, crop, locate

        suspects = set()
        previews = {}
        cursor = 0
        while self.watch:
            await asyncio.sleep(.045)
            zones = [state for state in self.zone_states.values()
                     if state['bounds'].w * state['bounds'].h <= 1_000_000
                     and not state.get('protected')
                     and any(s.shown_key for s in state['scene'].segments.values())]
            if not zones:
                suspects.clear()
                previews.clear()
                continue
            live_scenes = {zone['scene'] for zone in zones}
            previews = {scene: image for scene, image in previews.items() if scene in live_scenes}
            state = zones[cursor % len(zones)]
            cursor += 1
            bounds, scene = state['bounds'], state['scene']
            previous = {item for item in suspects if item[0] is scene}
            suspects = {item for item in suspects
                        if item[0] is not scene and item[0] in live_scenes}
            try:
                preview = self.preview_capture.capture(bounds).copy()
                old_preview = previews.get(scene)
                previews[scene] = preview
                if old_preview is not None and not previous and np.array_equal(preview, old_preview):
                    continue
                frame, protected = self._masked(self.capture.capture(bounds).copy(), bounds)
            except OSError:
                continue
            if protected:
                continue
            gray = _gray(frame)
            for segment in list(scene.segments.values()):
                if not segment.shown_key or segment.shown_key != segment.key or segment.pixels is None:
                    continue
                current = crop(gray, segment.rect)
                evidence = state.get('verified_rows', {}).get(segment.id)
                original = segment.pixels
                if evidence:
                    source, y, row = evidence
                    offset = source.y - y
                    original = row[offset:offset + source.h, max(0, source.x):source.right]
                if current is None or current.shape != original.shape or not original.size:
                    continue
                if VisualAnchors.identical(current, original):
                    continue
                if np.mean(np.abs(current.astype(np.int16) - original) > 35) < .19:
                    continue
                if (evidence and self._find_watch_row(gray, evidence) is not None) or locate(segment, gray):
                    continue
                identity = (scene, segment.id, segment.shown_key)
                if identity not in previous:
                    suspects.add(identity)
                    continue
                self._retire_segment(state, segment.id)

    async def _read_scene(self, state, bounds, core, np, now, hwnd=None):
        """OCR the accumulated changed strips of one unit and reconcile."""
        from .text import normalize
        scene = state['scene']
        image = state['image']
        dirty = state.pop('pending_dirty', [])
        state['last_ocr'] = now
        state['last_dirty'] = [Rect(a.x - bounds.x, a.y - bounds.y, a.w, a.h) for a in dirty]
        state['verify_at'] = now + .4
        if image is None:
            return
        blocks, areas, seen_lines = [], [], []
        for area in dirty:
            ox, oy = area.x - bounds.x, area.y - bounds.y
            relative = Rect(ox, oy, area.w, area.h)
            areas.append(relative)
            crop_image = image[oy:oy + area.h, ox:ox + area.w]
            if not crop_image.size:
                continue
            # Blank strips contain no English and need no OCR.
            if int(np.max(crop_image[:, :, :3])) - int(np.min(crop_image[:, :, :3])) < 12:
                continue
            async with self.ocr_lock:
                recognized = await self._get_ocr().read(crop_image)
                # Every OCR'd item, including values deliberately left
                # untranslated ("85 / 100"), so overlays never cover them.
                seen_lines += [Rect(ox + l.rect.x, oy + l.rect.y, l.rect.w, l.rect.h)
                               for l in list(getattr(self.ocr, 'last_lines', [])) + list(getattr(self.ocr, 'last_values', []))
                               if not l.text or readable_item(l.text)]
            for block in recognized:
                moved = replace(block,
                    rect=Rect(ox + block.rect.x, oy + block.rect.y, block.rect.w, block.rect.h),
                    container=Rect(ox + block.container.x, oy + block.container.y,
                        block.container.w, block.container.h) if block.container else None)
                for attribute in ('_last_line', '_lines'):
                    if hasattr(block, attribute):
                        setattr(moved, attribute, getattr(block, attribute))
                moved._offset = (ox, oy)  # Line rectangles stay crop-relative.
                center_x = bounds.x + moved.rect.x + moved.rect.w // 2
                center_y = bounds.y + moved.rect.y + moved.rect.h // 2
                if core is not None and not (core.x <= center_x < core.right
                        and core.y <= center_y < core.bottom):
                    continue
                if any(normalize(old.text) == normalize(moved.text)
                        and old.rect.overlap(moved.rect) > .65 for old in blocks):
                    continue
                blocks.append(moved)
        state['ocr_lines'] = [r for r in state.get('ocr_lines', [])
            if not any(r.intersect(a).w * r.intersect(a).h >= r.w * r.h * .5 for a in areas)] + seen_lines
        blocks = reconcile_zone_blocks(self, state, bounds, blocks)
        blocks = scene.split_by_history(blocks)
        added, updated, moved_ids, removed, replaced = scene.reconcile(
            blocks, areas, image, now, protected=state.get('protected', ()))
        if self.fast_watch and self.settings.provider == 'Built-in offline' and self.settings.stability_ms == 400:
            from .scene import _gray, crop
            rows = state.setdefault('ocr_rows', {})
            for identifier in set(rows) - scene.segments.keys():
                rows.pop(identifier)
            for segment in scene.segments.values():
                if segment.confirmed != now:
                    continue
                rect = segment.rect
                top = max(0, rect.y - 2)
                row = _gray(crop(image, Rect(0, top, bounds.w, rect.h + 4)))
                if row is not None and row.nbytes <= 250_000:
                    rows[segment.id] = (segment.text, (rect, top, row.copy()))
        for segment_id in removed:
            self._retire_segment(state, segment_id, already_removed=True)
        for segment_id in replaced:
            # Entirely different words now: never leave the old Arabic on them.
            segment = scene.segments.get(segment_id)
            if segment is not None:
                self._cancel_segment(segment)
                segment.shown_key = segment.shown_source = ''
            self.anchors.items.pop(segment_id, None)
            self.removed.emit(segment_id)
        for segment_id in moved_ids:
            segment = scene.segments.get(segment_id)
            if segment is not None and segment.shown_key:
                rect = Rect(bounds.x + segment.rect.x, bounds.y + segment.rect.y, segment.rect.w, segment.rect.h)
                anchor = self.anchors.items.get(segment_id)
                if anchor:
                    anchor.rect = rect
                self.source_moved.emit(segment_id, rect)
        if self.settings.show_translation_boxes:
            source_window = window_identity(hwnd) if hwnd else None
            for segment_id in added + updated:
                segment = scene.segments.get(segment_id)
                if segment is not None and not segment.shown_key:
                    self.progress.emit({'id': segment_id, 'rect': Rect(bounds.x + segment.rect.x,
                        bounds.y + segment.rect.y, segment.rect.w, segment.rect.h),
                        'percent': 25, 'stage': 'Detected', 'source_window': source_window})
        # Compute complete, newly recognized lines while Watch confirms their
        # source. Edited/typewriter segments retain the usual settle policy.
        if (self.fast_watch and self.settings.provider == 'Built-in offline'
                and self.settings.stability_ms == 400 and time.monotonic() >= self.backoff):
            self._schedule_scene(state, bounds, title=self.context_title(hwnd), hwnd=hwnd,
                                 now=now, early_ids=set(added + replaced + (updated if self.fast_watch_removal else [])))

    def context_title(self, hwnd):
        active = active_window()
        return active[2] if active and active[0] == hwnd else ''

    def _cancel_segment(self, segment):
        task = self.jobs.pop(segment.id, None)
        if task:
            task.cancel()
        segment.pending_key = ''

    def _retire_segment(self, state, segment_id, already_removed=False):
        if not already_removed:
            state['scene'].remove(segment_id)
        task = self.jobs.pop(segment_id, None)
        if task:
            task.cancel()
        self.anchors.items.pop(segment_id, None)
        self.removed.emit(segment_id)

    def _schedule_scene(self, state, bounds, title, hwnd, now, early_ids=None):
        scene = state['scene']
        base = max(.2, min(.8, self.settings.stability_ms / 1000))
        capacity = max(0, min(12, self.settings.max_regions) - len(self.jobs))
        if not capacity or state.get('image') is None:
            return
        source_window = window_identity(hwnd) if hwnd else None
        if early_ids is None:
            ready = scene.due(now, base, capacity, image=state['image'])
        else:
            ready = [segment for segment in scene.segments.values()
                     if segment.id in early_ids and not segment.pending_key
                     and (not segment.shown_key or (self.fast_watch_removal
                         and segment.shown_key != segment.key
                         and not segment.shown_key.startswith(segment.key)
                         and not segment.key.startswith(segment.shown_key)))
                     and segment.retry_after <= now and segment.text.endswith(('.', '?', '!'))
                     and '\n' not in segment.text and len(segment.text.split()) >= 4][:capacity]
        for segment in ready:
            reference = state.get('ocr_rows', {}).get(segment.id)
            evidence = (reference[1] if reference and reference[0] == segment.text
                        and not state.get('protected') else None)
            if early_ids is not None and evidence is None:
                continue
            self._cancel_segment(segment)
            segment.pending_key = segment.key
            arguments = (state, segment, segment.key, segment.block, bounds, title,
                         self.generation, source_window, state['image'])
            coroutine = (self._translate_segment(*arguments, evidence=evidence, early=early_ids is not None) if evidence is not None
                         else self._translate_segment(*arguments))
            task = asyncio.create_task(coroutine)
            self.jobs[segment.id] = task
            task.add_done_callback(lambda completed, key=segment.id:
                self.jobs.pop(key, None) if self.jobs.get(key) is completed else None)

    async def _translate_segment(self, state, segment, key, block, bounds, title, generation,
            source_window, image, evidence=None, early=False):
        from .scene import similarity
        scene = state['scene']
        source = block.text[:6000]
        start = time.monotonic()
        physical = Rect(bounds.x + block.rect.x, bounds.y + block.rect.y, block.rect.w, block.rect.h)
        try:
            if source_window and (not source_window_current(source_window)
                    or self.app_blocks.blocked(source_window[0])):
                segment.pending_key = ''
                return
            arabic, cached = await Engine._translate_progress(self, source, segment.id, physical, source_window)
            if early:
                await asyncio.sleep(max(0, .10 - (time.monotonic() - start)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._report(exc)
            if segment.pending_key == key:
                segment.pending_key = ''
            if isinstance(exc, TranslationError) and exc.code == 'rate_limit':
                self.backoff = time.monotonic() + 30
            segment.failures += 1
            segment.retry_after = time.monotonic() + min(30, 2 * segment.failures)
            Engine._progress(self, segment.id, physical, 50, 'Retrying', source_window)
            return
        if segment.pending_key == key:
            segment.pending_key = ''
        segment.failures = 0
        if generation != self.generation or scene.segments.get(segment.id) is not segment:
            return
        if source_window and (not source_window_current(source_window)
                or self.app_blocks.blocked(source_window[0])):
            return
        if evidence is not None:
            if segment.text[:6000] != source:
                return
            confirmed = self._confirm_watch_row(state, bounds, evidence)
            if confirmed is None:
                return
            segment.rect, image = confirmed
            rect, top, pixels = evidence
            state.setdefault('verified_rows', {})[segment.id] = (
                segment.rect, top + segment.rect.y - rect.y, pixels)
        if segment.key != key:
            # The words moved on while translating (typing). Show this interim
            # result only when it is closer to what is on screen than what is
            # already shown; the newer words are scheduled separately.
            if similarity(key, segment.key) < .6:
                return
            if segment.shown_key and similarity(segment.shown_key, segment.key) >= similarity(key, segment.key):
                return
        self.store.record(source, arabic, title)
        rect = Rect(bounds.x + segment.rect.x, bounds.y + segment.rect.y, segment.rect.w, segment.rect.h)
        result = Translation(segment.id, source, arabic, rect, title, cached,
            round((time.monotonic() - start) * 1000))
        result.source_window = source_window
        # One font reads 12-16 px tall in OCR boxes depending on its letters;
        # use the typical height of similar lines so sizes match line to line.
        result.line_height = typical_line_height(segment, scene.segments.values())
        if block.container:
            c = block.container
            result.container = Rect(bounds.x + c.x, bounds.y + c.y, c.w, c.h)
        # Keep subtitles off neighbouring lines that are still being read.
        result.avoid_regions = [Rect(bounds.x + other.rect.x - 4, bounds.y + other.rect.y - 4,
            other.rect.w + 8, other.rect.h + 8) for other in scene.segments.values()
            if other is not segment and other.rect.overlap(segment.rect) < .1]
        result.avoid_regions += [Rect(bounds.x + r.x - 2, bounds.y + r.y - 2, r.w + 4, r.h + 4)
            for r in state.get('ocr_lines', []) if r.overlap(segment.rect) < .1]
        if self.settings.overlay.match_game:
            from .appearance import sample_cell_style
            result.style_hint = sample_cell_style(image, block)
        segment.shown_key, segment.shown_source = key, source
        self.translated.emit(result)
        if self.settings.overlay.follow_content:
            current = image if evidence is not None else state.get('image')
            if current is not None:
                self.anchors.add(result, current, segment.rect, float('inf'), capture_bounds=bounds)
        if self.settings.debug:
            self.diagnostics.emit({'text': source, 'normalized': key, 'confidence': 'not provided by Windows OCR',
                'cached': cached, 'latency_ms': result.latency_ms, 'id': result.id})

    def _confirm_watch_row(self, state, bounds, evidence):
        """Accept the exact OCR source, including a row that scrolled intact."""
        from .scene import _gray
        try:
            now = time.monotonic()
            observed, frame = state.get('confirm_frame', (0, None))
            if frame is None or now - observed > .018:
                frame, protected = self._masked(self.capture.capture(bounds).copy(), bounds)
                if protected:
                    return None
                state['confirm_frame'] = (now, frame)
        except OSError:
            return None
        moved = Engine._find_watch_row(_gray(frame), evidence)
        return (moved, frame) if moved is not None else None

    @staticmethod
    def _find_watch_row(gray, evidence):
        import cv2
        import numpy as np
        rect, top, pixels = evidence
        height = pixels.shape[0]
        y = top
        if not np.array_equal(gray[y:y + height], pixels):
            scores = cv2.matchTemplate(gray, pixels, cv2.TM_SQDIFF_NORMED)
            _, _, (_, y), _ = cv2.minMaxLoc(scores)
            if not np.array_equal(gray[y:y + height], pixels):
                return None
        return Rect(rect.x, rect.y + y - top, rect.w, rect.h)

    async def _scan_zone(self, index, bounds, hwnd, title, np, started, preview=None, core=None, multiple=None):
        return await self._scan_ocr_zone(index, bounds, hwnd, title, np, started,
            preview=preview, core=core, multiple=multiple)

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
                self.manual_failed.emit('selection_changed', rect, source_window)
                return
            self.status.emit("reading")
            image, _ = self._masked(self.capture.capture(rect).copy(), rect)
            async with self.ocr_lock:
                blocks = await self._get_ocr().read(image, manual=True)
                visible_lines = [Rect(rect.x + l.rect.x - 2, rect.y + l.rect.y - 2, l.rect.w + 4, l.rect.h + 4)
                                 for l in list(getattr(self.ocr, 'last_lines', [])) + list(getattr(self.ocr, 'last_values', []))]
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
                        # The tracker lost the text while translation ran. Only
                        # drop the result if the pixels truly changed; otherwise
                        # (tracker false alarm) show it where it was selected.
                        if not self._source_unchanged(rect, image, box):
                            self.manual_failed.emit('selection_changed', rect, source_window)
                            continue
                        # Still on screen: keep tracking it so it leaves with its text.
                        tracked = Translation(key, block.text, '', physical, source_window=source_window)
                        self.anchors.add(tracked, image, box, float('inf'), capture_bounds=rect)
                    else:
                        physical = anchor.rect
                result = Translation(key, source, arabic, physical, title, cached, round((time.monotonic() - started) * 1000))
                result.source_window = source_window
                from .scene import first_line_height
                heights = sorted(first_line_height(b) for b in blocks)
                result.line_height = heights[min(len(heights) - 1, (len(heights) * 3) // 4)]
                result.avoid_regions = [r for r in visible_lines if r.overlap(physical) < .1]
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

    def _source_unchanged(self, rect, image, box):
        """True when the selected text is still pixel-identical on screen."""
        try:
            import cv2
            now = self.capture.capture(rect).copy()
            def gray(img):
                crop = img[max(0, box.y):box.bottom, max(0, box.x):box.right]
                return cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY if crop.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
            return bool(VisualAnchors.identical(gray(now), gray(image)))
        except Exception:
            return False

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

    async def _follow_manual_sources(self, image, bounds, protected=()):
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
            covered = sum(relative.intersect(p).w * relative.intersect(p).h for p in protected)
            if covered >= relative.w * relative.h * .5:
                # Beneath our own capture-visible overlay: unknown, not gone.
                self.anchors.items[key] = anchor
                continue
            probe = Rect(relative.x - 12, relative.y - 12,
                relative.w + 24, relative.h + 24).intersect(
                    Rect(0, 0, image.shape[1], image.shape[0]))
            same_text = False
            if anchor.source_text and probe.w >= 12 and probe.h >= 8:
                try:
                    async with self.ocr_lock:
                        blocks = await self._get_ocr().read(
                            image[probe.y:probe.bottom, probe.x:probe.right], manual=True)
                    same_text = same_words(anchor.source_text, blocks)
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
                preview, _ = self._masked(self.preview_capture.capture(bounds).copy(), bounds)
                import numpy as np
                if previous is None or previous.shape != preview.shape or np.count_nonzero(np.any(
                        np.abs(preview.astype(np.int16) - previous) > 12, axis=2)) >= 3:
                    previous = preview.astype(np.int16)
                    image, protected = self._masked(self.capture.capture(bounds).copy(), bounds)
                    await self._follow_manual_sources(image, bounds, protected)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Quick source tracking failed')
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
