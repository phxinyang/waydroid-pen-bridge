# Waydroid Pen Bridge

English | [简体中文](README.zh-CN.md)

Waydroid Pen Bridge switches Xiaomi Pad 6S Pro (`sheng`) stylus input between
the **Linux desktop** and **Waydroid**.

It builds on [xiaomi-sheng-thp](https://github.com/ianchb/xiaomi-sheng-thp) and
routes pen traffic through stable uinput proxies to:

- the Linux desktop (Wayland)
- Waydroid (Android)

The desktop always sees the same set of proxy devices; switching the target does
not rebuild them.

## Features

- Automatic pen routing between Linux and Waydroid
- Stable uinput proxies that survive mode switches
- M80p, P81c, and optional Pro gesture sources
- Native integration for GNOME 50 and KDE Plasma 6
- RPM, DEB, and source installs

## How it works

`xiaomi-sheng-thp` provides M80p, P81c, and optional Pro gesture sources.

`waydroid-pen-relay` reads those sources and maintains stable uinput proxies.
Depending on policy and window focus, pen input is routed to the Linux desktop
or into Waydroid through LXC mounts.

Physical devices are hidden with `LIBINPUT_IGNORE_DEVICE`, so the desktop only
sees the proxies created by the relay. The relay keeps one long-lived proxy per
pen model and only switches which model is active. If a Pro gesture source is
present, a matching gesture proxy is created as well. Touch input always goes
through Wayland and never through the relay.

## Understanding policy and runtime mode

Two layers are easy to mix up:

| Layer | Who sets it | Values | Meaning |
|-------|-------------|--------|---------|
| **Policy** (tray / Quick Settings) | You | `auto` · `waydroid` · `desktop` | Long-lived preference |
| **Runtime mode** (relay) | Session + policy | `desktop` · `direct` | Where pen coordinates go right now |

Overall flow:

```text
Policy (auto / waydroid / desktop)
        │
        ▼
session (focus / Overview / sticky / tip-safe)
        │
        ▼
relay runtime mode (desktop or direct)
        │
        ▼
pen input → Linux or Android
```

### Policies (tray)

GNOME Quick Settings and the KDE System Tray expose the same three policies
(labels follow locale: Auto / Waydroid / Desktop, or 自动 / Waydroid / 桌面).

| Policy | Coordinates | Buttons / Pro gestures |
|--------|-------------|------------------------|
| **Auto** | `direct` while a Waydroid window is the effective focus; otherwise `desktop` | Same focus rules as below |
| **Waydroid** | Always `direct` (Android gets pen XY) | Waydroid focus is still required for button / gesture side channels where applicable |
| **Desktop** | Always `desktop` (Linux proxy gets pen XY) | If Waydroid is focused: pen buttons and Pro gestures can use an **Android side channel** without moving coordinates off the desktop |

**Auto details**

- Overview (GNOME/KDE) forces desktop routing while open.
- Focus is debounced; a short sticky window reduces thrash on brief focus loss.
- Mode switches are tip-safe: a pending change can wait until the tip is up.

**What policies do not do**

- The UI never shows the word `direct`; that name belongs to the relay runtime.
- Policies do not assign Notein / Starnote actions. That belongs in an Android
  compatibility module.

### Runtime modes (relay)

| Mode | Pen coordinates | Pen buttons (M80p) | Pro gestures (P81c) |
|------|-----------------|--------------------|---------------------|
| **desktop** | Host desktop proxies | Desktop proxy, or Android `event5` side channel when Waydroid is focused | Desktop gesture proxy, or Android gesture path when focused |
| **direct** | Android `event4` (active model) | On the pen node (`event4`) while focused; not dual-written to `event5` | On `event5` when the Pro source exists; Android maps scan codes to 194–197 when focused |

Shared rules:

- Both model proxies stay alive across mode switches; they are not destroyed and recreated.
- `event4` exists only in direct mode and always points at the active model.
- `event5` is created only when an Android side channel is needed.
- The same button event is never sent to two destinations.
- On focus loss or Overview entry, held Android pen buttons are released first.
- Samples outside the Waydroid content rectangle never enter Android
  (geometry comes from GNOME / KWin).

### Pressure and axes

| Model | Pressure | Notes |
|-------|----------|--------|
| M80p | `0..8191` | Stylus buttons `BTN_STYLUS` / `BTN_STYLUS2` |
| P81c | `0..16383` | Optional brake; Pro gestures are a separate device |

The Y axis is mapped from the live source range to a unified tablet coordinate
range without changing the pressure protocol.

### Android key mapping

This layer only maps Linux → Android key transport. It does not implement any
application-level behavior.

| Source | Scan codes | Android keycodes (typical) |
|--------|------------|----------------------------|
| Pen node (M80p / P81c) | 331 / 332 | 194 / 195 |
| Pro gesture device | 262–265 (`BTN_6`…`BTN_9`) | 194–197 |

P81c pen frames themselves do not invent 194/195. App actions (Notein, Starnote,
and so on) belong in a module such as `xiaomi-penengine-compat`, not in this
bridge.

## Requirements

- GNOME Shell 50 **or** KDE Plasma 6 / KWin 6
- Waydroid 1.6.x
- Python 3
- `sudo`, `systemd`, `udevadm`, `visudo`, LXC
- [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp) with M80p/P81c
  `2717:3654`, and optionally Pro gestures `0022:5081`

## Install

### Recommended: GitHub Release (RPM / DEB)

Tags `v*` build packages on Actions and attach them to
[Releases](https://github.com/phxinyang/waydroid-pen-bridge/releases).

```bash
# Fedora / RHEL-like
sudo dnf install ./waydroid-pen-bridge-*.noarch.rpm

# Debian / Ubuntu
sudo apt install ./waydroid-pen-bridge_*.deb
```

After graphical login, if the tray / extension is missing:

```bash
waydroid-pen-bridge-user-setup
```

### From source

For development or debugging:

```bash
./install.sh
```

Both paths need Waydroid’s LXC config and a working **xiaomi-sheng-thp** unit.
This project does **not** replace or uninstall the THP driver; it only hides
driver nodes from libinput and routes through proxies.

> [!NOTE]
> Reboot once after the first install so udev can hide physical pen devices
> before login and the relay can create stable proxies early.

`install.sh` also runs user UI setup when possible. If the panel is still
missing:

```bash
./user-setup.sh
# or: waydroid-pen-bridge-user-setup
```

- **GNOME:** enable extension `Waydroid Pen Mode` if needed.
- **KDE:** System Tray → Entries → Waydroid Pen Mode → **Shown**.

### Common commands

Check current status:

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

The following interfaces are mainly for the session. Day-to-day use usually
does not need them by hand:

```bash
sudo /usr/local/libexec/waydroid-pen-mode desktop
sudo /usr/local/libexec/waydroid-pen-mode direct
sudo /usr/local/libexec/waydroid-pen-mode sync
sudo /usr/local/libexec/waydroid-pen-mode focus 1
sudo /usr/local/libexec/waydroid-pen-mode focus 0
sudo /usr/local/libexec/waydroid-pen-mode map X Y WIDTH HEIGHT
sudo /usr/local/libexec/waydroid-pen-mode unmap
```

Prefer the **tray policy** for normal use. GNOME/KDE call `focus` / `map` from
window monitors.

The installer enables Android’s built-in palm-rejection flag inside Waydroid; it
applies on the next container start.

## Uninstall

```bash
./uninstall.sh
```

If the bridge was installed with **rpm/dnf** or **deb/apt**, `uninstall.sh`
detects that and removes the package via the package manager, then clears
desktop UI and prints a verification checklist. Pure `install.sh` installs use
the file-based cleanup path.

Uninstalling the bridge removes:

- relay / link-sync services
- udev rules, helpers, LXC pen mounts, Android overlay KL/KCM
- GNOME extension and KDE plasmoid / KWin script

It does **not** uninstall [xiaomi-sheng-thp](https://github.com/ianchb/xiaomi-sheng-thp).

THP is restarted so physical pens return without `LIBINPUT_IGNORE_DEVICE`. A
reboot is still recommended so every session rediscovers devices cleanly.

## Architecture

| Component | Role |
|-----------|------|
| `waydroid-pen-relay` | Root data plane: read THP → uinput proxies; control socket |
| `waydroid-pen-mode` | Root control: desktop/direct, focus, map, LXC `event4`/`event5` links |
| `waydroid-pen-session` | User session: policy + focus/Overview → mode helper |
| GNOME extension / KDE plasmoid + KWin script | UI + window geometry / focus |

## License

See [LICENSE](LICENSE).
