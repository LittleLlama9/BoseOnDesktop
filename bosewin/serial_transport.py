"""Windows SPP serial transport for BMAP devices.

Drop-in replacement for pybmap.transport.RfcommTransport. Same send_recv
interface, so pybmap.connection.BmapConnection and the whole protocol/parser
layer are reused verbatim -- only the physical transport changes.

On Windows, a paired BMAP device exposes an outgoing SPP virtual COM port
bound to its RFCOMM channel. We talk to that COM port with pyserial; the
Bluetooth stack carries the bytes over RFCOMM exactly as a raw AF_BLUETOOTH
socket would on Linux.
"""

import time

import serial

from pybmap.errors import BmapConnectionError, BmapTimeoutError


class SerialTransport:
    """BMAP transport over a Windows SPP virtual COM port.

    Usage:
        with SerialTransport("COM3") as t:
            resp = t.send_recv(packet_bytes)
    """

    def __init__(self, port, timeout=3.0, settle=0.25):
        self.port = port
        self.timeout = timeout
        self.settle = settle
        self._ser = None

    def connect(self):
        """Open the COM port, establishing the RFCOMM SPP link."""
        try:
            self._ser = serial.Serial(
                self.port, baudrate=115200, timeout=0.3, write_timeout=self.timeout
            )
        except serial.SerialException as e:
            self._ser = None
            msg = str(e)
            if "semaphore" in msg.lower() or "121" in msg:
                raise BmapConnectionError(
                    "Could not open %s. The headphones are paired but not "
                    "connected to this PC. Power them on and connect them to "
                    "this PC over Bluetooth, then retry." % self.port
                ) from e
            raise BmapConnectionError(
                "Failed to open %s: %s" % (self.port, e)
            ) from e

    def close(self):
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def send_recv(self, packet, drain=False):
        """Send a BMAP packet and receive the response bytes.

        Args:
            packet: Raw bytes to send.
            drain: If True, keep reading until the stream goes quiet
                   (for commands that return multiple STATUS packets).

        Returns:
            Raw response bytes (possibly several concatenated BMAP packets).

        Raises:
            BmapTimeoutError: If no response arrives.
        """
        if not self._ser:
            raise BmapConnectionError("Not connected")
        try:
            self._ser.reset_input_buffer()
            self._ser.write(packet)
            self._ser.flush()
        except serial.SerialException as e:
            raise BmapConnectionError("Write error: %s" % e) from e

        time.sleep(self.settle)
        data = b""
        # Quiet-gap draining: read until no new bytes for `gap` seconds, bounded
        # by the overall timeout. Works for both single- and multi-packet replies.
        gap = 0.5 if drain else 0.3
        deadline = time.time() + self.timeout
        last_rx = time.time()
        while time.time() < deadline:
            try:
                chunk = self._ser.read(4096)
            except serial.SerialException as e:
                raise BmapConnectionError("Read error: %s" % e) from e
            if chunk:
                data += chunk
                last_rx = time.time()
            else:
                if data and (time.time() - last_rx) >= gap:
                    break
                if not data:
                    time.sleep(0.03)
        if not data:
            raise BmapTimeoutError("No response from device on %s" % self.port)
        return data

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
