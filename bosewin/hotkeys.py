"""Global hotkeys for the bosewin tray app -- pure Win32, no dependencies.

Uses RegisterHotKey/GetMessage via ctypes, so it costs nothing at idle (the OS
wakes our thread only when a registered chord is pressed -- no keyboard hook,
no polling, no admin). Runs its own message-loop thread.

Default chords (Ctrl+Alt+<key>) are mode switches, which always work regardless
of which mode is active (unlike CNC, which the locked presets refuse). The user
can rebind any of these from the Settings page; bindings are persisted and
applied live via rebind() (no restart).

Actions are keyed by mode slot: ``mode_0`` .. ``mode_9`` switch to that slot and
``mode_cycle`` cycles through the configured modes. Chords are stored as human
strings ("Ctrl+Alt+Q") and parsed to Win32 (modifiers, vk) here.
"""

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_REBIND = 0x0400  # WM_USER: request the loop thread to re-register bindings

# action name -> chord string. Actions are resolved to callbacks by the GUI.
# Slot 0/1/2 are the locked presets (Quiet/Aware/Immersion); 3-9 are custom.
DEFAULT_HOTKEYS = {
    "mode_0":     "Ctrl+Alt+Q",
    "mode_1":     "Ctrl+Alt+W",
    "mode_2":     "Ctrl+Alt+E",
    "mode_cycle": "Ctrl+Alt+N",
}

_MOD_TOKENS = {
    "CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL,
    "ALT": MOD_ALT, "SHIFT": MOD_SHIFT,
    "WIN": MOD_WIN, "META": MOD_WIN, "SUPER": MOD_WIN,
}

# Named non-typing keys that may be bound with NO modifier (they don't collide
# with ordinary typing). Arrows are the common case. Delete/Backspace/Escape are
# deliberately excluded -- the capture UI reserves them for clear/cancel.
NAMED_KEYS = {
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22, "END": 0x23, "HOME": 0x24, "INSERT": 0x2D,
}
_KEY_DISPLAY = {
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x21: "PageUp", 0x22: "PageDown", 0x23: "End", 0x24: "Home", 0x2D: "Insert",
}


def _is_typing_vk(vk):
    """Letters/digits collide with normal typing, so they need a modifier."""
    return 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A


def _vk_for_token(token):
    t = token.strip().upper()
    if len(t) == 1 and ("A" <= t <= "Z" or "0" <= t <= "9"):
        return ord(t)
    if t in NAMED_KEYS:
        return NAMED_KEYS[t]
    if len(t) >= 2 and t[0] == "F" and t[1:].isdigit():
        n = int(t[1:])
        if 1 <= n <= 12:
            return 0x70 + (n - 1)  # VK_F1..VK_F12
    return None


def _key_name(vk):
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x70 <= vk <= 0x7B:
        return "F%d" % (vk - 0x6F)
    return _KEY_DISPLAY.get(vk, "?")


def parse_chord(chord):
    """'Ctrl+Alt+Q' or 'Left' -> (modifiers|NOREPEAT, vk). Raises ValueError if
    invalid. Letters/digits require at least one of Ctrl/Alt/Win so the chord
    can't collide with typing; arrows and F-keys may be bound on their own.
    """
    mods = 0
    vk = None
    for tok in str(chord).split("+"):
        tok = tok.strip()
        if not tok:
            continue
        m = _MOD_TOKENS.get(tok.upper())
        if m:
            mods |= m
            continue
        v = _vk_for_token(tok)
        if v is None:
            raise ValueError("Unrecognized key: %r" % tok)
        if vk is not None:
            raise ValueError("Only one non-modifier key is allowed")
        vk = v
    if vk is None:
        raise ValueError("Pick a letter, number, arrow, or F-key")
    if _is_typing_vk(vk) and not (mods & (MOD_CONTROL | MOD_ALT | MOD_WIN)):
        raise ValueError("Include Ctrl, Alt, or Win")
    return (mods | MOD_NOREPEAT, vk)


