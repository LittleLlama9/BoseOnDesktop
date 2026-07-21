"""BMAP-over-USB HID transport for Bose QC Ultra gen-1 (Milestone 4).

The gen-1 exposes a vendor HID interface (usage page 0xFF00) over its USB-C
port that speaks the same BMAP protocol as the Bluetooth SPP channel. Framing
matches the iclemens NC700 findings:

    send:    HID output report id 0x0c, then [len_be16][bmap...] zero-padded
    receive: HID input report id 0x0d, then [bmap...]

This class exposes the same send_recv(packet, drain) interface as
SerialTransport, so pybmap.BmapConnection and the whole protocol/parser/CLI/GUI
layer are reused verbatim over USB.
"""

import struct
import time

import hid

from pybmap.errors import BmapConnectionError, BmapTimeoutError

VID, PID = 0x05A7, 0x4066
OUT_REPORT_ID = 0x0c
IN_REPORT_ID = 0x0d
OUT_LEN = 1023   # report-id byte + 1022 payload (OutputReportByteLength)
IN_LEN = 676     # InputReportByteLength; covers the largest input report + id


def find_bose_usb():
    """Return the hidapi device path for the Bose vendor HID interface, or None."""
    for d in hid.enumerate(VID, PID):
        if d.get("usage_page", 0) == 0xFF00:
            return d["path"]
    devs = hid.enumerate(VID, PID)
    return devs[0]["path"] if devs else None


class HidTransport:
    """BMAP transport over the Bose USB-C vendor HID interface.

    Usage:
        with HidTransport() as t:
            resp = t.send_recv(packet_bytes)
    """

    def __init__(self, path=None, timeout=3.0):
        self.path = path
        self.timeout = timeout
        self._dev = None

    def connect(self):
        path = self.path or find_bose_usb()
        if not path:
            raise BmapConnectionError(
                "No Bose USB HID device (VID 05A7 PID 4066) found. "
                "Plug the headphones into this PC directly over USB-C."
            )
        self.path = path
        try:
            self._dev = hid.device()
            self._dev.open_path(path)
        except Exception as e:
            self._dev = None
            raise BmapConnectionError("Failed to open Bose USB HID: %s" % e) from e

    def close(self):
        if self._dev:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

    def _frame(self, packet):
        body = bytes([OUT_REPORT_ID]) + struct.pack(">H", len(packet)) + packet
        if len(body) > OUT_LEN:
            raise BmapConnectionError("BMAP packet too large for USB report")
        return body + b"\x00" * (OUT_LEN - len(body))

    def send_recv(self, packet, drain=False):
        """Send a BMAP packet, return the concatenated BMAP response bytes.

        Strips the HID report-id and the report's zero padding so the caller
        sees clean BMAP bytes identical to the serial transport's output.
        """
        if not self._dev:
            raise BmapConnectionError("Not connected")
        try:
            self._dev.write(self._frame(packet))
        except Exception as e:
            raise BmapConnectionError("USB write error: %s" % e) from e

        data = b""
        deadline = time.time() + self.timeout
        gap = 0.4 if drain else 0.2
        last_rx = time.time()
        while time.time() < deadline:
            try:
                rep = self._dev.read(IN_LEN, timeout_ms=200)
            except Exception as e:
                raise BmapConnectionError("USB read error: %s" % e) from e
            if rep and rep[0] == IN_REPORT_ID:
                data += _strip_padding(bytes(rep[1:]))
                last_rx = time.time()
                if not drain:
                    break
            elif data and (time.time() - last_rx) >= gap:
                break
        if not data:
            raise BmapTimeoutError("No response from Bose USB HID device")
        return data

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()


def _strip_padding(buf):
    """Trim a 0x0d input report's trailing zero padding to the real BMAP bytes.

    Walks the concatenated BMAP packets by their length field; stops at the
    first byte that isn't a valid packet header (i.e. the zero padding)."""
    out = bytearray()
    pos = 0
    n = len(buf)
    while pos + 4 <= n:
        fb, fn, op, ln = buf[pos], buf[pos + 1], buf[pos + 2], buf[pos + 3]
        # Zero padding starts here (a real packet never has fb==fn==op==0).
        if fb == 0 and fn == 0 and (op & 0x0f) == 0 and ln == 0:
            break
        if pos + 4 + ln > n:
            break
        out += buf[pos:pos + 4 + ln]
        pos += 4 + ln
    return bytes(out)
