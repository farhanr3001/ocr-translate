from PySide6.QtWidgets import QApplication
from arabic_lens.app import Application
from arabic_lens.storage import TranslationStore


def test_missing_optional_seed_pack_does_not_crash_startup(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    qt.setProperty('smokeTest', True)
    def unavailable(*args, **kwargs):
        raise FileNotFoundError('optional pack missing')
    monkeypatch.setattr(TranslationStore, 'seed_pack', unavailable)
    app = Application(qt, str(tmp_path), minimized=True)
    try:
        assert app.window and app.engine.ready.is_set()
        assert app.store.get('Unknown text') is None
    finally:
        app.shutdown()
        app.window.close()
        qt.setProperty('smokeTest', False)
