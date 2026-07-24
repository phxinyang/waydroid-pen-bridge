#!/usr/bin/python3

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
    "PROXY_PHYS": "waydroid-pen-relay",
    "ANDROID_PROXY_PHYS": "waydroid-pen-android",
    "GESTURE_DEVICE_NAME": "Xiaomi Focus Pen Pro Gestures",
    "GESTURE_DEVICE_PHYS": "input/pen_p81c/gestures",
    "GESTURE_PROXY_PHYS": "waydroid-gesture-relay",
    "ANDROID_GESTURE_PROXY_PHYS": "waydroid-gesture-android",
    "DIRECT_Y_MIN": "600",
    "CONTROL_SOCKET": "/run/waydroid-pen-mode/control.sock",
    "STATE_PATH": "/run/waydroid-pen-mode/state.json",
}

BUS_USB = 0x03
BUS_VIRTUAL = 0x06
VENDOR_ID = 0x2717
PRODUCT_ID = 0x3654
GESTURE_PRODUCT_ID = 0x3655
PRO_GESTURE_VENDOR_ID = 0x0022
PRO_GESTURE_PRODUCT_ID = 0x5081
DEVICE_VERSION = 1
PRO_DEVICE_NAME = "NVTCapacitivePenP81c"
PRO_DEVICE_PHYS = "input/pen_p81c"

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03
SYN_REPORT = 0
BTN_TOOL_PEN = 0x140
BTN_TOUCH = 0x14A
BTN_STYLUS = 0x14B
BTN_STYLUS2 = 0x14C
BTN_6 = 0x106
BTN_7 = 0x107
BTN_8 = 0x108
BTN_9 = 0x109
KEY_PROG1 = 148
KEY_PROG2 = 149
KEY_PROG3 = 202
KEY_PROG4 = 203
DESKTOP_GESTURE_KEYS = (KEY_PROG3, KEY_PROG4)
ANDROID_GESTURE_KEYS = (KEY_PROG1, KEY_PROG2, KEY_PROG3, KEY_PROG4)
PRO_BUTTON_TO_STYLUS = {
    BTN_6: BTN_STYLUS,
    BTN_7: BTN_STYLUS2,
}
PRO_SLIDE_TO_DESKTOP = {
    BTN_8: KEY_PROG3,
    BTN_9: KEY_PROG4,
}
PRO_GESTURE_TO_ANDROID = {
    BTN_6: KEY_PROG1,
    BTN_7: KEY_PROG2,
    BTN_8: KEY_PROG3,
    BTN_9: KEY_PROG4,
}
PRO_GESTURE_CODES = tuple(PRO_GESTURE_TO_ANDROID)
ABS_X = 0x00
ABS_Y = 0x01
ABS_BRAKE = 0x0A
ABS_PRESSURE = 0x18
ABS_DISTANCE = 0x19
ABS_TILT_X = 0x1A
ABS_TILT_Y = 0x1B
INPUT_PROP_DIRECT = 0x01

ABS_CNT = 0x40
INPUT_ABSINFO = struct.Struct("@6i")
INPUT_EVENT = struct.Struct("@llHHi")
UINPUT_SETUP = struct.Struct("@HHHH80sI")
UINPUT_ABS_SETUP = struct.Struct("@H2x6i")

PEN_AXIS_SPECS = (
    (ABS_X, 0, 30479, 113),
    (ABS_Y, 0, 20319, 113),
    (ABS_BRAKE, 0, 360, 0),
    (ABS_PRESSURE, 0, 16383, 0),
    (ABS_DISTANCE, 0, 1, 0),
    (ABS_TILT_X, -60, 60, 0),
    (ABS_TILT_Y, -60, 60, 0),
)


def _ioc(direction, type_, number, size):
    return (direction << 30) | (size << 16) | (type_ << 8) | number


def _io(type_, number):
    return _ioc(0, type_, number, 0)


def _ior(type_, number, size):
    return _ioc(2, type_, number, size)


def _iow(type_, number, size):
    return _ioc(1, type_, number, size)


