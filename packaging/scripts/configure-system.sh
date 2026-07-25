#!/usr/bin/env bash
# System-layer configuration after package file install (rpm %post / deb postinst).
set -euo pipefail

SHARE=/usr/local/share/waydroid-pen-bridge
HELPER=/usr/local/libexec/waydroid-pen-mode
LXC_CONFIG=/var/lib/waydroid/lxc/waydroid/config_nodes
ANDROID_OVERLAY=/var/lib/waydroid/overlay/system/usr
RULE_PATH=/etc/udev/rules.d/99-waydroid-pen-mode.rules
LEGACY_RULE_PATH=/etc/udev/rules.d/99-waydroid-evdev-pen.rules
SUDOERS_PATH=/etc/sudoers.d/waydroid-pen-mode
LXC_PATH=/var/lib/waydroid/lxc
LXC_NAME=waydroid
ANDROID_PATH=/system/bin:/system/xbin

M80P_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen-m80p dev/waydroid_pen_m80p none bind,create=file,optional 0 0'
P81C_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen-p81c dev/waydroid_pen_p81c none bind,create=file,optional 0 0'
BUTTON_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-buttons dev/waydroid_pen_buttons none bind,create=file,optional 0 0'
GESTURE_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-gestures dev/waydroid_pen_gesture none bind,create=file,optional 0 0'
LEGACY_ANDROID_PEN_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen dev/waydroid_pen none bind,create=file,optional 0 0'
LEGACY_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-pen dev/waydroid_pen none bind,create=file,optional 0 0'

if ! systemctl cat xiaomi-sheng-thp.service >/dev/null 2>&1; then
    echo "WARNING: xiaomi-sheng-thp.service not found. Install the THP driver first." >&2
fi

INSTALL_USER=${SUDO_USER:-}
if [[ -z "$INSTALL_USER" || "$INSTALL_USER" == root ]]; then
    INSTALL_USER=$(loginctl list-sessions --no-legend 2>/dev/null \
        | awk '($3 ~ /^seat/) { print $4; exit }' || true)
fi
if [[ -z "$INSTALL_USER" || "$INSTALL_USER" == root ]]; then
    INSTALL_USER=$(loginctl list-users --no-legend 2>/dev/null \
        | awk '$1+0 >= 1000 { print $2; exit }' || true)
fi
if [[ -z "$INSTALL_USER" || "$INSTALL_USER" == root ]]; then
    INSTALL_USER=$(getent passwd 1000 | cut -d: -f1 || true)
fi
if [[ -z "$INSTALL_USER" || "$INSTALL_USER" == root ]]; then
    echo "WARNING: could not resolve desktop user; defaulting udev OWNER to uid 1000" >&2
    INSTALL_UID=1000
    INSTALL_USER=$(getent passwd 1000 | cut -d: -f1 || echo xinyang)
else
    INSTALL_UID=$(id -u "$INSTALL_USER")
fi
echo "configure-system: desktop user=$INSTALL_USER uid=$INSTALL_UID"

if group_entry=$(getent group 1004); then
    android_group=${group_entry%%:*}
else
    groupadd --gid 1004 android-input || true
    android_group=android-input
fi

if [[ -f "$SHARE/config/99-waydroid-pen-mode.rules.in" ]]; then
    sed \
        -e "s/@USER_UID@/$INSTALL_UID/g" \
        -e "s/@ANDROID_INPUT_GROUP@/$android_group/g" \
        "$SHARE/config/99-waydroid-pen-mode.rules.in" >"$RULE_PATH"
    chmod 0644 "$RULE_PATH"
fi
if [[ -e "$LEGACY_RULE_PATH" ]]; then
    mv "$LEGACY_RULE_PATH" "$LEGACY_RULE_PATH.disabled-by-waydroid-pen-mode" || true
fi

if [[ -n "$INSTALL_USER" && "$INSTALL_USER" != root ]]; then
    {
        printf '%s ALL=(root) NOPASSWD: %s direct\n' "$INSTALL_USER" "$HELPER"
        printf '%s ALL=(root) NOPASSWD: %s desktop\n' "$INSTALL_USER" "$HELPER"
        printf '%s ALL=(root) NOPASSWD: %s sync\n' "$INSTALL_USER" "$HELPER"
        printf '%s ALL=(root) NOPASSWD: %s focus *\n' "$INSTALL_USER" "$HELPER"
        printf '%s ALL=(root) NOPASSWD: %s status\n' "$INSTALL_USER" "$HELPER"
        printf '%s ALL=(root) NOPASSWD: %s map *\n' "$INSTALL_USER" "$HELPER"
        printf '%s ALL=(root) NOPASSWD: %s unmap\n' "$INSTALL_USER" "$HELPER"
    } >"$SUDOERS_PATH"
    chmod 0440 "$SUDOERS_PATH"
    if command -v visudo >/dev/null 2>&1; then
        visudo -cf "$SUDOERS_PATH" >/dev/null || rm -f "$SUDOERS_PATH"
    fi
fi

