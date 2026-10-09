import asyncio
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from arabic_lens.offline import TranslationProvider
from arabic_lens.config import Settings, SettingsService
from arabic_lens.storage import TranslationStore
from arabic_lens.localization import LocalizationService
from arabic_lens.ui import SettingsWindow


def test_default_translates_real_uncached_text_without_network(monkeypatch):
    async def scenario():
        provider = TranslationProvider(Settings())
        async def forbidden(*args, **kwargs):
            raise AssertionError('Built-in translation must not use the network')
        monkeypatch.setattr(provider.remote.client, 'post', forbidden)
        try:
            result = await provider.translate('You need to find the key before sunset.')
            assert 'المفتاح' in result and 'الشمس' in result
            result = await provider.translate('My budget is 800.')
            assert '800' in result and not any(c in result for c in '٠١٢٣٤٥٦٧٨٩')
        finally:
            await provider.close()
    asyncio.run(scenario())


def test_upgrade_needs_no_provider_setup_and_preserves_configured_service(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'provider': 'Chat compatible', 'endpoint': ''}))
    assert SettingsService(tmp_path).settings.provider == 'Built-in offline'
    path.write_text(json.dumps({'provider': 'Chat compatible', 'endpoint': 'https://my-service.example/v1'}))
    assert SettingsService(tmp_path).settings.provider == 'Chat compatible'


def test_simple_translation_page_and_themed_window_controls(tmp_path):
    qt = QApplication.instance() or QApplication([])
    settings = Settings()
    store = TranslationStore(tmp_path / 'ui.db', settings)
    window = SettingsWindow(settings, LocalizationService(settings), store)
    window.show()
    window.navigate(2)
    qt.processEvents()
    assert window.windowFlags() & Qt.FramelessWindowHint
    assert window.titlebar.height() == 48
    assert not window.translation_advanced.isVisible()
    assert not window.fields['endpoint'].isVisible()
    assert window.fields['provider'].currentData() == 'Built-in offline'
    QTest.mouseClick(window.titlebar.maximize, Qt.LeftButton)
    assert window.isMaximized()
    QTest.mouseClick(window.titlebar.maximize, Qt.LeftButton)
    assert not window.isMaximized()
    QTest.mouseClick(window.titlebar.close_button, Qt.LeftButton)
    assert not window.isVisible()
    window.deleteLater()
    store.close()
