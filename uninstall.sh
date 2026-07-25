#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME=waydroid-pen-bridge
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
RULE_PATH=/etc/udev/rules.d/99-waydroid-pen-mode.rules
LEGACY_RULE_PATH=/etc/udev/rules.d/99-waydroid-evdev-pen.rules
LEGACY_RULE_DISABLED=/etc/udev/rules.d/99-waydroid-evdev-pen.rules.disabled-by-waydroid-pen-mode
KWIN_ID=waydroid-pen-mode
PLASMOID_ID=org.xinyang.waydroidpenmode

# Prefer the real login user (same rule as user-setup.sh).
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != root ]]; then
    INSTALL_USER=$SUDO_USER
else
    INSTALL_USER=$USER
fi
if [[ "$INSTALL_USER" == root ]]; then
    INSTALL_USER=$(loginctl list-sessions --no-legend 2>/dev/null \
        | awk '($3 ~ /^seat/) { print $4; exit }' || true)
fi
if [[ -z "$INSTALL_USER" || "$INSTALL_USER" == root ]]; then
    INSTALL_USER=$(getent passwd 1000 | cut -d: -f1 || echo "$USER")
fi
INSTALL_HOME=$(getent passwd "$INSTALL_USER" | cut -d: -f6)

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

detect_package_install() {
    if command -v rpm >/dev/null 2>&1 \
            && rpm -q "$PACKAGE_NAME" >/dev/null 2>&1; then
        echo rpm
        return
    fi
    if command -v dpkg-query >/dev/null 2>&1; then
        local status
        status=$(dpkg-query -W -f='${Status}' "$PACKAGE_NAME" 2>/dev/null || true)
        if [[ "$status" == *"install ok installed"* ]]; then
            echo deb
            return
        fi
    fi
    echo none
}

remove_user_ui() {
    gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
    systemctl --user disable --now waydroid-pen-session.path \
        >/dev/null 2>&1 || true
    systemctl --user stop waydroid-pen-session-reapply.service \
        >/dev/null 2>&1 || true

    if command -v gdbus >/dev/null 2>&1; then
        plasma_script='const widgetName = "org.xinyang.waydroidpenmode"; for (const panelId of panelIds) { const panel = panelById(panelId); if (!panel) continue; for (const widgetId of panel.widgetIds) { const widget = panel.widgetById(widgetId); if (!widget || widget.type !== "org.kde.plasma.systemtray") continue; widget.currentConfigGroup = ["General"]; for (const key of ["extraItems", "shownItems", "hiddenItems"]) { const items = String(widget.readConfig(key) || "").split(",").filter(item => item.length > 0 && item !== widgetName); widget.writeConfig(key, items); } widget.reloadConfig(); } }'
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
    # Hard-remove package trees if kpackagetool left anything behind.
    rm -rf \
        "$INSTALL_HOME/.local/share/plasma/plasmoids/$PLASMOID_ID" \
        "$INSTALL_HOME/.local/share/kwin/scripts/$KWIN_ID" \
        "$INSTALL_HOME/.local/share/gnome-shell/extensions/$UUID"
    rm -f \
        "$INSTALL_HOME/.config/systemd/user/waydroid-pen-session@.service" \
        "$INSTALL_HOME/.config/systemd/user/waydroid-pen-session-reapply.service" \
        "$INSTALL_HOME/.config/systemd/user/waydroid-pen-session.path" \
        "$INSTALL_HOME/.config/waydroid-pen-mode/policy" \
        "$INSTALL_HOME/.local/state/waydroid-pen-mode/session.json"
    rmdir "$INSTALL_HOME/.config/waydroid-pen-mode" 2>/dev/null || true
    rmdir "$INSTALL_HOME/.local/state/waydroid-pen-mode" 2>/dev/null || true
    systemctl --user daemon-reload 2>/dev/null || true
}

path_status() {
    local path=$1
    if [[ -e "$path" || -L "$path" ]]; then
        echo "STILL $path"
        return 1
    fi
    echo "gone  $path"
    return 0
}

