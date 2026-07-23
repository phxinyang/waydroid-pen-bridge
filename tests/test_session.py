import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SESSION_PATH = (
    Path(__file__).resolve().parents[1]
    / "helper"
    / "waydroid-pen-session.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waydroid_pen_session", SESSION_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SessionTests(unittest.TestCase):
    def test_auto_policy_follows_focus_but_overview_forces_desktop(self):
        focused = MODULE.make_context("kde", 1, True, False, None)
        overview = MODULE.make_context("kde", 2, True, True, None)
        unfocused = MODULE.make_context("kde", 3, False, False, None)
        self.assertEqual(MODULE.desired_mode("auto", focused), "direct")
        self.assertEqual(MODULE.desired_mode("auto", overview), "desktop")
        self.assertEqual(MODULE.desired_mode("auto", unfocused), "desktop")

    def test_explicit_policies_ignore_focus(self):
        context = MODULE.make_context("gnome", 1, False, True, None)
        self.assertEqual(MODULE.desired_mode("waydroid", context), "direct")
        self.assertEqual(MODULE.desired_mode("desktop", context), "desktop")

    def test_context_token_round_trip_preserves_mapping(self):
        context = MODULE.make_context(
            "kde", 42, True, False, (0.125, 0.25, 0.75, 0.5)
        )
        token = MODULE.context_token(context)
        self.assertRegex(token, r"^[a-z0-9.]+$")
        self.assertEqual(MODULE.parse_context_token(token), context)

    def test_stale_generation_is_rejected_per_desktop_source(self):
        previous = MODULE.make_context("kde", 8, True, False, None)
        stale = MODULE.make_context("kde", 7, False, False, None)
        with self.assertRaisesRegex(MODULE.SessionError, "stale"):
            MODULE.accept_context(previous, stale)

    def test_new_desktop_source_can_replace_previous_session(self):
        previous = MODULE.make_context(
            "gnome_1700000000000_1", 99, True, False, None
        )
        incoming = MODULE.make_context(
            "kde_1700000001000_1", 1, False, False, None
        )
        MODULE.accept_context(previous, incoming)

    def test_superseded_desktop_source_is_rejected(self):
        previous = MODULE.make_context(
            "kde_1700000002000_1", 1, True, False, None
        )
        stale = MODULE.make_context(
            "gnome_1700000001000_9", 100, False, False, None
        )
        with self.assertRaisesRegex(MODULE.SessionError, "stale"):
            MODULE.accept_context(previous, stale)

    def test_same_generation_with_different_context_is_rejected(self):
        previous = MODULE.make_context("kde", 8, True, False, None)
        conflicting = MODULE.make_context("kde", 8, False, False, None)
        with self.assertRaisesRegex(MODULE.SessionError, "conflicting"):
            MODULE.accept_context(previous, conflicting)

    def test_direct_context_maps_before_switching_mode(self):
        context = MODULE.make_context(
            "kde", 2, True, False, (0.1, 0.2, 0.7, 0.6)
        )
        with mock.patch.object(MODULE, "root_command") as root:
            mode = MODULE.apply_context("auto", context)
        self.assertEqual(mode, "direct")
        self.assertEqual(
            root.call_args_list,
            [
                mock.call(
                    [
                        "map",
                        "0.100000000",
                        "0.200000000",
                        "0.700000000",
                        "0.600000000",
                    ]
                ),
                mock.call(["direct"]),
            ],
        )

    def test_desktop_context_does_not_mutate_mapping(self):
        context = MODULE.make_context("gnome", 2, False, True, None)
        with mock.patch.object(MODULE, "root_command") as root:
            mode = MODULE.apply_context("auto", context)
        self.assertEqual(mode, "desktop")
        root.assert_called_once_with(["desktop"])

    def test_reconcile_persists_context_and_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "policy": root / "config" / "policy",
                "state": root / "state" / "session.json",
                "lock": root / "run" / "session.lock",
            }
            context = MODULE.make_context("kde", 4, True, False, None)
            with (
                mock.patch.object(
                    MODULE, "apply_context", return_value="direct"
                ),
                mock.patch.object(
                    MODULE,
                    "query_root_status",
                    return_value={
                        "mode": "direct",
                        "relay": {"instance_id": "relay-1"},
                    },
                ),
            ):
                MODULE.reconcile(paths, "auto", context, {})
            state = json.loads(paths["state"].read_text(encoding="utf-8"))
        self.assertEqual(state["policy"], "auto")
        self.assertEqual(state["context"], context)
        self.assertEqual(state["desired_mode"], "direct")
        self.assertEqual(state["applied_mode"], "direct")
        self.assertEqual(state["relay_instance"], "relay-1")
        self.assertIsNone(state["last_error"])

    def test_reapply_saved_context_after_relay_restart(self):
        context = MODULE.make_context("kde_1700000002000_1", 4, True, False, None)
        state = {"context": context, "relay_instance": "relay-old"}
        root = {
            "mode": "desktop",
            "relay": {"instance_id": "relay-new"},
        }
        with (
            mock.patch.object(MODULE, "query_root_status", return_value=root),
            mock.patch.object(
                MODULE, "reconcile", return_value={"applied_mode": "direct"}
            ) as reconcile,
        ):
            result = MODULE.reapply_saved({}, "auto", context, state)
        reconcile.assert_called_once_with({}, "auto", context, state)
        self.assertEqual(result["applied_mode"], "direct")

    def test_reconcile_retries_if_relay_restarts_during_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "policy": root / "config" / "policy",
                "state": root / "state" / "session.json",
                "lock": root / "run" / "session.lock",
            }
            context = MODULE.make_context(
                "kde_1700000002000_1", 4, True, False, None
            )
            statuses = [
                {"mode": "desktop", "relay": {"instance_id": "relay-old"}},
                {"mode": "desktop", "relay": {"instance_id": "relay-new"}},
                {"mode": "desktop", "relay": {"instance_id": "relay-new"}},
                {"mode": "direct", "relay": {"instance_id": "relay-new"}},
            ]
            with (
                mock.patch.object(
                    MODULE, "apply_context", return_value="direct"
                ) as apply,
                mock.patch.object(
                    MODULE, "query_root_status", side_effect=statuses
                ),
            ):
                MODULE.reconcile(paths, "auto", context, {})
            state = json.loads(paths["state"].read_text(encoding="utf-8"))
        self.assertEqual(apply.call_count, 2)
        self.assertEqual(state["relay_instance"], "relay-new")
        self.assertEqual(state["applied_mode"], "direct")

    def test_reapply_ignores_state_changes_from_same_relay_instance(self):
        context = MODULE.make_context("kde_1700000002000_1", 4, True, False, None)
        state = {"context": context, "relay_instance": "relay-current"}
        root = {
            "mode": "desktop",
            "relay": {"instance_id": "relay-current"},
        }
        with (
            mock.patch.object(MODULE, "query_root_status", return_value=root),
            mock.patch.object(MODULE, "reconcile") as reconcile,
        ):
            result = MODULE.reapply_saved({}, "auto", context, state)
        reconcile.assert_not_called()
        self.assertIs(result, state)


if __name__ == "__main__":
    unittest.main()
