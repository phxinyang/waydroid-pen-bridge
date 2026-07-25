#!/usr/bin/python3

"""Route the two stable Xiaomi pen nodes without changing their protocol.

The THP driver keeps an M80p and a P81c uinput node alive for its whole
lifetime.  This relay mirrors that contract: both model proxies are created
once, only the model which is producing a live frame is written, and a model
switch releases the old proxy before the new one is selected.
"""

import fcntl
import json
import math
import os
from pathlib import Path
import selectors
import signal
import socket
import struct
import time
import uuid


CONFIG_PATH = Path("/etc/waydroid-pen-mode.conf")

DEFAULTS = {
    "DEVICE_NAME": "NVTCapacitivePenM80p",
    "DEVICE_PHYS": "input/pen",
    "PRO_DEVICE_NAME": "NVTCapacitivePenP81c",
    "PRO_DEVICE_PHYS": "input/pen_p81c",
    "M80P_PROXY_PHYS": "waydroid-pen-m80p",
    "P81C_PROXY_PHYS": "waydroid-pen-p81c",
    "ANDROID_M80P_PROXY_PHYS": "waydroid-android-pen-m80p",
    "ANDROID_P81C_PROXY_PHYS": "waydroid-android-pen-p81c",
    # Legacy names are accepted while an old relay is being replaced.  They
    # are never selected as physical sources.
    "PROXY_PHYS": "waydroid-pen-relay",
    "ANDROID_PROXY_PHYS": "waydroid-pen-android",
    "GESTURE_DEVICE_NAME": "Xiaomi Focus Pen Pro Gestures",
    "GESTURE_DEVICE_PHYS": "input/pen_p81c/gestures",
    "GESTURE_PROXY_PHYS": "waydroid-gesture-relay",
    "ANDROID_GESTURE_PROXY_PHYS": "waydroid-gesture-android",
    "ANDROID_BUTTON_PROXY_PHYS": "waydroid-pen-buttons",
    "DIRECT_Y_MIN": "0",  # kept for old config files; source ranges win
    "CONTROL_SOCKET": "/run/waydroid-pen-mode/control.sock",
    "STATE_PATH": "/run/waydroid-pen-mode/state.json",
    "LINK_STATE_PATH": "/run/waydroid-pen-mode/link-state.json",
}

BUS_VIRTUAL = 0x06
# Kept as a public compatibility constant for older callers/tests.  Physical
# sources are deliberately accepted only when they are BUS_VIRTUAL below.
BUS_USB = 0x03
VENDOR_ID = 0x2717
PRODUCT_ID = 0x3654
GESTURE_PRODUCT_ID = 0x3655
PRO_GESTURE_VENDOR_ID = 0x0022
PRO_GESTURE_PRODUCT_ID = 0x5081
DEVICE_VERSION = 1

MODEL_M80P = "m80p"
MODEL_P81C = "p81c"
PEN_MODELS = (MODEL_M80P, MODEL_P81C)

EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03
SYN_REPORT = 0
BTN_LEFT = 0x110
BTN_TOOL_PEN = 0x140
BTN_TOOL_MOUSE = 0x145
BTN_TOUCH = 0x14A
BTN_STYLUS = 0x14B
BTN_STYLUS2 = 0x14C
BTN_TRIGGER = 0x120
BTN_6 = 0x106
BTN_7 = 0x107
BTN_8 = 0x108
BTN_9 = 0x109
KEY_WAKEUP = 143
ORDINARY_BUTTON_CODES = (BTN_STYLUS, BTN_STYLUS2)
PRO_GESTURE_CODES = (BTN_6, BTN_7, BTN_8, BTN_9)
DESKTOP_GESTURE_KEYS = PRO_GESTURE_CODES
ANDROID_GESTURE_KEYS = PRO_GESTURE_CODES
ANDROID_BUTTON_KEYS = ORDINARY_BUTTON_CODES
REL_X = 0x00
REL_Y = 0x01
ABS_X = 0x00
ABS_Y = 0x01
ABS_BRAKE = 0x0A
ABS_PRESSURE = 0x18
ABS_DISTANCE = 0x19
ABS_TILT_X = 0x1A
ABS_TILT_Y = 0x1B
INPUT_PROP_POINTER = 0x00
INPUT_PROP_DIRECT = 0x01

M80P_PRESSURE_MAX = 8191
P81C_PRESSURE_MAX = 16383
PEN_X_MAX = 30479
PEN_Y_MAX = 20319

PEN_PROFILES = {
    MODEL_M80P: {
        "name": "NVTCapacitivePenM80p",
        "phys": "input/pen",
        "proxy_phys": "waydroid-pen-m80p",
        "pressure_max": M80P_PRESSURE_MAX,
        "has_stylus_buttons": True,
        "has_brake": False,
    },
    MODEL_P81C: {
        "name": "NVTCapacitivePenP81c",
        "phys": "input/pen_p81c",
        "proxy_phys": "waydroid-pen-p81c",
        "pressure_max": P81C_PRESSURE_MAX,
        "has_stylus_buttons": False,
        "has_brake": True,
    },
}

# Public description retained for tooling that inspects proxy capabilities.
PEN_AXIS_SPECS = (
    (ABS_X, 0, PEN_X_MAX, 113),
    (ABS_Y, 0, PEN_Y_MAX, 113),
    (ABS_BRAKE, 0, 360, 0),
    (ABS_PRESSURE, 0, P81C_PRESSURE_MAX, 0),
    (ABS_DISTANCE, 0, 1, 0),
    (ABS_TILT_X, -60, 60, 0),
    (ABS_TILT_Y, -60, 60, 0),
)

ABS_CNT = 0x40
INPUT_ABSINFO = struct.Struct("@6i")
INPUT_EVENT = struct.Struct("@llHHi")
UINPUT_SETUP = struct.Struct("@HHHH80sI")
UINPUT_ABS_SETUP = struct.Struct("@H2x6i")


def _ioc(direction, type_, number, size):
    return (direction << 30) | (size << 16) | (type_ << 8) | number


def _io(type_, number):
    return _ioc(0, type_, number, 0)


def _ior(type_, number, size):
    return _ioc(2, type_, number, size)


def _iow(type_, number, size):
    return _ioc(1, type_, number, size)


def evio_get_abs(axis):
    return _ior(ord("E"), 0x40 + axis, INPUT_ABSINFO.size)


