"""Check upstream BusyBox identity, applet table and native ramdisk staging."""
import argparse
import configparser
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import stat
import struct

ROOT = Path(__file__).resolve().parents[1]
SOURCE = {
    'repository': 'https://github.com/AERA-Recovery/android_vendor_recovery.git',
    'commit': '7b4e41362938ee3498fc0e8a4f3e0528bf320efd',
    'source': 'prebuilt/arm64/busybox', 'destination': 'sbin/busybox',
    'bytes': 1498688,
    'sha256': 'c629fce4b0dd3ba9775f851d0941e74582115f423258d3a79800f2bd11d30f5c',
    'applet_count': 353,
    'required_applets': ['ip', 'nc', 'nslookup', 'ping', 'sh', 'timeout', 'udhcpc', 'wget'],
}


def applets(blob):
    """Read BusyBox's contiguous sorted applet_names table, not usage strings."""
    marker = b'[\0[[\0'
    if blob.count(marker) != 1:
        raise ValueError('BusyBox applet table is absent or ambiguous')
    names = []
    for item in blob[blob.index(marker):].split(b'\0'):
        if not item or not re.fullmatch(rb'[A-Za-z0-9_.\[\]-]+', item):
            break
        name = item.decode('ascii')
        if names and name <= names[-1]:
            break
        names.append(name)
    missing = sorted(set(SOURCE['required_applets']) - set(names))
    if missing:
        raise ValueError(f'BusyBox required applets missing: {missing}')
    return names


def inspect_blob(blob):
    if len(blob) < 64 or blob[:7] != b'\x7fELF\x02\x01\x01':
        raise ValueError('BusyBox must be native ARM64')
    header = struct.unpack_from('<16sHHIQQQIHHHHHH', blob)
    if header[1:4] != (2, 183, 1) or header[8] != 64:
        raise ValueError('BusyBox must be an ARM64 executable')
    offset, size, count = header[5], header[9], header[10]
    if size != 56 or not count or offset < 64 or offset + size * count > len(blob):
        raise ValueError('BusyBox ELF program headers are invalid')
    segments = [struct.unpack_from('<I', blob, offset + size * i)[0] for i in range(count)]
    if 1 not in segments or any(kind in (2, 3) for kind in segments):
        raise ValueError('Upstream BusyBox must be standalone and statically linked')
    return applets(blob)


def verify_blob(blob):
    if len(blob) != SOURCE['bytes'] or hashlib.sha256(blob).hexdigest() != SOURCE['sha256']:
        raise ValueError('BusyBox differs from the exact pinned upstream prebuilt')
    names = inspect_blob(blob)
    if len(names) != SOURCE['applet_count']:
        raise ValueError('BusyBox applet count differs from the pinned prebuilt')
    return {'sha256': SOURCE['sha256'], 'bytes': len(blob), 'architecture': 'ARM64',
            'static': True, 'applet_count': len(names), 'required_applets': SOURCE['required_applets']}


