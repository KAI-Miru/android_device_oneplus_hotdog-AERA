"""Check Hotdog's recovery partition and native dynamic-partition/fastbootd setup."""
import hashlib
import io
import json
from pathlib import Path
import re
import stat
from elftools.elf.elffile import ELFFile


def verify_fstab(text):
    rows = [line.split() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
    logical = ('/system','/system_ext','/product','/vendor','/odm','/my_product','/my_engineering')
    for mount in logical:
        matches = [row for row in rows if row[1] == mount]
        if not matches or any(not {'logical','slotselect'} <= set(row[4].split(','))
                              or 'ro' not in row[3].split(',')
                              or row[0].startswith('/dev/block/bootdevice/by-name/') for row in matches):
            raise ValueError(f'Expected read-only, slotted logical partition: {mount}')
    for mount in ('/boot','/recovery'):
        matches = [row for row in rows if row[1] == mount]
        if len(matches) != 1 or matches[0][2] != 'emmc' or 'slotselect' not in matches[0][4].split(','):
            raise ValueError(f'Missing physical slotted partition: {mount}')
    data = [row for row in rows if row[1] == '/data']
    if len(data) != 1 or data[0][0] != '/dev/block/bootdevice/by-name/userdata':
        raise ValueError('Data must use its physical userdata device')
    return {'logical_partitions':list(logical),'recovery_partition':'recovery','slotted':True}


def verify_device_configuration(root):
    root = Path(root)
    board = (root/'BoardConfig.mk').read_text()
    product = (root/'device.mk').read_text()
    profile = json.loads((root/'config/device.json').read_text())
    if re.search(r'^BOARD_USES_RECOVERY_AS_BOOT[ \t]*:=[ \t]*\S',board,re.M):
        raise ValueError('Hotdog must build a dedicated recovery image')
    for pattern in (r'TARGET_NO_RECOVERY\s*:=\s*false',
                    r'BOARD_RECOVERYIMAGE_PARTITION_SIZE\s*:=\s*100663296',
                    r'AERA_INCLUDE_FASTBOOTD\s*:=\s*true'):
        if not re.search(pattern,board):
            raise ValueError(f'Missing Hotdog setting: {pattern}')
    if 'BOARD_SUPER_PARTITION_SIZE' in board or 'PARTITIONS_SIZE :=' in board:
        raise ValueError('Do not synthesize super using unverified legacy geometry')
    if not re.search(r'PRODUCT_USE_DYNAMIC_PARTITIONS\s*:=\s*true',product) or not re.search(
            r'PRODUCT_BUILD_SUPER_PARTITION\s*:=\s*false',product):
        raise ValueError('Enable native logical-partition support without building super')
    if 'android.hardware.fastboot@1.1-impl-mock' not in product:
        raise ValueError('Native fastboot HAL is absent')
    for name, key in (('proprietary','proprietary_manifest_sha256'),('modules','wlan_manifest_sha256')):
        if hashlib.sha256((root/name/'manifest.json').read_bytes()).hexdigest() != profile[key]:
            raise ValueError(f'Shared guacamole {name} provenance changed')
    copies = (root/'proprietary-files.mk').read_text()
    manifest = json.loads((root/'proprietary/manifest.json').read_text())
    for name in manifest['files']:
        mapping = f'$(LOCAL_PATH)/proprietary/{name}:$(TARGET_COPY_OUT_RECOVERY)/root/{name}'
        if mapping not in copies:
            raise ValueError(f'Shared provider copy rule is absent or renamed: {name}')
    for name in re.findall(r'\$\(LOCAL_PATH\)/([^:\s]+):',
                           product+'\n'+copies):
        if not (root/name).is_file():
            raise ValueError(f'Product copy input is absent: {name}')
    props = (root/'system.prop').read_text().splitlines()
    for setting in ('ro.boot.dynamic_partitions=true','ro.recovery.usb.vid=18D1',
                    'ro.recovery.usb.adb.pid=4EE7','ro.recovery.usb.fastboot.pid=4EE0'):
        if setting not in props:
            raise ValueError(f'Missing native dynamic/USB setting: {setting}')
    return verify_fstab((root/'recovery/root/system/etc/recovery.fstab').read_text())


def verify_fastboot_runtime(entries):
    name = 'system/bin/fastbootd'
    mode, data = entries.get(name,(0,b''))
    if not stat.S_ISREG(mode) or not mode & 0o111:
        raise ValueError('Hotdog requires the native fastbootd executable')
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
        raise ValueError('Fastbootd must be ARM64')
    init = entries.get('system/etc/init/hw/init.rc',(0,b''))[1]
    for marker in (b'service fastbootd /system/bin/fastbootd',b'mount functionfs fastboot',
                   b'functions/ffs.fastboot',b'start fastbootd'):
        if marker not in init:
            raise ValueError('Native fastbootd init/FunctionFS support is absent')
    properties = b'\n'.join(blob for path,(_,blob) in entries.items()
                            if path.endswith(('.prop','prop.default')))
    if b'ro.boot.dynamic_partitions=true' not in properties.splitlines():
        raise ValueError('Dynamic-partition capability is absent from image properties')
    fstab = entries.get('system/etc/recovery.fstab',(0,b''))[1].decode()
    layout = verify_fstab(fstab)
    return {'executable':name,'layout':layout,'device_fastbootd_tested':False}
