#!/usr/bin/env bash
# Build an architecture-independent .deb without external packagers.
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
NAME=waydroid-pen-bridge
VERSION=${VERSION:-0.2.0}
RELEASE=${RELEASE:-1}
OUT_DIR=${OUT_DIR:-"$ROOT_DIR/dist"}
ARCH=all
PKG_VER="${VERSION}-${RELEASE}"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$OUT_DIR" "$STAGE/DEBIAN"
ROOTFS="$STAGE"

install_tree() {
    local mode=$1 src=$2 dst=$3
    install -d "$(dirname "$ROOTFS$dst")"
    if [[ -d "$src" ]]; then
        mkdir -p "$ROOTFS$dst"
        cp -a "$src"/. "$ROOTFS$dst"/
    else
        install -m "$mode" "$src" "$ROOTFS$dst"
    fi
}

install -d "$ROOTFS/usr/local/libexec"
install -m 0755 "$ROOT_DIR/helper/waydroid-pen-mode.py" \
    "$ROOTFS/usr/local/libexec/waydroid-pen-mode"
install -m 0755 "$ROOT_DIR/helper/waydroid-pen-relay.py" \
    "$ROOTFS/usr/local/libexec/waydroid-pen-relay"
install -m 0755 "$ROOT_DIR/helper/waydroid-pen-session.py" \
    "$ROOTFS/usr/local/libexec/waydroid-pen-session"

install -d "$ROOTFS/usr/local/bin"
install -m 0755 "$ROOT_DIR/packaging/waydroid-pen-bridge-user-setup" \
    "$ROOTFS/usr/local/bin/waydroid-pen-bridge-user-setup"

install -d "$ROOTFS/usr/local/share/waydroid-pen-bridge"
cp -a "$ROOT_DIR/android" "$ROOT_DIR/config" "$ROOT_DIR/extension" "$ROOT_DIR/kde" \
    "$ROOTFS/usr/local/share/waydroid-pen-bridge/"
install -m 0755 "$ROOT_DIR/user-setup.sh" \
    "$ROOTFS/usr/local/share/waydroid-pen-bridge/user-setup.sh"
install -d "$ROOTFS/usr/local/share/waydroid-pen-bridge/scripts"
install -m 0755 \
    "$ROOT_DIR/packaging/scripts/configure-system.sh" \
    "$ROOT_DIR/packaging/scripts/pre-remove.sh" \
    "$ROOT_DIR/packaging/scripts/remove-system.sh" \
    "$ROOTFS/usr/local/share/waydroid-pen-bridge/scripts/"

install -d "$ROOTFS/usr/lib/systemd/system/waydroid-container.service.d"
install -m 0644 "$ROOT_DIR/config/waydroid-pen-relay.service" \
    "$ROOTFS/usr/lib/systemd/system/waydroid-pen-relay.service"
install -m 0644 "$ROOT_DIR/config/waydroid-pen-link-sync.path" \
    "$ROOTFS/usr/lib/systemd/system/waydroid-pen-link-sync.path"
install -m 0644 "$ROOT_DIR/config/waydroid-pen-link-sync.service" \
    "$ROOTFS/usr/lib/systemd/system/waydroid-pen-link-sync.service"
install -m 0644 "$ROOT_DIR/config/waydroid-container-pen.conf" \
    "$ROOTFS/usr/lib/systemd/system/waydroid-container.service.d/90-pen-relay.conf"

install -d "$ROOTFS/etc"
install -m 0644 "$ROOT_DIR/config/waydroid-pen-mode.conf" \
    "$ROOTFS/etc/waydroid-pen-mode.conf"

install -d "$ROOTFS/usr/share/doc/$NAME"
install -m 0644 "$ROOT_DIR/LICENSE" "$ROOT_DIR/README.md" "$ROOT_DIR/README.zh-CN.md" \
    "$ROOTFS/usr/share/doc/$NAME/"

# Installed size in KiB
SIZE_KB=$(du -sk "$ROOTFS" | awk '{print $1}')

cat >"$STAGE/DEBIAN/control" <<EOF
Package: $NAME
Version: $PKG_VER
Section: misc
Priority: optional
Architecture: $ARCH
Maintainer: xinyang <phxinyang@users.noreply.github.com>
Installed-Size: $SIZE_KB
Depends: python3, systemd
Recommends: waydroid
Homepage: https://github.com/phxinyang/waydroid-pen-bridge
Description: Route Xiaomi sheng pen between desktop and Waydroid
 Stable dual-model pen proxies and mode routing. System layer only;
 run waydroid-pen-bridge-user-setup after login. Requires xiaomi-sheng-thp
 separately.
EOF

install -m 0755 "$ROOT_DIR/packaging/scripts/deb-preinst.sh" "$STAGE/DEBIAN/preinst"
install -m 0755 "$ROOT_DIR/packaging/scripts/deb-postinst.sh" "$STAGE/DEBIAN/postinst"
install -m 0755 "$ROOT_DIR/packaging/scripts/deb-prerm.sh" "$STAGE/DEBIAN/prerm"
install -m 0755 "$ROOT_DIR/packaging/scripts/deb-postrm.sh" "$STAGE/DEBIAN/postrm"

# conffiles
cat >"$STAGE/DEBIAN/conffiles" <<EOF
/etc/waydroid-pen-mode.conf
EOF

DEB_PATH="$OUT_DIR/${NAME}_${PKG_VER}_${ARCH}.deb"
rm -f "$DEB_PATH"

if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --root-owner-group --build "$STAGE" "$DEB_PATH"
else
    # Fallback: assemble .deb with tar + ar (no dpkg tools required).
    BUILD=$(mktemp -d)
    (
        cd "$STAGE"
        tar --owner=0 --group=0 --numeric-owner -cf "$BUILD/data.tar" \
            --exclude=./DEBIAN .
        gzip -n9 "$BUILD/data.tar"
        cd DEBIAN
        tar --owner=0 --group=0 --numeric-owner -cf "$BUILD/control.tar" .
        gzip -n9 "$BUILD/control.tar"
    )
    printf '2.0\n' >"$BUILD/debian-binary"
    (
        cd "$BUILD"
        if command -v ar >/dev/null 2>&1; then
            ar r "$DEB_PATH" debian-binary control.tar.gz data.tar.gz
        else
            # Minimal GNU ar writer for three members.
            python3 - "$DEB_PATH" debian-binary control.tar.gz data.tar.gz <<'PY'
import sys, pathlib, time
out = pathlib.Path(sys.argv[1])
members = sys.argv[2:]
parts = [b"!<arch>\n"]
for name in members:
    data = pathlib.Path(name).read_bytes()
    header = (
        f"{name:<16}{int(time.time()):<12}0{'':<6}0{'':<6}100644{'':<8}{len(data):<10}`\n"
    ).encode("ascii")
    parts.append(header)
    parts.append(data)
    if len(data) % 2 == 1:
        parts.append(b"\n")
out.write_bytes(b"".join(parts))
print("wrote", out)
PY
        fi
    )
    rm -rf "$BUILD"
fi

echo "DEB: $DEB_PATH"
ls -la "$DEB_PATH"
