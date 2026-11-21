import os
"""Watch-zone invariants using screen pixels, without desktop input hooks."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import arabic_lens.engine as engine_module

from arabic_lens.config import Settings
from arabic_lens.anchors import VisualAnchors
from arabic_lens.detection import RegionTracker
from arabic_lens.engine import Engine, dirty_capture_rects, whole_screen_tiles
from arabic_lens.models import Rect, TextBlock, Translation
from arabic_lens.text import normalize


class CroppedCapture:
    def __init__(self, desktop, preview=False):
        self.desktop = desktop
        self.preview = preview
        self.calls = []

    def capture(self, area):
        self.calls.append(area)
        pixels = self.desktop[area.y:area.bottom, area.x:area.right].copy()
        return cv2.resize(pixels, (320, 180)) if self.preview else pixels


class StubOcr:
    def __init__(self):
        self.calls = []
        self.last_lines = []

    async def read(self, image):
        self.calls.append(image.shape)
        if not np.any(image[:, :, :3] > 100):
            return []
        h, w = image.shape[:2]
        return [TextBlock('A readable English sentence.',
            Rect(8, 8, max(20, min(130, w - 16)), min(24, h - 8)))]


def fake_ocr_engine(desktop, settings):
    """A Watch engine with real scanning/scene code, stub OCR and no translation."""
    import types
    ocr = StubOcr()
    removed, moved = [], []
    fake = SimpleNamespace(settings=settings, fast_watch=False, zone_states={},
        preview_capture=CroppedCapture(desktop, True), capture=CroppedCapture(desktop),
        ocr=ocr, _get_ocr=lambda: ocr, ocr_lock=asyncio.Lock(),
        anchors=VisualAnchors(), jobs={}, backoff=float('inf'), generation=1,
        own_overlays=lambda: (), removed=SimpleNamespace(emit=removed.append),
        source_moved=SimpleNamespace(emit=lambda *args: moved.append(args)),
        diagnostics=SimpleNamespace(emit=lambda *args: None),
        progress=SimpleNamespace(emit=lambda *args: None))
    for name in ('_masked', '_follow_scene', '_read_scene', '_verify_read', '_schedule_scene',
                 '_retire_segment', '_cancel_segment', '_translate_segment', '_scan_ocr_zone'):
        setattr(fake, name, types.MethodType(getattr(Engine, name), fake))
    return fake, ocr, removed


def test_selected_zones_and_outside_changes_are_isolated(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(engine_module.time, 'monotonic', lambda: clock[0])
    desktop = np.zeros((220, 620, 4), dtype=np.uint8)
    nav = Rect(10, 10, 180, 180)
    feed = Rect(230, 10, 180, 180)
    desktop[30:65, 30:160, :3] = 240
    desktop[30:65, 250:380, :3] = 240
    settings = Settings(watch_areas=[[nav.x, nav.y, nav.w, nav.h],
        [feed.x, feed.y, feed.w, feed.h]])
    fake, ocr, removed = fake_ocr_engine(desktop, settings)

    async def scan_both():
        await fake._scan_ocr_zone(0, nav, 1, 'X', np, 0, multiple=True)
        await fake._scan_ocr_zone(1, feed, 1, 'X', np, 0, multiple=True)

    async def exercise():
        await scan_both()
        static = fake.zone_states[0]['scene'].segments['watch-0-1']
        static.shown_key = static.key  # Its Arabic is on screen.
        clock[0] += .1
        desktop[30:95, 470:590, :3] = 240  # Entirely outside either zone.
        await scan_both()
        clock[0] += .1
        desktop[110:155, 260:385, :3] = 200  # Feed scroll/change only.
        await scan_both()
        clock[0] += .25
        await scan_both()  # Quiet tick reads only the dirty feed strip.
        return static

    static = asyncio.run(exercise())
    assert fake.preview_capture.calls == [nav, feed] * 4
    assert len(ocr.calls) == 3  # Each zone once, then only the changed feed.
    assert fake.zone_states[0]['scene'].segments['watch-0-1'] is static
    assert static.key == static.shown_key and not static.pending_key
    assert removed == []


def test_fullscreen_dirty_tile_does_not_touch_static_tile(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(engine_module.time, 'monotonic', lambda: clock[0])
    desktop = np.zeros((900, 1600, 4), dtype=np.uint8)
    desktop[80:120, 80:240, :3] = 240
    settings = Settings(watch_fullscreen=True)
    fake, ocr, removed = fake_ocr_engine(desktop, settings)
    bounds = Rect(0, 0, 1600, 900)

    async def scan_all():
        overview = fake.preview_capture.capture(bounds)
        for index, (core, padded, (x0, y0, x1, y1)) in enumerate(
                whole_screen_tiles(bounds, overview.shape)):
            await fake._scan_ocr_zone(index, padded, 1, 'X', np, 0,
                preview=overview[y0:y1, x0:x1], core=core, multiple=True)

    async def exercise():
        await scan_all()
        static = fake.zone_states[0]['scene'].segments['watch-0-1']
        static.shown_key = static.key
        initial_ocr = len(ocr.calls)
        clock[0] += .1
        desktop[760:840, 1350:1500, :3] = 240  # Other corner only.
        await scan_all()
        clock[0] += .25
        await scan_all()  # Debounced OCR of only the changed tile.
        return static, initial_ocr

    static, initial_ocr = asyncio.run(exercise())
    assert len(ocr.calls) == initial_ocr + 1
    assert fake.zone_states[0]['scene'].segments['watch-0-1'] is static
    assert static.key == static.shown_key
    assert removed == []


def test_click_visual_change_with_identical_words_does_not_remove_or_translate():
    from arabic_lens.scene import TextScene
    text = 'You need to find the key.'
    box = Rect(10, 10, 180, 30)
    pixels = np.zeros((80, 250, 4), dtype=np.uint8)
    pixels[15:35, 15:185:3, :3] = 240
    scene = TextScene('watch-')
    scene.reconcile([TextBlock(text, box)], [Rect(0, 0, 250, 80)], pixels, 0)
    segment = scene.segments['watch-1']
    segment.shown_key = segment.key
    clicked = pixels.copy()
    clicked[15:35, 15:185:3, :3] = 150  # Hover/pressed colour, same lettering.
    changes = scene.reconcile([TextBlock(text, box)], [Rect(0, 0, 250, 80)], clicked, 1)
    assert changes == ([], [], [], [], [])
    assert scene.segments['watch-1'] is segment
    assert scene.due(5, image=clicked) == []  # Nothing to retranslate.


def test_quick_capture_does_not_reset_active_watch_zones():
    anchor = object()
    tracker = RegionTracker()
    context = (False, (Rect(10, 10, 200, 100),))
    zone_states = {0: {'tracker': tracker, 'preview': object()}}
    async def manual_translate(*args):
        return None
    fake = SimpleNamespace(anchors=SimpleNamespace(items={'watch-1': anchor,
        'manual': object()}), anchor_watcher=None, generation=8,
        zone_states=zone_states, tracker=tracker, context=context, jobs={'watch-1': object()},
        manual=None, _manual_translate=manual_translate, removed=SimpleNamespace(emit=lambda key: None))

    async def exercise():
        await Engine._manual_start(fake, Rect(10, 10, 100, 40), 'X')
        await fake.manual

    asyncio.run(exercise())
    assert fake.generation == 8 and fake.context is context
    assert fake.zone_states is zone_states and fake.tracker is tracker
    assert fake.jobs == {'watch-1': fake.jobs['watch-1']}
    assert fake.anchors.items == {'watch-1': anchor}


def test_quick_without_window_identity_tracks_pixels_with_no_timer():
    image = np.zeros((90, 240, 4), dtype=np.uint8)
    image[20:45, 25:190:2, :3] = 240
    anchors = VisualAnchors()
    area = Rect(100, 100, 240, 90)
    result = Translation('manual', 'Visible English sentence', 'جملة عربية',
        Rect(125, 120, 165, 25), source_window=None)
    anchors.add(result, image, Rect(25, 20, 165, 25), float('inf'), capture_bounds=area)
    assert anchors.items['manual'].capture_bounds == area
    assert anchors.items['manual'].expires == float('inf')
    assert anchors.update(image, area, keys={'manual'}) == ([], [])


def test_manual_hover_or_click_keeps_same_words_until_ocr_confirms_loss():
    area = Rect(0, 0, 240, 90)
    image = np.zeros((90, 240, 4), dtype=np.uint8)
    image[20:45, 25:190:2, :3] = 240
    original = Translation('manual', 'A readable English sentence.', 'جملة عربية',
        Rect(25, 20, 165, 25), source_window=None)
    anchors = VisualAnchors()
    anchors.add(original, image, original.rect, float('inf'), capture_bounds=area)
    clicked = image.copy()
    clicked[20:45, 25:190:2, :3] = 130  # Hover/focus colour, same lettering.
    lost, moved = [], []
    class Ocr:
        answer = 'A readable English sentence.'
        async def read(self, crop, manual=False):
            return [TextBlock(self.answer, Rect(0, 0, 160, 25))]
    ocr = Ocr()
    fake = SimpleNamespace(anchors=anchors, ocr_lock=asyncio.Lock(),
        _get_ocr=lambda: ocr, source_lost=SimpleNamespace(emit=lost.append),
        source_moved=SimpleNamespace(emit=lambda *args: moved.append(args)))
    asyncio.run(Engine._follow_manual_sources(fake, clicked, area))
    assert not lost and 'manual' in anchors.items
    assert anchors.items['manual'].expires == float('inf')
    ocr.answer = 'Different words now appear.'
    replaced = image.copy()
    replaced[20:45, 25:190, :3] = 0  # The source lettering really disappeared.
    asyncio.run(Engine._follow_manual_sources(fake, replaced, area))
    assert lost == ['manual']


def test_continuous_scroll_debounces_ocr_and_does_not_queue_stale_frames(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(engine_module.time, 'monotonic', lambda: clock[0])
    desktop = np.zeros((220, 300, 4), dtype=np.uint8)
    desktop[25:50, 30:200, :3] = 240
    zone = Rect(0, 0, 300, 220)
    fake, ocr, _ = fake_ocr_engine(desktop, Settings(watch_areas=[[0, 0, 300, 220]]))

    async def exercise():
        await fake._scan_ocr_zone(0, zone, 1, 'X', np, 0)
        initial = len(ocr.calls)
        for step in range(6):  # 0.6 s of continuous motion
            clock[0] += .1
            desktop[90:180, 50:230, :3] = 0
            desktop[95 + step:115 + step, 50:230, :3] = 180
            await fake._scan_ocr_zone(0, zone, 1, 'X', np, 0)
        moving = len(ocr.calls)
        clock[0] += .25
        await fake._scan_ocr_zone(0, zone, 1, 'X', np, 0)
        quiet = len(ocr.calls)
        return initial, moving, quiet

    initial, moving, quiet = asyncio.run(exercise())
    assert initial == 1
    assert moving == initial  # No OCR backlog while frames keep moving.
    assert quiet == initial + 1  # The latest stable frame alone is read.


def test_continuous_change_still_reads_at_a_capped_cadence(monkeypatch):
    """Endless motion (video, fast chat) cannot starve text forever."""
    clock = [100.0]
    monkeypatch.setattr(engine_module.time, 'monotonic', lambda: clock[0])
    desktop = np.zeros((220, 300, 4), dtype=np.uint8)
    zone = Rect(0, 0, 300, 220)
    fake, ocr, _ = fake_ocr_engine(desktop, Settings(watch_areas=[[0, 0, 300, 220]]))

    async def exercise():
        for step in range(20):  # 2 s, a change every 100 ms
            desktop[:, :, :3] = 0
            desktop[20 + step * 4:45 + step * 4, 30:200, :3] = 220
            await fake._scan_ocr_zone(0, zone, 1, 'X', np, 0)
            clock[0] += .1
    asyncio.run(exercise())
    assert 2 <= len(ocr.calls) <= 5


def test_supplied_x_video_static_nav_and_scrolling_feed():
    video = Path(os.environ.get('ARABIC_LENS_WATCH_VIDEO', 'artifacts/fixtures/watch-scroll.mp4'))
    if not video.exists():
        pytest.skip('User-supplied scrolling recording is not available on this machine')
    capture = cv2.VideoCapture(str(video))
    try:
        frames = []
        for index in (45, 60):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            assert ok
            frames.append(frame)
    finally:
        capture.release()
    nav = Rect(110, 80, 240, 540)
    feed = Rect(380, 80, 600, 540)
    before_nav = cv2.resize(frames[0][nav.y:nav.bottom, nav.x:nav.right], (320, 180))
    after_nav = cv2.resize(frames[1][nav.y:nav.bottom, nav.x:nav.right], (320, 180))
    before_feed = cv2.resize(frames[0][feed.y:feed.bottom, feed.x:feed.right], (320, 180))
    after_feed = cv2.resize(frames[1][feed.y:feed.bottom, feed.x:feed.right], (320, 180))
    assert dirty_capture_rects(before_nav, after_nav, nav) == []
    assert dirty_capture_rects(before_feed, after_feed, feed)
