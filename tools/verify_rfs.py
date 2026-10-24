"""Require the stock H40/F22 TFTP layout and private RAM ownership."""

STOCK_LAYOUT = '''apq gnss modem yes
mdm adsp lpass yes
mdm cdsp cdsp no
mdm mpss modem yes
mdm slpi slpi no
mdm tn tn no
msm adsp lpass yes
msm cdsp cdsp yes
msm mpss modem yes
msm slpi slpi yes'''


def verify_rfs_configuration(storage):
    if "done <<'RFS_LAYOUT'\n" not in storage or storage.split(
            "done <<'RFS_LAYOUT'\n", 1)[1].split('\nRFS_LAYOUT', 1)[0] != STOCK_LAYOUT:
        raise ValueError('TFTP requires the complete original H40/F22 RFS layout')
    required = (
        "! grep -q ' /vendor ' /proc/mounts || exit 1",
        '[ -d /vendor ] && [ ! -L /vendor ] || exit 1',
        '[ "$(readlink /vendor/firmware_mnt)" = /firmware ] || exit 1',
        '[ ! -L "$base" ] || exit 1',
        '[ -z "$(find "$base" -type l -print)" ] || exit 1',
        'chown 2903:2903 "$base/$name"', 'chmod 0700 "$base/$name"',
        '[ ! -L "$1" ] || exit 1', 'chown 2903:2903 "$1"',
        'chmod 0700 "$1"', 'chmod 0755 "$1"',
        '[ "$(readlink "$2")" = "$1" ] || exit 1',
        '[ ! -e "$2" ] || exit 1', 'ln -s "$1" "$2"',
        'rfs_link /vendor/firmware_mnt "$dir/readonly/firmware"',
        'rfs_link /vendor/firmware "$dir/readonly/vendor/firmware"',
        'rfs_link /mnt/vendor/persist/hlos_rfs/shared "$dir/hlos"',
        'rfs_link "/mnt/vendor/persist/rfs/$family/$subsystem" "$dir/readwrite"',
        'rfs_link /mnt/vendor/persist/rfs/shared "$dir/shared"',
        'rfs_link "/data/vendor/tombstones/rfs/$dump" "$dir/ramdumps"',
        'rfs_link /data/vendor/olog "$dir/olog"',
        'ram_dir "$base/rfs/shared"', 'ram_dir "$base/hlos_rfs/shared"',
        'ram_dir "$base/rfs/$family"', 'ram_dir "$base/rfs/$family/$subsystem"',
        'ram_dir "$base/ramdumps/$dump"',
    )
    if any(line not in storage for line in required):
        raise ValueError('TFTP RFS links, RAM ownership or confinement guards are missing')
    if storage.index("! grep -q ' /vendor '") > storage.index('rfs_dir /vendor/rfs'):
        raise ValueError('RFS preparation must wait for installed vendor release')
    if storage.index('RFS_LAYOUT\n', storage.index("done <<'RFS_LAYOUT'")) > storage.index('mount -o bind'):
        raise ValueError('RFS layout and ownership must precede RAM binds')
