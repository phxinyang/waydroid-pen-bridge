# Waydroid Pen Bridge

English | [简体中文](README.zh-CN.md)

Routes the Xiaomi Pad 6S Pro (`sheng`) pen between the desktop and Waydroid
without hot-removing a tablet device from the compositor.

The driver-created M80p and P81c pen devices are ignored by libinput. A small
system service keeps one stable proxy for each model, selects the source that
is actually producing frames, and creates an optional Pro gesture proxy.

## Policies

The GNOME Quick Settings menu and KDE Plasma System Tray provide the same three
policies:

- **Auto:** follow the focused window.
- **Waydroid:** always send the physical evdev pen coordinates to Android. Pen
  button events still require a focused Waydroid window.
- **Desktop:** always forward the physical pen to the stable desktop proxy. When a
  Waydroid window is focused, ordinary pen buttons and Focus Pen Pro gestures
  use a separate Android side channel without changing the pen-coordinate
  route.

Screen touch continues through Wayland. The bridge preserves ordinary
`BTN_STYLUS`/`BTN_STYLUS2` and Pro `BTN_6` through `BTN_9` codes on Linux. It
does not assign application actions to them. The M80p proxy advertises native
pressure `0..8191`, and the P81c proxy advertises native pressure `0..16383`.
The source Y range is mapped to the stable tablet Y range without changing
either pressure range or destroying a proxy during a pen switch.

The installer also enables Android's built-in palm rejection flag inside
Waydroid. It takes effect the next time the Waydroid container starts.

## Runtime modes

- **Desktop:** an ordinary pen keeps its standard buttons and Focus Pen Pro
  keeps `BTN_6`/`BTN_7`/`BTN_8`/`BTN_9` unchanged on the desktop proxies.
  Android `event4` is absent. While a Waydroid window has focus, the active
  pen's button path is routed through Android `event5` instead of the desktop
  button destination.
- **Direct with an ordinary pen:** Android `event4` points at the pen proxy and
  keeps `BTN_STYLUS`/`BTN_STYLUS2` while the Waydroid window is focused.
  Android `event5` is not linked for ordinary-button transport in direct mode.
- **Direct with Focus Pen Pro:** P81c pen frames use `event4`. The separate Pro
  gesture source keeps scan codes 262, 263, 264, and 265 (`BTN_6` through
  `BTN_9`) on `event5`. Android maps them to key codes 194 through 197 while
  the host Waydroid window has focus.

The two model pen proxies remain stable while changing modes. Android `event4`
exists only in direct mode and points at the current active model. Android
`event5` is linked only when the focused side channel needs it; the Pro proxy
is created only while the physical Pro gestures source exists. Losing focus or
entering an Overview releases all active Android pen buttons before further
routing changes.

Each button action uses one destination: its normal desktop proxy for desktop
focus, Android `event4` for an ordinary pen in focused direct mode, or Android
`event5` for the focused desktop side channel and Pro gestures. The relay never
writes the same button frame to two destinations.

The GNOME extension and KWin script follow Waydroid window moves, resizes,
fullscreen changes, monitor scale and monitor position. Pen events outside the
Waydroid content rectangle are suppressed in Android. GNOME Overview and KDE
Overview temporarily select desktop routing while the policy is automatic.

Android's keylayout performs only transport conversion. On the M80p/P81c
pen device, scan codes `331/332` become `BUTTON_7/8`, which Android exposes as
key codes `194/195`. On the Pro gesture device, scan codes `262–265` become
`BUTTON_7–10`, exposed as `194–197`. P81c itself does not generate `194/195`;
those two codes come from the gesture or ordinary-button transport and are
handled by `xiaomi-penengine-compat`.
Per-application behavior belongs in an Android compatibility module such as
`xiaomi-penengine-compat`; the bridge does not contain Notein, Starnote, or
other application-specific actions.

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

`install.sh` requires Waydroid's LXC config and the
[`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp) unit. It does
not replace or uninstall that driver; it only hides the driver nodes from
libinput and routes them through stable proxies.

Reboot once after installation. The reboot lets udev hide the physical pen
before the desktop starts and lets the relay create the stable proxy before
login. Then enable the `Waydroid Pen Mode` GNOME extension. On KDE, the
installer enables the KWin script and adds `Waydroid Pen Mode` to the System
Tray.

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

`focus 1` enables the active pen's Android button route after checking
`event5`; `focus 0` releases all Android pen buttons immediately. GNOME and KDE
call these commands automatically from their window-focus monitors.

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

Uninstall removes the bridge only:

- stops and disables `waydroid-pen-relay` / link-sync
- removes udev rules, helpers, LXC pen mounts, Android overlay KL/KCM
- removes GNOME/KDE integration
- leaves [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp) installed

It also reloads udev and re-triggers the THP pen nodes so libinput can see the
physical driver devices again. A reboot is still recommended so every session
picks up the restored devices cleanly.
