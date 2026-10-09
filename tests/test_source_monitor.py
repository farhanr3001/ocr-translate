import pytest
from PySide6.QtWidgets import QApplication
from arabic_lens.models import Rect, Translation
from arabic_lens.source_monitor import SourceWindowMonitor
import arabic_lens.source_monitor as monitor_module
import arabic_lens.windows as windows


@pytest.mark.parametrize('change', ['closed', 'hidden', 'minimized', 'moved', 'reused'])
def test_source_window_lifecycle_rejects_stale_results(monkeypatch, change):
    identity = (1234, 5678, Rect(0, 0, 1920, 1080))
    monkeypatch.setattr(windows, 'window_identity', lambda hwnd: identity)
    monkeypatch.setattr(windows.user32, 'IsWindowVisible', lambda hwnd: True)
    monkeypatch.setattr(windows.user32, 'IsIconic', lambda hwnd: False)
    monkeypatch.setattr(windows.user32, 'GetForegroundWindow', lambda: 1234)
    assert windows.source_window_current(identity)
    if change == 'closed':
        monkeypatch.setattr(windows, 'window_identity', lambda hwnd: None)
    elif change == 'hidden':
        monkeypatch.setattr(windows.user32, 'IsWindowVisible', lambda hwnd: False)
    elif change == 'minimized':
        monkeypatch.setattr(windows.user32, 'IsIconic', lambda hwnd: True)
    else:
        other = (1234, 9999, identity[2]) if change == 'reused' else (1234, 5678, Rect(30, 0, 1920, 1080))
        monkeypatch.setattr(windows, 'window_identity', lambda hwnd: other)
    assert not windows.source_window_current(identity)


def test_visible_source_survives_focus_change_and_mouse_click(monkeypatch):
    identity = (1234, 5678, Rect(0, 0, 1920, 1080))
    monkeypatch.setattr(windows, 'window_identity', lambda hwnd: identity)
    monkeypatch.setattr(windows.user32, 'IsWindowVisible', lambda hwnd: True)
    monkeypatch.setattr(windows.user32, 'IsIconic', lambda hwnd: False)
    monkeypatch.setattr(windows.user32, 'GetForegroundWindow', lambda: 9999)
    assert windows.source_window_current(identity)


def test_all_cells_disappear_together_and_late_results_are_rejected(monkeypatch):
    qt = QApplication.instance() or QApplication([])
    live = [True]
    checks = []
    def current(identity):
        checks.append(identity)
        return live[0]
    monkeypatch.setattr(monitor_module, 'source_window_current', current)
    monitor = SourceWindowMonitor()
    source = (1234, 5678, Rect(0, 0, 1000, 800))
    results = [Translation(str(i), 'Find the key', 'اعثر على المفتاح', Rect(0, 0, 200, 30), source_window=source) for i in range(20)]
    for result in results:
        assert monitor.accept(result)
    checks.clear()
    monitor.check()
    assert len(checks) == 1  # Window checks are shared across translations.
    invalidated = []
    monitor.invalidated.connect(invalidated.append)
    invalidated_keys = []
    monitor.invalidated_keys.connect(invalidated_keys.append)
    live[0] = False
    monitor.check()
    assert invalidated == [source] and not monitor.sources
    assert invalidated_keys == [(source, tuple(str(i) for i in range(20)))]
    assert not monitor.timer.isActive()
    assert not monitor.accept(results[0])


def test_cache_upgrade_keeps_reviewed_text_but_bypasses_old_model(tmp_path):
    import sqlite3
    from pathlib import Path
    from arabic_lens.config import Settings
    from arabic_lens.storage import TranslationStore
    path = tmp_path / 'legacy.db'
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE cache(key TEXT PRIMARY KEY, arabic TEXT NOT NULL, used REAL NOT NULL)')
    db.execute('INSERT INTO cache VALUES(?,?,0)', ('an unknown phrase', 'ترجمة قديمة'))
    db.execute('INSERT INTO cache VALUES(?,?,0)', ('finish dress', 'إنهاء الفستان'))
    db.commit()
    db.close()
    store = TranslationStore(path, Settings())
    store.seed_pack(Path('arabic_lens/data/dressmaker.json'))
    assert store.get('An unknown phrase') is None
    assert store.get('Finish Dress') == 'إنهاء الفستان'
    store.put('An unknown phrase', 'ترجمة جديدة')
    assert store.get('An unknown phrase') == 'ترجمة جديدة'
    store.close()
