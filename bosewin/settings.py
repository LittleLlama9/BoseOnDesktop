"""Tiny persisted settings for the tray app (JSON in %APPDATA%\\BoseOnDesktop).

Kept deliberately minimal -- a flat key/value file so preferences (e.g. whether
to speak the mode name on a hotkey change) survive restarts, including when the
app is launched from the Startup shortcut.
"""

import json
import os

_DEFAULTS = {
    "speak_mode": True,   # announce the mode name aloud on a hotkey mode change
    # Global keyboard shortcuts: action name -> chord string. Actions are
    # "mode_<slot>" (0-9) and "mode_cycle". Kept as strings so the file stays
    # human-readable; hotkeys.parse_chord turns them into Win32 (mods, vk).
    "hotkeys": {
        "mode_0": "Ctrl+Alt+Q",
        "mode_1": "Ctrl+Alt+W",
        "mode_2": "Ctrl+Alt+E",
        "mode_cycle": "Ctrl+Alt+N",
    },
}


def _dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "BoseOnDesktop")


def _path():
    return os.path.join(_dir(), "settings.json")


def _load():
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def get(key):
    return _load().get(key, _DEFAULTS.get(key))


def set(key, value):
    data = _load()
    data[key] = value
    try:
        os.makedirs(_dir(), exist_ok=True)
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return value


def toggle(key):
    return set(key, not bool(get(key)))
