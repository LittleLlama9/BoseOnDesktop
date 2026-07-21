"""pywebview window hosting the Bose-style web UI.

Runs on the main thread (webview.start()). Closing the window HIDES it to the
tray instead of quitting -- webview.start() keeps running so the tray + hotkeys
stay alive. A module-level ``_quitting`` flag lets a real Quit through, because
``window.destroy()`` re-fires the ``closing`` handler and would otherwise hang
in an infinite self-cancel.
"""

import os
import sys
import threading

import webview

from bosewin.api import Api


_window = None
_quitting = False


def _webui_dir():
    """Locate the bundled webui/ static assets (source tree or frozen exe)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "bosewin", "webui")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui")


def _index():
    path = os.path.join(_webui_dir(), "index.html")
    # Pass a file:// URI (not a bare Windows path) so WebView2 reliably loads
    # the page -- a bare path can resolve to a chrome-error page on some builds.
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def show():
    """Show/raise the window from any thread (tray 'Open', hotkey, etc.)."""
    if _window is not None:
        try:
            _window.show()
        except Exception:
            pass


def hide():
    if _window is not None:
        try:
            _window.hide()
        except Exception:
            pass


def request_quit():
    """Allow the next close to actually destroy the window (used by tray Quit)."""
    global _quitting
    _quitting = True
    if _window is not None:
        try:
            _window.destroy()
        except Exception:
            pass


def create(controller, start_hidden=False):
    """Create the window and its JS API. Does NOT start the GUI loop."""
    global _window
    api = Api(controller, on_show=show)
    _window = webview.create_window(
        "Bose on Desktop",
        url=_index(),
        js_api=api,
        width=430,
        height=780,
        min_size=(390, 620),
        background_color="#FFFFFF",
        hidden=start_hidden,
        text_select=False,
    )

    def on_closing():
        # Hide to tray unless we're really quitting (see module docstring).
        if _quitting:
            return True
        hide()
        return False

    _window.events.closing += on_closing
    return _window


def run(controller, start_hidden=False, on_started=None):
    """Create the window and run the blocking GUI loop on the main thread."""
    create(controller, start_hidden=start_hidden)

    def _started():
        if on_started:
            try:
                on_started()
            except Exception:
                pass

    threading.Thread(target=_started, daemon=True).start()
    webview.start()
