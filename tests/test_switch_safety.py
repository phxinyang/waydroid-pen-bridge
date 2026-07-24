import importlib.util
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

SPEC = importlib.util.spec_from_file_location("waydroid_pen_mode", HELPER_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def result(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


class SwitchSafetyTests(unittest.TestCase):
    def test_android_mapping_is_unified_194_through_197(self):
        keylayout = GESTURE_KEYLAYOUT_PATH.read_text(encoding="utf-8")
        keychars = GESTURE_KEYCHARS_PATH.read_text(encoding="utf-8")
        self.assertEqual(
            keylayout.splitlines(),
            [
                "key 148   BUTTON_7",
                "key 149   BUTTON_8",
                "key 202   BUTTON_9",
                "key 203   BUTTON_10",
            ],
        )
        for button in range(7, 11):
            self.assertIn(f"key BUTTON_{button} {{", keychars)
        self.assertEqual(keychars.count("base: none"), 4)
        for legacy in ("NUMPAD", "PAGE_UP", "PAGE_DOWN", "key 73", "key 81"):
            self.assertNotIn(legacy, keylayout + keychars)

    def test_relay_contains_no_legacy_slide_translation(self):
        relay = RELAY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("KEY_KP9", relay)
        self.assertNotIn("KEY_KP3", relay)
        self.assertNotIn("ANDROID_GESTURE_KEY_MAP", relay)

    def test_android_link_specs_keep_event4_and_event5_stable(self):
        links = MODULE.android_links(dict(MODULE.DEFAULTS))
        self.assertEqual(links[0]["link"], "/dev/input/event4")
        self.assertEqual(links[0]["target"], "../waydroid_pen")
        self.assertEqual(links[1]["link"], "/dev/input/event5")
        self.assertEqual(links[1]["target"], "../waydroid_pen_gesture")

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

    def test_ordinary_sync_creates_event4_only(self):
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
            MODULE.sync_android_links(dict(MODULE.DEFAULTS), False)

        link_commands = [command for command in commands if command[0] == "ln"]
        self.assertEqual(
            link_commands,
            [("ln", "-s", "../waydroid_pen", "/dev/input/event4")],
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
            MODULE.sync_android_links(dict(MODULE.DEFAULTS), True)

        link_commands = [command for command in commands if command[0] == "ln"]
        self.assertEqual(
            link_commands,
            [
                ("ln", "-s", "../waydroid_pen", "/dev/input/event4"),
                (
                    "ln",
                    "-s",
                    "../waydroid_pen_gesture",
                    "/dev/input/event5",
                ),
            ],
        )

    def test_pro_disconnect_removes_owned_event5(self):
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
            MODULE.sync_android_links(dict(MODULE.DEFAULTS), False)

        self.assertIn(("unlink", "/dev/input/event5"), commands)
        self.assertNotIn(("unlink", "/dev/input/event4"), commands)

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
                MODULE.sync_android_links(dict(MODULE.DEFAULTS), True)
        shell.assert_not_called()

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
                MODULE.sync_android_links(dict(MODULE.DEFAULTS), True)

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
            mock.patch.object(
                MODULE, "sync_android_links", side_effect=MODULE.ModeError("failed")
            ),
            mock.patch.object(MODULE, "remove_owned_android_links") as remove,
        ):
            with self.assertRaises(MODULE.ModeError):
                MODULE.direct_mode(dict(MODULE.DEFAULTS))

        self.assertEqual(relay_commands, ["status", "desktop"])
        remove.assert_called_once()

    def test_pro_direct_prepares_event5_before_activating_relay(self):
        calls = []
        initial = {
            "ok": True,
            "mode": "desktop",
            "pro_available": True,
            "android_pro_active": False,
            "capability_generation": 9,
        }

        def relay(_config, command):
            calls.append(("relay", command))
            return dict(initial, mode="direct" if command.startswith("direct") else "desktop")

        with (
            mock.patch.object(MODULE, "relay_command", side_effect=relay),
            mock.patch.object(
                MODULE,
                "sync_android_links",
                side_effect=lambda _config, pro: calls.append(("links", pro)),
            ),
        ):
            MODULE.direct_mode(dict(MODULE.DEFAULTS))

        self.assertEqual(
            calls,
            [
                ("relay", "status"),
                ("links", True),
                ("relay", "status"),
                ("relay", "direct 9 1"),
            ],
        )

    def test_sync_reconciles_links_only_while_direct(self):
        with (
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=[
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": True,
                        "android_pro_active": True,
                        "capability_generation": 3,
                    },
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": True,
                        "android_pro_active": True,
                        "capability_generation": 3,
                    },
                ],
            ) as relay,
            mock.patch.object(MODULE, "sync_android_links") as sync,
        ):
            MODULE.sync_mode(dict(MODULE.DEFAULTS))
        sync.assert_called_once_with(dict(MODULE.DEFAULTS), True)
        self.assertEqual(relay.call_count, 2)

    def test_sync_retries_when_capability_changes_during_link_update(self):
        config = dict(MODULE.DEFAULTS)
        with (
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=[
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": False,
                        "android_pro_active": False,
                        "capability_generation": 4,
                    },
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": True,
                        "android_pro_active": False,
                        "capability_generation": 5,
                    },
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": True,
                        "android_pro_active": False,
                        "capability_generation": 5,
                    },
                    {
                        "ok": True,
                        "mode": "direct",
                        "pro_available": True,
                        "android_pro_active": True,
                        "capability_generation": 5,
                    },
                ],
            ),
            mock.patch.object(MODULE, "sync_android_links") as sync,
        ):
            result_value = MODULE.sync_mode(config)

        self.assertTrue(result_value["android_pro_active"])
        self.assertEqual(
            sync.call_args_list,
            [mock.call(config, False), mock.call(config, True)],
        )

    def test_sync_removes_owned_links_when_relay_is_desktop(self):
        with (
            mock.patch.object(
                MODULE,
                "relay_command",
                return_value={"ok": True, "mode": "desktop"},
            ),
            mock.patch.object(MODULE, "remove_owned_android_links") as remove,
            mock.patch.object(MODULE, "sync_android_links") as sync,
        ):
            MODULE.sync_mode(dict(MODULE.DEFAULTS))
        remove.assert_called_once()
        sync.assert_not_called()

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

    def test_desktop_releases_android_before_removing_links(self):
        calls = []
        with (
            mock.patch.object(
                MODULE,
                "remove_owned_android_links",
                side_effect=lambda cfg: calls.append("unlink"),
            ),
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=lambda cfg, mode: calls.append(mode) or {"ok": True},
            ),
        ):
            MODULE.desktop_mode(dict(MODULE.DEFAULTS))
        self.assertEqual(calls, ["desktop", "unlink"])

    def test_integration_files_cover_optional_pro_lifecycle(self):
        install = INSTALL_PATH.read_text(encoding="utf-8")
        uninstall = UNINSTALL_PATH.read_text(encoding="utf-8")
        rules = RULE_PATH.read_text(encoding="utf-8")
        service = SERVICE_PATH.read_text(encoding="utf-8")
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
        self.assertIn("Vendor_2717_Product_3655.kl", install)
        self.assertIn("Vendor_2717_Product_3655.kcm", uninstall)
        self.assertIn('ATTRS{id/bustype}=="0006"', rules)
        self.assertIn('ATTRS{id/vendor}=="2717"', rules)
        self.assertIn('ATTRS{id/product}=="3654"', rules)
        self.assertIn('ATTRS{id/vendor}=="0022"', rules)
        self.assertIn('ATTRS{id/product}=="5081"', rules)
        self.assertIn('ATTRS{phys}=="waydroid-gesture-android"', rules)
        self.assertIn("Xiaomi Focus Pen Pro Gestures", rules)
        self.assertIn("waydroid-android-gestures", service)
        self.assertNotIn("waydroid-pen-gestures", service)
        self.assertIn("waydroid-pen-session", extension)
        self.assertNotIn("sudo", extension)
        self.assertNotIn("capability_generation", extension)
        self.assertIn("Main.overview.connectObject", extension)
        self.assertIn("PathChanged=/run/waydroid-pen-mode/state.json", link_path)
        self.assertIn("BindsTo=waydroid-pen-relay.service", link_path)
        self.assertIn("Requisite=waydroid-pen-relay.service", link_service)
        self.assertIn("waydroid-pen-mode sync", link_service)
        self.assertIn("waydroid-pen-session apply %i", user_session)
        self.assertIn("waydroid-pen-session reapply", user_reapply)
        self.assertIn(
            "PathChanged=/run/waydroid-pen-mode/state.json",
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
        self.assertIn("waydroid-pen-session.path", uninstall)
        self.assertNotIn("waydroid shell", install + uninstall)
        self.assertIn("/usr/bin/lxc-info", install)
        self.assertIn("/usr/bin/lxc-attach", install)
        self.assertIn('"$state" == FROZEN', install)
        self.assertIn('"$state" == FROZEN', uninstall)


if __name__ == "__main__":
    unittest.main()
