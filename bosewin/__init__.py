"""bosewin -- Windows control for Bose BMAP headphones over SPP.

Reuses the pybmap protocol/parser/connection layer unchanged; supplies a
Windows pyserial transport and COM-port auto-discovery.

    import bosewin
    with bosewin.connect() as dev:
        print(dev.battery())
        print(dev.eq())
"""

from pybmap.connection import BmapConnection
from pybmap.devices import get_device
from pybmap.errors import BmapNotFoundError

from .serial_transport import SerialTransport
from .win_discovery import find_bose_port, find_bose_ports

__all__ = [
    "connect", "connect_usb", "connect_auto", "SerialTransport",
    "find_bose_port", "find_bose_ports",
]


def _wrap(transport, device):
    """Run a device's optional INIT_PACKET and wrap in a BmapConnection."""
    transport.connect()
    init = getattr(device, "INIT_PACKET", None)
    if init:
        from pybmap.protocol import bmap_packet
        fblock, func = init
        transport.send_recv(bmap_packet(fblock, func, 1))
    return BmapConnection(transport, device)


def connect(port=None, device_type=None):
    """Connect to a Bose BMAP device over its Windows SPP COM port.

    Args:
        port: COM port string (e.g. "COM3"). Auto-detected if None.
        device_type: pybmap device config key. Auto-detected from the port's
                     product ID if None; falls back to "qc_ultra1".

    Returns:
        A connected BmapConnection (context manager).

    Raises:
        BmapNotFoundError: If no Bose SPP port is found.
        BmapConnectionError: If the port cannot be opened.
    """
    if port is None:
        bp = find_bose_port()
        if bp is None:
            raise BmapNotFoundError(
                "No Bose SPP COM port found. Pair the headphones and add an "
                "outgoing COM port for the device's Serial Port service, or "
                "pass port= explicitly."
            )
        port = bp.port
        if device_type is None:
            device_type = bp.device_type

    if device_type is None:
        device_type = "qc_ultra1"

    device = get_device(device_type)
    transport = SerialTransport(port)
    return _wrap(transport, device)


def connect_usb(path=None, device_type=None):
    """Connect over the Bose USB-C vendor HID interface (Milestone 4).

    Works while the headphones are wired for analog audio (aux suspends
    Bluetooth, but the USB HID control channel is independent) and needs no
    Bluetooth pairing. Requires a USB-C *data* cable to the PC.

    Args:
        path: hidapi device path. Auto-detected if None.
        device_type: pybmap device config key. Defaults to "qc_ultra1"
                     (the only BMAP-over-USB device confirmed on this PC).

    Returns:
        A connected BmapConnection (context manager).

    Raises:
        BmapNotFoundError: If no Bose USB HID interface is found.
        BmapConnectionError: If the HID interface cannot be opened.
    """
    from .hid_transport import HidTransport, find_bose_usb

    if path is None:
        path = find_bose_usb()
        if path is None:
            raise BmapNotFoundError(
                "No Bose USB HID device (VID 05A7 PID 4066) found. Connect the "
                "headphones to this PC with a USB-C data cable."
            )
    if device_type is None:
        device_type = "qc_ultra1"

    device = get_device(device_type)
    transport = HidTransport(path)
    return _wrap(transport, device)


def connect_auto(port=None, device_type=None):
    """Connect over USB HID if present, otherwise fall back to Bluetooth SPP."""
    try:
        from .hid_transport import find_bose_usb
        if find_bose_usb() is not None:
            return connect_usb(device_type=device_type)
    except Exception:
        pass
    return connect(port=port, device_type=device_type)
