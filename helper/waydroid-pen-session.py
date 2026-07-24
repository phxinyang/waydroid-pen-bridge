#!/usr/bin/python3

import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT_HELPER = "/usr/local/libexec/waydroid-pen-mode"
POLICIES = {"auto", "waydroid", "desktop"}
SOURCE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
SOURCE_EPOCH_PATTERN = re.compile(
    r"(?:gnome|kde)_(\d{13,16})_(\d{1,16})\Z"
)
TOKEN_SCALE = 1_000_000_000


class SessionError(RuntimeError):
    pass


class StaleContext(SessionError):
    pass


def session_paths():
    home = Path.home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    state_home = Path(
        os.environ.get("XDG_STATE_HOME", home / ".local" / "state")
    )
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        lock_root = Path(runtime)
    else:
        lock_root = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    return {
        "policy": config_home / "waydroid-pen-mode" / "policy",
        "state": state_home / "waydroid-pen-mode" / "session.json",
        "lock": lock_root / "waydroid-pen-mode" / "session.lock",
    }


def write_atomic(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC,
        mode,
    )
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
    finally:
        os.close(fd)
    os.replace(temporary, path)
    os.chmod(path, mode)


def write_json(path, value):
    write_atomic(
        path,
        (json.dumps(value, sort_keys=True) + "\n").encode("utf-8"),
    )


def load_json(path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return default
    return value if isinstance(value, dict) else default


def load_policy(path):
    try:
        policy = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "auto"
    return policy if policy in POLICIES else "auto"


def save_policy(path, policy):
    if policy not in POLICIES:
        raise SessionError(f"invalid pen policy: {policy}")
    write_atomic(path, (policy + "\n").encode("utf-8"))


def parse_flag(value, name):
    if value not in {"0", "1"}:
        raise SessionError(f"{name} must be 0 or 1")
    return value == "1"


def validate_mapping(values):
    if values is None:
        return None
    if len(values) != 4:
        raise SessionError("mapping needs X Y WIDTH HEIGHT")
    try:
        mapping = tuple(float(value) for value in values)
    except ValueError as error:
        raise SessionError("mapping values must be numbers") from error
    if not all(math.isfinite(value) for value in mapping):
        raise SessionError("mapping values must be finite")
    x, y, width, height = mapping
    if width <= 0 or height <= 0:
        raise SessionError("mapping width and height must be positive")
    if x < 0 or y < 0 or x + width > 1 or y + height > 1:
        raise SessionError("mapping must fit inside the display")
    return mapping


def make_context(source, generation, focused, overview, mapping):
    if not SOURCE_PATTERN.fullmatch(source):
        raise SessionError("invalid desktop context source")
    try:
        generation = int(generation)
    except (TypeError, ValueError) as error:
        raise SessionError("context generation must be an integer") from error
    if generation < 0:
        raise SessionError("context generation must not be negative")
    mapping = validate_mapping(mapping)
    return {
        "source": source,
        "generation": generation,
        "waydroid_focused": bool(focused),
        "overview": bool(overview),
        "mapping": list(mapping) if mapping is not None else None,
    }


def parse_context_arguments(arguments):
    if len(arguments) not in {5, 8}:
        raise SessionError(
            "usage: waydroid-pen-session context "
            "SOURCE GENERATION FOCUSED OVERVIEW {none|X Y WIDTH HEIGHT}"
        )
    source, generation, focused, overview = arguments[:4]
    mapping_arguments = arguments[4:]
    if mapping_arguments == ["none"]:
        mapping = None
    elif len(mapping_arguments) == 4:
        mapping = mapping_arguments
    else:
        raise SessionError(
            "usage: waydroid-pen-session context "
            "SOURCE GENERATION FOCUSED OVERVIEW {none|X Y WIDTH HEIGHT}"
        )
    return make_context(
        source,
        generation,
        parse_flag(focused, "focused"),
        parse_flag(overview, "overview"),
        mapping,
    )


def context_token(context):
    parts = [
        "ctx",
        context["source"],
        str(context["generation"]),
        str(int(context["waydroid_focused"])),
        str(int(context["overview"])),
    ]
    mapping = context.get("mapping")
    if mapping is None:
        parts.append("none")
    else:
        parts.extend(str(round(value * TOKEN_SCALE)) for value in mapping)
    return ".".join(parts)


def parse_context_token(token):
    parts = token.split(".")
    if len(parts) not in {6, 9} or parts[0] != "ctx":
        raise SessionError("invalid desktop context token")
    source, generation, focused, overview = parts[1:5]
    if parts[5:] == ["none"]:
        mapping = None
    elif len(parts) == 9:
        try:
            mapping = [int(value) / TOKEN_SCALE for value in parts[5:]]
        except ValueError as error:
            raise SessionError("invalid desktop context token") from error
    else:
        raise SessionError("invalid desktop context token")
    return make_context(
        source,
        generation,
        parse_flag(focused, "focused"),
        parse_flag(overview, "overview"),
        mapping,
    )


def default_context():
    return make_context("session", 0, False, False, None)


def source_order(source):
    if not isinstance(source, str):
        return None
    match = SOURCE_EPOCH_PATTERN.fullmatch(source)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), source