def format_chord(mods, vk):
    """(modifiers, vk) -> 'Ctrl+Alt+Q' (canonical modifier order)."""
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_WIN:
        parts.append("Win")
    parts.append(_key_name(vk))
    return "+".join(parts)


def canonical_chord(chord):
    """Normalize a chord string (validates + canonical modifier order)."""
    return format_chord(*parse_chord(chord))


_prototypes_set = False


def _set_prototypes():
    """Set argtypes/restype so 64-bit handles/params aren't truncated."""
    global _prototypes_set
    if _prototypes_set:
        return
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                      wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    _prototypes_set = True


class HotkeyManager:
    """Registers global hotkeys and dispatches them to callbacks.

        hm = HotkeyManager({"mode_0": lambda: ctrl.switch_mode(0)})
        hm.start()
        ...
        hm.stop()

    Only actions present in both the bindings map and the callbacks map are
    registered; unknown or failed registrations are skipped (logged to errors).
    """

    def __init__(self, callbacks, bindings=None):
        self._callbacks = dict(callbacks)
        self._bindings = self._normalize(bindings if bindings is not None
                                         else DEFAULT_HOTKEYS)
        self._thread = None
        self._tid = None
        self._ids = {}          # hotkey id -> action name
        self._lock = threading.Lock()
        self._pending = None    # bindings queued for the loop thread to apply
        self._rebound = threading.Event()
        self.errors = []
        self.registered = []    # action names successfully bound

    @staticmethod
    def _normalize(bindings):
        """Accept action -> chord-string OR action -> (mods, vk); drop invalid."""
        out = {}
        for action, val in dict(bindings).items():
            try:
                if isinstance(val, str):
                    out[action] = parse_chord(val)
                else:
                    mods, vk = val
                    out[action] = (int(mods), int(vk))
            except Exception:
                pass
        return out

    def start(self):
        _set_prototypes()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._tid is not None:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    def rebind(self, bindings):
        """Re-register a new action->chord map live. Blocks until the loop thread
        has applied it; returns (registered, errors)."""
        pend = self._normalize(bindings)
        if self._tid is None:
            # Not started yet -- just stash; _run will pick it up.
            self._bindings = pend
            return (list(self.registered), list(self.errors))
        with self._lock:
            self._pending = pend
        self._rebound.clear()
        user32.PostThreadMessageW(self._tid, WM_REBIND, 0, 0)
        self._rebound.wait(timeout=2.0)
        return (list(self.registered), list(self.errors))

    def _register_all(self):
        """(loop thread only) Unregister everything, then register _bindings."""
        for hk_id in list(self._ids):
            user32.UnregisterHotKey(None, hk_id)
        self._ids.clear()
        self.registered = []
        self.errors = []
        hk_id = 1
        for action, (mods, vk) in self._bindings.items():
            if action not in self._callbacks:
                continue
            if user32.RegisterHotKey(None, hk_id, mods, vk):
                self._ids[hk_id] = action
                self.registered.append(action)
                hk_id += 1
            else:
                err = ctypes.get_last_error()
                self.errors.append("%s: RegisterHotKey failed (err %d, maybe "
                                   "chord already in use)" % (action, err))

    def _run(self):
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._register_all()

        msg = wintypes.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):   # WM_QUIT or error
                break
            if msg.message == WM_HOTKEY:
                action = self._ids.get(int(msg.wParam))
                cb = self._callbacks.get(action) if action else None
                if cb:
                    try:
                        cb()
                    except Exception as e:
                        self.errors.append("%s: %s" % (action, e))
            elif msg.message == WM_REBIND:
                with self._lock:
                    pend = self._pending
                    self._pending = None
                if pend is not None:
                    self._bindings = pend
                    self._register_all()
                self._rebound.set()

        for hk_id in list(self._ids):
            user32.UnregisterHotKey(None, hk_id)
        self._ids.clear()
