#!/bin/sh
set -e
case "$1" in
    configure)
        /usr/local/share/waydroid-pen-bridge/scripts/configure-system.sh || true
        ;;
esac
exit 0
