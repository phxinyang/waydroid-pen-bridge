import importlib.util
import io
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "helper" / "waydroid-pen-mode.py"
RELAY_PATH = ROOT / "helper" / "waydroid-pen-relay.py"
INSTALL_PATH = ROOT / "install.sh"
UNINSTALL_PATH = ROOT / "uninstall.sh"
RULE_PATH = ROOT / "config" / "99-waydroid-pen-mode.rules.in"
SERVICE_PATH = ROOT / "config" / "waydroid-pen-relay.service"
EXTENSION_PATH = ROOT / "extension" / "extension.js"
SESSION_PATH = ROOT / "helper" / "waydroid-pen-session.py"
LINK_PATH_UNIT = ROOT / "config" / "waydroid-pen-link-sync.path"
LINK_SERVICE_UNIT = ROOT / "config" / "waydroid-pen-link-sync.service"
USER_SESSION_UNIT = ROOT / "config" / "waydroid-pen-session@.service"
USER_REAPPLY_UNIT = ROOT / "config" / "waydroid-pen-session-reapply.service"
USER_REAPPLY_PATH = ROOT / "config" / "waydroid-pen-session.path"
KWIN_METADATA = ROOT / "kde" / "kwin" / "metadata.json"
KWIN_MAIN = ROOT / "kde" / "kwin" / "contents" / "ui" / "main.qml"
PLASMOID_METADATA = ROOT / "kde" / "plasmoid" / "metadata.json"
PLASMOID_MAIN = ROOT / "kde" / "plasmoid" / "contents" / "ui" / "main.qml"
GESTURE_KEYLAYOUT_PATH = ROOT / "android" / "Vendor_2717_Product_3655.kl"
GESTURE_KEYCHARS_PATH = ROOT / "android" / "Vendor_2717_Product_3655.kcm"
PEN_KEYLAYOUT_PATH = ROOT / "android" / "Vendor_2717_Product_3654.kl"
PEN_KEYCHARS_PATH = ROOT / "android" / "Vendor_2717_Product_3654.kcm"

