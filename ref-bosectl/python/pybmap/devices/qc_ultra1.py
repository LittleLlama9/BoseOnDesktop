"""Bose QC Ultra Headphones (1st gen) device configuration.

Codename "lonestarr", product_id 0x4066, variant 0x01.
Verified against Matthew's hardware on firmware 1.6.7+g6ebabd2 (2026-07-20)
over Windows SPP RFCOMM (COM3).

Gen-1 speaks the same BMAP dialect as QC Ultra 2 on the Settings [1.x] blocks,
but DIFFERS from gen-2 in two important ways discovered by read-only sweep:

  - AudioModesSettingsConfig [31.10] is FuncNotSupp on gen-1. This is the block
    gen-2 uses for set_cnc / set_anc / set_wind / set_spatial. That write path
    does NOT exist here, so those setters are intentionally omitted until the
    real gen-1 CNC-set mechanism is mapped app-in-the-loop.
  - GetAllModes [31.1] requires auth (OpNotSupp) on gen-1; gen-2 allows GET.

Verified WORKING getters (GET op 1, no auth):
    battery [2.2], firmware [0.5], productid [0.3], product_name [1.2],
    voice_prompts [1.3], auto_off [1.4], cnc [1.5], eq [1.7], buttons [1.9],
    multipoint [1.10], sidetone [1.11], auto_pause [1.24], auto_answer [1.27],
    pairing [4.8], source [5.1], current_mode [31.3], favorites [31.8].

Setters below use only unauthenticated SETGET on blocks whose getters are
verified present. No key extraction, no replay. cnc-set is deliberately absent.
"""

from . import parsers

# BMAP over the same RFCOMM channel as gen-2. On Windows the SPP virtual COM
# port abstracts the channel, but keep this for the Linux transport path.
RFCOMM_CHANNEL = 2

DEVICE_INFO = {
    "name": "Bose QC Ultra Headphones (1st Gen)",
    "codename": "lonestarr",
    "platform": "OTG-QCC-514x",
    "product_id": 0x4066,
    "variant": 0x01,
}

FEATURES = {
    "battery": {
        "addr": (2, 2),
        "parser": parsers.parse_battery,
    },
    "firmware": {
        "addr": (0, 5),
        "parser": parsers.parse_firmware,
    },
    "product_name": {
        "addr": (1, 2),
        "parser": parsers.parse_product_name,
        "builder": lambda name: b"\x00" + name.encode("utf-8"),
    },
    "voice_prompts": {
        "addr": (1, 3),
        "parser": parsers.parse_voice_prompts,
        # NO builder: gen-1 [1.3] write semantics differ from its read format
        # (echoing the 7-byte readback via SETGET toggled the battery-startup
        # byte rather than setting it). Left read-only until the dedicated
        # voice-prompt write command is reverse-engineered. Proven fw 1.6.7.
    },
    # Auto-Off standby timer [1.4]. 3-byte LE-minutes payload; SETGET verified
    # and reflected in the official Bose app (fw 1.6.7, 2026-07-20).
    "auto_off": {
        "addr": (1, 4),
        "parser": parsers.parse_auto_off,
        "builder": parsers.build_auto_off,
    },
    # CNC getter [1.5] (current, max). The gen-2 [31.10] write path is
    # FuncNotSupp on gen-1; noise-level writes go through the current mode's
    # ModeConfig [31.6] instead (see mode_config below + the set_cnc fallback
    # in connection._update_current_mode_settings).
    "cnc": {
        "addr": (1, 5),
        "parser": parsers.parse_cnc,
    },
    # Per-mode config [31.6]. GET(idx) returns a 47-byte STATUS; SETGET writes
    # the 40-byte gen-2-style payload (verified accepted on fw 1.6.7). Carries
    # CNC/spatial/wind/anc for each slot — the gen-1 noise-control surface.
    "mode_config": {
        "addr": (31, 6),
        "parser": parsers.parse_mode_config_47,
        "builder": parsers.build_mode_config_40,
    },
    "eq": {
        "addr": (1, 7),
        "parser": parsers.parse_eq,
        "builder": parsers.build_eq_band,
    },
    "buttons": {
        "addr": (1, 9),
        "parser": parsers.parse_buttons,
        "builder": parsers.build_buttons,
    },
    "multipoint": {
        "addr": (1, 10),
        "parser": parsers.parse_multipoint_gen1,
        "builder": parsers.build_multipoint_gen1,
    },
    "sidetone": {
        "addr": (1, 11),
        "parser": parsers.parse_sidetone,
        "builder": parsers.build_sidetone,
    },
    "auto_pause": {
        "addr": (1, 24),
        "parser": parsers.parse_bool,
        "builder": parsers.build_toggle,
    },
    "auto_answer": {
        "addr": (1, 27),
        "parser": parsers.parse_bool,
        "builder": parsers.build_toggle,
    },
    "pairing": {
        "addr": (4, 8),
    },
    "paired_devices": {
        "addr": (4, 4),
        "parser": parsers.parse_paired_gen1,
    },
    "connected_device": {
        "addr": (4, 9),
        "parser": parsers.parse_mac,
    },
    "source": {
        "addr": (5, 1),
        "parser": parsers.parse_source,
    },
    "current_mode": {
        "addr": (31, 3),
    },
    "favorites": {
        "addr": (31, 8),
    },
}

# Gen-1 GetAllModes [31.1] is auth-gated (OpNotSupp) for GET and its START
# does not reliably stream every slot's STATUS, so modes() enumerates each
# slot individually with a ModeConfig [31.6] GET. MODE_SLOTS drives that scan.
MODE_SLOTS = list(range(0, 10))

# Preset (non-editable) noise modes, index-matched to the app ordering.
# Custom profile names (Home / Focus / etc.) are read live from mode_config.
PRESET_MODES = {
    "quiet": {"idx": 0, "description": "Maximum noise cancellation"},
    "aware": {"idx": 1, "description": "Full ambient pass-through"},
    "immersion": {"idx": 2, "description": "Immersive spatial audio preset"},
}

MODE_BY_IDX = {0: "Quiet", 1: "Aware", 2: "Immersion"}

# Editable custom-profile slots (presets 0-2 are locked). Slots 6-9 ship empty.
EDITABLE_SLOTS = [3, 4, 5, 6, 7, 8, 9]

# The transmitted wind_block byte in a ModeConfig [31.6] write is a command
# TRIGGER, not persisted state: sending 1 clamps cnc->0 and anc->on (Wind Block
# == max ANC). The STATUS readback of that byte is meaningless (always 1). The
# connection layer keys off this flag to default the trigger to 0 on
# cnc/spatial/anc edits so they actually take. Proven on fw 1.6.7 (2026-07-20).
MODE_WIND_IS_TRIGGER = True

STATUS_OFFSETS = {
    "editable": 3,
    "configured": 4,
    "name": (6, 38),
    "cnc_level": 42,
    "auto_cnc": 43,
    "spatial": 44,
    "wind_block": 45,
    "anc_toggle": 46,
}