EVIOCGABS_Y = _ior(ord("E"), 0x40 + ABS_Y, INPUT_ABSINFO.size)
EVIOCSABS_Y = _iow(ord("E"), 0xC0 + ABS_Y, INPUT_ABSINFO.size)
UI_DEV_CREATE = _io(ord("U"), 1)
UI_DEV_DESTROY = _io(ord("U"), 2)
UI_DEV_SETUP = _iow(ord("U"), 3, UINPUT_SETUP.size)
UI_ABS_SETUP = _iow(ord("U"), 4, UINPUT_ABS_SETUP.size)
UI_SET_EVBIT = _iow(ord("U"), 100, struct.calcsize("I"))
UI_SET_KEYBIT = _iow(ord("U"), 101, struct.calcsize("I"))
UI_SET_ABSBIT = _iow(ord("U"), 103, struct.calcsize("I"))
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


def find_pen_source(
    config,
    pro_available,
    sys_class_input=Path("/sys/class/input"),
    dev_input=Path("/dev/input"),
):
    if pro_available:
        name = PRO_DEVICE_NAME
        phys = PRO_DEVICE_PHYS
    else:
        name = config["DEVICE_NAME"]
        phys = config["DEVICE_PHYS"]
    return find_source_event(
        name,
        PRODUCT_ID,
        phys,
        {config["PROXY_PHYS"], config["ANDROID_PROXY_PHYS"]},
        sys_class_input,
        dev_input,
    )


def find_gesture_source(
    config,
    sys_class_input=Path("/sys/class/input"),
    dev_input=Path("/dev/input"),
):
    return find_source_event(
        config["GESTURE_DEVICE_NAME"],
        PRO_GESTURE_PRODUCT_ID,
        config["GESTURE_DEVICE_PHYS"],
        {
            config["GESTURE_PROXY_PHYS"],
            config["ANDROID_GESTURE_PROXY_PHYS"],
        },
        sys_class_input,
        dev_input,
        vendor_id=PRO_GESTURE_VENDOR_ID,
    )


def write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    os.chmod(path.parent, 0o755)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC,
        0o644,
    )
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


def set_abs_y_min(node, minimum):
    with node.open("rb", buffering=0) as device:
        data = bytearray(INPUT_ABSINFO.size)
        fcntl.ioctl(device.fileno(), EVIOCGABS_Y, data, True)
    values = list(INPUT_ABSINFO.unpack(data))
    if values[1] == minimum:
        return
    values[1] = minimum
    with node.open("r+b", buffering=0) as device:
        fcntl.ioctl(device.fileno(), EVIOCSABS_Y, INPUT_ABSINFO.pack(*values))


def make_event(type_, code, value):
    return INPUT_EVENT.pack(0, 0, type_, code, value)


def make_abs_setup(code, minimum, maximum, resolution=0):
    return UINPUT_ABS_SETUP.pack(
        code, 0, minimum, maximum, 0, 0, resolution
    )


