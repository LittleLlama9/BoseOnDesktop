"""Integration tests — require a paired Bluetooth device.

Run with: pytest --integration
Or:       BMAP_INTEGRATION=1 pytest

Set BMAP_DEVICE to select device type (default: qc_ultra2).
Set BMAP_MAC to specify a MAC address (otherwise auto-detected).
"""

import os
import pytest

import pybmap
from pybmap.errors import BmapError

# Skip all tests in this module unless integration mode is enabled.
pytestmark = pytest.mark.integration


def _skip_unless_integration():
    if not os.environ.get("BMAP_INTEGRATION"):
        pytest.skip("Integration tests disabled (set BMAP_INTEGRATION=1)")


@pytest.fixture(scope="module")
def dev():
    _skip_unless_integration()
    mac = os.environ.get("BMAP_MAC")
    device_type = os.environ.get("BMAP_DEVICE", "qc_ultra2")
    try:
        conn = pybmap.connect(mac=mac, device_type=device_type)
    except BmapError as e:
        pytest.skip("Cannot connect: %s" % e)
    yield conn
    conn.close()


class TestRead:
    """Read-only tests — safe to run anytime."""

    def test_battery(self, dev):
        batt = dev.battery()
        assert isinstance(batt, int)
        assert 0 <= batt <= 100

    def test_firmware(self, dev):
        fw = dev.firmware()
        assert isinstance(fw, str)
        assert len(fw) > 0

    def test_name(self, dev):
        name = dev.name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_mode(self, dev):
        mode = dev.mode()
        assert isinstance(mode, str)

    def test_mode_idx(self, dev):
        idx = dev.mode_idx()
        assert isinstance(idx, int)
        assert 0 <= idx <= 10

    def test_cnc(self, dev):
        current, maximum = dev.cnc()
        assert isinstance(current, int)
        assert isinstance(maximum, int)
        assert 0 <= current <= maximum

    def test_eq(self, dev):
        bands = dev.eq()
        assert isinstance(bands, list)
        assert len(bands) > 0
        for b in bands:
            assert -10 <= b.current <= 10

    def test_sidetone(self, dev):
        st = dev.sidetone()
        assert isinstance(st, str)

    def test_multipoint(self, dev):
        mp = dev.multipoint()
        assert isinstance(mp, bool)

    def test_auto_pause(self, dev):
        ap = dev.auto_pause()
        assert isinstance(ap, bool)

    def test_prompts(self, dev):
        enabled, lang = dev.prompts()
        assert isinstance(enabled, bool)
        assert isinstance(lang, str)

    def test_buttons(self, dev):
        btn = dev.buttons()
        assert btn is not None
        assert btn.button_name is not None

    def test_modes(self, dev):
        modes = dev.modes()
        assert isinstance(modes, dict)
        assert len(modes) > 0
        # Should have at least the preset modes
        assert 0 in modes  # quiet
        assert 1 in modes  # aware

    def test_status(self, dev):
        s = dev.status()
        assert 0 <= s.battery <= 100
        assert isinstance(s.mode, str)
        assert isinstance(s.firmware, str)

    def test_has_feature(self, dev):
        assert dev.has_feature("battery")
        assert dev.has_feature("cnc")
        assert not dev.has_feature("nonexistent_feature")

    def test_device_info(self, dev):
        info = dev.device_info
        assert "name" in info


class TestWrite:
    """Write tests — these change device state! They attempt to restore it."""

    def test_set_cnc_roundtrip(self, dev):
        """Set CNC, verify, restore."""
        original, _ = dev.cnc()
        dev.set_cnc(5)
        current, _ = dev.cnc()
        # Restore
        try:
            dev.set_cnc(original)
        except BmapError:
            pass
        assert current == 5

    def test_set_eq_roundtrip(self, dev):
        """Set EQ, verify, restore."""
        original = dev.eq()
        dev.set_eq(2, -1, 3)
        bands = dev.eq()
        # Restore
        try:
            dev.set_eq(original[0].current, original[1].current, original[2].current)
        except BmapError:
            pass
        assert bands[0].current == 2
        assert bands[1].current == -1
        assert bands[2].current == 3
