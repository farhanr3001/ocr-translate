from PySide6.QtWidgets import QApplication
from arabic_lens.app import Application
from arabic_lens.engine import Engine
from arabic_lens.storage import TranslationStore


def test_minimized_startup_prepares_engines_without_optional_seed_pack(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    qt.setProperty('smokeTest', True)
    def unavailable(*args, **kwargs):
        raise FileNotFoundError('optional pack missing')
    monkeypatch.setattr(TranslationStore, 'seed_pack', unavailable)
    preparing = []
    prepare = Engine.prepare

    def track_preparation(engine):
        preparing.append(prepare(engine))

    monkeypatch.setattr(Engine, 'prepare', track_preparation)
    app = Application(qt, str(tmp_path), minimized=True)
    try:
        assert app.window and app.engine.ready.is_set()
        assert app.store.get('Unknown text') is None
        assert len(preparing) == 1
        preparing[0].result(timeout=30)
        assert app.engine.ocr is not None
        assert app.engine.provider.local.model is not None
        assert app.store.get('The window is open.') is None
        assert not app.store.history()
        assert not app.engine.watch
    finally:
        app.shutdown()
        app.window.close()
        qt.setProperty('smokeTest', False)
