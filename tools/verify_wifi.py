"""Verify the exact WLAN module and native recovery WLAN userspace."""
import hashlib
import io
import json
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from elftools.elf.elffile import ELFFile

WLAN_EXECUTABLES = ('system/bin/wpa_supplicant', 'system/bin/wpa_cli',
                    'system/bin/dhcptool', 'system/bin/aera-netfs', 'system/bin/fusermount3')
WLAN_VENDOR_EXECUTABLES = ('system/bin/rmt_storage', 'system/bin/tftp_server')


def verify_startup_configuration(entries):
    init = entries['init.recovery.wifi.rc'][1].decode()
    trigger = init.split('on property:sys.aera.wlan.up=1', 1)[1].split('\non ', 1)[0]
    if any('start ' + name in trigger for name in
           ('hotdog-qrtr-ns', 'hotdog-pd-mapper', 'hotdog-wlan-firmware')):
        raise ValueError('WLAN dependencies must start after the firmware bind')
    supplicant = init.split('service wpa_supplicant ', 1)[1].split('\nservice ', 1)[0]
    if '\n    oneshot\n' not in supplicant:
        raise ValueError('Failed WLAN startup must stop instead of automatically restarting')
    prepare = entries['system/bin/hotdog-wlan-prepare.sh'][1].decode()
    for guard in ('module_vermagic=$(modinfo -F vermagic "$module")',
                  'module_release=${module_vermagic%% *}',
                  '[ "$(uname -r)" = "$module_release" ]'):
        if guard not in prepare or prepare.index(guard) > prepare.index('start_service()'):
            raise ValueError('WLAN must validate the actual bundled module before services')
    if 'expected_kernel=' in prepare or 'insmod "$module"' not in prepare:
        raise ValueError('WLAN must use normal module loading without a fixed kernel release')
    for line in prepare.splitlines():
        if line.strip().startswith('insmod ') and line.strip() != 'insmod "$module"':
            raise ValueError('WLAN must not force-load its module')
    domains = entries['system/bin/hotdog-wlan-domains.sh'][1].decode()
    if '/vendor/firmware_mnt/image/modemuw.jsn' not in domains:
        raise ValueError('WLAN firmware-domain readiness check is missing')
    for guard in ("! grep -q ' /vendor ' /proc/mounts || exit 1",
                  '[ -L /vendor/firmware_mnt ] || exit 1',
                  '[ "$(readlink /vendor/firmware_mnt)" = /firmware ] || exit 1'):
        if guard not in domains or domains.index(guard) > domains.index('start_service hotdog-pd-mapper'):
            raise ValueError('PD mapper must use the ramdisk firmware symlink after vendor cleanup')
    if '\nmount ' in domains or 'mount -o bind /firmware /vendor' in domains:
        raise ValueError('WLAN domains must not pin installed vendor with a firmware bind')
    if '/vendor/firmware_mnt/image/modemuw.jsn' not in prepare:
        raise ValueError('WLAN preparation must recheck the firmware bind after startup')
    boot = init.split('on boot', 1)[1].split('\non ', 1)[0]
    if 'start hotdog-wlan-domains' not in boot:
        raise ValueError('WLAN domains must register before the kernel startup timeout')
    if 'insmod ' in domains or 'hotdog-wlan-firmware' in domains:
        raise ValueError('Early domain registration must not power up the WLAN firmware')
    if prepare.index('sys.hotdog.wlan.domains)" = ready') > prepare.index('start_service hotdog-wlan-firmware'):
        raise ValueError('Radio startup must wait for populated firmware domains')
    stop = init.split('on property:init.svc.wpa_supplicant=stopped', 1)[1].split('\non ', 1)[0].split('\nservice ', 1)[0]
    if any('stop ' + name not in stop for name in ('hotdog-wlan-prepare', 'hotdog-cnss-daemon', 'hotdog-wlan-firmware')):
        raise ValueError('Failed supplicant startup must release its radio helpers')
    dependencies = ('hotdog-qrtr-ns', 'hotdog-pd-mapper', 'hotdog-rmt-storage', 'hotdog-tftp-server')
    if any('stop ' + name in stop for name in dependencies):
        raise ValueError('Wi-Fi toggles must retain the registered modem backends')
    for service, executable in (('hotdog-rmt-storage', 'rmt_storage'), ('hotdog-tftp-server', 'tftp_server')):
        declaration = init.split('service ' + service + ' ', 1)[1].split('\nservice ', 1)[0]
        if not declaration.startswith('/system/bin/' + executable + '\n') or any(line not in declaration for line in
                ('\n    shutdown critical\n', '\n    oneshot\n', '\n    setenv LD_LIBRARY_PATH /system/lib64:/vendor/lib64\n')):
            raise ValueError('Stock WLAN backend lifetime/provider configuration is missing')
        if prepare.index('start_service ' + service) > prepare.index('start_service hotdog-wlan-firmware'):
            raise ValueError('Modem storage and TFTP must start before firmware power')
    storage = entries['system/bin/hotdog-wlan-storage.sh'][1].decode()
    if 'base=/tmp/hotdog-wlan-rfs' not in storage or "grep -Eq ' (ro|rw),'" not in storage or 'current_root' not in storage:
        raise ValueError('Stock TFTP writes require guarded RAM mirrors and mounted persist')
    if prepare.index('/system/bin/sh /system/bin/hotdog-wlan-storage.sh') > prepare.index('start_service hotdog-tftp-server'):
        raise ValueError('TFTP RAM storage must be prepared before its service starts')
    config = entries['system/etc/hotdog-wpa_supplicant.conf'][1].decode()
    if 'pmf=1\n' not in config or 'sae_pwe=2\n' not in config:
        raise ValueError('Native WLAN configuration must enable PMF negotiation and SAE H2E')
    wrapper = entries['system/bin/hotdog-wpa-supplicant.sh'][1].decode()
    if 'getprop sys.hotdog.wlan.prepare' not in wrapper or '!= failed' not in wrapper:
        raise ValueError('Supplicant must observe device preparation failure')
    for permission in ('chown wifi:wifi "$config" || exit 1', 'chmod 0600 "$config" || exit 1'):
        if permission not in wrapper or wrapper.index(permission) > wrapper.index('exec /system/bin/wpa_supplicant'):
            raise ValueError('Native supplicant must own its private RAM configuration')
    return {'firmware_before_mapper': True, 'early_domains_without_radio_power': True, 'failed_startup_retries': False,
            'supplicant_private_config_owner': 'wifi'}


