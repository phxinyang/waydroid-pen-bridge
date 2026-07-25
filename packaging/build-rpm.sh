#!/usr/bin/env bash
# Build a noarch RPM on the current machine (expects rpmbuild).
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=${VERSION:-0.2.0}
NAME=waydroid-pen-bridge
TARBALL="${NAME}-${VERSION}.tar.gz"
TOPDIR=${TOPDIR:-$HOME/rpmbuild}

mkdir -p "$TOPDIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

# Stage a clean source tree for the tarball.
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/${NAME}-${VERSION}"
rsync -a \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.codegraph' \
    --exclude 'packaging/*.rpm' \
    "$ROOT_DIR"/ "$STAGE/${NAME}-${VERSION}/"

tar -C "$STAGE" -czf "$TOPDIR/SOURCES/$TARBALL" "${NAME}-${VERSION}"
cp "$ROOT_DIR/packaging/${NAME}.spec" "$TOPDIR/SPECS/${NAME}.spec"

rpmbuild \
    --define "_topdir $TOPDIR" \
    -ba "$TOPDIR/SPECS/${NAME}.spec"

echo "RPMs:"
find "$TOPDIR/RPMS" -name "${NAME}-${VERSION}*.rpm" -print
