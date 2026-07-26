# Waydroid Pen Bridge

English | [简体中文](README.zh-CN.md)

**One tray toggle. Your pen, working on Linux and in Waydroid, without
sacrificing either side.**

I daily-drive a Xiaomi Pad 6S Pro (`sheng`), running Linux with Waydroid for
note-taking. Writing notes in Waydroid shouldn't break the desktop pen
experience. Switching between them shouldn't feel like juggling fragile
workarounds.

So I built a thin relay that sits between the [THP
driver](https://github.com/ianchb/xiaomi-sheng-thp) and the rest of the system,
giving each side its own stable pen proxy. It's fast enough that you probably
won't notice it's there.

## Quick try

Make sure [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp) is
installed and active. Then:

```bash
# From a release (RPM / DEB)
sudo dnf install ./waydroid-pen-bridge-*.noarch.rpm   # Fedora
sudo apt install ./waydroid-pen-bridge_*.deb           # Debian/Ubuntu

# Or from source
./install.sh

# Reboot once, then log in
waydroid-pen-bridge-user-setup   # if you don't see the tray icon
```

You'll get a tray toggle with **Auto / Waydroid / Desktop**. That's it — flip
to what you need and keep writing.

To get rid of it:

```bash
./uninstall.sh
```

Works whether you installed via rpm, deb, or source. Leaves THP alone.

## How it works

The THP driver creates M80p and P81c pen devices (and optionally Pro gestures).
My relay hides those from the desktop so neither side fights over the same
physical node. Instead, it creates **resident proxies** for each model —
one for Linux, one for Android — and routes to whichever the tray says.

Two concepts to keep straight because they're easy to mix up:

| What | Where you see it | What it means |
|------|------------------|---------------|
| **Policy** | Tray / Quick Settings | `auto` / `waydroid` / `desktop` — your long-term preference |
| **Runtime** | The relay inside | `desktop` / `direct` — where pen coordinates actually go right now |

Policy → session (focus, Overview, sticky timing) → runtime. Tray says "auto";
the session decides whether the current situation means `desktop` or `direct`.

### What the three policies do

**Auto.** I recommend this for daily use. It follows Waydroid focus: pen goes
direct when Waydroid has the active window, otherwise stays on the desktop.
Overview mode forces desktop routing. Focus is debounced so brief blips don't
toggle. Mode changes wait for pen lift when that makes sense.

**Waydroid.** Pen coordinates always route to Android. Buttons and Pro gestures
still need a focused Waydroid window where applicable.

**Desktop.** Pen coordinates always stay on Linux. But if Waydroid has focus,
ordinary stylus buttons and Pro gestures can ride a separate side channel into
Android — so you get button actions inside Waydroid apps without moving the pen
away from the desktop.

### Runtime: desktop vs direct

| Mode | Pen XY | M80p buttons | P81p Pro gestures |
|------|--------|--------------|--------------------|
| **desktop** | Desktop proxies | Desktop proxy; or Android `event5` side-channel when Waydroid is focused | Desktop gesture proxy, or Android gesture path when focused |
| **direct** | Android `event4` (active model) | On the pen node, not re-sent to `event5` | Android `event5`; scan codes map to keycodes 194–197 when focused |

### Pressure and buttons (short version)

M80p gives `0..8191` with `BTN_STYLUS`/`BTN_STYLUS2`. P81c gives `0..16383`
with optional brake and a separate gesture device. Y gets mapped from the live
source range to the stable tablet space without touching pressure ranges.

This bridge only delivers the key events; it doesn't assign what Starnote or
Notein *do* with them. That's up to a compat layer like
[`xiaomi-penengine-compat`](https://github.com/phxinyang).

### The one-destination rule

Every button frame goes to exactly one place. Desktop focus? Desktop proxy.
Focused direct with an ordinary pen? `event4`. Desktop+focus side channel?
`event5`. No dual-delivery.

### GNOME and KDE

Both work. The tray / Quick Settings toggle is the same; there's also a KWin
script and a GNOME extension that feed window geometry and focus changes to
the session, so the relay knows where Waydroid is on screen and whether it's
in focus. Pen events outside Waydroid's content rectangle are suppressed in
Android.

## Requirements

- A sheng tablet running Fedora (or similar with GNOME 50+ / KDE Plasma 6)
- Waydroid 1.6.x
- [`xiaomi-sheng-thp`](https://github.com/ianchb/xiaomi-sheng-thp) (provides M80p/P81c, optionally Pro gestures)
- Python 3, `sudo`, `systemd`, LXC

## Looking under the hood

Four pieces, but you usually only touch the tray:

| Piece | Lives at | Does |
|-------|----------|------|
| `waydroid-pen-relay` | `root` | Reads THP, writes uinput proxies, talks over a unix socket |
| `waydroid-pen-mode` | `root` | Desktop/direct switching, focus, map, LXC `event4`/`event5` |
| `waydroid-pen-session` | `user` | Policy + context → mode helper calls |
| Tray / extension | DE | GNOME Quick Settings or KDE System Tray toggles |

If something feels off, start here:

```bash
sudo /usr/local/libexec/waydroid-pen-mode status
```

For low-level tests (you usually don't need these):

```bash
sudo /usr/local/libexec/waydroid-pen-mode desktop
sudo /usr/local/libexec/waydroid-pen-mode direct
sudo /usr/local/libexec/waydroid-pen-mode focus 1
sudo /usr/local/libexec/waydroid-pen-mode focus 0
sudo /usr/local/libexec/waydroid-pen-mode map X Y WIDTH HEIGHT
sudo /usr/local/libexec/waydroid-pen-mode unmap
```

## Uninstall

```bash
./uninstall.sh
```

If the bridge was installed via rpm or deb, the script uses the package
manager, then cleans up desktop UI and prints what it found. If it was from
`./install.sh`, it does the file-level cleanup directly. Either way, THP stays.

## A note on latency

On desktop, the relay's host-side overhead is around **p50 ~0.04 ms** (Rust
build). The bottleneck for Waydroid note taking is the Android input stack and
the app itself, not this bridge.

If you're curious, see the `rust-rewrite` branch for the Rust data plane.

## License

MIT — [LICENSE](LICENSE)