def accept_context(previous, incoming):
    if not isinstance(previous, dict):
        return
    previous_source = previous.get("source")
    if previous_source != incoming["source"]:
        previous_order = source_order(previous_source)
        incoming_order = source_order(incoming["source"])
        if previous_order is not None and (
            incoming_order is None or incoming_order <= previous_order
        ):
            raise StaleContext("stale desktop context source")
        return
    previous_generation = previous.get("generation")
    if not isinstance(previous_generation, int):
        return
    if incoming["generation"] < previous_generation:
        raise StaleContext("stale desktop context generation")
    if incoming["generation"] == previous_generation and incoming != previous:
        raise SessionError("conflicting desktop context generation")


def desired_mode(policy, context):
    if policy == "waydroid":
        return "direct"
    if policy == "desktop":
        return "desktop"
    if context["overview"]:
        return "desktop"
    return "direct" if context["waydroid_focused"] else "desktop"


def desired_android_focus(context):
    return bool(context["waydroid_focused"] and not context["overview"])


def root_command(arguments, *, check=True):
    result = subprocess.run(
        ["/usr/bin/sudo", "-n", ROOT_HELPER, *arguments],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise SessionError(message or "root pen helper failed")
    return result


def query_root_status():
    result = root_command(["status"])
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SessionError("root pen helper returned invalid JSON") from error
    if not isinstance(status, dict):
        raise SessionError("root pen helper returned invalid JSON")
    return status


def relay_instance(root_status):
    relay = root_status.get("relay")
    instance = relay.get("instance_id") if isinstance(relay, dict) else None
    if not isinstance(instance, str) or not instance:
        raise SessionError("pen relay returned an invalid instance id")
    return instance


def relay_waydroid_focused(root_status):
    relay = root_status.get("relay")
    focused = relay.get("waydroid_focused") if isinstance(relay, dict) else None
    return focused if isinstance(focused, bool) else None


def apply_context(policy, context):
    mode = desired_mode(policy, context)
    focused = desired_android_focus(context)
    if not focused:
        root_command(["focus", "0"])
    if mode == "direct":
        mapping = context.get("mapping")
        if mapping is None:
            root_command(["unmap"])
        else:
            root_command(
                ["map", *(f"{value:.9f}" for value in mapping)]
            )
        root_command(["direct"])
    else:
        root_command(["desktop"])
    if focused:
        root_command(["focus", "1"])
    return mode


def apply_verified_context(policy, context):
    desired = desired_mode(policy, context)
    focused = desired_android_focus(context)
    for _attempt in range(3):
        before = query_root_status()
        before_instance = relay_instance(before)
        applied_mode = apply_context(policy, context)
        after = query_root_status()
        after_instance = relay_instance(after)
        if (
            before_instance == after_instance
            and applied_mode == desired
            and after.get("mode") == desired
            and relay_waydroid_focused(after) == focused
        ):
            return applied_mode, after_instance
    raise SessionError("pen relay changed repeatedly while applying context")


def reconcile(paths, policy, context, state):
    state.update(
        {
            "policy": policy,
            "context": context,
            "desired_mode": desired_mode(policy, context),
            "updated_at_ns": time.time_ns(),
        }
    )
    try:
        applied_mode, instance = apply_verified_context(policy, context)
        state["applied_mode"] = applied_mode
        state["relay_instance"] = instance
        state["last_error"] = None
    except Exception as error:
        state["last_error"] = str(error)
        write_json(paths["state"], state)
        raise
    write_json(paths["state"], state)
    return state


def reapply_saved(paths, policy, context, state):
    root_status = query_root_status()
    instance = relay_instance(root_status)
    if state.get("relay_instance") == instance:
        return state

    desired = desired_mode(policy, context)
    focused = desired_android_focus(context)
    if (
        root_status.get("mode") == desired
        and relay_waydroid_focused(root_status) == focused
    ):
        state.update(
            {
                "policy": policy,
                "context": context,
                "desired_mode": desired,
                "applied_mode": desired,
                "relay_instance": instance,
                "last_error": None,
                "updated_at_ns": time.time_ns(),
            }
        )
        write_json(paths["state"], state)
        return state
    return reconcile(paths, policy, context, state)


def status(paths):
    policy = load_policy(paths["policy"])
    state = load_json(paths["state"], {})
    context = state.get("context")
    if not isinstance(context, dict):
        context = default_context()
    state.update(
        {
            "policy": policy,
            "context": context,
            "desired_mode": desired_mode(policy, context),
        }
    )
    result = root_command(["status"], check=False)
    if result.returncode == 0:
        try:
            state["root"] = json.loads(result.stdout)
        except json.JSONDecodeError:
            state["root"] = {"error": "root helper returned invalid JSON"}
    else:
        state["root"] = {
            "error": result.stderr.strip() or result.stdout.strip()
        }
    print(json.dumps(state, ensure_ascii=False, sort_keys=True))


def main():
    if len(sys.argv) < 2:
        raise SessionError(
            "usage: waydroid-pen-session "
            "{policy|context|apply|reapply|status}"
        )
    paths = session_paths()
    paths["lock"].parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(paths["lock"].parent, 0o700)
    with paths["lock"].open("w", encoding="utf-8") as lock_file:
        os.chmod(paths["lock"], 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        command = sys.argv[1]
        if command == "status":
            if len(sys.argv) != 2:
                raise SessionError("usage: waydroid-pen-session status")
            status(paths)
            return

        policy = load_policy(paths["policy"])
        state = load_json(paths["state"], {})
        context = state.get("context")
        if not isinstance(context, dict):
            context = default_context()

        if command == "reapply":
            if len(sys.argv) != 2:
                raise SessionError("usage: waydroid-pen-session reapply")
            state = reapply_saved(paths, policy, context, state)
            print(json.dumps(state, ensure_ascii=False, sort_keys=True))
            return
        if command == "policy":
            if len(sys.argv) != 3 or sys.argv[2] not in POLICIES:
                raise SessionError(
                    "usage: waydroid-pen-session policy "
                    "{auto|waydroid|desktop}"
                )
            policy = sys.argv[2]
            save_policy(paths["policy"], policy)
        elif command == "context":
            context = parse_context_arguments(sys.argv[2:])
            accept_context(state.get("context"), context)
        elif command == "apply":
            if len(sys.argv) != 3:
                raise SessionError("usage: waydroid-pen-session apply TOKEN")
            context = parse_context_token(sys.argv[2])
            accept_context(state.get("context"), context)
        else:
            raise SessionError(
                "usage: waydroid-pen-session "
                "{policy|context|apply|reapply|status}"
            )

        state = reconcile(paths, policy, context, state)
        print(json.dumps(state, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except StaleContext as error:
        print(f"waydroid-pen-session: {error}", file=sys.stderr)
    except (OSError, SessionError, subprocess.SubprocessError) as error:
        print(f"waydroid-pen-session: {error}", file=sys.stderr)
        sys.exit(1)
