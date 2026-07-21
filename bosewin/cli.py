"""bosewin CLI -- Windows control for Bose QC Ultra (1st gen) over SPP.

Read commands plus setters using verified unauthenticated SETGET on blocks
present on gen-1. Noise control (CNC level, Immersive Audio, Wind Block, ANC)
is written through the current mode's ModeConfig [31.6] since the gen-2
AudioModesSettingsConfig [31.10] write path is FuncNotSupp here. Only editable
custom modes can be changed; locked presets (Quiet/Aware/Immersion) raise.
"""

import argparse
import sys

import bosewin
from bosewin.win_discovery import find_bose_ports
from pybmap.errors import BmapError, BmapConnectionError, BmapNotFoundError
from pybmap.protocol import bmap_packet, parse_all_responses, fmt_response
from pybmap.constants import OP_GET


def _mode_disp(dev, idx, mc):
    """Best display name for a mode: stored custom name, else the voice-prompt
    scenario (HOME/FOCUS/etc, which is what the app shows), else preset name."""
    if mc is not None and mc.name and mc.name != "None":
        return mc.name
    if mc is not None and mc.prompt and not mc.prompt.startswith("("):
        p = mc.prompt
        if p != "NONE":
            return p.capitalize()
    return dev._mode_name_from_idx(idx)


def _print_status(dev):
    info = dev.device_info
    print("Model     : %s" % info.get("name"))
    print("Firmware  : %s" % dev.firmware())
    print("Name      : %s" % dev.name())
    print("Battery   : %d%%" % dev.battery())
    try:
        idx = dev.mode_idx()
        mc = dev.modes().get(idx)
        if mc is not None:
            disp = _mode_disp(dev, idx, mc)
            print("Mode      : %s [%d]%s" % (disp, idx, "" if mc.editable else " (preset)"))
            # Wind byte (off45) is a meaningless constant on gen-1 -- omit it.
            print("Immersive : %s   ANC: %s"
                  % ({0:"off",1:"still",2:"motion"}.get(mc.spatial, mc.spatial),
                     "on" if mc.anc_toggle else "off"))
    except BmapError:
        pass
    try:
        cur, mx = dev.cnc()
        # Raw device scale is inverted vs the mobile app: device 0 = max ANC,
        # device mx = full ambient. Show both so it matches the app slider.
        print("Noise     : %d/%d app-scale (device cnc=%d, 0=max ANC)"
              % (mx - cur, mx, cur))
    except BmapError:
        pass
    try:
        bands = dev.eq()
        print("EQ        : " + "  ".join("%s %+d" % (b.name, b.current) for b in bands))
    except BmapError:
        pass
    try:
        print("Sidetone  : %s" % dev.sidetone())
    except BmapError:
        pass
    try:
        print("Multipoint: %s" % ("on" if dev.multipoint() else "off"))
    except BmapError:
        pass
    try:
        print("AutoPause : %s   AutoAnswer: %s"
              % ("on" if dev.auto_pause() else "off",
                 "on" if dev.auto_answer() else "off"))
    except BmapError:
        pass
    try:
        from pybmap.devices.parsers import AUTO_OFF_LABELS
        mins = dev.auto_off()
        print("AutoOff   : %s (%d min)" % (AUTO_OFF_LABELS.get(mins, "%dmin" % mins), mins))
    except BmapError:
        pass
    try:
        b = dev.buttons()
        print("Shortcut  : %s %s -> %s" % (b.button_name, b.event_name, b.action_name))
    except BmapError:
        pass
    try:
        src = dev.source()
        print("Source    : %s%s" % (src.source_type,
              (" " + src.source_mac) if src.source_mac else ""))
    except BmapError:
        pass


def cmd_ports(args):
    ports = find_bose_ports()
    if not ports:
        print("No Bose SPP COM ports found.")
        return 1
    for bp in ports:
        supported = bp.device_type or "unsupported"
        print("%s  %s  pid=0x%04x  %s  [%s]"
              % (bp.port, bp.mac, bp.product_id, bp.name, supported))
    return 0


