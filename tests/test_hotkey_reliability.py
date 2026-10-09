from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

import arabic_lens.hotkeys as hotkeys
import arabic_lens.app as app_module
from arabic_lens.app import Application
from arabic_lens.config import SettingsService
from arabic_lens.models import Rect


def test_unavailable_add_zone_does_not_disable_alt_q(monkeypatch):
    QApplication.instance() or QApplication([])
    active = {}

    def register(hwnd, index, modifiers, key):
        if key == ord('R'):
            return False  # Another app owns Alt+R on this Windows machine.
        active[index] = key
        return True

    monkeypatch.setattr(hotkeys, 'user32', SimpleNamespace(
        RegisterHotKey=register, UnregisterHotKey=lambda hwnd, index: active.pop(index, None)))
    manager = hotkeys.HotkeyManager(lambda action: None)
    try:
        unavailable = manager.register({'quick': 'Alt+Q', 'repeat': 'Alt+E',
            'watch': 'Alt+W', 'add_zone': 'Alt+R', 'hide': 'Alt+H'})
        assert unavailable == ['add_zone']
        assert manager.registered[1] == 'quick'
        assert set(manager.registered.values()) == {'quick', 'repeat', 'watch', 'hide'}
        assert active[1] == ord('Q')
    finally:
        manager.close()


def test_conflicting_shortcut_edit_restores_existing_hotkeys(monkeypatch):
    QApplication.instance() or QApplication([])
    active = {}

    def register(hwnd, index, modifiers, key):
        if key == ord('R'):
            return False
        active[index] = key
        return True

    monkeypatch.setattr(hotkeys, 'user32', SimpleNamespace(
        RegisterHotKey=register, UnregisterHotKey=lambda hwnd, index: active.pop(index, None)))
    manager = hotkeys.HotkeyManager(lambda action: None)
    try:
        manager.register({'quick': 'Alt+Q', 'repeat': 'Alt+E'})
        with pytest.raises(ValueError, match='shortcut_conflict'):
            manager.register({'quick': 'Alt+Q', 'add_zone': 'Alt+R'}, strict=True)
        assert set(manager.registered.values()) == {'quick', 'repeat'}
        assert active[1] == ord('Q')
    finally:
        manager.close()


def test_quick_capture_while_watching_keeps_unchanged_watch_overlays(monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module, 'active_window', lambda: None)
    app = Application.__new__(Application)
    app.paused = False
    app.capture_request = 0
    events = []
    app.selector = SimpleNamespace(windows=[], begin=lambda: events.append('selector'))
    app.engine = SimpleNamespace(watch=True, hide=lambda: events.append('clear-watch'))
    app.overlays = SimpleNamespace(windows={'watch-0-1': object(), 'manual': object()},
        remove=lambda key, immediate=False: events.append(f'remove:{key}'),
        clear=lambda immediate=False: events.append('clear-all'))
    app.source_monitor = SimpleNamespace(forget=lambda key: events.append(f'forget:{key}'),
        clear=lambda: events.append('clear-sources'))
    app.window = SimpleNamespace(hide=lambda: events.append('hide-settings'))
    Application.action(app, 'quick')
    assert 'selector' in events and 'remove:manual' in events
    assert 'clear-watch' not in events and 'clear-all' not in events
    assert 'remove:watch-0-1' not in events


def test_quick_capture_cannot_silently_drop_when_focus_restore_fails(monkeypatch):
    qt = QApplication.instance() or QApplication([])
    source = (123, 9, Rect(0, 0, 900, 700))
    selected = Rect(40, 50, 250, 100)
    app = Application.__new__(Application)
    app.capture_request = 1
    app.selector = SimpleNamespace(windows=[])
    captured = []
    app.engine = SimpleNamespace(translate_region=lambda *args: captured.append(args))
    monkeypatch.setattr(app_module, 'restore_capture_focus', lambda identity: False)
    monkeypatch.setattr(app_module, 'window_at_rect', lambda rect: None)
    monkeypatch.setattr(app_module, 'active_window', lambda: None)
    Application.schedule_capture(app, selected, 'Game', source)
    QTest.qWait(430); qt.processEvents()
    assert captured == [(selected, 'Game', source)]


def test_closing_quick_source_does_not_clear_watch_overlays():
    app = Application.__new__(Application)
    events = []
    app.overlays = SimpleNamespace(remove=lambda key, immediate=False: events.append((key, immediate)),
        clear=lambda immediate=False: events.append(('clear-all', immediate)))
    app.engine = SimpleNamespace(invalidate_source=lambda: events.append(('reset-watch', True)))
    app.progress = SimpleNamespace(remove=lambda key: None)

    Application.source_invalidated(app, ((123, 7, Rect(0, 0, 200, 100)), ('manual',)))

    assert events == [('manual', True)]


def test_old_add_area_default_migrates_without_changing_user_shortcuts(tmp_path):
    import json
    (tmp_path / 'settings.json').write_text(json.dumps({'schema_version': 6,
        'shortcuts': {'quick': 'Ctrl+Alt+Q', 'add_zone': 'Alt+R'}}), encoding='utf-8')
    settings = SettingsService(tmp_path).settings
    assert settings.shortcuts['quick'] == 'Ctrl+Alt+Q'
    assert settings.shortcuts['add_zone'] == 'Alt+Shift+W'
