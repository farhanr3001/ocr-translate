import asyncio
from pathlib import Path

import cv2
import numpy as np
import pytest

from arabic_lens.config import Settings
from arabic_lens.models import Rect, TextBlock
from arabic_lens.ocr import WindowsOcrProvider, OcrService
from arabic_lens.text import TextFilterService, group_lines, western_digits
from arabic_lens.storage import TranslationStore


def test_independent_labels_do_not_form_a_sentence():
    cells = [TextBlock(label, Rect(x, 10, 70, 20), standalone=True,
             container=Rect(x - 5, 5, 110, 30))
             for x, label in [(10, 'Warm'), (130, 'Gothic'), (250, 'Risque')]]
    assert [b.text for b in group_lines(cells)] == ['Warm', 'Gothic', 'Risque']
    assert western_digits('ميزانيتي ٨٠٠. يلزم ٣٫٨٥ متر') == 'ميزانيتي 800. يلزم 3.85 متر'


def test_native_ocr_keeps_cell_values_outside_labels():
    image = np.full((120, 620, 3), 240, dtype=np.uint8)
    for x, label, value in [(10, 'Warm', '10'), (210, 'Gothic', '11'), (410, 'Cute', '62')]:
        cv2.rectangle(image, (x, 20), (x + 190, 90), (80, 100, 80), -1)
        cv2.putText(image, label, (x + 10, 63), cv2.FONT_HERSHEY_SIMPLEX, .8, (255,255,255), 2)
        cv2.putText(image, value, (x + 146, 63), cv2.FONT_HERSHEY_SIMPLEX, .8, (255,255,255), 2)
    blocks = asyncio.run(OcrService(WindowsOcrProvider(), TextFilterService(Settings())).read(image))
    by_text = {b.text.casefold(): b for b in blocks}
    for x, label in [(10, 'warm'), (210, 'gothic'), (410, 'cute')]:
        assert label in by_text
        assert by_text[label].standalone
        assert by_text[label].rect.right < x + 146


def test_official_dressmaker_dialogue_and_all_attribute_cells(tmp_path):
    fixture = Path(__file__).resolve().parents[1] / 'artifacts/dressmaker/steam-02.jpg'
    if not fixture.exists():
        pytest.skip('Official Steam screenshot is a local development fixture')
    blocks = asyncio.run(OcrService(WindowsOcrProvider(), TextFilterService(Settings())).read(cv2.imread(str(fixture))))
    brief = next(b for b in blocks if b.text.startswith("I'm hosting a garden party"))
    assert 'paint stains' in brief.text and '800' in brief.text
    assert not brief.standalone
    store = TranslationStore(tmp_path / 'cache.db', Settings())
    store.seed_pack(fixture.parents[2] / 'arabic_lens/data/dressmaker.json')
    assert '800' in store.get(brief.text)
    expected = {'daywear', 'casual', 'cool', 'cute', 'playful', 'profession', 'simple',
        'flowers', 'patterned', 'elaborate', 'workwear', 'romantic', 'elegant', 'gothic', 'warm', 'risque'}
    labels = {b.text.casefold(): b for b in blocks if b.rect.x > 900 and b.rect.x < 1400 and b.rect.y > 750}
    assert expected <= labels.keys()
    for label in expected:
        assert labels[label].standalone and store.get(labels[label].text)
        assert not any(c.isdigit() for c in labels[label].text)
    store.close()
