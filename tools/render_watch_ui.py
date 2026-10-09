"""Render Watch controls off-screen for visual review without opening the app."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import QApplication
from arabic_lens.config import Settings
from arabic_lens.localization import LocalizationService
from arabic_lens.storage import TranslationStore
from arabic_lens.ui import SettingsWindow
from arabic_lens.watch_dialogs import WatchPresetsDialog, PresetNameDialog
from arabic_lens.selection import SelectionWindow
from arabic_lens.models import Rect


def main():
    app = QApplication([])
    output = Path('artifacts/watch-workflow')
    output.mkdir(parents=True, exist_ok=True)
    settings = Settings(first_run=False, watch_startup='presets', watch_areas=[[20, 40, 300, 100], [400, 40, 300, 100]])
    store = TranslationStore(output / 'preview.db', settings)
    try:
        window = SettingsWindow(settings, LocalizationService(settings), store)
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        window.show()
        window.navigate(3)
        app.processEvents()
        window.grab().save(str(output / 'watch-settings.png'))
        window.navigate(2)
        app.processEvents()
        window.grab().save(str(output / 'translation-setup.png'))
        dialog = WatchPresetsDialog(LocalizationService(settings))
        dialog.setAttribute(Qt.WA_DontShowOnScreen, True)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(output / 'watch-presets-empty.png'))
        dialog.set_presets([{'name': 'Dressmaker', 'areas': [[20, 40, 300, 100], [400, 40, 300, 100]]}], 0)
        app.processEvents()
        dialog.grab().save(str(output / 'watch-presets-selected.png'))
        dialog.close()
        name_dialog = PresetNameDialog(LocalizationService(settings))
        name_dialog.setAttribute(Qt.WA_DontShowOnScreen, True)
        name_dialog.name.setText('My dialogue zones')
        name_dialog.show()
        app.processEvents()
        name_dialog.grab().save(str(output / 'preset-name.png'))
        name_dialog.close()
        selector = SelectionWindow(app.primaryScreen(), LocalizationService(settings))
        selector.multi = True
        selector.areas = [Rect(120, 80, 250, 400), Rect(430, 80, 450, 400)]
        selector.setAttribute(Qt.WA_DontShowOnScreen, True)
        selector.show()
        app.processEvents()
        selector.grab(QRect(selector.width() // 2 - 160, 0, 320, 110)).save(str(output / 'selection-controls.png'))
        selector.close()
        window.hide()
    finally:
        store.close()


if __name__ == '__main__':
    main()