UI_DEV_CREATE = _io(ord("U"), 1)
UI_DEV_DESTROY = _io(ord("U"), 2)
UI_DEV_SETUP = _iow(ord("U"), 3, UINPUT_SETUP.size)
UI_ABS_SETUP = _iow(ord("U"), 4, UINPUT_ABS_SETUP.size)
UI_SET_EVBIT = _iow(ord("U"), 100, struct.calcsize("I"))
UI_SET_KEYBIT = _iow(ord("U"), 101, struct.calcsize("I"))
UI_SET_ABSBIT = _iow(ord("U"), 103, struct.calcsize("I"))
UI_SET_RELBIT = _iow(ord("U"), 102, struct.calcsize("I"))
UI_SET_PHYS = _iow(ord("U"), 108, struct.calcsize("P"))
UI_SET_PROPBIT = _iow(ord("U"), 110, struct.calcsize("I"))


class RelayError(RuntimeError):
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


def _read_text(path, default=None):
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return default


def read_input_identity(event_path):
    device_path = event_path / "device"
    name = _read_text(device_path / "name")
    bustype = _read_text(device_path / "id" / "bustype")
    vendor = _read_text(device_path / "id" / "vendor")
    product = _read_text(device_path / "id" / "product")
    if None in (name, bustype, vendor, product):
        return None
    try:
        return {
            "name": name,
            "phys": _read_text(device_path / "phys", ""),
            "bustype": int(bustype, 16),
            "vendor": int(vendor, 16),
            "product": int(product, 16),
        }
    except ValueError:
        return None


def _proxy_physes(config):
    return {
        config["M80P_PROXY_PHYS"],
        config["P81C_PROXY_PHYS"],
        config["ANDROID_M80P_PROXY_PHYS"],
        config["ANDROID_P81C_PROXY_PHYS"],
        config["PROXY_PHYS"],
        config["ANDROID_PROXY_PHYS"],
        config["GESTURE_PROXY_PHYS"],
        config["ANDROID_GESTURE_PROXY_PHYS"],
        config["ANDROID_BUTTON_PROXY_PHYS"],
    }


def find_source_event(
    device_name,
    product_id,
    expected_phys,
    proxy_physes,
    sys_class_input=Path("/sys/class/input"),
    dev_input=Path("/dev/input"),
    vendor_id=VENDOR_ID,
    bustype=BUS_VIRTUAL,
):
    matches = []
    for event_path in sorted(sys_class_input.glob("event*")):
        identity = read_input_identity(event_path)
        if identity is None:
            continue
        if identity != {
            "name": device_name,
            "phys": expected_phys,
            "bustype": bustype,
            "vendor": vendor_id,
            "product": product_id,
        }:
            continue
        if identity["phys"] in proxy_physes:
            continue
        matches.append(dev_input / event_path.name)
    if len(matches) > 1:
        nodes = ", ".join(str(node) for node in matches)
        raise RelayError(f"ambiguous input source for {device_name}: {nodes}")
    return matches[0] if matches else None


def find_pen_sources(config, sys_class_input=Path("/sys/class/input"),
                     dev_input=Path("/dev/input")):
    return {
        MODEL_M80P: find_source_event(
            config["DEVICE_NAME"], PRODUCT_ID, config["DEVICE_PHYS"],
            _proxy_physes(config), sys_class_input, dev_input,
        ),
        MODEL_P81C: find_source_event(
            config["PRO_DEVICE_NAME"], PRODUCT_ID, config["PRO_DEVICE_PHYS"],
            _proxy_physes(config), sys_class_input, dev_input,
        ),
    }


def find_pen_source(config, pro_available, sys_class_input=Path("/sys/class/input"),
                    dev_input=Path("/dev/input")):
    model = MODEL_P81C if pro_available else MODEL_M80P
    return find_pen_sources(config, sys_class_input, dev_input)[model]


def find_gesture_source(config, sys_class_input=Path("/sys/class/input"),
                        dev_input=Path("/dev/input")):
    return find_source_event(
        config["GESTURE_DEVICE_NAME"], PRO_GESTURE_PRODUCT_ID,
        config["GESTURE_DEVICE_PHYS"], _proxy_physes(config),
        sys_class_input, dev_input, vendor_id=PRO_GESTURE_VENDOR_ID,
    )


def write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    os.chmod(path.parent, 0o755)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC,
                 0o644)
    try:
        os.fchmod(fd, 0o644)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
    finally:
        os.close(fd)
    os.replace(temporary, path)
    os.chmod(path, 0o644)


def read_abs_range(fd, axis, fallback):
    data = bytearray(INPUT_ABSINFO.size)
    try:
        fcntl.ioctl(fd, evio_get_abs(axis), data, True)
    except OSError:
        return fallback
    values = INPUT_ABSINFO.unpack(data)
    minimum, maximum = values[1], values[2]
    if maximum <= minimum:
        return fallback
    return minimum, maximum


def make_event(type_, code, value):
    return INPUT_EVENT.pack(0, 0, type_, code, value)


def make_abs_setup(code, minimum, maximum, resolution=0):
    return UINPUT_ABS_SETUP.pack(code, 0, minimum, maximum, 0, 0, resolution)


def map_axis_value(value, source_min, source_max, target_min, target_max):
    if source_max <= source_min:
        raise RelayError("invalid axis range")
    value = min(source_max, max(source_min, value))
    return target_min + round(
        (value - source_min) * (target_max - target_min)
        / (source_max - source_min)
    )


def transform_pen_events(
    data,
    *,
    ordinary=False,
    source_y_min=0,
    source_y_max=PEN_Y_MAX,
    target_y_min=None,
    target_y_max=None,
    pressure_max=None,
    suppress_buttons=(),
):
    """Copy a frame, optionally remapping Y and clamping native pressure.

    ``ordinary`` remains an accepted keyword for callers from the previous
    relay; it deliberately has no scaling behavior.  M80p pressure is never
    converted to the P81c range here.
    """
    del ordinary
    suppressed = set(suppress_buttons)
    if target_y_min is None:
        target_y_min = source_y_min
    if target_y_max is None:
        target_y_max = source_y_max
    events = []
    for offset in range(0, len(data), INPUT_EVENT.size):
        seconds, microseconds, event_type, code, value = INPUT_EVENT.unpack_from(
            data, offset
        )
        if event_type == EV_KEY and code in suppressed:
            continue
        if event_type == EV_ABS and code == ABS_PRESSURE and pressure_max is not None:
            value = min(pressure_max, max(0, value))
        if event_type == EV_ABS and code == ABS_Y:
            value = map_axis_value(
                value, source_y_min, source_y_max,
                target_y_min, target_y_max,
            )
        events.append(INPUT_EVENT.pack(seconds, microseconds, event_type, code,
                                       value))
    return b"".join(events)


