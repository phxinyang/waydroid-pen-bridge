Name:           waydroid-pen-bridge
Version:        0.2.0
Release:        2%{?dist}
Summary:        Route Xiaomi sheng pen between desktop and Waydroid
License:        MIT
URL:            https://github.com/phxinyang/waydroid-pen-bridge
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3
Requires:       systemd
Requires:       waydroid
Recommends:      plasma-desktop
# THP driver is external; checked at install time when the unit exists.

%description
Stable dual-model pen proxies and mode routing for Xiaomi Pad 6S Pro (sheng)
with Waydroid. System layer only: helpers, units, udev, LXC mounts, Android
keylayout overlay. Desktop tray/extension: run waydroid-pen-bridge-user-setup
after login.

%prep
%setup -q

%build
# no compile

%install
rm -rf %{buildroot}
install -d %{buildroot}/usr/local/libexec
install -m 0755 helper/waydroid-pen-mode.py \
    %{buildroot}/usr/local/libexec/waydroid-pen-mode
install -m 0755 helper/waydroid-pen-relay.py \
    %{buildroot}/usr/local/libexec/waydroid-pen-relay
install -m 0755 helper/waydroid-pen-session.py \
    %{buildroot}/usr/local/libexec/waydroid-pen-session

install -d %{buildroot}/usr/local/share/waydroid-pen-bridge
cp -a android config extension kde user-setup.sh \
    %{buildroot}/usr/local/share/waydroid-pen-bridge/
# Convenience entry for post-login UI setup.
install -d %{buildroot}/usr/local/bin
cat > %{buildroot}/usr/local/bin/waydroid-pen-bridge-user-setup <<'EOF'
#!/usr/bin/env bash
exec /usr/local/share/waydroid-pen-bridge/user-setup.sh "$@"
EOF
chmod 0755 %{buildroot}/usr/local/bin/waydroid-pen-bridge-user-setup
# user-setup resolves ROOT_DIR from its own path; keep it next to assets.
chmod 0755 %{buildroot}/usr/local/share/waydroid-pen-bridge/user-setup.sh

install -d %{buildroot}%{_unitdir}
install -m 0644 config/waydroid-pen-relay.service \
    %{buildroot}%{_unitdir}/waydroid-pen-relay.service
install -m 0644 config/waydroid-pen-link-sync.path \
    %{buildroot}%{_unitdir}/waydroid-pen-link-sync.path
install -m 0644 config/waydroid-pen-link-sync.service \
    %{buildroot}%{_unitdir}/waydroid-pen-link-sync.service

install -d %{buildroot}%{_unitdir}/waydroid-container.service.d
install -m 0644 config/waydroid-container-pen.conf \
    %{buildroot}%{_unitdir}/waydroid-container.service.d/90-pen-relay.conf

install -d %{buildroot}%{_sysconfdir}
install -m 0644 config/waydroid-pen-mode.conf \
    %{buildroot}%{_sysconfdir}/waydroid-pen-mode.conf

# udev template is rendered in %post (needs login UID + android-input group).
install -d %{buildroot}/usr/local/share/waydroid-pen-bridge/config
install -m 0644 config/99-waydroid-pen-mode.rules.in \
    %{buildroot}/usr/local/share/waydroid-pen-bridge/config/99-waydroid-pen-mode.rules.in

# Android overlays shipped under share; %post copies into Waydroid overlay.
install -d %{buildroot}/usr/local/share/waydroid-pen-bridge/android
install -m 0644 android/Vendor_2717_Product_3654.kl \
    android/Vendor_2717_Product_3654.kcm \
    android/Vendor_2717_Product_3655.kl \
    android/Vendor_2717_Product_3655.kcm \
    %{buildroot}/usr/local/share/waydroid-pen-bridge/android/

%pre
# Ensure android-input gid 1004 exists before udev rules reference it.
if ! getent group 1004 >/dev/null 2>&1; then
    groupadd --gid 1004 android-input || true
fi

%post
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

# Prefer installing sudo user, else seat0 active user, else first uid>=1000, else 1000.
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
echo "rpm post: desktop user=$INSTALL_USER uid=$INSTALL_UID"

if group_entry=$(getent group 1004); then
    android_group=${group_entry%%%%:*}
else
    groupadd --gid 1004 android-input || true
    android_group=android-input
fi

# Render udev rules for this machine's login user.
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

# Sudoers for mode helper (same commands as install.sh).
if [[ -n "$INSTALL_USER" && "$INSTALL_USER" != root ]]; then
    {
        printf '%%s ALL=(root) NOPASSWD: %%s direct\n' "$INSTALL_USER" "$HELPER"
        printf '%%s ALL=(root) NOPASSWD: %%s desktop\n' "$INSTALL_USER" "$HELPER"
        printf '%%s ALL=(root) NOPASSWD: %%s sync\n' "$INSTALL_USER" "$HELPER"
        printf '%%s ALL=(root) NOPASSWD: %%s focus *\n' "$INSTALL_USER" "$HELPER"
        printf '%%s ALL=(root) NOPASSWD: %%s status\n' "$INSTALL_USER" "$HELPER"
        printf '%%s ALL=(root) NOPASSWD: %%s map *\n' "$INSTALL_USER" "$HELPER"
        printf '%%s ALL=(root) NOPASSWD: %%s unmap\n' "$INSTALL_USER" "$HELPER"
    } >"$SUDOERS_PATH"
    chmod 0440 "$SUDOERS_PATH"
    if command -v visudo >/dev/null 2>&1; then
        visudo -cf "$SUDOERS_PATH" >/dev/null || rm -f "$SUDOERS_PATH"
    fi
