"""Tests for the QC Ultra (1st gen) device config and catalog registration."""

import pytest

import pybmap
from pybmap.connection import BmapConnection
from pybmap.constants import OP_GET, OP_SETGET, OP_STATUS, OP_START, OP_RESULT
from pybmap.devices import get_device, detect_device_type, qc_ultra1
from pybmap.devices.parsers import parse_mode_config_47
from pybmap.errors import BmapError


def test_gen1_registered():
    dev = get_device("qc_ultra1")
    assert dev.DEVICE_INFO["product_id"] == 0x4066
    assert dev.DEVICE_INFO["codename"] == "lonestarr"


def test_gen1_product_id_detection():
    assert detect_device_type(0x4066) == "qc_ultra1"


def test_gen1_catalog_entry_supported():
    entry = pybmap.lookup_device(0x4066)
    assert entry is not None
    assert entry.config == "qc_ultra1"
    assert pybmap.is_supported(0x4066)


def test_gen1_verified_getters_present():
    dev = get_device("qc_ultra1")
    for feat in ("battery", "firmware", "product_name", "cnc", "eq",
                 "buttons", "multipoint", "sidetone", "source"):
        assert feat in dev.FEATURES, feat


def test_gen1_omits_gen2_only_write_block():
    # AudioModesSettingsConfig [31.10] is FuncNotSupp on gen-1; it must not be
    # advertised, so set_cnc/set_anc correctly raise instead of writing blind.
    dev = get_device("qc_ultra1")
    assert "audio_settings" not in dev.FEATURES


def test_gen1_cnc_is_read_only():
    dev = get_device("qc_ultra1")
    assert "builder" not in dev.FEATURES["cnc"]


def test_gen1_mode_config_feature():
    dev = get_device("qc_ultra1")
    mc = dev.FEATURES["mode_config"]
    assert mc["addr"] == (31, 6)
    assert mc["parser"] is parse_mode_config_47
    assert callable(mc["builder"])


def test_gen1_mode_metadata():
    dev = get_device("qc_ultra1")
    assert dev.MODE_SLOTS == list(range(0, 10))
    assert dev.PRESET_MODES["quiet"]["idx"] == 0
    assert dev.MODE_BY_IDX[1] == "Aware"
    assert 3 in dev.EDITABLE_SLOTS and 0 not in dev.EDITABLE_SLOTS


def build_status_47(idx, editable=True, cnc=10, auto_cnc=0, spatial=0,
                    wind=1, anc=0, name=b"None", pb=(0, 0), flag41=13):
    """Assemble a synthetic 47-byte gen-1 ModeConfig STATUS payload."""
    buf = bytearray(47)
    buf[0] = idx
    buf[1], buf[2] = pb
    buf[3] = 1 if editable else 0
    buf[4] = 0            # configured
    buf[5] = 0
    buf[6:6 + len(name)] = name
    buf[41] = flag41
    buf[42] = cnc
    buf[43] = auto_cnc
    buf[44] = spatial
    buf[45] = wind
    buf[46] = anc
    return bytes(buf)


def test_parse_mode_config_47_fields():
    payload = build_status_47(3, editable=True, cnc=7, spatial=2, wind=1, anc=1,
                              name=b"Home")
    mc = parse_mode_config_47(payload)
    assert mc.mode_idx == 3
    assert mc.name == "Home"
    assert mc.cnc_level == 7
    assert mc.spatial == 2
    assert mc.wind_block is True
    assert mc.anc_toggle is True
    assert mc.editable is True


