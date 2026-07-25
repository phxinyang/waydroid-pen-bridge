#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
UUID=waydroid-pen-mode@sheng
HELPER=/usr/local/libexec/waydroid-pen-mode
RELAY=/usr/local/libexec/waydroid-pen-relay
SESSION=/usr/local/libexec/waydroid-pen-session
RELAY_UNIT=/etc/systemd/system/waydroid-pen-relay.service
LINK_SYNC_PATH=/etc/systemd/system/waydroid-pen-link-sync.path
LINK_SYNC_SERVICE=/etc/systemd/system/waydroid-pen-link-sync.service
WAYDROID_DROPIN=/etc/systemd/system/waydroid-container.service.d/90-pen-relay.conf
LXC_CONFIG=/var/lib/waydroid/lxc/waydroid/config_nodes
M80P_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen-m80p dev/waydroid_pen_m80p none bind,create=file,optional 0 0'
P81C_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen-p81c dev/waydroid_pen_p81c none bind,create=file,optional 0 0'
BUTTON_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-buttons dev/waydroid_pen_buttons none bind,create=file,optional 0 0'
GESTURE_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-gestures dev/waydroid_pen_gesture none bind,create=file,optional 0 0'
# Mount used by the previous single-pen bridge release.
LEGACY_ANDROID_PEN_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen dev/waydroid_pen none bind,create=file,optional 0 0'
LEGACY_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-pen dev/waydroid_pen none bind,create=file,optional 0 0'
ANDROID_OVERLAY=/var/lib/waydroid/overlay/system/usr
LXC_PATH=/var/lib/waydroid/lxc
LXC_NAME=waydroid
ANDROID_PATH=/system/bin:/system/xbin
RULE_PATH=/etc/udev/rules.d/99-waydroid-pen-mode.rules
LEGACY_RULE_PATH=/etc/udev/rules.d/99-waydroid-evdev-pen.rules
SUDOERS_PATH=/etc/sudoers.d/waydroid-pen-mode
INSTALL_USER=${SUDO_USER:-$USER}
INSTALL_UID=$(id -u "$INSTALL_USER")
INSTALL_HOME=$(getent passwd "$INSTALL_USER" | cut -d: -f6)
EXTENSION_DIR="$INSTALL_HOME/.local/share/gnome-shell/extensions/$UUID"
POLICY_DIR="$INSTALL_HOME/.config/waydroid-pen-mode"
USER_UNIT_DIR="$INSTALL_HOME/.config/systemd/user"
KWIN_ID=waydroid-pen-mode
PLASMOID_ID=org.xinyang.waydroidpenmode

