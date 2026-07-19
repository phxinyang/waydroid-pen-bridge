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


class FakeMapper:
    def __init__(self):
        self.geometry = None
        self.releases = 0
        self.feeds = []

    def release(self):
        self.releases += 1

    def feed(self, data, enabled):
        self.feeds.append((data, enabled))

    def set_geometry(self, geometry):
        self.geometry = geometry


class RelayTests(unittest.TestCase):
    def make_relay(self, state_path):
        relay = MODULE.PenRelay.__new__(MODULE.PenRelay)
        relay.config = {"STATE_PATH": str(state_path)}
        relay.mode = "desktop"
        relay.device = Path("/dev/input/event4")
        relay.proxy = FakeProxy()
        relay.android_mapper = FakeMapper()
        return relay

    def test_direct_mode_releases_proxy_and_suppresses_physical_events(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_mode("direct")
            relay.forward(b"pen-events")
        self.assertEqual(relay.proxy.releases, 1)
        self.assertEqual(relay.proxy.writes, [])
        self.assertEqual(relay.android_mapper.feeds, [(b"pen-events", True)])

    def test_desktop_mode_forwards_without_recreating_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            proxy = relay.proxy
            relay.set_mode("direct")
            relay.set_mode("desktop")
            relay.forward(b"pen-events")
        self.assertIs(relay.proxy, proxy)
        self.assertEqual(relay.proxy.writes, [b"pen-events"])
        self.assertEqual(relay.android_mapper.releases, 1)
        self.assertEqual(relay.android_mapper.feeds[-1], (b"pen-events", False))

    def test_proxy_axes_include_tablet_resolution(self):
        x_axis = MODULE.UINPUT_ABS_SETUP.unpack(
            MODULE.make_abs_setup(MODULE.ABS_X, 0, 30479, 113)
        )
        y_axis = MODULE.UINPUT_ABS_SETUP.unpack(
            MODULE.make_abs_setup(MODULE.ABS_Y, 0, 20319, 113)
        )
        self.assertEqual(x_axis[-1], 113)
        self.assertEqual(y_axis[-1], 113)

    def test_window_mapping_expands_content_rect_to_android_axes(self):
        output = FakeProxy()
        mapper = MODULE.AndroidFrameMapper(output, output_y_min=600)
        mapper.set_geometry((0.25, 0.25, 0.5, 0.5))
        mapper.feed(
            b"".join(
                (
                    MODULE.make_event(MODULE.EV_KEY, MODULE.BTN_TOOL_PEN, 1),
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_X, 15240),
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_Y, 10160),
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_PRESSURE, 8000),
                    MODULE.make_event(MODULE.EV_SYN, MODULE.SYN_REPORT, 0),
                )
            ),
            True,
        )
        events = [
            MODULE.INPUT_EVENT.unpack_from(output.writes[0], offset)
            for offset in range(0, len(output.writes[0]), MODULE.INPUT_EVENT.size)
        ]
        values = {(event[2], event[3]): event[4] for event in events}
        self.assertAlmostEqual(values[(MODULE.EV_ABS, MODULE.ABS_X)], 15240, delta=1)
        self.assertAlmostEqual(values[(MODULE.EV_ABS, MODULE.ABS_Y)], 10460, delta=1)
        self.assertEqual(values[(MODULE.EV_ABS, MODULE.ABS_PRESSURE)], 8000)

    def test_maximized_window_does_not_apply_top_bar_offset_twice(self):
        mapper = MODULE.AndroidFrameMapper(FakeProxy(), output_y_min=600)
        logical_height = 1016
        window_top = 30
        window_height = 986
        mapper.set_geometry(
            (
                0.0,
                window_top / logical_height,
                1.0,
                window_height / logical_height,
            )
        )
        pen_y = 508
        raw_y = round(pen_y / logical_height * mapper.Y_MAX)
        _, android_y = mapper._map_point(mapper.X_MAX // 2, raw_y)
        android_position = (
            (android_y - mapper.output_y_min)
            / (mapper.Y_MAX - mapper.output_y_min)
        )
        rendered_y = window_top + android_position * window_height
        self.assertAlmostEqual(rendered_y, pen_y, delta=0.1)

    def test_window_mapping_suppresses_pen_outside_and_releases_on_exit(self):
        output = FakeProxy()
        mapper = MODULE.AndroidFrameMapper(output, output_y_min=600)
        mapper.set_geometry((0.25, 0.25, 0.5, 0.5))

        def frame(x, y):
            return b"".join(
                (
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_X, x),
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_Y, y),
                    MODULE.make_event(MODULE.EV_SYN, MODULE.SYN_REPORT, 0),
                )
            )

        mapper.feed(frame(1000, 1000), True)
        self.assertEqual(output.writes, [])
        mapper.feed(frame(15240, 10460), True)
        self.assertEqual(len(output.writes), 1)
        mapper.feed(frame(1000, 1000), True)
        self.assertEqual(output.releases, 1)

    def test_mapping_change_releases_active_android_pen(self):
        output = FakeProxy()
        mapper = MODULE.AndroidFrameMapper(output, output_y_min=600)
        mapper.feed(
            b"".join(
                (
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_X, 15240),
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_Y, 10460),
                    MODULE.make_event(MODULE.EV_SYN, MODULE.SYN_REPORT, 0),
                )
            ),
            True,
        )
        mapper.set_geometry((0.1, 0.1, 0.8, 0.8))
        self.assertEqual(output.releases, 1)

    def test_mapper_rejects_non_finite_geometry(self):
        mapper = MODULE.AndroidFrameMapper(FakeProxy(), output_y_min=600)
        with self.assertRaises(MODULE.RelayError):
            mapper.set_geometry((float("nan"), 0.0, 1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
