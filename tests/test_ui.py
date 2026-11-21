import time
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from arabic_lens.config import Settings
from arabic_lens.localization import LocalizationService
from arabic_lens.storage import TranslationStore
from arabic_lens.ui import SettingsWindow
from arabic_lens.selection import SelectionWindow


@pytest.fixture(scope="module")
def qt():
    return QApplication.instance() or QApplication([])


def test_preview_visible_and_arabic_language_switch(qt, tmp_path):
    settings = Settings()
    store = TranslationStore(tmp_path / "ui.db", settings)
    window = SettingsWindow(settings, LocalizationService(settings), store)
    window.show()
    window.navigate(4)
    QTest.qWait(30)
    assert window.preview.width() > 200
    assert window.preview.height() > 30
    assert window.preview.document.defaultTextOption().textDirection() == Qt.RightToLeft
    assert window.preview.geometry().bottom() < window.preview_scene.height()
    window.overlay_fields["font_size"].setValue(30)
    assert window.preview_appearance.font_size == 30
    window.apply_preset("Subtitle")
    assert window.overlay_fields["font_size"].value() == 27
    assert window.overlay_fields["background_opacity"].value() == 32
    assert window.preset_buttons["Subtitle"].isChecked()
    settings.language = "ar"
    window.rebuild(0)
    assert window.centralWidget().layoutDirection() == Qt.RightToLeft
    assert window.navs[0].text() == "الرئيسية"
    window.hide()
    window.deleteLater()
    store.close()


def test_selection_release_submits_without_confirmation_and_escape_cancels(qt):
    selection = SelectionWindow(qt.primaryScreen(), LocalizationService(Settings()))
    selected, cancelled = [], []
    selection.selected.connect(selected.append)
    selection.cancelled.connect(lambda: cancelled.append(True))
    selection.show()
    QTest.mousePress(selection, Qt.LeftButton, pos=QPoint(100, 100))
    QTest.mouseMove(selection, QPoint(350, 180))
    QTest.mouseRelease(selection, Qt.LeftButton, pos=QPoint(350, 180))
    assert len(selected) == 1
    assert selected[0].w > 200
    QTest.keyClick(selection, Qt.Key_Escape)
    assert cancelled
    selection.close()
    selection.deleteLater()


def test_quick_translate_overlay_time_setting(qt, tmp_path):
    settings = Settings()
    store = TranslationStore(tmp_path / "quick-time.db", settings)
    window = SettingsWindow(settings, LocalizationService(settings), store)
    try:
        lifetime = window.overlay_fields['quick_lifetime']
        seconds = window.overlay_fields['quick_seconds']
        assert lifetime.currentData() == 'source' and not seconds.isEnabled()
        lifetime.setCurrentIndex(lifetime.findData('timer'))
        assert seconds.isEnabled()
        seconds.setValue(9)
        emitted = []
        window.apply_requested.connect(emitted.append)
        window.apply()
        assert emitted[0]['overlay']['quick_lifetime'] == 'timer'
        assert emitted[0]['overlay']['quick_seconds'] == 9
    finally:
        window.deleteLater()
        store.close()
