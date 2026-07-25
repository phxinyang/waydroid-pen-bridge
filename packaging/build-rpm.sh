#!/usr/bin/env bash
# Build a noarch RPM (expects rpmbuild).
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
NAME=waydroid-pen-bridge
VERSION=${VERSION:-0.2.0}
RELEASE=${RELEASE:-3}
OUT_DIR=${OUT_DIR:-"$ROOT_DIR/dist"}
TOPDIR=${TOPDIR:-$(mktemp -d)}
TARBALL="${NAME}-${VERSION}.tar.gz"

cleanup() {
    if [[ "${KEEP_TOPDIR:-0}" != 1 ]]; then
        rm -rf "$TOPDIR"
    fi
}
trap cleanup EXIT

mkdir -p "$TOPDIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS} "$OUT_DIR"

# Keep Version/Release in the staged spec in sync with env.
SPEC_SRC="$ROOT_DIR/packaging/${NAME}.spec"
SPEC_DST="$TOPDIR/SPECS/${NAME}.spec"
sed \
    -e "s/^Version:.*/Version:        ${VERSION}/" \
    -e "s/^Release:.*/Release:        ${RELEASE}%{?dist}/" \
    "$SPEC_SRC" >"$SPEC_DST"

STAGE=$(mktemp -d)
mkdir -p "$STAGE/${NAME}-${VERSION}"
rsync -a \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.codegraph' \
    --exclude 'dist' \
    --exclude 'packaging/*.rpm' \
    "$ROOT_DIR"/ "$STAGE/${NAME}-${VERSION}/"

tar -C "$STAGE" -czf "$TOPDIR/SOURCES/$TARBALL" "${NAME}-${VERSION}"
rm -rf "$STAGE"

rpmbuild \
    --define "_topdir $TOPDIR" \
    -ba "$SPEC_DST"

mapfile -t RPMS < <(find "$TOPDIR/RPMS" -name "${NAME}-${VERSION}*.rpm" | sort)
if [[ ${#RPMS[@]} -eq 0 ]]; then
    echo "No RPM produced" >&2
    exit 1
fi
cp -a "${RPMS[@]}" "$OUT_DIR/"
# Also copy src rpm if present.
find "$TOPDIR/SRPMS" -name "${NAME}-${VERSION}*.rpm" -exec cp -a {} "$OUT_DIR/" \; || true

echo "RPMs in $OUT_DIR:"
ls -la "$OUT_DIR"/${NAME}-${VERSION}*.rpm
