#!/system/bin/sh
# Keep TFTP RFS writes in RAM, including when crypto needs writable persist.
set -e
umask 077
base=/tmp/hotdog-wlan-rfs
targets='/mnt/vendor/persist/rfs /mnt/vendor/persist/hlos_rfs /data/vendor/tombstones/rfs /data/vendor/olog'
grep ' /mnt/vendor/persist ' /proc/mounts | grep -Eq ' (ro|rw),'

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
mkdir -p "$base"
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

# Keep these mirrors and stock backends for the recovery session. Switching
# Wi-Fi off only releases the radio's power references, not its file services.
for target in $targets; do
    name=$(mirror_name "$target")
    current_root=$(awk -v target="$target" '$5 == target { print $4 }' /proc/self/mountinfo)
    if [ -z "$current_root" ]; then
        mount -o bind "$base/$name" "$target"
    fi
done
