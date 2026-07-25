#!/bin/sh
set -e
if ! getent group 1004 >/dev/null 2>&1; then
    groupadd --gid 1004 android-input 2>/dev/null || true
fi
exit 0
