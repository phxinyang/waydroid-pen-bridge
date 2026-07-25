#!/bin/sh
set -e
case "$1" in
    remove|deconfigure)
        /usr/local/share/waydroid-pen-bridge/scripts/pre-remove.sh || true
        ;;
esac
exit 0