def verify_tree(root):
    root = Path(root)
    if json.loads((root / 'tools/busybox-source.json').read_text()) != SOURCE:
        raise ValueError('BusyBox source record differs from the audited upstream input')
    lock = json.loads((root / 'sources.lock.json').read_text())
    vendor = [p for p in lock['projects'] if p['path'] == 'vendor/recovery']
    if len(vendor) != 1 or (vendor[0]['url'], vendor[0]['commit']) != (SOURCE['repository'], SOURCE['commit']):
        raise ValueError('BusyBox requires the audited vendor/recovery source pin')
    board = (root / 'BoardConfig.mk').read_text()
    if re.findall(r'^AERA_USE_BUSYBOX_BINARY\s*:=\s*(\S+)\s*$', board, re.M) != ['1']:
        raise ValueError('BusyBox must be explicitly enabled in BoardConfig')
    if not re.search(r'^TARGET_FS_CONFIG_GEN[ \t]*\+=[ \t]*\$\(DEVICE_PATH\)/config/busybox-fs-config\.fs[ \t]*$', board, re.M):
        raise ValueError('BusyBox native filesystem permission input is missing')
    permissions = configparser.ConfigParser()
    permissions.read(root / 'config/busybox-fs-config.fs')
    if permissions.sections() != ['sbin/busybox'] or dict(permissions['sbin/busybox']) != {
            'mode': '0755', 'user': 'AID_ROOT', 'group': 'AID_ROOT', 'caps': '0'}:
        raise ValueError('BusyBox must remain root-owned executable without special capabilities')
    if not re.search(r'^TARGET_RECOVERY_DEVICE_MODULES[ \t]*\+=[ \t]*fs_config_files_system[ \t]*$', (root / 'device.mk').read_text(), re.M):
        raise ValueError('Recovery must generate filesystem permissions before mkbootfs')
    setup = (root / 'vendorsetup.sh').read_text()
    if re.findall(r'^\s*export AERA_USE_BUSYBOX_BINARY=(\S+)\s*$', setup, re.M) != ['1']:
        raise ValueError('Upstream AERA BusyBox export is missing')
    if 'include $(LOCAL_PATH)/busybox.mk' not in (root / 'Android.mk').read_text():
        raise ValueError('Native BusyBox packaging guard is not included')
    integration = (root / 'busybox.mk').read_text()
    for required in ('AERA_VENDOR += AERA_USE_BUSYBOX_BINARY="$(AERA_USE_BUSYBOX_BINARY)"',
                     'BOARD_RECOVERY_IMAGE_PREPARE := /usr/bin/python3 $(LOCAL_PATH)/tools/verify_busybox.py',
                     '--source vendor/recovery/prebuilt/$(TARGET_ARCH)/busybox',
                     '--ramdisk $(TARGET_RECOVERY_ROOT_OUT)',
                     '--fs-config $(TARGET_OUT_ETC)/fs_config_files'):
        if required not in integration:
            raise ValueError('BusyBox must use the upstream hook and native pre-pack verification')
    return SOURCE


def verify_runtime(entries):
    name = SOURCE['destination']
    mode, blob = entries.get(name, (0, b''))
    if not stat.S_ISREG(mode) or stat.S_IMODE(mode) != 0o755:
        raise ValueError('BusyBox must be a regular executable /sbin/busybox with mode 0755')
    return verify_blob(blob)


def verify_fs_config(blob):
    """Verify the actual generated table that native mkbootfs reads via -d."""
    offset, matching = 0, []
    while offset < len(blob):
        if offset + 16 > len(blob):
            raise ValueError('Generated filesystem permission table is truncated')
        length, mode, uid, gid, caps = struct.unpack_from('<HHHHQ', blob, offset)
        if length < 24 or length % 8 or offset + length > len(blob):
            raise ValueError('Generated filesystem permission record is invalid')
        name = blob[offset + 16:offset + length]
        if b'\0' not in name:
            raise ValueError('Generated filesystem permission path is unterminated')
        pattern = name.split(b'\0', 1)[0].decode('utf-8')
        if fnmatch.fnmatchcase('sbin/busybox', pattern):
            matching.append((pattern, mode, uid, gid, caps))
        offset += length
    if not matching or matching[0] != ('sbin/busybox', 0o755, 0, 0, 0) or sum(
            item[0] == 'sbin/busybox' for item in matching) != 1:
        raise ValueError('Native mkbootfs would not preserve executable BusyBox permissions')
    return {'path': 'sbin/busybox', 'mode': '0755', 'uid': 0, 'gid': 0, 'capabilities': 0}


def verify_staging(source, ramdisk, fs_config=None):
    source, target = Path(source), Path(ramdisk) / SOURCE['destination']
    if source.is_symlink() or not source.is_file():
        raise ValueError('Pinned upstream BusyBox source must be a regular file')
    verify_blob(source.read_bytes())
    if target.is_symlink() or not target.is_file():
        raise ValueError('Upstream hook did not package a regular /sbin/busybox')
    result = verify_runtime({SOURCE['destination']: (target.stat().st_mode, target.read_bytes())})
    if fs_config is not None:
        result['native_permissions'] = verify_fs_config(Path(fs_config).read_bytes())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--ramdisk', required=True, type=Path)
    parser.add_argument('--fs-config', required=True, type=Path)
    args = parser.parse_args()
    verify_tree(ROOT)
    print('Verified upstream BusyBox: ' + json.dumps(verify_staging(args.source, args.ramdisk, args.fs_config)))
