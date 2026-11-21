import time
import cv2
import numpy as np
from PySide6.QtWidgets import QApplication
from arabic_lens.config import Settings
from arabic_lens.models import Rect
from arabic_lens.storage import TranslationStore
from arabic_lens.engine import Engine
import arabic_lens.engine as engine_module


def test_real_ocr_emits_two_independent_cached_translations(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    image = np.full((300, 800, 3), 24, np.uint8)
    cv2.putText(image, 'You need to find the key before sunset.', (25, 80), cv2.FONT_HERSHEY_SIMPLEX, .9, (245, 245, 245), 2)
    cv2.putText(image, 'You do not have enough money.', (25, 240), cv2.FONT_HERSHEY_SIMPLEX, .9, (245, 245, 245), 2)
    bounds = Rect(0, 0, 800, 300)

    class Capture:
        calls = 0
        def capture(self, rect):
            self.calls += 1
            return image[rect.y:rect.bottom, rect.x:rect.right].copy()
        def close(self):
            pass

    class Preview(Capture):
        def capture(self, rect):
            return cv2.resize(super().capture(rect), (320, 180))

    monkeypatch.setattr(engine_module, 'CaptureService', Capture)
    monkeypatch.setattr(engine_module, 'PreviewCaptureService', Preview)
    monkeypatch.setattr(engine_module, 'active_window', lambda active=True: (123, bounds, 'Test'))
    monkeypatch.setattr(engine_module, 'source_window_current', lambda source: True)
    settings = Settings(watch_areas=[[0, 0, 800, 300]], scan_ms=250, stability_ms=250)
    store = TranslationStore(tmp_path / 'multi.db', settings)
    store.put('You need to find the key before sunset.', 'عليك العثور على المفتاح قبل الغروب.')
    store.put('You do not have enough money.', 'ليس لديك ما يكفي من المال.')
    engine = Engine(settings, store)
    results = []
    engine.translated.connect(results.append)
    try:
        engine.set_watch(True)
        deadline = time.monotonic() + 8
        while len(results) < 2 and time.monotonic() < deadline:
            qt.processEvents(); time.sleep(.02)
        settle = time.monotonic() + .8  # Unchanged text: nothing more.
        while time.monotonic() < settle:
            qt.processEvents(); time.sleep(.02)
        assert len(results) == 2
        assert all(r.cached for r in results)
        assert results[0].id != results[1].id
        assert results[0].rect.overlap(results[1].rect) == 0
    finally:
        engine.close()
        store.close()