if [[ -d /var/lib/waydroid ]]; then
    install -D -m 0644 "$SHARE/android/Vendor_2717_Product_3654.kl" \
        "$ANDROID_OVERLAY/keylayout/Vendor_2717_Product_3654.kl"
    install -D -m 0644 "$SHARE/android/Vendor_2717_Product_3654.kcm" \
        "$ANDROID_OVERLAY/keychars/Vendor_2717_Product_3654.kcm"
    install -D -m 0644 "$SHARE/android/Vendor_2717_Product_3655.kl" \
        "$ANDROID_OVERLAY/keylayout/Vendor_2717_Product_3655.kl"
    install -D -m 0644 "$SHARE/android/Vendor_2717_Product_3655.kcm" \
        "$ANDROID_OVERLAY/keychars/Vendor_2717_Product_3655.kcm"
fi

if [[ -f "$LXC_CONFIG" ]]; then
    lxc_backed_up=false
    backup_lxc() {
        if [[ "$lxc_backed_up" == false ]]; then
            cp -a "$LXC_CONFIG" "$LXC_CONFIG.wayland-pen-mode-backup-$(date +%Y%m%d-%H%M%S)" || true
            lxc_backed_up=true
        fi
    }
    if grep -Fqx "$LEGACY_ANDROID_PEN_LXC_LINE" "$LXC_CONFIG" \
            || grep -Fqx "$LEGACY_LXC_LINE" "$LXC_CONFIG"; then
        backup_lxc
        config_tmp=$(mktemp)
        awk -v old_android="$LEGACY_ANDROID_PEN_LXC_LINE" \
            -v old_legacy="$LEGACY_LXC_LINE" \
            '$0 != old_android && $0 != old_legacy { print }' \
            "$LXC_CONFIG" >"$config_tmp"
        install -m 0644 "$config_tmp" "$LXC_CONFIG"
        rm -f "$config_tmp"
    fi
    for line in "$M80P_LXC_LINE" "$P81C_LXC_LINE" "$BUTTON_LXC_LINE" "$GESTURE_LXC_LINE"; do
        if ! grep -Fqx "$line" "$LXC_CONFIG"; then
            backup_lxc
            printf '%s\n' "$line" >>"$LXC_CONFIG"
        fi
    done
fi

waydroid_container_available() {
    local state
    state=$(/usr/bin/timeout --kill-after=1s 5s \
        /usr/bin/lxc-info -P "$LXC_PATH" -n "$LXC_NAME" -sH 2>/dev/null || true)
    [[ "$state" == RUNNING || "$state" == FROZEN ]]
}
waydroid_container_shell() {
    /usr/bin/timeout --kill-after=1s 5s \
        /usr/bin/lxc-attach -P "$LXC_PATH" -n "$LXC_NAME" \
        --clear-env --set-var "PATH=$ANDROID_PATH" -- \
        /system/bin/sh -c 'exec "$@"' waydroid-pen-pkg "$@"
}
if waydroid_container_available; then
    waydroid_container_shell setprop \
        persist.device_config.input_native_boot.palm_rejection_enabled 1 || true
    target=$(waydroid_container_shell readlink /dev/input/event4 2>/dev/null || true)
    if [[ "$target" == ../waydroid_pen || "$target" == ../waydroid_pen_m80p || "$target" == ../waydroid_pen_p81c ]]; then
        waydroid_container_shell unlink /dev/input/event4 || true
    fi
    gesture_target=$(waydroid_container_shell readlink /dev/input/event5 2>/dev/null || true)
    if [[ "$gesture_target" == ../waydroid_pen_gesture || "$gesture_target" == ../waydroid_pen_buttons ]]; then
        waydroid_container_shell unlink /dev/input/event5 || true
    fi
fi

rm -f /run/waydroid-pen-direct
udevadm control --reload-rules || true
shopt -s nullglob
for event_path in /sys/class/input/event*; do
    device_name=$(cat "$event_path/device/name" 2>/dev/null || true)
    if [[ "$device_name" == "NVTCapacitivePenM80p" \
            || "$device_name" == "NVTCapacitivePenP81c" \
            || "$device_name" == "Xiaomi Focus Pen Pro Gestures" ]]; then
        udevadm trigger --action=add "$event_path" || true
    fi
done
udevadm settle || true

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
    systemctl reset-failed \
        waydroid-pen-link-sync.service \
        waydroid-pen-link-sync.path \
        waydroid-pen-relay.service >/dev/null 2>&1 || true
    systemctl enable waydroid-pen-relay.service waydroid-pen-link-sync.path \
        >/dev/null 2>&1 || true
    if systemctl is-active --quiet xiaomi-sheng-thp.service; then
        systemctl restart waydroid-pen-relay.service || true
        systemctl restart waydroid-pen-link-sync.path || true
    elif systemctl is-active --quiet waydroid-pen-relay.service; then
        systemctl restart waydroid-pen-link-sync.path || true
    fi
fi

if [[ -n "$INSTALL_USER" && "$INSTALL_USER" != root \
        && -x /usr/local/bin/waydroid-pen-bridge-user-setup ]]; then
    if [[ -S "/run/user/$(id -u "$INSTALL_USER")/bus" ]]; then
        sudo -u "$INSTALL_USER" \
            env -u SUDO_USER \
            XDG_RUNTIME_DIR="/run/user/$(id -u "$INSTALL_USER")" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$INSTALL_USER")/bus" \
            /usr/local/bin/waydroid-pen-bridge-user-setup || true
    else
        echo "Session bus for $INSTALL_USER not up; run waydroid-pen-bridge-user-setup after login."
    fi
fi

echo "waydroid-pen-bridge system layer configured."
echo "If tray/extension is missing after login: waydroid-pen-bridge-user-setup"
echo "Reboot once so udev hides physical pens before login when possible."
