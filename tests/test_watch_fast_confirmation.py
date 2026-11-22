import asyncio
from types import SimpleNamespace

import numpy as np

from arabic_lens.engine import Engine, same_bright_strokes
from arabic_lens.models import Rect, TextBlock


def test_pale_tooltip_strokes_survive_background_motion_but_not_replacement():
    reference = np.full((12, 70), 38, dtype=np.uint8)
    changed = np.full_like(reference, 81)
    reference[2:10, 4:65:5] = changed[2:10, 4:65:5] = 240
    assert same_bright_strokes(reference, changed)
    changed[2:10, 49:65] = 81
    changed[2:10, 50:65:5] = 240
    assert not same_bright_strokes(reference, changed)
    assert not same_bright_strokes(reference, np.full_like(reference, 65))


def test_compound_label_can_start_early_on_a_bounded_card():
    rect = Rect(30, 24, 90, 16)
    text = 'Iron Pickaxe'
    segment = SimpleNamespace(text=text, rect=rect, block=TextBlock(text, rect, standalone=True))
    frame = np.full((80, 160, 3), 38, dtype=np.uint8)
    frame[26:38, 32:118:4] = 235
    assert not Engine._early_watch_text(segment, frame, False, .4)
    frame[:17] = 120
    frame[47:] = 120
    assert Engine._early_watch_text(segment, frame, False, .4)


def test_fast_watch_accepts_an_intact_scrolled_row_and_rejects_a_replacement():
    bounds = Rect(100, 100, 32, 24)
    source = Rect(4, 3, 20, 4)
    pixels = np.random.default_rng(4).integers(0, 255, (8, bounds.w), dtype=np.uint8)
    frame = np.zeros((bounds.h, bounds.w, 4), dtype=np.uint8)
    frame[10:18, :, :3] = pixels[..., None]
    engine = SimpleNamespace(capture=SimpleNamespace(capture=lambda _: frame),
                             _masked=lambda image, _: (image, ()))
    evidence = (source, 1, pixels)
    result = Engine._confirm_watch_row(engine, {}, bounds, evidence)
    assert result[0] == Rect(source.x, source.y + 9, source.w, source.h)

    frame[12, 8, :3] ^= 255
    assert Engine._confirm_watch_row(engine, {}, bounds, evidence) is None


def test_fresh_ocr_accepts_matching_subtitle_words_and_rejects_another_line():
    bounds = Rect(10, 20, 400, 90)
    frame = np.zeros((bounds.h, bounds.w, 4), dtype=np.uint8)
    box = Rect(50, 30, 240, 20)
    words = "I had Claude measure a cartoon channel"
    segment = SimpleNamespace(rect=box, block=TextBlock(words, box))
    observed = [TextBlock(words, Rect(50, 16, 240, 20))]

    async def read(image):
        assert image.shape[0] < bounds.h
        return observed

    async def check():
        engine = SimpleNamespace(capture=SimpleNamespace(capture=lambda _: frame),
                                 _masked=lambda image, _: (image, ()), ocr_lock=asyncio.Lock(),
                                 _get_ocr=lambda: SimpleNamespace(read=read))
        verified = await Engine._confirm_watch_text(engine, {}, bounds, segment, words)
        assert verified[0] == box
        observed[0].text = "Then the next subtitle appeared"
        assert await Engine._confirm_watch_text(engine, {}, bounds, segment, words) is None

    asyncio.run(check())


def test_windows_ocr_checks_consecutive_subtitles_on_changing_frames():
    import cv2
    from arabic_lens.config import Settings
    from arabic_lens.ocr import OcrService, WindowsOcrProvider
    from arabic_lens.text import TextFilterService, normalize

    bounds = Rect(0, 0, 680, 100)
    captions = ("The story starts here", "We need to catch the train", "Meet me outside the station")

    def subtitle(text, shade):
        frame = np.full((bounds.h, bounds.w, 4), shade, dtype=np.uint8)
        frame[:, :12, :3] = 180 - shade
        cv2.putText(frame, text, (35, 64), cv2.FONT_HERSHEY_SIMPLEX,
                    1.05, (255, 255, 255, 255), 2, cv2.LINE_AA)
        return frame

    async def check():
        ocr = OcrService(WindowsOcrProvider(), TextFilterService(Settings()))
        engine = SimpleNamespace(ocr_lock=asyncio.Lock(), _get_ocr=lambda: ocr,
                                 _masked=lambda frame, _: (frame, ()))
        for index, words in enumerate(captions):
            initial = subtitle(words, 26)
            blocks = await ocr.read(initial)
            block = next(block for block in blocks if normalize(block.text) == normalize(words))
            frame = subtitle(words, 75)
            engine.capture = SimpleNamespace(capture=lambda _: frame)
            pixels = cv2.cvtColor(initial, cv2.COLOR_BGRA2GRAY)
            assert Engine._find_watch_row(cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY),
                                          (block.rect, 0, pixels)) is None
            segment = SimpleNamespace(rect=block.rect, block=block)
            assert await Engine._confirm_watch_text(engine, {}, bounds, segment, words) is not None
            if index + 1 < len(captions):
                frame = subtitle(captions[index + 1], 64)
                assert await Engine._confirm_watch_text(engine, {}, bounds, segment, words) is None

    asyncio.run(check())
