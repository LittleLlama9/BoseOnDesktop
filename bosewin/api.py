"""JS <-> Python bridge for the pywebview window.

Wraps the shared :class:`bosewin.gui.Controller` so the web front-end can read
state and drive the headphones. Every method returns JSON-safe data (dicts /
lists / primitives) that pywebview marshals to a JS promise. Device I/O runs on
pywebview's js_api worker thread, so slow reads never block the GUI thread.

The core control methods return the full serialised state so the front-end can
re-render from a single value after every action.
"""

from pybmap.constants import SIDETONE_NAMES
from pybmap.errors import BmapError
from pybmap.devices.parsers import AUTO_OFF_MINUTES


SPATIAL_LABELS = {0: "Off", 1: "Still", 2: "Motion"}
SIDETONE_ORDER = ["high", "medium", "low", "off"]  # app display order

# Shortcut (volume-strip long-press) actions the gen-1 firmware actually
# accepts for button 128 / long_press -- each verified reversibly on hardware
# (VPA, BatteryLevel, SpatialAudioMode, SpotifyGo all round-trip; the device
# coerces NotConfigured -> Disabled). Order + copy mirror the Bose app.
# The `action` values match ACTION_MODES names (what set_buttons resolves).
SHORTCUT_OPTIONS = [
    {"action": "BatteryLevel", "label": "Hear Battery Level", "icon": "battery",
     "desc": "A voice prompt announces the battery level of your headphones."},
    {"action": "SpatialAudioMode", "label": "Change Immersive Audio",
     "icon": "immersion",
     "desc": "Cycle through Still, Motion, and Off settings."},
    {"action": "VPA", "label": "Access Your Voice Assistant", "icon": "vpa",
     "desc": "Use voice control on your mobile device."},
    {"action": "SpotifyGo", "label": "Spotify", "icon": "spotify",
     "desc": "Use your shortcut to resume Spotify. Do it again to discover "
             "music you'll love. To set this shortcut, make sure your Spotify "
             "app is up to date."},
]
SHORTCUT_DISABLED = "Disabled"  # toggle-off state the device accepts
SHORTCUT_HINT = ("Touch and hold the volume strip on the right earcup to use "
                 "your shortcut.")

# Support / help links (open in the system browser; no Bose cloud calls).
TIPS_URL = "https://www.bose.com/en_us/support/articles/HC2751/productCodes/qc_ultra_headphones/article.html"
FAQ_URL = "https://www.bose.com/en_us/support/products/bose_headphones_support/bose_over_ear_headphones_support/quietcomfort-ultra-headphones.html"


def _cnc_app(device_byte):
    """Device CNC byte (0 = max ANC) -> app scale (10 = max)."""
    if device_byte is None:
        return None
    return 10 - device_byte