SPEC = importlib.util.spec_from_file_location("waydroid_pen_mode", HELPER_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
RELAY_SPEC = importlib.util.spec_from_file_location(
    "waydroid_pen_relay", RELAY_PATH
)
RELAY = importlib.util.module_from_spec(RELAY_SPEC)
RELAY_SPEC.loader.exec_module(RELAY)


def result(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


class SwitchSafetyTests(unittest.TestCase):
    def test_android_mapping_is_unified_194_through_197(self):
        keylayout = GESTURE_KEYLAYOUT_PATH.read_text(encoding="utf-8")
        keychars = GESTURE_KEYCHARS_PATH.read_text(encoding="utf-8")
        keylayout_lines = [
            line for line in keylayout.splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(
            keylayout_lines,
            [
                "key 331   BUTTON_7",
                "key 332   BUTTON_8",
                "key 262   BUTTON_7",
                "key 263   BUTTON_8",
                "key 264   BUTTON_9",
                "key 265   BUTTON_10",
            ],
        )
        for button in range(7, 11):
            self.assertIn(f"key BUTTON_{button} {{", keychars)
        self.assertEqual(keychars.count("base: none"), 4)
        self.assertNotIn("STYLUS_BUTTON_PRIMARY", keylayout + keychars)
        self.assertNotIn("STYLUS_BUTTON_SECONDARY", keylayout + keychars)
        for legacy in (
            "NUMPAD",
            "PAGE_UP",
            "PAGE_DOWN",
            "key 73",
            "key 81",
            "key 148",
            "key 149",
            "key 202",
            "key 203",
        ):
            self.assertNotIn(legacy, keylayout + keychars)

        pen_keylayout = PEN_KEYLAYOUT_PATH.read_text(encoding="utf-8")
        pen_keychars = PEN_KEYCHARS_PATH.read_text(encoding="utf-8")
        self.assertIn("key 331   BUTTON_7", pen_keylayout)
        self.assertIn("key 332   BUTTON_8", pen_keylayout)
        self.assertEqual(pen_keychars.count("base: none"), 2)
        self.assertNotIn("STYLUS_BUTTON_PRIMARY", pen_keylayout + pen_keychars)
        self.assertNotIn("STYLUS_BUTTON_SECONDARY", pen_keylayout + pen_keychars)

    def test_relay_contains_no_legacy_slide_translation(self):
        relay = RELAY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("KEY_KP9", relay)
        self.assertNotIn("KEY_KP3", relay)
        self.assertNotIn("ANDROID_GESTURE_KEY_MAP", relay)
        self.assertNotIn("KEY_PROG", relay)

    def test_pro_y_axis_normalizes_for_desktop_and_direct(self):
        frame = b"".join(
            (
                RELAY.make_event(RELAY.EV_ABS, RELAY.ABS_Y, 600),
                RELAY.make_event(RELAY.EV_SYN, RELAY.SYN_REPORT, 0),
            )
        )
        desktop = RELAY.transform_pen_events(
            frame,
            ordinary=False,
            source_y_min=600,
            target_y_min=0,
        )
        desktop_y = RELAY.INPUT_EVENT.unpack_from(desktop)[4]
        self.assertEqual(desktop_y, 0)

        output = type(
            "Output",
            (),
            {"release": lambda self: None, "write": lambda self, data: None},
        )()
        mapper = RELAY.AndroidFrameMapper(
            output,
            output_y_min=600,
            source_y_min=600,
        )
        _, android_top = mapper._map_point(mapper.X_MAX // 2, 600)
        _, android_bottom = mapper._map_point(mapper.X_MAX // 2, 20319)
        self.assertEqual(android_top, 600)
        self.assertEqual(android_bottom, 20319)

    def test_ordinary_y_axis_stays_identity(self):
        frame = b"".join(
            (
                RELAY.make_event(RELAY.EV_ABS, RELAY.ABS_Y, 600),
                RELAY.make_event(RELAY.EV_SYN, RELAY.SYN_REPORT, 0),
            )
        )
        desktop = RELAY.transform_pen_events(
            frame,
            ordinary=True,
            source_y_min=0,
            target_y_min=0,
        )
        self.assertEqual(RELAY.INPUT_EVENT.unpack_from(desktop)[4], 600)

    def test_desktop_gesture_proxy_is_tagged_as_pointer_for_kwin(self):
        rules = RULE_PATH.read_text(encoding="utf-8")
        desktop_rule = next(
            line for line in rules.splitlines()
            if 'phys}=="waydroid-gesture-relay"' in line
        )
        self.assertIn('ENV{ID_INPUT_MOUSE}="1"', desktop_rule)

    def test_android_link_specs_keep_event4_and_event5_stable(self):
        links = MODULE.android_links(
            dict(MODULE.DEFAULTS),
            {
                "mode": "direct",
                "active_pen": "p81c",
                "pro_available": True,
                "android_button_active": False,
            },
        )
        self.assertEqual(links[0]["link"], "/dev/input/event4")
        self.assertEqual(links[0]["target"], "../waydroid_pen_p81c")
        self.assertEqual(links[1]["link"], "/dev/input/event5")
        self.assertEqual(links[1]["target"], "../waydroid_pen_gesture")

    def test_direct_links_fallback_when_active_pen_is_still_null(self):
        pro_links = MODULE.android_links(
            dict(MODULE.DEFAULTS),
            {
                "mode": "direct",
                "active_pen": None,
                "pro_available": True,
                "android_button_active": False,
            },
        )
        ordinary_links = MODULE.android_links(
            dict(MODULE.DEFAULTS),
            {
                "mode": "direct",
                "active_pen": None,
                "pro_available": False,
                "android_button_active": False,
            },
        )
        self.assertEqual(pro_links[0]["target"], "../waydroid_pen_p81c")
        self.assertEqual(pro_links[1]["target"], "../waydroid_pen_gesture")
        self.assertEqual(ordinary_links[0]["target"], "../waydroid_pen_m80p")
        self.assertIsNone(ordinary_links[1]["target"])

    def test_frozen_waydroid_container_remains_available(self):
        for state, expected in (
            ("RUNNING", True),
            ("FROZEN", True),
            ("STOPPED", False),
        ):
            with self.subTest(state=state):
                with mock.patch.object(
                    MODULE,
                    "run",
                    return_value=result(stdout=f"{state}\n"),
                ):
                    self.assertEqual(MODULE.waydroid_running(), expected)

    def test_commands_have_a_bounded_timeout(self):
        with mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=result(),
        ) as process:
            MODULE.run(["command"])
        self.assertEqual(
            process.call_args.kwargs["timeout"],
            MODULE.COMMAND_TIMEOUT_SECONDS,
        )

    def test_android_commands_bypass_waydroid_freeze_cycle(self):
        with mock.patch.object(MODULE, "run", return_value=result()) as run:
            MODULE.waydroid_shell("unlink", "/dev/input/event5")
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/lxc-attach")
        self.assertNotIn("/usr/bin/waydroid", command)
        self.assertEqual(command[-2:], ["unlink", "/dev/input/event5"])

    def test_frozen_container_is_thawed_only_for_android_command(self):
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            if command[0] == MODULE.LXC_INFO:
                return result(stdout="FROZEN\n")
            return result()

        with mock.patch.object(MODULE, "run", side_effect=fake_run):
            MODULE.waydroid_shell("readlink", "/dev/input/event4")

        self.assertEqual(calls[0][0], MODULE.LXC_INFO)
        self.assertEqual(calls[1][0], MODULE.LXC_UNFREEZE)
        self.assertEqual(calls[2][0], "/usr/bin/lxc-attach")
        self.assertEqual(calls[3][0], MODULE.LXC_FREEZE)

    def test_android_path_probe_ignores_waydroid_shell_exit_status(self):
        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE,
                "waydroid_shell",
                return_value=result(returncode=0, stdout="missing"),
            ),
        ):
            self.assertFalse(MODULE.android_path_exists("/dev/input/event4"))

    def test_android_path_probe_rejects_unknown_output(self):
        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE,
                "waydroid_shell",
                return_value=result(returncode=0, stdout=""),
            ),
        ):
            with self.assertRaisesRegex(MODULE.ModeError, "failed to inspect"):
                MODULE.android_path_exists("/dev/input/event4")

    def test_capability_snapshot_requires_typed_relay_state(self):
        with self.assertRaises(MODULE.ModeError):
            MODULE.capability_snapshot(
                {"capability_generation": "4", "pro_available": "false"}
            )

    def test_android_pro_routing_requires_typed_focus_state(self):
        relay = {
            "mode": "desktop",
            "capability_generation": 4,
            "pro_available": True,
            "waydroid_focused": "false",
        }
        with self.assertRaisesRegex(MODULE.ModeError, "focus state"):
            MODULE.android_pro_should_be_active(relay)

    def test_android_pro_routing_requires_typed_active_state(self):
        with self.assertRaisesRegex(MODULE.ModeError, "Android Pro state"):
            MODULE.android_pro_is_active({"android_pro_active": 1})

    def test_ordinary_direct_sync_creates_model_event4_only(self):
        commands = []

        def shell(*arguments, **_kwargs):
            commands.append(arguments)
            return result()

        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE, "inspect_android_link", return_value=("missing", None)
            ),
            mock.patch.object(MODULE, "waydroid_shell", side_effect=shell),
        ):
            MODULE.sync_android_links(
                dict(MODULE.DEFAULTS),
                {
                    "mode": "direct",
                    "active_pen": "m80p",
                    "pro_available": False,
                    "android_button_active": False,
                },
            )

        link_commands = [command for command in commands if command[0] == "ln"]
        self.assertEqual(
            link_commands,
            [
                ("ln", "-s", "../waydroid_pen_m80p", "/dev/input/event4"),
            ],
        )

    def test_pro_sync_creates_event4_and_event5(self):
        commands = []

        def shell(*arguments, **_kwargs):
            commands.append(arguments)
            return result()

        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE, "inspect_android_link", return_value=("missing", None)
            ),
            mock.patch.object(MODULE, "waydroid_shell", side_effect=shell),
        ):
            MODULE.sync_android_links(
                dict(MODULE.DEFAULTS),
                {
                    "mode": "direct",
                    "active_pen": "p81c",
                    "pro_available": True,
                    "android_button_active": False,
                },
            )

        link_commands = [command for command in commands if command[0] == "ln"]
        self.assertEqual(
            link_commands,
            [
                ("ln", "-s", "../waydroid_pen_p81c", "/dev/input/event4"),
                (
                    "ln",
                    "-s",
                    "../waydroid_pen_gesture",
                    "/dev/input/event5",
                ),
            ],
        )

    def test_pro_desktop_sync_creates_event5_only(self):
        commands = []

        def shell(*arguments, **_kwargs):
            commands.append(arguments)
            return result()

        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE, "inspect_android_link", return_value=("missing", None)
            ),
            mock.patch.object(MODULE, "waydroid_shell", side_effect=shell),
        ):
            MODULE.sync_android_links(
                dict(MODULE.DEFAULTS),
                {
                    "mode": "desktop",
                    "active_pen": "p81c",
                    "pro_available": True,
                    "android_button_active": False,
                },
            )

        link_commands = [command for command in commands if command[0] == "ln"]
        self.assertEqual(
            link_commands,
            [
                (
                    "ln",
                    "-s",
                    "../waydroid_pen_gesture",
                    "/dev/input/event5",
                )
            ],
        )

    def test_no_side_channel_removes_owned_event5(self):
        commands = []

        def shell(*arguments, **_kwargs):
            commands.append(arguments)
            return result()

        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE, "inspect_android_link", return_value=("owned", "target")
            ),
            mock.patch.object(MODULE, "waydroid_shell", side_effect=shell),
        ):
            MODULE.sync_android_links(
                dict(MODULE.DEFAULTS),
                {
                    "mode": "direct",
                    "active_pen": "m80p",
                    "pro_available": False,
                    "android_button_active": False,
                },
            )

        self.assertIn(("unlink", "/dev/input/event5"), commands)

    def test_foreign_event_link_is_rejected_before_mutation(self):
        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE,
                "inspect_android_link",
                return_value=("foreign", "../unrelated_device"),
            ),
            mock.patch.object(MODULE, "waydroid_shell") as shell,
        ):
            with self.assertRaisesRegex(MODULE.ModeError, "refusing to replace"):
                MODULE.sync_android_links(dict(MODULE.DEFAULTS), True, True)
        shell.assert_not_called()

    def test_unrequired_foreign_event4_does_not_block_desktop_event5(self):
        commands = []

        def inspect(spec):
            if spec["capability"] == "pen":
                return "foreign", "../unrelated_pen"
            return "missing", None

        def shell(*arguments, **_kwargs):
            commands.append(arguments)
            return result()

        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(MODULE, "inspect_android_link", side_effect=inspect),
            mock.patch.object(MODULE, "waydroid_shell", side_effect=shell),
        ):
            MODULE.sync_android_links(dict(MODULE.DEFAULTS), False, True)

        self.assertIn(
            (
                "ln",
                "-s",
                "../waydroid_pen_gesture",
                "/dev/input/event5",
            ),
            commands,
        )
        self.assertNotIn(("unlink", "/dev/input/event4"), commands)

    def test_partial_pro_link_creation_is_rolled_back(self):
        commands = []

        def shell(*arguments, **_kwargs):
            commands.append(arguments)
            if arguments[:3] == (
                "ln",
                "-s",
                "../waydroid_pen_gesture",
            ):
                raise subprocess.CalledProcessError(1, arguments)
            return result()

        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE, "inspect_android_link", return_value=("missing", None)
            ),
            mock.patch.object(MODULE, "waydroid_shell", side_effect=shell),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                MODULE.sync_android_links(dict(MODULE.DEFAULTS), True, True)

        self.assertIn(("unlink", "/dev/input/event4"), commands)

    def test_direct_failure_removes_owned_links_and_restores_desktop(self):
        relay_commands = []

        def relay(_config, command):
            relay_commands.append(command)
            return {
                "ok": True,
                "mode": "desktop",
                "pro_available": True,
                "capability_generation": 7,
            }

        with (
            mock.patch.object(MODULE, "relay_command", side_effect=relay),
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE, "sync_android_links", side_effect=MODULE.ModeError("failed")
            ),
            mock.patch.object(MODULE, "remove_owned_android_links") as remove,
            mock.patch.object(MODULE.sys, "stderr", new=io.StringIO()),
        ):
            with self.assertRaises(MODULE.ModeError):
                MODULE.direct_mode(dict(MODULE.DEFAULTS))

        self.assertEqual(
            relay_commands,
            ["status", "desktop", "deactivate-pro"],
        )
        remove.assert_called_once()

    def test_rollback_preserves_focused_desktop_event5_when_sync_succeeds(self):
        config = dict(MODULE.DEFAULTS)
        desktop = {
            "ok": True,
            "mode": "desktop",
            "pro_available": True,
            "waydroid_focused": True,
            "android_pro_active": True,
            "capability_generation": 7,
        }
        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE, "relay_command", return_value=desktop
            ) as relay,
            mock.patch.object(
                MODULE, "reconcile_android_links", return_value=desktop
            ) as reconcile,
            mock.patch.object(MODULE, "remove_owned_android_links") as remove,
        ):
            MODULE.rollback_to_desktop(config)

        relay.assert_called_once_with(config, "desktop")
        reconcile.assert_called_once_with(config, desktop)
        remove.assert_not_called()

    def test_pro_direct_prepares_event5_before_activating_relay(self):
        calls = []
        initial = {
            "ok": True,
            "mode": "desktop",
            "pro_available": True,
            "active_pen": "p81c",
            "waydroid_focused": True,
            "android_pro_active": False,
            "android_button_active": False,
            "capability_generation": 9,
        }

        def relay(_config, command):
            calls.append(("relay", command))
            mode = "direct" if command.startswith("direct") else "desktop"
            return dict(initial, mode=mode)

        with (
            mock.patch.object(MODULE, "relay_command", side_effect=relay),
            mock.patch.object(
                MODULE,
                "sync_android_links",
                side_effect=lambda _config, state: calls.append(
                    ("links", state["mode"], state["active_pen"], state["pro_available"])
                ),
            ),
        ):
            MODULE.direct_mode(dict(MODULE.DEFAULTS))

        self.assertEqual(
            calls,
            [
                ("relay", "status"),
                ("links", "direct", "p81c", True),
                ("relay", "status"),
                ("relay", "direct 9 1"),
            ],
        )

    def test_sync_reconciles_direct_pen_and_pro_links(self):
        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=[
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": True,
                        "active_pen": "p81c",
                        "waydroid_focused": True,
                        "android_pro_active": True,
                        "android_button_active": False,
                        "capability_generation": 3,
                    },
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": True,
                        "active_pen": "p81c",
                        "waydroid_focused": True,
                        "android_pro_active": True,
                        "android_button_active": False,
                        "capability_generation": 3,
                    },
                ],
            ) as relay,
            mock.patch.object(MODULE, "sync_android_links") as sync,
        ):
            MODULE.sync_mode(dict(MODULE.DEFAULTS))
        sync.assert_called_once()
        self.assertEqual(sync.call_args.args[0], dict(MODULE.DEFAULTS))
        self.assertEqual(sync.call_args.args[1]["active_pen"], "p81c")
        self.assertEqual(sync.call_args.args[1]["mode"], "direct")
        self.assertEqual(relay.call_count, 2)

    def test_sync_disables_android_pro_when_container_is_stopped(self):
        config = dict(MODULE.DEFAULTS)
        relay_state = {
            "ok": True,
            "mode": "desktop",
            "pro_available": True,
            "waydroid_focused": True,
            "android_pro_active": True,
            "capability_generation": 3,
        }
        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=False),
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=[relay_state, dict(relay_state, android_pro_active=False)],
            ) as relay,
        ):
            result_value = MODULE.sync_mode(config)
        self.assertFalse(result_value["android_pro_active"])
        self.assertEqual(
            relay.call_args_list,
            [mock.call(config, "status"), mock.call(config, "deactivate-pro")],
        )

    def test_sync_retries_when_capability_changes_during_link_update(self):
        config = dict(MODULE.DEFAULTS)
        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=[
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": False,
                        "active_pen": "m80p",
                        "waydroid_focused": True,
                        "android_pro_active": False,
                        "android_button_active": False,
                        "capability_generation": 4,
                    },
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": True,
                        "active_pen": "p81c",
                        "waydroid_focused": True,
                        "android_pro_active": False,
                        "android_button_active": False,
                        "capability_generation": 5,
                    },
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": True,
                        "active_pen": "p81c",
                        "waydroid_focused": True,
                        "android_pro_active": False,
                        "android_button_active": False,
                        "capability_generation": 5,
                    },
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": True,
                        "active_pen": "p81c",
                        "waydroid_focused": True,
                        "android_pro_active": True,
                        "android_button_active": False,
                        "capability_generation": 5,
                    },
                ],
            ),
            mock.patch.object(MODULE, "sync_android_links") as sync,
        ):
            result_value = MODULE.sync_mode(config)

        self.assertTrue(result_value["android_pro_active"])
        self.assertEqual(sync.call_count, 2)
        self.assertEqual(
            [call.args[1]["active_pen"] for call in sync.call_args_list],
            ["m80p", "p81c"],
        )

    def test_sync_keeps_only_event5_for_pro_desktop(self):
        relay_state = {
            "ok": True,
            "mode": "desktop",
            "pro_available": True,
            "active_pen": "p81c",
            "waydroid_focused": False,
            "android_pro_active": False,
            "android_button_active": False,
            "capability_generation": 6,
        }
        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=[relay_state, relay_state],
            ),
            mock.patch.object(MODULE, "remove_owned_android_links") as remove,
            mock.patch.object(MODULE, "sync_android_links") as sync,
        ):
            MODULE.sync_mode(dict(MODULE.DEFAULTS))
        remove.assert_not_called()
        sync.assert_called_once_with(dict(MODULE.DEFAULTS), relay_state)

    def test_mapping_is_validated_before_reaching_relay(self):
        with mock.patch.object(MODULE, "relay_command") as relay_command:
            result_value = MODULE.set_mapping(
                dict(MODULE.DEFAULTS), ["map", "0.1", "0.2", "0.7", "0.6"]
            )
        relay_command.assert_called_once_with(
            dict(MODULE.DEFAULTS),
            "map 0.100000000 0.200000000 0.700000000 0.600000000",
        )
        self.assertIs(result_value, relay_command.return_value)

    def test_mapping_outside_display_is_rejected(self):
        with self.assertRaises(MODULE.ModeError):
            MODULE.set_mapping(
                dict(MODULE.DEFAULTS), ["map", "0.5", "0.5", "0.6", "0.6"]
            )

    def test_non_finite_mapping_is_rejected(self):
        with self.assertRaises(MODULE.ModeError):
            MODULE.set_mapping(
                dict(MODULE.DEFAULTS), ["map", "nan", "0", "1", "1"]
            )

    def test_desktop_keeps_pro_gesture_link_available(self):
        config = dict(MODULE.DEFAULTS)
        relay_state = {
            "ok": True,
            "mode": "desktop",
            "pro_available": True,
            "waydroid_focused": False,
            "android_pro_active": False,
            "capability_generation": 8,
        }
        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE,
                "relay_command",
                return_value=relay_state,
            ) as relay,
            mock.patch.object(
                MODULE,
                "reconcile_android_links",
                return_value=relay_state,
            ) as reconcile,
        ):
            result_value = MODULE.desktop_mode(config)
        relay.assert_called_once_with(config, "desktop")
        reconcile.assert_called_once_with(config, relay_state)
        self.assertIs(result_value, relay_state)

    def test_desktop_focus_creates_event5_before_enabling_forwarding(self):
        config = dict(MODULE.DEFAULTS)
        unfocused = {
            "ok": True,
            "mode": "desktop",
            "pro_available": True,
            "active_pen": "p81c",
            "waydroid_focused": False,
            "android_pro_active": False,
            "android_button_active": False,
            "capability_generation": 9,
        }
        focused = dict(
            unfocused,
            waydroid_focused=True,
            android_pro_active=True,
        )
        calls = []

        def relay(_config, command):
            calls.append(("relay", command))
            return focused if command == "focus 1" else unfocused

        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(MODULE, "relay_command", side_effect=relay),
            mock.patch.object(
                MODULE,
                "sync_android_links",
                side_effect=lambda _config, state: calls.append(
                    ("preflight", state["waydroid_focused"])
                ),
            ),
            mock.patch.object(
                MODULE,
                "reconcile_android_links",
                side_effect=lambda _config, state: calls.append(
                    ("links", state["waydroid_focused"])
                )
                or state,
            ),
        ):
            MODULE.focus_mode(config, True)

        self.assertEqual(
            calls,
            [
                ("relay", "status"),
                ("preflight", True),
                ("relay", "focus 1"),
                ("links", True),
            ],
        )

    def test_focus_enable_failure_leaves_relay_unfocused(self):
        config = dict(MODULE.DEFAULTS)
        unfocused = {
            "ok": True,
            "mode": "desktop",
            "pro_available": True,
            "active_pen": "p81c",
            "waydroid_focused": False,
            "android_pro_active": False,
            "android_button_active": False,
            "capability_generation": 9,
        }
        with (
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE, "relay_command", return_value=unfocused
            ) as relay,
            mock.patch.object(
                MODULE,
                "sync_android_links",
                side_effect=MODULE.ModeError("event5 unavailable"),
            ),
        ):
            with self.assertRaisesRegex(MODULE.ModeError, "event5 unavailable"):
                MODULE.focus_mode(config, True)
        relay.assert_called_once_with(config, "status")

    def test_focus_loss_releases_without_requiring_container_access(self):
        config = dict(MODULE.DEFAULTS)
        focused = {
            "ok": True,
            "mode": "desktop",
            "pro_available": True,
            "active_pen": "p81c",
            "waydroid_focused": True,
            "android_pro_active": True,
            "android_button_active": False,
            "capability_generation": 9,
        }
        unfocused = dict(
            focused,
            waydroid_focused=False,
            android_pro_active=False,
        )
        with (
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=[focused, unfocused],
            ) as relay,
            mock.patch.object(MODULE, "waydroid_running", return_value=True),
            mock.patch.object(
                MODULE, "reconcile_android_links", return_value=unfocused
            ) as reconcile,
        ):
            result_value = MODULE.focus_mode(config, False)

        self.assertFalse(result_value["android_pro_active"])
        self.assertEqual(
            relay.call_args_list,
            [mock.call(config, "status"), mock.call(config, "focus 0")],
        )
        reconcile.assert_called_once_with(config, unfocused)

    def test_integration_files_cover_optional_pro_lifecycle(self):
        install = INSTALL_PATH.read_text(encoding="utf-8")
        uninstall = UNINSTALL_PATH.read_text(encoding="utf-8")
        rules = RULE_PATH.read_text(encoding="utf-8")
        service = SERVICE_PATH.read_text(encoding="utf-8")
        container_dropin = (
            ROOT / "config" / "waydroid-container-pen.conf"
        ).read_text(encoding="utf-8")
        extension = EXTENSION_PATH.read_text(encoding="utf-8")
        session = SESSION_PATH.read_text(encoding="utf-8")
        link_path = LINK_PATH_UNIT.read_text(encoding="utf-8")
        link_service = LINK_SERVICE_UNIT.read_text(encoding="utf-8")
        user_session = USER_SESSION_UNIT.read_text(encoding="utf-8")
        user_reapply = USER_REAPPLY_UNIT.read_text(encoding="utf-8")
        user_reapply_path = USER_REAPPLY_PATH.read_text(encoding="utf-8")
        kwin_metadata = KWIN_METADATA.read_text(encoding="utf-8")
        kwin_main = KWIN_MAIN.read_text(encoding="utf-8")
        plasmoid_metadata = PLASMOID_METADATA.read_text(encoding="utf-8")
        plasmoid_main = PLASMOID_MAIN.read_text(encoding="utf-8")

        self.assertIn("waydroid_pen_gesture", install)
        self.assertIn("NOPASSWD: %s sync", install)
        self.assertIn("NOPASSWD: %s focus *", install)
        self.assertIn("Vendor_2717_Product_3655.kl", install)
        self.assertIn("Vendor_2717_Product_3655.kcm", uninstall)
        self.assertIn("xiaomi-sheng-thp.service", install)
        self.assertIn("disable --now", uninstall)
        self.assertIn("udevadm trigger", uninstall)
        self.assertIn("disabled-by-waydroid-pen-mode", uninstall)
        self.assertIn("xiaomi-sheng-thp is left installed", uninstall)
        self.assertIn("98-waydroid-pen-restore-thp.rules", uninstall)
        self.assertIn('ENV{LIBINPUT_IGNORE_DEVICE}=""', uninstall)
        self.assertNotIn("systemctl disable xiaomi-sheng-thp", uninstall)
        self.assertNotIn("systemctl stop xiaomi-sheng-thp", uninstall)
        self.assertIn('ATTRS{id/bustype}=="0006"', rules)
        self.assertIn('ATTRS{id/vendor}=="2717"', rules)
        self.assertIn('ATTRS{id/product}=="3654"', rules)
        self.assertIn('ATTRS{id/vendor}=="0022"', rules)
        self.assertIn('ATTRS{id/product}=="5081"', rules)
        self.assertIn('ATTRS{phys}=="waydroid-gesture-android"', rules)
        self.assertIn("Xiaomi Focus Pen Pro Gestures", rules)
        self.assertIn('phys}=="waydroid-pen-m80p"', rules)
        self.assertIn('phys}=="waydroid-pen-p81c"', rules)
        self.assertIn('phys}=="waydroid-android-pen-m80p"', rules)
        self.assertIn('phys}=="waydroid-android-pen-p81c"', rules)
        self.assertIn('ENV{LIBINPUT_IGNORE_DEVICE}="1"', rules)
        self.assertIn("waydroid-android-pen-m80p", service)
        self.assertIn("waydroid-android-pen-p81c", service)
        self.assertIn("waydroid-android-buttons", service)
        self.assertNotIn("-e /dev/input/waydroid-android-gestures", service)
        self.assertNotIn("waydroid-pen-gestures", service)
        self.assertNotIn("-e /dev/input/waydroid-pen ", service)
        self.assertIn(
            "ExecStartPost=-/usr/local/libexec/waydroid-pen-mode sync",
            container_dropin,
        )
        self.assertIn(
            "ExecStopPost=-/usr/local/libexec/waydroid-pen-mode sync",
            container_dropin,
        )
        self.assertIn("waydroid-pen-session", extension)
        self.assertNotIn("sudo", extension)
        self.assertNotIn("capability_generation", extension)
        self.assertIn("Main.overview.connectObject", extension)
        self.assertIn(
            "PathChanged=/run/waydroid-pen-mode/link-state.json",
            link_path,
        )
        self.assertIn("BindsTo=waydroid-pen-relay.service", link_path)
        self.assertIn("Requisite=waydroid-pen-relay.service", link_service)
        self.assertIn("waydroid-pen-mode sync", link_service)
        self.assertNotIn("StartLimitIntervalSec=0", link_path + link_service)
        self.assertIn(
            "ExecStartPost=-/usr/local/libexec/waydroid-pen-mode sync",
            service,
        )
        self.assertIn("waydroid-pen-session apply %i", user_session)
        self.assertIn("waydroid-pen-session reapply", user_reapply)
        self.assertIn(
            "PathChanged=/run/waydroid-pen-mode/link-state.json",
            user_reapply_path,
        )
        self.assertIn("stale desktop context generation", session)
        self.assertIn('"KPackageStructure": "KWin/Script"', kwin_metadata)
        self.assertNotIn('"X-Plasma-MainScript"', kwin_metadata)
        self.assertIn("Workspace.activeWindow", kwin_main)
        self.assertIn("org.freedesktop.systemd1.Manager", kwin_main)
        self.assertIn('"KPackageStructure": "Plasma/Applet"', plasmoid_metadata)
        self.assertIn('"X-Plasma-NotificationAreaCategory": "Hardware"', plasmoid_metadata)
        self.assertIn("auto", plasmoid_main)
        self.assertIn("waydroid", plasmoid_main)
        self.assertIn("desktop", plasmoid_main)
        self.assertIn("statusPending", plasmoid_main)
        self.assertIn("policyPending", plasmoid_main)
        self.assertIn("waydroid-pen-link-sync.path", install)
        self.assertIn("org.xinyang.waydroidpenmode", install)
        self.assertNotIn("SystrayContainmentId", install + uninstall)
        self.assertIn('widget.currentConfigGroup = ["General"]', install)
        self.assertIn('widget.currentConfigGroup = ["General"]', uninstall)
        self.assertIn("waydroid-pen-session@.service", uninstall)
        self.assertIn("waydroid-pen-session.path", install)
        self.assertIn("reset-failed", install)
        self.assertIn("waydroid-pen-session.path", uninstall)
        self.assertNotIn("waydroid shell", install + uninstall)
        self.assertIn("/usr/bin/lxc-info", install)
        self.assertIn("/usr/bin/lxc-attach", install)
        self.assertIn('"$state" == FROZEN', install)
        self.assertIn('"$state" == FROZEN', uninstall)


if __name__ == "__main__":
    unittest.main()
