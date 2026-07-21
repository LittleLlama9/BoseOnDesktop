"""Speak short mode-name announcements aloud, mirroring the headphones' own
voice prompt when you hold the action button to cycle modes.

Uses the Windows built-in SAPI voice (System.Speech) via a single long-lived
PowerShell worker that reads lines from stdin. The one-time assembly-load cost
(~400 ms) is paid once at startup (see :func:`warmup`), so each subsequent
announcement starts near-instantly -- matching the app-speed bar for hotkeys.
No pip dependency; works from the frozen exe.

Speech plays through the default audio output, so if the headphones are the
current output (Bluetooth or aux) the announcement comes through them, just
like the native prompt. Rapid presses interrupt: each new line cancels the
in-progress utterance so only the latest mode name is spoken.
"""

import subprocess
import threading

_CREATE_NO_WINDOW = 0x08000000

# Persistent worker: read a line, cancel anything speaking, speak the line.
_WORKER = (
    "Add-Type -AssemblyName System.Speech;"
    "$v = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$v.Rate = 1;"
    "while ($true) {"
    "  $line = [Console]::In.ReadLine();"
    "  if ($line -eq $null) { break }"
    "  if ($line -eq '__QUIT__') { break }"
    "  if ($line.Length -gt 0) { $v.SpeakAsyncCancelAll(); $v.SpeakAsync($line) | Out-Null }"
    "}"
)

_lock = threading.Lock()
_proc = None


def _spawn():
    return subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WORKER],
        creationflags=_CREATE_NO_WINDOW,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _ensure_locked():
    """Return a live worker, (re)spawning if needed. Caller holds _lock."""
    global _proc
    if _proc is None or _proc.poll() is not None:
        try:
            _proc = _spawn()
        except Exception:
            _proc = None
    return _proc


def warmup():
    """Start the worker early so the first announcement isn't delayed by the
    one-time SAPI assembly load. Best-effort; safe to call from any thread."""
    try:
        with _lock:
            _ensure_locked()
    except Exception:
        pass


def speak(text):
    """Speak ``text``, cancelling any in-progress announcement.

    Never raises -- announcement is best-effort feedback, not core function.
    """
    if not text:
        return
    line = str(text).replace("\r", " ").replace("\n", " ").strip()
    if not line:
        return
    data = (line + "\n").encode("utf-8", "replace")
    try:
        with _lock:
            p = _ensure_locked()
            if p is None or p.stdin is None:
                return
            try:
                p.stdin.write(data)
                p.stdin.flush()
            except (OSError, ValueError):
                # Worker died; respawn once and retry.
                p = _ensure_locked()
                if p is not None and p.stdin is not None:
                    p.stdin.write(data)
                    p.stdin.flush()
    except Exception:
        pass


def stop():
    """Shut down the worker (called on app quit)."""
    global _proc
    with _lock:
        p = _proc
        _proc = None
    if p is None:
        return
    try:
        if p.stdin is not None and p.poll() is None:
            p.stdin.write(b"__QUIT__\n")
            p.stdin.flush()
    except Exception:
        pass
    try:
        p.wait(timeout=1)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