class VirtualPen:
    def __init__(self, profile, phys=None):
        self.profile = dict(profile)
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_CLOEXEC)
        self.phys = phys or profile["proxy_phys"]
        self.has_state = False
        self.button_state = {code: False for code in ORDINARY_BUTTON_CODES}
        self.axis_codes = [ABS_X, ABS_Y, ABS_PRESSURE, ABS_DISTANCE,
                           ABS_TILT_X, ABS_TILT_Y]
        if profile["has_brake"]:
            self.axis_codes.append(ABS_BRAKE)
        self.key_codes = [BTN_TOOL_PEN, BTN_TOUCH]
        if profile["has_stylus_buttons"]:
            self.key_codes.extend(ORDINARY_BUTTON_CODES)
        else:
            # Mirror the driver's advertised P81c capabilities.  The driver
            # does not emit these keys, but Android/libinput sees the same ABI.
            self.key_codes.extend((KEY_WAKEUP, BTN_TRIGGER))
        try:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
            for key in self.key_codes:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, key)
            for axis in self.axis_codes:
                fcntl.ioctl(self.fd, UI_SET_ABSBIT, axis)
            fcntl.ioctl(self.fd, UI_SET_PROPBIT, INPUT_PROP_DIRECT)
            fcntl.ioctl(self.fd, UI_SET_PHYS, (self.phys + "\0").encode("ascii"))
            setup = UINPUT_SETUP.pack(
                BUS_VIRTUAL, VENDOR_ID, PRODUCT_ID, DEVICE_VERSION,
                profile["name"].encode("utf-8"), 0,
            )
            fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(self.fd, UI_SET_PHYS,
                        (self.phys + "\0").encode("ascii"))
            for axis in self.axis_codes:
                if axis == ABS_X:
                    minimum, maximum, resolution = 0, PEN_X_MAX, 113
                elif axis == ABS_Y:
                    minimum, maximum, resolution = 0, PEN_Y_MAX, 113
                elif axis == ABS_PRESSURE:
                    minimum, maximum, resolution = 0, profile["pressure_max"], 0
                elif axis == ABS_BRAKE:
                    minimum, maximum, resolution = 0, 360, 0
                elif axis == ABS_DISTANCE:
                    minimum, maximum, resolution = 0, 1, 0
                else:
                    minimum, maximum, resolution = -60, 60, 0
                fcntl.ioctl(self.fd, UI_ABS_SETUP,
                            make_abs_setup(axis, minimum, maximum, resolution))
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
            time.sleep(0.1)
        except Exception:
            os.close(self.fd)
            self.fd = -1
            raise

    def write(self, data):
        view = memoryview(data)
        while view:
            written = os.write(self.fd, view)
            view = view[written:]
        self.has_state = True

    def write_buttons(self, states):
        if not self.profile["has_stylus_buttons"]:
            return
        events = []
        for code in ORDINARY_BUTTON_CODES:
            pressed = bool(states.get(code, False))
            self.button_state[code] = pressed
            events.append(make_event(EV_KEY, code, int(pressed)))
        events.append(make_event(EV_SYN, SYN_REPORT, 0))
        self.write(b"".join(events))

    def release_buttons(self):
        if not self.profile["has_stylus_buttons"]:
            return
        events = []
        for code in ORDINARY_BUTTON_CODES:
            if not self.button_state.get(code):
                continue
            self.button_state[code] = False
            events.append(make_event(EV_KEY, code, 0))
        if events:
            events.append(make_event(EV_SYN, SYN_REPORT, 0))
            self.write(b"".join(events))

    def snapshot(self, keys, axes, x, y):
        events = []
        for code in self.key_codes:
            if code in ORDINARY_BUTTON_CODES:
                value = int(bool(keys.get(code, 0)))
            else:
                value = int(bool(keys.get(code, 0)))
            events.append(make_event(EV_KEY, code, value))
        for code in self.axis_codes:
            if code == ABS_X:
                value = x
            elif code == ABS_Y:
                value = y
            else:
                value = axes.get(code, 0) or 0
            events.append(make_event(EV_ABS, code, value))
        events.append(make_event(EV_SYN, SYN_REPORT, 0))
        return b"".join(events)

    def release(self):
        if not self.has_state:
            return
        events = [make_event(EV_KEY, code, 0) for code in self.key_codes]
        events.extend(make_event(EV_ABS, code, 0) for code in self.axis_codes
                       if code not in (ABS_X, ABS_Y))
        events.append(make_event(EV_SYN, SYN_REPORT, 0))
        try:
            self.write(b"".join(events))
        finally:
            self.has_state = False
            for code in self.button_state:
                self.button_state[code] = False

    def close(self):
        if self.fd < 0:
            return
        try:
            self.release()
        except OSError:
            pass
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)
            self.fd = -1


class VirtualGestureKeyboard:
    def __init__(self, name, phys, supported_codes, *, pointer=False,
                 vendor=VENDOR_ID, product=GESTURE_PRODUCT_ID):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_CLOEXEC)
        self.supported_codes = tuple(supported_codes)
        self.pressed = {code: False for code in self.supported_codes}
        self.pending = {}
        self.pointer = pointer
        try:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            for code in self.supported_codes:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
            if pointer:
                fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
                fcntl.ioctl(self.fd, UI_SET_RELBIT, REL_X)
                fcntl.ioctl(self.fd, UI_SET_RELBIT, REL_Y)
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, BTN_LEFT)
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, BTN_TOOL_MOUSE)
                fcntl.ioctl(self.fd, UI_SET_PROPBIT, INPUT_PROP_POINTER)
            fcntl.ioctl(self.fd, UI_SET_PHYS, (phys + "\0").encode("ascii"))
            setup = UINPUT_SETUP.pack(
                BUS_VIRTUAL, vendor, product, DEVICE_VERSION,
                name.encode("utf-8"), 0,
            )
            fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(self.fd, UI_SET_PHYS,
                        (phys + "\0").encode("ascii"))
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
            time.sleep(0.1)
        except Exception:
            os.close(self.fd)
            self.fd = -1
            raise

    def write(self, data):
        view = memoryview(data)
        while view:
            written = os.write(self.fd, view)
            view = view[written:]

    def feed(self, data, stream):
        pending = self.pending.setdefault(stream, [])
        for offset in range(0, len(data), INPUT_EVENT.size):
            seconds, microseconds, event_type, code, value = (
                INPUT_EVENT.unpack_from(data, offset)
            )
            if event_type == EV_KEY and code in self.pressed:
                if value not in (0, 1):
                    continue
                pressed = value == 1
                if self.pressed[code] == pressed:
                    continue
                self.pressed[code] = pressed
                pending.append(INPUT_EVENT.pack(
                    seconds, microseconds, EV_KEY, code, value))
            elif event_type == EV_SYN and code == SYN_REPORT and pending:
                pending.append(INPUT_EVENT.pack(
                    seconds, microseconds, EV_SYN, SYN_REPORT, 0))
                self.write(b"".join(pending))
                pending.clear()

    def set_key(self, code, pressed):
        if code not in self.pressed:
            raise RelayError(f"unsupported gesture key code: {code}")
        pressed = bool(pressed)
        if self.pressed[code] == pressed:
            return False
        self.pressed[code] = pressed
        self.write(b"".join((
            make_event(EV_KEY, code, int(pressed)),
            make_event(EV_SYN, SYN_REPORT, 0),
        )))
        return True

    def release(self):
        events = []
        for code, pressed in self.pressed.items():
            if pressed:
                self.pressed[code] = False
                events.append(make_event(EV_KEY, code, 0))
        self.pending.clear()
        if events:
            events.append(make_event(EV_SYN, SYN_REPORT, 0))
            self.write(b"".join(events))

    def release_keys(self, codes):
        """Release only a selected subset, preserving unrelated key state."""
        events = []
        for code in codes:
            if code not in self.pressed or not self.pressed[code]:
                continue
            self.pressed[code] = False
            events.append(make_event(EV_KEY, code, 0))
        self.pending.clear()
        if events:
            events.append(make_event(EV_SYN, SYN_REPORT, 0))
            self.write(b"".join(events))

    def close(self):
        if self.fd < 0:
            return
        try:
            self.release()
        except OSError:
            pass
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)
            self.fd = -1


