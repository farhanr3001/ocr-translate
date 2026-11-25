"""Real capture/OCR/model where Windows refuses overlay capture exclusion.

Seen on Windows 11 build 22000: overlays are visible to screen capture, so a
Replace overlay hides its own source. The engine must still notice when the
covered English disappears or changes (by rendering the window beneath), and
must not drop an overlay whose English is still there.
"""
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
import arabic_lens.app as app_module
import arabic_lens.overlay as overlay_module


def _pump(qt, seconds, until=None):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qt.processEvents(); time.sleep(.02)
        if until and until():
            return True
    return False


def _shown(app):
    return [o for o in app.overlays.windows.values() if o.isVisible() and not o.closing]


def test_covered_source_retires_and_updates_when_exclusion_is_refused(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    qt.setProperty('smokeTest', True)
    qt.setQuitOnLastWindowClosed(False)
    qt.sendPostedEvents(None, QEvent.DeferredDelete)
    qt.processEvents()
    root = Path(__file__).resolve().parents[1]
    child = subprocess.Popen([sys.executable, str(root / 'tests/fixtures/covered_text_window.py'), str(tmp_path)],
                             env=dict(os.environ, PYTHONPATH=str(root)),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app = None
    monkeypatch.setattr(overlay_module, 'exclude_capture', lambda widget: False)
    monkeypatch.setattr(app_module.HotkeyManager, 'register', lambda *args: None)
    try:
        assert _pump(qt, 10, lambda: (tmp_path / 'ready.json').exists()), 'Native fixture did not start'
        fixture = json.loads((tmp_path / 'ready.json').read_text())
        source = Rect(*fixture['rect'])
        app = Application(qt, tmp_path / 'app-data')
        app.window.hide()
        app.settings.overlay.position = 'Replace'
        app.start_with_areas([[source.x, source.y, source.w, source.h]])
        assert _pump(qt, 20, lambda: _shown(app)), 'No overlay for the visible English'
        overlay = _shown(app)[0]
        assert not overlay.capture_excluded and app.overlays.capture_visible_rects()
        first = overlay.text
        # Still there: the overlay must stay (no flicker/retire loop).
        _pump(qt, 3)
        assert overlay in _shown(app) and overlay.text == first
        # The covered English disappears: the overlay must go.
        (tmp_path / 'clear').touch()
        assert _pump(qt, 6, lambda: not _shown(app)), 'Overlay stayed after its English disappeared'
        # New English in the same place gets its own translation.
        (tmp_path / 'second').touch()
        assert _pump(qt, 15, lambda: _shown(app) and _shown(app)[0].text != first), 'New English not translated'
    finally:
        (tmp_path / 'quit').touch()
        if app:
            app.shutdown()
            qt.aboutToQuit.disconnect(app.shutdown)
            app.window.hide(); app.window.deleteLater()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
        qt.setProperty('smokeTest', False)
