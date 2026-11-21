import time
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication, QSizeGrip
from PySide6.QtTest import QTest
from arabic_lens.config import Settings
from arabic_lens.localization import LocalizationService
from arabic_lens.storage import TranslationStore
from arabic_lens.ui import SettingsWindow, ToolboxWindow
from arabic_lens.selection import SelectionWindow, SelectionManager


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
    assert window.preview.appearance.background_color == settings.overlay.background_color
    assert window.preview_scene.source.isHidden()
    assert not window.findChildren(QSizeGrip)
    window.resize(1060, 700)
    QTest.qWait(30)
    position = window.preview_scene.mapToGlobal(QPoint())
    scroll = window.overlay_scroll.verticalScrollBar()
    assert scroll.maximum() > 0
    scroll.setValue(scroll.maximum())
    assert window.preview_scene.mapToGlobal(QPoint()) == position
    assert window.preview_scene.isVisible()
    placement = window.overlay_fields["position"]
    placement.setCurrentIndex(placement.findData("Below"))
    window.overlay_fields["font_size"].setValue(30)
    assert window.preview.document.defaultFont().pixelSize() == 30
    assert not window.preview_scene.source.isHidden()
    assert window.preview.y() > window.preview_scene.source.y()
    window.overlay_fields["background_color"].setText("#071828")
    window.overlay_fields["background_opacity"].setValue(70)
    assert window.preview.appearance.background_color == "#071828"
    assert window.preview.appearance.background_opacity == 70
    settings.language = "ar"
    window.rebuild(0)
    assert window.centralWidget().layoutDirection() == Qt.RightToLeft
    assert window.navs[0].text() == "الرئيسية"
    window.hide()
    window.deleteLater()
    store.close()


def test_toolbox_shares_watch_choices_and_remembers_pin(qt, tmp_path):
    from arabic_lens.app import Application
    from arabic_lens.config import SettingsService

    app = Application.__new__(Application)
    app.service = SettingsService(tmp_path)
    app.settings = app.service.settings
    app.defer_update_prompt = False
    localization = LocalizationService(app.settings)
    store = TranslationStore(tmp_path / 'toolbox.db', app.settings)
    app.window = SettingsWindow(app.settings, localization, store)
    app.toolbox = ToolboxWindow(app.settings, localization)
    app.window.watch_startup_changed.connect(app.set_watch_startup)
    app.toolbox.watch_startup_changed.connect(app.set_watch_startup)
    app.toolbox.settings_requested.connect(app.show_settings)
    app.window.toolbox_requested.connect(app.show_toolbox)
    app.toolbox.pin_changed.connect(app.pin_toolbox)
    try:
        app.show_toolbox()
        assert app.toolbox.isVisible() and not app.window.isVisible()
        app.toolbox.watch_choices.buttons()[2].click()
        assert app.window.watch_choices.checkedButton().property("mode") == "previous"
        app.toolbox.settings_requested.emit()
        assert app.window.isVisible() and not app.toolbox.isVisible()
        app.window.watch_choices.buttons()[0].click()
        assert app.toolbox.watch_choices.checkedButton().property("mode") == "fullscreen"
        app.window.close()
        app.open_controls()
        assert app.toolbox.isVisible() and not app.window.isVisible()
        app.toolbox.pin.click()
        assert app.toolbox.windowFlags() & Qt.WindowStaysOnTopHint
        assert SettingsService(tmp_path).settings.toolbox_pinned is True
        actions = []
        app.toolbox.action_requested.connect(actions.append)
        app.toolbox.watch_button.click()
        app.toolbox.update_watch(True)
        assert actions == ["watch"] and app.toolbox.watch_button.text() == "Stop"
    finally:
        app.toolbox.close()
        app.window.hide()
        app.toolbox.deleteLater()
        app.window.deleteLater()
        store.close()


def test_overlay_changes_persist_without_applying_other_settings(qt, tmp_path):
    from PySide6.QtCore import QTimer
    from arabic_lens.app import Application
    from arabic_lens.config import SettingsService

    app = Application.__new__(Application)
    app.service = SettingsService(tmp_path)
    app.settings = app.service.settings
    app.overlay_save_timer = QTimer()
    app.overlay_save_timer.setSingleShot(True)
    app.overlay_save_timer.setInterval(10)
    app.overlay_save_timer.timeout.connect(app.service.save)
    store = TranslationStore(tmp_path / 'autosave.db', app.settings)
    window = SettingsWindow(app.settings, LocalizationService(app.settings), store)
    window.overlay_changed.connect(app.edit_overlay)
    try:
        window.overlay_fields["font_size"].setValue(32)
        window.overlay_fields["background_opacity"].setValue(63)
        QTest.qWait(40)
        loaded = SettingsService(tmp_path).settings
        assert (loaded.overlay.font_size, loaded.overlay.background_opacity) == (32, 63)
        assert loaded.shortcuts == Settings().shortcuts
    finally:
        window.deleteLater()
        store.close()


def test_watch_area_x_removes_only_that_area_and_allows_redraw(qt):
    selected = []
    manager = SelectionManager(LocalizationService(Settings()), lambda _: None)
    manager.begin_multi([], selected.append, lambda: None)
    window = manager.windows[0]
    try:
        for point in (QPoint(60, 100), QPoint(200, 100)):
            QTest.mousePress(window, Qt.LeftButton, pos=point)
            QTest.mouseRelease(window, Qt.LeftButton, pos=point + QPoint(80, 60))
        assert len(manager.areas) == 2
        remaining = manager.areas[1]
        box = next(window.local_areas())[1]
        remove = window.remove_rect(box).center()
        window.update_cursor(remove)
        assert window.cursor().shape() == Qt.PointingHandCursor
        QTest.mouseClick(window, Qt.LeftButton, pos=remove)
        assert manager.areas == [remaining]
        start = QPoint(70, 210)
        QTest.mousePress(window, Qt.LeftButton, pos=start)
        QTest.mouseRelease(window, Qt.LeftButton, pos=start + QPoint(100, 45))
        assert len(manager.areas) == 2
        QTest.mouseClick(window, Qt.LeftButton, pos=window.done_rect().center())
        assert len(selected) == 1 and selected[0][0] == remaining and len(selected[0]) == 2
    finally:
        if manager.windows:
            manager.cancel()


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
