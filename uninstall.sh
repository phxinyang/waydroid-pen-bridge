#!/usr/bin/env bash
set -euo pipefail

UUID=waydroid-pen-mode@sheng
HELPER=/usr/local/libexec/waydroid-pen-mode
LXC_CONFIG=/var/lib/waydroid/lxc/waydroid/config_nodes
LXC_LINE='lxc.mount.entry = /dev/input/waydroid-pen dev/waydroid_pen none bind,create=file,optional 0 0'
INSTALL_USER=${SUDO_USER:-$USER}
INSTALL_HOME=$(getent passwd "$INSTALL_USER" | cut -d: -f6)

gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
if [[ -x "$HELPER" ]] && sudo systemctl is-active --quiet waydroid-pen-relay.service; then
    sudo "$HELPER" desktop || true
fi
sudo systemctl disable waydroid-pen-relay.service >/dev/null 2>&1 || true
if waydroid status 2>/dev/null | grep -q $'Container:\tRUNNING'; then
    sudo waydroid shell -- setprop \
        persist.device_config.input_native_boot.palm_rejection_enabled '' || true
fi

if [[ -f "$LXC_CONFIG" ]] && grep -Fqx "$LXC_LINE" "$LXC_CONFIG"; then
    config_tmp=$(mktemp)
    grep -Fvx "$LXC_LINE" "$LXC_CONFIG" >"$config_tmp"
    sudo install -o root -g root -m 0644 "$config_tmp" "$LXC_CONFIG"
    rm "$config_tmp"
fi

sudo rm -f \
    /etc/udev/rules.d/99-waydroid-pen-mode.rules \
    /etc/sudoers.d/waydroid-pen-mode \
    /etc/systemd/system/waydroid-pen-relay.service \
    /etc/systemd/system/waydroid-container.service.d/90-pen-relay.conf \
    /etc/waydroid-pen-mode.conf \
    /usr/local/libexec/waydroid-pen-relay \
    "$HELPER"
rm -rf "$INSTALL_HOME/.local/share/gnome-shell/extensions/$UUID"
sudo udevadm control --reload-rules
sudo systemctl daemon-reload

echo "Uninstalled. Reboot to stop the proxy and restore the physical GNOME pen."