verify_clean() {
    local failed=0
    echo "=== uninstall verification ==="
    path_status "$HELPER" || failed=1
    path_status /usr/local/libexec/waydroid-pen-relay || failed=1
    path_status "$SESSION" || failed=1
    path_status /usr/local/bin/waydroid-pen-bridge-user-setup || failed=1
    path_status /usr/local/share/waydroid-pen-bridge || failed=1
    path_status "$RULE_PATH" || failed=1
    path_status "$LEGACY_RULE_PATH" || failed=1
    path_status /etc/sudoers.d/waydroid-pen-mode || failed=1
    path_status /usr/lib/systemd/system/waydroid-pen-relay.service || failed=1
    path_status /etc/systemd/system/waydroid-pen-relay.service || failed=1
    path_status /etc/waydroid-pen-mode.conf || failed=1
    path_status "$INSTALL_HOME/.local/share/plasma/plasmoids/$PLASMOID_ID" || failed=1
    path_status "$INSTALL_HOME/.local/share/kwin/scripts/$KWIN_ID" || failed=1
    path_status "$INSTALL_HOME/.local/share/gnome-shell/extensions/$UUID" || failed=1

    if command -v rpm >/dev/null 2>&1 && rpm -q "$PACKAGE_NAME" >/dev/null 2>&1; then
        echo "STILL rpm package $PACKAGE_NAME"
        failed=1
    else
        echo "gone  rpm package record (or n/a)"
    fi
    if command -v dpkg-query >/dev/null 2>&1; then
        local status
        status=$(dpkg-query -W -f='${Status}' "$PACKAGE_NAME" 2>/dev/null || true)
        if [[ "$status" == *"install ok installed"* ]]; then
            echo "STILL deb package $PACKAGE_NAME"
            failed=1
        else
            echo "gone  deb package record (or n/a)"
        fi
    fi

    if systemctl is-active --quiet waydroid-pen-relay.service 2>/dev/null; then
        echo "STILL waydroid-pen-relay.service active"
        failed=1
    else
        echo "gone  waydroid-pen-relay.service (inactive/missing)"
    fi

    local proxy
    for proxy in /dev/input/waydroid-pen /dev/input/waydroid-pen-pro \
            /dev/input/waydroid-android-pen-m80p /dev/input/waydroid-android-pen-p81c; do
        if [[ -e "$proxy" || -L "$proxy" ]]; then
            echo "STILL $proxy"
            failed=1
        fi
    done

    local event_path device_name phys ignore
    shopt -s nullglob
    for event_path in /sys/class/input/event*; do
        device_name=$(cat "$event_path/device/name" 2>/dev/null || true)
        phys=$(cat "$event_path/device/phys" 2>/dev/null || true)
        if [[ ( "$device_name" == "NVTCapacitivePenM80p" && "$phys" == "input/pen" ) \
                || ( "$device_name" == "NVTCapacitivePenP81c" && "$phys" == "input/pen_p81c" ) \
                || ( "$device_name" == "Xiaomi Focus Pen Pro Gestures" && "$phys" == "input/pen_p81c/gestures" ) ]]; then
            ignore=$(udevadm info -q property -p "$event_path" 2>/dev/null \
                | grep '^LIBINPUT_IGNORE_DEVICE=' || true)
            if [[ "$ignore" == *"=1"* ]]; then
                echo "STILL LIBINPUT_IGNORE on $device_name ($phys)"
                failed=1
            else
                echo "ok    $device_name ignore cleared"
            fi
        fi
    done

    if systemctl cat xiaomi-sheng-thp.service >/dev/null 2>&1; then
        if systemctl is-active --quiet xiaomi-sheng-thp.service; then
            echo "ok    xiaomi-sheng-thp is left installed (active)"
        else
            echo "warn  xiaomi-sheng-thp unit present but not active"
        fi
    fi

    if [[ "$failed" -ne 0 ]]; then
        echo "Verification found leftovers (see STILL lines above)." >&2
        return 1
    fi
    echo "Verification passed."
    return 0
}

