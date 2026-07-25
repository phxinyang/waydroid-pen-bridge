#!/usr/bin/env bash
# Configure the current desktop user session after system install.
# Safe to re-run. Does not require root for most steps; uses the login session.
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
UUID=waydroid-pen-mode@sheng
KWIN_ID=waydroid-pen-mode
PLASMOID_ID=org.xinyang.waydroidpenmode
# Prefer the real login user.  When root runs `sudo -u alice`, SUDO_USER is often
# still "root"; never install UI into /root in that case.
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != root ]]; then
    INSTALL_USER=$SUDO_USER
else
    INSTALL_USER=$USER
fi
if [[ "$INSTALL_USER" == root ]]; then
    echo "Refusing to configure desktop UI for root; run as the desktop user." >&2
    exit 1
fi
INSTALL_HOME=$(getent passwd "$INSTALL_USER" | cut -d: -f6)
EXTENSION_DIR="$INSTALL_HOME/.local/share/gnome-shell/extensions/$UUID"
POLICY_DIR="$INSTALL_HOME/.config/waydroid-pen-mode"
USER_UNIT_DIR="$INSTALL_HOME/.config/systemd/user"

if [[ -z "$INSTALL_HOME" || "$INSTALL_HOME" != /* || "$INSTALL_HOME" == / ]]; then
    echo "Invalid home for $INSTALL_USER: $INSTALL_HOME" >&2
    exit 1
fi

run_as_user() {
    if [[ "$(id -un)" == "$INSTALL_USER" ]]; then
        "$@"
    else
        sudo -u "$INSTALL_USER" -- "$@"
    fi
}

# Prefer the interactive user session bus when available.
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -S "/run/user/$(id -u "$INSTALL_USER")/bus" ]]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u "$INSTALL_USER")"
    export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$INSTALL_USER")/bus"
fi

echo "Configuring desktop UI for user: $INSTALL_USER"

# Policy default + user systemd units (also installed by install.sh; keep idempotent).
install -d -m 0700 "$POLICY_DIR"
if [[ ! -f "$POLICY_DIR/policy" ]]; then
    printf '%s\n' auto >"$POLICY_DIR/policy"
    chown "$INSTALL_USER:" "$POLICY_DIR/policy" 2>/dev/null || true
fi
install -d -m 0755 "$USER_UNIT_DIR"
install -m 0644 \
    "$ROOT_DIR/config/waydroid-pen-session@.service" \
    "$USER_UNIT_DIR/waydroid-pen-session@.service"
install -m 0644 \
    "$ROOT_DIR/config/waydroid-pen-session-reapply.service" \
    "$USER_UNIT_DIR/waydroid-pen-session-reapply.service"
install -m 0644 \
    "$ROOT_DIR/config/waydroid-pen-session.path" \
    "$USER_UNIT_DIR/waydroid-pen-session.path"
chown -R "$INSTALL_USER:" "$USER_UNIT_DIR"/waydroid-pen-session* 2>/dev/null || true

if command -v systemctl >/dev/null 2>&1; then
    run_as_user systemctl --user daemon-reload || true
    run_as_user systemctl --user enable waydroid-pen-session.path >/dev/null 2>&1 || true
    run_as_user systemctl --user reset-failed \
        waydroid-pen-session-reapply.service \
        waydroid-pen-session.path >/dev/null 2>&1 || true
    run_as_user systemctl --user restart waydroid-pen-session.path >/dev/null 2>&1 || true
fi

# GNOME extension files + enable.
install -d -m 0755 "$EXTENSION_DIR"
install -m 0644 "$ROOT_DIR/extension/extension.js" "$EXTENSION_DIR/extension.js"
install -m 0644 "$ROOT_DIR/extension/metadata.json" "$EXTENSION_DIR/metadata.json"
chown -R "$INSTALL_USER:" "$EXTENSION_DIR" 2>/dev/null || true
if command -v gnome-extensions >/dev/null 2>&1; then
    run_as_user gnome-extensions enable "$UUID" >/dev/null 2>&1 || true
    echo "GNOME: extension files installed; enable '$UUID' if not already enabled."
fi

# KDE packages + tray visibility.
if command -v kpackagetool6 >/dev/null 2>&1; then
    if run_as_user kpackagetool6 --type KWin/Script --show "$KWIN_ID" >/dev/null 2>&1; then
        run_as_user kpackagetool6 --type KWin/Script --upgrade "$ROOT_DIR/kde/kwin" >/dev/null 2>&1 || true
    else
        run_as_user kpackagetool6 --type KWin/Script --install "$ROOT_DIR/kde/kwin" >/dev/null 2>&1 || true
    fi
    if run_as_user kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID" >/dev/null 2>&1; then
        run_as_user kpackagetool6 --type Plasma/Applet --upgrade "$ROOT_DIR/kde/plasmoid" >/dev/null 2>&1 || true
    else
        run_as_user kpackagetool6 --type Plasma/Applet --install "$ROOT_DIR/kde/plasmoid" >/dev/null 2>&1 || true
    fi
fi

if command -v kwriteconfig6 >/dev/null 2>&1; then
    run_as_user kwriteconfig6 --file kwinrc --group Plugins \
        --key "${KWIN_ID}Enabled" true >/dev/null 2>&1 || true
fi

if command -v gdbus >/dev/null 2>&1; then
    run_as_user gdbus call --session --dest org.kde.KWin --object-path /Scripting \
        --method org.kde.kwin.Scripting.unloadScript "$KWIN_ID" \
        >/dev/null 2>&1 || true
    run_as_user gdbus call --session --dest org.kde.KWin --object-path /Scripting \
        --method org.kde.kwin.Scripting.start >/dev/null 2>&1 || true

    plasma_script='const widgetName = "org.xinyang.waydroidpenmode"; let touched = 0; for (const panelId of panelIds) { const panel = panelById(panelId); if (!panel) continue; for (const widgetId of panel.widgetIds) { const widget = panel.widgetById(widgetId); if (!widget || widget.type !== "org.kde.plasma.systemtray") continue; widget.currentConfigGroup = ["General"]; const extraItems = String(widget.readConfig("extraItems") || "").split(",").filter(item => item.length > 0); if (!extraItems.includes(widgetName)) { extraItems.push(widgetName); widget.writeConfig("extraItems", extraItems); } const shownItems = String(widget.readConfig("shownItems") || "").split(",").filter(item => item.length > 0); if (!shownItems.includes(widgetName)) { shownItems.push(widgetName); widget.writeConfig("shownItems", shownItems); } const hiddenItems = String(widget.readConfig("hiddenItems") || "").split(",").filter(item => item.length > 0 && item !== widgetName); widget.writeConfig("hiddenItems", hiddenItems); widget.reloadConfig(); touched += 1; } } touched;'
    result=$(run_as_user gdbus call --session --dest org.kde.plasmashell \
        --object-path /PlasmaShell \
        --method org.kde.PlasmaShell.evaluateScript "$plasma_script" 2>/dev/null || true)
    echo "KDE: plasmoid/kwin installed; tray script result: ${result:-unavailable}"
    echo "If the tray icon is missing: System Tray settings → Entries → Waydroid Pen Mode → Shown"
fi

echo "User setup done."
