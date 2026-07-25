#!/usr/bin/env bash
set -euo pipefail

UUID=waydroid-pen-mode@sheng
HELPER=/usr/local/libexec/waydroid-pen-mode
SESSION=/usr/local/libexec/waydroid-pen-session
LXC_CONFIG=/var/lib/waydroid/lxc/waydroid/config_nodes
M80P_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen-m80p dev/waydroid_pen_m80p none bind,create=file,optional 0 0'
P81C_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen-p81c dev/waydroid_pen_p81c none bind,create=file,optional 0 0'
BUTTON_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-buttons dev/waydroid_pen_buttons none bind,create=file,optional 0 0'
GESTURE_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-gestures dev/waydroid_pen_gesture none bind,create=file,optional 0 0'
LEGACY_ANDROID_PEN_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen dev/waydroid_pen none bind,create=file,optional 0 0'
LEGACY_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-pen dev/waydroid_pen none bind,create=file,optional 0 0'
ANDROID_OVERLAY=/var/lib/waydroid/overlay/system/usr
LXC_PATH=/var/lib/waydroid/lxc
LXC_NAME=waydroid
ANDROID_PATH=/system/bin:/system/xbin
INSTALL_USER=${SUDO_USER:-$USER}
INSTALL_HOME=$(getent passwd "$INSTALL_USER" | cut -d: -f6)
KWIN_ID=waydroid-pen-mode
PLASMOID_ID=org.xinyang.waydroidpenmode

