#!/usr/bin/python3

import fcntl
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys


CONFIG_PATH = Path("/etc/waydroid-pen-mode.conf")
LOCK_PATH = Path("/run/lock/waydroid-pen-mode.lock")
LXC_PATH = "/var/lib/waydroid/lxc"
LXC_NAME = "waydroid"
LXC_INFO = "/usr/bin/lxc-info"
LXC_UNFREEZE = "/usr/bin/lxc-unfreeze"
LXC_FREEZE = "/usr/bin/lxc-freeze"
ANDROID_PATH = "/system/bin:/system/xbin"
COMMAND_TIMEOUT_SECONDS = 5.0

DEFAULTS = {
    "CONTROL_SOCKET": "/run/waydroid-pen-mode/control.sock",
    "ANDROID_M80P_DEVICE": "/dev/waydroid_pen_m80p",
    "ANDROID_P81C_DEVICE": "/dev/waydroid_pen_p81c",
    "ANDROID_BUTTON_DEVICE": "/dev/waydroid_pen_buttons",
    "ANDROID_DEVICE": "/dev/waydroid_pen",
    "ANDROID_LINK": "/dev/input/event4",
    "ANDROID_LINK_TARGET_M80P": "../waydroid_pen_m80p",
    "ANDROID_LINK_TARGET_P81C": "../waydroid_pen_p81c",
    "ANDROID_LINK_TARGET": "../waydroid_pen",
    "ANDROID_BUTTON_LINK_TARGET": "../waydroid_pen_buttons",
    "ANDROID_GESTURE_DEVICE": "/dev/waydroid_pen_gesture",
    "ANDROID_GESTURE_LINK": "/dev/input/event5",
    "ANDROID_GESTURE_LINK_TARGET": "../waydroid_pen_gesture",
}


class ModeError(RuntimeError):
    pass


def load_config():
    config = dict(DEFAULTS)
    if not CONFIG_PATH.exists():
        return config

    for raw_line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in config:
            config[key] = value.strip()
    return config


def run(command, *, check=True, capture=False):
    return subprocess.run(
        command,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )


def waydroid_shell(*arguments, check=True, capture=False):
    command = [
        "/usr/bin/lxc-attach",
        "-P",
        LXC_PATH,
        "-n",
        LXC_NAME,
        "--clear-env",
        "--set-var",
        f"PATH={ANDROID_PATH}",
        "--",
        "/system/bin/sh",
        "-c",
        'exec "$@"',
        "waydroid-pen-mode",
        *arguments,
    ]
    thawed = waydroid_state() == "FROZEN"
    if thawed:
        run([LXC_UNFREEZE, "-P", LXC_PATH, "-n", LXC_NAME])
    try:
        return run(command, check=check, capture=capture)
    finally:
        if thawed:
            run(
                [LXC_FREEZE, "-P", LXC_PATH, "-n", LXC_NAME],
                check=False,
            )


