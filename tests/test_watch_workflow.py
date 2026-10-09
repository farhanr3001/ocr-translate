import asyncio
from types import SimpleNamespace

import numpy as np
from PySide6.QtWidgets import QApplication, QPushButton

from arabic_lens.config import Settings, SettingsService
from arabic_lens.models import Rect
from arabic_lens.watch_dialogs import WatchPresetsDialog, PresetNameDialog
from arabic_lens.localization import LocalizationService
from arabic_lens.selection import SelectionManager, SelectionWindow
from arabic_lens.engine import Engine, whole_screen_tiles
from arabic_lens.detection import RegionTracker
from arabic_lens.overlay import OverlayManager
from arabic_lens.storage import TranslationStore
from arabic_lens.ui import SettingsWindow
from arabic_lens.app import Application


def test_saved_watch_zones_and_presets_are_distinct(tmp_path):
    service = SettingsService(tmp_path)
    service.settings.watch_areas = [[100, 100, 200, 80], [400, 100, 200, 80]]
    service.settings.watch_previous = [area.copy() for area in service.settings.watch_areas]
    service.settings.watch_origin = [0, 0, 800, 600]
    service.settings.watch_previous_origin = [0, 0, 800, 600]
    service.settings.watch_presets = [{'name': 'Dressmaker', 'app': 'C:/Games/Dressmaker.exe',
        'areas': [[100, 100, 200, 80]], 'origin': [0, 0, 800, 600]}]
    service.settings.watch_startup = 'presets'
    service.save()
    loaded = SettingsService(tmp_path).settings
    assert loaded.watch_previous == [[100, 100, 200, 80], [400, 100, 200, 80]]
    assert loaded.watch_presets[0]['areas'] == [[100, 100, 200, 80]]
    assert loaded.watch_startup == 'presets'
    service.settings.watch_areas = [[50, 50, 300, 120]]
    service.settings.watch_previous = [[50, 50, 300, 120]]
    service.save()
    assert SettingsService(tmp_path).settings.watch_presets[0]['areas'] == [[100, 100, 200, 80]]


def test_watch_preset_dialog_empty_selection_and_delete_control():
    QApplication.instance() or QApplication([])
    dialog = WatchPresetsDialog(LocalizationService(Settings()))
    try:
        assert dialog.display.currentWidget() is dialog.empty
        assert not dialog.delete_button.isEnabled()
        assert not dialog.start.isEnabled()
        dialog.set_presets([{'name': 'Dressmaker', 'areas': [[1, 2, 300, 200]]}])
        assert dialog.display.currentWidget() is dialog.list
        assert not dialog.delete_button.isEnabled()
        dialog.list.setCurrentRow(0)
        assert dialog.delete_button.isEnabled() and dialog.start.isEnabled()
        dialog.set_presets([])
        assert not dialog.delete_button.isEnabled() and not dialog.start.isEnabled()
    finally:
        dialog.deleteLater()


def test_preset_name_is_required_before_target_choice():
    QApplication.instance() or QApplication([])
    dialog = PresetNameDialog(LocalizationService(Settings()))
    names = []
    dialog.chosen.connect(names.append)
    try:
        buttons = dialog.findChildren(QPushButton)
        continue_button = next(button for button in buttons if button.text() == 'Continue')
        assert not continue_button.isEnabled()
        dialog.name.setText('  My X zones  ')
        assert continue_button.isEnabled()
        dialog.accept_name()
        assert names == ['My X zones']
    finally:
        dialog.deleteLater()


def test_plus_asks_for_name_before_optional_focus_target(monkeypatch):
    import arabic_lens.app as app_module
    QApplication.instance() or QApplication([])
    app = Application.__new__(Application)
    app.l = LocalizationService(Settings())
    app.pending_preset_name = ''
    app.target_dialog = None
    app.preset_dialog = SimpleNamespace(hide=lambda: None, list=SimpleNamespace(currentRow=lambda: -1))
    app.show_watch_presets = lambda index: None
    started = []
    app.begin_area_setup = lambda areas, preset=False, target=None: started.append((areas, preset, target))
    monkeypatch.setattr(app_module, 'open_windows', lambda: [{'hwnd': 42, 'title': 'Browser', 'path': 'C:/Browser.exe'}])
    Application.choose_preset_target(app)
    assert app.name_dialog and app.target_dialog is None
    app.name_dialog.name.setText('My pages')
    app.name_dialog.accept_name()
    assert app.pending_preset_name == 'My pages'
    assert app.target_dialog is not None and not started
    app.target_dialog.list.setCurrentRow(0)
    app.target_dialog.accept_target()
    assert started == [([], True, {'hwnd': 42, 'title': 'Browser', 'path': 'C:/Browser.exe'})]