class Gen1ModeTransport:
    """Fake transport backing a per-slot ModeConfig store for gen-1 tests.

    Serves current_mode [31.3] GET and ModeConfig [31.6] GET(idx)/SETGET, and
    records SETGET writes so tests can assert the CNC round-trip.
    """

    def __init__(self, current_idx, slots):
        self.current_idx = current_idx
        self.slots = dict(slots)   # idx -> dict(editable, cnc, spatial, wind, anc, name)
        self.sent = []
        self.closed = False

    def _status(self, idx):
        s = self.slots[idx]
        return build_status_47(idx, editable=s["editable"], cnc=s["cnc"],
                               spatial=s["spatial"], wind=s["wind"],
                               anc=s["anc"], name=s["name"])

    def send_recv(self, packet, drain=False):
        self.sent.append(packet)
        fb, fn, op, ln = packet[0], packet[1], packet[2] & 0x0F, packet[3]
        payload = packet[4:4 + ln]
        if (fb, fn) == (31, 3) and op == OP_GET:
            return bytes([31, 3, OP_STATUS, 1, self.current_idx])
        if (fb, fn) == (31, 3) and op == OP_START:
            self.current_idx = payload[0]
            return bytes([31, 3, OP_RESULT, 1, self.current_idx])
        if (fb, fn) == (31, 6) and op == OP_GET:
            idx = payload[0]
            if idx not in self.slots:
                return bytes([31, 6, 4, 1, 7])  # DataUnavail for empty slot
            body = self._status(idx)
            return bytes([31, 6, OP_STATUS, len(body)]) + body
        if (fb, fn) == (31, 6) and op == OP_SETGET:
            idx = payload[0]
            s = self.slots[idx]
            cnc, auto, spatial = payload[35], payload[36], payload[37]
            wind, anc = payload[38], payload[39]
            # Faithful gen-1 firmware behaviour: the transmitted wind byte is a
            # trigger. wind=1 clamps cnc->0 and anc->on regardless of the sent
            # cnc; wind=0 stores the sent cnc/anc as-is.
            if wind:
                cnc, anc = 0, 1
            s["cnc"], s["auto"], s["spatial"] = cnc, auto, spatial
            s["wind"], s["anc"] = wind, anc
            body = self._status(idx)
            return bytes([31, 6, OP_STATUS, len(body)]) + body
        return bytes([fb, fn, 4, 1, 4])  # FuncNotSupp

    def close(self):
        self.closed = True


def _slot(editable=True, cnc=10, spatial=0, wind=1, anc=0, name=b"None"):
    return {"editable": editable, "cnc": cnc, "auto": 0, "spatial": spatial,
            "wind": wind, "anc": anc, "name": name}


def test_gen1_set_cnc_writes_current_mode():
    # Current mode is editable custom slot 3 (Home) at CNC 2. The default slot
    # wind readback is 1; the fix must send wind=0 so the level actually sticks
    # (sending wind=1 would clamp cnc->0 on real firmware, modelled by the fake).
    t = Gen1ModeTransport(3, {3: _slot(editable=True, cnc=2, wind=1, name=b"Home")})
    dev = BmapConnection(t, qc_ultra1)
    dev.set_cnc(8)
    # Store updated (not clamped to 0), and a SETGET was issued on [31.6] with
    # cnc byte = 8 and the wind trigger byte = 0.
    assert t.slots[3]["cnc"] == 8
    setgets = [p for p in t.sent if p[0] == 31 and p[1] == 6 and (p[2] & 0x0F) == OP_SETGET]
    assert setgets and setgets[-1][4 + 35] == 8
    assert setgets[-1][4 + 38] == 0  # wind trigger off, else cnc would clamp


def test_gen1_enable_wind_clamps_cnc():
    # Engaging Wind Block sends wind=1, which the firmware treats as "max ANC":
    # cnc is driven to 0. This mirrors the app's "Wind Block automatically
    # adjusts noise cancellation" behaviour.
    t = Gen1ModeTransport(3, {3: _slot(editable=True, cnc=6, wind=1, name=b"Home")})
    dev = BmapConnection(t, qc_ultra1)
    dev.set_wind(True)
    setgets = [p for p in t.sent if p[0] == 31 and p[1] == 6 and (p[2] & 0x0F) == OP_SETGET]
    assert setgets and setgets[-1][4 + 38] == 1  # wind trigger on
    assert t.slots[3]["cnc"] == 0  # clamped by firmware


