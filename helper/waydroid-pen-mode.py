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
    "ANDROID_DEVICE": "/dev/waydroid_pen",
    "ANDROID_LINK": "/dev/input/event4",
    "ANDROID_LINK_TARGET": "../waydroid_pen",
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


def android_links(config):
    return (
        {
            "device": config["ANDROID_DEVICE"],
            "link": config["ANDROID_LINK"],
            "target": config["ANDROID_LINK_TARGET"],
            "capability": "pen",
        },
        {
            "device": config["ANDROID_GESTURE_DEVICE"],
            "link": config["ANDROID_GESTURE_LINK"],
            "target": config["ANDROID_GESTURE_LINK_TARGET"],
            "capability": "pro",
        },
    )


def inspect_android_link(spec):
    target = android_readlink(spec["link"])
    if target == spec["target"]:
        return "owned", target
    if target is not None:
        return "foreign", target
    if android_path_exists(spec["link"]):
        return "foreign", "<non-symlink>"
    return "missing", None


def remove_owned_android_links(config):
    if not waydroid_running():
        return
    for spec in android_links(config):
        state, _target = inspect_android_link(spec)
        if state == "owned":
            waydroid_shell("unlink", spec["link"], check=False)


def sync_android_links(config, pen_required, pro_available):
    if not waydroid_running():
        raise ModeError("Waydroid is not running")

    specs = android_links(config)
    required = {
        spec["capability"]
        for spec in specs
        if (spec["capability"] == "pen" and pen_required)
        or (spec["capability"] == "pro" and pro_available)
    }
    states = {}
    for spec in specs:
        state, target = inspect_android_link(spec)
        if state == "foreign" and spec["capability"] in required:
            raise ModeError(
                f"refusing to replace Android link {spec['link']} -> {target}"
            )
        states[spec["capability"]] = state

    for spec in specs:
        if spec["capability"] not in required:
            continue
        probe = waydroid_shell("test", "-c", spec["device"], check=False)
        if probe.returncode != 0:
            raise ModeError(f"Waydroid device is missing: {spec['device']}")

    for spec in specs:
        if spec["capability"] not in required and states[spec["capability"]] == "owned":
            waydroid_shell("unlink", spec["link"])

    created = []
    try:
        for spec in specs:
            if spec["capability"] not in required:
                continue
            if states[spec["capability"]] == "owned":
                continue
            waydroid_shell("ln", "-s", spec["target"], spec["link"])
            created.append(spec)
    except Exception:
        for spec in reversed(created):
            waydroid_shell("unlink", spec["link"], check=False)
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
    return mode, generation, pro_available


def routing_matches(left, right):
    return routing_snapshot(left) == routing_snapshot(right)


def android_pro_should_be_active(relay):
    _mode, _generation, pro_available = routing_snapshot(relay)
    focused = relay.get("waydroid_focused")
    if not isinstance(focused, bool):
        raise ModeError("pen relay returned an invalid focus state")
    return pro_available and focused


def android_pro_is_active(relay):
    active = relay.get("android_pro_active")
    if not isinstance(active, bool):
        raise ModeError("pen relay returned an invalid Android Pro state")
    return active


def prepare_android_links(config, relay):
    mode, generation, pro_available = routing_snapshot(relay)
    sync_android_links(config, mode == "direct", pro_available)
    current = relay_command(config, "status")
    if not routing_matches(relay, current):
        return None, current
    return (generation, pro_available), current


def reconcile_android_links(config, relay):
    for _attempt in range(3):
        prepared, current = prepare_android_links(config, relay)
        if prepared is None:
            relay = current
            continue
        generation, _pro_available = prepared
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
    generation, pro_available = capability_snapshot(relay)
    sync_android_links(config, True, pro_available)
    current = relay_command(config, "status")
    if not capability_matches(relay, current):
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
        # Create event5 before enabling the relay's Android side channel.
        relay = reconcile_android_links(config, relay)
    relay = relay_command(config, f"focus {int(focused)}")
    if focused:
        relay = reconcile_android_links(config, relay)
    return relay


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