def test_selector_controls_are_small_centered_and_not_crosshair():
    from PySide6.QtCore import Qt
    qt = QApplication.instance() or QApplication([])
    window = SelectionWindow(qt.primaryScreen(), LocalizationService(Settings()))
    window.multi = True
    try:
        assert abs(window.done_rect().center().x() - window.width() // 2) < 45
        assert window.done_rect().width() == 36 and window.cancel_rect().width() == 36
        window.update_cursor(window.done_rect().center())
        assert window.cursor().shape() == Qt.PointingHandCursor
        window.update_cursor(window.cancel_rect().center())
        assert window.cursor().shape() == Qt.PointingHandCursor
        window.update_cursor(window.rect().bottomLeft())
        assert window.cursor().shape() == Qt.CrossCursor
    finally:
        window.deleteLater()


def test_watch_startup_boxes_are_exclusive_and_both_activation_paths_share_choice(tmp_path):
    QApplication.instance() or QApplication([])
    settings = Settings()
    store = TranslationStore(tmp_path / 'ui.db', settings)
    window = SettingsWindow(settings, LocalizationService(settings), store)
    changed = []
    window.watch_startup_changed.connect(lambda value: (changed.append(value), setattr(settings, 'watch_startup', value)))
    try:
        choices = window.watch_choices.buttons()
        assert [item.isChecked() for item in choices] == [False, True, False, False]
        choices[3].click()
        assert [item.isChecked() for item in choices] == [False, False, False, True]
        choices[2].click()
        assert [item.isChecked() for item in choices] == [False, False, True, False]
        assert changed == ['presets', 'previous']
        app = Application.__new__(Application)
        app.settings = settings
        app.paused = False
        app.engine = SimpleNamespace(watch=False)
        started = []
        app.start_watch_choice = started.append
        Application.action(app, 'watch')  # Both button and Alt+W emit this action.
        assert started == ['previous']
        choices[0].click()
        assert [item.isChecked() for item in choices] == [True, False, False, False]
        Application.action(app, 'watch')
        assert started == ['previous', 'fullscreen']
    finally:
        window.deleteLater()
        store.close()


def test_multi_selection_saves_all_zones_and_cancel_leaves_previous_set():
    QApplication.instance() or QApplication([])
    results, cancels = [], []
    manager = SelectionManager(LocalizationService(Settings()), lambda rect: None)
    manager.begin_multi([Rect(1, 2, 80, 40)], results.append, lambda: cancels.append(True))
    assert manager.mode == 'multi'
    manager.add_area(Rect(120, 2, 80, 40))
    manager.add_area(Rect(121, 3, 78, 38))  # Near-identical overlap is ignored.
    manager.finish_multi()
    assert results == [[Rect(1, 2, 80, 40), Rect(120, 2, 80, 40)]]
    manager.begin_multi([], results.append, lambda: cancels.append(True))
    manager.add_area(Rect(20, 20, 90, 40))
    manager.cancel()
    assert len(results) == 1 and cancels == [True]


def test_preset_creation_does_not_change_previous_until_preset_is_started():
    app = Application.__new__(Application)
    app.settings = Settings(watch_previous=[[10, 10, 80, 40]])
    app.selection_window = (7, 77, Rect(0, 0, 800, 600))
    app.selection_target = {'path': 'C:/Games/Dressmaker.exe', 'title': 'Dressmaker'}
    app.selection_purpose = 'watch_preset'
    app.pending_preset_name = 'My custom dialogue zones'
    saved, shown, started = [], [], []
    app.service = SimpleNamespace(save=lambda: saved.append(True))
    app.show_watch_presets = shown.append
    app.start_with_areas = lambda *args: started.append(args)
    Application.watch_areas_selected(app, [Rect(30, 40, 200, 100), Rect(300, 40, 200, 100)])
    assert app.settings.watch_previous == [[10, 10, 80, 40]]
    assert app.settings.watch_presets[0]['areas'] == [[30, 40, 200, 100], [300, 40, 200, 100]]
    assert app.settings.watch_presets[0]['name'] == 'My custom dialogue zones'
    assert 'app' not in app.settings.watch_presets[0]
    assert shown == [0] and saved
    Application.start_watch_preset(app, 0)
    assert started == [([[30, 40, 200, 100], [300, 40, 200, 100]],)]


def test_create_new_starts_without_app_identity_or_old_preset_binding(monkeypatch):
    import arabic_lens.app as app_module
    from PySide6.QtTest import QTest
    qt = QApplication.instance() or QApplication([])
    app = Application.__new__(Application)
    app.settings = Settings(watch_app='C:/OldGame.exe', watch_origin=[0, 0, 800, 600])
    app.preset_dialog = None
    app.window = SimpleNamespace(hide=lambda: None, rebuild=lambda page: None)
    app.service = SimpleNamespace(save=lambda: None)
    states = []
    app.engine = SimpleNamespace(watch=False, set_watch=lambda enabled: states.append(enabled))
    app.selection_purpose = 'watch_multi'
    app.selection_window = None
    app.selection_target = None
    monkeypatch.setattr(app_module, 'window_at_rect', lambda rect: None)
    Application.watch_areas_selected(app, [Rect(100, 100, 180, 80)])
    QTest.qWait(180); qt.processEvents()
    assert states == [True]
    assert app.settings.watch_areas == [[100, 100, 180, 80]]
    assert app.settings.watch_previous == app.settings.watch_areas
    assert app.settings.watch_app == '' and app.settings.watch_origin is None


def test_new_area_uses_window_under_selection_over_stale_explorer_focus(monkeypatch):
    import arabic_lens.app as app_module
    app = Application.__new__(Application)
    app.settings = Settings()
    app.selection_window = (11, 1, Rect(0, 1032, 1920, 48))  # Old focused taskbar.
    app.selection_target = None
    app.selection_purpose = 'watch_multi'
    app.start_with_areas = lambda areas: None
    selected = (22, 2, Rect(0, 0, 1920, 1032))
    focused = []
    monkeypatch.setattr(app_module, 'window_at_rect', lambda rect: selected)
    monkeypatch.setattr(app_module, 'focus_chosen_window', lambda hwnd: focused.append(hwnd))
    Application.watch_areas_selected(app, [Rect(309, 190, 274, 570)])
    assert focused == [22]


def test_create_new_hides_settings_before_opening_selector(monkeypatch):
    import arabic_lens.app as app_module
    from PySide6.QtTest import QTest
    qt = QApplication.instance() or QApplication([])
    events = []
    app = Application.__new__(Application)
    app.settings = Settings()
    app.capture_request = 0
    app.closing = False
    app.selection_purpose = 'quick'
    app.preset_dialog = None
    app.window = SimpleNamespace(hide=lambda: events.append('hide'))
    app.engine = SimpleNamespace(watch=False, set_watch=lambda value: events.append(f'watch:{value}'))
    app.overlays = SimpleNamespace(clear=lambda **kwargs: None)
    app.source_monitor = SimpleNamespace(clear=lambda: None)
    app.selector = SimpleNamespace(windows=[], begin_multi=lambda *args: events.append('selector'))
    monkeypatch.setattr(app_module, 'active_window', lambda: None)
    Application.start_watch_choice(app, 'new')
    QTest.qWait(180); qt.processEvents()
    assert events.index('hide') < events.index('selector')
    assert events[0] == 'watch:False'


def test_preset_target_is_brought_forward_before_selector(monkeypatch):
    import arabic_lens.app as app_module
    app = Application.__new__(Application)
    app.closing = False
    app.selection_purpose = 'watch_preset'
    app.selection_target = {'hwnd': 1234}
    app.selection_window = (1234, 9, Rect(0, 0, 800, 600))
    app.selection_existing = []
    app.selector = SimpleNamespace(begin_multi=lambda *args: selected.append(args))
    selected, focused = [], []
    monkeypatch.setattr(app_module, 'focus_chosen_window', lambda hwnd: focused.append(hwnd))
    Application.begin_multi_selection(app)
    assert focused == [1234] and selected


def test_watch_scanner_captures_each_zone_only_when_its_preview_changes():
    class Capture:
        def __init__(self, preview=False):
            self.calls = []
            self.version = {10: 1, 300: 1}
            self.preview = preview
        def capture(self, bounds):
            self.calls.append(bounds)
            return np.full((18, 24, 4), self.version[bounds.x], dtype=np.uint8)
    full, preview = Capture(), Capture(preview=True)
    fake = SimpleNamespace(
        settings=Settings(watch_areas=[[10, 10, 100, 100], [300, 10, 100, 100]]),
        zone_states={}, tracker=RegionTracker(), preview_capture=preview, capture=full,
        anchors=SimpleNamespace(items={}), detector=SimpleNamespace(detect=lambda image, sensitivity: []),
        jobs={}, backoff=0, generation=1)
    one, two = Rect(10, 10, 100, 100), Rect(300, 10, 100, 100)
    async def scan():
        await Engine._scan_zone(fake, 0, one, 1, 'Game', np, 0)
        await Engine._scan_zone(fake, 1, two, 1, 'Game', np, 0)
        await Engine._scan_zone(fake, 0, one, 1, 'Game', np, 0)
        await Engine._scan_zone(fake, 1, two, 1, 'Game', np, 0)
        preview.version[300] = 50
        await Engine._scan_zone(fake, 0, one, 1, 'Game', np, 0)
        await Engine._scan_zone(fake, 1, two, 1, 'Game', np, 0)
    asyncio.run(scan())
    assert full.calls == [one, two, two]
    assert len(preview.calls) == 6


def test_scroll_zone_does_not_reprocess_static_zone_and_static_overlay_stays_alive():
    class Capture:
        def __init__(self):
            self.calls = []
            self.version = {10: 1, 300: 1}
        def capture(self, bounds):
            self.calls.append(bounds)
            return np.full((18, 24, 4), self.version[bounds.x], dtype=np.uint8)
    preview, full = Capture(), Capture()
    alive = []
    anchor = SimpleNamespace(expires=float('inf'))
    fake = SimpleNamespace(settings=Settings(watch_areas=[[10, 10, 100, 100], [300, 10, 100, 100]]),
        zone_states={}, tracker=RegionTracker(), preview_capture=preview, capture=full,
        anchors=SimpleNamespace(items={'watch-0-1': anchor}),
        detector=SimpleNamespace(detect=lambda image, sensitivity: [Rect(1, 1, 18, 10)]),
        jobs={}, backoff=0, generation=1, region_alive=SimpleNamespace(emit=alive.append),
        _follow_sources=lambda *args, **kwargs: None)
    one, two = Rect(10, 10, 100, 100), Rect(300, 10, 100, 100)
    async def scan():
        await Engine._scan_zone(fake, 0, one, 1, 'Game', np, 0)
        await Engine._scan_zone(fake, 1, two, 1, 'Game', np, 0)
        static = fake.zone_states[0]['tracker'].regions['1']
        static.processed = True
        static.delivered.add('home')
        preview.version[300] = 50
        await Engine._scan_zone(fake, 1, two, 1, 'Game', np, 0)
        await Engine._scan_zone(fake, 0, one, 1, 'Game', np, 0)
    asyncio.run(scan())
    assert full.calls == [one, two, two]
    assert fake.zone_states[0]['tracker'].regions['1'].revision == 0
    assert alive == ['watch-0-1'] and anchor.expires == float('inf')
    manager = OverlayManager(fake.settings, lambda text: None)
    starts = []
    manager.windows = {'watch-0-1': SimpleNamespace(appearance=SimpleNamespace(persistence=True, duration=12),
        closing=False, timer=SimpleNamespace(start=starts.append))}
    manager.keep_alive_group('watch-0-1')
    # Translation overlays have no expiry timer, so activity in the other
    # watch area must not restart one.
    assert starts == []


def test_changes_outside_all_watch_areas_never_reprocess_selected_text():
    screen = np.zeros((90, 220, 4), dtype=np.uint8)
    selected = Rect(10, 10, 70, 45)
    screen[10:55, 10:80] = 100

    class Capture:
        def __init__(self):
            self.calls = []

        def capture(self, bounds):
            self.calls.append(bounds)
            return screen[bounds.y:bounds.bottom, bounds.x:bounds.right].copy()

    preview, full = Capture(), Capture()
    detector_calls = []

    def detect(image, sensitivity):
        detector_calls.append(True)
        return [Rect(4, 4, 55, 20)]

    fake = SimpleNamespace(settings=Settings(watch_areas=[[10, 10, 70, 45]]),
        zone_states={}, tracker=RegionTracker(), preview_capture=preview, capture=full,
        anchors=SimpleNamespace(items={}), detector=SimpleNamespace(detect=detect),
        jobs={}, backoff=0, generation=1, region_alive=SimpleNamespace(emit=lambda group: None))

    async def scan():
        await Engine._scan_zone(fake, 0, selected, 1, 'Browser', np, 0)
        region = fake.zone_states[0]['tracker'].regions['1']
        region.processed = True
        region.delivered.add('static text')
        first_seen = region.seen
        screen[60:85, 100:200] = 240  # Scroll/motion entirely outside the selected area.
        await Engine._scan_zone(fake, 0, selected, 1, 'Browser', np, 0)
        return region, first_seen

    region, first_seen = asyncio.run(scan())
    assert len(preview.calls) == 2  # Cheap local change probe only.
    assert full.calls == [selected]
    assert detector_calls == [True]
    assert region.revision == 0 and region.processed
    assert region.delivered == {'static text'}
    assert region.seen >= first_seen
    assert fake.zone_states[0]['tracker'].regions['1'] is region


def test_vanished_region_expires_without_reprocessing_unchanged_zone():
    from arabic_lens.detection import TrackedRegion
    tracker = RegionTracker()
    tracker.regions['1'] = TrackedRegion('1', Rect(1, 1, 20, 10), np.zeros((20, 48), dtype=np.uint8), 1.0, 1.0)
    assert tracker.expire(1.4) == []
    assert tracker.expire(1.61) == ['1']
    assert tracker.regions == {}


def test_fullscreen_tiles_change_independently_and_keep_static_text():
    bounds = Rect(0, 0, 1600, 900)
    overview = np.zeros((180, 320, 4), dtype=np.uint8)
    tiles = list(whole_screen_tiles(bounds, overview.shape))
    assert len(tiles) > 1

    class Capture:
        def __init__(self):
            self.calls = []
        def capture(self, area):
            self.calls.append(area)
            return np.full((area.h, area.w, 4), 100, dtype=np.uint8)

    full = Capture()
    detected = []
    fake = SimpleNamespace(settings=Settings(watch_fullscreen=True), zone_states={},
        tracker=RegionTracker(), preview_capture=SimpleNamespace(), capture=full,
        anchors=SimpleNamespace(items={}), detector=SimpleNamespace(detect=lambda image, sensitivity: detected.append(True) or []),
        jobs={}, backoff=0, generation=1, region_alive=SimpleNamespace(emit=lambda group: None))

    async def scan_all():
        for index, (core, padded, (x0, y0, x1, y1)) in enumerate(tiles):
            await Engine._scan_zone(fake, index, padded, 1, 'Game', np, 0,
                preview=overview[y0:y1, x0:x1], core=core, multiple=True)

    async def exercise():
        await scan_all()
        from arabic_lens.detection import TrackedRegion
        static = TrackedRegion('1', Rect(10, 10, 80, 20), np.zeros((20, 48), dtype=np.uint8), 0, 0)
        static.processed = True
        static.delivered.add('sidebar text')
        fake.zone_states[0]['tracker'].regions['1'] = static
        fake.zone_states[0]['seen_ids'].add('1')
        x0, y0, x1, y1 = tiles[-1][2]
        overview[y0:y1, x0:x1] = 200  # Scrolling in a different tile.
        await scan_all()
        return static

    static = asyncio.run(exercise())
    assert len(full.calls) == len(tiles) + 1
    assert len(detected) == len(tiles) + 1
    assert static.processed and static.delivered == {'sidebar text'} and static.revision == 0
    assert fake.zone_states[0]['tracker'].regions['1'] is static


def test_fullscreen_start_skips_selection_and_preserves_previous_areas():
    from PySide6.QtTest import QTest
    qt = QApplication.instance() or QApplication([])
    app = Application.__new__(Application)
    app.settings = Settings(watch_previous=[[10, 20, 180, 90]])
    app.preset_dialog = None
    app.window = SimpleNamespace(hide=lambda: None, rebuild=lambda page: None)
    app.service = SimpleNamespace(save=lambda: None)
    enabled = []
    app.engine = SimpleNamespace(set_watch=enabled.append)
    Application.start_watch_choice(app, 'fullscreen')
    QTest.qWait(180); qt.processEvents()
    assert enabled == [True]
    assert app.settings.watch_fullscreen
    assert app.settings.watch_previous == [[10, 20, 180, 90]]
    assert app.settings.watch_areas == []


def test_unchanged_text_in_a_dirty_tile_skips_fingerprinting(monkeypatch):
    import arabic_lens.detection as detection
    original = detection.fingerprint
    calls = []
    monkeypatch.setattr(detection, 'fingerprint', lambda image: calls.append(True) or original(image))
    tracker = RegionTracker()
    old = np.full((100, 220, 4), 100, dtype=np.uint8)
    text = Rect(10, 10, 100, 25)
    moving = Rect(130, 50, 70, 25)
    tracker.update([text, moving], old, 1.0)
    assert len(calls) == 2
    tracker.regions['1'].processed = True
    tracker.regions['1'].delivered.add('unchanged translation')
    new = old.copy()
    new[50:75, 130:200] = 180
    tracker.update([text, moving], new, 2.0, previous_image=old)
    assert len(calls) == 3  # Only moving text was fingerprinted.
    assert tracker.regions['1'].processed
    assert tracker.regions['1'].delivered == {'unchanged translation'}
    assert tracker.regions['1'].revision == 0


def test_video_compression_noise_does_not_reprocess_a_static_watch_area():
    area = Rect(220, 90, 175, 575)
    class Capture:
        def __init__(self):
            self.calls = 0
        def capture(self, bounds):
            self.calls += 1
            return np.zeros((100, 100, 4), dtype=np.uint8)
    full = Capture()
    detections = []
    fake = SimpleNamespace(settings=Settings(watch_areas=[[area.x, area.y, area.w, area.h]]),
        zone_states={}, tracker=RegionTracker(), preview_capture=None, capture=full,
        detector=SimpleNamespace(detect=lambda image, sensitivity: detections.append(True) or []),
        anchors=SimpleNamespace(items={}), jobs={}, backoff=0, generation=1)
    still = np.zeros((180, 320, 4), dtype=np.uint8)
    noisy = still.copy()
    noisy[20:25, 20:23] = 18  # Fifteen changed pixels, like the recorded X navigation.
    changed = still.copy()
    changed[20:35, 20:30] = 180  # A real text/panel change.
    async def scan():
        for preview in (still, noisy, changed):
            await Engine._scan_zone(fake, 0, area, 1, 'X', np, 0, preview=preview)
    asyncio.run(scan())
    assert full.calls == 2
    assert detections == [True, True]


def test_watch_button_restores_target_focus_before_fullscreen_or_previous_starts(monkeypatch):
    import arabic_lens.app as app_module
    from PySide6.QtTest import QTest
    qt = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module, 'open_windows', lambda: [{'hwnd': 4321, 'title': 'Game'}])
    for choice in ('fullscreen', 'previous'):
        events = []
        app = Application.__new__(Application)
        app.settings = Settings(watch_previous=[[10, 10, 200, 100]])
        app.preset_dialog = None
        app.window = SimpleNamespace(isVisible=lambda: True, hide=lambda: events.append('hide'),
            rebuild=lambda page: None)
        app.service = SimpleNamespace(save=lambda: None)
        app.engine = SimpleNamespace(set_watch=lambda enabled: events.append('watch'))
        monkeypatch.setattr(app_module, 'focus_chosen_window', lambda hwnd: events.append(f'focus:{hwnd}'))
        Application.start_watch_choice(app, choice)
        QTest.qWait(180); qt.processEvents()
        assert events == ['hide', 'focus:4321', 'watch']
