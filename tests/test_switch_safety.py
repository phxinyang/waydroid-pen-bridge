import importlib.util
from pathlib import Path
import unittest
from unittest import mock


HELPER_PATH = Path(__file__).resolve().parents[1] / "helper" / "waydroid-pen-mode.py"
SPEC = importlib.util.spec_from_file_location("waydroid_pen_mode", HELPER_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SwitchSafetyTests(unittest.TestCase):
    def test_direct_stops_desktop_forwarding_before_connecting_android(self):
        calls = []
        with (
            mock.patch.object(
                MODULE, "ensure_android_link", side_effect=lambda cfg: calls.append("link")
            ),
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=lambda cfg, mode: calls.append(mode) or {"ok": True},
            ),
        ):
            MODULE.direct_mode(dict(MODULE.DEFAULTS))
        self.assertEqual(calls, ["direct", "link", "status"])

    def test_direct_link_failure_restores_desktop_forwarding(self):
        relay_modes = []
        with (
            mock.patch.object(MODULE, "ensure_android_link", side_effect=RuntimeError),
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=lambda cfg, mode: relay_modes.append(mode) or {"ok": True},
            ),
            mock.patch("builtins.print"),
        ):
            with self.assertRaises(RuntimeError):
                MODULE.direct_mode(dict(MODULE.DEFAULTS))
        self.assertEqual(relay_modes, ["direct", "desktop"])

    def test_desktop_disconnects_android_before_forwarding_to_proxy(self):
        calls = []
        with (
            mock.patch.object(
                MODULE, "remove_android_link", side_effect=lambda cfg: calls.append("unlink")
            ),
            mock.patch.object(
                MODULE,
                "relay_command",
                side_effect=lambda cfg, mode: calls.append(mode) or {"ok": True},
            ),
        ):
            MODULE.desktop_mode(dict(MODULE.DEFAULTS))
        self.assertEqual(calls, ["unlink", "desktop"])


if __name__ == "__main__":
    unittest.main()
