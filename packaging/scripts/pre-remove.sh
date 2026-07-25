#!/usr/bin/env bash
# Runs before package files are removed (rpm %preun full remove / deb prerm remove).
set -euo pipefail

HELPER=/usr/local/libexec/waydroid-pen-mode

if [[ -x "$HELPER" ]] && systemctl is-active --quiet waydroid-pen-relay.service 2>/dev/null; then
    "$HELPER" desktop || true
fi

if command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now \
        waydroid-pen-link-sync.path \
        waydroid-pen-link-sync.service \
        waydroid-pen-relay.service >/dev/null 2>&1 || true
    systemctl reset-failed \
        waydroid-pen-link-sync.path \
        waydroid-pen-link-sync.service \
        waydroid-pen-relay.service >/dev/null 2>&1 || true
fi