remove_via_package_manager() {
    local kind=$1
    echo "Detected $kind install of $PACKAGE_NAME; removing with package manager..."
    case "$kind" in
        rpm)
            if command -v dnf >/dev/null 2>&1; then
                sudo dnf remove -y "$PACKAGE_NAME"
            else
                sudo rpm -e "$PACKAGE_NAME"
            fi
            ;;
        deb)
            if command -v apt-get >/dev/null 2>&1; then
                sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y "$PACKAGE_NAME"
            else
                sudo dpkg -r "$PACKAGE_NAME"
            fi
            ;;
        *)
            echo "Unknown package kind: $kind" >&2
            exit 1
            ;;
    esac
}

# --- entry ---

PKG_KIND=$(detect_package_install)

if [[ "$PKG_KIND" != none ]]; then
    remove_via_package_manager "$PKG_KIND"
    remove_user_ui
    echo "Uninstalled waydroid-pen-bridge via $PKG_KIND."
    echo "xiaomi-sheng-thp is left installed."
    echo "Physical THP pen nodes should be visible to libinput again."
    echo "Reboot still recommended so every desktop session fully rediscovers them."
    verify_clean
    exit 0
fi

# --- script / install.sh install path ---

gnome-extensions disable "$UUID" >/dev/null 2>&1 || true
systemctl --user disable --now waydroid-pen-session.path \
    >/dev/null 2>&1 || true
systemctl --user stop waydroid-pen-session-reapply.service \
    >/dev/null 2>&1 || true

# Prefer a clean desktop handoff while the helper still exists, then stop the
# relay so uinput proxies disappear before udev restores the physical pen.
if [[ -x "$HELPER" ]] && sudo systemctl is-active --quiet waydroid-pen-relay.service; then
    sudo "$HELPER" desktop || true
fi
sudo systemctl disable --now \
    waydroid-pen-link-sync.path \
    waydroid-pen-link-sync.service \
    waydroid-pen-relay.service \
    >/dev/null 2>&1 || true
sudo systemctl reset-failed \
    waydroid-pen-link-sync.path \
    waydroid-pen-link-sync.service \
    waydroid-pen-relay.service \
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

remove_user_ui

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
    "$RULE_PATH" \
    /etc/sudoers.d/waydroid-pen-mode \
    /etc/systemd/system/waydroid-pen-link-sync.path \
    /etc/systemd/system/waydroid-pen-link-sync.service \
    /etc/systemd/system/waydroid-pen-relay.service \
    /etc/systemd/system/waydroid-container.service.d/90-pen-relay.conf \
    /usr/lib/systemd/system/waydroid-pen-link-sync.path \
    /usr/lib/systemd/system/waydroid-pen-link-sync.service \
    /usr/lib/systemd/system/waydroid-pen-relay.service \
    /usr/lib/systemd/system/waydroid-container.service.d/90-pen-relay.conf \
    /etc/waydroid-pen-mode.conf \
    /usr/local/libexec/waydroid-pen-relay \
    /usr/local/bin/waydroid-pen-bridge-user-setup \
    "$SESSION" \
    "$ANDROID_OVERLAY/keylayout/Vendor_2717_Product_3654.kl" \
    "$ANDROID_OVERLAY/keychars/Vendor_2717_Product_3654.kcm" \
    "$ANDROID_OVERLAY/keylayout/Vendor_2717_Product_3655.kl" \
    "$ANDROID_OVERLAY/keychars/Vendor_2717_Product_3655.kcm" \
    "$HELPER" \
    /run/waydroid-pen-direct \
    /run/waydroid-pen-mode/state.json \
    /run/waydroid-pen-mode/link-state.json \
    /run/waydroid-pen-mode/control.sock \
    /run/lock/waydroid-pen-mode.lock
# Best-effort cleanup if an experimental IDC overlay was installed earlier.
sudo rm -f \
    "$ANDROID_OVERLAY/idc/Vendor_2717_Product_3654.idc" \
    "$ANDROID_OVERLAY/idc/NVTCapacitivePenM80p.idc" \
    "$ANDROID_OVERLAY/idc/NVTCapacitivePenP81c.idc" \
    "$ANDROID_OVERLAY/idc/Vendor_2717_Product_3655.idc"