def _bool(s):
    v = s.strip().lower()
    if v in ("on", "true", "1", "yes", "enable", "enabled"):
        return True
    if v in ("off", "false", "0", "no", "disable", "disabled"):
        return False
    raise argparse.ArgumentTypeError("expected on/off, got %r" % s)


def _connect(args):
    if getattr(args, "usb", False):
        return bosewin.connect_usb(device_type=args.device)
    if getattr(args, "bt", False):
        return bosewin.connect(port=args.port, device_type=args.device)
    # No transport specified: prefer USB if a data cable is present (works
    # during analog gaming, no BT needed), else fall back to Bluetooth SPP.
    if args.port:
        return bosewin.connect(port=args.port, device_type=args.device)
    return bosewin.connect_auto(port=args.port, device_type=args.device)


def run(args):
    with _connect(args) as dev:
        cmd = args.command

        if cmd in (None, "status"):
            _print_status(dev)

        elif cmd == "battery":
            print("%d%%" % dev.battery())

        elif cmd == "firmware":
            print(dev.firmware())

        elif cmd == "eq":
            if args.values is None:
                for b in dev.eq():
                    print("%-6s %+d  (%d..%d)" % (b.name, b.current, b.min_val, b.max_val))
            else:
                bass, mid, treble = args.values
                dev.set_eq(bass=bass, mid=mid, treble=treble)
                print("EQ set: Bass %+d  Mid %+d  Treble %+d" % (bass, mid, treble))
                for b in dev.eq():
                    print("  now %-6s %+d" % (b.name, b.current))

        elif cmd == "cnc":
            if args.set is None:
                cur, mx = dev.cnc()
                print("Noise %d/%d (app scale; %d = max cancellation)"
                      % (mx - cur, mx, mx))
            else:
                if not 0 <= args.set <= 10:
                    print("noise level must be 0-10 (10 = max cancellation)",
                          file=sys.stderr)
                    return 2
                # CLI/app scale is inverted vs the raw device byte.
                dev.set_cnc(10 - args.set)
                cur, mx = dev.cnc()
                print("Noise set -> %d/%d (app scale; %d = max cancellation)"
                      % (mx - cur, mx, mx))

        elif cmd == "modes":
            current = dev.mode_idx()
            for idx, mc in sorted(dev.modes().items()):
                disp = _mode_disp(dev, idx, mc)
                tag = " *" if idx == current else "  "
                kind = "preset" if not mc.editable else ("empty" if not mc.configured and (not mc.name or mc.name == "None") else "custom")
                print("%s[%d] %-16s %-6s noise=%d spatial=%s anc=%s"
                      % (tag, idx, disp, kind, 10 - mc.cnc_level,
                         {0:"off",1:"still",2:"motion"}.get(mc.spatial, mc.spatial),
                         "on" if mc.anc_toggle else "off"))

        elif cmd == "mode":
            if args.name is None:
                idx = dev.mode_idx()
                print(_mode_disp(dev, idx, dev.modes().get(idx)))
            else:
                target = args.name.strip().lower()
                # Resolve by preset name, custom display/prompt name, or index.
                idx = None
                if target.isdigit():
                    idx = int(target)
                else:
                    for i, mc in dev.modes().items():
                        if _mode_disp(dev, i, mc).lower() == target:
                            idx = i
                            break
                if idx is None:
                    # Fall back to library name resolution (presets).
                    try:
                        dev.set_mode(args.name)
                    except BmapError:
                        print("unknown mode: %s" % args.name, file=sys.stderr)
                        return 2
                else:
                    dev.set_mode_idx(idx)
                cur = dev.mode_idx()
                print("Mode -> %s [%d]" % (_mode_disp(dev, cur, dev.modes().get(cur)), cur))

        elif cmd == "spatial":
            if args.value is None:
                mc = dev.modes().get(dev.mode_idx())
                v = mc.spatial if mc else None
                print({0:"off",1:"still",2:"motion"}.get(v, v))
            else:
                sval = {"off":0, "still":1, "room":1, "motion":2, "head":2}.get(args.value.lower())
                if sval is None:
                    print("spatial must be off/still/motion", file=sys.stderr)
                    return 2
                dev.set_spatial({0:"off",1:"room",2:"head"}[sval])
                print("Spatial set: %s" % args.value.lower())

        elif cmd == "wind":
            if args.state is None:
                mc = dev.modes().get(dev.mode_idx())
                print("on" if (mc and mc.wind_block) else "off")
            else:
                dev.set_wind(args.state)
                print("Wind block: %s" % ("on" if args.state else "off"))

        elif cmd == "anc":
            if args.state is None:
                mc = dev.modes().get(dev.mode_idx())
                print("on" if (mc and mc.anc_toggle) else "off")
            else:
                dev.set_anc(args.state)
                print("ANC: %s" % ("on" if args.state else "off"))

        elif cmd == "name":
            if args.new is None:
                print(dev.name())
            else:
                dev.set_name(args.new)
                print("Name set to: %s" % dev.name())

        elif cmd == "sidetone":
            if args.level is None:
                print(dev.sidetone())
            else:
                from pybmap.constants import SIDETONE_VALUES
                lvl = SIDETONE_VALUES.get(args.level.lower())
                if lvl is None:
                    print("level must be off/high/medium/low", file=sys.stderr)
                    return 2
                dev.set_sidetone(lvl)
                print("Sidetone set: %s" % dev.sidetone())

        elif cmd == "multipoint":
            if args.state is None:
                print("on" if dev.multipoint() else "off")
            else:
                dev.set_multipoint(args.state)
                print("Multipoint: %s" % ("on" if dev.multipoint() else "off"))

        elif cmd == "autopause":
            if args.state is None:
                print("on" if dev.auto_pause() else "off")
            else:
                dev.set_auto_pause(args.state)
                print("AutoPause: %s" % ("on" if dev.auto_pause() else "off"))

        elif cmd == "autoanswer":
            if args.state is None:
                print("on" if dev.auto_answer() else "off")
            else:
                dev.set_auto_answer(args.state)
                print("AutoAnswer: %s" % ("on" if dev.auto_answer() else "off"))

        elif cmd == "autooff":
            from pybmap.devices.parsers import AUTO_OFF_LABELS, AUTO_OFF_BY_LABEL
            if args.value is None:
                mins = dev.auto_off()
                print("%s (%d min)" % (AUTO_OFF_LABELS.get(mins, "%dmin" % mins), mins))
            else:
                v = args.value.strip().lower()
                if v in AUTO_OFF_BY_LABEL:
                    target = AUTO_OFF_BY_LABEL[v]
                elif v.isdigit():
                    target = int(v)
                else:
                    print("auto-off must be minutes or one of: %s"
                          % ", ".join(AUTO_OFF_BY_LABEL), file=sys.stderr)
                    return 2
                dev.set_auto_off(target)
                mins = dev.auto_off()
                print("AutoOff: %s (%d min)"
                      % (AUTO_OFF_LABELS.get(mins, "%dmin" % mins), mins))

        elif cmd == "buttons":
            b = dev.buttons()
            if getattr(args, "action", None) is None:
                print("%s %s -> %s" % (b.button_name, b.event_name, b.action_name))
                if b.supported_actions:
                    print("supported: %s" % ", ".join(b.supported_actions))
            else:
                from pybmap.devices.parsers import ACTION_BY_NAME
                if args.action.lower() not in ACTION_BY_NAME:
                    print("unknown action: %s\nvalid: %s"
                          % (args.action, ", ".join(sorted(
                              v for v in ACTION_BY_NAME))), file=sys.stderr)
                    return 2
                nb = dev.set_buttons(b.button_id, b.event, args.action)
                shown = nb.action_name if nb else args.action
                print("Shortcut %s -> %s" % (b.event_name, shown))

        elif cmd == "paired":
            try:
                conn = dev.connected_device()
            except Exception:
                conn = None
            try:
                lst = dev.paired_devices()
            except Exception:
                lst = []
            print("Connected: %s" % (conn or "unknown"))
            if lst:
                for m in lst:
                    tag = "  (connected)" if conn and m == conn else ""
                    print("  paired: %s%s" % (m, tag))
            else:
                print("  (no remembered devices reported)")

        elif cmd == "raw":
            # Read-only exploration helper: send a raw GET to fblock.func.
            fb, fn = args.addr
            data = dev._transport.send_recv(bmap_packet(fb, fn, OP_GET), drain=args.drain)
            for r in parse_all_responses(data):
                print(fmt_response(r))

        else:
            print("unknown command: %s" % cmd, file=sys.stderr)
            return 2
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="bosewin",
        description="Control Bose QC Ultra (1st gen) over Bluetooth SPP or USB-C on Windows.")
    p.add_argument("--port", help="COM port (default: auto-detect)")
    p.add_argument("--device", help="device config key (default: auto)")
    tg = p.add_mutually_exclusive_group()
    tg.add_argument("--usb", action="store_true",
        help="use the USB-C control channel (works during analog wired audio; no Bluetooth needed)")
    tg.add_argument("--bt", action="store_true",
        help="force the Bluetooth SPP channel (COM port)")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("status", help="show full device status (default)")
    sub.add_parser("battery", help="battery percentage")
    sub.add_parser("firmware", help="firmware version")
    sub.add_parser("ports", help="list discovered Bose SPP COM ports")
    pb = sub.add_parser("buttons", help="show or remap the shortcut-button action")
    pb.add_argument("action", nargs="?",
                    help="action name to bind (e.g. SpotifyGo, ANC, ConversationMode); omit to read")

    pe = sub.add_parser("eq", help="get or set 3-band EQ (-10..+10)")
    pe.add_argument("values", nargs="*", type=int, metavar="BASS MID TREBLE",
                    help="omit to read; give 3 ints to set")

    pc = sub.add_parser("cnc", help="read or set noise level (0-10, 10=max cancellation, app scale)")
    pc.add_argument("set", nargs="?", type=int, help="0-10; omit to read")

    sub.add_parser("modes", help="list noise modes / custom profiles")
    sub.add_parser("paired", help="show connected + remembered Bluetooth devices")

    pm = sub.add_parser("mode", help="show or switch current mode by name")
    pm.add_argument("name", nargs="?", help="mode name (quiet/aware/immersion/custom); omit to read")

    psp = sub.add_parser("spatial", help="Immersive Audio: off/still/motion")
    psp.add_argument("value", nargs="?")

    pn = sub.add_parser("name", help="get or set Bluetooth name")
    pn.add_argument("new", nargs="?", help="omit to read")

    ps = sub.add_parser("sidetone", help="get or set sidetone (off/high/medium/low)")
    ps.add_argument("level", nargs="?")

    pao = sub.add_parser("autooff",
        help="get or set auto-off timer (never/5min/20min/40min/1h/3h/24h or minutes)")
    pao.add_argument("value", nargs="?")

    for name in ("multipoint", "autopause", "autoanswer", "wind", "anc"):
        sp = sub.add_parser(name, help="get or set %s (on/off)" % name)
        sp.add_argument("state", nargs="?", type=_bool)

    pr = sub.add_parser("raw", help="send a raw GET to FBLOCK.FUNC (read-only)")
    pr.add_argument("addr", nargs=2, type=lambda x: int(x, 0), metavar="FBLOCK FUNC")
    pr.add_argument("--drain", action="store_true", help="drain multi-packet reply")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    # eq: normalize values (0 -> read, 3 -> set)
    if getattr(args, "command", None) == "eq":
        if not args.values:
            args.values = None
        elif len(args.values) != 3:
            print("eq set requires exactly 3 values: BASS MID TREBLE", file=sys.stderr)
            return 2
    try:
        if args.command == "ports":
            return cmd_ports(args)
        return run(args)
    except BmapNotFoundError as e:
        print("Not found: %s" % e, file=sys.stderr)
        return 3
    except BmapConnectionError as e:
        print("Connection error: %s" % e, file=sys.stderr)
        return 4
    except BmapError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