def waydroid_state():
    result = run(
        [LXC_INFO, "-P", LXC_PATH, "-n", LXC_NAME, "-sH"],
        check=False,
        capture=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def waydroid_running():
    return waydroid_state() in {"RUNNING", "FROZEN"}


def android_readlink(link_path):
    if not waydroid_running():
        return None
    result = waydroid_shell("readlink", link_path, check=False, capture=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def android_path_exists(path):
    if not waydroid_running():
        return False
    result = waydroid_shell(
        "sh",
        "-c",
        (
            'if [ -e "$1" ] || [ -L "$1" ]; then '
            'printf present; else printf missing; fi'
        ),
        "waydroid-pen-mode",
        path,
        check=False,
        capture=True,
    )
    state = result.stdout.strip()
    if state == "present":
        return True
    if state == "missing":
        return False
    raise ModeError(f"failed to inspect Android path {path}")


def _pen_link_targets(config):
    return {
        "m80p": (
            config.get("ANDROID_M80P_DEVICE", "/dev/waydroid_pen_m80p"),
            config.get("ANDROID_LINK_TARGET_M80P", "../waydroid_pen_m80p"),
        ),
        "p81c": (
            config.get("ANDROID_P81C_DEVICE", "/dev/waydroid_pen_p81c"),
            config.get("ANDROID_LINK_TARGET_P81C", "../waydroid_pen_p81c"),
        ),
    }


def _side_link_target(config, relay):
    # event5 is a single active-pen side channel.  A paired Pro gestures
    # source must not steal the ordinary M80p button route while M80p is the
    # active pen.
    if (relay.get("active_pen") == "p81c"
            and relay.get("pro_available")):
        return (
            config["ANDROID_GESTURE_DEVICE"],
            config["ANDROID_GESTURE_LINK_TARGET"],
            "gesture",
        )
    if (relay.get("active_pen") == "m80p"
            and relay.get("mode") == "desktop"
            and relay.get("android_button_active")):
        return (
            config.get("ANDROID_BUTTON_DEVICE", "/dev/waydroid_pen_buttons"),
            config.get("ANDROID_BUTTON_LINK_TARGET", "../waydroid_pen_buttons"),
            "button",
        )
    return None


def android_links(config, relay=None):
    """Return the desired event4/event5 links for a relay snapshot.

    Both model devices are mounted into LXC permanently.  event4 points at
    the active model only in direct mode; event5 points at Pro gestures or the
    ordinary-button side channel when that route is required.
    """
    relay = relay or {}
    targets = _pen_link_targets(config)
    active = relay.get("active_pen")
    pen_device, pen_target = targets.get(active, (None, None))
    pen_owned = {target for _device, target in targets.values()}
    # Migrate the previous one-device installation without treating it as a
    # foreign link.
    pen_owned.add(config.get("ANDROID_LINK_TARGET", "../waydroid_pen"))
    side = _side_link_target(config, relay)
    side_targets = {
        config.get("ANDROID_BUTTON_LINK_TARGET", "../waydroid_pen_buttons"),
        config.get("ANDROID_GESTURE_LINK_TARGET", "../waydroid_pen_gesture"),
    }
    return (
        {
            "device": pen_device,
            "link": config["ANDROID_LINK"],
            "target": pen_target if relay.get("mode") == "direct" else None,
            "owned_targets": pen_owned,
            "capability": "pen",
        },
        {
            "device": side[0] if side else None,
            "link": config["ANDROID_GESTURE_LINK"],
            "target": side[1] if side else None,
            "owned_targets": side_targets,
            "capability": side[2] if side else "side",
        },
    )


def inspect_android_link(spec):
    target = android_readlink(spec["link"])
    if target in spec.get("owned_targets", {spec.get("target")}):
        return "owned", target
    if target is not None:
        return "foreign", target
    if android_path_exists(spec["link"]):
        return "foreign", "<non-symlink>"
    return "missing", None


def remove_owned_android_links(config):
    if not waydroid_running():
        return
    for spec in android_links(config, {"mode": "desktop"}):
        state, _target = inspect_android_link(spec)
        if state == "owned":
            waydroid_shell("unlink", spec["link"], check=False)


def sync_android_links(config, relay_or_pen_required, pro_available=None,
                       active_pen=None):
    # Keep the old three-argument entry point for local callers while making
    # the relay snapshot the source of truth for active model and side route.
    if isinstance(relay_or_pen_required, bool):
        relay = {
            "mode": "direct" if relay_or_pen_required else "desktop",
            "pro_available": bool(pro_available),
            "active_pen": active_pen or ("p81c" if pro_available else "m80p"),
            "android_button_active": False,
        }
    else:
        relay = dict(relay_or_pen_required)
    if not waydroid_running():
        raise ModeError("Waydroid is not running")

    specs = android_links(config, relay)
    required = set()
    if relay.get("mode") == "direct" and specs[0]["target"] is not None:
        required.add("pen")
    if specs[1]["target"] is not None:
        required.add(specs[1]["capability"])
    states = {}
    for spec in specs:
        state, target = inspect_android_link(spec)
        if state == "foreign" and spec["capability"] in required:
            raise ModeError(
                f"refusing to replace Android link {spec['link']} -> {target}"
            )
        states[spec["capability"]] = (state, target)

    for spec in specs:
        if spec["capability"] not in required or not spec["device"]:
            continue
        probe = waydroid_shell("test", "-c", spec["device"], check=False)
        if probe.returncode != 0:
            raise ModeError(f"Waydroid device is missing: {spec['device']}")

    # Apply the complete two-link update as a small transaction.  A failed
    # event5 replacement must restore the previous owned event4/event5 links,
    # otherwise a mode switch leaves Android with a half-configured path.
    removed = []
    created = []
    try:
        for spec in specs:
            state, current = states[spec["capability"]]
            desired = spec["target"] if spec["capability"] in required else None
            if state != "owned" or current == desired:
                continue
            waydroid_shell("unlink", spec["link"])
            removed.append((spec, current))
        for spec in specs:
            state, current = states[spec["capability"]]
            desired = spec["target"] if spec["capability"] in required else None
            if desired is None or (state == "owned" and current == desired):
                continue
            waydroid_shell("ln", "-s", desired, spec["link"])
            created.append(spec)
    except Exception:
        for spec in reversed(created):
            waydroid_shell("unlink", spec["link"], check=False)
        for spec, target in reversed(removed):
            waydroid_shell("ln", "-s", target, spec["link"], check=False)
        raise


def rollback_to_desktop(config):
    relay = None
    try:
        relay = relay_command(config, "desktop")
    except Exception as rollback_error:
        print(f"relay rollback failed: {rollback_error}", file=sys.stderr)

    if relay is not None and waydroid_running():
        try:
            reconcile_android_links(config, relay)
            return
        except Exception as rollback_error:
            print(
                f"desktop link rollback failed: {rollback_error}",
                file=sys.stderr,
            )

    try:
        relay_command(config, "deactivate-pro")
    except Exception as rollback_error:
        print(f"relay Pro release failed: {rollback_error}", file=sys.stderr)
    try:
        remove_owned_android_links(config)
    except Exception as rollback_error:
        print(f"Android link cleanup failed: {rollback_error}", file=sys.stderr)


def capability_snapshot(relay):
    try:
        generation = relay["capability_generation"]
        pro_available = relay["pro_available"]
    except (KeyError, TypeError) as error:
        raise ModeError("pen relay returned an invalid capability state") from error
    if isinstance(generation, bool) or not isinstance(generation, int):
        raise ModeError("pen relay returned an invalid capability state")
    if generation < 0 or not isinstance(pro_available, bool):
        raise ModeError("pen relay returned an invalid capability state")
    return generation, pro_available


def capability_matches(left, right):
    return capability_snapshot(left) == capability_snapshot(right)


def routing_snapshot(relay):
    generation, pro_available = capability_snapshot(relay)
    mode = relay.get("mode")
    if mode not in {"desktop", "direct"}:
        raise ModeError("pen relay returned an invalid routing mode")
    active_pen = relay.get("active_pen")
    if active_pen not in {None, "m80p", "p81c"}:
        raise ModeError("pen relay returned an invalid active pen")
    booleans = (
        "waydroid_focused",
        "android_pro_active",
        "android_button_active",
    )
    for field in booleans:
        value = relay.get(field, False)
        if not isinstance(value, bool):
            if field == "waydroid_focused":
                raise ModeError("pen relay returned an invalid focus state")
            raise ModeError(f"pen relay returned an invalid {field} state")
    return (
        mode,
        generation,
        pro_available,
        active_pen,
        relay.get("waydroid_focused", False),
        relay.get("android_pro_active", False),
        relay.get("android_button_active", False),
    )


def routing_matches(left, right):
    return routing_snapshot(left) == routing_snapshot(right)


def android_pro_should_be_active(relay):
    _mode, _generation, pro_available, active, focused, _pro_active, _button_active = (
        routing_snapshot(relay)
    )
    return pro_available and active == "p81c" and focused


def android_pro_is_active(relay):
    active = relay.get("android_pro_active", False)
    if not isinstance(active, bool):
        raise ModeError("pen relay returned an invalid Android Pro state")
    return active


def prepare_android_links(config, relay):
    snapshot = routing_snapshot(relay)
    sync_android_links(config, relay)
    current = relay_command(config, "status")
    if not routing_matches(relay, current):
        return None, current
    return snapshot, current


def reconcile_android_links(config, relay):
    for _attempt in range(3):
        prepared, current = prepare_android_links(config, relay)
        if prepared is None:
            relay = current
            continue
        _mode, generation, _pro_available, _active, _focused, _pro_active, _button_active = prepared
        if android_pro_should_be_active(current) and not android_pro_is_active(
            current
        ):
            try:
                return relay_command(config, f"activate-pro {generation}")
            except ModeError:
                relay = relay_command(config, "status")
                continue
        if not android_pro_should_be_active(current) and android_pro_is_active(
            current
        ):
            try:
                return relay_command(config, "deactivate-pro")
            except ModeError:
                relay = relay_command(config, "status")
                continue
        return current
    raise ModeError(
        "pen capability or routing changed repeatedly during link sync"
    )


def prepare_direct_links(config, relay):
    snapshot = routing_snapshot(dict(relay, mode="direct"))
    _mode, generation, pro_available, _active, _focused, _pro_active, _button_active = snapshot
    sync_android_links(config, dict(relay, mode="direct"))
    current = relay_command(config, "status")
    if not routing_matches(dict(relay, mode="direct"),
                           dict(current, mode="direct")):
        return None, current
    return (generation, pro_available), current


def relay_command(config, command):
    control_socket = config["CONTROL_SOCKET"]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3.0)
            client.connect(control_socket)
            client.sendall((command + "\n").encode("ascii"))
            response = client.recv(65536)
    except OSError as error:
        raise ModeError(f"pen relay is unavailable: {error}") from error

    if not response:
        raise ModeError("pen relay returned an empty response")
    result = json.loads(response.decode("utf-8"))
    if not result.get("ok"):
        raise ModeError(result.get("error", "pen relay command failed"))
    return result


def desktop_mode(config):
    relay = relay_command(config, "desktop")
    if not waydroid_running():
        remove_owned_android_links(config)
        return relay
    try:
        return reconcile_android_links(config, relay)
    except Exception:
        try:
            relay_command(config, "deactivate-pro")
        except Exception as release_error:
            print(f"relay Pro release failed: {release_error}", file=sys.stderr)
        raise


def direct_mode(config):
    try:
        relay = relay_command(config, "status")
        for _attempt in range(3):
            prepared, current = prepare_direct_links(config, relay)
            if prepared is None:
                relay = current
                continue
            generation, pro_available = prepared
            try:
                return relay_command(
                    config,
                    f"direct {generation} {int(pro_available)}",
                )
            except ModeError:
                relay = relay_command(config, "status")
        raise ModeError("pen capability changed repeatedly during direct switch")
    except Exception:
        rollback_to_desktop(config)
        raise


def sync_mode(config):
    relay = relay_command(config, "status")
    if not waydroid_running():
        # A stopped container cannot be inspected or relinked, but the relay
        # must stop writing Pro events into a stale Android channel.  The
        # container start/stop drop-in runs sync again when inspection is
        # possible.
        return relay_command(config, "deactivate-pro")
    try:
        return reconcile_android_links(config, relay)
    except Exception:
        if relay.get("mode") == "direct":
            rollback_to_desktop(config)
        else:
            try:
                relay_command(config, "deactivate-pro")
            except Exception as release_error:
                print(
                    f"relay Pro release failed: {release_error}",
                    file=sys.stderr,
                )
        raise


def focus_mode(config, focused):
    focused = bool(focused)
    relay = relay_command(config, "status")
    if focused:
        if not waydroid_running():
            raise ModeError("Waydroid is not running")
        # Prepare the side channel before enabling forwarding.  For an
        # ordinary pen the relay reports the route only after focus is set, so
        # predict that one field for the preflight link transaction.
        predicted = dict(relay, waydroid_focused=True)
        if (predicted.get("active_pen") == "m80p" and
                predicted.get("mode") == "desktop"):
            predicted["android_button_active"] = True
        sync_android_links(config, predicted)
    try:
        relay = relay_command(config, f"focus {int(focused)}")
        # Focus changes are the only state changes that alter the ordinary
        # button side-channel target.  Reconcile explicitly; link-state.path
        # intentionally does not watch focus/map churn.
        if waydroid_running():
            relay = reconcile_android_links(config, relay)
        return relay
    except Exception:
        if focused:
            try:
                relay_command(config, "focus 0")
                if waydroid_running():
                    reconcile_android_links(config, relay_command(config, "status"))
            except Exception:
                pass
        raise


def status(config):
    try:
        relay = relay_command(config, "status")
    except ModeError as error:
        relay = {"ok": False, "error": str(error), "mode": "unavailable"}
    result = {
        "mode": relay.get("mode"),
        "relay": relay,
        "android_link": android_readlink(config["ANDROID_LINK"]),
        "android_gesture_link": android_readlink(
            config["ANDROID_GESTURE_LINK"]
        ),
        "waydroid_running": waydroid_running(),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def set_mapping(config, arguments):
    if len(arguments) == 1 and arguments[0] == "unmap":
        return relay_command(config, "unmap")
    if len(arguments) != 5 or arguments[0] != "map":
        raise ModeError("usage: waydroid-pen-mode map X Y WIDTH HEIGHT")
    try:
        values = [float(value) for value in arguments[1:]]
    except ValueError as error:
        raise ModeError("mapping values must be numbers") from error
    if not all(math.isfinite(value) for value in values):
        raise ModeError("mapping values must be finite")
    x, y, width, height = values
    if width <= 0 or height <= 0:
        raise ModeError("mapping width and height must be positive")
    if x < 0 or y < 0 or x + width > 1 or y + height > 1:
        raise ModeError("mapping must fit inside the display")
    command = "map " + " ".join(f"{value:.9f}" for value in values)
    return relay_command(config, command)


def main():
    if os.geteuid() != 0:
        raise ModeError("must run as root")
    if len(sys.argv) < 2:
        raise ModeError(
            "usage: waydroid-pen-mode "
            "{direct|desktop|sync|focus|status|map|unmap}"
        )

    config = load_config()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        command = sys.argv[1]
        if command == "direct":
            if len(sys.argv) != 2:
                raise ModeError("usage: waydroid-pen-mode direct")
            result = direct_mode(config)
            print(f"direct {result.get('device', '')}".rstrip())
        elif command == "desktop":
            if len(sys.argv) != 2:
                raise ModeError("usage: waydroid-pen-mode desktop")
            result = desktop_mode(config)
            print(f"desktop {result.get('device', '')}".rstrip())
        elif command == "sync":
            if len(sys.argv) != 2:
                raise ModeError("usage: waydroid-pen-mode sync")
            result = sync_mode(config)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif command == "focus":
            if len(sys.argv) != 3 or sys.argv[2] not in {"0", "1"}:
                raise ModeError("usage: waydroid-pen-mode focus {0|1}")
            result = focus_mode(config, sys.argv[2] == "1")
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        elif command == "status":
            if len(sys.argv) != 2:
                raise ModeError("usage: waydroid-pen-mode status")
            status(config)
        elif command in {"map", "unmap"}:
            result = set_mapping(config, sys.argv[1:])
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            raise ModeError(
                "usage: waydroid-pen-mode "
                "{direct|desktop|sync|focus|status|map|unmap}"
            )


if __name__ == "__main__":
    try:
        main()
    except (ModeError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"waydroid-pen-mode: {error}", file=sys.stderr)
        sys.exit(1)