def verify_module_metadata_tool(entries):
    name = 'system/bin/modinfo'
    if name not in entries:
        raise ValueError('Bundled module metadata reader is missing')
    mode, data = entries[name]
    if stat.S_ISLNK(mode):
        if data not in (b'toybox', b'/system/bin/toybox'):
            raise ValueError('Unexpected module metadata reader link')
        name = 'system/bin/toybox'
        if name not in entries:
            raise ValueError('Module metadata reader target is missing')
        mode, data = entries[name]
    if not stat.S_ISREG(mode) or not mode & 0o111:
        raise ValueError('Module metadata reader must be executable')
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
        raise ValueError('Module metadata reader must be ARM64')
    if name.endswith('/toybox') and b'modinfo\0' not in data:
        raise ValueError('Toybox module metadata applet is missing')


def verify_module(data, record):
    if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError('WLAN module identity differs from the pinned WLAN artifact')
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
        raise ValueError('WLAN module must be ARM64')
    section = elf.get_section_by_name('.modinfo')
    info = dict(item.decode().split('=', 1) for item in section.data().split(b'\0') if b'=' in item)
    if info.get('name') != 'wlan' or info.get('vermagic', '').strip() != record['vermagic']:
        raise ValueError('WLAN module kernel ABI differs from its manifest')
    return info


def verify_module_tree(root):
    root = Path(root)
    metadata = json.loads((root / 'modules/manifest.json').read_text())
    files = metadata['files']
    actual = {p.name for p in (root / 'modules').iterdir() if p.is_file()}
    if actual != set(files) | {'manifest.json'}:
        raise ValueError('Unmanifested WLAN module inputs')
    for name, record in files.items():
        verify_module((root / 'modules' / name).read_bytes(), record)
    return metadata


def verify_runtime(entries, module_metadata):
    from verify_rmt_storage import verify_runtime as verify_rmt_storage_runtime
    remote_storage = verify_rmt_storage_runtime(entries)
    verify_module_metadata_tool(entries)
    module = 'system/lib/modules/msmnile/qca_cld3_wlan.ko'
    if module not in entries or not stat.S_ISREG(entries[module][0]):
        raise ValueError('Matched WLAN module is absent')
    verify_module(entries[module][1], module_metadata['files']['qca_cld3_wlan.ko'])
    for name in WLAN_EXECUTABLES + WLAN_VENDOR_EXECUTABLES:
        if name not in entries or not stat.S_ISREG(entries[name][0]) or not entries[name][0] & 0o111:
            raise ValueError(f'Native WLAN executable missing: {name}')
        elf = ELFFile(io.BytesIO(entries[name][1]))
        if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
            raise ValueError(f'Native WLAN executable must be ARM64: {name}')
    configs = ('init.recovery.wifi.rc', 'system/bin/hotdog-wlan-firmware.sh',
               'system/bin/hotdog-wlan-domains.sh',
               'system/bin/hotdog-wlan-storage.sh',
               'system/bin/hotdog-wlan-prepare.sh', 'system/bin/hotdog-wpa-supplicant.sh',
               'system/etc/hotdog-wpa_supplicant.conf',
               'system/etc/vintf/manifest/hotdog-wifi.xml')
    for name in configs:
        if name not in entries or not stat.S_ISREG(entries[name][0]):
            raise ValueError(f'WLAN startup configuration missing: {name}')
    manifest = ET.fromstring(entries[configs[-1]][1])
    if manifest.tag != 'manifest' or manifest.get('type') != 'framework' or not any(
            hal.findtext('name') == 'android.hardware.wifi.supplicant' and (
                'ISupplicant/default' in (hal.findtext('fqname') or '') or
                (hal.findtext('interface/name') == 'ISupplicant' and
                 hal.findtext('interface/instance') == 'default'))
            for hal in manifest.findall('hal')):
        raise ValueError('Native supplicant declaration is not visible to recovery')
    startup = verify_startup_configuration(entries)
    return {'module_sha256': module_metadata['files']['qca_cld3_wlan.ko']['sha256'],
            'kernel_release': module_metadata['kernel_release'], 'userspace': list(WLAN_EXECUTABLES),
            'startup': startup, 'remote_storage': remote_storage, 'device_wifi_tested': False}