def test_gen1_set_cnc_rejects_locked_preset():
    # Current mode is a locked preset (Quiet, idx 0, editable=False).
    t = Gen1ModeTransport(0, {0: _slot(editable=False, cnc=0, name=b"Quiet")})
    dev = BmapConnection(t, qc_ultra1)
    with pytest.raises(BmapError):
        dev.set_cnc(5)
    assert t.slots[0]["cnc"] == 0  # unchanged


def test_gen1_set_spatial_and_wind_via_mode_config():
    t = Gen1ModeTransport(4, {4: _slot(editable=True, cnc=5, spatial=0, wind=1, name=b"Focus")})
    dev = BmapConnection(t, qc_ultra1)
    dev.set_spatial("head")
    dev.set_wind(False)
    assert t.slots[4]["spatial"] == 2
    assert t.slots[4]["wind"] == 0
    assert t.slots[4]["cnc"] == 5  # untouched by spatial/wind writes


# ── Auto-Off timer [1.4] and read-only voice_prompts ────────────────────────

from pybmap.devices.parsers import (
    parse_auto_off, build_auto_off, AUTO_OFF_BY_LABEL,
)


def test_parse_auto_off_le_minutes():
    assert parse_auto_off(bytes([0x00, 0x00, 0x00])) == 0      # Never
    assert parse_auto_off(bytes([0x14, 0x00, 0x00])) == 20     # 20 min
    assert parse_auto_off(bytes([0xa0, 0x00, 0x05])) == 1440   # 24 h


def test_build_auto_off_roundtrip():
    for label, mins in AUTO_OFF_BY_LABEL.items():
        payload = build_auto_off(label)
        assert len(payload) == 3
        assert payload[1] == 0
        assert parse_auto_off(payload) == mins
    assert build_auto_off(1440) == bytes([0xa0, 0x00, 0x05])
    assert build_auto_off("never") == bytes([0x00, 0x00, 0x00])


def test_build_auto_off_rejects_bad_label():
    with pytest.raises(ValueError):
        build_auto_off("forever")


def test_gen1_auto_off_feature_present():
    dev = get_device("qc_ultra1")
    assert dev.FEATURES["auto_off"]["addr"] == (1, 4)
    assert callable(dev.FEATURES["auto_off"]["builder"])


def test_gen1_voice_prompts_read_only():
    # [1.3] write format differs from its read format on gen-1; must be
    # advertised as a getter only (no builder) so set_prompts raises cleanly.
    dev = get_device("qc_ultra1")
    assert "voice_prompts" in dev.FEATURES
    assert "builder" not in dev.FEATURES["voice_prompts"]


class SettingTransport:
    """Minimal fake transport for single-block [1.x] GET/SETGET settings."""

    def __init__(self, blocks):
        self.blocks = {k: bytearray(v) for k, v in blocks.items()}
        self.sent = []
        self.closed = False

    def send_recv(self, packet, drain=False):
        self.sent.append(packet)
        fb, fn, op, ln = packet[0], packet[1], packet[2] & 0x0F, packet[3]
        payload = packet[4:4 + ln]
        key = (fb, fn)
        if key not in self.blocks:
            return bytes([fb, fn, 4, 1, 4])  # FuncNotSupp
        if op == OP_SETGET:
            self.blocks[key] = bytearray(payload)
        body = bytes(self.blocks[key])
        return bytes([fb, fn, OP_STATUS, len(body)]) + body

    def close(self):
        self.closed = True


def test_gen1_auto_off_get_set_roundtrip():
    t = SettingTransport({(1, 4): bytes([0x14, 0x00, 0x00])})
    dev = BmapConnection(t, qc_ultra1)
    assert dev.auto_off() == 20
    dev.set_auto_off("never")
    assert dev.auto_off() == 0
    dev.set_auto_off(1440)
    assert dev.auto_off() == 1440


