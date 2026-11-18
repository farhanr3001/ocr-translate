"""Use real GDI capture, Windows OCR, model and overlays across HWND owners."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent
from arabic_lens.app import Application
from arabic_lens.models import Rect
from arabic_lens.windows import window_identity
import arabic_lens.app as app_module


def test_selected_app_survives_unrelated_foreground_window_closing(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    qt.setProperty('smokeTest', True)
    qt.setQuitOnLastWindowClosed(False)
    qt.sendPostedEvents(None, QEvent.DeferredDelete)
    qt.processEvents()
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root))
    child = subprocess.Popen([sys.executable, str(root/'tests/fixtures/manual_selection_window.py'), str(tmp_path)],
                             env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app = None
    try:
        deadline = time.monotonic()+10
        while not (tmp_path/'ready.json').exists():
            assert child.poll() is None, 'Native fixture exited'
            assert time.monotonic() < deadline, 'Native fixture did not start'
            qt.processEvents(); time.sleep(.02)
        fixture = json.loads((tmp_path/'ready.json').read_text())
        selected = window_identity(fixture['target'])
        previous = window_identity(fixture['previous'])
        assert selected and previous
        monkeypatch.setattr(app_module.HotkeyManager, 'register', lambda *args: None)
        app = Application(qt, tmp_path/'app-data')
        app.window.hide()
        results, failures = [], []
        app.engine.translated.connect(results.append)
        app.engine.manual_failed.connect(lambda *args: failures.append(args))
        app.schedule_capture(Rect(*fixture['rect']), 'Previous foreground fixture', previous)
        started = time.monotonic()
        while time.monotonic()-started < 15:
            qt.processEvents(); time.sleep(.02)
            if time.monotonic()-started > .3:
                (tmp_path/'close-previous').touch(exist_ok=True)
            if results and time.monotonic()-started > 2:
                break
        assert not failures, failures
        assert results, 'Real capture/OCR/model did not produce a translation'
        assert all(result.source_window == selected for result in results), (selected, [r.source_window for r in results])
        assert any('\u0600' <= char <= '\u06ff' for result in results for char in result.arabic)
        assert any(overlay.isVisible() for overlay in app.overlays.windows.values())
    finally:
        if app:
            app.shutdown()
            qt.aboutToQuit.disconnect(app.shutdown)
            app.window.hide(); app.window.deleteLater()
        child.terminate()
        child.wait(timeout=5)
        qt.setProperty('smokeTest', False)
