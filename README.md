# Waydroid Pen Mode

Routes the Xiaomi Pad 6S Pro (`sheng`) pen between the desktop and Waydroid
without hot-removing a tablet device from the compositor.

The driver-created `NVTCapacitivePenM80p` device is always ignored by libinput.
A small system service creates stable pen and gesture proxies for the desktop
and Android and keeps those proxies for the full login session.

## Policies

The GNOME Quick Settings menu and KDE Plasma System Tray provide the same three
policies:

- **自动:** follow the focused window.
- **Waydroid:** always send the physical evdev pen to Android.
- **桌面:** always forward the physical pen to the stable GNOME proxy.

Screen touch continues through Wayland. Focus Pen Pro slide gestures use the
dedicated gesture proxies in desktop and direct modes.

The installer also enables Android's built-in palm rejection flag inside
Waydroid. It takes effect the next time the Waydroid container starts.

## Runtime modes

- **Desktop:** the relay copies the standard pen buttons to the stable desktop
  tablet and forwards Pro slide up/down as `KEY_PROG3`/`KEY_PROG4`. Android
  event links are absent.
- **Direct with an ordinary pen:** Android `event4` points at the pen proxy and
  keeps `BTN_STYLUS`/`BTN_STYLUS2`. Android `event5` is absent.
- **Direct with Focus Pen Pro:** `event4` suppresses the two standard stylus
  buttons. The relay emits pinch, double press, slide up, and slide down once on
  the Android gesture proxy as scan codes 148, 149, 202, and 203. Android maps
  them to key codes 194 through 197 on `event5`.

The bridge proxies remain stable while changing modes. Only Android's `event5`
link is added or removed when Focus Pen Pro availability changes.

The GNOME extension and KWin script follow Waydroid window moves, resizes,
fullscreen changes, monitor scale and monitor position. Pen events outside the
Waydroid content rectangle are suppressed in Android. GNOME Overview and KDE
Overview temporarily select desktop routing while the policy is automatic.

## Requirements

- GNOME Shell 50 or KDE Plasma 6 / KWin 6
- Waydroid 1.6.x
- Python 3
- `sudo`, `systemd`, `udevadm`, `visudo` and LXC
- The refactored `xiaomi-sheng-thp.service`, using `BUS_VIRTUAL` devices
  `2717:3654` for the standard pen and optional `2717:3655` for Pro slides

## Install

```bash
./install.sh
```

Reboot once after installation. The reboot lets udev hide the physical pen
before GNOME starts and lets the relay create the stable proxy before login.
Then enable the `Waydroid Pen Mode` GNOME extension. On KDE, the installer
enables the KWin script and adds `Waydroid Pen Mode` to the System Tray.

Check the current runtime mode:

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

Manual runtime selection:

```bash
sudo /usr/local/libexec/waydroid-pen-mode desktop
sudo /usr/local/libexec/waydroid-pen-mode direct
sudo /usr/local/libexec/waydroid-pen-mode sync
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
