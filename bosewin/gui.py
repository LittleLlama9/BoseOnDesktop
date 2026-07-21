"""bosewin system-tray control for Bose QC Ultra (1st gen).

A lightweight pystray menu -- no always-open window. The headphones drop off
Bluetooth often (multipoint bumps the PC, auto-off), and the SPP COM port is
exclusive, so every action opens a short-lived connection, acts, and closes.
State is cached between refreshes and the menu is rebuilt live.

Weighted toward the controls the PC genuinely can't do otherwise: noise mode,
CNC level, Immersive Audio, Wind Block, ANC. EQ is intentionally omitted from
the tray because Matthew runs Equalizer APO on this machine.

Run:  py -m bosewin.gui
"""

import threading
import sys

import pystray
from PIL import Image, ImageDraw, ImageFont

import bosewin
from pybmap.errors import BmapError, BmapConnectionError
from pybmap.constants import SIDETONE_NAMES, SIDETONE_VALUES
from pybmap.devices.parsers import AUTO_OFF_LABELS, AUTO_OFF_MINUTES

SPATIAL_LABELS = {0: "Off", 1: "Still", 2: "Motion"}
SPATIAL_TO_NAME = {0: "off", 1: "room", 2: "head"}
# Noise-level menu uses the mobile-app scale (higher = more cancellation).
# pybmap/device stay on the raw byte where 0 = max ANC, so app<->device is
# app = 10 - device. Menu offers the same coarse steps the app slider snaps to.
CNC_APP_STEPS = [10, 8, 6, 4, 2, 0]
SIDETONE_ORDER = ["off", "low", "medium", "high"]


def _mode_disp(dev, idx, mc):
    """Display name for a mode: stored custom name, else the voice-prompt
    scenario (HOME/FOCUS/etc, what the app shows), else preset name."""
    if mc is not None and mc.name and mc.name != "None":
        return mc.name
    if mc is not None and getattr(mc, "prompt", None) and not mc.prompt.startswith("("):
        if mc.prompt != "NONE":
            return mc.prompt.capitalize()
    return dev._mode_name_from_idx(idx)


def _mode_disp_local(dev, idx, mc):
    """Like _mode_disp but never re-reads the device. Resolves empty slots to a
    known preset name (or 'None'), avoiding the pathological modes() recursion
    when building the full mode table (we already hold every ModeConfig)."""
    if mc is not None and mc.name and mc.name != "None":
        return mc.name
    if mc is not None and getattr(mc, "prompt", None) and not mc.prompt.startswith("("):
        if mc.prompt != "NONE":
            return mc.prompt.capitalize()
    return dev._device.MODE_BY_IDX.get(idx, "None")


