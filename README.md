# Waydroid Pen Mode

English | [简体中文](README.zh-CN.md)

Routes the Xiaomi Pad 6S Pro (`sheng`) pen between the desktop and Waydroid
without hot-removing a tablet device from the compositor.

The driver-created M80p and P81c pen devices are ignored by libinput. A small
system service selects the active source and creates stable pen and gesture
proxies for the desktop and Android.

## Policies

The GNOME Quick Settings menu and KDE Plasma System Tray provide the same three
policies:

- **自动:** follow the focused window.
- **Waydroid:** always send the physical evdev pen coordinates to Android. Pro
  button events still require a focused Waydroid window.
- **桌面:** always forward the physical pen to the stable desktop proxy. When a
  Waydroid window is focused, Focus Pen Pro buttons use a separate Android
  side channel without changing the pen-coordinate route.

Screen touch continues through Wayland. Focus Pen Pro slide gestures use the
dedicated gesture proxies in desktop and direct modes. The bridge preserves
the driver's `BTN_6` through `BTN_9` codes and does not assign application
actions to them.

The installer also enables Android's built-in palm rejection flag inside
Waydroid. It takes effect the next time the Waydroid container starts.

## Runtime modes

- **Desktop:** an ordinary pen keeps its standard buttons. Focus Pen Pro keeps
  `BTN_6`/`BTN_7`/`BTN_8`/`BTN_9` unchanged on the stable desktop gesture
  proxy. Android `event4` is absent. While a Waydroid window has focus, the
  same raw Pro button frames are routed through Android `event5` instead of
  the desktop gesture proxy.
- **Direct with an ordinary pen:** Android `event4` points at the pen proxy and
  keeps `BTN_STYLUS`/`BTN_STYLUS2`. Android `event5` is absent.
- **Direct with Focus Pen Pro:** P81c pen frames use `event4`. The separate Pro
  gesture source keeps scan codes 262, 263, 264, and 265 (`BTN_6` through
  `BTN_9`) on `event5`. Android maps them to key codes 194 through 197 while
  the host Waydroid window has focus.

The bridge proxies remain stable while changing modes. Android `event4` exists
only in direct mode. Android `event5` exists while Focus Pen Pro is available,
including desktop mode whenever the Waydroid container is running, but the
relay writes Pro button events only while a Waydroid window has focus. Losing
focus or entering an Overview releases all active Android Pro buttons before
further routing changes.

Each Pro action uses one destination: the desktop raw gesture proxy for normal
desktop focus, or Android `event5` for Waydroid focus. The relay never writes
the same button frame to both destinations.

The GNOME extension and KWin script follow Waydroid window moves, resizes,
fullscreen changes, monitor scale and monitor position. Pen events outside the
Waydroid content rectangle are suppressed in Android. GNOME Overview and KDE
Overview temporarily select desktop routing while the policy is automatic.

Android's keylayout performs only the transport conversion from the four Linux
scan codes to key codes 194 through 197. Per-application behavior belongs in an
Android compatibility module such as `xiaomi-penengine-compat`; the bridge does
not contain Notein, Starnote, or other application-specific actions.

## Requirements

- GNOME Shell 50 or KDE Plasma 6 / KWin 6
- Waydroid 1.6.x
- Python 3
- `sudo`, `systemd`, `udevadm`, `visudo` and LXC
- [`xiaomi-sheng-thp.service`](https://github.com/ianchb/xiaomi-sheng-thp) with
  M80p/P81c `2717:3654` pen nodes and the
  optional `0022:5081` `Xiaomi Focus Pen Pro Gestures` node

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
sudo /usr/local/libexec/waydroid-pen-mode focus 1
sudo /usr/local/libexec/waydroid-pen-mode focus 0
```

`focus 1` enables the Pro Android side channel after checking `event5`;
`focus 0` releases all Android Pro buttons immediately. GNOME and KDE call
these commands automatically from their window-focus monitors.

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
