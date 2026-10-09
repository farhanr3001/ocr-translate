import base64
import ctypes
import json
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict

DEFAULT_IGNORE = ["Exit", "Exit Game", "Quit", "Quit Game", "Close", "Cancel", "Back", "Continue", "Restart", "Resume", "Leave", "Start", "Play", "Pause", "Settings", "Options", "Apply", "Confirm", "Yes", "No", "OK", "Save", "Load", "Menu", "Skip"]
PRESETS = {
    "Default": dict(font_size=23, background_opacity=78, padding=14, radius=12, shadow=True, outline=0, max_width=560),
    "Subtitle": dict(font_size=27, background_opacity=32, padding=10, radius=6, shadow=True, outline=1, max_width=720),
    "Minimal": dict(font_size=21, background_opacity=58, padding=9, radius=8, shadow=True, outline=0, max_width=480),
    "High Contrast": dict(font_size=25, background_opacity=95, padding=16, radius=10, shadow=True, outline=1, max_width=600),
}


@dataclass
class OverlaySettings:
    follow_content: bool = True
    interaction_hold: str = "Ctrl+Alt"
    match_game: bool = False
    border_color: str = "#b59252"
    border_width: int = 0
    font: str = "Segoe UI"
    font_size: int = 23
    text_color: str = "#ffffff"
    background_color: str = "#10151d"
    background_opacity: int = 78
    opacity: int = 100
    padding: int = 14
    radius: int = 12
    max_width: int = 560
    outline: int = 0
    shadow: bool = True
    position: str = "Replace"
    fade_ms: int = 180
    duration: int = 12
    persistence: bool = True


@dataclass
class Settings:
    schema_version: int = 8
    language: str = "en"
    first_run: bool = True
    start_minimized: bool = False
    start_windows: bool = False
    minimize_tray: bool = True
    remember_mode: bool = False
    last_watch: bool = False
    auto_check_updates: bool = True
    update_last_prompt_version: str = ""
    update_last_prompt_time: float = 0.0
    provider: str = "Built-in offline"
    endpoint: str = ""
    model: str = ""
    api_key: str = ""  # DPAPI ciphertext only. Never plaintext on disk.
    azure_region: str = ""
    timeout: int = 12
    cache_enabled: bool = True
    cache_limit: int = 5000
    history_enabled: bool = True
    history_limit: int = 500
    scan_ms: int = 500
    stability_ms: int = 400
    cooldown_ms: int = 800
    sensitivity: int = 50
    min_chars: int = 1
    filter_ui: bool = True
    active_only: bool = True
    watch_region: list | None = None  # Physical screen rectangle; None watches the focused window.
    watch_areas: list = field(default_factory=list)  # Physical rectangles in the latest session.
    watch_previous: list = field(default_factory=list)
    watch_app: str = ""
    watch_previous_app: str = ""
    watch_origin: list | None = None
    watch_previous_origin: list | None = None
    watch_presets: list = field(default_factory=list)
    watch_startup: str = "new"
    watch_fullscreen: bool = False
    max_regions: int = 128
    debug: bool = False
    show_translation_boxes: bool = False
    ignored_translations: dict = field(default_factory=dict)
    ignored: list = field(default_factory=lambda: DEFAULT_IGNORE.copy())
    blocked_apps: list = field(default_factory=list)
    shortcuts: dict = field(default_factory=lambda: {"quick": "Alt+Q", "repeat": "Alt+E", "watch": "Alt+W", "add_zone": "Alt+Shift+W", "hide": "Alt+H"})
    last_region: list | None = None
    pinned_regions: list = field(default_factory=list)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_byte))]


def protect_secret(value: str, decrypt=False):
    if not value:
        return ""
    raw = base64.b64decode(value) if decrypt else value.encode("utf-8")
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    dest = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
        raise OSError("Credential protection unavailable")
    try:
        result = ctypes.string_at(dest.data, dest.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(dest.data, ctypes.c_void_p))


