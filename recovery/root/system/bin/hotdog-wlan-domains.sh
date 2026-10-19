#!/system/bin/sh
set -e
umask 077
exec >/tmp/hotdog-wlan-domains.log 2>&1
setprop sys.hotdog.wlan.domains preparing
trap 'status=$?; if [ "$status" -ne 0 ]; then setprop sys.hotdog.wlan.domains failed; fi' EXIT

# ICNSS requests its domain once during kernel probe. Populate the mapper
# before that request times out, independently of the Wi-Fi UI or CE unlock.
attempt=0
while [ "$attempt" -lt 45 ]; do
    if ! grep -q ' /vendor ' /proc/mounts &&
            [ -r /vendor/firmware_mnt/image/modemuw.jsn ]; then
        break
    fi
    sleep 1
    attempt=$((attempt + 1))
done
# Native partition discovery may temporarily mount vendor. Wait for its normal
# cleanup, then use init's ramdisk symlink to the read-only firmware partition.
# A child bind under installed vendor would keep that partition busy.
! grep -q ' /vendor ' /proc/mounts || exit 1
[ -L /vendor/firmware_mnt ] || exit 1
[ "$(readlink /vendor/firmware_mnt)" = /firmware ] || exit 1
[ -r /vendor/firmware_mnt/image/modemuw.jsn ] || {
    echo 'Hotdog WLAN: missing the WLAN firmware-domain descriptor' >&2
    exit 1
}

start_service() {
    setprop ctl.start "$1"
    service_attempt=0
    while [ "$service_attempt" -lt 100 ]; do
        [ "$(getprop "init.svc.$1")" != running ] || return 0
        sleep 0.1
        service_attempt=$((service_attempt + 1))
    done
    echo "Hotdog WLAN: domain service did not start: $1" >&2
    return 1
}
start_service hotdog-qrtr-ns
start_service hotdog-pd-mapper
setprop sys.hotdog.wlan.domains ready
