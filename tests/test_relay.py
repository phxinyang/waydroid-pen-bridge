import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


RELAY_PATH = Path(__file__).resolve().parents[1] / "helper" / "waydroid-pen-relay.py"
SPEC = importlib.util.spec_from_file_location("waydroid_pen_relay", RELAY_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeProxy:
    def __init__(self):
        self.releases = 0
        self.writes = []
        self.closed = False

    def release(self):
        self.releases += 1

    def write(self, data):
        self.writes.append(data)

    def close(self):
        self.closed = True


def make_keyboard(codes):
    keyboard = MODULE.VirtualGestureKeyboard.__new__(
        MODULE.VirtualGestureKeyboard
    )
    keyboard.fd = -1
    keyboard.supported_codes = tuple(codes)
    keyboard.pressed = {code: False for code in codes}
    keyboard.pending = {}
    keyboard.writes = []
    keyboard.write = keyboard.writes.append
    return keyboard


def unpack_events(data):
    return [
        MODULE.INPUT_EVENT.unpack_from(data, offset)
        for offset in range(0, len(data), MODULE.INPUT_EVENT.size)
    ]


def event_values(writes):
    return [
        event[2:]
        for data in writes
        for event in unpack_events(data)
        if event[2] != MODULE.EV_SYN
    ]


def pen_frame(*key_events):
    events = [
        MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_X, 15240),
        MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_Y, 10160),
    ]
    events.extend(
        MODULE.make_event(MODULE.EV_KEY, code, value)
        for code, value in key_events
    )
    events.append(MODULE.make_event(MODULE.EV_SYN, MODULE.SYN_REPORT, 0))
    return b"".join(events)


def gesture_frame(code, value):
    return b"".join(
        (
            MODULE.make_event(MODULE.EV_KEY, code, value),
            MODULE.make_event(MODULE.EV_SYN, MODULE.SYN_REPORT, 0),
        )
    )


def create_sysfs_event(
    root,
    event_name,
    *,
    name,
    bustype,
    vendor,
    product,
    phys="",
):
    device = root / event_name / "device"
    (device / "id").mkdir(parents=True)
    (device / "name").write_text(name + "\n", encoding="utf-8")
    (device / "phys").write_text(phys + "\n", encoding="utf-8")
    (device / "id" / "bustype").write_text(
        f"{bustype:04x}\n", encoding="utf-8"
    )
    (device / "id" / "vendor").write_text(
        f"{vendor:04x}\n", encoding="utf-8"
    )
    (device / "id" / "product").write_text(
        f"{product:04x}\n", encoding="utf-8"
    )


