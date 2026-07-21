"""RFCOMM Bluetooth socket transport for BMAP devices."""

import socket
import time

from .errors import BmapConnectionError, BmapTimeoutError

RFCOMM_CHANNEL = 2  # BMAP protocol is always on RFCOMM channel 2


class RfcommTransport:
    """Raw RFCOMM Bluetooth socket transport.

    Manages the Bluetooth socket lifecycle and provides send/receive
    with optional multi-packet draining for async responses.

    Usage:
        with RfcommTransport("68:F2:1F:XX:XX:XX") as transport:
            resp = transport.send_recv(packet_bytes)
    """

    def __init__(self, mac, channel=RFCOMM_CHANNEL, timeout=3.0):
        self.mac = mac
        self.channel = channel
        self.timeout = timeout
        self._sock = None

    def connect(self):
        """Open the RFCOMM socket to the device."""
        try:
            self._sock = socket.socket(
                socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
            )
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.mac, self.channel))
        except (OSError, socket.error) as e:
            self._sock = None
            raise BmapConnectionError(
                "Failed to connect to %s: %s" % (self.mac, e)
            ) from e

    def close(self):
        """Close the socket."""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def send_recv(self, packet, drain=False):
        """Send a BMAP packet and receive the response.

        Args:
            packet: Raw bytes to send.
            drain: If True, keep reading until the socket times out.
                   Needed for commands that return multiple STATUS
                   messages (e.g., GetAll).

        Returns:
            Raw response bytes (may contain multiple concatenated packets
            if drain=True).

        Raises:
            BmapTimeoutError: If no response is received.
        """
        if not self._sock:
            raise BmapConnectionError("Not connected")
        try:
            self._sock.send(packet)
            time.sleep(0.2)
            data = self._sock.recv(4096)
        except socket.timeout:
            raise BmapTimeoutError("No response from device")
        except OSError as e:
            raise BmapConnectionError("Communication error: %s" % e) from e

        if drain:
            self._sock.settimeout(0.5)
            try:
                while True:
                    more = self._sock.recv(4096)
                    if not more:
                        break
                    data += more
            except (socket.timeout, BlockingIOError):
                pass
            self._sock.settimeout(self.timeout)

        return data

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