class AndroidFrameMapper:
    X_MIN = 0
    X_MAX = PEN_X_MAX
    Y_MAX = PEN_Y_MAX

    def __init__(self, output, output_y_min=0, output_y_max=PEN_Y_MAX,
                 source_y_min=0, source_y_max=PEN_Y_MAX,
                 pressure_max=None):
        self.output = output
        self.output_y_min = output_y_min
        self.output_y_max = output_y_max
        self.source_y_min = source_y_min
        self.source_y_max = source_y_max
        self.pressure_max = pressure_max
        self.geometry = None
        self.events = []
        self.axes = {
            ABS_X: None, ABS_Y: None, ABS_BRAKE: 0, ABS_PRESSURE: 0,
            ABS_DISTANCE: 0, ABS_TILT_X: 0, ABS_TILT_Y: 0,
        }
        self.keys = {BTN_TOOL_PEN: 0, BTN_TOUCH: 0,
                     BTN_STYLUS: 0, BTN_STYLUS2: 0,
                     KEY_WAKEUP: 0, BTN_TRIGGER: 0}
        self.active = False

    def set_source_range(self, source_y_min, source_y_max, pressure_max=None):
        if source_y_max <= source_y_min:
            raise RelayError("invalid source Y range")
        changed = (source_y_min != self.source_y_min or
                   source_y_max != self.source_y_max or
                   pressure_max != self.pressure_max)
        if changed:
            self.release()
            self.source_y_min = source_y_min
            self.source_y_max = source_y_max
            self.pressure_max = pressure_max
            self.reset_source_state()

    # Compatibility alias used by the previous tests/callers.
    def set_source_y_min(self, source_y_min):
        self.set_source_range(source_y_min, self.source_y_max,
                              self.pressure_max)

    def set_geometry(self, geometry):
        if geometry is not None:
            x, y, width, height = geometry
            if not all(math.isfinite(value) for value in geometry):
                raise RelayError("mapping values must be finite")
            if width <= 0 or height <= 0:
                raise RelayError("mapping width and height must be positive")
            if x < 0 or y < 0 or x + width > 1 or y + height > 1:
                raise RelayError("mapping must fit inside the display")
            geometry = tuple(float(value) for value in geometry)
        if geometry == self.geometry:
            return
        self.release()
        self.geometry = geometry

    def reset_source_state(self):
        self.release()
        self.events.clear()
        for code in self.axes:
            self.axes[code] = None if code in (ABS_X, ABS_Y) else 0
        for code in self.keys:
            self.keys[code] = 0

    def release(self):
        if self.active:
            self.output.release()
        self.active = False

    def feed(self, data, enabled, suppress_keys=()):
        suppressed = set(suppress_keys)
        for offset in range(0, len(data), INPUT_EVENT.size):
            event = INPUT_EVENT.unpack_from(data, offset)
            _, _, event_type, code, value = event
            if event_type == EV_ABS and code in self.axes:
                self.axes[code] = value
            elif event_type == EV_KEY and code in self.keys:
                self.keys[code] = value
            self.events.append(event)
            if event_type == EV_SYN and code == SYN_REPORT:
                if enabled:
                    mapped = self._map_frame(suppressed)
                    if mapped:
                        self.output.write(mapped)
                elif self.active:
                    self.release()
                self.events.clear()

    def _map_frame(self, suppress_keys=()):
        x, y = self.axes[ABS_X], self.axes[ABS_Y]
        if x is None or y is None:
            return b""
        mapped = self._map_point(x, y)
        if mapped is None:
            self.release()
            return b""
        mapped_x, mapped_y = mapped
        if not self.active:
            self.active = True
            keys = dict(self.keys)
            for code in suppress_keys:
                if code in keys:
                    keys[code] = 0
            return self.output.snapshot(keys, self.axes, mapped_x, mapped_y)
        mapped_events = []
        for seconds, microseconds, event_type, code, value in self.events:
            key_codes = getattr(self.output, "key_codes", None)
            axis_codes = getattr(self.output, "axis_codes", None)
            if key_codes is not None or axis_codes is not None:
                if event_type == EV_KEY and key_codes is not None and code not in key_codes:
                    continue
                if event_type == EV_ABS and axis_codes is not None and code not in axis_codes:
                    continue
            if event_type == EV_KEY and code in suppress_keys:
                continue
            if event_type == EV_ABS and code == ABS_X:
                value = mapped_x
            elif event_type == EV_ABS and code == ABS_Y:
                value = mapped_y
            elif (event_type == EV_ABS and code == ABS_PRESSURE and
                  self.pressure_max is not None):
                value = min(self.pressure_max, max(0, value))
            mapped_events.append(INPUT_EVENT.pack(
                seconds, microseconds, event_type, code, value))
        return b"".join(mapped_events)

    def release_buttons(self):
        if hasattr(self.output, "release_buttons"):
            self.output.release_buttons()

    def _map_point(self, x, y):
        geometry = self.geometry
        # Full-display mapping used to go through float normalize/expand and
        # re-quantize every sample.  That alone makes Waydroid writing feel
        # softer and less precise than the desktop proxy path.
        if geometry is None or geometry == (0.0, 0.0, 1.0, 1.0):
            if (self.source_y_min != self.output_y_min or
                    self.source_y_max != self.output_y_max):
                y = map_axis_value(
                    y, self.source_y_min, self.source_y_max,
                    self.output_y_min, self.output_y_max,
                )
            return (
                min(self.X_MAX, max(self.X_MIN, x)),
                min(self.output_y_max, max(self.output_y_min, y)),
            )
        source_x = (x - self.X_MIN) / (self.X_MAX - self.X_MIN)
        source_y = (y - self.source_y_min) / (
            self.source_y_max - self.source_y_min)
        left, top, width, height = geometry
        if not (left <= source_x <= left + width):
            return None
        if not (top <= source_y <= top + height):
            return None
        target_x = round((source_x - left) / width * self.X_MAX)
        target_y = round(
            self.output_y_min + (source_y - top) / height *
            (self.output_y_max - self.output_y_min))
        return (min(self.X_MAX, max(self.X_MIN, target_x)),
                min(self.output_y_max, max(self.output_y_min, target_y)))