class VirtualPen:
    def __init__(self, name, phys, y_min=0):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_CLOEXEC)
        try:
            for event_type in (EV_KEY, EV_ABS):
                fcntl.ioctl(self.fd, UI_SET_EVBIT, event_type)
            for key in (BTN_TOOL_PEN, BTN_TOUCH, BTN_STYLUS, BTN_STYLUS2):
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, key)
            for axis, _minimum, _maximum, _resolution in PEN_AXIS_SPECS:
                fcntl.ioctl(self.fd, UI_SET_ABSBIT, axis)
            fcntl.ioctl(self.fd, UI_SET_PROPBIT, INPUT_PROP_DIRECT)
            fcntl.ioctl(self.fd, UI_SET_PHYS, (phys + "\0").encode("ascii"))
            setup = UINPUT_SETUP.pack(
                BUS_USB,
                VENDOR_ID,
                PRODUCT_ID,
                DEVICE_VERSION,
                name.encode("utf-8"),
                0,
            )
            fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
            for code, minimum, maximum, resolution in PEN_AXIS_SPECS:
                if code == ABS_Y:
                    minimum = y_min
                fcntl.ioctl(
                    self.fd,
                    UI_ABS_SETUP,
                    make_abs_setup(code, minimum, maximum, resolution),
                )
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

    def release(self):
        self.write(
            b"".join(
                (
                    make_event(EV_KEY, BTN_TOOL_PEN, 0),
                    make_event(EV_KEY, BTN_TOUCH, 0),
                    make_event(EV_KEY, BTN_STYLUS, 0),
                    make_event(EV_KEY, BTN_STYLUS2, 0),
                    make_event(EV_ABS, ABS_BRAKE, 0),
                    make_event(EV_ABS, ABS_PRESSURE, 0),
                    make_event(EV_ABS, ABS_DISTANCE, 0),
                    make_event(EV_ABS, ABS_TILT_X, 0),
                    make_event(EV_ABS, ABS_TILT_Y, 0),
                    make_event(EV_SYN, SYN_REPORT, 0),
                )
            )
        )

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
    def __init__(self, name, phys, supported_codes):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_CLOEXEC)
        self.supported_codes = tuple(supported_codes)
        self.pressed = {code: False for code in self.supported_codes}
        self.pending = {}
        try:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            for code in self.supported_codes:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
            fcntl.ioctl(self.fd, UI_SET_PHYS, (phys + "\0").encode("ascii"))
            setup = UINPUT_SETUP.pack(
                BUS_USB,
                VENDOR_ID,
                GESTURE_PRODUCT_ID,
                DEVICE_VERSION,
                name.encode("utf-8"),
                0,
            )
            fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
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

    def feed(self, data, code_map, stream):
        pending = self.pending.setdefault(stream, [])
        for offset in range(0, len(data), INPUT_EVENT.size):
            seconds, microseconds, event_type, code, value = (
                INPUT_EVENT.unpack_from(data, offset)
            )
            output_code = code_map.get(code)
            if event_type == EV_KEY and output_code in self.pressed:
                if value not in (0, 1):
                    continue
                pressed = value == 1
                if self.pressed[output_code] == pressed:
                    continue
                self.pressed[output_code] = pressed
                pending.append(
                    INPUT_EVENT.pack(
                        seconds,
                        microseconds,
                        EV_KEY,
                        output_code,
                        value,
                    )
                )
            elif event_type == EV_SYN and code == SYN_REPORT and pending:
                pending.append(
                    INPUT_EVENT.pack(
                        seconds,
                        microseconds,
                        EV_SYN,
                        SYN_REPORT,
                        0,
                    )
                )
                self.write(b"".join(pending))
                pending.clear()

    def set_key(self, code, pressed):
        if code not in self.pressed:
            raise RelayError(f"unsupported gesture key code: {code}")
        if self.pressed[code] == pressed:
            return False
        self.pressed[code] = pressed
        self.write(
            b"".join(
                (
                    make_event(EV_KEY, code, int(pressed)),
                    make_event(EV_SYN, SYN_REPORT, 0),
                )
            )
        )
        return True

    def release(self):
        events = []
        for code, pressed in self.pressed.items():
            if not pressed:
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
    X_MAX = 30479
    SOURCE_Y_MIN = 0
    Y_MAX = 20319

    def __init__(self, output, output_y_min):
        self.output = output
        self.output_y_min = output_y_min
        self.geometry = None
        self.events = []
        self.axes = {
            ABS_X: None,
            ABS_Y: None,
            ABS_BRAKE: 0,
            ABS_PRESSURE: 0,
            ABS_DISTANCE: 0,
            ABS_TILT_X: 0,
            ABS_TILT_Y: 0,
        }
        self.keys = {
            BTN_TOOL_PEN: 0,
            BTN_TOUCH: 0,
            BTN_STYLUS: 0,
            BTN_STYLUS2: 0,
        }
        self.stylus_buttons_enabled = True
        self.active = False

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

    def set_stylus_buttons_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self.stylus_buttons_enabled:
            return
        self.release()
        self.stylus_buttons_enabled = enabled

    def reset_stylus_buttons(self):
        self.release()
        self.keys[BTN_STYLUS] = 0
        self.keys[BTN_STYLUS2] = 0
        self.events = [
            event
            for event in self.events
            if not (
                event[2] == EV_KEY
                and event[3] in (BTN_STYLUS, BTN_STYLUS2)
            )
        ]

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

    def feed(self, data, enabled):
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
                    mapped = self._map_frame()
                    if mapped:
                        self.output.write(mapped)
                self.events.clear()

    def _map_frame(self):
        x = self.axes[ABS_X]
        y = self.axes[ABS_Y]
        if x is None or y is None:
            return b""

        mapped = self._map_point(x, y)
        if mapped is None:
            self.release()
            return b""

        mapped_x, mapped_y = mapped
        if not self.active:
            self.active = True
            return self._snapshot(mapped_x, mapped_y)

        mapped_events = []
        for seconds, microseconds, event_type, code, value in self.events:
            if event_type == EV_ABS and code == ABS_X:
                value = mapped_x
            elif event_type == EV_ABS and code == ABS_Y:
                value = mapped_y
            elif (
                event_type == EV_KEY
                and code in (BTN_STYLUS, BTN_STYLUS2)
                and not self.stylus_buttons_enabled
            ):
                continue
            mapped_events.append(
                INPUT_EVENT.pack(
                    seconds, microseconds, event_type, code, value
                )
            )
        return b"".join(mapped_events)

    def _map_point(self, x, y):
        source_x = (x - self.X_MIN) / (self.X_MAX - self.X_MIN)
        source_y = (y - self.SOURCE_Y_MIN) / (
            self.Y_MAX - self.SOURCE_Y_MIN
        )
        geometry = self.geometry or (0.0, 0.0, 1.0, 1.0)
        left, top, width, height = geometry
        if not (left <= source_x <= left + width):
            return None
        if not (top <= source_y <= top + height):
            return None
        target_x = round((source_x - left) / width * self.X_MAX)
        target_y = round(
            self.output_y_min
            + (source_y - top)
            / height
            * (self.Y_MAX - self.output_y_min)
        )
        return (
            min(self.X_MAX, max(self.X_MIN, target_x)),
            min(self.Y_MAX, max(self.output_y_min, target_y)),
        )

    def _snapshot(self, x, y):
        stylus = self.keys[BTN_STYLUS] if self.stylus_buttons_enabled else 0
        stylus2 = self.keys[BTN_STYLUS2] if self.stylus_buttons_enabled else 0
        events = [
            make_event(EV_KEY, BTN_TOOL_PEN, self.keys[BTN_TOOL_PEN]),
            make_event(EV_KEY, BTN_TOUCH, self.keys[BTN_TOUCH]),
            make_event(EV_KEY, BTN_STYLUS, stylus),
            make_event(EV_KEY, BTN_STYLUS2, stylus2),
            make_event(EV_ABS, ABS_X, x),
            make_event(EV_ABS, ABS_Y, y),
            make_event(EV_ABS, ABS_BRAKE, self.axes[ABS_BRAKE]),
            make_event(EV_ABS, ABS_PRESSURE, self.axes[ABS_PRESSURE]),
            make_event(EV_ABS, ABS_DISTANCE, self.axes[ABS_DISTANCE]),
            make_event(EV_ABS, ABS_TILT_X, self.axes[ABS_TILT_X]),
            make_event(EV_ABS, ABS_TILT_Y, self.axes[ABS_TILT_Y]),
            make_event(EV_SYN, SYN_REPORT, 0),
        ]
        return b"".join(events)


