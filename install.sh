#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
UUID=waydroid-pen-mode@sheng
HELPER=/usr/local/libexec/waydroid-pen-mode
RELAY=/usr/local/libexec/waydroid-pen-relay
RELAY_UNIT=/etc/systemd/system/waydroid-pen-relay.service
WAYDROID_DROPIN=/etc/systemd/system/waydroid-container.service.d/90-pen-relay.conf
LXC_CONFIG=/var/lib/waydroid/lxc/waydroid/config_nodes
LXC_LINE='lxc.mount.entry = /dev/input/waydroid-android-pen dev/waydroid_pen none bind,create=file,optional 0 0'
LEGACY_LXC_LINE='lxc.mount.entry = /dev/input/waydroid-pen dev/waydroid_pen none bind,create=file,optional 0 0'
RULE_PATH=/etc/udev/rules.d/99-waydroid-pen-mode.rules
LEGACY_RULE_PATH=/etc/udev/rules.d/99-waydroid-evdev-pen.rules
SUDOERS_PATH=/etc/sudoers.d/waydroid-pen-mode
INSTALL_USER=${SUDO_USER:-$USER}
INSTALL_UID=$(id -u "$INSTALL_USER")
INSTALL_HOME=$(getent passwd "$INSTALL_USER" | cut -d: -f6)
EXTENSION_DIR="$INSTALL_HOME/.local/share/gnome-shell/extensions/$UUID"
POLICY_DIR="$INSTALL_HOME/.config/waydroid-pen-mode"

if [[ ! -f "$LXC_CONFIG" ]]; then
    echo "Waydroid LXC config not found: $LXC_CONFIG" >&2
    exit 1
fi

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
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/config/waydroid-pen-relay.service" "$RELAY_UNIT"
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/config/waydroid-container-pen.conf" "$WAYDROID_DROPIN"
sudo install -D -o root -g root -m 0644 \
    "$ROOT_DIR/config/waydroid-pen-mode.conf" /etc/waydroid-pen-mode.conf

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
    printf '%s ALL=(root) NOPASSWD: %s status\n' "$INSTALL_USER" "$HELPER"
    printf '%s ALL=(root) NOPASSWD: %s map *\n' "$INSTALL_USER" "$HELPER"
    printf '%s ALL=(root) NOPASSWD: %s unmap\n' "$INSTALL_USER" "$HELPER"
} >"$sudoers_tmp"
sudo visudo -cf "$sudoers_tmp" >/dev/null
sudo install -D -o root -g root -m 0440 "$sudoers_tmp" "$SUDOERS_PATH"
rm "$sudoers_tmp"

lxc_backed_up=false
if grep -Fqx "$LEGACY_LXC_LINE" "$LXC_CONFIG"; then
    sudo cp -a "$LXC_CONFIG" "$LXC_CONFIG.wayland-pen-mode-backup-$(date +%Y%m%d-%H%M%S)"
    lxc_backed_up=true
    config_tmp=$(mktemp)
    grep -Fvx "$LEGACY_LXC_LINE" "$LXC_CONFIG" >"$config_tmp"
    sudo install -o root -g root -m 0644 "$config_tmp" "$LXC_CONFIG"
    rm "$config_tmp"
fi
if ! grep -Fqx "$LXC_LINE" "$LXC_CONFIG"; then
    if [[ "$lxc_backed_up" == false ]]; then
        sudo cp -a "$LXC_CONFIG" "$LXC_CONFIG.wayland-pen-mode-backup-$(date +%Y%m%d-%H%M%S)"
    fi
    printf '%s\n' "$LXC_LINE" | sudo tee -a "$LXC_CONFIG" >/dev/null
fi

install -d -m 0755 "$EXTENSION_DIR"
install -m 0644 "$ROOT_DIR/extension/extension.js" "$EXTENSION_DIR/extension.js"
install -m 0644 "$ROOT_DIR/extension/metadata.json" "$EXTENSION_DIR/metadata.json"
install -d -m 0700 "$POLICY_DIR"
if [[ ! -f "$POLICY_DIR/policy" ]]; then
    printf '%s\n' auto >"$POLICY_DIR/policy"
fi

if waydroid status 2>/dev/null | grep -q $'Container:\tRUNNING'; then
    sudo waydroid shell -- setprop \
        persist.device_config.input_native_boot.palm_rejection_enabled 1
    target=$(sudo waydroid shell -- readlink /dev/input/event4 2>/dev/null || true)
    if [[ "$target" == ../waydroid_pen ]]; then
        sudo waydroid shell -- unlink /dev/input/event4 || true
    fi
fi

sudo rm -f /run/waydroid-pen-direct
sudo udevadm control --reload-rules
sudo systemctl daemon-reload
sudo systemctl enable waydroid-pen-relay.service >/dev/null

echo "Installed. Restart Waydroid, then reboot once so the desktop starts with the stable proxy."
echo "After login, enable the Waydroid Pen Mode extension."
