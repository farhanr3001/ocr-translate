import asyncio

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QApplication
from types import SimpleNamespace

from arabic_lens.config import Settings
from arabic_lens.engine import Engine, keep_unchanged_watch_lines
from arabic_lens.models import Rect, TextBlock, Translation, neighboring_line_pitch
from arabic_lens.numeric_ocr import reread_clock
from arabic_lens.ocr import OcrService, WindowsOcrProvider
from arabic_lens.scene import TextScene
from arabic_lens.text import TextFilterService, normalize
import arabic_lens.overlay as overlay


LINES = ("Hello, Nina, how are you today?", "What are you doing right now?", "The train leaves at 7:35.")


def test_watch_ignores_fragments_of_an_unchanged_neighbor():
    image = np.zeros((120, 400, 4), dtype=np.uint8)
    source = Rect(20, 20, 310, 29)
    image[20:49, 20:330:4, :3] = 255
    first = TextBlock(LINES[0].rstrip('?') + '.', source)
    scene = TextScene("watch-")
    scene.reconcile([first], [Rect(0, 0, 400, 120)], image, 0)
    segment = next(iter(scene.segments.values()))
    segment.shown_key = segment.key
    fragments = [TextBlock('Hello, Nina,', Rect(20, 21, 117, 25)),
                 TextBlock('how are you today.', Rect(145, 20, 182, 29)),
                 TextBlock(LINES[0].rstrip('?') + ',', Rect(20, 22, 310, 27))]
    next_line = TextBlock(LINES[1], Rect(20, 58, 280, 29))
    scan = fragments + [next_line]
    assert keep_unchanged_watch_lines(scene, scan, image, np) == [next_line, first]
    image[25, 35, :3] ^= 255
    assert keep_unchanged_watch_lines(scene, scan, image, np) == scan


def test_watch_keeps_a_known_line_below_a_replacement_in_progress():
    image = np.zeros((120, 500, 4), dtype=np.uint8)
    known = TextBlock('The package is ready to collect.', Rect(12, 70, 300, 25))
    scene = TextScene('watch-')
    areas = [Rect(0, 0, 500, 120)]
    scene.reconcile([known], areas, image, 0)
    key = next(iter(scene.segments))
    edit = TextBlock('They walked through the garden', Rect(12, 35, 305, 24))
    joined = TextBlock(edit.text + ' ' + known.text, edit.rect.union(known.rect))
    joined._lines = [edit, known]
    blocks = scene.split_by_history([joined])
    assert [block.text for block in blocks] == [edit.text, known.text]
    scene.reconcile(blocks, areas, image, 1)
    assert scene.segments[key].text == known.text


def test_watch_does_not_draw_an_overlapping_punctuation_variant():
    QApplication.instance() or QApplication([])
    manager = overlay.OverlayManager(Settings(), lambda _: None)
    first = Rect(20, 42, 140, 12)
    manager.windows['watch-1'] = SimpleNamespace(closing=False)
    manager.source_rects['watch-1'] = first
    manager.sources['watch-1'] = normalize('The hallway is quiet.')
    duplicate = Translation('watch-2', 'The hallway is quiet,', '', first)
    next_row = Translation('watch-3', 'The hallway is quiet,', '', Rect(20, 60, 140, 12))
    assert manager._duplicate_of(duplicate) == 'watch-1'
    assert manager._duplicate_of(next_row) is None


def test_watch_rechecks_a_small_line_when_verification_finds_more_text():
    async def run():
        bounds = Rect(40, 20, 300, 90)
        source = Rect(20, 18, 90, 9)
        before = np.zeros((90, 300, 4), dtype=np.uint8)
        after = before.copy()
        after[19:26, 111:125, :3] = 255

        async def read(image):
            return [TextBlock('The train leaves at 8:20.', Rect(20, 16, 106, 9))]

        instance = SimpleNamespace(ocr_lock=asyncio.Lock(),
            capture=SimpleNamespace(capture=lambda _: after),
            _masked=lambda image, _: (image, ()),
            _get_ocr=lambda: SimpleNamespace(read=read))
        state = {'image': before}
        segment = SimpleNamespace(rect=source, line_height=9)
        assert await Engine._confirm_watch_text(instance, state, bounds, segment, 'The train leaves at') is None
        assert state['pending_dirty'] == [Rect(40, 22, 300, 41)]
        assert np.array_equal(state['image'], after)

    asyncio.run(run())


