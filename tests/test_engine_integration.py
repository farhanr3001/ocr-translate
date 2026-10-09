import asyncio
import time
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest
from arabic_lens.config import Settings
from arabic_lens.engine import Engine
from arabic_lens.storage import TranslationStore
from arabic_lens.models import Rect
from arabic_lens.overlay import logical_to_physical, OverlayManager
import arabic_lens.engine as engine_module


class DialogueFixture(QWidget):
    text = "You need to find the key before sunset."
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#11151d"))
        font = QFont("Segoe UI")
        font.setPixelSize(32)
        p.setFont(font)
        p.setPen(QColor("#ffffff"))
        p.drawText(40, 140, self.text)


def wait_for(qt, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt.processEvents()
        if predicate():
            return
        # Yield the Python GIL to the engine thread; Qt qWait can retain it.
        time.sleep(.03)
    raise AssertionError("Pipeline did not reach expected state")


def test_real_watch_pipeline_change_disappearance_and_overlay(monkeypatch, tmp_path):
    qt = QApplication.instance() or QApplication([])
    fixture = DialogueFixture()
    fixture.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    fixture.setWindowTitle("Arabic Lens test dialogue")
    fixture.setGeometry(80, 80, 1000, 260)
    fixture.show()
    fixture.raise_()
    fixture.activateWindow()
    QTest.qWait(500)
    geometry = fixture.geometry()
    bounds = logical_to_physical(fixture.screen(), Rect(geometry.x(), geometry.y(), geometry.width(), geometry.height()))
    from arabic_lens.windows import CaptureService
    from arabic_lens.detection import TextRegionDetector
    capture = CaptureService()
    frame = capture.capture(bounds).copy()
    capture.close()
    # Some remote/hidden desktop execution hosts do not compose test windows onto
    # the captured desktop. Validate the render locally, then use fixture pixels
    # for that environment; real GDI capture has its own independent test.
    from PySide6.QtGui import QImage
    import numpy as np
    rendered = fixture.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    fixture_frame = np.frombuffer(rendered.bits(), dtype=np.uint8).reshape(rendered.height(), rendered.width(), 4).copy()
    import cv2
    fixture_frame = cv2.cvtColor(fixture_frame, cv2.COLOR_RGBA2BGRA)
    captured_matches = np.mean(cv2.absdiff(frame, fixture_frame)) < 4 if frame.shape == fixture_frame.shape else False
    if not captured_matches:
        # Qt widgets must remain on the GUI thread. Supply immutable snapshots
        # refreshed by the test at each dialogue change.
        snapshot = [fixture_frame]
        class SnapshotCapture:
            calls = 0
            def capture(self, rect):
                self.calls += 1
                return snapshot[0]
            def close(self):
                pass
        monkeypatch.setattr(engine_module, 'CaptureService', SnapshotCapture)
        class SnapshotPreview(SnapshotCapture):
            def capture(self, rect):
                self.calls += 1
                return cv2.resize(snapshot[0], (320, 180))
        monkeypatch.setattr(engine_module, 'PreviewCaptureService', SnapshotPreview)
    # Deliberately hidden fixtures have no foreground HWND; the lifecycle
    # monitor is exercised independently with Win32 window state transitions.
    monkeypatch.setattr(engine_module, 'window_identity', lambda hwnd: None)
    monkeypatch.setattr(engine_module, "active_window", lambda active=True: (int(fixture.winId()), bounds, "Test dialogue"))
    settings = Settings(scan_ms=250, stability_ms=250, cooldown_ms=500)
    store = TranslationStore(tmp_path / "engine.db", settings)
    engine = Engine(settings, store)
    results, removed, errors = [], [], []
    engine.translated.connect(results.append)
    engine.removed.connect(removed.append)
    engine.status.connect(errors.append)
    class FixtureTranslator:
        calls = 0
        async def translate(self, text):
            self.calls += 1
            await asyncio.sleep(.05)
            return "عليك العثور على الكنز." if "treasure" in text.casefold() else "عليك العثور على المفتاح قبل غروب الشمس."
    provider = FixtureTranslator()
    async def install():
        engine.translator.provider = provider
    engine._submit(install()).result(3)
    overlays = OverlayManager(settings, errors.append)
    try:
        engine.set_watch(True)
        wait_for(qt, lambda: len(results) == 1)
        assert "find the key" in results[0].source.casefold()
        assert results[0].id.startswith("watch-")
        if not captured_matches:
            wait_for(qt, lambda: engine.preview_capture.calls >= 3)
        else:
            deadline = time.monotonic() + .9
            while time.monotonic() < deadline:
                qt.processEvents()
                time.sleep(.03)
        assert provider.calls == 1  # Stable dialogue incurs no repeated OCR/translation.
        if not captured_matches:
            assert engine.capture.calls == 1
            assert engine.preview_capture.calls >= 3
        overlays.show(results[0])
        qt.processEvents()
        window = overlays.windows[results[0].id]
        assert window.capture_excluded
        assert window.windowFlags() & Qt.WindowTransparentForInput
        # Returning to the same unchanged game after a focus/window invalidation
        # must restore cached overlays instead of staying silently suppressed.
        engine.invalidate_source()
        wait_for(qt, lambda: len(results) == 2)
        assert results[-1].cached and provider.calls == 1
        fixture.text = "You need to find the treasure before dawn."
        fixture.update()
        qt.processEvents()
        if not captured_matches:
            rendered = fixture.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
            snapshot[0] = cv2.cvtColor(np.frombuffer(rendered.bits(), dtype=np.uint8).reshape(rendered.height(), rendered.width(), 4).copy(), cv2.COLOR_RGBA2BGRA)
        wait_for(qt, lambda: len(results) == 3)
        assert "treasure" in results[2].source.casefold()
        assert removed
        fixture.text = ""
        fixture.update()
        qt.processEvents()
        if not captured_matches:
            rendered = fixture.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
            snapshot[0] = cv2.cvtColor(np.frombuffer(rendered.bits(), dtype=np.uint8).reshape(rendered.height(), rendered.width(), 4).copy(), cv2.COLOR_RGBA2BGRA)
        count = len(removed)
        wait_for(qt, lambda: len(removed) > count)
        assert provider.calls == 2
        assert not errors
        engine.set_watch(False)
        wait_for(qt, lambda: not engine.watch)
    finally:
        overlays.clear()
        engine.close()
        fixture.close()
        fixture.deleteLater()
        store.close()