if [[ -z "$INSTALL_HOME" || "$INSTALL_HOME" != /* || "$INSTALL_HOME" == / ]]; then
    echo "Invalid install home for $INSTALL_USER: $INSTALL_HOME" >&2
    exit 1
fi

waydroid_container_available() {
    local state
    state=$(sudo /usr/bin/timeout --kill-after=1s 5s \
        /usr/bin/lxc-info -P "$LXC_PATH" -n "$LXC_NAME" -sH \
        2>/dev/null || true)
    [[ "$state" == RUNNING || "$state" == FROZEN ]]
}

waydroid_container_shell() {
    sudo /usr/bin/timeout --kill-after=1s 5s \
        /usr/bin/lxc-attach -P "$LXC_PATH" -n "$LXC_NAME" \
        --clear-env --set-var "PATH=$ANDROID_PATH" -- \
        /system/bin/sh -c 'exec "$@"' waydroid-pen-uninstall "$@"
}

gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
systemctl --user disable --now waydroid-pen-session.path \
    >/dev/null 2>&1 || true
if [[ -x "$HELPER" ]] && sudo systemctl is-active --quiet waydroid-pen-relay.service; then
    sudo "$HELPER" desktop || true
fi
sudo systemctl disable \
    waydroid-pen-link-sync.path waydroid-pen-relay.service \
    >/dev/null 2>&1 || true
if waydroid_container_available; then
    waydroid_container_shell setprop \
        persist.device_config.input_native_boot.palm_rejection_enabled '' || true
    event4_target=$(waydroid_container_shell readlink /dev/input/event4 2>/dev/null || true)
    if [[ "$event4_target" == ../waydroid_pen || "$event4_target" == ../waydroid_pen_m80p || "$event4_target" == ../waydroid_pen_p81c ]]; then
        waydroid_container_shell unlink /dev/input/event4 || true
    fi
    event5_target=$(waydroid_container_shell readlink /dev/input/event5 2>/dev/null || true)
    if [[ "$event5_target" == ../waydroid_pen_gesture || "$event5_target" == ../waydroid_pen_buttons ]]; then
        waydroid_container_shell unlink /dev/input/event5 || true
    fi
fi

if command -v gdbus >/dev/null 2>&1; then
    plasma_script='const widgetName = "org.xinyang.waydroidpenmode"; for (const panelId of panelIds) { const panel = panelById(panelId); if (!panel) continue; for (const widgetId of panel.widgetIds) { const widget = panel.widgetById(widgetId); if (!widget || widget.type !== "org.kde.plasma.systemtray") continue; widget.currentConfigGroup = ["General"]; const extraItems = String(widget.readConfig("extraItems") || "").split(",").filter(item => item.length > 0 && item !== widgetName); widget.writeConfig("extraItems", extraItems); widget.reloadConfig(); } }'
    gdbus call --session --dest org.kde.plasmashell \
        --object-path /PlasmaShell \
        --method org.kde.PlasmaShell.evaluateScript "$plasma_script" \
        >/dev/null 2>&1 || true
    gdbus call --session --dest org.kde.KWin --object-path /Scripting \
        --method org.kde.kwin.Scripting.unloadScript "$KWIN_ID" \
        >/dev/null 2>&1 || true
fi
if command -v kwriteconfig6 >/dev/null 2>&1; then
    kwriteconfig6 --file kwinrc --group Plugins \
        --key "${KWIN_ID}Enabled" --delete >/dev/null 2>&1 || true
fi
if command -v kpackagetool6 >/dev/null 2>&1; then
    kpackagetool6 --type Plasma/Applet --remove "$PLASMOID_ID" \
        >/dev/null 2>&1 || true
    kpackagetool6 --type KWin/Script --remove "$KWIN_ID" \
        >/dev/null 2>&1 || true
fi

if [[ -f "$LXC_CONFIG" ]] && {
    grep -Fqx "$M80P_LXC_LINE" "$LXC_CONFIG" \
        || grep -Fqx "$P81C_LXC_LINE" "$LXC_CONFIG" \
        || grep -Fqx "$BUTTON_LXC_LINE" "$LXC_CONFIG" \
        || grep -Fqx "$GESTURE_LXC_LINE" "$LXC_CONFIG" \
        || grep -Fqx "$LEGACY_ANDROID_PEN_LXC_LINE" "$LXC_CONFIG" \
        || grep -Fqx "$LEGACY_LXC_LINE" "$LXC_CONFIG";
}; then
    config_tmp=$(mktemp)
    awk -v m80p="$M80P_LXC_LINE" \
        -v p81c="$P81C_LXC_LINE" \
        -v buttons="$BUTTON_LXC_LINE" \
        -v gestures="$GESTURE_LXC_LINE" \
        -v old_android="$LEGACY_ANDROID_PEN_LXC_LINE" \
        -v old_legacy="$LEGACY_LXC_LINE" \
        '$0 != m80p && $0 != p81c && $0 != buttons && \
         $0 != gestures && $0 != old_android && $0 != old_legacy { print }' \
        "$LXC_CONFIG" >"$config_tmp"
    sudo install -o root -g root -m 0644 "$config_tmp" "$LXC_CONFIG"
    rm "$config_tmp"
fi

sudo rm -f \
    /etc/udev/rules.d/99-waydroid-pen-mode.rules \
    /etc/sudoers.d/waydroid-pen-mode \
    /etc/systemd/system/waydroid-pen-link-sync.path \
    /etc/systemd/system/waydroid-pen-link-sync.service \
    /etc/systemd/system/waydroid-pen-relay.service \
    /etc/systemd/system/waydroid-container.service.d/90-pen-relay.conf \
    /etc/waydroid-pen-mode.conf \
    /usr/local/libexec/waydroid-pen-relay \
    "$SESSION" \
    "$ANDROID_OVERLAY/keylayout/Vendor_2717_Product_3654.kl" \
    "$ANDROID_OVERLAY/keychars/Vendor_2717_Product_3654.kcm" \
    "$ANDROID_OVERLAY/keylayout/Vendor_2717_Product_3655.kl" \
    "$ANDROID_OVERLAY/keychars/Vendor_2717_Product_3655.kcm" \
    "$HELPER"
rm -rf "$INSTALL_HOME/.local/share/gnome-shell/extensions/$UUID"
rm -f \
    "$INSTALL_HOME/.config/systemd/user/waydroid-pen-session@.service" \
    "$INSTALL_HOME/.config/systemd/user/waydroid-pen-session-reapply.service" \
    "$INSTALL_HOME/.config/systemd/user/waydroid-pen-session.path" \
    "$INSTALL_HOME/.config/waydroid-pen-mode/policy" \
    "$INSTALL_HOME/.local/state/waydroid-pen-mode/session.json"
rmdir "$INSTALL_HOME/.config/waydroid-pen-mode" 2>/dev/null || true
rmdir "$INSTALL_HOME/.local/state/waydroid-pen-mode" 2>/dev/null || true
systemctl --user daemon-reload
sudo udevadm control --reload-rules
sudo systemctl daemon-reload

echo "Uninstalled. Reboot to stop the proxy and restore the physical GNOME pen."
