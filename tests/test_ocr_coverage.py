import asyncio
from pathlib import Path

import cv2
import numpy as np
import pytest

from arabic_lens.config import Settings
from arabic_lens.detection import TextRegionDetector
from arabic_lens.models import Rect, TextBlock
from arabic_lens.ocr import OcrService
from arabic_lens.text import TextFilterService


def test_dense_changed_crop_does_not_drop_everything_after_tenth_text_region():
    image = np.zeros((1100, 900, 3), dtype=np.uint8)
    for index in range(16):
        cv2.putText(image, f'Sentence {index:02d}', (40, 40 + index * 65),
                    cv2.FONT_HERSHEY_SIMPLEX, .85, (255, 255, 255), 2)
    regions = TextRegionDetector().detect(image)
    assert len(regions) >= 16
    assert any(region.y > 900 for region in regions)


def test_watch_accepts_sentence_with_unknown_game_names_but_still_ignores_ui_labels():
    text_filter = TextFilterService(Settings())
    story = TextBlock('Zorvia Calden Yuvellian required Bonethread for the gauntlet.',
                      Rect(10, 10, 530, 28))
    assert text_filter.reason(story) == ''
    assert text_filter.reason(TextBlock('Continue!', Rect(10, 60, 100, 28))) == 'simple UI label'
    assert text_filter.reason(TextBlock('Continue through the tunnel.', Rect(10, 90, 300, 28))) == ''


def test_manual_retry_adds_missing_spatial_line_without_duplicate_overlay():
    class Provider:
        def __init__(self):
            self.calls = 0

        async def recognize(self, image):
            self.calls += 1
            if self.calls == 1:
                return [TextBlock('The first paragraph.', Rect(15, 20, 240, 22))]
            # Enhanced pass coordinates are twice source coordinates.
            return [TextBlock('The first paragraph.', Rect(30, 40, 480, 44)),
                    TextBlock('The second paragraph has 73 hours.', Rect(30, 200, 706, 44))]

    provider = Provider()
    service = OcrService(provider, TextFilterService(Settings()))
    image = np.full((250, 650, 3), 245, dtype=np.uint8)
    blocks = asyncio.run(service.read(image, manual=True))
    assert provider.calls == 2
    assert [block.text for block in blocks] == [
        'The first paragraph.', 'The second paragraph has 73 hours.']
    assert blocks[1].rect.y == 100
    assert len(service.last_lines) == 2


def test_watch_audits_crop_even_when_native_ocr_already_reads_some_text():
    class Provider:
        calls = 0

        async def recognize(self, image):
            self.calls += 1
            return [TextBlock('You need to find the key.', Rect(10, 10, 280, 25))]

    provider = Provider()
    blocks = asyncio.run(OcrService(provider, TextFilterService(Settings())).read(
        np.zeros((100, 350, 3), dtype=np.uint8)))
    assert len(blocks) == 1 and provider.calls == 2


def test_full_screen_dressmaker_capture_recovers_small_rank_label():
    fixture = Path(__file__).resolve().parents[1] / 'artifacts/dressmaker/steam-02.jpg'
    if not fixture.exists():
        pytest.skip('Official Dressmaker screenshot is a local development fixture')
    from arabic_lens.ocr import WindowsOcrProvider
    image = cv2.imread(str(fixture))
    blocks = asyncio.run(OcrService(WindowsOcrProvider(), TextFilterService(Settings())).read(
        image, manual=True))
    assert any(block.text.startswith('Rank 4 - Unknown V') for block in blocks)
    brief = next(block for block in blocks if block.text.startswith("I'm hosting a garden party"))
    assert 'paint stains' in brief.text and '800' in brief.text