if [[ -z "$INSTALL_HOME" || "$INSTALL_HOME" != /* || "$INSTALL_HOME" == / ]]; then
    echo "Invalid install home for $INSTALL_USER: $INSTALL_HOME" >&2
    exit 1
fi

if [[ ! -f "$LXC_CONFIG" ]]; then
    echo "Waydroid LXC config not found: $LXC_CONFIG" >&2
    exit 1
fi

if ! systemctl cat xiaomi-sheng-thp.service >/dev/null 2>&1; then
    echo "Missing required unit: xiaomi-sheng-thp.service" >&2
    echo "Install and start https://github.com/ianchb/xiaomi-sheng-thp first." >&2
    exit 1
fi
if ! systemctl is-active --quiet xiaomi-sheng-thp.service; then
    echo "xiaomi-sheng-thp.service is installed but not active." >&2
    echo "Start it before installing the bridge, or reboot after install." >&2
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
        /system/bin/sh -c 'exec "$@"' waydroid-pen-install "$@"
}

if group_entry=$(getent group 1004); then
    android_group=${group_entry%%:*}
else
    sudo groupadd --gid 1004 android-input
    android_group=android-input
fi

gnome-extensions disable "$UUID" >/dev/null 2>&1 || true

sudo install -D -o root -g root -m 0755 \
    "$ROOT_DIR/helper/waydroid-pen-mode.py" "$HELPER"
sudo install -D -o root -g root -m 0755 \
    "$ROOT_DIR/helper/waydroid-pen-relay.py" "$RELAY"
sudo install -D -o root -g root -m 0755 \
    "$ROOT_DIR/helper/waydroid-pen-session.py" "$SESSION"
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/config/waydroid-pen-relay.service" "$RELAY_UNIT"
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/config/waydroid-pen-link-sync.path" "$LINK_SYNC_PATH"
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/config/waydroid-pen-link-sync.service" "$LINK_SYNC_SERVICE"
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/config/waydroid-container-pen.conf" "$WAYDROID_DROPIN"
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/config/waydroid-pen-mode.conf" /etc/waydroid-pen-mode.conf
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/android/Vendor_2717_Product_3654.kl" \
    "$ANDROID_OVERLAY/keylayout/Vendor_2717_Product_3654.kl"
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/android/Vendor_2717_Product_3654.kcm" \
    "$ANDROID_OVERLAY/keychars/Vendor_2717_Product_3654.kcm"
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/android/Vendor_2717_Product_3655.kl" \
    "$ANDROID_OVERLAY/keylayout/Vendor_2717_Product_3655.kl"
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/android/Vendor_2717_Product_3655.kcm" \
    "$ANDROID_OVERLAY/keychars/Vendor_2717_Product_3655.kcm"

rule_tmp=$(mktemp)
sed \
    -e "s/@USER_UID@/$INSTALL_UID/g" \
    -e "s/@ANDROID_INPUT_GROUP@/$android_group/g" \
    "$ROOT_DIR/config/99-waydroid-pen-mode.rules.in" >"$rule_tmp"
sudo install -D -o root -g root -m 0644 "$rule_tmp" "$RULE_PATH"
rm "$rule_tmp"

if sudo test -e "$LEGACY_RULE_PATH"; then
    sudo mv "$LEGACY_RULE_PATH" "$LEGACY_RULE_PATH.disabled-by-waydroid-pen-mode"
fi

sudoers_tmp=$(mktemp)
{
    printf '%s ALL=(root) NOPASSWD: %s direct\n' "$INSTALL_USER" "$HELPER"
    printf '%s ALL=(root) NOPASSWD: %s desktop\n' "$INSTALL_USER" "$HELPER"
    printf '%s ALL=(root) NOPASSWD: %s sync\n' "$INSTALL_USER" "$HELPER"
    printf '%s ALL=(root) NOPASSWD: %s focus *\n' "$INSTALL_USER" "$HELPER"
    printf '%s ALL=(root) NOPASSWD: %s status\n' "$INSTALL_USER" "$HELPER"
    printf '%s ALL=(root) NOPASSWD: %s map *\n' "$INSTALL_USER" "$HELPER"
    printf '%s ALL=(root) NOPASSWD: %s unmap\n' "$INSTALL_USER" "$HELPER"
} >"$sudoers_tmp"
sudo visudo -cf "$sudoers_tmp" >/dev/null
sudo install -D -o root -g root -m 0440 "$sudoers_tmp" "$SUDOERS_PATH"
rm "$sudoers_tmp"

lxc_backed_up=false
if grep -Fqx "$LEGACY_ANDROID_PEN_LXC_LINE" "$LXC_CONFIG" \
        || grep -Fqx "$LEGACY_LXC_LINE" "$LXC_CONFIG"; then
    sudo cp -a "$LXC_CONFIG" "$LXC_CONFIG.wayland-pen-mode-backup-$(date +%Y%m%d-%H%M%S)"
    lxc_backed_up=true
    config_tmp=$(mktemp)
    awk -v old_android="$LEGACY_ANDROID_PEN_LXC_LINE" \
        -v old_legacy="$LEGACY_LXC_LINE" \
        '$0 != old_android && $0 != old_legacy { print }' \
        "$LXC_CONFIG" >"$config_tmp"
    sudo install -o root -g root -m 0644 "$config_tmp" "$LXC_CONFIG"
    rm "$config_tmp"
fi
if ! grep -Fqx "$M80P_LXC_LINE" "$LXC_CONFIG"; then
    if [[ "$lxc_backed_up" == false ]]; then
        sudo cp -a "$LXC_CONFIG" "$LXC_CONFIG.wayland-pen-mode-backup-$(date +%Y%m%d-%H%M%S)"
    fi
    printf '%s\n' "$M80P_LXC_LINE" | sudo tee -a "$LXC_CONFIG" >/dev/null
    lxc_backed_up=true
fi
if ! grep -Fqx "$P81C_LXC_LINE" "$LXC_CONFIG"; then
    if [[ "$lxc_backed_up" == false ]]; then
        sudo cp -a "$LXC_CONFIG" "$LXC_CONFIG.wayland-pen-mode-backup-$(date +%Y%m%d-%H%M%S)"
    fi
    printf '%s\n' "$P81C_LXC_LINE" | sudo tee -a "$LXC_CONFIG" >/dev/null
    lxc_backed_up=true
fi
if ! grep -Fqx "$BUTTON_LXC_LINE" "$LXC_CONFIG"; then
    if [[ "$lxc_backed_up" == false ]]; then
        sudo cp -a "$LXC_CONFIG" "$LXC_CONFIG.wayland-pen-mode-backup-$(date +%Y%m%d-%H%M%S)"
    fi
    printf '%s\n' "$BUTTON_LXC_LINE" | sudo tee -a "$LXC_CONFIG" >/dev/null
    lxc_backed_up=true
fi
if ! grep -Fqx "$GESTURE_LXC_LINE" "$LXC_CONFIG"; then
    if [[ "$lxc_backed_up" == false ]]; then
        sudo cp -a "$LXC_CONFIG" "$LXC_CONFIG.wayland-pen-mode-backup-$(date +%Y%m%d-%H%M%S)"
    fi
    printf '%s\n' "$GESTURE_LXC_LINE" | sudo tee -a "$LXC_CONFIG" >/dev/null
fi

# User-session pieces (GNOME extension, KDE tray/script, user units).
if [[ -x "$ROOT_DIR/user-setup.sh" ]]; then
    # Keep going even if the graphical session bus is unavailable during install.
    "$ROOT_DIR/user-setup.sh" || true
fi

if waydroid_container_available; then
    waydroid_container_shell setprop \
        persist.device_config.input_native_boot.palm_rejection_enabled 1
    target=$(waydroid_container_shell readlink /dev/input/event4 2>/dev/null || true)
    if [[ "$target" == ../waydroid_pen || "$target" == ../waydroid_pen_m80p || "$target" == ../waydroid_pen_p81c ]]; then
        waydroid_container_shell unlink /dev/input/event4 || true
    fi
    gesture_target=$(waydroid_container_shell readlink /dev/input/event5 2>/dev/null || true)
    if [[ "$gesture_target" == ../waydroid_pen_gesture || "$gesture_target" == ../waydroid_pen_buttons ]]; then
        waydroid_container_shell unlink /dev/input/event5 || true
    fi
fi

sudo rm -f /run/waydroid-pen-direct
sudo udevadm control --reload-rules
for event_path in /sys/class/input/event*; do
    device_name=$(cat "$event_path/device/name" 2>/dev/null || true)
    if [[ "$device_name" == "NVTCapacitivePenM80p" \
            || "$device_name" == "NVTCapacitivePenP81c" \
            || "$device_name" == "Xiaomi Focus Pen Pro Gestures" ]]; then
        sudo udevadm trigger --action=add "$event_path"
    fi
done
sudo udevadm settle
sudo systemctl daemon-reload
sudo systemctl reset-failed \
    waydroid-pen-link-sync.service \
    waydroid-pen-link-sync.path >/dev/null 2>&1 || true
sudo systemctl enable \
    waydroid-pen-relay.service waydroid-pen-link-sync.path >/dev/null
if systemctl is-active --quiet xiaomi-sheng-thp.service; then
    sudo systemctl restart waydroid-pen-relay.service
    sudo systemctl restart waydroid-pen-link-sync.path
elif sudo systemctl is-active --quiet waydroid-pen-relay.service; then
    sudo systemctl restart waydroid-pen-link-sync.path
fi

echo "Installed waydroid-pen-bridge (system)."
echo "Prerequisite: xiaomi-sheng-thp remains the pen driver; this package only routes it."
echo "Restart Waydroid, then reboot once so udev hides the physical pen before login"
echo "and the relay creates stable proxies."
echo "If the mode switch UI is missing after login, run: ./user-setup.sh"
echo "On GNOME, enable the Waydroid Pen Mode extension if needed."
echo "On KDE, the Waydroid Pen Mode item should appear in the System Tray."
