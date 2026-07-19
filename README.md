# Waydroid Pen Mode

Routes the Xiaomi Pad 6S Pro (`sheng`) pen between the desktop and Waydroid
without hot-removing a tablet device from the compositor.

The physical `NVTCapacitivePenM80p` device is always ignored by libinput. A
small system service creates stable virtual pens for the desktop and Android
and keeps both for the full login session.

## Policies

The GNOME Quick Settings menu provides three policies:

- **自动:** follow the focused window.
- **Waydroid:** always send the physical evdev pen to Android.
- **桌面:** always forward the physical pen to the stable GNOME proxy.

Screen touch and Bluetooth gesture/button devices continue through Wayland in
all three policies.

The installer also enables Android's built-in palm rejection flag inside
Waydroid. It takes effect the next time the Waydroid container starts.

## Runtime modes

- **Desktop:** the relay copies pen events to the stable desktop proxy and the
  Android direct link is absent.
- **Direct:** the relay releases and pauses the desktop proxy, maps physical
  screen coordinates into the Waydroid content rectangle, and writes the
  transformed events to the Android proxy.

No input device is created or destroyed while changing modes.

The GNOME extension follows Waydroid window moves, resizes, fullscreen changes,
monitor scale and monitor position. Pen events outside the Waydroid content
rectangle are suppressed in Android.

## Requirements

- GNOME Shell 50
- Waydroid 1.6.x
- Python 3
- `sudo`, `systemd`, `udevadm`, `visudo` and LXC
- `xiaomi-sheng-thp.service`

## Install

```bash
./install.sh
```

Reboot once after installation. The reboot lets udev hide the physical pen
before GNOME starts and lets the relay create the stable proxy before login.
Then enable the `Waydroid Pen Mode` GNOME extension.

Check the current runtime mode:

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

Manual runtime selection:

```bash
sudo /usr/local/libexec/waydroid-pen-mode desktop
sudo /usr/local/libexec/waydroid-pen-mode direct
```

Set a normalized Waydroid content rectangle manually:

```bash
sudo /usr/local/libexec/waydroid-pen-mode map X Y WIDTH HEIGHT
sudo /usr/local/libexec/waydroid-pen-mode unmap
```

`unmap` restores full-display identity mapping.

## Uninstall

```bash
./uninstall.sh
```

Reboot after uninstalling so the proxy exits outside the GNOME session and the
physical pen becomes visible to libinput again.
