import importlib.util
from pathlib import Path
import tempfile
import unittest


RELAY_PATH = Path(__file__).resolve().parents[1] / "helper" / "waydroid-pen-relay.py"
SPEC = importlib.util.spec_from_file_location("waydroid_pen_relay", RELAY_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeProxy:
    def __init__(self):
        self.releases = 0
        self.writes = []

    def release(self):
        self.releases += 1

    def write(self, data):
        self.writes.append(data)


class RelayTests(unittest.TestCase):
    def make_relay(self, state_path):
        relay = MODULE.PenRelay.__new__(MODULE.PenRelay)
        relay.config = {"STATE_PATH": str(state_path)}
        relay.mode = "desktop"
        relay.device = Path("/dev/input/event4")
        relay.proxy = FakeProxy()
        return relay

    def test_direct_mode_releases_proxy_and_suppresses_physical_events(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_mode("direct")
            relay.forward(b"pen-events")
        self.assertEqual(relay.proxy.releases, 1)
        self.assertEqual(relay.proxy.writes, [])

    def test_desktop_mode_forwards_without_recreating_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            proxy = relay.proxy
            relay.set_mode("direct")
            relay.set_mode("desktop")
            relay.forward(b"pen-events")
        self.assertIs(relay.proxy, proxy)
        self.assertEqual(relay.proxy.writes, [b"pen-events"])

    def test_proxy_axes_include_tablet_resolution(self):
        x_axis = MODULE.UINPUT_ABS_SETUP.unpack(
            MODULE.make_abs_setup(MODULE.ABS_X, 0, 30479, 113)
        )
        y_axis = MODULE.UINPUT_ABS_SETUP.unpack(
            MODULE.make_abs_setup(MODULE.ABS_Y, 0, 20319, 113)
        )
        self.assertEqual(x_axis[-1], 113)
        self.assertEqual(y_axis[-1], 113)


if __name__ == "__main__":
    unittest.main()
