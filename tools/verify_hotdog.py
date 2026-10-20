"""Check Hotdog's recovery partition and native dynamic-partition/fastbootd setup."""
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import shlex
import xml.etree.ElementTree as ET
from elftools.elf.elffile import ELFFile


HEALTH_INIT = 'system/etc/init/android.hardware.health@2.1-service.rc'
HEALTH_BINARY = 'system/bin/android.hardware.health@2.1-service'
HEALTH_PROVIDER = 'system/lib64/hw/android.hardware.health@2.0-impl-2.1.so'
HEALTH_MANIFEST = 'vendor/etc/vintf/manifest/android.hardware.health@2.1.xml'
FASTBOOT_HAL_MANIFEST = 'vendor/etc/vintf/manifest.xml'
FASTBOOT_HAL_PROVIDER = 'system/lib64/hw/android.hardware.fastboot@1.1-impl-mock.so'


def verify_fastboot_hal_manifest(text):
    """Match HIDL getService discovery to the bundled in-process provider."""
    manifest = ET.fromstring(text)
    hals = [hal for hal in manifest.findall('hal')
            if hal.findtext('name') == 'android.hardware.fastboot']
    if manifest.tag != 'manifest' or manifest.get('type') != 'device' or len(hals) != 1:
        raise ValueError('Fastboot HAL requires one device VINTF declaration')
    hal = hals[0]
    transports = hal.findall('transport')
    if (hal.get('format') != 'hidl' or len(transports) != 1 or
            transports[0].text != 'passthrough' or transports[0].get('arch') != '64' or
            [node.text for node in hal.findall('fqname')] != ['@1.1::IFastboot/default']):
        raise ValueError('Fastboot HAL must declare the ARM64 HIDL 1.1 default passthrough provider')
    return {'manifest': FASTBOOT_HAL_MANIFEST, 'interface': '@1.1::IFastboot/default',
            'transport': 'passthrough', 'arch': '64'}


def verify_fastboot_hal_runtime(entries):
    for name in (FASTBOOT_HAL_MANIFEST, FASTBOOT_HAL_PROVIDER):
        if name not in entries or not stat.S_ISREG(entries[name][0]):
            raise ValueError(f'Missing regular Fastboot HAL input: {name}')
    result = verify_fastboot_hal_manifest(entries[FASTBOOT_HAL_MANIFEST][1])
    elf = ELFFile(io.BytesIO(entries[FASTBOOT_HAL_PROVIDER][1]))
    if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64' or elf.header['e_type'] != 'ET_DYN':
        raise ValueError('Fastboot HAL provider must be an ARM64 shared library')
    symbols = elf.get_section_by_name('.dynsym')
    if symbols is None or not any(
            symbol.name == 'HIDL_FETCH_IFastboot' and symbol['st_shndx'] != 'SHN_UNDEF' and
            symbol['st_info']['bind'] in ('STB_GLOBAL', 'STB_WEAK') and
            symbol['st_other']['visibility'] in ('STV_DEFAULT', 'STV_PROTECTED')
            for symbol in symbols.iter_symbols()):
        raise ValueError('Fastboot HAL provider must export HIDL_FETCH_IFastboot')
    return dict(result, provider=FASTBOOT_HAL_PROVIDER)


def verify_health_startup(text):
    """Require an explicit import and boot start, not just installed HAL files."""
    imports = []
    boot_commands = []
    action = None
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        words = shlex.split(line)
        if not raw[0].isspace():
            action = words[1:] if words[0] == 'on' else None
            if words[0] == 'import':
                imports.append(words[1:])
        elif action == ['boot']:
            boot_commands.append(words)
    if ['/' + HEALTH_INIT] not in imports:
        raise ValueError('Health HAL service init import is missing')
    if ['start', 'health-hal-2-1'] not in boot_commands:
        raise ValueError('Health HAL must start on boot before fastbootd is requested')
    return {'service': 'health-hal-2-1', 'startup_event': 'boot'}


def verify_health_runtime(entries):
    qcom = 'init.recovery.qcom.rc'
    for name in (qcom, HEALTH_INIT, HEALTH_BINARY, HEALTH_PROVIDER, HEALTH_MANIFEST):
        if name not in entries or not stat.S_ISREG(entries[name][0]):
            raise ValueError(f'Missing regular Health HAL input: {name}')
    result = verify_health_startup(entries[qcom][1].decode())
    native_init = entries.get('system/etc/init/hw/init.rc', (0, b''))[1]
    if b'import /init.recovery.${ro.hardware}.rc' not in native_init.splitlines():
        raise ValueError('Native init must import the Hotdog Qualcomm startup script')
    service = entries[HEALTH_INIT][1].decode()
    declarations = [shlex.split(line) for line in service.splitlines()
                    if line and not line[0].isspace() and not line.startswith('#')]
    if ['service', 'health-hal-2-1', '/' + HEALTH_BINARY] not in declarations:
        raise ValueError('Health HAL service name or executable does not match startup')
    for name in (HEALTH_BINARY, HEALTH_PROVIDER):
        mode, data = entries[name]
        if name == HEALTH_BINARY and not mode & 0o111:
            raise ValueError('Health HAL service must be executable')
        elf = ELFFile(io.BytesIO(data))
        if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
            raise ValueError(f'Health HAL input must be ARM64: {name}')
    manifest = ET.fromstring(entries[HEALTH_MANIFEST][1])
    if manifest.get('type') != 'device' or not any(
            hal.findtext('name') == 'android.hardware.health' and
            hal.findtext('transport') == 'hwbinder' and
            '@2.1::IHealth/default' in [node.text for node in hal.findall('fqname')]
            for hal in manifest.findall('hal')):
        raise ValueError('Health HAL 2.1 default hwbinder declaration is missing')
    return dict(result, executable=HEALTH_BINARY, provider=HEALTH_PROVIDER,
                manifest=HEALTH_MANIFEST)


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
    verify_health_startup((root/'recovery/root/init.recovery.qcom.rc').read_text())
    verify_fastboot_hal_manifest((root/'manifest.xml').read_bytes())
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
    copy_rules = [line.split('#', 1)[0].strip().rstrip('\\').strip()
                  for line in product.splitlines()]
    if ('$(LOCAL_PATH)/manifest.xml:$(TARGET_COPY_OUT_RECOVERY)/root/' + FASTBOOT_HAL_MANIFEST
            not in copy_rules):
        raise ValueError('Fastboot HAL device manifest must be copied into the recovery ramdisk')
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
    health = verify_health_runtime(entries)
    fastboot_hal = verify_fastboot_hal_runtime(entries)
    return {'executable':name,'layout':layout,'health_hal':health,'fastboot_hal':fastboot_hal,
            'device_fastbootd_tested':False}