sudo rm -rf /usr/local/share/waydroid-pen-bridge
sudo rmdir /etc/systemd/system/waydroid-container.service.d 2>/dev/null || true
sudo rmdir /usr/lib/systemd/system/waydroid-container.service.d 2>/dev/null || true
sudo rmdir /run/waydroid-pen-mode 2>/dev/null || true

# Never restore the pre-bridge ignore rule.  That legacy file tags the
# physical M80p with LIBINPUT_IGNORE_DEVICE=1 and would leave THP unusable
# on the desktop after uninstall.  Delete both live and renamed copies.
sudo rm -f "$LEGACY_RULE_PATH" "$LEGACY_RULE_DISABLED"

systemctl --user daemon-reload 2>/dev/null || true
sudo systemctl daemon-reload

# udev keeps previously assigned properties on live nodes until a rule clears
# them.  After removing the bridge ignore rules, explicitly unset
# LIBINPUT_IGNORE_DEVICE on the physical THP pen/gesture sources.
# Live udev nodes keep previously assigned ENV values after the setting rule is
# deleted.  The reliable cleanup is: no bridge ignore rules left, then recreate
# the physical THP devices so they are enumerated cleanly for libinput.
sudo udevadm control --reload-rules
if systemctl cat xiaomi-sheng-thp.service >/dev/null 2>&1; then
    # Restart only the driver service.  It remains enabled/installed; this just
    # rebuilds M80p/P81c (and optional gestures) without LIBINPUT_IGNORE tags.
    sudo systemctl restart xiaomi-sheng-thp.service || true
    # Wait briefly for driver nodes to reappear.
    for ((i=0; i<50; i++)); do
        if [[ -e /dev/input/waydroid-pen || -e /sys/class/input ]]; then
            m80p_ok=0
            p81c_ok=0
            for event_path in /sys/class/input/event*; do
                device_name=$(cat "$event_path/device/name" 2>/dev/null || true)
                phys=$(cat "$event_path/device/phys" 2>/dev/null || true)
                if [[ "$device_name" == "NVTCapacitivePenM80p" && "$phys" == "input/pen" ]]; then
                    m80p_ok=1
                fi
                if [[ "$device_name" == "NVTCapacitivePenP81c" && "$phys" == "input/pen_p81c" ]]; then
                    p81c_ok=1
                fi
            done
            if [[ "$m80p_ok" -eq 1 && "$p81c_ok" -eq 1 ]]; then
                break
            fi
        fi
        sleep 0.1
    done
    for event_path in /sys/class/input/event*; do
        device_name=$(cat "$event_path/device/name" 2>/dev/null || true)
        phys=$(cat "$event_path/device/phys" 2>/dev/null || true)
        if [[ ( "$device_name" == "NVTCapacitivePenM80p" && "$phys" == "input/pen" ) \
                || ( "$device_name" == "NVTCapacitivePenP81c" && "$phys" == "input/pen_p81c" ) \
                || ( "$device_name" == "Xiaomi Focus Pen Pro Gestures" && "$phys" == "input/pen_p81c/gestures" ) ]]; then
            sudo udevadm trigger --action=add --sysname-match="$(basename "$event_path")" || true
        fi
    done
    sudo udevadm settle || true
fi

# Best-effort leftover cleanup from older experimental installs.
sudo rm -f /etc/udev/rules.d/98-waydroid-pen-restore-thp.rules \
    /etc/udev/rules.d/99-waydroid-pen-mode.rules.bak \
    /etc/udev/rules.d/99-waydroid-pen-mode.rules.bak.* 2>/dev/null || true

echo "Uninstalled waydroid-pen-bridge."
echo "xiaomi-sheng-thp is left installed; it was restarted to restore clean pen nodes."
echo "Physical THP pen nodes should be visible to libinput again."
echo "Reboot still recommended so every desktop session fully rediscovers them."
verify_clean
