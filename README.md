# Waydroid Pen Bridge

English | [简体中文](README.zh-CN.md)

Route the Xiaomi Pad 6S Pro (`sheng`) stylus between the **Linux desktop** and
**Waydroid** without hot-removing the tablet device from the compositor.

The [THP driver](https://github.com/ianchb/xiaomi-sheng-thp) exposes M80p, P81c,
and optional Pro gesture nodes. **waydroid-pen-relay** reads those sources and
feeds stable dual-model proxies (plus an optional gesture proxy). From there,
pen traffic goes either to the **desktop** stack or into **Android** through LXC
input mounts—whichever the current policy and focus require.

Physical driver nodes are ignored by libinput so the desktop only sees the
proxies. The relay keeps **one resident proxy per pen model**, activates the
model that is producing frames, and creates Pro gesture proxies only while that
source exists. Touchscreen input stays on Wayland.

## Concepts (read this first)

Two layers are easy to confuse:

| Layer | Who sets it | Values | Meaning |
|-------|-------------|--------|---------|
| **Policy** (tray / Quick Settings) | You | `auto` · `waydroid` · `desktop` | Long-lived preference |
| **Runtime mode** (relay) | Session + policy | `desktop` · `direct` | Where **pen coordinates** go right now |

Flow: choose a **policy** in the tray → the **session** applies focus, Overview,
sticky timing, and tip-safe switching → the relay runs in **`desktop` or
`direct`**.

## Policies (tray)

GNOME Quick Settings and the KDE System Tray expose the same three policies
(labels follow locale: Auto / Waydroid / Desktop, or 自动 / Waydroid / 桌面).

| Policy | Coordinates | Buttons / Pro gestures |
|--------|-------------|-------------------------|
| **Auto** | `direct` while a Waydroid window is the effective focus; otherwise `desktop` | Follow the same focus rules as below |
| **Waydroid** | Always `direct` (Android gets pen XY) | Still need Waydroid focus for button / gesture side channels where applicable |
| **Desktop** | Always `desktop` (Linux proxy gets pen XY) | If Waydroid is focused: ordinary buttons + Pro gestures can use an **Android side channel** without moving coordinates off the desktop |

**Auto details**

- Overview (GNOME/KDE) forces desktop routing while the overview is open.
- Focus is debounced; a short **sticky** window reduces thrash on brief focus loss.
- Mode switches are **tip-safe**: a pending change waits until the tip is up when needed.

**What policies are not**

- They are not the same strings as runtime mode (`direct` never appears in the tray).
- They do not assign Notein/Starnote actions; that belongs in an Android compat module.

## Runtime modes (relay)

| Mode | Pen coordinates | Ordinary pen buttons (M80p) | Pro gestures (P81c) |
|------|-----------------|-----------------------------|---------------------|
| **desktop** | Host desktop proxies | Desktop proxy, **or** Android `event5` side channel when Waydroid is focused | Desktop gesture proxy, or Android gesture path when focused / policy needs it |
| **direct** | Android `event4` → active model proxy | On the pen node (`event4`) while focused; not dual-written to `event5` | Gestures on `event5` when the Pro source exists; Android maps scan codes to 194–197 when focused |

Shared rules:

- Both model proxies stay alive across mode switches (no destroy/recreate thrash).
- `event4` exists only in **direct** and points at the **active** model.
- `event5` is linked only when a side channel needs it.
- **One destination per button frame** — never dual-write the same press.
- Losing focus or entering Overview releases held Android pen buttons before further routing.
- Outside the Waydroid content rectangle, pen samples are suppressed for Android (geometry from GNOME/KWin).

### Pressure and axes

| Model | Pressure | Notes |
|-------|----------|--------|
| M80p | `0..8191` | Stylus buttons `BTN_STYLUS` / `BTN_STYLUS2` |
| P81c | `0..16383` | Optional brake; Pro gestures are a **separate** device |

Y is mapped from the live source range to the stable tablet range without
changing pressure contracts.

### Android key transport (not app actions)

Keylayout only remaps scan codes for transport:

| Source | Scan codes | Android keycodes (typical) |
|--------|------------|----------------------------|
| Ordinary pen / M80p–P81c pen node | 331 / 332 | 194 / 195 |
| Pro gesture device | 262–265 (`BTN_6`…`BTN_9`) | 194–197 |

P81c pen frames themselves do not invent 194/195. App behavior (Notein, Starnote,
…) belongs in something like [`xiaomi-penengine-compat`](https://github.com/phxinyang)
— not in this bridge.

## Requirements

- GNOME Shell 50 **or** KDE Plasma 6 / KWin 6  
- Waydroid 1.6.x  
- Python 3  
- `sudo`, `systemd`, `udevadm`, `visudo`, LXC  
- [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp) providing
  M80p/P81c `2717:3654`, and optionally Pro gestures `0022:5081`

## Install

### From a GitHub Release (RPM / DEB)

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

```bash
./install.sh
```

Both paths need Waydroid’s LXC config and a working **xiaomi-sheng-thp** unit.
This project does **not** replace or uninstall the THP driver; it only ignores
driver nodes for libinput and routes through proxies.

**Reboot once** after first install so udev hides physical pens before login and
the relay creates stable proxies early.

`install.sh` also runs user UI setup when possible. If the panel is still missing:

```bash
./user-setup.sh
# or: waydroid-pen-bridge-user-setup
```

- **GNOME:** enable extension `Waydroid Pen Mode` if needed.  
- **KDE:** System Tray → Entries → Waydroid Pen Mode → **Shown**.

### Check status

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

Low-level runtime knobs (normally driven by the session, not by hand):

```bash
sudo /usr/local/libexec/waydroid-pen-mode desktop
sudo /usr/local/libexec/waydroid-pen-mode direct
sudo /usr/local/libexec/waydroid-pen-mode sync
sudo /usr/local/libexec/waydroid-pen-mode focus 1   # enable Android button route when ready
sudo /usr/local/libexec/waydroid-pen-mode focus 0   # release Android pen buttons
sudo /usr/local/libexec/waydroid-pen-mode map X Y WIDTH HEIGHT   # normalized content rect
sudo /usr/local/libexec/waydroid-pen-mode unmap                  # full-display identity
```

GNOME/KDE call `focus` / `map` from window monitors. Prefer the **tray policy**
for day-to-day use.

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

Removes **only the bridge**:

- stops relay / link-sync  
- udev rules, helpers, LXC pen mounts, Android overlay KL/KCM  
- GNOME extension and KDE plasmoid / KWin script  
- **keeps** [xiaomi-sheng-thp](https://github.com/ianchb/xiaomi-sheng-thp)

THP is restarted so physical pens return without `LIBINPUT_IGNORE_DEVICE`. A
reboot is still recommended so every session rediscovers devices cleanly.

## Architecture (short)

| Component | Role |
|-----------|------|
| `waydroid-pen-relay` | Root data plane: read THP → uinput proxies; control socket |
| `waydroid-pen-mode` | Root control: desktop/direct, focus, map, LXC `event4`/`event5` links |
| `waydroid-pen-session` | User session: policy + focus/Overview → mode helper |
| GNOME extension / KDE plasmoid + KWin script | UI + window geometry / focus |

## License

See [LICENSE](LICENSE).
