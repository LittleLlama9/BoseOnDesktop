"""Start-on-login support for the bosewin tray app (no admin, no dependencies).

Creates/removes a shortcut in the user's Startup folder that launches the tray
app windowless (pythonw, so no console flashes at login). The tray process is
~28 MB RSS and idles cheaply, so this is a reasonable autostart.

The .lnk is created via PowerShell's WScript.Shell -- no pywin32 needed.
"""

import os
import subprocess
import sys

SHORTCUT_NAME = "Bose on Desktop.lnk"


def startup_dir():
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                        "Start Menu", "Programs", "Startup")


def shortcut_path():
    return os.path.join(startup_dir(), SHORTCUT_NAME)


def _pythonw():
    """Windowless interpreter matching the current one, else fall back."""
    exe = sys.executable or ""
    for cand in (exe.replace("python.exe", "pythonw.exe"),
                 os.path.join(os.path.dirname(exe), "pythonw.exe")):
        if cand and cand.lower().endswith("pythonw.exe") and os.path.exists(cand):
            return cand
    return exe  # last resort: console interpreter (a console window will show)


def _workdir():
    # Repo root (parent of the bosewin package) so `-m bosewin.gui` resolves.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_enabled():
    return os.path.exists(shortcut_path())


def enable():
    """Create the Startup shortcut. Returns the shortcut path."""
    if getattr(sys, "frozen", False):
        # Bundled exe: launch it directly, no interpreter or -m arguments.
        target = sys.executable
        args = ""
        workdir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        target = _pythonw()
        args = "-m bosewin.gui"
        workdir = _workdir()
    lnk = shortcut_path()
    os.makedirs(startup_dir(), exist_ok=True)
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(%(lnk)s);"
        "$s.TargetPath = %(target)s;"
        "$s.Arguments = %(args)s;"
        "$s.WorkingDirectory = %(wd)s;"
        "$s.WindowStyle = 7;"
        "$s.Description = 'Bose on Desktop tray control';"
        "$s.Save()"
    ) % {
        "lnk": _ps_quote(lnk),
        "target": _ps_quote(target),
        "args": _ps_quote(args),
        "wd": _ps_quote(workdir),
    }
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=True, capture_output=True, text=True,
    )
    return lnk


def disable():
    """Remove the Startup shortcut. Returns True if one was removed."""
    lnk = shortcut_path()
    if os.path.exists(lnk):
        os.remove(lnk)
        return True
    return False


def toggle():
    if is_enabled():
        disable()
        return False
    enable()
    return True


def _ps_quote(s):
    """Single-quote a string for PowerShell (double any embedded quotes)."""
    return "'" + s.replace("'", "''") + "'"
