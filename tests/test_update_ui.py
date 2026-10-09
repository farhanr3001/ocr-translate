"""Update notifications must stay understandable and never start an install by themselves."""

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QPushButton

from arabic_lens.app import Application
from arabic_lens.config import Settings
from arabic_lens.localization import LocalizationService
from arabic_lens.storage import TranslationStore
from arabic_lens.ui import SettingsWindow
from arabic_lens.updates import UpdateInfo


def update_info():
    return UpdateInfo("0.2.0", "", "https://github.com/farhanr3001/ocr-translate/releases/tag/v0.2.0",
                      "https://github.com/farhanr3001/ocr-translate/releases/download/v0.2.0/ArabicLens-Setup.exe",
                      "a" * 64, 200_000_000)


def test_general_page_update_action_and_bilingual_status(tmp_path):
    qt = QApplication.instance() or QApplication([])
    settings = Settings()
    store = TranslationStore(tmp_path / "test.db", settings)
    window = SettingsWindow(settings, LocalizationService(settings), store)
    try:
        window.navigate(1)
        requested = []
        window.update_requested.connect(lambda: requested.append(True))
        button = next(button for button in window.findChildren(QPushButton)
                      if button.text() == "Check for updates")
        button.click()
        assert requested == [True]
        window.set_update_status("Update available", " · 0.2.0")
        assert window.update_status_label.text() == "Update available · 0.2.0"
        settings.language = "ar"
        window.rebuild(1)
        assert window.update_status_label.text() == "يتوفر تحديث · 0.2.0"
        assert window.fields["auto_check_updates"].isChecked()
    finally:
        window.hide()
        window.deleteLater()
        store.close()
        qt.processEvents()


def test_check_notification_defers_while_settings_hidden(tmp_path):
    qt = QApplication.instance() or QApplication([])
    settings = Settings()
    store = TranslationStore(tmp_path / "test.db", settings)
    window = SettingsWindow(settings, LocalizationService(settings), store)
    balloons = []
    prompts = []
    app = Application.__new__(Application)
    app.closing = False
    app.settings = settings
    app.window = window
    app.tray = SimpleNamespace(isVisible=lambda: True, showMessage=lambda *args: balloons.append(args))
    app.l = LocalizationService(settings)
    app.update_info = None
    app.defer_update_prompt = False
    app.show_update_prompt = lambda: prompts.append(True)
    try:
        app.update_checked(update_info(), None, False)
        assert app.defer_update_prompt
        assert len(balloons) == 1
        assert not prompts
        assert window.update_status_label.text() == "Update available · 0.2.0"
    finally:
        window.deleteLater()
        store.close()
        qt.processEvents()


def test_installer_start_failure_keeps_old_app_running(tmp_path):
    qt = QApplication.instance() or QApplication([])
    settings = Settings()
    store = TranslationStore(tmp_path / "test.db", settings)
    window = SettingsWindow(settings, LocalizationService(settings), store)
    quits = []
    app = Application.__new__(Application)
    app.closing = False
    app.window = window
    app.qt = SimpleNamespace(quit=lambda: quits.append(True))
    try:
        app.update_launched(None, RuntimeError("fixture failure"))
        assert quits == []
        assert window.update_status_label.text() == "Update installation could not start. The current app is unchanged."
        app.update_launched(object(), None)
        assert quits == [True]
    finally:
        window.deleteLater()
        store.close()
        qt.processEvents()