class Api:
    def __init__(self, controller, on_show=None):
        self._ctrl = controller
        self._on_show = on_show  # optional: called when JS requests the window

    # ---- state ---------------------------------------------------------

    def _serialize(self):
        st = self._ctrl.state
        modes = []
        table = st.get("modes") or {}
        for idx in sorted(table.keys()):
            lbl = table[idx]
            disp, editable, configured, name = lbl[0], lbl[1], lbl[2], lbl[3]
            cnc = lbl[4] if len(lbl) >= 7 else None
            spatial = lbl[5] if len(lbl) >= 7 else None
            anc = lbl[6] if len(lbl) >= 7 else None
            modes.append({
                "idx": idx,
                "name": disp,
                "editable": bool(editable),
                "configured": bool(configured),
                "cnc_app": _cnc_app(cnc),
                "spatial": spatial,
                "anc": bool(anc) if anc is not None else None,
                "active": idx == st.get("mode_idx"),
            })
        sidetone = st.get("sidetone")
        return {
            "connected": bool(st.get("connected")),
            "error": st.get("error") or "",
            "battery": st.get("battery"),
            "mode_idx": st.get("mode_idx"),
            "mode_name": st.get("mode_name"),
            "editable": bool(st.get("editable")),
            "cnc_app": _cnc_app(st.get("cnc")),
            "spatial": st.get("spatial"),
            "anc": st.get("anc"),
            "sidetone": sidetone,
            "auto_off": st.get("auto_off"),
            "auto_pause": st.get("auto_pause"),
            "auto_answer": st.get("auto_answer"),
            "multipoint": st.get("multipoint"),
            "modes": modes,
        }

    def get_state(self):
        """Cached state, no device read (instant)."""
        return self._serialize()

    def refresh(self):
        """Full device read (~0.6s), then return fresh state."""
        self._ctrl.refresh(full=True)
        return self._serialize()

    def poll(self):
        """Light device read (battery + active mode, ~0.1s)."""
        self._ctrl.refresh(full=False)
        return self._serialize()

    # ---- mode / noise --------------------------------------------------

    def set_mode(self, idx):
        self._ctrl.switch_mode(int(idx))
        return self._serialize()

    def delete_mode(self, idx):
        self._ctrl.delete_mode(int(idx))
        return self._serialize()

    def set_cnc_app(self, level):
        self._ctrl.set_cnc_app(int(level))
        return self._serialize()

    def set_spatial(self, value):
        self._ctrl.set_spatial(int(value))
        return self._serialize()

    def set_wind(self):
        """One-shot: force max ANC (gen-1 Wind Block is not a persisted toggle)."""
        self._ctrl.set_wind(True)
        return self._serialize()

    def set_anc(self, on):
        self._ctrl.set_anc(bool(on))
        return self._serialize()

    # ---- preferences ---------------------------------------------------

    def set_sidetone(self, name):
        self._ctrl.set_sidetone(str(name))
        return self._serialize()

    def set_auto_off(self, minutes):
        self._ctrl.set_auto_off(int(minutes))
        return self._serialize()

    def set_auto_pause(self, on):
        self._ctrl.set_auto_pause(bool(on))
        return self._serialize()

    def set_auto_answer(self, on):
        self._ctrl.set_auto_answer(bool(on))
        return self._serialize()

    def set_multipoint(self, on):
        self._ctrl.set_multipoint(bool(on))
        return self._serialize()

    # ---- lazy extras (name / paired / eq / prompts) --------------------

    def get_extras(self):
        """Read name, paired devices, EQ and voice prompts on demand.

        These aren't in the fast core refresh; the front-end asks for them when
        opening the Bluetooth / Settings / EQ screens. Best-effort per field.
        """
        out = {"name": None, "firmware": None, "paired": [], "eq": None,
               "prompts": None, "error": ""}

        def read(dev):
            try:
                out["name"] = dev.name()
            except BmapError:
                pass
            try:
                out["firmware"] = dev.firmware()
            except BmapError:
                pass
            try:
                out["paired"] = [
                    {"mac": getattr(p, "mac", str(p)),
                     "name": getattr(p, "name", None)}
                    for p in (dev.paired_devices() or [])
                ]
            except BmapError:
                pass
            try:
                bands = dev.eq()
                vals = [getattr(b, "current", getattr(b, "value", b)) for b in bands]
                if len(vals) >= 3:
                    out["eq"] = {"bass": vals[0], "mid": vals[1], "treble": vals[2]}
            except BmapError:
                pass
            try:
                enabled, lang = dev.prompts()
                out["prompts"] = {"enabled": bool(enabled), "language": lang}
            except BmapError:
                pass
            return out

        try:
            return self._ctrl._do(read)
        except Exception as e:
            out["error"] = str(e)
            return out

    def set_name(self, new_name):
        try:
            self._ctrl._do(lambda d: d.set_name(str(new_name)))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    # ---- shortcut (volume-strip long-press remap) ---------------------

    def _valid_shortcut_actions(self):
        return [o["action"] for o in SHORTCUT_OPTIONS]

    def _last_shortcut(self):
        """Remembered action to restore when the shortcut toggle turns on."""
        try:
            from bosewin import settings
            v = settings.get("shortcut_last_action")
        except Exception:
            v = None
        return v if v in self._valid_shortcut_actions() else "SpotifyGo"

    def _remember_shortcut(self, action):
        if action in self._valid_shortcut_actions():
            try:
                from bosewin import settings
                settings.set("shortcut_last_action", action)
            except Exception:
                pass

    def get_shortcut(self):
        """Current Shortcut action + the selectable options (gen-1 verified)."""
        def read(d):
            b = d.buttons()
            return {"button": b.button_name, "event": b.event_name,
                    "action": b.action_name}
        try:
            r = self._ctrl._do(read)
        except Exception as e:
            return {"error": str(e), "options": SHORTCUT_OPTIONS, "action": None,
                    "enabled": True, "last_action": self._last_shortcut(),
                    "hint": SHORTCUT_HINT}
        action = r.get("action")
        enabled = action != SHORTCUT_DISABLED
        if enabled:
            self._remember_shortcut(action)
        r["options"] = SHORTCUT_OPTIONS
        r["enabled"] = enabled
        r["last_action"] = self._last_shortcut()
        r["hint"] = SHORTCUT_HINT
        return r

    def set_shortcut(self, action):
        """Remap the Shortcut long-press action, then read it back.

        Pass "Disabled" to turn the shortcut off; any valid action turns it on
        and is remembered as the value to restore next time it is re-enabled.
        """
        action = str(action)
        def act(d):
            b = d.buttons()
            d.set_buttons(b.button_id, b.event, action)
            return {"action": d.buttons().action_name}
        try:
            r = self._ctrl._do(act)
            got = r["action"]
            self._remember_shortcut(got)
            return {"ok": True, "action": got,
                    "enabled": got != SHORTCUT_DISABLED,
                    "options": SHORTCUT_OPTIONS,
                    "last_action": self._last_shortcut()}
        except Exception as e:
            return {"ok": False, "error": str(e), "options": SHORTCUT_OPTIONS}

    # ---- technical info + help links ----------------------------------

    def get_tech_info(self):
        """Read-only device identity for the Technical Info screen."""
        def read(d):
            info = getattr(d._device, "DEVICE_INFO", {}) or {}
            pid = info.get("product_id")
            out = {"model": info.get("name"),
                   "product_id": ("0x%04X" % pid) if isinstance(pid, int) else pid,
                   "codename": info.get("codename"),
                   "platform": info.get("platform"),
                   "firmware": None}
            try:
                out["firmware"] = d.firmware()
            except Exception:
                pass
            return out
        try:
            return self._ctrl._do(read)
        except Exception as e:
            return {"error": str(e)}

    def open_url(self, which):
        """Open a support link in the system browser (no cloud calls made)."""
        import webbrowser
        url = {"tips": TIPS_URL, "faq": FAQ_URL}.get(str(which), str(which))
        try:
            webbrowser.open(url)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_eq(self, bass, mid, treble):
        try:
            self._ctrl._do(lambda d: d.set_eq(int(bass), int(mid), int(treble)))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        # Remember it so we can re-apply after the device's reconnect flat-reset.
        self._ctrl.save_eq(bass, mid, treble)
        return {"ok": True, "eq": {"bass": int(bass), "mid": int(mid),
                                   "treble": int(treble)}}

    # ---- app-only settings --------------------------------------------

    def get_app_settings(self):
        out = {"speak_mode": False, "autostart": False, "hotkeys": {}}
        try:
            from bosewin import settings
            out["speak_mode"] = bool(settings.get("speak_mode"))
        except Exception:
            pass
        try:
            from bosewin.autostart import is_enabled
            out["autostart"] = bool(is_enabled())
        except Exception:
            pass
        try:
            from bosewin.hotkeys import HOTKEY_LABELS
            out["hotkeys"] = dict(HOTKEY_LABELS)
        except Exception:
            pass
        return out

    def toggle_speak(self):
        try:
            from bosewin import settings
            return {"speak_mode": bool(settings.toggle("speak_mode"))}
        except Exception as e:
            return {"error": str(e)}

    def toggle_autostart(self):
        try:
            from bosewin.autostart import toggle
            return {"autostart": bool(toggle())}
        except Exception as e:
            return {"error": str(e)}

    # ---- meta for the UI ----------------------------------------------

    def get_options(self):
        """Static option lists the UI renders (auto-off steps, sidetone order)."""
        return {
            "auto_off_minutes": list(AUTO_OFF_MINUTES),
            "sidetone_order": list(SIDETONE_ORDER),
            "sidetone_names": SIDETONE_NAMES,
            "spatial_labels": SPATIAL_LABELS,
        }