class SettingsService:
    def __init__(self, directory=None):
        self.directory = Path(directory or Path(os.getenv("LOCALAPPDATA", ".")) / "ArabicLens")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "settings.json"
        self.settings = Settings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get('provider', 'Chat compatible') == 'Chat compatible' and not data.get('endpoint'):
                data['provider'] = 'Built-in offline'
            overlay = data.pop("overlay", {})
            if data.get('schema_version', 1) < 2:
                if data.get('max_regions', 3) == 3: data['max_regions'] = 32
                if data.get('min_chars', 12) == 12: data['min_chars'] = 6
                if overlay.get('position', 'Below') == 'Below': overlay['position'] = 'Replace'
                data['schema_version'] = 2
            if data.get('schema_version', 2) < 3:
                # The old default cut off dense game screens mid-panel.
                if data.get('max_regions', 32) == 32:
                    data['max_regions'] = 48
                data['schema_version'] = 3
            if data.get('schema_version', 3) < 4:
                for key, old, new in [('scan_ms', 650, 500), ('stability_ms', 650, 400), ('cooldown_ms', 1200, 800), ('min_chars', 6, 1)]:
                    if data.get(key, old) == old:
                        data[key] = new
                data['schema_version'] = 4
            if data.get('schema_version', 4) < 5:
                if data.get('watch_region'):
                    data['watch_areas'] = [data['watch_region']]
                    data['watch_previous'] = [data['watch_region']]
                    data['watch_startup'] = 'previous'
                data['schema_version'] = 5
            if data.get('schema_version', 5) < 6:
                if data.get('max_regions', 48) == 48:
                    data['max_regions'] = 128
                overlay['persistence'] = True
                data['schema_version'] = 6
            if data.get('schema_version', 6) < 7:
                # Alt+R is commonly owned by other Windows software. It used
                # to disable every shortcut when registration failed.
                shortcuts = data.get('shortcuts')
                if isinstance(shortcuts, dict) and shortcuts.get('add_zone') == 'Alt+R':
                    shortcuts['add_zone'] = 'Alt+Shift+W'
                data['schema_version'] = 7
            if data.get('schema_version', 7) < 8:
                data['schema_version'] = 8
            self.settings = Settings(**{k: v for k, v in data.items() if k in Settings.__dataclass_fields__})
            self.settings.overlay = OverlaySettings(**{k: v for k, v in overlay.items() if k in OverlaySettings.__dataclass_fields__})
            self.settings.overlay.persistence = True
            self.settings.scan_ms = max(250, min(3000, self.settings.scan_ms))
            self.settings.max_regions = max(1, min(128, self.settings.max_regions))
            area = self.settings.watch_region
            self.settings.watch_region = area if (isinstance(area, list) and len(area) == 4
                and all(isinstance(value, int) and not isinstance(value, bool) for value in area)
                and area[2] >= 8 and area[3] >= 8 and area[2] <= 20000 and area[3] <= 20000) else None
            def clean_areas(areas):
                if not isinstance(areas, list):
                    return []
                return [a for a in areas[:12] if isinstance(a, list) and len(a) == 4
                    and all(isinstance(v, int) and not isinstance(v, bool) for v in a)
                    and 8 <= a[2] <= 20000 and 8 <= a[3] <= 20000]
            self.settings.watch_areas = clean_areas(self.settings.watch_areas)
            self.settings.watch_previous = clean_areas(self.settings.watch_previous)
            self.settings.watch_origin = (clean_areas([self.settings.watch_origin]) or [None])[0]
            self.settings.watch_previous_origin = (clean_areas([self.settings.watch_previous_origin]) or [None])[0]
            if not isinstance(self.settings.watch_presets, list):
                self.settings.watch_presets = []
            self.settings.watch_presets = [dict(p, areas=clean_areas(p.get('areas')),
                origin=(clean_areas([p.get('origin')]) or [None])[0]) for p in self.settings.watch_presets[:50]
                if isinstance(p, dict) and isinstance(p.get('name'), str) and isinstance(p.get('areas'), list) and clean_areas(p.get('areas'))]
            if self.settings.watch_startup not in ('fullscreen', 'new', 'previous', 'presets'):
                self.settings.watch_startup = 'new'
            defaults = Settings().shortcuts
            if not isinstance(self.settings.shortcuts, dict):
                self.settings.shortcuts = defaults
            else:
                self.settings.shortcuts = {**defaults, **{k: v for k, v in self.settings.shortcuts.items() if k in defaults and isinstance(v, str)}}
            from .app_catalog import clean_apps
            self.settings.blocked_apps = clean_apps(self.settings.blocked_apps)
        except (FileNotFoundError, ValueError, TypeError):
            pass

    def save(self):
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self.settings), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