class PenRelay:
    def __init__(self, config):
        self.config = config
        self.selector = selectors.DefaultSelector()
        self.running = True
        self.mode = "desktop"
        self.device = None
        self.device_fd = None
        self.input_buffer = bytearray()
        self.gesture_device = None
        self.gesture_device_fd = None
        self.gesture_input_buffer = bytearray()
        self.pro_gesture_state = {code: False for code in PRO_GESTURE_CODES}
        self.desktop_pro_buttons = {
            BTN_STYLUS: False,
            BTN_STYLUS2: False,
        }
        self.desktop_pro_button_pending = []
        self.pro_available = False
        self.android_pro_active = False
        self.capability_generation = self._next_capability_generation()
        self.instance_id = uuid.uuid4().hex
        self.proxy = VirtualPen(config["DEVICE_NAME"], config["PROXY_PHYS"])
        self.android_proxy = VirtualPen(
            config["DEVICE_NAME"],
            config["ANDROID_PROXY_PHYS"],
            int(config["DIRECT_Y_MIN"]),
        )
        self.android_mapper = AndroidFrameMapper(
            self.android_proxy, int(config["DIRECT_Y_MIN"])
        )
        self.gesture_proxy = VirtualGestureKeyboard(
            config["GESTURE_DEVICE_NAME"],
            config["GESTURE_PROXY_PHYS"],
            DESKTOP_GESTURE_KEYS,
        )
        self.android_gesture_proxy = VirtualGestureKeyboard(
            config["GESTURE_DEVICE_NAME"],
            config["ANDROID_GESTURE_PROXY_PHYS"],
            ANDROID_GESTURE_KEYS,
        )
        self.server = self._create_server(Path(config["CONTROL_SOCKET"]))
        self.selector.register(self.server, selectors.EVENT_READ, "control")
        self._write_state()

    def _next_capability_generation(self):
        state_path = Path(self.config["STATE_PATH"])
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
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

    def _state(self):
        return {
            "mode": self.mode,
            "device": str(self.device) if self.device else None,
            "gesture_device": (
                str(self.gesture_device) if self.gesture_device else None
            ),
            "pro_available": self.pro_available,
            "android_pro_active": self.android_pro_active,
            "capability_generation": self.capability_generation,
            "instance_id": self.instance_id,
            "forwarding": self.mode == "desktop",
            "mapping": self.android_mapper.geometry,
        }

    def _response(self):
        return {"ok": True, **self._state()}

    def _sync_android_button_policy(self):
        self.android_mapper.set_stylus_buttons_enabled(
            not (self.mode == "direct" and self.android_pro_active)
        )

    def _clear_desktop_pro_buttons(self):
        for code in self.desktop_pro_buttons:
            self.desktop_pro_buttons[code] = False
        self.desktop_pro_button_pending.clear()

    def _set_desktop_pro_button(self, code, pressed):
        pressed = bool(pressed)
        if self.desktop_pro_buttons[code] == pressed:
            return False
        self.desktop_pro_buttons[code] = pressed
        self.proxy.write(
            b"".join(
                (
                    make_event(EV_KEY, code, int(pressed)),
                    make_event(EV_SYN, SYN_REPORT, 0),
                )
            )
        )
        return True

    def _release_desktop_pro_buttons(self):
        events = []
        for code, pressed in self.desktop_pro_buttons.items():
            if not pressed:
                continue
            self.desktop_pro_buttons[code] = False
            events.append(make_event(EV_KEY, code, 0))
        self.desktop_pro_button_pending.clear()
        if events:
            events.append(make_event(EV_SYN, SYN_REPORT, 0))
            self.proxy.write(b"".join(events))

    def _feed_desktop_pro_buttons(self, data):
        for offset in range(0, len(data), INPUT_EVENT.size):
            seconds, microseconds, event_type, code, value = (
                INPUT_EVENT.unpack_from(data, offset)
            )
            output_code = PRO_BUTTON_TO_STYLUS.get(code)
            if event_type == EV_KEY and output_code is not None:
                if value not in (0, 1):
                    continue
                pressed = value == 1
                if self.desktop_pro_buttons[output_code] == pressed:
                    continue
                self.desktop_pro_buttons[output_code] = pressed
                self.desktop_pro_button_pending.append(
                    INPUT_EVENT.pack(
                        seconds,
                        microseconds,
                        EV_KEY,
                        output_code,
                        value,
                    )
                )
            elif (
                event_type == EV_SYN
                and code == SYN_REPORT
                and self.desktop_pro_button_pending
            ):
                self.desktop_pro_button_pending.append(
                    INPUT_EVENT.pack(
                        seconds,
                        microseconds,
                        EV_SYN,
                        SYN_REPORT,
                        0,
                    )
                )
                self.proxy.write(b"".join(self.desktop_pro_button_pending))
                self.desktop_pro_button_pending.clear()

    def _update_pro_gesture_state(self, data):
        for offset in range(0, len(data), INPUT_EVENT.size):
            _seconds, _microseconds, event_type, code, value = (
                INPUT_EVENT.unpack_from(data, offset)
            )
            if (
                event_type == EV_KEY
                and code in self.pro_gesture_state
                and value in (0, 1)
            ):
                self.pro_gesture_state[code] = value == 1

    def _reset_pro_gesture_state(self):
        for code in self.pro_gesture_state:
            self.pro_gesture_state[code] = False

    def _synthesize_desktop_pro_state(self):
        for source_code, output_code in PRO_BUTTON_TO_STYLUS.items():
            if self.pro_gesture_state[source_code]:
                self._set_desktop_pro_button(output_code, True)
        for source_code, output_code in PRO_SLIDE_TO_DESKTOP.items():
            if self.pro_gesture_state[source_code]:
                self.gesture_proxy.set_key(output_code, True)

    def _synthesize_android_pro_state(self):
        for source_code, output_code in PRO_GESTURE_TO_ANDROID.items():
            if self.pro_gesture_state[source_code]:
                self.android_gesture_proxy.set_key(output_code, True)

    def _set_android_pro_active(self, active, synthesize_pressed=False):
        active = bool(active)
        if active == self.android_pro_active:
            return False
        if active:
            if self.mode != "direct" or not self.pro_available:
                raise RelayError("cannot activate Pro routing in the current state")
            self.android_pro_active = True
            self._sync_android_button_policy()
            if synthesize_pressed:
                self._synthesize_android_pro_state()
        else:
            self.android_gesture_proxy.release()
            self.android_pro_active = False
            self._sync_android_button_policy()
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
        if not available:
            self._set_android_pro_active(False)
            self._release_desktop_pro_buttons()
            self.gesture_proxy.release()
            self.android_gesture_proxy.release()
            self._reset_pro_gesture_state()
            self.android_mapper.reset_stylus_buttons()
        self.pro_available = available
        self.capability_generation += 1
        self._sync_android_button_policy()
        self._write_state()
        return True

    def set_desktop_mode(self):
        if self.mode == "desktop" and not self.android_pro_active:
            return self._response()
        if self.mode == "direct":
            self.android_mapper.release()
        self._set_android_pro_active(False)
        self.mode = "desktop"
        self._sync_android_button_policy()
        if self.pro_available:
            self._synthesize_desktop_pro_state()
        self._write_state()
        return self._response()

    def set_direct_mode(self, generation, pro_available):
        self._require_capability(generation, pro_available)
        entering_direct = self.mode != "direct"
        if entering_direct:
            self.proxy.release()
            self._clear_desktop_pro_buttons()
            self.gesture_proxy.release()
            self.mode = "direct"
        self._set_android_pro_active(
            pro_available, synthesize_pressed=True
        )
        self._sync_android_button_policy()
        self._write_state()
        return self._response()

    def activate_android_pro(self, generation):
        self._require_capability(generation, True)
        if self.mode != "direct":
            raise RelayError("cannot activate Pro routing outside direct mode")
        if self._set_android_pro_active(True, synthesize_pressed=True):
            self._write_state()
        return self._response()

    def forward(self, data):
        if self.mode == "desktop":
            self.proxy.write(data)
        self.android_mapper.feed(data, self.mode == "direct")

    def forward_gesture(self, data):
        self._update_pro_gesture_state(data)
        if self.mode == "desktop":
            self._feed_desktop_pro_buttons(data)
            self.gesture_proxy.feed(
                data,
                PRO_SLIDE_TO_DESKTOP,
                "gesture",
            )
        elif self.android_pro_active:
            self.android_gesture_proxy.feed(
                data,
                PRO_GESTURE_TO_ANDROID,
                "gesture",
            )

    def set_mapping(self, values):
        if values is None:
            self.android_mapper.set_geometry(None)
        else:
            self.android_mapper.set_geometry(tuple(float(value) for value in values))
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
                    response = self.set_direct_mode(
                        int(arguments[1]), arguments[2] == "1"
                    )
                elif command.startswith("activate-pro "):
                    arguments = command.split()
                    if len(arguments) != 2:
                        raise RelayError("usage: activate-pro GENERATION")
                    response = self.activate_android_pro(int(arguments[1]))
                else:
                    raise RelayError(f"invalid relay command: {command}")
            except Exception as error:
                response = {"ok": False, "error": str(error), "mode": self.mode}
            connection.sendall(json.dumps(response).encode("utf-8"))

    def _close_device(self):
        if self.device_fd is not None:
            try:
                self.selector.unregister(self.device_fd)
            except Exception:
                pass
            os.close(self.device_fd)
        self.device_fd = None
        self.device = None
        self.input_buffer.clear()
        self.proxy.release()
        self._clear_desktop_pro_buttons()
        self.android_mapper.reset_source_state()
        self.gesture_proxy.release()
        self.android_gesture_proxy.release()
        self._reset_pro_gesture_state()
        self._write_state()

    def _close_gesture_device(self):
        if self.gesture_device_fd is not None:
            try:
                self.selector.unregister(self.gesture_device_fd)
            except Exception:
                pass
            os.close(self.gesture_device_fd)
        self.gesture_device_fd = None
        self.gesture_device = None
        self.gesture_input_buffer.clear()
        self.gesture_proxy.release()
        self.android_gesture_proxy.release()
        if not self._set_pro_available(False):
            self._write_state()

    def _open_device(self, node=None):
        if node is None:
            node = find_pen_source(self.config, self.pro_available)
        if node is None:
            return
        set_abs_y_min(node, int(self.config["DIRECT_Y_MIN"]))
        fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        self.device = node
        self.device_fd = fd
        self.selector.register(fd, selectors.EVENT_READ, "pen")
        self._write_state()

    def _open_gesture_device(self, node=None):
        if node is None:
            node = find_gesture_source(self.config)
        if node is None:
            return
        fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            self.selector.register(fd, selectors.EVENT_READ, "gesture")
        except Exception:
            os.close(fd)
            raise
        self.gesture_device = node
        self.gesture_device_fd = fd
        if not self._set_pro_available(True):
            self._write_state()

    def _reconcile_sources(self):
        gesture_node = find_gesture_source(self.config)
        if gesture_node != self.gesture_device:
            self._close_gesture_device()
            if gesture_node is not None:
                self._open_gesture_device(gesture_node)

        pen_node = find_pen_source(self.config, self.pro_available)
        if pen_node != self.device:
            self._close_device()
            if pen_node is not None:
                self._open_device(pen_node)

    def _read_device(self):
        try:
            data = os.read(self.device_fd, INPUT_EVENT.size * 128)
        except BlockingIOError:
            return
        except OSError:
            self._close_device()
            return
        if not data:
            self._close_device()
            return
        self.input_buffer.extend(data)
        complete = len(self.input_buffer) // INPUT_EVENT.size * INPUT_EVENT.size
        if complete:
            self.forward(bytes(self.input_buffer[:complete]))
            del self.input_buffer[:complete]

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
        complete = (
            len(self.gesture_input_buffer)
            // INPUT_EVENT.size
            * INPUT_EVENT.size
        )
        if complete:
            self.forward_gesture(bytes(self.gesture_input_buffer[:complete]))
            del self.gesture_input_buffer[:complete]

    def run(self):
        while self.running:
            try:
                self._reconcile_sources()
            except OSError:
                self._close_device()
                self._close_gesture_device()
            for key, _ in self.selector.select(timeout=1.0):
                if key.data == "control":
                    self._accept_command()
                elif key.data == "pen":
                    self._read_device()
                elif key.data == "gesture":
                    self._read_gesture_device()

    def close(self):
        self._close_device()
        self._close_gesture_device()
        try:
            self.selector.unregister(self.server)
        except Exception:
            pass
        self.server.close()
        Path(self.config["CONTROL_SOCKET"]).unlink(missing_ok=True)
        self.proxy.close()
        self.android_proxy.close()
        self.gesture_proxy.close()
        self.android_gesture_proxy.close()
        self.selector.close()


def main():
    if os.geteuid() != 0:
        raise RelayError("must run as root")
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
