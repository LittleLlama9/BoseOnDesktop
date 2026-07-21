"""Global hotkeys for the bosewin tray app -- pure Win32, no dependencies.

Uses RegisterHotKey/GetMessage via ctypes, so it costs nothing at idle (the OS
wakes our thread only when a registered chord is pressed -- no keyboard hook,
no polling, no admin). Runs its own message-loop thread.

Default chords (Ctrl+Alt+<key>) are mode switches, which always work regardless
of which mode is active (unlike CNC, which the locked presets refuse). Edit
DEFAULT_HOTKEYS to taste; keys are Win32 virtual-key codes.
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

# Virtual-key codes for the default chords.
VK_Q, VK_W, VK_E = 0x51, 0x57, 0x45
VK_N = 0x4E

# action name -> (modifiers, vk). Actions are resolved to callbacks by the GUI.
DEFAULT_HOTKEYS = {
    "mode_quiet":     (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_Q),
    "mode_aware":     (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_W),
    "mode_immersion": (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_E),
    "mode_cycle":     (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_N),
}

# Human-readable chord labels for the menu / logs.
HOTKEY_LABELS = {
    "mode_quiet": "Ctrl+Alt+Q", "mode_aware": "Ctrl+Alt+W",
    "mode_immersion": "Ctrl+Alt+E", "mode_cycle": "Ctrl+Alt+N",
}

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

        hm = HotkeyManager({"mode_quiet": lambda: ctrl.switch_mode(0)})
        hm.start()
        ...
        hm.stop()

    Only actions present in both the bindings map and the callbacks map are
    registered; unknown or failed registrations are skipped (logged to errors).
    """

    def __init__(self, callbacks, bindings=None):
        self._callbacks = dict(callbacks)
        self._bindings = dict(bindings or DEFAULT_HOTKEYS)
        self._thread = None
        self._tid = None
        self._ids = {}          # hotkey id -> action name
        self.errors = []
        self.registered = []    # action names successfully bound

    def start(self):
        _set_prototypes()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._tid is not None:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    def _run(self):
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
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

        for hk_id in list(self._ids):
            user32.UnregisterHotKey(None, hk_id)
        self._ids.clear()
