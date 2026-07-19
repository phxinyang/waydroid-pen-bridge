#!/usr/bin/python3

import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


CONFIG_PATH = Path("/etc/waydroid-pen-mode.conf")
LOCK_PATH = Path("/run/lock/waydroid-pen-mode.lock")

DEFAULTS = {
    "CONTROL_SOCKET": "/run/waydroid-pen-mode/control.sock",
    "ANDROID_DEVICE": "/dev/waydroid_pen",
    "ANDROID_LINK": "/dev/input/event4",
    "ANDROID_LINK_TARGET": "../waydroid_pen",
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
    )


def waydroid_shell(*arguments, check=True, capture=False):
    return run(
        ["/usr/bin/waydroid", "shell", "--", *arguments],
        check=check,
        capture=capture,
    )


def waydroid_running():
    result = run(
        ["/usr/bin/waydroid", "status"],
        check=False,
        capture=True,
    )
    return result.returncode == 0 and "Container:\tRUNNING" in result.stdout


def android_readlink(link_path):
    if not waydroid_running():
        return None
    result = waydroid_shell("readlink", link_path, check=False, capture=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def remove_android_link(config):
    link_path = config["ANDROID_LINK"]
    expected = config["ANDROID_LINK_TARGET"]
    if android_readlink(link_path) == expected:
        waydroid_shell("unlink", link_path, check=False)


def ensure_android_link(config):
    if not waydroid_running():
        raise ModeError("Waydroid is not running")

    device_path = config["ANDROID_DEVICE"]
    probe = waydroid_shell("test", "-c", device_path, check=False)
    if probe.returncode != 0:
        raise ModeError(f"Waydroid device is missing: {device_path}")

    link_path = config["ANDROID_LINK"]
    expected = config["ANDROID_LINK_TARGET"]
    target = android_readlink(link_path)
    if target == expected:
        return
    if target is not None:
        raise ModeError(f"refusing to replace Android link {link_path} -> {target}")
    waydroid_shell("ln", "-s", expected, link_path)


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
    remove_android_link(config)
    return relay_command(config, "desktop")


def direct_mode(config):
    relay_command(config, "direct")
    try:
        ensure_android_link(config)
    except Exception:
        try:
            relay_command(config, "desktop")
        except Exception as rollback_error:
            print(f"relay rollback failed: {rollback_error}", file=sys.stderr)
        raise
    return relay_command(config, "status")


def status(config):
    try:
        relay = relay_command(config, "status")
    except ModeError as error:
        relay = {"ok": False, "error": str(error), "mode": "unavailable"}
    result = {
        "mode": relay.get("mode"),
        "relay": relay,
        "android_link": android_readlink(config["ANDROID_LINK"]),
        "waydroid_running": waydroid_running(),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def main():
    if os.geteuid() != 0:
        raise ModeError("must run as root")
    if len(sys.argv) != 2 or sys.argv[1] not in {"direct", "desktop", "status"}:
        raise ModeError("usage: waydroid-pen-mode {direct|desktop|status}")

    config = load_config()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        command = sys.argv[1]
        if command == "direct":
            result = direct_mode(config)
            print(f"direct {result.get('device', '')}".rstrip())
        elif command == "desktop":
            result = desktop_mode(config)
            print(f"desktop {result.get('device', '')}".rstrip())
        else:
            status(config)


if __name__ == "__main__":
    try:
        main()
    except (ModeError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"waydroid-pen-mode: {error}", file=sys.stderr)
        sys.exit(1)