class Controller:
    """Serialises short-lived connections and caches device state."""

    def __init__(self, port=None, device=None):
        self._port = port
        self._device = device
        self._lock = threading.Lock()
        self.state = {
            "connected": False,
            "battery": None,
            "mode_idx": None,
            "mode_name": "-",
            "editable": False,
            "cnc": None,
            "spatial": None,
            "wind": None,
            "anc": None,
            "modes": {},   # idx -> (label, editable)
            "sidetone": None,
            "auto_off": None,
            "auto_pause": None,
            "auto_answer": None,
            "multipoint": None,
            "error": "",
        }

    def _do(self, fn):
        """Open, run fn(dev), close. Returns fn result or raises.

        Prefers the USB-C control channel when a data cable is present (works
        during analog wired audio, no Bluetooth needed), else Bluetooth SPP.
        """
        with self._lock:
            if self._port:
                dev = bosewin.connect(port=self._port, device_type=self._device)
            else:
                dev = bosewin.connect_auto(device_type=self._device)
            try:
                return fn(dev)
            finally:
                dev.close()

    def refresh(self, full=True):
        """Refresh cached state.

        full=True  -> read battery, mode index, the whole 10-slot mode table,
                      and all preference blocks (~4s on gen-1; used on first
                      load and the explicit Refresh action).
        full=False -> read only battery + current mode index and resolve the
                      active mode's config from the cached table (~0.1s; used
                      by the periodic background poll). Falls back to a full
                      read if the mode table isn't cached yet.
        """
        if not full and not self.state.get("modes"):
            full = True
        if not full and not self.state.get("modes"):
            full = True
        prev_connected = self.state.get("connected")
        try:
            def read(dev):
                st = {}
                st["battery"] = dev.battery()
                idx = dev.mode_idx()
                st["mode_idx"] = idx
                if full:
                    modes = dev.modes()
                    labels = {}
                    for i, mc in modes.items():
                        disp = _mode_disp_local(dev, i, mc)
                        labels[i] = (disp, mc.editable, mc.configured, mc.name,
                                     mc.cnc_level, mc.spatial, mc.anc_toggle)
                    st["modes"] = labels
                    mc = modes.get(idx)
                    if mc is not None:
                        st["mode_name"] = _mode_disp(dev, idx, mc)
                        st["editable"] = mc.editable
                        st["cnc"] = mc.cnc_level
                        st["spatial"] = mc.spatial
                        # off45 (wind_block) is a meaningless constant on
                        # gen-1; do NOT surface it. off46 (anc_toggle) is real.
                        st["anc"] = mc.anc_toggle
                    # Preference blocks (all reliable getters). Best-effort.
                    for key, reader in (
                        ("sidetone", dev.sidetone),
                        ("auto_off", dev.auto_off),
                        ("auto_pause", dev.auto_pause),
                        ("auto_answer", dev.auto_answer),
                        ("multipoint", dev.multipoint),
                    ):
                        try:
                            st[key] = reader()
                        except BmapError:
                            st[key] = None
                else:
                    # Read the ACTIVE mode's config fresh (one cheap GET) so the
                    # hero name + noise level always reflect the device, even if
                    # the active mode was reconfigured or switched externally
                    # (e.g. from the phone) since the last full refresh. The
                    # cached 10-slot table is only rebuilt on a full read, so
                    # trusting it for the active slot let a stale name/level
                    # linger for an unbounded time between full refreshes.
                    mc = dev.mode_config(idx, drain=False)
                    if mc is not None:
                        st["mode_name"] = _mode_disp(dev, idx, mc)
                        st["editable"] = mc.editable
                        st["cnc"] = mc.cnc_level
                        st["spatial"] = mc.spatial
                        st["anc"] = mc.anc_toggle
                        # Keep the cached table's active-slot entry in sync so the
                        # mode list agrees with the hero on the next render.
                        modes = dict(self.state.get("modes") or {})
                        modes[idx] = (st["mode_name"], mc.editable,
                                      mc.configured, mc.name, mc.cnc_level,
                                      mc.spatial, mc.anc_toggle)
                        st["modes"] = modes
                    else:
                        self._apply_cached_mode(st, idx)
                return st
            st = self._do(read)
            self.state.update(st)
            self.state["connected"] = True
            self.state["error"] = ""
        except BmapConnectionError as e:
            self.state["connected"] = False
            self.state["error"] = "disconnected"
        except BmapError as e:
            self.state["connected"] = False
            self.state["error"] = str(e)
        # On a disconnected -> connected transition, re-apply the user's saved
        # EQ. Bose headphones drop custom EQ back to flat on a full BT
        # reconnect / power-cycle; the mobile app re-pushes it on connect, and
        # so do we. No-op if nothing is saved or the device already matches.
        if self.state.get("connected") and not prev_connected:
            try:
                self.sync_eq()
            except Exception:
                pass
        return self.state

    # ---- EQ persistence (survive the reconnect flat-reset) ----------------

    def _desired_eq(self):
        """The user's saved EQ (bass, mid, treble), or None if unset."""
        try:
            from bosewin import settings
            v = settings.get("eq")
        except Exception:
            v = None
        if isinstance(v, dict) and all(k in v for k in ("bass", "mid", "treble")):
            try:
                return (int(v["bass"]), int(v["mid"]), int(v["treble"]))
            except (TypeError, ValueError):
                return None
        return None

    def save_eq(self, bass, mid, treble):
        """Persist the user's desired EQ so it can be re-applied on reconnect."""
        try:
            from bosewin import settings
            settings.set("eq", {"bass": int(bass), "mid": int(mid),
                                "treble": int(treble)})
        except Exception:
            pass

    def sync_eq(self):
        """Reconcile device EQ with the saved desired EQ (best-effort).

        - Nothing saved yet: seed the store from the device, but only if the
          device EQ is non-flat (a flat reading may be a post-reset state we
          must not memorise as the user's preference).
        - Saved and device differs: re-apply the saved EQ (the reconnect case).
        """
        desired = self._desired_eq()

        def act(dev):
            cur = tuple(int(getattr(b, "current", 0)) for b in dev.eq()[:3])
            if len(cur) < 3:
                return ("skip", cur)
            if desired is None:
                if any(v != 0 for v in cur):
                    self.save_eq(*cur)
                    return ("seeded", cur)
                return ("flat", cur)
            if cur != desired:
                dev.set_eq(*desired)
                return ("reapplied", cur, desired)
            return ("match", cur)

        try:
            return self._do(act)
        except BmapError:
            return None

    def _apply_cached_mode(self, st, idx):
        """Fill mode_name/editable/cnc/spatial/anc for idx from the cached
        mode table (no device read)."""
        lbl = (self.state.get("modes") or {}).get(idx)
        if lbl:
            st["mode_name"] = lbl[0]
            st["editable"] = lbl[1]
            if len(lbl) >= 7:
                st["cnc"], st["spatial"], st["anc"] = lbl[4], lbl[5], lbl[6]

    def _store_active(self, idx, mc, batt):
        """Update state + the cached mode-table label for the active slot from
        a freshly read ModeConfig (no extra device reads)."""
        if batt is not None:
            self.state["battery"] = batt
        self.state["mode_idx"] = idx
        if mc is not None:
            modes = dict(self.state.get("modes") or {})
            old = modes.get(idx)
            # Resolve the DISPLAY name. gen-1 custom modes all carry raw
            # mc.name == "None" and get their real name from the prompt byte
            # (e.g. prompt "FOCUS" -> "Focus"); only presets have a real
            # mc.name. Using mc.name alone wrongly kept the *previous* mode's
            # name when switching to a custom slot ("Quiet - Noise level 3").
            prompt = getattr(mc, "prompt", None)
            if mc.name and mc.name != "None":
                disp = mc.name
            elif prompt and prompt != "NONE":
                disp = prompt.capitalize()
            elif old:
                disp = old[0]
            else:
                disp = self.state.get("mode_name", "-")
            self.state["mode_name"] = disp
            self.state["editable"] = mc.editable
            self.state["cnc"] = mc.cnc_level
            self.state["spatial"] = mc.spatial
            self.state["anc"] = mc.anc_toggle
            modes[idx] = (disp, mc.editable, mc.configured, mc.name,
                          mc.cnc_level, mc.spatial, mc.anc_toggle)
            self.state["modes"] = modes
        self.state["connected"] = True
        self.state["error"] = ""

    def _set_active_config(self, action):
        """Run a config-changing action (cnc/spatial/anc/wind) and re-read only
        the active mode slot -- fast (~0.1s), not a full 10-slot refresh."""
        def act(dev):
            action(dev)
            idx = dev.mode_idx()
            mc = dev.mode_config(idx, drain=False)
            return idx, mc, dev.battery()
        try:
            idx, mc, batt = self._do(act)
            self._store_active(idx, mc, batt)
        except BmapConnectionError:
            self.state["connected"] = False
            self.state["error"] = "disconnected"
        except BmapError as e:
            self.state["error"] = str(e)

    def _set_pref(self, action, key, reader):
        """Run a preference setter and read back just that one value."""
        def act(dev):
            action(dev)
            try:
                return reader(dev)
            except BmapError:
                return None
        try:
            self.state[key] = self._do(act)
            self.state["connected"] = True
            self.state["error"] = ""
        except BmapConnectionError:
            self.state["connected"] = False
            self.state["error"] = "disconnected"
        except BmapError as e:
            self.state["error"] = str(e)

    def set_cnc(self, level):
        self._set_active_config(lambda d: d.set_cnc(level))

    def set_cnc_app(self, app_level):
        """Set noise level on the mobile-app scale (10 = max ANC)."""
        self._set_active_config(lambda d: d.set_cnc(10 - app_level))

    def set_spatial(self, value):
        self._set_active_config(lambda d: d.set_spatial(SPATIAL_TO_NAME[value]))

    def set_wind(self, on):
        self._set_active_config(lambda d: d.set_wind(on))

    def set_anc(self, on):
        self._set_active_config(lambda d: d.set_anc(on))

    def set_sidetone(self, name):
        self._set_pref(lambda d: d.set_sidetone(name), "sidetone",
                       lambda d: d.sidetone())

    def set_auto_off(self, minutes):
        self._set_pref(lambda d: d.set_auto_off(minutes), "auto_off",
                       lambda d: d.auto_off())

    def set_auto_pause(self, on):
        self._set_pref(lambda d: d.set_auto_pause(on), "auto_pause",
                       lambda d: d.auto_pause())

    def set_auto_answer(self, on):
        self._set_pref(lambda d: d.set_auto_answer(on), "auto_answer",
                       lambda d: d.auto_answer())

    def set_multipoint(self, on):
        self._set_pref(lambda d: d.set_multipoint(on), "multipoint",
                       lambda d: d.multipoint())

    def switch_mode(self, idx):
        """Fast mode switch: send the START packet and read back only the new
        slot's config (~0.1s). No full 10-slot re-read."""
        def act(dev):
            dev.set_mode_idx(idx)
            return dev.mode_config(idx, drain=False)
        try:
            mc = self._do(act)
            self._store_active(idx, mc, None)
        except BmapConnectionError:
            self.state["connected"] = False
            self.state["error"] = "disconnected"
        except BmapError as e:
            self.state["error"] = str(e)

    def delete_mode(self, idx):
        """Clear a custom mode slot by writing an empty 'None' config via
        ModeConfig [31.6] (verified reversible on gen-1 fw 1.6.7). Presets
        (0-2) cannot be deleted. If the target is the active mode, switch to
        Quiet [0] first so the device is never left sitting on an empty slot,
        then clear the slot and do a full refresh."""
        info = self.state.get("modes", {}).get(idx)
        if info is not None and not info[1]:  # info[1] == editable
            self.state["error"] = "Cannot delete a preset mode"
            return self.state
        try:
            if idx == self.state.get("mode_idx"):
                self._do(lambda d: d.set_mode_idx(0))
            self._do(lambda d: d._write_mode(idx, "None", cnc_level=0,
                                             spatial=0, wind_block=0,
                                             anc_toggle=0))
            self.refresh(full=True)
            self.state["connected"] = True
            self.state["error"] = ""
        except BmapConnectionError:
            self.state["connected"] = False
            self.state["error"] = "disconnected"
        except BmapError as e:
            self.state["error"] = str(e)
        return self.state

    def add_mode(self, name, cnc_level=0, spatial=0, anc_toggle=1):
        """Create a custom mode in the first free editable slot via
        create_profile -- the inverse of delete_mode (both write ModeConfig
        [31.6], verified reversible on gen-1 fw 1.6.7). Creates it, switches to
        it, and reads the new slot back, all in ONE connection so the write and
        its verification share a single BT/USB link (opening a fresh link per
        step made rapid SPP reconnects drop as 'disconnected').

        wind_block is forced 0: on gen-1 it is a one-shot 'force max ANC'
        TRIGGER, not persisted state, so sending 1 would clamp the new mode's
        noise level to max instead of honouring cnc_level. cnc_level is the
        device byte (0 = full noise cancellation). create_profile raises if
        every editable slot (3-9) is already configured."""
        name = (name or "").strip()
        if not name:
            self.state["error"] = "Enter a mode name"
            return self.state

        def act(dev):
            slot = dev.create_profile(name, cnc_level=cnc_level,
                                      spatial=spatial, wind_block=0,
                                      anc_toggle=anc_toggle)
            dev.set_mode_idx(slot)
            mc = dev.mode_config(slot, drain=False)
            return slot, mc, dev.battery()
        try:
            slot, mc, batt = self._do(act)
            self._store_active(slot, mc, batt)
            self.state["connected"] = True
            self.state["error"] = ""
        except BmapConnectionError:
            self.state["connected"] = False
            self.state["error"] = "disconnected"
        except BmapError as e:
            self.state["error"] = str(e)
        return self.state


