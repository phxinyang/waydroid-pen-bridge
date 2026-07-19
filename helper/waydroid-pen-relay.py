#!/usr/bin/python3

import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import struct
import time


CONFIG_PATH = Path("/etc/waydroid-pen-mode.conf")

DEFAULTS = {
    "DEVICE_NAME": "NVTCapacitivePenM80p",
    "PROXY_PHYS": "waydroid-pen-relay",
    "DIRECT_Y_MIN": "600",
    "CONTROL_SOCKET": "/run/waydroid-pen-mode/control.sock",
    "STATE_PATH": "/run/waydroid-pen-mode/state.json",
}

BUS_USB = 0x03
VENDOR_ID = 0x2717
PRODUCT_ID = 0x3654
DEVICE_VERSION = 1

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03
SYN_REPORT = 0
BTN_TOOL_PEN = 0x140
BTN_TOUCH = 0x14A
BTN_STYLUS = 0x14B
BTN_STYLUS2 = 0x14C
ABS_X = 0x00
ABS_Y = 0x01
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


def find_real_event(device_name, proxy_phys):
    for event_path in sorted(Path("/sys/class/input").glob("event*")):
        device_path = event_path / "device"
        try:
            name = (device_path / "name").read_text(encoding="utf-8").strip()
            phys_path = device_path / "phys"
            phys = (
                phys_path.read_text(encoding="utf-8").strip()
                if phys_path.exists()
                else ""
            )
        except OSError:
            continue
        if name == device_name and phys != proxy_phys:
            return Path("/dev/input") / event_path.name
    return None


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
    def __init__(self, name, phys):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_CLOEXEC)
        try:
            for event_type in (EV_KEY, EV_ABS):
                fcntl.ioctl(self.fd, UI_SET_EVBIT, event_type)
            for key in (BTN_TOOL_PEN, BTN_TOUCH, BTN_STYLUS, BTN_STYLUS2):
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, key)
            for axis in (
                ABS_X,
                ABS_Y,
                ABS_PRESSURE,
                ABS_DISTANCE,
                ABS_TILT_X,
                ABS_TILT_Y,
            ):
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
            for axis in (
                make_abs_setup(ABS_X, 0, 30479, 113),
                make_abs_setup(ABS_Y, 0, 20319, 113),
                make_abs_setup(ABS_PRESSURE, 0, 16384),
                make_abs_setup(ABS_DISTANCE, 0, 1),
                make_abs_setup(ABS_TILT_X, -60, 60),
                make_abs_setup(ABS_TILT_Y, -60, 60),
            ):
                fcntl.ioctl(self.fd, UI_ABS_SETUP, axis)
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


class PenRelay:
    def __init__(self, config):
        self.config = config
        self.selector = selectors.DefaultSelector()
        self.running = True
        self.mode = "desktop"
        self.device = None
        self.device_fd = None
        self.input_buffer = bytearray()
        self.proxy = VirtualPen(config["DEVICE_NAME"], config["PROXY_PHYS"])
        self.server = self._create_server(Path(config["CONTROL_SOCKET"]))
        self.selector.register(self.server, selectors.EVENT_READ, "control")
        self._write_state()

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
        state_path = Path(self.config["STATE_PATH"])
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "mode": self.mode,
                    "device": str(self.device) if self.device else None,
                    "forwarding": self.mode == "desktop",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _response(self):
        return {
            "ok": True,
            "mode": self.mode,
            "device": str(self.device) if self.device else None,
            "forwarding": self.mode == "desktop",
        }

    def set_mode(self, mode):
        if mode not in {"desktop", "direct"}:
            raise RelayError(f"invalid relay mode: {mode}")
        if mode == self.mode:
            return self._response()
        if mode == "direct":
            self.proxy.release()
        self.mode = mode
        self._write_state()
        return self._response()

    def forward(self, data):
        if self.mode == "desktop":
            self.proxy.write(data)

    def _accept_command(self):
        connection, _ = self.server.accept()
        with connection:
            connection.settimeout(2.0)
            try:
                command = connection.recv(128).decode("ascii").strip()
                if command == "status":
                    response = self._response()
                else:
                    response = self.set_mode(command)
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
        self._write_state()

    def _open_device(self):
        node = find_real_event(
            self.config["DEVICE_NAME"], self.config["PROXY_PHYS"]
        )
        if node is None:
            return
        set_abs_y_min(node, int(self.config["DIRECT_Y_MIN"]))
        fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        self.device = node
        self.device_fd = fd
        self.selector.register(fd, selectors.EVENT_READ, "pen")
        self._write_state()

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

    def run(self):
        while self.running:
            if self.device_fd is None:
                try:
                    self._open_device()
                except OSError:
                    self._close_device()
            for key, _ in self.selector.select(timeout=1.0):
                if key.data == "control":
                    self._accept_command()
                elif key.data == "pen":
                    self._read_device()

    def close(self):
        self._close_device()
        try:
            self.selector.unregister(self.server)
        except Exception:
            pass
        self.server.close()
        Path(self.config["CONTROL_SOCKET"]).unlink(missing_ok=True)
        self.proxy.close()
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