class RelayTests(unittest.TestCase):
    def make_relay(self, state_path):
        relay = MODULE.PenRelay.__new__(MODULE.PenRelay)
        relay.config = {"STATE_PATH": str(state_path)}
        relay.mode = "desktop"
        relay.device = Path("/dev/input/event4")
        relay.device_fd = None
        relay.input_buffer = bytearray()
        relay.gesture_device = None
        relay.gesture_device_fd = None
        relay.gesture_input_buffer = bytearray()
        relay.pro_available = False
        relay.android_pro_active = False
        relay.capability_generation = 1
        relay.instance_id = "test-relay-instance"
        relay.proxy = FakeProxy()
        relay.android_proxy = FakeProxy()
        relay.android_mapper = MODULE.AndroidFrameMapper(
            relay.android_proxy, output_y_min=600
        )
        relay.gesture_proxy = make_keyboard(MODULE.DESKTOP_GESTURE_KEYS)
        relay.android_gesture_proxy = make_keyboard(
            MODULE.ANDROID_GESTURE_KEYS
        )
        return relay

    def test_source_discovery_requires_exact_virtual_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sys"
            dev = Path(directory) / "dev"
            create_sysfs_event(
                root,
                "event2",
                name="NVTCapacitivePenM80p",
                bustype=MODULE.BUS_USB,
                vendor=MODULE.VENDOR_ID,
                product=MODULE.PRODUCT_ID,
                phys="waydroid-pen-relay",
            )
            create_sysfs_event(
                root,
                "event7",
                name="NVTCapacitivePenM80p",
                bustype=MODULE.BUS_VIRTUAL,
                vendor=MODULE.VENDOR_ID,
                product=MODULE.PRODUCT_ID,
            )
            node = MODULE.find_source_event(
                "NVTCapacitivePenM80p",
                MODULE.PRODUCT_ID,
                "",
                {"waydroid-pen-relay", "waydroid-pen-android"},
                root,
                dev,
            )
        self.assertEqual(node, dev / "event7")

    def test_source_discovery_rejects_ambiguous_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sys"
            for event_name in ("event6", "event9"):
                create_sysfs_event(
                    root,
                    event_name,
                    name="Xiaomi Focus Pen Gestures",
                    bustype=MODULE.BUS_VIRTUAL,
                    vendor=MODULE.VENDOR_ID,
                    product=MODULE.GESTURE_PRODUCT_ID,
                )
            with self.assertRaisesRegex(MODULE.RelayError, "ambiguous"):
                MODULE.find_source_event(
                    "Xiaomi Focus Pen Gestures",
                    MODULE.GESTURE_PRODUCT_ID,
                    "",
                    set(),
                    root,
                    Path(directory) / "dev",
                )

    def test_missing_optional_gesture_source_keeps_ordinary_pen_state(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.config.update(
                {
                    "GESTURE_DEVICE_NAME": "Xiaomi Focus Pen Gestures",
                    "GESTURE_DEVICE_PHYS": "",
                    "GESTURE_PROXY_PHYS": "waydroid-gesture-relay",
                    "ANDROID_GESTURE_PROXY_PHYS": "waydroid-gesture-android",
                }
            )
            with mock.patch.object(MODULE, "find_source_event", return_value=None):
                relay._open_gesture_device()
        self.assertFalse(relay.pro_available)
        self.assertIsNone(relay.gesture_device)

    def test_ordinary_direct_preserves_standard_stylus_buttons(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_direct_mode(relay.capability_generation, False)
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 1)))

        pen_values = event_values(relay.android_proxy.writes)
        self.assertIn((MODULE.EV_KEY, MODULE.BTN_STYLUS, 1), pen_values)
        self.assertEqual(relay.android_gesture_proxy.writes, [])

    def test_pro_desktop_keeps_standard_buttons_and_slide_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            button_data = pen_frame((MODULE.BTN_STYLUS, 1))
            relay.forward(button_data)
            relay.forward_gesture(gesture_frame(MODULE.KEY_PROG3, 1))

        self.assertEqual(relay.proxy.writes, [button_data])
        self.assertEqual(
            event_values(relay.gesture_proxy.writes),
            [(MODULE.EV_KEY, MODULE.KEY_PROG3, 1)],
        )
        self.assertEqual(relay.android_gesture_proxy.writes, [])

    def test_pro_direct_filters_pen_buttons_and_emits_194_195_sources_once(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            relay.forward(
                pen_frame(
                    (MODULE.BTN_STYLUS, 1),
                    (MODULE.BTN_STYLUS2, 1),
                )
            )
            relay.forward(
                pen_frame(
                    (MODULE.BTN_STYLUS, 2),
                    (MODULE.BTN_STYLUS2, 1),
                )
            )

        pen_values = event_values(relay.android_proxy.writes)
        self.assertNotIn((MODULE.EV_KEY, MODULE.BTN_STYLUS, 1), pen_values)
        self.assertNotIn((MODULE.EV_KEY, MODULE.BTN_STYLUS2, 1), pen_values)
        self.assertEqual(
            event_values(relay.android_gesture_proxy.writes),
            [
                (MODULE.EV_KEY, MODULE.KEY_PROG1, 1),
                (MODULE.EV_KEY, MODULE.KEY_PROG2, 1),
            ],
        )

    def test_dynamic_pro_capability_waits_for_explicit_android_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_direct_mode(relay.capability_generation, False)
            relay._set_pro_available(True)
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 1)))

            self.assertFalse(relay.android_pro_active)
            self.assertIn(
                (MODULE.EV_KEY, MODULE.BTN_STYLUS, 1),
                event_values(relay.android_proxy.writes),
            )
            self.assertEqual(relay.android_gesture_proxy.writes, [])

            relay.activate_android_pro(relay.capability_generation)
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 0)))
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 1)))
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 0)))

        self.assertTrue(relay.android_pro_active)
        self.assertEqual(
            event_values(relay.android_gesture_proxy.writes),
            [
                (MODULE.EV_KEY, MODULE.KEY_PROG1, 1),
                (MODULE.EV_KEY, MODULE.KEY_PROG1, 0),
            ],
        )

    def test_pro_slides_remain_key_prog3_4_without_legacy_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            for code in (MODULE.KEY_PROG3, MODULE.KEY_PROG4):
                relay.forward_gesture(gesture_frame(code, 1))
                relay.forward_gesture(gesture_frame(code, 0))

        values = event_values(relay.android_gesture_proxy.writes)
        self.assertEqual(
            [value[1] for value in values],
            [
                MODULE.KEY_PROG3,
                MODULE.KEY_PROG3,
                MODULE.KEY_PROG4,
                MODULE.KEY_PROG4,
            ],
        )
        self.assertNotIn(73, [value[1] for value in values])
        self.assertNotIn(81, [value[1] for value in values])

    def test_mode_switch_releases_all_android_gesture_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            for code in MODULE.ANDROID_GESTURE_KEYS:
                relay.android_gesture_proxy.set_key(code, True)
            write_count = len(relay.android_gesture_proxy.writes)
            relay.set_desktop_mode()

        release_values = event_values(
            relay.android_gesture_proxy.writes[write_count:]
        )
        self.assertEqual(
            set(release_values),
            {
                (MODULE.EV_KEY, code, 0)
                for code in MODULE.ANDROID_GESTURE_KEYS
            },
        )

    def test_pro_disconnect_releases_keys_and_increments_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            generation = relay.capability_generation
            relay.android_gesture_proxy.set_key(MODULE.KEY_PROG1, True)
            relay.android_gesture_proxy.set_key(MODULE.KEY_PROG4, True)
            relay.android_mapper.keys[MODULE.BTN_STYLUS] = 1
            relay.android_mapper.keys[MODULE.BTN_STYLUS2] = 1
            relay.android_mapper.events.append(
                MODULE.INPUT_EVENT.unpack(
                    MODULE.make_event(MODULE.EV_KEY, MODULE.BTN_STYLUS, 1)
                )
            )
            write_count = len(relay.android_gesture_proxy.writes)
            relay._set_pro_available(False)
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertEqual(relay.capability_generation, generation + 1)
        self.assertFalse(state["pro_available"])
        self.assertFalse(state["android_pro_active"])
        self.assertIsNone(state["gesture_device"])
        self.assertEqual(relay.android_mapper.keys[MODULE.BTN_STYLUS], 0)
        self.assertEqual(relay.android_mapper.keys[MODULE.BTN_STYLUS2], 0)
        self.assertEqual(relay.android_mapper.events, [])
        self.assertEqual(
            set(event_values(relay.android_gesture_proxy.writes[write_count:])),
            {
                (MODULE.EV_KEY, MODULE.KEY_PROG1, 0),
                (MODULE.EV_KEY, MODULE.KEY_PROG4, 0),
            },
        )

    def test_gesture_keyboard_suppresses_repeat_and_duplicate_events(self):
        keyboard = make_keyboard(MODULE.ANDROID_GESTURE_KEYS)
        keyboard.feed(
            b"".join(
                (
                    gesture_frame(MODULE.KEY_PROG1, 1),
                    gesture_frame(MODULE.KEY_PROG1, 2),
                    gesture_frame(MODULE.KEY_PROG1, 1),
                    gesture_frame(MODULE.KEY_PROG1, 0),
                )
            ),
            {MODULE.KEY_PROG1: MODULE.KEY_PROG1},
            "test",
        )
        self.assertEqual(
            event_values(keyboard.writes),
            [
                (MODULE.EV_KEY, MODULE.KEY_PROG1, 1),
                (MODULE.EV_KEY, MODULE.KEY_PROG1, 0),
            ],
        )

    def test_missing_release_is_repaired_on_keyboard_release(self):
        keyboard = make_keyboard(MODULE.ANDROID_GESTURE_KEYS)
        keyboard.set_key(MODULE.KEY_PROG2, True)
        keyboard.release()
        self.assertEqual(
            event_values(keyboard.writes),
            [
                (MODULE.EV_KEY, MODULE.KEY_PROG2, 1),
                (MODULE.EV_KEY, MODULE.KEY_PROG2, 0),
            ],
        )

    def test_pen_source_disconnect_releases_synthetic_android_buttons(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 1)))
            write_count = len(relay.android_gesture_proxy.writes)
            relay._close_device()

        self.assertEqual(
            event_values(relay.android_gesture_proxy.writes[write_count:]),
            [(MODULE.EV_KEY, MODULE.KEY_PROG1, 0)],
        )
        self.assertIsNone(relay.android_mapper.axes[MODULE.ABS_X])
        self.assertEqual(relay.android_mapper.keys[MODULE.BTN_STYLUS], 0)

    def test_service_exit_closes_keyboard_after_releasing_pressed_keys(self):
        keyboard = make_keyboard(MODULE.ANDROID_GESTURE_KEYS)
        keyboard.fd = 17
        keyboard.set_key(MODULE.KEY_PROG3, True)
        with (
            mock.patch.object(MODULE.fcntl, "ioctl"),
            mock.patch.object(MODULE.os, "close") as close,
        ):
            keyboard.close()
        self.assertEqual(
            event_values(keyboard.writes)[-1],
            (MODULE.EV_KEY, MODULE.KEY_PROG3, 0),
        )
        close.assert_called_once_with(17)

    def test_atomic_state_is_world_readable_and_contains_capability_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay._write_state()
            state_path = Path(directory) / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            mode = stat.S_IMODE(state_path.stat().st_mode)
            directory_mode = stat.S_IMODE(state_path.parent.stat().st_mode)
        self.assertEqual(mode, 0o644)
        self.assertEqual(directory_mode, 0o755)
        self.assertIn("pro_available", state)
        self.assertIn("capability_generation", state)
        self.assertIn("gesture_device", state)
        self.assertEqual(state["instance_id"], "test-relay-instance")

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
        values = {
            (event[2], event[3]): event[4]
            for event in unpack_events(output.writes[0])
        }
        self.assertAlmostEqual(
            values[(MODULE.EV_ABS, MODULE.ABS_X)], 15240, delta=1
        )
        self.assertAlmostEqual(
            values[(MODULE.EV_ABS, MODULE.ABS_Y)], 10460, delta=1
        )
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
        mapper.feed(pen_frame(), True)
        mapper.set_geometry((0.1, 0.1, 0.8, 0.8))
        self.assertEqual(output.releases, 1)

    def test_mapper_rejects_non_finite_geometry(self):
        mapper = MODULE.AndroidFrameMapper(FakeProxy(), output_y_min=600)
        with self.assertRaises(MODULE.RelayError):
            mapper.set_geometry((float("nan"), 0.0, 1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
