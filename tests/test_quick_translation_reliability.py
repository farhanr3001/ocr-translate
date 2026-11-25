"""Exercise the real manual pipeline without opening windows on the desktop."""
import asyncio
import time
import cv2
import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QFont, QColor
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtTest import QTest
from arabic_lens.app import Application
from arabic_lens.models import Rect
from arabic_lens.translation import TranslationError
import arabic_lens.app as app_module
import arabic_lens.engine as engine_module
import arabic_lens.source_monitor as monitor_module


def wait(qt, predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qt.processEvents()
        if predicate(): return
        QTest.qWait(20)
    raise AssertionError('Translation was not displayed')


def frame(text):
    image = QImage(900, 140, QImage.Format_RGBA8888)
    image.fill(QColor('#ece7de'))
    painter = QPainter(image)
    font = QFont('Segoe UI'); font.setPixelSize(30); painter.setFont(font)
    painter.setPen(QColor('#182b25')); painter.drawText(20, 80, text); painter.end()
    pixels = np.frombuffer(image.bits(), np.uint8).reshape(140, 900, 4).copy()
    return cv2.cvtColor(pixels, cv2.COLOR_RGBA2BGRA)


def test_quick_capture_real_ocr_translation_repeat_cancel_failure_and_recovery(monkeypatch, tmp_path):
    qt = QApplication.instance() or QApplication([])
    qt.setProperty('smokeTest', True)
    qt.setQuitOnLastWindowClosed(False)
    snapshot = [frame('You need to find the key before sunset.')]
    identity = (123, 456, Rect(0, 0, 1920, 1080))
    class Capture:
        def capture(self, rect): return snapshot[0].copy()
        def close(self): pass
    monkeypatch.setattr(engine_module, 'CaptureService', Capture)
    monkeypatch.setattr(engine_module, 'PreviewCaptureService', Capture)
    monkeypatch.setattr(app_module.HotkeyManager, 'register', lambda self, values: None)
    monkeypatch.setattr(app_module, 'active_window', lambda: (123, identity[2], 'Fixture'))
    monkeypatch.setattr(app_module, 'window_identity', lambda hwnd: identity)
    monkeypatch.setattr(app_module, 'window_at_rect', lambda rect: identity)
    monkeypatch.setattr(engine_module, 'source_window_current', lambda source: True)
    monkeypatch.setattr(monitor_module, 'source_window_current', lambda source: True)
    focus_calls = []
    def focus(source):
        focus_calls.append(source)
        return len(focus_calls) >= 3  # First selection needs focus restoration retries.
    monkeypatch.setattr(app_module, 'restore_capture_focus', focus)
    app = Application(qt, tmp_path)
    results, failures = [], []
    app.engine.translated.connect(results.append)
    app.engine.manual_failed.connect(lambda *args: failures.append(args))
    try:
        # A real click on the built-in button must apply the provider and show
        # an uncached model result inside the Translation page.
        app.show_settings(2)
        app.window.overlay_fields['follow_content'].setChecked(False)
        app.window.fields['provider'].setCurrentIndex(1)
        app.window.builtin_toggle.setChecked(True)
        app.window.translation_input.setPlainText('You need to find the key before sunset.')
        qt.processEvents()
        button = app.window.translate_button
        QTest.mouseClick(button, Qt.LeftButton)
        wait(qt, lambda: 'المفتاح' in app.window.translation_feedback.text())
        assert app.settings.provider == 'Built-in offline'
        app.window.fields['minimize_tray'].setChecked(False)
        assert app.service.settings.minimize_tray is False
        app.window.overlay_fields['background_opacity'].setValue(54)
        app.show_toolbox()
        # The toolbox is visible to capture (screen sharing shows it) and its
        # area is masked from OCR, so keep it clear of the fixture text.
        area = app.toolbox.screen().availableGeometry()
        app.toolbox.move(area.right() - app.toolbox.width(), area.bottom() - app.toolbox.height())
        qt.processEvents()
        assert not app.toolbox.capture_excluded and app.toolbox.capture_bounds
        for index in range(12):
            if index == 6:
                snapshot[0] = frame('Bring the blue fabric to the village shop.')
            count = len(results)
            app.action('quick')
            assert app.toolbox.isVisible() and not app.toolbox.isMinimized()
            selector = app.selector.windows[0]
            QTest.mousePress(selector, Qt.LeftButton, pos=QPoint(40, 180))
            QTest.mouseRelease(selector, Qt.LeftButton, pos=QPoint(940, 320))
            wait(qt, lambda: len(results) == count + 1)
            wait(qt, lambda: 'manual' in app.overlays.windows)
            overlay = app.overlays.windows['manual']
            assert overlay.isVisible() and not overlay.closing
            assert overlay.appearance.background_opacity == 54
            assert results[-1].arabic and results[-1].source_window == identity
            if index not in (0, 6): assert results[-1].cached
            app.action('quick')
            assert not app.selector.windows and 'manual' not in app.overlays.windows
            # A result queued just before the dismissal cannot put it back.
            app.show_translation(results[-1])
            assert 'manual' not in app.overlays.windows
        assert len(focus_calls) >= 14 and not failures
        count = len(results)
        app.action('quick')
        QTest.keyClick(app.selector.windows[0], Qt.Key_Escape)
        QTest.qWait(250); qt.processEvents()
        assert not app.selector.windows and len(results) == count
        # A delayed capture from an earlier request must not race a newer one.
        app.schedule_capture(Rect(40, 180, 900, 140), 'Fixture', identity)
        app.action('hide'); QTest.qWait(250); qt.processEvents()
        assert len(results) == count
        snapshot[0] = frame('')
        app.recapture(Rect(40, 180, 900, 140))
        wait(qt, lambda: failures and failures[-1][0] == 'no_text')
        wait(qt, lambda: 'manual-notice' in app.overlays.windows)
        # Failures are visible for manual requests, and do not poison the next capture.
        snapshot[0] = frame('Collect the silver thread before dawn.')
        class FailingProvider:
            async def translate(self, text): raise TranslationError('translation_failed')
        original = app.engine.translator.provider
        app.engine.translator.provider = FailingProvider()
        app.recapture(Rect(40, 180, 900, 140))
        wait(qt, lambda: failures[-1][0] == 'translation_failed')
        app.engine.translator.provider = original
        app.recapture(Rect(40, 180, 900, 140))
        wait(qt, lambda: len(results) == count + 1)
        wait(qt, lambda: 'manual' in app.overlays.windows)
        assert 'الخيط' in results[-1].arabic
    finally:
        app.shutdown()
        qt.aboutToQuit.disconnect(app.shutdown)
        app.toolbox.hide(); app.toolbox.deleteLater()
        app.window.hide(); app.window.deleteLater()
        qt.setProperty('smokeTest', False)


def test_focus_restore_never_steals_focus_from_another_app(monkeypatch):
    import os
    import arabic_lens.windows as windows
    identity = (123, 456, Rect(0, 0, 100, 100))
    monkeypatch.setattr(windows, 'window_identity', lambda hwnd: identity)
    monkeypatch.setattr(windows, 'source_window_current', lambda source: False)
    monkeypatch.setattr(windows.user32, 'GetForegroundWindow', lambda: 999)
    def pid(hwnd, output): output._obj.value = os.getpid() + 1
    monkeypatch.setattr(windows.user32, 'GetWindowThreadProcessId', pid)
    calls = []
    monkeypatch.setattr(windows.user32, 'SetForegroundWindow', calls.append)
    assert not windows.restore_capture_focus(identity)
    assert not calls


def test_capture_binds_to_selected_window_instead_of_previous_foreground(monkeypatch):
    from types import SimpleNamespace
    qt = QApplication.instance() or QApplication([])
    old = (123, 1, Rect(0, 0, 100, 100))
    selected = (456, 2, Rect(100, 0, 900, 600))
    calls = []
    focused = []
    fake = SimpleNamespace(capture_request=1, selector=SimpleNamespace(windows=[]),
        engine=SimpleNamespace(translate_region=lambda *args: calls.append(args)))
    monkeypatch.setattr(app_module, 'restore_capture_focus', lambda source: focused.append(source) or True)
    monkeypatch.setattr(app_module, 'window_at_rect', lambda rect: selected)
    rect = Rect(120, 30, 300, 90)
    Application.schedule_capture(fake, rect, 'Previous window', old)
    wait(qt, lambda: bool(calls), seconds=2)
    assert calls[0][0] == rect and calls[0][2] == selected
    assert focused == [selected]


def test_manual_failure_is_not_hidden_by_invalid_source(monkeypatch):
    from types import SimpleNamespace
    from arabic_lens.config import Settings
    from arabic_lens.localization import LocalizationService
    notices, messages, balloons = [], [], []
    fake = SimpleNamespace(l=LocalizationService(Settings()), report=messages.append, manual_hidden=False,
        show_translation=notices.append, visible_controls=lambda: None,
        tray=SimpleNamespace(isVisible=lambda: True, showMessage=lambda *args: balloons.append(args)))
    Application.manual_failed(fake, 'ocr_language', Rect(10, 20, 400, 100), (123, 1, Rect(0,0,100,100)))
    assert notices[0].source_window is None and notices[0].notice
    assert 'English OCR' in messages[0] and balloons


def test_stale_manual_source_reports_instead_of_silently_returning(monkeypatch):
    from types import SimpleNamespace
    failures = []
    fake = SimpleNamespace(manual_failed=SimpleNamespace(emit=lambda *args: failures.append(args)))
    monkeypatch.setattr(engine_module, 'source_window_current', lambda source: False)
    asyncio.run(engine_module.Engine._manual_translate(fake, Rect(0,0,100,100), '', (123,1,Rect(0,0,100,100))))
    assert failures[0][0] == 'selection_changed'


def test_missing_english_ocr_emits_actionable_manual_failure(monkeypatch):
    from types import SimpleNamespace
    failures, reports = [], []
    def unavailable(): raise RuntimeError('ocr_language')
    fake = SimpleNamespace(status=SimpleNamespace(emit=lambda *args: None),
        manual_failed=SimpleNamespace(emit=lambda *args: failures.append(args)),
        capture=SimpleNamespace(capture=lambda rect: np.zeros((100,300,4), np.uint8)),
        ocr_lock=asyncio.Lock(), _get_ocr=unavailable, _report=reports.append,
        _masked=lambda image, bounds: (image, []))
    monkeypatch.setattr(engine_module, 'source_window_current', lambda source: True)
    asyncio.run(engine_module.Engine._manual_translate(fake, Rect(0,0,300,100), '', None))
    assert failures[0][0] == 'ocr_language' and reports