@pytest.mark.parametrize('readings,expected', [
    (('8:20.', '8:20.'), '8:20.'),
    (('8:20.', '8:28.'), '8:2e.'),
    (('9:20.', '9:20.'), '8:2e.'),
])
def test_clock_digit_requires_matching_pixel_reads(readings, expected):
    class Provider:
        answers = iter(readings)

        async def recognize_text(self, image):
            return next(self.answers)

    frame = np.zeros((24, 90, 3), dtype=np.uint8)
    result = asyncio.run(reread_clock(Provider(), frame, Rect(10, 4, 38, 15), '8:2e.'))
    assert result == expected


@pytest.mark.parametrize('font,pixels,dark', [
    ('consola.ttf', 9, True), ('consola.ttf', 10, False),
    ('segoeui.ttf', 11, True), ('segoeui.ttf', 12, False),
    ('consola.ttf', 16, True), ('segoeui.ttf', 24, False),
])
def test_windows_ocr_keeps_adjacent_rows_separate(font, pixels, dark):
    image = Image.new('RGB', (770, 160), (36,) * 3 if dark else (246,) * 3)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('C:/Windows/Fonts/' + font, pixels)
    for index, text in enumerate(LINES):
        draw.text((14, 10 + index * round(pixels * 1.2)), text, font=font,
                  fill=(240,) * 3 if dark else (21,) * 3)
    frame = np.asarray(image)[:, :, ::-1].copy()
    ocr = OcrService(WindowsOcrProvider(), TextFilterService(Settings()))

    async def read():
        for manual in (True, False):
            blocks = await ocr.read(frame, manual=manual)
            assert [normalize(block.text) for block in blocks] == [normalize(line) for line in LINES]
            assert all(a.rect.bottom <= b.rect.y for a, b in zip(blocks, blocks[1:]))

    asyncio.run(read())


@pytest.mark.parametrize('glyph_height,pitch', [(8, 10), (10, 12), (14, 17), (20, 24), (26, 32)])
def test_replace_fits_a_previous_overlay_when_the_next_line_arrives(monkeypatch, glyph_height, pitch):
    app = QApplication.instance() or QApplication([])
    screen = app.primaryScreen()
    monkeypatch.setattr(overlay, 'physical_to_logical', lambda rect: (screen, rect))
    monkeypatch.setattr(overlay, 'exclude_capture', lambda _: True)
    settings = Settings()
    settings.overlay.fade_ms = 0
    manager = overlay.OverlayManager(settings, lambda _: None)
    start = screen.availableGeometry().topLeft()
    first = Rect(start.x() + 80, start.y() + 120, 190, glyph_height)
    second = Rect(first.x, first.y + pitch, 155, glyph_height)
    try:
        manager.show(Translation('watch-1', LINES[0], 'مرحبًا يا نينا، كيف حالك اليوم؟', first,
                                 line_height=glyph_height))
        original = manager.windows['watch-1']
        manager.show(Translation('watch-2', LINES[1], 'ماذا تفعلين الآن؟', second,
                                 line_height=glyph_height,
                                 line_pitch=neighboring_line_pitch(second, (first,))))
        longer = manager.windows['watch-2']
        assert manager.windows['watch-1'] is original
        assert original.geometry().contains(first.x, first.y)
        assert original.geometry().contains(first.right - 1, first.bottom - 1)
        assert longer.y() == second.y
        assert original.geometry().bottom() < longer.y()
    finally:
        manager.clear(immediate=True)
