<div align="center">
  <h1>Waydroid Pen Bridge</h1>
  <p><b>One tray toggle. Your pen, working on Linux and in Waydroid.</b></p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
</div>

English | [简体中文](README.zh-CN.md)

## Features

- Automatic routing between Linux and Waydroid that follows window focus
- Stable uinput proxies that survive every switch, so the desktop keeps seeing one set of devices
- Both pen models handled live: M80p (`0..8191` pressure) and P81c (`0..16383`, with brake), plus optional Pro gestures
- Tip, pressure, tilt, and stylus buttons preserved on both sides
- Native tray UI for GNOME 50 and KDE Plasma 6
- Ships as RPM, DEB, or a source install

## Requirements

- Xiaomi Pad 6S Pro (`sheng`) with [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp) providing the M80p / P81c pen (`2717:3654`), optionally Pro gestures (`0022:5081`)
- GNOME Shell 50 **or** KDE Plasma 6 / KWin 6
- Waydroid 1.6.x with its LXC container configured
- Python 3, `systemd`, and the usual root tools (`sudo`, `udevadm`, `visudo`, LXC)

## Install

Grab a package from [Releases](https://github.com/phxinyang/waydroid-pen-bridge/releases):

**Fedora / RHEL-like**

```bash
sudo dnf install ./waydroid-pen-bridge-*.noarch.rpm
```

**Debian / Ubuntu**

```bash
sudo apt install ./waydroid-pen-bridge_*.deb
```

**From source**

```bash
./install.sh
```

Every path needs a working `xiaomi-sheng-thp` unit and Waydroid's LXC config:
the bridge routes the THP pen, it does not replace it.

> [!NOTE]
> Reboot once after the first install so udev hides the physical pen before login
> and the relay can bring its proxies up early.

If the tray toggle is missing after you log in:

```bash
waydroid-pen-bridge-user-setup   # or ./user-setup.sh from a source checkout
```

- **GNOME:** enable the *Waydroid Pen Mode* extension.
- **KDE:** System Tray → Entries → *Waydroid Pen Mode* → **Shown**.

## Use

The tray toggle (GNOME Quick Settings or the KDE System Tray) offers three
policies. Labels follow your locale (Auto / Waydroid / Desktop).

| Policy | Pen goes to | Notes |
|--------|-------------|-------|
| **Auto** (default) | Waydroid when a Waydroid window is focused, the desktop otherwise | What you want almost all the time |
| **Waydroid** | Always into Android | For a full note-taking session |
| **Desktop** | Always the Linux desktop | Stylus buttons and Pro gestures can still reach a focused Waydroid app through a side channel |

Leave it on **Auto** and forget about it. To see what the relay is doing:

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

The `desktop`, `direct`, `focus`, `map`, and `unmap` subcommands exist too, but
the session calls them for you.

## How it works

`xiaomi-sheng-thp` exposes the raw M80p and P81c pen nodes, plus a Pro gesture
node when present. udev hides them from libinput, so the desktop never reads
them directly; it only sees the proxies the relay creates.

`waydroid-pen-relay` runs as root and reads whichever pen is producing frames.
Each model gets two resident proxies, one for the desktop and one hidden for
Android, plus side channels for stylus buttons and Pro gestures. The proxies
live as long as the relay does; switching models or modes never tears one down,
it only changes which proxy gets written.

Which one gets written is decided in two layers:

- **Policy**: the `auto` / `waydroid` / `desktop` you pick in the tray. A long-lived preference.
- **Runtime mode**: the relay's current `desktop` or `direct`, computed by the session from policy, window focus, and Overview, with debounce and stickiness on top. You never set it directly.

In `desktop` mode pen frames go to the desktop proxy, passed through untouched
when they already match its axis layout, which keeps the pen hot path light. In
`direct` mode the relay maps frames into the focused Waydroid window's content
rectangle and feeds the hidden proxies through LXC; samples outside the
rectangle are dropped.

Three rules hold throughout: an event goes to exactly one destination; a mode
switch waits for pen lift instead of cutting a stroke; losing focus or entering
Overview releases any held Android buttons first.

## Details

**Runtime modes**

| Mode | Pen coordinates | Stylus buttons (M80p) | Pro gestures (P81c) |
|------|-----------------|-----------------------|---------------------|
| **desktop** | Desktop proxy | Desktop proxy; or an Android side channel (`event5`) when Waydroid is focused | Desktop gesture proxy; or the Android gesture path when focused |
| **direct** | Android `event4` (active model) | On the pen's own Android node | On `event5` when a Pro source exists |

**Pressure and axes**

| Model | Pressure | Extras |
|-------|----------|--------|
| M80p | `0..8191` | `BTN_STYLUS` / `BTN_STYLUS2` |
| P81c | `0..16383` | brake axis; Pro gestures are a separate device |

Both proxies expose the same tablet space (X `0..30479`, Y `0..20319`). The relay
maps each source's live Y range onto it and clamps pressure to the model's own
range; it never rewrites the pressure protocol.

**Android key mapping**

The Android keylayout overlay maps the driver's Linux key codes onto Android's
stable `BUTTON_7..BUTTON_10` transport. Turning that transport into app actions
(for example keycodes 194-197 for Notein / Starnote) is a separate compat layer's
job, not this bridge's.

| Source | Linux codes | Android transport |
|--------|-------------|-------------------|
| Pen buttons (M80p / P81c) | 331 / 332 | `BUTTON_7` / `BUTTON_8` |
| Pro gestures | 262-265 | `BUTTON_7..BUTTON_10` |

## Architecture

| Component | Runs as | Role |
|-----------|---------|------|
| `waydroid-pen-relay` | root | Reads the THP pen nodes, owns the uinput proxies, exposes a control socket |
| `waydroid-pen-mode` | root | Applies desktop/direct, focus, and geometry; manages the LXC `event4` / `event5` links |
| `waydroid-pen-session` | user | Turns policy + focus / Overview into mode-helper calls |
| GNOME extension · KDE plasmoid + KWin script | user session | The tray toggle, plus window geometry and focus reporting |

## Uninstall

```bash
./uninstall.sh
```

## License

MIT License. See [LICENSE](LICENSE).