def test_gen1_set_prompts_raises_read_only():
    t = SettingTransport({(1, 3): bytes([0xe1, 0, 1, 0x81, 0x5e, 1, 1])})
    dev = BmapConnection(t, qc_ultra1)
    with pytest.raises(BmapError):
        dev.set_prompts(False)


def test_gen1_mode_config_single_slot_read():
    # mode_config(idx) reads exactly one slot via a single [31.6] GET and does
    # NOT enumerate all slots (the fast path used by the tray app's refresh).
    t = Gen1ModeTransport(0, {
        2: _slot(editable=False, cnc=5, spatial=1, anc=1, name=b"Immersion"),
        3: _slot(editable=True, cnc=7, name=b"None"),
    })
    dev = BmapConnection(t, qc_ultra1)
    mc = dev.mode_config(2)
    assert mc is not None
    assert mc.mode_idx == 2
    assert mc.cnc_level == 5
    assert mc.spatial == 1
    # Exactly one ModeConfig GET was issued (single-slot, not a 10-slot sweep).
    gets = [p for p in t.sent
            if p[0] == 31 and p[1] == 6 and (p[2] & 0x0F) == OP_GET]
    assert len(gets) == 1
    assert gets[0][4] == 2  # requested idx


def test_gen1_mode_config_empty_slot_returns_none():
    t = Gen1ModeTransport(0, {3: _slot(editable=True, cnc=7, name=b"None")})
    dev = BmapConnection(t, qc_ultra1)
    assert dev.mode_config(5) is None  # slot 5 absent -> DataUnavail -> None


def test_gen1_set_mode_idx_switches_by_index():
    # Custom slots all store name "None"; switching must be by index, not name.
    t = Gen1ModeTransport(0, {
        3: _slot(editable=True, cnc=10, name=b"None"),
        4: _slot(editable=True, cnc=7, name=b"None"),
    })
    dev = BmapConnection(t, qc_ultra1)
    dev.set_mode_idx(4)
    # The last current_mode START must carry idx 4, and state must update.
    starts = [p for p in t.sent if p[0] == 31 and p[1] == 3 and (p[2] & 0x0F) == OP_START]
    assert starts, "no [31.3] START sent"
    assert starts[-1][4] == 4
    assert t.current_idx == 4


def test_gen1_multipoint_parse_and_build():
    from pybmap.devices import parsers as P
    # ON=0x07, OFF=0x06; only bit 0x01 encodes enabled on gen-1.
    assert P.parse_multipoint_gen1(b"\x07") is True
    assert P.parse_multipoint_gen1(b"\x06") is False
    assert P.build_multipoint_gen1(True) == b"\x07"
    assert P.build_multipoint_gen1(False) == b"\x06"
    # Round-trip through the config-selected funcs.
    from pybmap.devices import qc_ultra1
    mp = qc_ultra1.FEATURES["multipoint"]
    assert mp["parser"](mp["builder"](True)) is True
    assert mp["parser"](mp["builder"](False)) is False


def test_gen1_paired_and_mac_parsers():
    from pybmap.devices import parsers as P
    # [4.9] connected device = bare 6-byte MAC.
    assert P.parse_mac(bytes.fromhex("dc567b56ebaa")) == "dc:56:7b:56:eb:aa"
    assert P.parse_mac(b"") is None
    # [4.4] paired list = lead byte + N*6-byte MACs.
    raw = bytes.fromhex("01" "dc567b56ebaa" "78a7c70c4a03")
    assert P.parse_paired_gen1(raw) == ["dc:56:7b:56:eb:aa", "78:a7:c7:0c:4a:03"]
    assert P.parse_paired_gen1(b"") == []
    # Feature wiring is read-only (no builder).
    from pybmap.devices import qc_ultra1
    assert "builder" not in qc_ultra1.FEATURES["paired_devices"]
    assert "builder" not in qc_ultra1.FEATURES["connected_device"]
