Name:           waydroid-pen-bridge
Version:        0.2.0
Release:        3%{?dist}
Summary:        Route Xiaomi sheng pen between desktop and Waydroid
License:        MIT
URL:            https://github.com/phxinyang/waydroid-pen-bridge
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3
Requires:       systemd
Requires:       waydroid
Recommends:     plasma-desktop
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
install -d %{buildroot}/usr/local/share/waydroid-pen-bridge/scripts
install -m 0755 packaging/scripts/configure-system.sh \
    packaging/scripts/pre-remove.sh \
    packaging/scripts/remove-system.sh \
    %{buildroot}/usr/local/share/waydroid-pen-bridge/scripts/

install -d %{buildroot}/usr/local/bin
cat > %{buildroot}/usr/local/bin/waydroid-pen-bridge-user-setup <<'EOF'
#!/usr/bin/env bash
exec /usr/local/share/waydroid-pen-bridge/user-setup.sh "$@"
EOF
chmod 0755 %{buildroot}/usr/local/bin/waydroid-pen-bridge-user-setup
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

install -d %{buildroot}/usr/local/share/waydroid-pen-bridge/config
install -m 0644 config/99-waydroid-pen-mode.rules.in \
    %{buildroot}/usr/local/share/waydroid-pen-bridge/config/99-waydroid-pen-mode.rules.in

install -d %{buildroot}/usr/local/share/waydroid-pen-bridge/android
install -m 0644 android/Vendor_2717_Product_3654.kl \
    android/Vendor_2717_Product_3654.kcm \
    android/Vendor_2717_Product_3655.kl \
    android/Vendor_2717_Product_3655.kcm \
    %{buildroot}/usr/local/share/waydroid-pen-bridge/android/

%pre
if ! getent group 1004 >/dev/null 2>&1; then
    groupadd --gid 1004 android-input || true
fi

%post
/usr/local/share/waydroid-pen-bridge/scripts/configure-system.sh || true

%preun
# $1 == 0 means full uninstall (not upgrade). Scripts are still on disk here.
if [[ "$1" -eq 0 ]]; then
    /usr/local/share/waydroid-pen-bridge/scripts/pre-remove.sh || true
    /usr/local/share/waydroid-pen-bridge/scripts/remove-system.sh || true
fi

%postun
if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
fi

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
* Sat Jul 25 2026 xinyang <phxinyang@users.noreply.github.com> - 0.2.0-3
- Share configure/remove scripts between RPM and DEB packaging

* Sat Jul 25 2026 xinyang <phxinyang@users.noreply.github.com> - 0.2.0-2
- Fix udev group expansion and user-setup under rpm post

* Sat Jul 25 2026 xinyang <phxinyang@users.noreply.github.com> - 0.2.0-1
- Initial RPM packaging for system-layer install/uninstall
