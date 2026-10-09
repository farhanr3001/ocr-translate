import ctypes
from ctypes import wintypes
from PySide6.QtCore import QAbstractNativeEventFilter
from .windows import user32


def parse_shortcut(value):
    parts = value.replace("Meta", "Win").replace("Control", "Ctrl").split("+")
    modifiers = {"Alt": 1, "Ctrl": 2, "Shift": 4, "Win": 8}
    if len(parts) < 2 or any(p not in modifiers for p in parts[:-1]):
        raise ValueError("Use a modifier and a letter, number or function key.")
    mod = 0
    for p in parts[:-1]:
        mod |= modifiers[p]
    key = parts[-1].upper()
    if len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 111 + int(key[1:])
    else:
        raise ValueError("Unsupported shortcut key")
    if (mod, vk) in ((1, 115), (2, 81), (8, 76), (8, 68)):
        raise ValueError("Reserved system shortcut")
    return mod, vk


class HotkeyManager(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = {}
        self.values = {}
        self.unavailable = []

    def register(self, shortcuts, strict=False):
        parsed, invalid = {}, []
        for action, value in shortcuts.items():
            try:
                parsed[action] = parse_shortcut(value)
            except ValueError:
                if strict:
                    raise
                invalid.append(action)
        if strict and len(set(parsed.values())) != len(parsed):
            raise ValueError("shortcut_conflict")
        previous = self.values.copy()
        self.close()
        unavailable = list(invalid)
        for index, (action, (mod, vk)) in enumerate(parsed.items(), 1):
            if not user32.RegisterHotKey(None, index, mod | 0x4000, vk):
                unavailable.append(action)
            else:
                self.registered[index] = action
        self.values = shortcuts.copy()
        self.unavailable = unavailable
        if strict and unavailable:
            self.close()
            if previous:
                self.register(previous)
            raise ValueError("shortcut_conflict")
        return unavailable

    def nativeEventFilter(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x312:
            action = self.registered.get(msg.wParam)
            if action:
                self.callback(action)
                return True, 0
        return False, 0

    def close(self):
        for index in self.registered:
            user32.UnregisterHotKey(None, index)
        self.registered.clear()
        self.values.clear()
        self.unavailable.clear()