class PenRelay:
    def __init__(self, config):
        self.config = config
        self.selector = selectors.DefaultSelector()
        self.running = True
        self.mode = "desktop"
        self.sources = {
            model: {
                "node": None, "fd": None, "buffer": bytearray(),
                "y_min": 0, "y_max": PEN_Y_MAX,
                "pressure_min": 0,
                "pressure_max": PEN_PROFILES[model]["pressure_max"],
            }
            for model in PEN_MODELS
        }
        # Compatibility aliases are kept for status consumers; they always
        # describe the currently active source, never a scan-order choice.
        self.device = None
        self.device_fd = None
        self.input_buffer = bytearray()
        self.active_model = None
        self.gesture_device = None
        self.gesture_device_fd = None
        self.gesture_input_buffer = bytearray()
        self.pro_gesture_state = {code: False for code in PRO_GESTURE_CODES}
        self.ordinary_button_state = {code: False for code in ORDINARY_BUTTON_CODES}
        self.ordinary_button_route = None
        self.pro_available = False
        self.waydroid_focused = False
        self.android_pro_active = False
        self.android_button_active = False
        self.capability_generation = self._next_capability_generation()
        self.instance_id = uuid.uuid4().hex

        self.proxies = {
            MODEL_M80P: VirtualPen(
                {**PEN_PROFILES[MODEL_M80P],
                 "proxy_phys": config.get("M80P_PROXY_PHYS",
                                          PEN_PROFILES[MODEL_M80P]["proxy_phys"])},
            ),
            MODEL_P81C: VirtualPen(
                {**PEN_PROFILES[MODEL_P81C],
                 "proxy_phys": config.get("P81C_PROXY_PHYS",
                                          PEN_PROFILES[MODEL_P81C]["proxy_phys"])},
            ),
        }
        # Keep a second, permanently-created proxy for each model.  The
        # desktop proxy remains visible to libinput; the Android proxy is
        # marked LIBINPUT_IGNORE_DEVICE by udev and is used only in direct
        # Waydroid mode.  Sharing one proxy caused duplicate tablet frames.
        self.android_proxies = {
            MODEL_M80P: VirtualPen(
                {**PEN_PROFILES[MODEL_M80P],
                 "proxy_phys": config.get(
                     "ANDROID_M80P_PROXY_PHYS",
                     "waydroid-android-pen-m80p",
                 )},
            ),
            MODEL_P81C: VirtualPen(
                {**PEN_PROFILES[MODEL_P81C],
                 "proxy_phys": config.get(
                     "ANDROID_P81C_PROXY_PHYS",
                     "waydroid-android-pen-p81c",
                 )},
            ),
        }
        self.proxy_m80p = self.proxies[MODEL_M80P]
        self.proxy_p81c = self.proxies[MODEL_P81C]
        # Old attribute names point at M80p only for source compatibility;
        # routing code never uses them.
        self.proxy = self.proxy_m80p
        self.android_proxy = self.android_proxies[MODEL_M80P]
        self.mappers = {
            model: AndroidFrameMapper(
                self.android_proxies[model],
                pressure_max=PEN_PROFILES[model]["pressure_max"],
            )
            for model in PEN_MODELS
        }
        self.android_mapper = self.mappers[MODEL_M80P]

        # Ordinary M80p buttons need a keyboard-like Android side channel in
        # desktop+Waydroid focus mode.  It is distinct from Pro gestures.
        self.android_button_proxy = VirtualGestureKeyboard(
            "Xiaomi Focus Pen Buttons", config["ANDROID_BUTTON_PROXY_PHYS"],
            ANDROID_BUTTON_KEYS, product=GESTURE_PRODUCT_ID,
        )
        self.gesture_proxy = None
        self.android_gesture_proxy = None
        self.server = self._create_server(Path(config["CONTROL_SOCKET"]))
        self.selector.register(self.server, selectors.EVENT_READ, "control")
        self._write_state()
        self._write_link_state()

    def _next_capability_generation(self):
        try:
            previous = json.loads(Path(self.config["STATE_PATH"]).read_text(
                encoding="utf-8"))
            return int(previous.get("capability_generation", 0)) + 1
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 1

    def _create_server(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(4)
        server.setblocking(False)
        return server

    def _write_state(self):
        write_json_atomic(Path(self.config["STATE_PATH"]), self._state())

    def _write_link_state(self):
        # Keep this file limited to link-relevant capability fields.  The
        # generation advances on active-model changes as well as Pro changes,
        # so event4 is resynchronized without watching focus/map state.
        write_json_atomic(Path(self.config["LINK_STATE_PATH"]), {
            "instance_id": self.instance_id,
            "capability_generation": self.capability_generation,
            "pro_available": self.pro_available,
        })

    def _active_source(self):
        return self.sources[self.active_model] if self.active_model else None

    def _state(self):
        active_model = getattr(self, "active_model", None)
        sources = getattr(self, "sources", {})
        mappers = getattr(self, "mappers", {})
        return {
            "mode": self.mode,
            "active_pen": active_model,
            "device": str(self.device) if self.device else None,
            "devices": {
                model: str(sources[model]["node"])
                if model in sources and sources[model]["node"] else None
                for model in PEN_MODELS
            },
            "gesture_device": (str(self.gesture_device)
                               if self.gesture_device else None),
            "pro_available": self.pro_available,
            "waydroid_focused": self.waydroid_focused,
            "android_pro_active": self.android_pro_active,
            "android_button_active": self.android_button_active,
            "capability_generation": self.capability_generation,
            "instance_id": self.instance_id,
            "forwarding": self.mode in {"desktop", "direct"},
            "mapping": mappers[MODEL_M80P].geometry
            if MODEL_M80P in mappers else None,
            "proxy_pressure_ranges": {
                model: [0, PEN_PROFILES[model]["pressure_max"]]
                for model in PEN_MODELS
            },
            "source_y_ranges": {
                model: [sources[model]["y_min"], sources[model]["y_max"]]
                if model in sources else [0, PEN_Y_MAX]
                for model in PEN_MODELS
            },
        }

    def _response(self):
        return {"ok": True, **self._state()}

    def _update_pro_gesture_state(self, data):
        for offset in range(0, len(data), INPUT_EVENT.size):
            _s, _us, event_type, code, value = INPUT_EVENT.unpack_from(data, offset)
            if event_type == EV_KEY and code in self.pro_gesture_state and value in (0, 1):
                self.pro_gesture_state[code] = value == 1

    def _reset_pro_gesture_state(self):
        for code in self.pro_gesture_state:
            self.pro_gesture_state[code] = False

    def _update_ordinary_button_state(self, data):
        for offset in range(0, len(data), INPUT_EVENT.size):
            _s, _us, event_type, code, value = INPUT_EVENT.unpack_from(data, offset)
            if event_type == EV_KEY and code in self.ordinary_button_state and value in (0, 1):
                self.ordinary_button_state[code] = value == 1

    def _reset_ordinary_button_state(self):
        for code in self.ordinary_button_state:
            self.ordinary_button_state[code] = False
        for mapper in getattr(self, "mappers", {}).values():
            for code in ORDINARY_BUTTON_CODES:
                mapper.keys[code] = 0

    def _create_gesture_proxies(self):
        if self.gesture_proxy is not None:
            return
        self.gesture_proxy = VirtualGestureKeyboard(
            self.config["GESTURE_DEVICE_NAME"],
            self.config["GESTURE_PROXY_PHYS"],
            DESKTOP_GESTURE_KEYS, pointer=True,
        )
        try:
            self.android_gesture_proxy = VirtualGestureKeyboard(
                self.config["GESTURE_DEVICE_NAME"],
                self.config["ANDROID_GESTURE_PROXY_PHYS"],
                ANDROID_GESTURE_KEYS,
            )
        except Exception:
            self.gesture_proxy.close()
            self.gesture_proxy = None
            raise

    def _close_gesture_proxies(self):
        if self.gesture_proxy is not None:
            self.gesture_proxy.release()
            self.gesture_proxy.close()
        if self.android_gesture_proxy is not None:
            self.android_gesture_proxy.release()
            self.android_gesture_proxy.close()
        self.gesture_proxy = None
        self.android_gesture_proxy = None

    def _synthesize_desktop_pro_state(self):
        if self.gesture_proxy is None:
            return
        for code in PRO_GESTURE_CODES:
            if self.pro_gesture_state[code]:
                self.gesture_proxy.set_key(code, True)

    def _synthesize_android_pro_state(self):
        if self.android_gesture_proxy is None:
            return
        for code in PRO_GESTURE_CODES:
            if self.pro_gesture_state[code]:
                self.android_gesture_proxy.set_key(code, True)

    def _android_pro_should_be_active(self):
        # A gestures source may remain present while the ordinary M80p is the
        # active pen.  Android must only receive the path belonging to the
        # active physical pen; merely having a paired Pro device is not enough.
        return (
            self.active_model == MODEL_P81C
            and self.pro_available
            and self.waydroid_focused
        )

    def _set_android_pro_active(self, active, synthesize_pressed=False):
        active = bool(active)
        if active == self.android_pro_active:
            return False
        if active:
            if not self._android_pro_should_be_active() or self.android_gesture_proxy is None:
                raise RelayError("cannot activate Pro routing in the current state")
            self.android_pro_active = True
            if synthesize_pressed:
                self._synthesize_android_pro_state()
        else:
            if self.android_gesture_proxy is not None:
                self.android_gesture_proxy.release()
            self.android_pro_active = False
        return True

    def _desired_button_route(self):
        if self.active_model != MODEL_M80P:
            return None
        if self.mode == "direct":
            return "direct-pen" if self.waydroid_focused else None
        if self.waydroid_focused:
            return "android-button"
        return "desktop-pen"

    def _write_button_state(self, route, states):
        if route == "desktop-pen":
            self.proxies[MODEL_M80P].write_buttons(states)
        elif route == "direct-pen":
            self.android_proxies[MODEL_M80P].write_buttons(states)
        elif route == "android-button":
            for code in ORDINARY_BUTTON_CODES:
                self.android_button_proxy.set_key(code, bool(states.get(code, False)))

    def _release_button_route(self, route):
        if route in {"desktop-pen", "direct-pen"}:
            proxy = (
                self.proxies[MODEL_M80P]
                if route == "desktop-pen"
                else self.android_proxies[MODEL_M80P]
            )
            if hasattr(proxy, "release_buttons"):
                proxy.release_buttons()
            else:
                proxy.release()
        elif route == "android-button":
            if hasattr(self.android_button_proxy, "release_keys"):
                self.android_button_proxy.release_keys(ORDINARY_BUTTON_CODES)
            else:
                self.android_button_proxy.release()

    def _reroute_ordinary_buttons(self):
        route = self._desired_button_route()
        if route == self.ordinary_button_route:
            return False
        if self.ordinary_button_route is not None:
            self._release_button_route(self.ordinary_button_route)
        self.ordinary_button_route = route
        # Do not replay a held physical button merely because focus or mode
        # changed.  The next source frame carries the state once, preventing a
        # synthetic duplicate click during a route transition.
        self.android_button_active = route == "android-button"
        return True

    def _require_capability(self, generation, pro_available):
        if generation != self.capability_generation:
            raise RelayError("pen capability changed during mode transition")
        if bool(pro_available) != self.pro_available:
            raise RelayError("pen capability no longer matches mode transition")

    def _set_pro_available(self, available):
        available = bool(available)
        if available == self.pro_available:
            return False
        if available:
            self._create_gesture_proxies()
        else:
            self._set_android_pro_active(False)
            self._close_gesture_proxies()
            self._reset_pro_gesture_state()
        self.pro_available = available
        self.capability_generation += 1
        self._write_state()
        self._write_link_state()
        return True

    def _activate_model(self, model):
        if model not in PEN_MODELS:
            raise RelayError(f"unknown pen model: {model}")
        if self.active_model == model:
            return False
        if self.active_model is not None:
            old = self.active_model
            if self.ordinary_button_route is not None:
                self._release_button_route(self.ordinary_button_route)
            if self.android_pro_active:
                self._set_android_pro_active(False)
            if self.gesture_proxy is not None:
                self.gesture_proxy.release()
            self.mappers[old].reset_source_state()
            self.proxies[old].release()
        self.active_model = model
        source = self.sources[model]
        self.mappers[model].set_source_range(
            source["y_min"], source["y_max"], source["pressure_max"]
        )
        self.android_mapper = self.mappers[model]
        self.proxy = self.proxies[model]
        self.android_proxy = self.android_proxies[model]
        self.device = source["node"]
        self.device_fd = source["fd"]
        self.input_buffer = source["buffer"]
        self._reset_ordinary_button_state()
        self.ordinary_button_route = None
        self._reroute_ordinary_buttons()
        self.capability_generation += 1
        self._write_state()
        self._write_link_state()
        return True

    def _data_has_active_pen(self, data):
        for offset in range(0, len(data), INPUT_EVENT.size):
            _s, _us, event_type, code, value = INPUT_EVENT.unpack_from(data, offset)
            if event_type == EV_KEY and code == BTN_TOOL_PEN and value:
                return True
            if event_type == EV_KEY and code == BTN_TOUCH and value:
                return True
            if event_type == EV_ABS and code in (ABS_X, ABS_Y, ABS_PRESSURE) and value:
                return True
        return False

    def _release_desktop_proxies(self):
        for proxy in self.proxies.values():
            proxy.release()

    def _release_android_pen_paths(self):
        for mapper in self.mappers.values():
            mapper.reset_source_state()
        for proxy in self.android_proxies.values():
            if hasattr(proxy, "release"):
                proxy.release()

    def set_desktop_mode(self):
        if self.mode == "direct":
            # Leaving direct must clear every Android pen tip before desktop
            # frames resume, including the inactive model proxy.
            self._release_android_pen_paths()
        self.mode = "desktop"
        self._reroute_ordinary_buttons()
        if self.android_pro_active and not self._android_pro_should_be_active():
            self._set_android_pro_active(False)
        if self.pro_available:
            self._synthesize_desktop_pro_state()
        self._write_state()
        return self._response()

    def set_direct_mode(self, generation, pro_available):
        self._require_capability(generation, pro_available)
        if self.mode != "direct":
            # Drop any held desktop tip so only the hidden Android proxies
            # carry the next stroke.
            self._release_desktop_proxies()
            self._release_android_pen_paths()
        self.mode = "direct"
        self._reroute_ordinary_buttons()
        self._set_android_pro_active(
            self._android_pro_should_be_active(), synthesize_pressed=True
        )
        self._write_state()
        return self._response()

    def activate_android_pro(self, generation):
        self._require_capability(generation, True)
        if not self._android_pro_should_be_active():
            raise RelayError("cannot activate Pro routing in the current state")
        if self._set_android_pro_active(True, synthesize_pressed=True):
            self._write_state()
        return self._response()

    def deactivate_android_pro(self):
        if self._set_android_pro_active(False):
            self._write_state()
        return self._response()

    def set_waydroid_focus(self, focused):
        focused = bool(focused)
        focus_changed = focused != self.waydroid_focused
        self.waydroid_focused = focused
        if self._android_pro_should_be_active() and not self.android_pro_active:
            if self.gesture_proxy is not None:
                self.gesture_proxy.release()
            routing_changed = self._set_android_pro_active(True, False)
        elif not focused and self.android_pro_active:
            routing_changed = self._set_android_pro_active(False)
        else:
            routing_changed = False
        ordinary_changed = self._reroute_ordinary_buttons()
        if focus_changed or routing_changed or ordinary_changed:
            self._write_state()
        return self._response()

    def forward(self, model, data=None):
        # ``forward(data)`` was the pre-dual-node diagnostic API.  Keep it as
        # a harmless alias while the event loop uses ``forward(model, data)``
        # to make the source identity explicit.
        if data is None:
            data = model
            model = self.active_model
        if model != self.active_model:
            return
        source = self.sources[model]
        profile = PEN_PROFILES[model]
        self._update_ordinary_button_state(data)
        suppress = ()
        if model == MODEL_M80P:
            expected_route = (
                "desktop-pen" if self.mode == "desktop"
                else "direct-pen" if self.waydroid_focused else None
            )
            if expected_route is None or self.ordinary_button_route != expected_route:
                suppress = ORDINARY_BUTTON_CODES
        if self.mode == "desktop":
            mapped = transform_pen_events(
                data, source_y_min=source["y_min"], source_y_max=source["y_max"],
                target_y_min=0, target_y_max=PEN_Y_MAX,
                pressure_max=profile["pressure_max"], suppress_buttons=suppress,
            )
            self.proxies[model].write(mapped)
        elif self.mode == "direct":
            mapper = self.mappers[model]
            mapper.set_source_range(source["y_min"], source["y_max"],
                                    profile["pressure_max"])
            mapper.feed(data, True, suppress_keys=suppress)
        if model == MODEL_M80P and self.ordinary_button_route == "android-button":
            self.android_button_proxy.feed(data, "ordinary")

    def forward_gesture(self, data):
        if (
            self.active_model != MODEL_P81C
            or not self.pro_available
            or self.gesture_proxy is None
        ):
            return
        self._update_pro_gesture_state(data)
        if self.mode == "desktop" and not self.android_pro_active:
            self.gesture_proxy.feed(data, "gesture")
        if self.android_pro_active and self.android_gesture_proxy is not None:
            self.android_gesture_proxy.feed(data, "gesture")

    def set_mapping(self, values):
        for mapper in self.mappers.values():
            mapper.set_geometry(None if values is None else tuple(float(value) for value in values))
        self._write_state()
        return self._response()

    def _accept_command(self):
        connection, _ = self.server.accept()
        with connection:
            connection.settimeout(2.0)
            try:
                command = connection.recv(128).decode("ascii").strip()
                if command == "status":
                    response = self._response()
                elif command == "unmap":
                    response = self.set_mapping(None)
                elif command.startswith("map "):
                    values = command.split()[1:]
                    if len(values) != 4:
                        raise RelayError("usage: map X Y WIDTH HEIGHT")
                    response = self.set_mapping(values)
                elif command == "desktop":
                    response = self.set_desktop_mode()
                elif command.startswith("direct "):
                    arguments = command.split()
                    if len(arguments) != 3 or arguments[2] not in {"0", "1"}:
                        raise RelayError("usage: direct GENERATION PRO_AVAILABLE")
                    response = self.set_direct_mode(int(arguments[1]), arguments[2] == "1")
                elif command.startswith("activate-pro "):
                    arguments = command.split()
                    if len(arguments) != 2:
                        raise RelayError("usage: activate-pro GENERATION")
                    response = self.activate_android_pro(int(arguments[1]))
                elif command == "deactivate-pro":
                    response = self.deactivate_android_pro()
                elif command.startswith("focus "):
                    arguments = command.split()
                    if len(arguments) != 2 or arguments[1] not in {"0", "1"}:
                        raise RelayError("usage: focus {0|1}")
                    response = self.set_waydroid_focus(arguments[1] == "1")
                else:
                    raise RelayError(f"invalid relay command: {command}")
            except Exception as error:
                response = {"ok": False, "error": str(error), "mode": self.mode}
            connection.sendall(json.dumps(response).encode("utf-8"))

    def _open_source(self, model, node=None):
        source = self.sources[model]
        if node is None:
            node = find_pen_sources(self.config).get(model)
        if node is None or source["fd"] is not None:
            return
        fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        profile = PEN_PROFILES[model]
        source["y_min"], source["y_max"] = read_abs_range(
            fd, ABS_Y, (0, PEN_Y_MAX))
        source["pressure_min"], source["pressure_max"] = read_abs_range(
            fd, ABS_PRESSURE, (0, profile["pressure_max"]))
        source["node"] = node
        source["fd"] = fd
        source["buffer"] = bytearray()
        self.selector.register(fd, selectors.EVENT_READ, ("pen", model))
        if self.active_model == model:
            self.device, self.device_fd, self.input_buffer = node, fd, source["buffer"]
            self.mappers[model].set_source_range(source["y_min"], source["y_max"],
                                                 profile["pressure_max"])
        self._write_state()

    # Compatibility shims for older local diagnostics.  New code always uses
    # the model-specific source methods so a scan-order choice cannot return.
    def _open_device(self, node=None):
        model = self.active_model or MODEL_M80P
        self._open_source(model, node)

    def _close_device(self):
        model = self.active_model
        if model is not None:
            self._close_source(model)

    def _close_source(self, model):
        source = self.sources[model]
        fd = source["fd"]
        if fd is not None:
            try:
                self.selector.unregister(fd)
            except Exception:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
        source.update({"node": None, "fd": None, "buffer": bytearray()})
        if self.active_model == model:
            # A disappearing active pen is a hard input boundary.  Release
            # every keyboard side-channel before dropping the source so an
            # incomplete final frame cannot leave Android or KDE stuck down.
            if self.android_gesture_proxy is not None:
                self.android_gesture_proxy.release()
            if self.gesture_proxy is not None:
                self.gesture_proxy.release()
            self.android_pro_active = False
            self._reset_pro_gesture_state()
            self.mappers[model].reset_source_state()
            self.proxies[model].release()
            self.active_model = None
            self.device = self.device_fd = None
            self.input_buffer = bytearray()
            self._reset_ordinary_button_state()
            self.ordinary_button_route = None
            self.android_button_active = False
            self.capability_generation += 1
            self._write_link_state()
        self._write_state()

    def _open_gesture_device(self, node=None):
        if node is None:
            node = find_gesture_source(self.config)
        if node is None or self.gesture_device_fd is not None:
            return
        self._create_gesture_proxies()
        try:
            fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        except Exception:
            self._close_gesture_proxies()
            raise
        try:
            self.selector.register(fd, selectors.EVENT_READ, "gesture")
        except Exception:
            os.close(fd)
            self._close_gesture_proxies()
            raise
        self.gesture_device, self.gesture_device_fd = node, fd
        self._set_pro_available(True)
        self._write_state()

    def _close_gesture_device(self):
        if self.gesture_device_fd is not None:
            try:
                self.selector.unregister(self.gesture_device_fd)
            except Exception:
                pass
            try:
                os.close(self.gesture_device_fd)
            except OSError:
                pass
        self.gesture_device = None
        self.gesture_device_fd = None
        self.gesture_input_buffer.clear()
        self._set_pro_available(False)
        self._write_state()

    def _reconcile_sources(self):
        discovered = find_pen_sources(self.config)
        for model in PEN_MODELS:
            node = discovered[model]
            current = self.sources[model]["node"]
            if node != current:
                if current is not None:
                    self._close_source(model)
                if node is not None:
                    self._open_source(model, node)
        gesture_node = find_gesture_source(self.config)
        if gesture_node != self.gesture_device:
            if self.gesture_device is not None:
                self._close_gesture_device()
            if gesture_node is not None:
                self._open_gesture_device(gesture_node)

    def _read_source(self, model):
        source = self.sources[model]
        try:
            data = os.read(source["fd"], INPUT_EVENT.size * 128)
        except BlockingIOError:
            return
        except OSError:
            self._close_source(model)
            return
        if not data:
            self._close_source(model)
            return
        source["buffer"].extend(data)
        complete = len(source["buffer"]) // INPUT_EVENT.size * INPUT_EVENT.size
        if not complete:
            return
        frame_data = bytes(source["buffer"][:complete])
        del source["buffer"][:complete]
        if self.active_model != model and self._data_has_active_pen(frame_data):
            self._activate_model(model)
        self.forward(model, frame_data)

    def _read_gesture_device(self):
        try:
            data = os.read(self.gesture_device_fd, INPUT_EVENT.size * 64)
        except BlockingIOError:
            return
        except OSError:
            self._close_gesture_device()
            return
        if not data:
            self._close_gesture_device()
            return
        self.gesture_input_buffer.extend(data)
        complete = len(self.gesture_input_buffer) // INPUT_EVENT.size * INPUT_EVENT.size
        if complete:
            self.forward_gesture(bytes(self.gesture_input_buffer[:complete]))
            del self.gesture_input_buffer[:complete]

    def run(self):
        while self.running:
            try:
                self._reconcile_sources()
            except OSError:
                for model in PEN_MODELS:
                    self._close_source(model)
                self._close_gesture_device()
            for key, _ in self.selector.select(timeout=1.0):
                if key.data == "control":
                    self._accept_command()
                elif isinstance(key.data, tuple) and key.data[0] == "pen":
                    self._read_source(key.data[1])
                elif key.data == "gesture":
                    self._read_gesture_device()

    def close(self):
        for model in PEN_MODELS:
            self._close_source(model)
        self._close_gesture_device()
        try:
            self.selector.unregister(self.server)
        except Exception:
            pass
        self.server.close()
        Path(self.config["CONTROL_SOCKET"]).unlink(missing_ok=True)
        self.android_button_proxy.close()
        for proxy in self.proxies.values():
            proxy.close()
        for proxy in self.android_proxies.values():
            proxy.close()
        self.selector.close()


def main():
    if os.geteuid() != 0:
        raise RelayError("must be run as root")
    relay = PenRelay(load_config())

    def stop(_signum, _frame):
        relay.running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        relay.run()
    finally:
        relay.close()


if __name__ == "__main__":
    main()
