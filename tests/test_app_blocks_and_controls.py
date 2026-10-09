import time
import numpy as np
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QComboBox, QSlider, QPushButton, QScrollArea
from PySide6.QtTest import QTest
from arabic_lens.config import Settings, SettingsService, OverlaySettings
from arabic_lens.app_catalog import AppBlockService, clean_apps
from arabic_lens.localization import LocalizationService
from arabic_lens.storage import TranslationStore
from arabic_lens.ui import SettingsWindow
from arabic_lens.models import Rect
from arabic_lens.engine import Engine
import arabic_lens.engine as engine_module


def pump(qt, duration):
    until = time.monotonic() + duration
    while time.monotonic() < until:
        qt.processEvents(); QTest.qWait(15)


def test_executable_exclusions_persist_and_do_not_match_similar_names(tmp_path):
    service = SettingsService(tmp_path)
    apps = [{'name': 'Browser', 'path': r'C:\Apps\Browser.exe'},
            {'name': 'Duplicate', 'path': r'c:\apps\BROWSER.EXE'}, {'name': 'invalid', 'path': ''}]
    service.settings.blocked_apps = clean_apps(apps)
    service.save()
    settings = SettingsService(tmp_path).settings
    assert len(settings.blocked_apps) == 1
    calls = []
    blocker = AppBlockService(settings, lambda hwnd: calls.append(hwnd) or r'C:\Apps\browser.exe')
    assert blocker.blocked(123) and blocker.blocked(123)
    assert calls == [123]
    blocker.cache.clear(); blocker.resolver = lambda hwnd: r'C:\Other\browser.exe'
    assert not blocker.blocked(123)
    settings.blocked_apps = []
    assert not blocker.blocked(123)


def test_blocked_watch_never_captures_and_resumes_when_removed(monkeypatch, tmp_path):
    qt = QApplication.instance() or QApplication([])
    settings = Settings(scan_ms=250, blocked_apps=[{'name': 'Game', 'path': r'C:\Game.exe'}])
    class Capture:
        calls = 0
        def capture(self, rect):
            self.calls += 1
            return np.zeros((180, 320, 4), np.uint8)
        def close(self): pass
    monkeypatch.setattr(engine_module, 'CaptureService', Capture)
    monkeypatch.setattr(engine_module, 'PreviewCaptureService', Capture)
    monkeypatch.setattr(engine_module, 'active_window', lambda active=True: (123, Rect(0, 0, 320, 180), 'Game'))
    store = TranslationStore(tmp_path / 'blocked.db', settings)
    engine = Engine(settings, store)
    engine.app_blocks.resolver = lambda hwnd: r'C:\Game.exe'
    try:
        engine.set_watch(True); pump(qt, .8)
        assert engine.capture.calls == engine.preview_capture.calls == 0
        assert engine.ocr is None and not engine.jobs
        settings.blocked_apps = []; pump(qt, .6)
        assert engine.capture.calls == 1 and engine.preview_capture.calls >= 1
        settings.blocked_apps = [{'name': 'Game', 'path': r'C:\Game.exe'}]
        pump(qt, .35)
        calls = engine.preview_capture.calls
        pump(qt, .6)
        assert engine.preview_capture.calls == calls
        assert engine.context is None and not engine.jobs
    finally:
        engine.close(); store.close()


def test_settings_wheel_never_changes_fields_and_overlay_defaults(tmp_path):
    qt = QApplication.instance() or QApplication([])
    settings = Settings(); settings.overlay.font_size = 41; settings.overlay.match_game = True
    store = TranslationStore(tmp_path / 'ui.db', settings)
    window = SettingsWindow(settings, LocalizationService(settings), store)
    window.show(); window.navigate(4); qt.processEvents()
    for widget in window.findChildren(QAbstractSpinBox) + window.findChildren(QComboBox) + window.findChildren(QSlider):
        if isinstance(widget, QAbstractSpinBox): before = widget.value()
        elif isinstance(widget, QComboBox): before = widget.currentIndex()
        else: before = widget.value()
        pos = widget.rect().center(); global_pos = widget.mapToGlobal(pos)
        widget.setFocus()
        event = QWheelEvent(QPointF(pos), QPointF(global_pos), QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(widget, event)
        after = widget.currentIndex() if isinstance(widget, QComboBox) else widget.value()
        assert before == after
    window.restore_overlay()
    defaults = OverlaySettings()
    for key, widget in window.overlay_fields.items():
        assert window.field_value(widget) == getattr(defaults, key)
    values = []; window.apply_requested.connect(values.append)
    window.add_blocked_item({'name': 'Example', 'path': r'C:\Example.exe'})
    window.apply()
    assert values[-1]['blocked_apps'][0]['path'] == r'C:\Example.exe'
    window.navigate(2)
    window.translation_input.setPlainText('Translate this sentence.')
    qt.processEvents()
    button = window.translate_button
    QTest.mouseClick(button, Qt.LeftButton)
    assert values[-1]['test'] and values[-1]['provider'] == 'Built-in offline'
    assert values[-1]['test_text'] == 'Translate this sentence.'
    window.hide(); window.deleteLater(); store.close()