fi

# Android KL/KCM overlay.
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

# LXC node mounts.
if [[ -f "$LXC_CONFIG" ]]; then
    lxc_backed_up=false
    backup_lxc() {
        if [[ "$lxc_backed_up" == false ]]; then
            cp -a "$LXC_CONFIG" "$LXC_CONFIG.wayland-pen-mode-backup-$(date +%%Y%%m%%d-%%H%%M%%S)" || true
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
            printf '%%s\n' "$line" >>"$LXC_CONFIG"
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
        /system/bin/sh -c 'exec "$@"' waydroid-pen-rpm "$@"
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
for event_path in /sys/class/input/event*; do
    device_name=$(cat "$event_path/device/name" 2>/dev/null || true)
    if [[ "$device_name" == "NVTCapacitivePenM80p" \
            || "$device_name" == "NVTCapacitivePenP81c" \
            || "$device_name" == "Xiaomi Focus Pen Pro Gestures" ]]; then
        udevadm trigger --action=add "$event_path" || true
    fi
done
udevadm settle || true

%systemd_post waydroid-pen-relay.service waydroid-pen-link-sync.path
systemctl reset-failed waydroid-pen-link-sync.service waydroid-pen-link-sync.path >/dev/null 2>&1 || true
systemctl enable waydroid-pen-relay.service waydroid-pen-link-sync.path >/dev/null 2>&1 || true
if systemctl is-active --quiet xiaomi-sheng-thp.service; then
    systemctl restart waydroid-pen-relay.service || true
    systemctl restart waydroid-pen-link-sync.path || true
elif systemctl is-active --quiet waydroid-pen-relay.service; then
    systemctl restart waydroid-pen-link-sync.path || true
fi

# Best-effort UI setup for the resolved user (needs session bus; may no-op).
if [[ -n "$INSTALL_USER" && "$INSTALL_USER" != root && -x /usr/local/bin/waydroid-pen-bridge-user-setup ]]; then
    if [[ -S "/run/user/$(id -u "$INSTALL_USER")/bus" ]]; then
        # Drop SUDO_USER so user-setup does not treat root as the target.
        sudo -u "$INSTALL_USER" --preserve-env=XDG_RUNTIME_DIR,DBUS_SESSION_BUS_ADDRESS \
            env -u SUDO_USER \
            XDG_RUNTIME_DIR="/run/user/$(id -u "$INSTALL_USER")" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$INSTALL_USER")/bus" \
            /usr/local/bin/waydroid-pen-bridge-user-setup || true
    else
        echo "Session bus for $INSTALL_USER not up; run waydroid-pen-bridge-user-setup after login."
    fi
fi

echo "waydroid-pen-bridge installed (rpm system layer)."
echo "If tray/extension is missing after login: waydroid-pen-bridge-user-setup"
echo "Reboot once so udev hides physical pens before login when possible."

%preun
HELPER=/usr/local/libexec/waydroid-pen-mode
if [[ "$1" -eq 0 ]]; then
    # Full uninstall only (not upgrade).
    if [[ -x "$HELPER" ]] && systemctl is-active --quiet waydroid-pen-relay.service; then
        "$HELPER" desktop || true
    fi
    %systemd_preun waydroid-pen-link-sync.path waydroid-pen-relay.service
    systemctl disable --now \
        waydroid-pen-link-sync.path \
        waydroid-pen-link-sync.service \
        waydroid-pen-relay.service >/dev/null 2>&1 || true
fi

%postun
LXC_CONFIG=/var/lib/waydroid/lxc/waydroid/config_nodes
ANDROID_OVERLAY=/var/lib/waydroid/overlay/system/usr
RULE_PATH=/etc/udev/rules.d/99-waydroid-pen-mode.rules
LEGACY_RULE_PATH=/etc/udev/rules.d/99-waydroid-evdev-pen.rules
LEGACY_RULE_DISABLED=/etc/udev/rules.d/99-waydroid-evdev-pen.rules.disabled-by-waydroid-pen-mode
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

if [[ "$1" -eq 0 ]]; then
    # Full remove.
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
    # Never restore legacy M80p ignore rule.
    rm -f "$LEGACY_RULE_PATH" "$LEGACY_RULE_DISABLED"

    udevadm control --reload-rules || true
    if systemctl cat xiaomi-sheng-thp.service >/dev/null 2>&1; then
        systemctl restart xiaomi-sheng-thp.service || true
    fi
    echo "waydroid-pen-bridge removed; xiaomi-sheng-thp left installed."
    echo "Run waydroid-pen-bridge-user-setup cleanup is manual for user UI;"
    echo "or remove plasmoid/extension from the user session if still present."
fi
%systemd_postun_with_restart waydroid-pen-relay.service

%files
%license LICENSE
%doc README.md README.zh-CN.md
/usr/local/libexec/waydroid-pen-mode
/usr/local/libexec/waydroid-pen-relay
/usr/local/libexec/waydroid-pen-session
/usr/local/bin/waydroid-pen-bridge-user-setup
/usr/local/share/waydroid-pen-bridge/
%config(noreplace) %{_sysconfdir}/waydroid-pen-mode.conf
%{_unitdir}/waydroid-pen-relay.service
%{_unitdir}/waydroid-pen-link-sync.path
%{_unitdir}/waydroid-pen-link-sync.service
%{_unitdir}/waydroid-container.service.d/90-pen-relay.conf

%changelog
* Sat Jul 25 2026 xinyang <phxinyang@users.noreply.github.com> - 0.2.0-1
- Initial RPM packaging for system-layer install/uninstall
