import copy
import asyncio
import sys
import logging
import os
import time
from concurrent.futures import CancelledError
from pathlib import Path
from logging.handlers import RotatingFileHandler
from PySide6.QtCore import Qt, QTimer, QLockFile, QObject, Signal, Slot
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QInputDialog, QMessageBox, QTextEdit, QProgressDialog
from .config import SettingsService, protect_secret
from .storage import TranslationStore
from .localization import LocalizationService
from .windows import active_window, set_startup, window_identity, window_at_rect, restore_capture_focus, focus_chosen_window
from .source_monitor import SourceWindowMonitor
from .models import Rect, Translation
from .engine import Engine
from .ui import SettingsWindow, lens_icon
from .overlay import OverlayManager, display_maps, physical_to_logical, DiagnosticOverlay
from .selection import SelectionManager
from .hotkeys import HotkeyManager
from .translation import validate_endpoint, TranslationError
from .app_catalog import open_windows
from .watch_dialogs import WatchPresetsDialog, WatchTargetDialog, PresetNameDialog
from .updates import UpdateService, UpdateError
from .version import APP_VERSION


UPDATE_REPOSITORY = 'https://github.com/farhanr3001/ocr-translate'


class UpdateEvents(QObject):
    """Marshal background update results onto the Qt UI thread."""

    checked = Signal(object, object, bool)
    downloaded = Signal(object, object)
    launched = Signal(object, object)
    progress = Signal(int, int)

    def __init__(self, owner):
        super().__init__(owner.qt)
        self.owner = owner
        self.checked.connect(self.on_checked, Qt.QueuedConnection)
        self.downloaded.connect(self.on_downloaded, Qt.QueuedConnection)
        self.launched.connect(self.on_launched, Qt.QueuedConnection)
        self.progress.connect(self.on_progress, Qt.QueuedConnection)

    @Slot(object, object, bool)
    def on_checked(self, result, error, manual):
        self.owner.update_checked(result, error, manual)

    @Slot(object, object)
    def on_downloaded(self, path, error):
        self.owner.update_downloaded(path, error)

    @Slot(object, object)
    def on_launched(self, process, error):
        self.owner.update_launched(process, error)

    @Slot(int, int)
    def on_progress(self, received, total):
        self.owner.update_progress(received, total)


