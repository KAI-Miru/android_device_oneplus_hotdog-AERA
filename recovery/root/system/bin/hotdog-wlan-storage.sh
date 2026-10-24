#!/system/bin/sh
# Keep TFTP RFS writes in RAM, including when crypto needs writable persist.
set -e
umask 077
base=/tmp/hotdog-wlan-rfs
targets='/mnt/vendor/persist/rfs /mnt/vendor/persist/hlos_rfs /data/vendor/tombstones/rfs /data/vendor/olog'
grep ' /mnt/vendor/persist ' /proc/mounts | grep -Eq ' (ro|rw),'
# Only modify the native ramdisk after temporary installed-vendor discovery.
! grep -q ' /vendor ' /proc/mounts || exit 1
[ -d /vendor ] && [ ! -L /vendor ] || exit 1
[ -L /vendor/firmware_mnt ] || exit 1
[ "$(readlink /vendor/firmware_mnt)" = /firmware ] || exit 1

mirror_name() {
    case "$1" in
        /mnt/vendor/persist/rfs) echo rfs ;;
        /mnt/vendor/persist/hlos_rfs) echo hlos_rfs ;;
        /data/vendor/tombstones/rfs) echo ramdumps ;;
        /data/vendor/olog) echo olog ;;
        *) return 1 ;;
    esac
}

# Refuse a foreign bind instead of hiding another recovery user's mount.
for target in $targets; do
    [ -d "$target" ] && [ ! -L "$target" ] || exit 1
    name=$(mirror_name "$target")
    current_root=$(awk -v target="$target" '$5 == target { print $4 }' /proc/self/mountinfo)
    [ -z "$current_root" ] || [ "$current_root" = "/hotdog-wlan-rfs/$name" ] || exit 1
done
[ ! -L "$base" ] || exit 1
mkdir -p "$base"
for name in rfs hlos_rfs ramdumps olog; do
    [ ! -L "$base/$name" ] || exit 1
done
if [ ! -f "$base/seeded" ]; then
    for target in $targets; do
        name=$(mirror_name "$target")
        mkdir -p "$base/$name"
        case "$target" in
            /mnt/vendor/persist/*) cp -a "$target/." "$base/$name/" ;;
        esac
    done
    [ -z "$(find "$base/rfs" "$base/hlos_rfs" -type l -print)" ] || exit 1
    touch "$base/seeded"
fi

# TFTP drops to oem_2903 internally. Repair only private RAM directory roots;
# never chown persist, copied calibration files, or arbitrary link targets.
[ -z "$(find "$base" -type l -print)" ] || exit 1
for name in rfs hlos_rfs ramdumps olog; do
    chown 2903:2903 "$base/$name"
    chmod 0700 "$base/$name"
done
ram_dir() {
    [ ! -L "$1" ] || exit 1
    if [ ! -e "$1" ]; then
        mkdir "$1"
        chown 2903:2903 "$1"
        chmod 0700 "$1"
    fi
    [ -d "$1" ] || exit 1
}
ram_dir "$base/rfs/shared"
ram_dir "$base/hlos_rfs/shared"

# Reproduce the original H40/F22 vendor RFS link layout. Public directory
# traversal is needed for firmware reads; all writable destinations stay RAM.
rfs_dir() {
    [ ! -L "$1" ] || exit 1
    mkdir -p "$1"
    chmod 0755 "$1"
}
rfs_link() {
    if [ -L "$2" ]; then
        [ "$(readlink "$2")" = "$1" ] || exit 1
    else
        [ ! -e "$2" ] || exit 1
        ln -s "$1" "$2"
    fi
}
rfs_dir /vendor/rfs
while read -r family subsystem dump vendor_firmware; do
    rfs_dir "/vendor/rfs/$family"
    dir="/vendor/rfs/$family/$subsystem"
    rfs_dir "$dir"
    rfs_dir "$dir/readonly"
    rfs_link /vendor/firmware_mnt "$dir/readonly/firmware"
    if [ "$vendor_firmware" = yes ]; then
        rfs_dir "$dir/readonly/vendor"
        rfs_link /vendor/firmware "$dir/readonly/vendor/firmware"
    fi
    rfs_link /mnt/vendor/persist/hlos_rfs/shared "$dir/hlos"
    rfs_link "/mnt/vendor/persist/rfs/$family/$subsystem" "$dir/readwrite"
    rfs_link /mnt/vendor/persist/rfs/shared "$dir/shared"
    rfs_link "/data/vendor/tombstones/rfs/$dump" "$dir/ramdumps"
    if [ "$subsystem" = mpss ]; then
        rfs_link /data/vendor/olog "$dir/olog"
    fi
    ram_dir "$base/rfs/$family"
    ram_dir "$base/rfs/$family/$subsystem"
    ram_dir "$base/ramdumps/$dump"
done <<'RFS_LAYOUT'
apq gnss modem yes
mdm adsp lpass yes
mdm cdsp cdsp no
mdm mpss modem yes
mdm slpi slpi no
mdm tn tn no
msm adsp lpass yes
msm cdsp cdsp yes
msm mpss modem yes
msm slpi slpi yes
RFS_LAYOUT

# Keep these mirrors and stock backends for the recovery session. Switching
# Wi-Fi off only releases the radio's power references, not its file services.
for target in $targets; do
    name=$(mirror_name "$target")
    current_root=$(awk -v target="$target" '$5 == target { print $4 }' /proc/self/mountinfo)
    if [ -z "$current_root" ]; then
        mount -o bind "$base/$name" "$target"
    fi
done
