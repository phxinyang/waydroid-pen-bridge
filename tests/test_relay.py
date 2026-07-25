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
    def __init__(self, profile=None):
        self.releases = 0
        self.writes = []
        self.closed = False
        self.profile = profile
        self.key_codes = None
        self.axis_codes = None

    def release(self):
        self.releases += 1

    def write(self, data):
        self.writes.append(data)

    def write_buttons(self, states):
        self.writes.append(
            b"".join(
                MODULE.make_event(MODULE.EV_KEY, code, int(bool(states.get(code, False))))
                for code in MODULE.ORDINARY_BUTTON_CODES
            )
            + MODULE.make_event(MODULE.EV_SYN, MODULE.SYN_REPORT, 0)
        )

    def release_buttons(self):
        self.releases += 1

    def snapshot(self, keys, axes, x, y):
        events = []
        key_codes = self.key_codes or (
            MODULE.BTN_TOOL_PEN,
            MODULE.BTN_TOUCH,
            MODULE.BTN_STYLUS,
            MODULE.BTN_STYLUS2,
        )
        for code in key_codes:
            events.append(
                MODULE.make_event(MODULE.EV_KEY, code, int(bool(keys.get(code, 0))))
            )
        for code, value in (
            (MODULE.ABS_X, x),
            (MODULE.ABS_Y, y),
            (MODULE.ABS_PRESSURE, axes.get(MODULE.ABS_PRESSURE, 0) or 0),
        ):
            events.append(MODULE.make_event(MODULE.EV_ABS, code, value))
        events.append(MODULE.make_event(MODULE.EV_SYN, MODULE.SYN_REPORT, 0))
        return b"".join(events)

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
        relay.config = dict(MODULE.DEFAULTS)
        relay.config["STATE_PATH"] = str(state_path)
        relay.config["LINK_STATE_PATH"] = str(
            state_path.with_name("link-state.json")
        )
        relay.mode = "desktop"
        relay.active_model = MODULE.MODEL_M80P
        relay.sources = {
            model: {
                "node": Path(f"/dev/input/{model}"),
                "fd": None,
                "buffer": bytearray(),
                "y_min": 0,
                "y_max": MODULE.PEN_Y_MAX,
                "pressure_min": 0,
                "pressure_max": MODULE.PEN_PROFILES[model]["pressure_max"],
            }
            for model in MODULE.PEN_MODELS
        }
        relay.device = Path("/dev/input/event4")
        relay.device_fd = None
        relay.input_buffer = bytearray()
        relay.gesture_device = None
        relay.gesture_device_fd = None
        relay.gesture_input_buffer = bytearray()
        relay.ordinary_button_state = {
            code: False for code in MODULE.ORDINARY_BUTTON_CODES
        }
        relay.ordinary_button_route = "desktop-pen"
        relay.pro_gesture_state = {
            code: False for code in MODULE.PRO_GESTURE_CODES
        }
        relay.pro_available = False
        relay.waydroid_focused = False
        relay.android_pro_active = False
        relay.android_button_active = False
        relay.capability_generation = 1
        relay.instance_id = "test-relay-instance"
        relay.proxy = FakeProxy()
        relay.proxies = {
            MODULE.MODEL_M80P: relay.proxy,
            MODULE.MODEL_P81C: FakeProxy(),
        }
        relay.android_proxies = {
            MODULE.MODEL_M80P: FakeProxy(),
            MODULE.MODEL_P81C: FakeProxy(),
        }
        relay.android_proxy = relay.android_proxies[MODULE.MODEL_M80P]
        relay.proxy.key_codes = [
            MODULE.BTN_TOOL_PEN,
            MODULE.BTN_TOUCH,
            *MODULE.ORDINARY_BUTTON_CODES,
        ]
        relay.proxy.axis_codes = [
            MODULE.ABS_X,
            MODULE.ABS_Y,
            MODULE.ABS_PRESSURE,
        ]
        relay.proxies[MODULE.MODEL_P81C].key_codes = [
            MODULE.BTN_TOOL_PEN,
            MODULE.BTN_TOUCH,
            MODULE.KEY_WAKEUP,
            MODULE.BTN_TRIGGER,
        ]
        relay.proxies[MODULE.MODEL_P81C].axis_codes = [
            MODULE.ABS_X,
            MODULE.ABS_Y,
            MODULE.ABS_PRESSURE,
            MODULE.ABS_BRAKE,
            MODULE.ABS_DISTANCE,
            MODULE.ABS_TILT_X,
            MODULE.ABS_TILT_Y,
        ]
        for proxy, model in (
            (relay.android_proxies[MODULE.MODEL_M80P], MODULE.MODEL_M80P),
            (relay.android_proxies[MODULE.MODEL_P81C], MODULE.MODEL_P81C),
        ):
            proxy.key_codes = list(relay.proxies[model].key_codes)
            proxy.axis_codes = list(relay.proxies[model].axis_codes)
        relay.mappers = {
            model: MODULE.AndroidFrameMapper(
                relay.android_proxies[model],
                source_y_min=0,
                source_y_max=MODULE.PEN_Y_MAX,
                pressure_max=MODULE.PEN_PROFILES[model]["pressure_max"],
            )
            for model in MODULE.PEN_MODELS
        }
        relay.proxy_m80p = relay.proxies[MODULE.MODEL_M80P]
        relay.proxy_p81c = relay.proxies[MODULE.MODEL_P81C]
        relay.android_button_proxy = make_keyboard(MODULE.ANDROID_BUTTON_KEYS)
        relay.android_mapper = relay.mappers[MODULE.MODEL_M80P]
        relay.gesture_proxy = make_keyboard(MODULE.DESKTOP_GESTURE_KEYS)
        relay.android_gesture_proxy = make_keyboard(
            MODULE.ANDROID_GESTURE_KEYS
        )
        return relay

    def make_pro_relay(self, state_path):
        relay = self.make_relay(state_path)
        relay._activate_model(MODULE.MODEL_P81C)
        return relay
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
                phys="input/pen",
            )
            node = MODULE.find_source_event(
                "NVTCapacitivePenM80p",
                MODULE.PRODUCT_ID,
                "input/pen",
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
                    name="Xiaomi Focus Pen Pro Gestures",
                    bustype=MODULE.BUS_VIRTUAL,
                    vendor=MODULE.PRO_GESTURE_VENDOR_ID,
                    product=MODULE.PRO_GESTURE_PRODUCT_ID,
                    phys="input/pen_p81c/gestures",
                )
            with self.assertRaisesRegex(MODULE.RelayError, "ambiguous"):
                MODULE.find_source_event(
                    "Xiaomi Focus Pen Pro Gestures",
                    MODULE.PRO_GESTURE_PRODUCT_ID,
                    "input/pen_p81c/gestures",
                    set(),
                    root,
                    Path(directory) / "dev",
                    vendor_id=MODULE.PRO_GESTURE_VENDOR_ID,
                )

    def test_parallel_pen_nodes_select_model_from_gesture_capability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sys"
            dev = Path(directory) / "dev"
            create_sysfs_event(
                root,
                "event4",
                name="NVTCapacitivePenM80p",
                bustype=MODULE.BUS_VIRTUAL,
                vendor=MODULE.VENDOR_ID,
                product=MODULE.PRODUCT_ID,
                phys="input/pen",
            )
            create_sysfs_event(
                root,
                "event5",
                name="NVTCapacitivePenP81c",
                bustype=MODULE.BUS_VIRTUAL,
                vendor=MODULE.VENDOR_ID,
                product=MODULE.PRODUCT_ID,
                phys="input/pen_p81c",
            )
            config = dict(MODULE.DEFAULTS)
            ordinary = MODULE.find_pen_source(config, False, root, dev)
            pro = MODULE.find_pen_source(config, True, root, dev)

        self.assertEqual(ordinary, dev / "event4")
        self.assertEqual(pro, dev / "event5")

    def test_reconcile_keeps_both_pen_sources_open_and_gestures_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            ordinary = Path("/dev/input/event4")
            pro = Path("/dev/input/event5")
            gestures = Path("/dev/input/event13")

            def discovered(_config):
                return {MODULE.MODEL_M80P: ordinary, MODULE.MODEL_P81C: pro}

            def open_source(model, node):
                relay.sources[model]["node"] = node
                relay.sources[model]["fd"] = 99 + (0 if model == MODULE.MODEL_M80P else 1)

            def close_source(model):
                relay.sources[model]["node"] = None
                relay.sources[model]["fd"] = None

            with (
                mock.patch.object(MODULE, "find_pen_sources", side_effect=discovered),
                mock.patch.object(MODULE, "find_gesture_source", return_value=gestures),
                mock.patch.object(relay, "_open_source", side_effect=open_source),
                mock.patch.object(relay, "_close_source", side_effect=close_source),
                mock.patch.object(relay, "_open_gesture_device") as open_gesture,
            ):
                relay._reconcile_sources()
                self.assertEqual(relay.sources[MODULE.MODEL_M80P]["node"], ordinary)
                self.assertEqual(relay.sources[MODULE.MODEL_P81C]["node"], pro)
                open_gesture.assert_called_once_with(gestures)

            with (
                mock.patch.object(MODULE, "find_pen_sources", side_effect=discovered),
                mock.patch.object(MODULE, "find_gesture_source", return_value=None),
                mock.patch.object(relay, "_close_gesture_device") as close_gesture,
            ):
                relay.gesture_device = gestures
                relay._reconcile_sources()
                close_gesture.assert_called_once_with()

        self.assertEqual(relay.active_model, MODULE.MODEL_M80P)
        self.assertEqual(relay.sources[MODULE.MODEL_M80P]["node"], ordinary)
        self.assertEqual(relay.sources[MODULE.MODEL_P81C]["node"], pro)

    def test_missing_optional_gesture_source_keeps_ordinary_pen_state(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.config.update(
                {
                    "GESTURE_DEVICE_NAME": "Xiaomi Focus Pen Pro Gestures",
                    "GESTURE_DEVICE_PHYS": "input/pen_p81c/gestures",
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
            relay.set_waydroid_focus(True)
            relay.set_direct_mode(relay.capability_generation, False)
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 1)))

        pen_values = event_values(relay.android_proxy.writes)
        self.assertIn((MODULE.EV_KEY, MODULE.BTN_STYLUS, 1), pen_values)
        self.assertEqual(relay.proxies[MODULE.MODEL_M80P].writes, [])
        self.assertEqual(relay.android_gesture_proxy.writes, [])

    def test_ordinary_desktop_unfocused_keeps_buttons_on_desktop_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 1)))

        self.assertIn(
            (MODULE.EV_KEY, MODULE.BTN_STYLUS, 1),
            event_values(relay.proxy.writes),
        )
        self.assertEqual(
            relay.android_proxies[MODULE.MODEL_M80P].writes, []
        )
        self.assertEqual(relay.android_gesture_proxy.writes, [])

    def test_ordinary_desktop_focus_routes_buttons_only_to_android(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_waydroid_focus(True)
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 1)))

        self.assertNotIn(
            (MODULE.EV_KEY, MODULE.BTN_STYLUS, 1),
            event_values(relay.proxy.writes),
        )
        self.assertIn(
            (MODULE.EV_KEY, MODULE.BTN_STYLUS, 1),
            event_values(relay.android_button_proxy.writes),
        )

    def test_ordinary_focus_loss_releases_android_button(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_waydroid_focus(True)
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 1)))
            write_count = len(relay.android_button_proxy.writes)
            relay.set_waydroid_focus(False)

        self.assertEqual(
            event_values(relay.android_button_proxy.writes[write_count:]),
            [(MODULE.EV_KEY, MODULE.BTN_STYLUS, 0)],
        )

    def test_ordinary_direct_unfocused_filters_buttons(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_direct_mode(relay.capability_generation, False)
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 1)))

        self.assertNotIn(
            (MODULE.EV_KEY, MODULE.BTN_STYLUS, 1),
            event_values(relay.android_proxy.writes),
        )

    def test_ordinary_direct_focus_uses_pen_proxy_only(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_waydroid_focus(True)
            relay.set_direct_mode(relay.capability_generation, False)
            relay.forward(pen_frame((MODULE.BTN_STYLUS, 1)))

        self.assertIn(
            (MODULE.EV_KEY, MODULE.BTN_STYLUS, 1),
            event_values(relay.android_proxy.writes),
        )
        self.assertEqual(relay.proxies[MODULE.MODEL_M80P].writes, [])
        self.assertEqual(relay.android_gesture_proxy.writes, [])

    def test_direct_pen_frames_are_isolated_from_desktop_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_waydroid_focus(True)
            relay.set_direct_mode(relay.capability_generation, False)
            relay.forward(pen_frame())

        self.assertGreater(len(relay.android_proxies[MODULE.MODEL_M80P].writes), 0)
        self.assertEqual(relay.proxies[MODULE.MODEL_M80P].writes, [])

    def test_desktop_pen_frames_are_isolated_from_android_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.forward(pen_frame())

        self.assertGreater(len(relay.proxies[MODULE.MODEL_M80P].writes), 0)
        self.assertEqual(relay.android_proxies[MODULE.MODEL_M80P].writes, [])

    def test_direct_full_display_mapping_is_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_waydroid_focus(True)
            relay.set_direct_mode(relay.capability_generation, False)
            relay.set_mapping((0.0, 0.0, 1.0, 1.0))
            frame = b"".join(
                (
                    MODULE.make_event(MODULE.EV_KEY, MODULE.BTN_TOOL_PEN, 1),
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_X, 12345),
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_Y, 6789),
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_PRESSURE, 4321),
                    MODULE.make_event(MODULE.EV_SYN, MODULE.SYN_REPORT, 0),
                )
            )
            relay.forward(frame)

        values = event_values(relay.android_proxies[MODULE.MODEL_M80P].writes)
        self.assertIn((MODULE.EV_ABS, MODULE.ABS_X, 12345), values)
        self.assertIn((MODULE.EV_ABS, MODULE.ABS_Y, 6789), values)
        self.assertIn((MODULE.EV_ABS, MODULE.ABS_PRESSURE, 4321), values)

    def test_mode_switch_releases_opposite_pen_proxies(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_waydroid_focus(True)
            relay.set_direct_mode(relay.capability_generation, False)
            relay.forward(pen_frame((MODULE.BTN_TOOL_PEN, 1)))
            desktop_releases = relay.proxies[MODULE.MODEL_M80P].releases
            android_releases = relay.android_proxies[MODULE.MODEL_M80P].releases
            relay.set_desktop_mode()
            after_desktop = relay.android_proxies[MODULE.MODEL_M80P].releases
            relay.set_direct_mode(relay.capability_generation, False)
            after_direct = relay.proxies[MODULE.MODEL_M80P].releases

        self.assertGreater(after_desktop, android_releases)
        self.assertGreater(after_direct, desktop_releases)

    def test_pressure_ranges_remain_native_per_pen_model(self):
        ordinary = MODULE.transform_pen_events(
            b"".join(
                (
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_PRESSURE, 8191),
                    MODULE.make_event(MODULE.EV_SYN, MODULE.SYN_REPORT, 0),
                )
            ),
            ordinary=True,
        )
        pro = MODULE.transform_pen_events(
            b"".join(
                (
                    MODULE.make_event(MODULE.EV_ABS, MODULE.ABS_PRESSURE, 8191),
                    MODULE.make_event(MODULE.EV_SYN, MODULE.SYN_REPORT, 0),
                )
            ),
            ordinary=False,
        )
        self.assertEqual(unpack_events(ordinary)[0][4], 8191)
        self.assertEqual(unpack_events(pro)[0][4], 8191)
        self.assertNotIn("normalize_m80p_pressure", dir(MODULE))

    def test_model_proxies_are_resident_and_switch_releases_only_old_state(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            m80p_proxy = relay.proxies[MODULE.MODEL_M80P]
            p81c_proxy = relay.proxies[MODULE.MODEL_P81C]
            relay.sources[MODULE.MODEL_P81C]["y_min"] = 600
            relay.sources[MODULE.MODEL_P81C]["y_max"] = 20319

            relay._activate_model(MODULE.MODEL_P81C)
            relay.forward(
                MODULE.MODEL_M80P,
                pen_frame((MODULE.BTN_TOOL_PEN, 1)),
            )
            inactive_writes = len(m80p_proxy.writes)
            relay.forward(
                MODULE.MODEL_P81C,
                pen_frame((MODULE.BTN_TOOL_PEN, 1)),
            )

        self.assertIs(relay.proxies[MODULE.MODEL_M80P], m80p_proxy)
        self.assertIs(relay.proxies[MODULE.MODEL_P81C], p81c_proxy)
        self.assertFalse(m80p_proxy.closed)
        self.assertGreaterEqual(m80p_proxy.releases, 1)
        self.assertEqual(len(m80p_proxy.writes), inactive_writes)
        self.assertGreater(len(p81c_proxy.writes), 0)
        self.assertEqual(
            relay.sources[MODULE.MODEL_M80P]["pressure_max"],
            MODULE.M80P_PRESSURE_MAX,
        )
        self.assertEqual(
            relay.sources[MODULE.MODEL_P81C]["pressure_max"],
            MODULE.P81C_PRESSURE_MAX,
        )

    def test_pro_gesture_events_follow_active_p81c_only(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_waydroid_focus(True)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))
            self.assertEqual(relay.android_gesture_proxy.writes, [])

            relay._activate_model(MODULE.MODEL_P81C)
            relay.set_waydroid_focus(True)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))

        self.assertEqual(
            event_values(relay.android_gesture_proxy.writes),
            [(MODULE.EV_KEY, MODULE.BTN_6, 1)],
        )

    def test_pro_desktop_keeps_raw_buttons_off_android_without_focus(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.proxy.writes.clear()
            for code in (
                MODULE.BTN_6,
                MODULE.BTN_7,
                MODULE.BTN_8,
                MODULE.BTN_9,
            ):
                relay.forward_gesture(gesture_frame(code, 1))

        self.assertEqual(relay.proxy.writes, [])
        self.assertEqual(
            event_values(relay.gesture_proxy.writes),
            [
                (MODULE.EV_KEY, MODULE.BTN_6, 1),
                (MODULE.EV_KEY, MODULE.BTN_7, 1),
                (MODULE.EV_KEY, MODULE.BTN_8, 1),
                (MODULE.EV_KEY, MODULE.BTN_9, 1),
            ],
        )
        self.assertEqual(relay.android_gesture_proxy.writes, [])

    def test_pro_desktop_focus_routes_raw_buttons_only_to_android(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_waydroid_focus(True)
            for code in MODULE.PRO_GESTURE_CODES:
                relay.forward_gesture(gesture_frame(code, 1))

        expected = [
            (MODULE.EV_KEY, code, 1) for code in MODULE.PRO_GESTURE_CODES
        ]
        self.assertEqual(relay.gesture_proxy.writes, [])
        self.assertEqual(
            event_values(relay.android_gesture_proxy.writes), expected
        )
        self.assertTrue(relay.android_pro_active)

    def test_pro_direct_forwards_gestures_once_without_ordinary_buttons(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            relay.set_waydroid_focus(True)
            relay.forward(
                pen_frame(
                    (MODULE.BTN_STYLUS, 1),
                    (MODULE.BTN_STYLUS2, 1),
                )
            )
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))
            relay.forward_gesture(gesture_frame(MODULE.BTN_7, 1))
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))

        pen_values = event_values(relay.android_proxy.writes)
        self.assertNotIn((MODULE.EV_KEY, MODULE.BTN_STYLUS, 1), pen_values)
        self.assertNotIn((MODULE.EV_KEY, MODULE.BTN_STYLUS2, 1), pen_values)
        self.assertEqual(
            event_values(relay.android_gesture_proxy.writes),
            [
                (MODULE.EV_KEY, MODULE.BTN_6, 1),
                (MODULE.EV_KEY, MODULE.BTN_7, 1),
            ],
        )

    def test_dynamic_pro_capability_waits_for_explicit_android_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay.set_direct_mode(relay.capability_generation, False)
            relay.set_waydroid_focus(True)
            relay._set_pro_available(True)
            relay._activate_model(MODULE.MODEL_P81C)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))

            self.assertFalse(relay.android_pro_active)
            self.assertEqual(relay.android_gesture_proxy.writes, [])

            relay.activate_android_pro(relay.capability_generation)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 0))

        self.assertTrue(relay.android_pro_active)
        self.assertEqual(
            event_values(relay.android_gesture_proxy.writes),
            [
                (MODULE.EV_KEY, MODULE.BTN_6, 1),
                (MODULE.EV_KEY, MODULE.BTN_6, 0),
            ],
        )

    def test_pro_gestures_remain_raw_without_legacy_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            relay.set_waydroid_focus(True)
            for code in (MODULE.BTN_8, MODULE.BTN_9):
                relay.forward_gesture(gesture_frame(code, 1))
                relay.forward_gesture(gesture_frame(code, 0))

        values = event_values(relay.android_gesture_proxy.writes)
        self.assertEqual(
            [value[1] for value in values],
            [
                MODULE.BTN_8,
                MODULE.BTN_8,
                MODULE.BTN_9,
                MODULE.BTN_9,
            ],
        )
        for legacy_code in (73, 81, 148, 149, 202, 203):
            self.assertNotIn(legacy_code, [value[1] for value in values])

    def test_direct_to_desktop_keeps_focused_android_gesture_state(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            relay.set_waydroid_focus(True)
            for code in MODULE.ANDROID_GESTURE_KEYS:
                relay.android_gesture_proxy.set_key(code, True)
            write_count = len(relay.android_gesture_proxy.writes)
            relay.set_desktop_mode()

        self.assertEqual(relay.android_gesture_proxy.writes[write_count:], [])
        self.assertTrue(relay.android_pro_active)

    def test_desktop_focus_loss_releases_all_android_gesture_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_waydroid_focus(True)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))
            relay.forward_gesture(gesture_frame(MODULE.BTN_9, 1))
            write_count = len(relay.android_gesture_proxy.writes)
            relay.set_waydroid_focus(False)

        self.assertFalse(relay.android_pro_active)
        self.assertEqual(
            set(event_values(relay.android_gesture_proxy.writes[write_count:])),
            {
                (MODULE.EV_KEY, MODULE.BTN_6, 0),
                (MODULE.EV_KEY, MODULE.BTN_9, 0),
            },
        )

    def test_direct_focus_loss_also_releases_android_gesture_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            relay.set_waydroid_focus(True)
            relay.forward_gesture(gesture_frame(MODULE.BTN_7, 1))
            write_count = len(relay.android_gesture_proxy.writes)
            relay.set_waydroid_focus(False)

        self.assertFalse(relay.android_pro_active)
        self.assertEqual(
            event_values(relay.android_gesture_proxy.writes[write_count:]),
            [(MODULE.EV_KEY, MODULE.BTN_7, 0)],
        )

    def test_desktop_focus_gain_does_not_replay_held_button(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))
            relay.set_waydroid_focus(True)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 0))

        self.assertEqual(relay.android_gesture_proxy.writes, [])
        self.assertEqual(
            event_values(relay.gesture_proxy.writes),
            [
                (MODULE.EV_KEY, MODULE.BTN_6, 1),
                (MODULE.EV_KEY, MODULE.BTN_6, 0),
            ],
        )

    def test_pro_button_destination_follows_focus_without_duplication(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 0))
            relay.set_waydroid_focus(True)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 0))
            relay.set_waydroid_focus(False)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 0))

        self.assertEqual(
            event_values(relay.gesture_proxy.writes),
            [
                (MODULE.EV_KEY, MODULE.BTN_6, 1),
                (MODULE.EV_KEY, MODULE.BTN_6, 0),
            ] * 2,
        )
        self.assertEqual(
            event_values(relay.android_gesture_proxy.writes),
            [
                (MODULE.EV_KEY, MODULE.BTN_6, 1),
                (MODULE.EV_KEY, MODULE.BTN_6, 0),
            ],
        )

    def test_pro_disconnect_releases_keys_and_increments_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            relay.set_waydroid_focus(True)
            generation = relay.capability_generation
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))
            relay.forward_gesture(gesture_frame(MODULE.BTN_9, 1))
            android_gesture = relay.android_gesture_proxy
            write_count = len(android_gesture.writes)
            relay._set_pro_available(False)
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertEqual(relay.capability_generation, generation + 1)
        self.assertFalse(state["pro_available"])
        self.assertFalse(state["android_pro_active"])
        self.assertIsNone(state["gesture_device"])
        self.assertFalse(any(relay.pro_gesture_state.values()))
        self.assertEqual(
            set(event_values(android_gesture.writes[write_count:])),
            {
                (MODULE.EV_KEY, MODULE.BTN_6, 0),
                (MODULE.EV_KEY, MODULE.BTN_9, 0),
            },
        )

    def test_gesture_keyboard_suppresses_repeat_and_duplicate_events(self):
        keyboard = make_keyboard(MODULE.ANDROID_GESTURE_KEYS)
        keyboard.feed(
            b"".join(
                (
                    gesture_frame(MODULE.BTN_6, 1),
                    gesture_frame(MODULE.BTN_6, 2),
                    gesture_frame(MODULE.BTN_6, 1),
                    gesture_frame(MODULE.BTN_6, 0),
                )
            ),
            "test",
        )
        self.assertEqual(
            event_values(keyboard.writes),
            [
                (MODULE.EV_KEY, MODULE.BTN_6, 1),
                (MODULE.EV_KEY, MODULE.BTN_6, 0),
            ],
        )

    def test_missing_release_is_repaired_on_keyboard_release(self):
        keyboard = make_keyboard(MODULE.ANDROID_GESTURE_KEYS)
        keyboard.set_key(MODULE.BTN_7, True)
        keyboard.release()
        self.assertEqual(
            event_values(keyboard.writes),
            [
                (MODULE.EV_KEY, MODULE.BTN_7, 1),
                (MODULE.EV_KEY, MODULE.BTN_7, 0),
            ],
        )

    def test_pen_source_disconnect_releases_pro_gesture_state(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_pro_relay(Path(directory) / "state.json")
            relay._set_pro_available(True)
            relay.set_direct_mode(relay.capability_generation, True)
            relay.set_waydroid_focus(True)
            relay.forward_gesture(gesture_frame(MODULE.BTN_6, 1))
            write_count = len(relay.android_gesture_proxy.writes)
            relay._close_device()

        self.assertEqual(
            event_values(relay.android_gesture_proxy.writes[write_count:]),
            [(MODULE.EV_KEY, MODULE.BTN_6, 0)],
        )
        self.assertIsNone(relay.android_mapper.axes[MODULE.ABS_X])
        self.assertFalse(any(relay.pro_gesture_state.values()))

    def test_service_exit_closes_keyboard_after_releasing_pressed_keys(self):
        keyboard = make_keyboard(MODULE.ANDROID_GESTURE_KEYS)
        keyboard.fd = 17
        keyboard.set_key(MODULE.BTN_8, True)
        with (
            mock.patch.object(MODULE.fcntl, "ioctl"),
            mock.patch.object(MODULE.os, "close") as close,
        ):
            keyboard.close()
        self.assertEqual(
            event_values(keyboard.writes)[-1],
            (MODULE.EV_KEY, MODULE.BTN_8, 0),
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
        self.assertIn("waydroid_focused", state)
        self.assertIn("capability_generation", state)
        self.assertIn("gesture_device", state)
        self.assertEqual(state["instance_id"], "test-relay-instance")

    def test_link_state_contains_only_link_relevant_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            relay._write_link_state()
            link_state_path = Path(directory) / "link-state.json"
            link_state = json.loads(
                link_state_path.read_text(encoding="utf-8")
            )

        self.assertEqual(
            link_state,
            {
                "instance_id": "test-relay-instance",
                "capability_generation": 1,
                "pro_available": False,
            },
        )

    def test_runtime_state_updates_do_not_rewrite_link_state(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            with mock.patch.object(MODULE, "write_json_atomic") as write:
                relay._write_state()

        write.assert_called_once()
        self.assertEqual(
            write.call_args.args[0], Path(directory) / "state.json"
        )

    def test_capability_change_updates_runtime_and_link_state(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = self.make_relay(Path(directory) / "state.json")
            with mock.patch.object(MODULE, "write_json_atomic") as write:
                relay._set_pro_available(True)

        self.assertEqual(write.call_count, 2)
        self.assertEqual(
            [call.args[0].name for call in write.call_args_list],
            ["state.json", "link-state.json"],
        )

    def test_proxy_axes_include_tablet_resolution(self):
        x_axis = MODULE.UINPUT_ABS_SETUP.unpack(
            MODULE.make_abs_setup(MODULE.ABS_X, 0, 30479, 113)
        )
        y_axis = MODULE.UINPUT_ABS_SETUP.unpack(
            MODULE.make_abs_setup(MODULE.ABS_Y, 0, 20319, 113)
        )
        self.assertEqual(x_axis[-1], 113)
        self.assertEqual(y_axis[-1], 113)

    def test_proxy_axes_cover_pro_pressure_and_brake(self):
        specs = {
            code: (minimum, maximum, resolution)
            for code, minimum, maximum, resolution in MODULE.PEN_AXIS_SPECS
        }
        self.assertEqual(specs[MODULE.ABS_PRESSURE], (0, 16383, 0))
        self.assertEqual(specs[MODULE.ABS_BRAKE], (0, 360, 0))

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