class Application:
    def __init__(self, qt, directory=None, minimized=False):
        self.qt = qt
        self.service = SettingsService(directory)
        self.settings = self.service.settings
        self.l = LocalizationService(self.settings)
        self.lock = QLockFile(str(self.service.directory / "instance.lock"))
        self.lock.setStaleLockTime(0)
        if not self.lock.tryLock(0):
            raise RuntimeError(self.l.t("Another Arabic Lens instance is already running."))
        handler = RotatingFileHandler(self.service.directory / "app.log", maxBytes=256_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger("arabic_lens").addHandler(handler)
        logging.getLogger("arabic_lens").setLevel(logging.INFO)
        self.store = TranslationStore(self.service.directory / "translations.db", self.settings)
        try:
            self.store.seed_pack(Path(__file__).parent / 'data' / 'dressmaker.json')
        except (OSError, ValueError):
            # An optional phrase pack must never prevent normal translation.
            logging.getLogger('arabic_lens').warning('Optional seed pack unavailable')
        self.engine = Engine(self.settings, self.store)
        self.window = SettingsWindow(self.settings, self.l, self.store)
        if qt.property('smokeTest'):
            self.window.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.window.apply_requested.connect(self.apply)
        self.window.action_requested.connect(self.action)
        self.window.watch_startup_changed.connect(self.set_watch_startup)
        self.window.update_requested.connect(lambda: self.check_updates(manual=True))
        self.overlays = OverlayManager(self.settings, self.report, self.forget_overlay)
        from .progress import TranslationProgress
        self.progress = TranslationProgress(self.settings, self.l)
        self.engine.progress.connect(self.progress.update)
        self.engine.removed.connect(self.progress.remove)
        self.engine.source_lost.connect(self.progress.remove)
        self.engine.source_moved.connect(self.progress.move)
        self.engine.ignore_translated.connect(self.window.set_ignore_translation)
        self.window.ignore_translation_requested.connect(self.engine.translate_ignore_label)
        self.selector = SelectionManager(self.l, self.selected,
            lambda: restore_capture_focus(getattr(self, 'selection_window', None)), self.selection_cancelled)
        self.selection_purpose = 'quick'
        self.selection_restore_watch = False
        self.preset_dialog = None
        self.target_dialog = None
        self.name_dialog = None
        self.pending_preset_name = ''
        self.hotkeys = HotkeyManager(self.action)
        self.qt.installNativeEventFilter(self.hotkeys)
        try:
            unavailable = self.hotkeys.register(self.settings.shortcuts)
            if unavailable:
                self.report("Shortcut unavailable. Choose another combination.")
        except ValueError:
            self.report("Shortcut unavailable. Choose another combination.")
        self.source_monitor = SourceWindowMonitor(self.qt)
        self.source_monitor.invalidated_keys.connect(self.source_invalidated)
        self.engine.translated.connect(self.show_translation)
        self.engine.removed.connect(self.overlays.remove_group)
        self.engine.removed.connect(self.source_monitor.forget)
        self.engine.cleared.connect(self.clear_overlays)
        self.engine.watch_changed.connect(self.watch_changed)
        self.engine.status.connect(self.on_status)
        self.engine.tested.connect(self.tested)
        self.engine.manual_failed.connect(self.manual_failed)
        self.engine.source_moved.connect(self.overlays.follow_source)
        self.engine.source_lost.connect(lambda key: self.overlays.remove(key, immediate=True))
        self.engine.region_alive.connect(self.overlays.keep_alive_group)
        self.engine.diagnostics.connect(self.diagnostics)
        self.debug_windows = []
        self.debug_text = None
        self.paused_watch = False
        self.paused = False
        self.capture_request = 0
        self.update_service = UpdateService(UPDATE_REPOSITORY, APP_VERSION)
        self.update_events = UpdateEvents(self)
        self.update_check_job = None
        self.update_download_job = None
        self.update_install_job = None
        self.update_info = None
        self.update_prompt = None
        self.update_dialog = None
        self.defer_update_prompt = False
        self.tray = QSystemTrayIcon(lens_icon(), self.qt)
        self.tray.activated.connect(lambda reason: self.show_settings() if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.messageClicked.connect(self.show_settings)
        self.rebuild_tray()
        if not qt.property('smokeTest'):
            self.tray.show()
        self.closing = False
        self.qt.aboutToQuit.connect(self.shutdown)
        if self.settings.first_run or not (minimized or self.settings.start_minimized):
            self.window.show()
        if self.settings.remember_mode and self.settings.last_watch and not self.settings.first_run:
            self.engine.set_watch(True)
        self.update_timer = QTimer(self.qt)
        self.update_timer.setInterval(24 * 60 * 60 * 1000)
        self.update_timer.timeout.connect(self.check_updates)
        if not qt.property('smokeTest') and self.settings.auto_check_updates:
            self.update_timer.start()
            QTimer.singleShot(12000, self.check_updates)

    def rebuild_tray(self):
        menu = QMenu()
        watch = menu.addAction(self.l.t("Watch Mode"))
        watch.setCheckable(True)
        watch.setChecked(self.engine.watch)
        watch.triggered.connect(lambda: self.action("watch"))
        for title, key in (("Quick Translate", "quick"), ("Translate Last Region", "repeat")):
            action = menu.addAction(self.l.t(title) + "\t" + self.settings.shortcuts[key])
            action.triggered.connect(lambda checked=False, k=key: self.action(k))
        add_zone = menu.addAction(self.l.t("Add Watch Area") + "\t" + self.settings.shortcuts.get('add_zone', 'Alt+Shift+W'))
        add_zone.triggered.connect(lambda: self.action('add_zone'))
        pause = menu.addAction(self.l.t("Resume Translation" if self.paused else "Pause Translation"))
        pause.triggered.connect(lambda: self.action("pause"))
        menu.addSeparator()
        menu.addAction(self.l.t("Settings"), self.show_settings)
        menu.addAction(self.l.t("History"), lambda: self.show_settings(7))
        menu.addSeparator()
        menu.addAction(self.l.t("Exit"), self.qt.quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(self.l.t("Arabic Lens") + " · " + self.l.t("Watch is on" if self.engine.watch else "Watch is off"))
        self.tray_menu = menu

    def show_settings(self, page=None):
        if page is not None:
            self.window.navigate(page)
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
        if self.defer_update_prompt and self.update_info:
            self.defer_update_prompt = False
            QTimer.singleShot(200, self.show_update_prompt)

    def check_updates(self, manual=False):
        """Check a public release without making the GUI or gameplay wait."""
        if self.closing or (not manual and not self.settings.auto_check_updates):
            return
        if self.update_check_job and not self.update_check_job.done():
            return
        if manual:
            self.window.set_update_status("Checking for updates…")
        job = self.engine._submit(self.update_service.check())
        self.update_check_job = job
        def finished(future):
            try:
                result, error = future.result(), None
            except BaseException as exc:
                result, error = None, exc
            self.update_events.checked.emit(result, error, bool(manual))
        job.add_done_callback(finished)

    def update_checked(self, info, error, manual):
        if self.closing:
            return
        if error is not None:
            if manual:
                self.window.set_update_status("Could not check for updates. Try again later.")
            logging.getLogger('arabic_lens').warning('Update check unavailable: %s', type(error).__name__)
            return
        if info is None:
            if manual:
                self.window.set_update_status("No new update is available.")
            return
        self.update_info = info
        self.window.set_update_status("Update available", ' · ' + info.version)
        now = time.time()
        last_version = self.settings.update_last_prompt_version
        last_time = self.settings.update_last_prompt_time
        recently_prompted = (last_version == info.version and isinstance(last_time, (int, float))
            and 0 <= now - last_time < 24 * 60 * 60)
        if manual or not recently_prompted:
            if self.window.isVisible():
                self.show_update_prompt()
            else:
                self.defer_update_prompt = True
                if self.tray.isVisible():
                    self.tray.showMessage(self.l.t("Update available"),
                        self.l.t("Update ready. Open Arabic Lens to install it."),
                        QSystemTrayIcon.Information, 10000)

    def show_update_prompt(self):
        if self.closing or not self.update_info or (self.update_prompt and self.update_prompt.isVisible()):
            return
        info = self.update_info
        self.settings.update_last_prompt_version = info.version
        self.settings.update_last_prompt_time = time.time()
        self.service.save()
        box = QMessageBox(self.window)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(self.l.t("Update available"))
        box.setText(self.l.t("A new Arabic Lens version is available. Download and install it now?")
            + '\n' + APP_VERSION + ' → ' + info.version)
        accept = box.addButton(self.l.t("Download update"), QMessageBox.AcceptRole)
        box.addButton(self.l.t("Not now"), QMessageBox.RejectRole)
        box.setAttribute(Qt.WA_DeleteOnClose, True)
        self.update_prompt = box
        def chosen(_result):
            self.update_prompt = None
            if box.clickedButton() is accept and not self.closing:
                self.download_update(info)
        box.finished.connect(chosen)
        box.open()

    def download_update(self, info):
        if self.update_download_job and not self.update_download_job.done():
            return
        dialog = QProgressDialog(self.l.t("Downloading update…"), self.l.t("Cancel download"),
            0, 1000, self.window)
        dialog.setWindowTitle(self.l.t("Update available"))
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(self.cancel_update_download)
        dialog.show()
        self.update_dialog = dialog
        self.window.set_update_status("Downloading update…")
        job = self.engine._submit(self.update_service.download(info,
            on_progress=lambda received, total: self.update_events.progress.emit(received, total)))
        self.update_download_job = job
        def finished(future):
            try:
                path, error = future.result(), None
            except BaseException as exc:
                path, error = None, exc
            self.update_events.downloaded.emit(path, error)
        job.add_done_callback(finished)

    def cancel_update_download(self):
        if self.update_download_job and not self.update_download_job.done():
            self.update_download_job.cancel()

    def update_progress(self, received, total):
        if self.closing or not self.update_dialog or not total:
            return
        percent = min(100, max(0, int(received * 100 / total)))
        self.update_dialog.setValue(percent * 10)
        self.update_dialog.setLabelText(self.l.t("Downloading update…") + f' {percent}%')
        self.window.set_update_status("Downloading update…", f' {percent}%')

    def update_downloaded(self, path, error):
        if self.closing:
            return
        if self.update_dialog:
            self.update_dialog.close()
            self.update_dialog.deleteLater()
            self.update_dialog = None
        if error is not None:
            if isinstance(error, CancelledError) or isinstance(error, asyncio.CancelledError):
                self.window.set_update_status("Update download canceled.")
            elif isinstance(error, UpdateError) and 'checksum' in str(error).lower():
                self.window.set_update_status("Update verification failed. The current app is unchanged.")
            else:
                self.window.set_update_status("Update download failed. Try again later.")
            logging.getLogger('arabic_lens').warning('Update download did not complete: %s', type(error).__name__)
            return
        self.window.set_update_status("Installing update…")
        async def start_installer():
            return await asyncio.to_thread(self.update_service.launch_installer, path,
                executable=sys.executable, data_directory=self.service.directory)
        job = self.engine._submit(start_installer())
        self.update_install_job = job
        def finished(future):
            try:
                process, failure = future.result(), None
            except BaseException as exc:
                process, failure = None, exc
            self.update_events.launched.emit(process, failure)
        job.add_done_callback(finished)

    def update_launched(self, process, error):
        if self.closing:
            return
        if error is not None or process is None:
            self.window.set_update_status("Update installation could not start. The current app is unchanged.")
            logging.getLogger('arabic_lens').warning('Update installer did not launch: %s',
                type(error).__name__ if error is not None else 'Unknown')
            return
        self.qt.quit()

    def action(self, action):
        if action == "watch":
            self.paused = False
            if self.engine.watch:
                self.engine.set_watch(False)
            else:
                self.start_watch_choice(self.settings.watch_startup)
        elif action == "quick" and not self.paused:
            if self.selector.windows:
                self.selector.cancel()
                self.capture_request += 1
                return
            self.capture_request += 1
            self.selection_purpose = 'quick'
            self.selection_context = active_window()
            self.selection_window = window_identity(self.selection_context[0]) if self.selection_context else None
            if self.engine.watch:
                # Manual capture does not invalidate unchanged Watch zones.
                for key in list(self.overlays.windows):
                    if key == 'manual' or key.startswith('manual:') or key == 'manual-notice':
                        self.overlays.remove(key, immediate=True)
                self.source_monitor.forget('manual')
                self.source_monitor.forget('manual-notice')
            else:
                self.engine.hide()
                self.overlays.clear(immediate=True)
                self.source_monitor.clear()
            self.window.hide()
            self.selector.begin()
        elif action == 'select_watch_area' and not self.paused:
            self.begin_area_setup([])
        elif action == 'add_zone' and not self.paused:
            self.begin_area_setup(self.settings.watch_areas)
        elif action == 'clear_watch_area':
            self.settings.watch_region = None
            self.settings.watch_areas = []
            self.settings.watch_previous = []
            self.settings.watch_app = ''
            self.settings.watch_previous_app = ''
            self.settings.watch_origin = None
            self.settings.watch_previous_origin = None
            self.service.save()
            self.window.rebuild(3)
            if self.engine.watch:
                self.engine.set_watch(True)
        elif action == "repeat" and not self.paused:
            if self.settings.last_region:
                self.recapture(Rect(*self.settings.last_region))
            else:
                self.report("Select a region with Quick Translate first.")
        elif action == "hide":
            self.capture_request += 1
            self.selector.cancel()
            self.engine.hide()
        elif action == "pause":
            if self.paused:
                self.paused = False
                self.engine.set_watch(self.paused_watch)
            else:
                self.paused_watch = self.engine.watch
                self.paused = True
                self.engine.hide()
                self.engine.set_watch(False)
            self.rebuild_tray()
        elif action == "pin":
            if not self.settings.last_region:
                self.report("Select a region with Quick Translate first.")
                return
            name, ok = QInputDialog.getText(self.window, self.l.t("Pin last region"), self.l.t("Region name"))
            if ok and name.strip():
                self.settings.pinned_regions.append({"name": name.strip(), "rect": self.settings.last_region.copy()})
                self.settings.pinned_regions = self.settings.pinned_regions[-20:]
                self.service.save()
                self.window.regions_list.addItem(name.strip())
        elif action.startswith("region:"):
            index = int(action.split(":")[1])
            if 0 <= index < len(self.settings.pinned_regions) and not self.paused:
                self.window.hide()
                self.recapture(Rect(*self.settings.pinned_regions[index]["rect"]))
        elif action.startswith("unpin:"):
            index = int(action.split(":")[1])
            if 0 <= index < len(self.settings.pinned_regions):
                del self.settings.pinned_regions[index]
                self.service.save()
                self.window.regions_list.takeItem(index)

    def selected(self, rect):
        if self.selection_purpose == 'watch':
            self.settings.watch_region = [rect.x, rect.y, rect.w, rect.h]
            self.service.save()
            self.selection_purpose = 'quick'
            self.selection_restore_watch = False
            self.window.rebuild(3)
            QTimer.singleShot(120, lambda: self.engine.set_watch(True))
            return
        self.settings.last_region = [rect.x, rect.y, rect.w, rect.h]
        self.service.save()
        title = self.selection_context[2] if getattr(self, "selection_context", None) else ""
        # Let the compositor remove selection dimming before the capture happens.
        source = getattr(self, 'selection_window', None)
        self.schedule_capture(rect, title, source)

    def set_watch_startup(self, choice):
        if choice in ('fullscreen', 'new', 'previous', 'presets'):
            self.settings.watch_startup = choice
            self.service.save()

    def start_watch_choice(self, choice):
        if choice == 'fullscreen':
            self.start_fullscreen()
        elif choice == 'presets':
            self.show_watch_presets()
        elif choice == 'previous':
            self.start_with_areas(self.settings.watch_previous)
        else:
            self.begin_area_setup([])

    def start_fullscreen(self):
        self.hide_for_watch()
        self.settings.watch_fullscreen = True
        self.service.save()
        self.window.rebuild(3)
        QTimer.singleShot(120, lambda: self.engine.set_watch(True))

    def show_watch_presets(self, selected=-1):
        self.window.hide()
        if self.preset_dialog is None:
            dialog = WatchPresetsDialog(self.l)
            dialog.create_requested.connect(self.choose_preset_target)
            dialog.delete_requested.connect(self.delete_watch_preset)
            dialog.preset_requested.connect(self.start_watch_preset)
            dialog.new_requested.connect(lambda: self.begin_area_setup([]))
            dialog.previous_requested.connect(lambda: self.start_with_areas(self.settings.watch_previous))
            dialog.dismissed.connect(self.close_watch_presets)
            self.preset_dialog = dialog
        self.preset_dialog.set_presets(self.settings.watch_presets, selected)
        self.preset_dialog.show()
        self.preset_dialog.raise_()
        self.preset_dialog.activateWindow()

    def close_watch_presets(self):
        if self.preset_dialog:
            self.preset_dialog.hide()
        if not self.closing and not self.engine.watch and not self.selector.windows:
            self.show_settings(3)

    def delete_watch_preset(self, index):
        if not 0 <= index < len(self.settings.watch_presets):
            return
        del self.settings.watch_presets[index]
        self.service.save()
        self.preset_dialog.set_presets(self.settings.watch_presets, min(index, len(self.settings.watch_presets)-1))

    def choose_preset_target(self):
        self.pending_preset_name = ''
        self.preset_dialog.hide()
        self.name_dialog = PresetNameDialog(self.l)
        self.name_dialog.chosen.connect(self.preset_name_chosen)
        self.name_dialog.cancelled.connect(lambda: self.show_watch_presets(self.preset_dialog.list.currentRow()))
        self.name_dialog.show()

    def preset_name_chosen(self, name):
        self.pending_preset_name = name
        targets = open_windows()
        self.target_dialog = WatchTargetDialog(self.l, targets)
        self.target_dialog.chosen.connect(lambda target: self.begin_area_setup([], preset=True, target=target))
        self.target_dialog.cancelled.connect(self.preset_target_cancelled)
        self.target_dialog.show()

    def preset_target_cancelled(self):
        self.pending_preset_name = ''
        self.show_watch_presets(self.preset_dialog.list.currentRow())

    def start_watch_preset(self, index):
        if not 0 <= index < len(self.settings.watch_presets):
            return
        preset = self.settings.watch_presets[index]
        self.start_with_areas(preset['areas'])

    def start_with_areas(self, areas):
        self.hide_for_watch()
        self.settings.watch_fullscreen = False
        self.settings.watch_areas = [list(area) for area in areas]
        self.settings.watch_previous = [list(area) for area in areas]
        # The app chooser is only a way to reveal the target during setup.
        # Saved zones are screen areas and must never be locked to that EXE.
        self.settings.watch_app = ''
        self.settings.watch_previous_app = ''
        self.settings.watch_origin = None
        self.settings.watch_previous_origin = None
        self.settings.watch_region = self.settings.watch_areas[0] if len(self.settings.watch_areas) == 1 else None
        self.service.save()
        self.window.rebuild(3)
        # The app must leave the foreground before Watch samples its first frame.
        QTimer.singleShot(120, lambda: self.engine.set_watch(True))

    def hide_for_watch(self):
        # Enabling from Settings can otherwise leave the shell/taskbar in the
        # foreground. The topmost external app is only brought back into focus;
        # it is never saved as an executable restriction for these screen zones.
        visible = getattr(self.window, 'isVisible', lambda: False)()
        preset_visible = self.preset_dialog and getattr(self.preset_dialog, 'isVisible', lambda: False)()
        targets = open_windows() if visible or preset_visible else []
        if self.preset_dialog:
            self.preset_dialog.hide()
        self.window.hide()
        if targets:
            QTimer.singleShot(60, lambda hwnd=targets[0]['hwnd']: focus_chosen_window(hwnd))

    def begin_area_setup(self, existing, preset=False, target=None):
        if self.selector.windows:
            return
        self.selection_purpose = 'watch_preset' if preset else 'watch_multi'
        self.selection_restore_watch = self.engine.watch
        self.capture_request += 1
        self.engine.set_watch(False)
        self.overlays.clear(immediate=True)
        self.source_monitor.clear()
        self.selection_context = active_window()
        hwnd = target['hwnd'] if target else (self.selection_context[0] if self.selection_context else None)
        self.selection_window = window_identity(hwnd) if hwnd else None
        self.selection_target = target
        self.selection_existing = [Rect(*area) if isinstance(area, list) else area for area in existing]
        self.window.hide()
        if self.preset_dialog:
            self.preset_dialog.hide()
        QTimer.singleShot(120, self.begin_multi_selection)

    def begin_multi_selection(self):
        if self.closing or self.selection_purpose not in ('watch_multi', 'watch_preset'):
            return
        if self.selection_target and self.selection_target.get('hwnd'):
            focus_chosen_window(self.selection_target['hwnd'])
        elif self.selection_window:
            restore_capture_focus(self.selection_window)
        elif not self.selection_context:
            active = active_window()
            self.selection_window = window_identity(active[0]) if active else None
        self.selector.begin_multi(self.selection_existing, self.watch_areas_selected,
            self.selection_cancelled, 'Preset setup' if self.selection_purpose == 'watch_preset' else 'Watch area setup')

    def watch_areas_selected(self, areas):
        serialized = [[a.x, a.y, a.w, a.h] for a in areas]
        source = window_at_rect(areas[0]) or self.selection_window
        if source:
            # The selector was foreground while the user pressed ✓. Return to
            # the selected window so a normal Create New starts scanning now.
            focus_chosen_window(source[0])
        # A zone follows its screen coordinates. Choosing an app during preset
        # creation only focuses it for drawing; it is not a Watch restriction.
        if self.selection_purpose == 'watch_preset':
            name = self.pending_preset_name or 'Watch preset'
            names = {item['name'] for item in self.settings.watch_presets}
            base = name[:42]
            index = 1
            while name in names:
                index += 1; name = f'{base} {index}'
            self.settings.watch_presets.append({'name': name, 'areas': serialized})
            self.service.save()
            self.selection_purpose = 'quick'
            self.pending_preset_name = ''
            self.show_watch_presets(len(self.settings.watch_presets)-1)
        else:
            self.selection_purpose = 'quick'
            self.start_with_areas(serialized)

    def begin_watch_selection(self):
        if self.selection_purpose != 'watch' or self.closing:
            return
        active = active_window()
        self.selection_context = active
        self.selection_window = window_identity(active[0]) if active else None
        self.selector.begin()

    def selection_cancelled(self):
        if self.selection_purpose not in ('watch', 'watch_multi', 'watch_preset'):
            return
        purpose = self.selection_purpose
        self.selection_purpose = 'quick'
        if self.selection_restore_watch:
            self.engine.set_watch(True)
        self.selection_restore_watch = False
        if not self.closing:
            if purpose == 'watch_preset':
                self.pending_preset_name = ''
                self.show_watch_presets(self.preset_dialog.list.currentRow() if self.preset_dialog else -1)
            else:
                self.show_settings(3)

    def schedule_capture(self, rect, title, source):
        request = self.capture_request
        def capture(attempt=0):
            if request != self.capture_request or self.selector.windows:
                return
            if source and not restore_capture_focus(source):
                # A closing selector may briefly own focus. Never silently
                # discard the translation if Windows refuses focus restoration.
                if attempt < 3:
                    QTimer.singleShot(50, lambda: capture(attempt + 1))
                    return
            actual_source, actual_title = source, title
            # Bind the OCR to what is actually beneath the selected rectangle.
            # This also handles Alt+Q launched from Settings or the tray.
            revealed = window_at_rect(rect)
            if revealed and actual_source is None:
                actual_source = revealed
            if not actual_title:
                active = active_window()
                actual_title = active[2] if active else ''
            self.engine.translate_region(rect, actual_title, actual_source)
        QTimer.singleShot(120, capture)

    def recapture(self, rect):
        self.capture_request += 1
        if not any(native.intersect(rect) == rect for screen, native in display_maps()):
            self.report("This selection is outside the connected displays.")
            return
        self.overlays.clear(immediate=True)
        self.source_monitor.clear()
        self.window.hide()
        active = active_window()
        source = window_identity(active[0]) if active else None
        self.schedule_capture(rect, active[2] if active else "", source)

    def show_translation(self, result):
        if result.id.startswith('watch-') and result.source_window and self.engine.app_blocks.blocked(result.source_window[0]):
            return
        if self.source_monitor.accept(result):
            if result.source.strip() == result.arabic.strip() and not result.notice:
                self.overlays.remove(result.id, immediate=True)
            else:
                self.overlays.show(result)
            self.progress.complete(result)

    def manual_failed(self, code, rect, source):
        result = Translation('manual-notice', '', self.l.status(code), rect, source_window=source, notice=True)
        self.show_translation(result)

    def forget_overlay(self, key):
        self.progress.remove(key)
        self.engine.forget_anchor(key)
        if hasattr(self, 'source_monitor'):
            self.source_monitor.forget_exact(key)

    def source_invalidated(self, invalidation):
        # A closed or moved source removes only translations attached to that
        # window. A Quick capture from another app must not reset Watch zones.
        # Mere clicks or focus changes do not invalidate source identity.
        _identity, keys = invalidation
        for key in keys:
            self.overlays.remove(key, immediate=True)
            self.progress.remove(key)

    def watch_changed(self, enabled):
        self.settings.last_watch = enabled
        self.window.update_watch(enabled)
        self.tray.setIcon(lens_icon(active=enabled))
        self.rebuild_tray()

    def on_status(self, code):
        self.report(self.l.status(code))

    def report(self, text):
        if hasattr(self, "window"):
            self.window.status_label.setText(self.l.t(text))
        if hasattr(self, "tray"):
            self.tray.setToolTip(self.l.t("Arabic Lens") + " · " + self.l.t(text))
        # No gameplay toast storms. Status is available in Settings and tray tooltip.

    def apply(self, values):
        candidate = copy.deepcopy(self.settings)
        page = self.window.stack.currentIndex()
        changed_language = values.get("language") != self.settings.language
        try:
            for key, value in values.items():
                if key == "overlay":
                    for name, content in value.items():
                        setattr(candidate.overlay, name, content)
                elif key in candidate.__dataclass_fields__:
                    setattr(candidate, key, value)
            candidate.overlay.persistence = True
            if candidate.endpoint and candidate.provider != 'Built-in offline':
                validate_endpoint(candidate.endpoint)
            if values["remove_secret"]:
                candidate.api_key = ""
            elif values["secret"]:
                candidate.api_key = protect_secret(values["secret"])
            if candidate.shortcuts != self.settings.shortcuts:
                self.hotkeys.register(candidate.shortcuts, strict=True)
            elif not self.hotkeys.registered:
                self.hotkeys.register(candidate.shortcuts)
            if candidate.start_windows != self.settings.start_windows:
                set_startup(candidate.start_windows)
        except (ValueError, OSError, TranslationError) as exc:
            self.report("Shortcut unavailable. Choose another combination." if isinstance(exc, ValueError) else "Connect a translation provider in Settings.")
            return
        was_watch = self.engine.watch
        blocks_changed = candidate.blocked_apps != self.settings.blocked_apps
        self.settings.__dict__.update(candidate.__dict__)
        self.settings.first_run = False
        self.service.save()
        if self.settings.auto_check_updates and not self.qt.property('smokeTest'):
            if not self.update_timer.isActive():
                self.update_timer.start()
                QTimer.singleShot(0, self.check_updates)
        else:
            self.update_timer.stop()
        self.store.prune()
        self.engine.hide()
        if blocks_changed:
            self.overlays.clear(immediate=True)
            self.source_monitor.clear()
            self.engine.invalidate_source()
        if was_watch:
            self.engine.set_watch(True)
        if not self.settings.debug:
            self.clear_debug()
        self.window.rebuild(page)
        self.rebuild_tray()
        self.report("Changes saved")
        if values["test"]:
            self.report("Translating…")
            self.window.translation_feedback.setText(self.l.t("Translating…"))
            self.engine.test_provider(values.get('test_text') or None)

    def tested(self, success, result):
        local = self.settings.provider == 'Built-in offline'
        message = 'Translation is ready' if local else 'Connection successful'
        self.report(message if success else self.l.status(result))
        self.window.translation_feedback.setText(result if success else self.l.status(result))
        if success:
            self.window.status_label.setText(self.l.t(message))

    def clear_debug(self):
        for window in self.debug_windows:
            window.close()
            window.deleteLater()
        self.debug_windows.clear()
        if self.debug_text:
            self.debug_text.close()
            self.debug_text.deleteLater()
            self.debug_text = None

    def clear_overlays(self):
        self.overlays.clear()
        self.progress.clear()
        self.source_monitor.clear()
        self.clear_debug()

    def diagnostics(self, info):
        if not self.settings.debug:
            return
        if "regions" in info:
            for window in self.debug_windows:
                window.close()
                window.deleteLater()
            self.debug_windows.clear()
            grouped = {}
            for key, rect, revision in info["regions"]:
                screen, logical = physical_to_logical(rect)
                grouped.setdefault(screen, []).append((key, logical, revision))
            for screen, regions in grouped.items():
                window = DiagnosticOverlay(screen, regions)
                window.show()
                self.debug_windows.append(window)
        else:
            if self.debug_text is None:
                self.debug_text = QTextEdit()
                self.debug_text.setWindowTitle("Arabic Lens · Developer diagnostics")
                self.debug_text.setReadOnly(True)
                self.debug_text.resize(560, 300)
                self.debug_text.document().setMaximumBlockCount(200)
                self.debug_text.show()
            self.debug_text.append(str(info))

    def shutdown(self):
        if self.closing:
            return
        self.closing = True
        self.update_timer.stop()
        for job in (self.update_check_job, self.update_download_job):
            if job and not job.done():
                job.cancel()
        self.selector.cancel()
        self.overlays.clear()
        self.progress.clear()
        self.clear_debug()
        self.settings.last_watch = self.engine.watch
        self.service.save()
        self.hotkeys.close()
        self.qt.removeNativeEventFilter(self.hotkeys)
        self.engine.close()
        self.store.close()
        self.tray.hide()
        self.lock.unlock()


def run(directory=None, minimized=False, smoke=False):
    qt = QApplication.instance() or QApplication([])
    qt.setApplicationName("Arabic Lens")
    qt.setOrganizationName("ArabicLens")
    qt.setQuitOnLastWindowClosed(False)
    qt.setProperty('smokeTest', smoke)
    try:
        app = Application(qt, directory, minimized)
    except RuntimeError as exc:
        QMessageBox.information(None, "Arabic Lens", str(exc))
        return 1
    if smoke:
        path = Path(directory or "artifacts")
        path.mkdir(parents=True, exist_ok=True)
        def screenshot():
            app.window.grab().save(str(path / "home.png"))
            app.window.navigate(4)
            QTimer.singleShot(300, overlay_shot)
        def overlay_shot():
            app.window.grab().save(str(path / "overlay-settings.png"))
            app.settings.language = "ar"
            app.window.rebuild(0)
            QTimer.singleShot(300, arabic_shot)
        def arabic_shot():
            app.window.grab().save(str(path / "home-arabic.png"))
            app.window.navigate(2)
            app.window.grab().save(str(path / 'translation-simple.png'))
            if app.settings.provider == 'Built-in offline':
                app.engine.tested.connect(local_smoke_result)
                app.engine.test_provider()
            else:
                qt.quit()
        def local_smoke_result(success, result):
            import json
            (path / 'offline-translation.json').write_text(json.dumps(
                {'success': success, 'result': result}, ensure_ascii=False), encoding='utf-8')
            qt.exit(0 if success else 1)
        QTimer.singleShot(800, screenshot)
    return qt.exec()
