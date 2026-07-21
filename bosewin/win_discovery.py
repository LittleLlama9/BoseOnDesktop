"""Discover the Bose device's outgoing SPP COM port on Windows.

A paired BMAP device exposes an *outgoing* SPP virtual COM port whose PnP
hardware ID carries the Bose Bluetooth VID (0x009E) and the device MAC. The
matching *incoming* server port carries LOCALMFG instead and must be skipped.
"""

import re

from serial.tools import list_ports

from pybmap.catalog import lookup_device

BOSE_BT_VID = 0x009E


class BosePort:
    def __init__(self, port, product_id, mac, device_type, name):
        self.port = port
        self.product_id = product_id
        self.mac = mac
        self.device_type = device_type
        self.name = name

    def __repr__(self):
        return "BosePort(%s, %s, pid=0x%04x, %s)" % (
            self.port, self.mac, self.product_id, self.device_type
        )


def _parse_hwid(hwid):
    """Extract (product_id, mac) from an outgoing SPP hardware ID.

    Example outgoing hwid:
      BTHENUM\\{00001101-...}_VID&0001009E_PID&4066\\9&..&0&BC87FA98DDBA_C00...
    The trailing 12-hex group is the device MAC. Incoming server ports use
    LOCALMFG&0000 with an all-zero MAC and are rejected.
    """
    up = hwid.upper()
    if "BTHENUM" not in up or "LOCALMFG" in up:
        return None
    vid_m = re.search(r"VID&0001([0-9A-F]{4})", up)
    pid_m = re.search(r"PID&([0-9A-F]{4})", up)
    mac_m = re.search(r"&([0-9A-F]{12})_", up)
    if not (vid_m and pid_m and mac_m):
        return None
    vid = int(vid_m.group(1), 16)
    if vid != BOSE_BT_VID:
        return None
    pid = int(pid_m.group(1), 16)
    raw_mac = mac_m.group(1)
    if raw_mac == "000000000000":
        return None
    mac = ":".join(raw_mac[i:i + 2] for i in range(0, 12, 2))
    return pid, mac


def find_bose_ports():
    """Return a list of BosePort for every outgoing Bose SPP COM port."""
    found = []
    for p in list_ports.comports():
        hwid = p.hwid or ""
        parsed = _parse_hwid(hwid)
        if not parsed:
            continue
        pid, mac = parsed
        entry = lookup_device(pid)
        device_type = entry.config if entry else None
        name = entry.name if entry else "Unknown Bose device"
        found.append(BosePort(p.device, pid, mac, device_type, name))
    return found


def find_bose_port():
    """Return the first supported Bose outgoing SPP port, or None."""
    ports = find_bose_ports()
    for bp in ports:
        if bp.device_type:
            return bp
    return ports[0] if ports else None