def _battery_icon(pct, connected):
    """Draw a small battery glyph with the percentage number."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    outline = (255, 255, 255, 255) if connected else (128, 128, 128, 255)
    d.rounded_rectangle([6, 20, 54, 46], radius=4, outline=outline, width=3)
    d.rectangle([54, 28, 59, 38], fill=outline)
    if pct is not None:
        fill_w = int(44 * max(0, min(100, pct)) / 100)
        color = (60, 200, 90, 255) if pct > 20 else (220, 70, 60, 255)
        d.rectangle([9, 23, 9 + fill_w, 43], fill=color)
    try:
        font = ImageFont.truetype("segoeui.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    txt = ("%d" % pct) if pct is not None else "?"
    d.text((32, 54), txt, fill=outline, anchor="mm", font=font)
    return img


def build_menu(ctrl):
    st = ctrl.state

    def mode_items():
        items = []
        for idx in sorted(st["modes"].keys()):
            disp, editable, configured, raw = st["modes"][idx][:4]
            if not disp or disp == "None":
                continue  # hide empty scratch slots (resolved display is 'None')
            label = disp + ("" if editable else "  (preset)")
            items.append(pystray.MenuItem(
                label,
                (lambda i: (lambda item: ctrl.switch_mode(i)))(idx),
                checked=(lambda i: (lambda item: st["mode_idx"] == i))(idx),
                radio=True,
            ))
        return items

    def cnc_items():
        editable = st["editable"]
        dev_cnc = st["cnc"]
        app_cnc = None if dev_cnc is None else 10 - dev_cnc
        items = []
        for lvl in CNC_APP_STEPS:
            label = "%d  (max ANC)" % lvl if lvl == 10 else (
                    "%d  (full ambient)" % lvl if lvl == 0 else "%d" % lvl)
            items.append(pystray.MenuItem(
                label,
                (lambda L: (lambda item: ctrl.set_cnc_app(L)))(lvl),
                checked=(lambda L: (lambda item: app_cnc == L))(lvl),
                radio=True,
                enabled=editable,
            ))
        return items

    def spatial_items():
        editable = st["editable"]
        items = []
        for val, label in SPATIAL_LABELS.items():
            items.append(pystray.MenuItem(
                label,
                (lambda v: (lambda item: ctrl.set_spatial(v)))(val),
                checked=(lambda v: (lambda item: st["spatial"] == v))(val),
                radio=True,
                enabled=editable,
            ))
        return items

    def sidetone_items():
        cur = st["sidetone"]
        items = []
        for name in SIDETONE_ORDER:
            items.append(pystray.MenuItem(
                name.capitalize(),
                (lambda n: (lambda item: ctrl.set_sidetone(n)))(name),
                checked=(lambda n: (lambda item: cur == n))(name),
                radio=True,
            ))
        return items

    def autooff_items():
        cur = st["auto_off"]
        items = []
        for mins in AUTO_OFF_MINUTES:
            label = "Never" if mins == 0 else AUTO_OFF_LABELS.get(mins, "%dmin" % mins)
            items.append(pystray.MenuItem(
                label,
                (lambda m: (lambda item: ctrl.set_auto_off(m)))(mins),
                checked=(lambda m: (lambda item: cur == m))(mins),
                radio=True,
            ))
        return items

    def status_text(item):
        if not st["connected"]:
            return "Disconnected -- click Refresh"
        b = st["battery"]
        return "Battery: %s%%   Mode: %s" % (b if b is not None else "?", st["mode_name"])

    def _open_window(icon, item):
        from bosewin import window as win
        win.show()

    def _quit(icon, item):
        # Destroy the pywebview window; that returns control from
        # webview.start() on the main thread, which then stops the tray and
        # hotkeys in main()'s finally block. Stopping the icon here instead
        # would leave the window (and its device port) alive.
        from bosewin import window as win
        win.request_quit()

    return pystray.Menu(
        pystray.MenuItem("Open Window", _open_window, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Mode", pystray.Menu(mode_items)),
        pystray.MenuItem("Noise level", pystray.Menu(cnc_items)),
        pystray.MenuItem("Immersive Audio", pystray.Menu(spatial_items)),
        pystray.MenuItem(
            "ANC",
            lambda item: ctrl.set_anc(not bool(st["anc"])),
            checked=lambda item: bool(st["anc"]),
            enabled=lambda item: st["editable"],
        ),
        # Wind Block on gen-1 is a destructive "force max ANC" action, not a
        # persisted toggle (turning it off does NOT restore the prior level),
        # and its status byte is meaningless -- so expose it as a one-shot
        # action rather than a checkbox that would lie about state.
        pystray.MenuItem(
            "Wind Block (force max ANC)",
            lambda item: ctrl.set_wind(True),
            enabled=lambda item: st["editable"],
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Self Voice", pystray.Menu(sidetone_items)),
        pystray.MenuItem("Auto-Off", pystray.Menu(autooff_items)),
        pystray.MenuItem(
            "Auto Play/Pause",
            lambda item: ctrl.set_auto_pause(not bool(st["auto_pause"])),
            checked=lambda item: bool(st["auto_pause"]),
        ),
        pystray.MenuItem(
            "Auto Answer Call",
            lambda item: ctrl.set_auto_answer(not bool(st["auto_answer"])),
            checked=lambda item: bool(st["auto_answer"]),
        ),
        pystray.MenuItem(
            "Multipoint",
            lambda item: ctrl.set_multipoint(not bool(st["multipoint"])),
            checked=lambda item: bool(st["multipoint"]),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Speak mode on hotkey", lambda item: _toggle_speak(),
                         checked=lambda item: _speak_enabled()),
        pystray.MenuItem("Start on login", lambda item: _toggle_autostart(),
                         checked=lambda item: _autostart_enabled()),
        pystray.MenuItem("Refresh", lambda icon, item: _refresh_and_redraw(icon, ctrl, full=True)),
        pystray.MenuItem("Quit", _quit),
    )


def _speak_enabled():
    try:
        from bosewin import settings
        return bool(settings.get("speak_mode"))
    except Exception:
        return False


def _toggle_speak():
    try:
        from bosewin import settings
        settings.toggle("speak_mode")
    except Exception:
        pass


def _autostart_enabled():
    try:
        from bosewin.autostart import is_enabled
        return is_enabled()
    except Exception:
        return False


def _toggle_autostart():
    try:
        from bosewin.autostart import toggle
        toggle()
    except Exception:
        pass

def _spoken_name(ctrl, idx):
    """Display name to announce for a mode index, from cached state."""
    modes = ctrl.state.get("modes") or {}
    lbl = modes.get(idx)
    if lbl and lbl[0]:
        return lbl[0]
    return ctrl.state.get("mode_name") or "mode"


def _announce_mode(ctrl, idx):
    try:
        from bosewin import settings, announce
        if settings.get("speak_mode"):
            announce.speak(_spoken_name(ctrl, idx))
    except Exception:
        pass


def _hotkey_callbacks(icon, ctrl):
    """Map hotkey action names to functions. switch_mode already syncs the
    cache fast (~0.1s), so we redraw from cache without another device read."""
    def _mode(idx):
        def go():
            ctrl.switch_mode(idx)
            _announce_mode(ctrl, idx)
            _redraw(icon, ctrl)
        return go

    def _cycle():
        st = ctrl.state
        modes = st.get("modes") or {}

        def real(table):
            return [i for i in sorted(table.keys())
                    if table[i] and table[i][0] and table[i][0] != "None"]

        order = real(modes)
        if not order:
            ctrl.refresh(full=True)
            order = real(ctrl.state.get("modes") or {})
        if not order:
            return
        cur = st.get("mode_idx")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
        ctrl.switch_mode(nxt)
        _announce_mode(ctrl, nxt)
        _redraw(icon, ctrl)

    return {
        "mode_quiet": _mode(0),
        "mode_aware": _mode(1),
        "mode_immersion": _mode(2),
        "mode_cycle": _cycle,
    }


def main():
    ctrl = Controller()

    icon = pystray.Icon("bosewin", title="Bose on Desktop")
    icon.menu = build_menu(ctrl)
    # Set an image BEFORE run() so the tray icon appears instantly. Without
    # this, pystray has no image to draw until the first refresh finishes
    # (~0.6s, or never if the device read errors), so nothing shows up at all.
    icon.icon = _battery_icon(None, False)

    hm = None
    try:
        from bosewin.hotkeys import HotkeyManager
        hm = HotkeyManager(_hotkey_callbacks(icon, ctrl))
        hm.start()
    except Exception:
        hm = None

    def on_setup(ic):
        ic.visible = True
        # Do the first (slow) device read off the icon thread so the tray
        # icon shows immediately and just updates when the read completes.
        threading.Thread(
            target=lambda: _refresh_and_redraw(ic, ctrl, full=True),
            daemon=True,
        ).start()

    try:
        from bosewin import settings, announce
        if settings.get("speak_mode"):
            threading.Thread(target=announce.warmup, daemon=True).start()
    except Exception:
        pass

    # Periodic background poll so the icon tracks battery / drops. Uses the
    # LIGHT refresh (battery + mode index, active config from cache ~0.1s) so
    # it never blocks on the slow 10-slot table read. Polls every 30s while
    # connected; re-probes every 5s while disconnected so a reconnect (e.g.
    # USB-C plugged back in) is reflected within a few seconds.
    def loop():
        import time
        while True:
            time.sleep(30 if ctrl.state.get("connected") else 5)
            try:
                _refresh_and_redraw(icon, ctrl, full=False)
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True).start()

    # Run the tray in a daemon thread; the pywebview window owns the MAIN
    # thread (webview.start() must run there). Sharing one Controller keeps a
    # single exclusive device connection behind both surfaces.
    def run_tray():
        try:
            icon.run(setup=on_setup)
        except Exception:
            pass

    threading.Thread(target=run_tray, daemon=True).start()

    from bosewin import window as win
    try:
        win.run(ctrl)
    finally:
        try:
            icon.stop()
        except Exception:
            pass
        if hm:
            hm.stop()
        try:
            from bosewin import announce
            announce.stop()
        except Exception:
            pass


def _refresh_and_redraw(icon, ctrl, full=True):
    ctrl.refresh(full=full)
    _redraw(icon, ctrl)


def _redraw(icon, ctrl):
    """Redraw the tray icon + tooltip from cached state (no device read)."""
    icon.icon = _battery_icon(ctrl.state["battery"], ctrl.state["connected"])
    tip = "Bose QC Ultra -- "
    tip += ("%s%%  %s" % (ctrl.state["battery"], ctrl.state["mode_name"])
            if ctrl.state["connected"] else "disconnected")
    icon.title = tip
    icon.update_menu()


if __name__ == "__main__":
    main()
