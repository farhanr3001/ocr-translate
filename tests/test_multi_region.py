import time
import cv2
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from arabic_lens.config import Settings
from arabic_lens.models import Rect
from arabic_lens.detection import TrackedRegion, fingerprint
from arabic_lens.storage import TranslationStore
from arabic_lens.engine import Engine


def test_real_ocr_emits_two_independent_cached_translations(tmp_path):
    qt = QApplication.instance() or QApplication([])
    settings = Settings()
    store = TranslationStore(tmp_path / 'multi.db', settings)
    store.put('You need to find the key before sunset.', 'عليك العثور على المفتاح قبل الغروب.')
    store.put('You do not have enough money.', 'ليس لديك ما يكفي من المال.')
    image = np.full((300, 800, 3), 24, np.uint8)
    cv2.putText(image, 'You need to find the key before sunset.', (25, 80), cv2.FONT_HERSHEY_SIMPLEX, .9, (245, 245, 245), 2)
    cv2.putText(image, 'You do not have enough money.', (25, 240), cv2.FONT_HERSHEY_SIMPLEX, .9, (245, 245, 245), 2)
    engine = Engine(settings, store)
    results = []
    engine.translated.connect(results.append)
    async def process():
        region = TrackedRegion('test', Rect(0, 0, 800, 300), fingerprint(image), 0, 0)
        engine.tracker.regions[region.id] = region
        await engine._region(region, image, Rect(0, 0, 800, 300), 'Test', engine.generation)
        await engine._region(region, image, Rect(0, 0, 800, 300), 'Test', engine.generation)
    try:
        engine._submit(process()).result(5)
        qt.processEvents()
        assert len(results) == 2
        assert all(r.cached for r in results)
        assert results[0].id != results[1].id
        assert results[0].rect.overlap(results[1].rect) == 0
    finally:
        engine.close()
        store.close()
