#!/usr/bin/env bash
# Cleanup after package files are gone (rpm %postun full remove / deb postrm remove).
# Must be self-contained: package files may already be deleted.
set -euo pipefail

LXC_CONFIG=/var/lib/waydroid/lxc/waydroid/config_nodes
ANDROID_OVERLAY=/var/lib/waydroid/overlay/system/usr
RULE_PATH=/etc/udev/rules.d/99-waydroid-pen-mode.rules
LEGACY_RULE_PATH=/etc/udev/rules.d/99-waydroid-evdev-pen.rules
LEGACY_RULE_DISABLED=/etc/udev/rules.d/99-waydroid-evdev-pen.rules.disabled-by-waydroid-pen-mode
SUDOERS_PATH=/etc/sudoers.d/waydroid-pen-mode

M80P_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen-m80p dev/waydroid_pen_m80p none bind,create=file,optional 0 0'
P81C_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen-p81c dev/waydroid_pen_p81c none bind,create=file,optional 0 0'
BUTTON_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-buttons dev/waydroid_pen_buttons none bind,create=file,optional 0 0'
GESTURE_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-gestures dev/waydroid_pen_gesture none bind,create=file,optional 0 0'
LEGACY_ANDROID_PEN_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen dev/waydroid_pen none bind,create=file,optional 0 0'
LEGACY_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-pen dev/waydroid_pen none bind,create=file,optional 0 0'

if [[ -f "$LXC_CONFIG" ]]; then
    config_tmp=$(mktemp)
    awk -v m80p="$M80P_LXC_LINE" -v p81c="$P81C_LXC_LINE" \
        -v buttons="$BUTTON_LXC_LINE" -v gestures="$GESTURE_LXC_LINE" \
        -v old_android="$LEGACY_ANDROID_PEN_LXC_LINE" -v old_legacy="$LEGACY_LXC_LINE" \
        '$0 != m80p && $0 != p81c && $0 != buttons && $0 != gestures && $0 != old_android && $0 != old_legacy { print }' \
        "$LXC_CONFIG" >"$config_tmp"
    install -m 0644 "$config_tmp" "$LXC_CONFIG"
    rm -f "$config_tmp"
fi

rm -f "$RULE_PATH" "$SUDOERS_PATH" \
    "$ANDROID_OVERLAY/keylayout/Vendor_2717_Product_3654.kl" \
    "$ANDROID_OVERLAY/keychars/Vendor_2717_Product_3654.kcm" \
    "$ANDROID_OVERLAY/keylayout/Vendor_2717_Product_3655.kl" \
    "$ANDROID_OVERLAY/keychars/Vendor_2717_Product_3655.kcm" \
    "$ANDROID_OVERLAY/idc/Vendor_2717_Product_3654.idc" \
    "$ANDROID_OVERLAY/idc/NVTCapacitivePenM80p.idc" \
    "$ANDROID_OVERLAY/idc/NVTCapacitivePenP81c.idc" \
    "$ANDROID_OVERLAY/idc/Vendor_2717_Product_3655.idc" \
    /run/waydroid-pen-direct \
    /run/waydroid-pen-mode/state.json \
    /run/waydroid-pen-mode/link-state.json \
    /run/waydroid-pen-mode/control.sock \
    /run/lock/waydroid-pen-mode.lock
rmdir /run/waydroid-pen-mode 2>/dev/null || true
rm -f "$LEGACY_RULE_PATH" "$LEGACY_RULE_DISABLED"

if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
fi
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
    if systemctl cat xiaomi-sheng-thp.service >/dev/null 2>&1; then
        systemctl restart xiaomi-sheng-thp.service || true
    fi
fi

echo "waydroid-pen-bridge removed; xiaomi-sheng-thp left installed."
echo "Desktop UI (plasmoid/extension) may remain until cleaned in the user session."
