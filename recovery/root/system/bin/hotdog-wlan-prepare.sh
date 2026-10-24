#!/system/bin/sh
set -e
umask 077
exec >/tmp/hotdog-wlan-prepare.log 2>&1
trap 'status=$?; if [ "$status" -ne 0 ]; then setprop sys.hotdog.wlan.prepare failed; fi' EXIT
module=/system/lib/modules/msmnile/qca_cld3_wlan.ko
[ -r "$module" ] || exit 1
# Derive the release from the actual bundled module, including repacked inputs.
# A matching release is only a preflight: normal insmod still enforces vermagic
# flags and symbol CRCs. Never force-load a module or start radio helpers first.
module_vermagic=$(modinfo -F vermagic "$module") || {
    echo 'WLAN: cannot read bundled module vermagic' >&2
    exit 1
}
module_release=${module_vermagic%% *}
[ -n "$module_release" ] && [ "$(uname -r)" = "$module_release" ] || {
    echo 'WLAN: bundled module release does not match the running kernel' >&2
    exit 1
}

# Native crypto initializes DE storage. Wait outside init's
# main thread; credential-encrypted user storage is not needed for WLAN.
attempt=0
while [ "$attempt" -lt 45 ]; do
    if [ -d /data/vendor/wifi ] && [ -d /vendor/firmware_mnt ] &&
            [ -d /firmware/image ]; then
        break
    fi
    sleep 1
    attempt=$((attempt + 1))
done
[ -d /data/vendor/wifi ] && [ -d /vendor/firmware_mnt ] && [ -d /firmware/image ] || exit 1

# Init starts the domain mapper early, before ICNSS's one-time lookup expires.
# Also allow a retry if its read-only firmware was unavailable during startup.
if [ "$(getprop sys.hotdog.wlan.domains)" != ready ] ||
        [ ! -r /vendor/firmware_mnt/image/modemuw.jsn ]; then
    /system/bin/sh /system/bin/hotdog-wlan-domains.sh
fi
[ "$(getprop sys.hotdog.wlan.domains)" = ready ] || {
    echo 'Hotdog WLAN: firmware domains are not ready' >&2
    exit 1
}
[ -r /vendor/firmware_mnt/image/modemuw.jsn ] || exit 1

socket_dir=/data/vendor/wifi/sockets
runtime_dir=/tmp/hotdog-cnss-sockets
if [ ! -d "$socket_dir" ]; then
    mkdir "$socket_dir"
    chmod 0770 "$socket_dir"
    chown system:wifi "$socket_dir"
fi
mkdir -p "$runtime_dir"
chmod 0770 "$runtime_dir"
chown system:wifi "$runtime_dir"
if ! grep -q " $socket_dir " /proc/mounts; then
    mount -o bind "$runtime_dir" "$socket_dir"
fi

start_service() {
    setprop ctl.start "$1"
    service_attempt=0
    while [ "$service_attempt" -lt 100 ]; do
        [ "$(getprop "init.svc.$1")" != running ] || return 0
        sleep 0.1
        service_attempt=$((service_attempt + 1))
    done
    echo "Hotdog WLAN: service did not start: $1" >&2
    return 1
}
# Modem firmware needs the stock remote-storage and TFTP servers. Start
# them before taking power references, and retain them across Wi-Fi toggles.
/system/bin/sh /system/bin/hotdog-wlan-storage.sh
start_service hotdog-rmt-storage
start_service hotdog-tftp-server
start_service hotdog-wlan-firmware

if ! grep -q '^wlan ' /proc/modules; then
    # Normal insmod preserves the kernel's module-version/CRC enforcement.
    insmod "$module"
fi
start_service hotdog-cnss-daemon
setprop sys.hotdog.wlan.prepare ready
