#!/usr/bin/env python3
"""Verify the actual boot image and its native AERA ramdisk before upload."""
import argparse, gzip, hashlib, io, json, lzma, stat, xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from boot_v2 import parse_boot, bootloader_layout
from elftools.elf.elffile import ELFFile
from verify_wifi import WLAN_EXECUTABLES, verify_runtime as verify_wifi_runtime
from verify_usb import verify_usb_configuration

def unpack_newc(data):
    entries = {}; offset = 0
    while True:
        h = data[offset:offset+110]
        if len(h) != 110 or h[:6] not in (b'070701', b'070702'):
            raise ValueError('Malformed CPIO header')
        fields = [int(h[6+i*8:14+i*8],16) for i in range(13)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        name_start = offset+110; name_end = name_start+namesize
        if namesize < 1 or name_end > len(data) or data[name_end-1] != 0:
            raise ValueError('Invalid CPIO name bounds')
        name = data[name_start:name_end-1].decode('utf-8')
        begin = (name_end+3)//4*4; end = begin+size
        if end > len(data): raise ValueError('Truncated CPIO entry')
        if name == 'TRAILER!!!': break
        if name.startswith('./'): name = name[2:]
        if name not in ('', '.'):
            if name.startswith('/') or '..' in PurePosixPath(name).parts or name in entries:
                raise ValueError(f'Unsafe or duplicate CPIO path: {name}')
            entries[name] = (mode, data[begin:end])
        offset = (end+3)//4*4
    return entries

def verify_native_init(entries):
    # Pinned AERA's init_recovery.rc module installs under system/etc/init/hw.
    # Its Makefile removes root init.rc and creates this native init symlink.
    script = 'system/etc/init/hw/init.rc'
    for name in ('init', 'system/bin/init', script, 'init.recovery.service.rc'):
        if name not in entries:
            raise ValueError(f'Missing native AERA init file: {name}')
    mode, target = entries['init']
    if not stat.S_ISLNK(mode) or target != b'/system/bin/init':
        raise ValueError('Root init must point to the native /system/bin/init')
    mode, binary = entries['system/bin/init']
    if not stat.S_ISREG(mode) or not mode & 0o111:
        raise ValueError('Native init must be a regular executable')
    elf = ELFFile(io.BytesIO(binary))
    if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
        raise ValueError('Native init must be an ARM64 ELF')
    for name in (script, 'init.recovery.service.rc'):
        if not stat.S_ISREG(entries[name][0]):
            raise ValueError(f'Native init script must be a regular file: {name}')
    if b'import /init.recovery.service.rc' not in entries[script][1]:
        raise ValueError('Native AERA service init import is missing')
    if b'service recovery /system/bin/recovery' not in entries['init.recovery.service.rc'][1]:
        raise ValueError('Native AERA recovery service is missing')
    return script

def verify_native_service_configuration(entries):
    profiles = 'system/etc/task_profiles.json'
    framework = 'system/etc/vintf/manifest.xml'
    manager = 'system/etc/vintf/manifest/hwservicemanager.xml'
    boot = 'system/etc/vintf/manifest/hotdog-boot.xml'
    for name in (profiles, framework, manager, boot):
        if name not in entries or not stat.S_ISREG(entries[name][0]):
            raise ValueError(f'Missing native service configuration: {name}')
    definitions = json.loads(entries[profiles][1])
    names = {p['Name'] for section in ('Profiles', 'AggregateProfiles') for p in definitions.get(section, [])}
    if not {'SCHED_SP_FOREGROUND', 'SCHED_SP_BACKGROUND'} <= names:
        raise ValueError('Native scheduling profiles are incomplete')
    for name in (framework, manager, boot):
        root = ET.fromstring(entries[name][1])
        if root.tag != 'manifest' or root.get('type') != 'framework':
            raise ValueError(f'Invalid native framework manifest: {name}')
    declarations = ET.fromstring(entries[manager][1])
    if not any(h.findtext('name') == 'android.hidl.manager' and
               h.findtext('transport') == 'hwbinder' and
               h.findtext('version') == '1.2' and
               h.findtext('interface/name') == 'IServiceManager' and
               h.findtext('interface/instance') == 'default' for h in declarations.findall('hal')):
        raise ValueError('Native hardware service manager declaration is missing')
    declaration = ET.fromstring(entries[boot][1])
    if not any(h.findtext('name') == 'android.hardware.boot' and
               h.findtext('transport') == 'hwbinder' and
               h.findtext('fqname') == '@1.1::IBootControl/default' for h in declaration.findall('hal')):
        raise ValueError('SDK30 boot-control service declaration is missing')
    service = 'system/bin/android.hardware.boot@1.1-service'
    if service not in entries or not stat.S_ISREG(entries[service][0]) or not entries[service][0] & 0o111:
        raise ValueError('Native boot-control 1.1 executable is missing')
    elf = ELFFile(io.BytesIO(entries[service][1]))
    if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
        raise ValueError('Native boot-control service must be ARM64')
    # The service dlopens this provider, so DT_NEEDED closure alone cannot
    # detect an image which starts the service but has no implementation.
    for path in ('system/lib64/hw/android.hardware.boot@1.0-impl-1.1-qti.so',
                 'system/lib64/libboot_control_qti.so',
                 'system/lib64/librecovery_updater.so'):
        if path not in entries or not stat.S_ISREG(entries[path][0]):
            raise ValueError(f'Missing boot-control runtime provider: {path}')
        provider = ELFFile(io.BytesIO(entries[path][1]))
        if provider.elfclass != 64 or provider.header['e_machine'] != 'EM_AARCH64':
            raise ValueError(f'Boot-control runtime provider must be ARM64: {path}')
    return [profiles, framework, manager, boot]


def verify_screen_lock_configuration(recovery):
    markers = (b'display suspended after inactivity', b'Use Android screen lock',
               b'/system/locksettings.db', b'user-gk-authentication', b'weaver-key',
               b'Checking Android credential...', b'twrp.user.0.decrypt')
    for marker in markers:
        if marker not in recovery:
            raise ValueError(f'Missing Android screen-lock/timeout marker: {marker!r}')
    if b'AERA-SCREEN-LOCK-1' in recovery:
        raise ValueError('Obsolete separate AERA password verifier')
    return {'native_timeout_and_android_bouncer_present': True,
            'device_blank_wake_and_credential_tested': False}


def verify_filesystem_format_configuration(recovery, entries):
    required = (b'Change filesystem', b'Format partition now',
                b'Type yes to enable formatting', b'/proc/filesystems',
                b'dmctl delete userdata',
                b'userdata mapping removal failed or was not confirmed; refusing to format.')
    if any(value not in recovery for value in required):
        raise ValueError('Native filesystem selection, format confirmation or mapping cleanup is missing')
    if b'dmsetup remove -f userdata' in recovery:
        raise ValueError('Device userdata cleanup must use non-forced dmctl removal')
    tool = entries.get('system/bin/dmctl')
    if not tool or not stat.S_ISREG(tool[0]) or not tool[0] & 0o111:
        raise ValueError('Executable native dmctl mapping-cleanup tool is missing')
    elf = ELFFile(io.BytesIO(tool[1]))
    if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
        raise ValueError('Mapping-cleanup dmctl must be ARM64')
    return {'native_filesystem_selection_present': True,
            'checked_userdata_mapping_cleanup_present': True,
            'mapping_cleanup_command': 'dmctl delete userdata',
            'native_mapping_tool_present': True,
            'device_format_tested': False}


def verify_gpu_startup_configuration(recovery, properties, entries):
    compiler = 'system/lib64/libllvm-glnext.so'
    required = ('ro.aera.gpu.required_libraries=/' + compiler).encode()
    if required not in properties.splitlines():
        raise ValueError('GPU renderer lacks the ramdisk compiler configuration')
    if (b'ro.aera.gpu.required_libraries\0' not in recovery or
            b'GPU runtime: required library unavailable' not in recovery):
        raise ValueError('GPU renderer lacks the device-declared compiler preflight')
    if b'Native UI: vendor runtime mount unavailable' in recovery:
        raise ValueError('GPU startup still pins the installed vendor partition')
    profile = json.loads((Path(__file__).parent / 'gpu-source.json').read_text())
    runtime = sorted(set(profile['seeds'].values()) | set(profile['required_libraries']))
    for name in runtime:
        if name not in entries or not stat.S_ISREG(entries[name][0]):
            raise ValueError(f'Missing ramdisk GPU runtime: {name}')
    if any(name in entries[compiler][1] for name in (b'libllvm-qgl.so', b'libllvm-qcom.so')):
        raise ValueError('Ramdisk shader compiler still requires external compiler providers')
    declaration = entries.get('vendor/etc/init/aera-gralloc.rc', (0, b''))[1]
    if (b'service aera-gralloc /system/bin/aera-vendor-allocator\n' not in declaration or
            b'    setenv LD_LIBRARY_PATH /system/lib64:/vendor/lib64:/vendor/lib64/egl\n' not in declaration):
        raise ValueError('Graphics allocator must prefer the bundled platform and GPU providers')
    return {'ramdisk_compiler': '/' + compiler, 'runtime_files': runtime,
            'installed_vendor_required': False,
            'vendor_mount_before_ui': False, 'cold_boot_tested': False}


def image_properties(entries):
    return b'\n'.join(data for name, (_, data) in entries.items()
                      if name.endswith(('.prop', 'prop.default')))


def verify_arm64_runtime(entries):
    count = 0
    for name, (mode, data) in entries.items():
        # GPU firmware containers may themselves be ELF32; they are loaded by
        # the kernel and are not Android processes or shared libraries.
        if name.startswith('vendor/firmware/') or not stat.S_ISREG(mode) or data[:4] != b'\x7fELF':
            continue
        elf = ELFFile(io.BytesIO(data))
        if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
            raise ValueError(f'Non-ARM64 executable or library in recovery: {name}')
        count += 1
    return {'primary': 'arm64', 'secondary': None, 'elf_count': count}


def verify_gpu_runtime(entries):
    library = 'system/lib64/libnativewindow.so'
    recovery = entries['system/bin/recovery'][1]
    if ('/' + library).encode() + b'\0' not in recovery:
        raise ValueError('GPU renderer does not load the native AERA buffer runtime')
    verify_gpu_startup_configuration(recovery, image_properties(entries), entries)
    if library not in entries or not stat.S_ISREG(entries[library][0]):
        raise ValueError('Missing native GPU buffer runtime')
    elf = ELFFile(io.BytesIO(entries[library][1]))
    if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
        raise ValueError('GPU buffer runtime must be ARM64')
    symbols = elf.get_section_by_name('.dynsym')
    exports = {s.name for s in symbols.iter_symbols() if s.entry.st_shndx != 'SHN_UNDEF'} if symbols else set()
    required = {'AHardwareBuffer_allocate', 'AHardwareBuffer_release',
                'AHardwareBuffer_describe', 'AHardwareBuffer_getNativeHandle',
                '_ZN7android38AHardwareBuffer_to_ANativeWindowBufferEPK15AHardwareBuffer'}
    if not required <= exports:
        raise ValueError(f'Incomplete GPU buffer API: {sorted(required - exports)}')
    for script in ('system/bin/runatboot.sh', 'system/bin/postscreenunblank.sh'):
        if script not in entries or not stat.S_ISREG(entries[script][0]):
            raise ValueError(f'Missing native touch hook: {script}')
    return '/' + library


def verify_gatekeeper_spu_configuration(entries):
    """Require the working hotdog Gatekeeper choice before crypto startup."""
    parent = 'init.recovery.qcom.rc'
    if parent not in entries or not stat.S_ISREG(entries[parent][0]):
        raise ValueError('Missing hotdog Gatekeeper startup configuration')
    trigger = None
    assignments = []
    verifier_actions = []
    verifier_trigger = 'on property:crypto.ready=0 && property:twrp.user.0.decrypt=1'
    for raw in entries[parent][1].decode().splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if not raw[:1].isspace():
            trigger = line
        elif line.startswith('setprop vendor.gatekeeper.disable_spu '):
            assignments.append((trigger, line.split()))
        elif trigger == verifier_trigger:
            verifier_actions.append(line)
    if assignments != [('on init', ['setprop', 'vendor.gatekeeper.disable_spu', 'true'])]:
        raise ValueError('Official hotdog Gatekeeper must disable SPU on init before crypto startup')
    if verifier_actions != ['start qseecomd', 'start gatekeeper-1-0-qti']:
        raise ValueError('Screen verifier must restart after crypto cleanup only for a decrypted owner')
    return {'disable_spu': True, 'trigger': 'on init', 'post_decrypt_verifier': True,
            'credential_unlock_tested': False}


def verify_crypto_service_configuration(entries):
    name = 'init.recovery.hotdog-crypto.rc'
    parent = 'init.recovery.qcom.rc'
    for path in (name, parent):
        if path not in entries or not stat.S_ISREG(entries[path][0]):
            raise ValueError(f'Missing official crypto service configuration: {path}')
    imports = entries[parent][1].decode().splitlines()
    if ('import /init.recovery.qcom_decrypt.rc' not in imports or
            'import /' + name not in imports or
            imports.index('import /init.recovery.qcom_decrypt.rc') > imports.index('import /' + name)):
        raise ValueError('Official Qualcomm services must be imported before the device loader overrides')
    text = entries[name][1].decode()
    services = {}
    for block in ('\n' + text).split('\nservice ')[1:]:
        lines = block.splitlines()
        service_name, executable = lines[0].split()
        if service_name in services:
            raise ValueError('Duplicate official crypto service')
        services[service_name] = (executable, {line.strip() for line in lines[1:] if line[:1].isspace()})
    required = {
        'qseecomd': '/system/bin/qseecomd',
        'keymaster-4-0-qti': '/system/bin/android.hardware.keymaster@4.0-service-qti',
        'gatekeeper-1-0-qti': '/system/bin/android.hardware.gatekeeper@1.0-service-qti',
    }
    if services.keys() != required.keys():
        raise ValueError('Official Qualcomm crypto service set is incomplete')
    loader = 'setenv LD_LIBRARY_PATH /system/lib64:/vendor/lib64:/system/lib:/vendor/lib:/sbin'
    for service_name, executable in required.items():
        actual, options = services[service_name]
        if actual != executable or not {'override', 'disabled', 'user root', 'group root',
                                       'seclabel u:r:recovery:s0', loader} <= options:
            raise ValueError(f'Official crypto service has unsafe or shadowed providers: {service_name}')
    verify_gatekeeper_spu_configuration(entries)
    return sorted(required)

def verify(image, report, kernel=None):
    root = Path(__file__).resolve().parents[1]
    expected = json.loads((root/'prebuilt/manifest.json').read_text())
    from kernel_input import verify_image_kernel, verify_bundled_boot
    verify_bundled_boot(root)
    supplied = root / 'prebuilt/kernel'
    if kernel is not None and Path(kernel).resolve() != supplied.resolve():
        raise ValueError('Hotdog uses only the bundled original F22 kernel')
    raw = Path(image).read_bytes(); header, pieces = parse_boot(raw)
    module = None
    if (root / 'modules/manifest.json').exists():
        module = json.loads((root / 'modules/manifest.json').read_text())['files']['qca_cld3_wlan.ko']
    kernel_record = verify_image_kernel(pieces['kernel'], supplied, module)
    if len(raw) != expected['partition_bytes']:
        raise ValueError('Final AVB-padded image must equal the actual 96 MiB partition')
    for key in ('kernel_address','ramdisk_address','second_address','tags_address','dtb_address'):
        if header[key] != expected['header'][key]: raise ValueError(f'Changed boot address: {key}')
    for n in ('kernel', 'dtb.img', 'recovery-dtbo.img'):
        record = expected['files'][n]
        if hashlib.sha256(pieces[n]).hexdigest() != record['sha256']:
            raise ValueError(f'Changed device boot component: {n}')
    compressed = pieces['ramdisk']
    layout = json.loads((root/'config/bootloader-layout.json').read_text())
    loading = bootloader_layout(pieces['kernel'], len(compressed), header['page_size'], layout)
    if compressed[:2] == b'\x1f\x8b':
        compression = 'gzip'; data = gzip.decompress(compressed)
    elif compressed[:6] == b'\xfd7zXZ\x00':
        raise ValueError('This device configuration requires legacy LZMA ramdisks')
    else:
        compression = 'lzma'; data = lzma.decompress(compressed, format=lzma.FORMAT_ALONE)
        from lzma_ramdisk import DICTIONARY_BYTES
        if int.from_bytes(compressed[1:5], 'little') != DICTIONARY_BYTES:
            raise ValueError('Ramdisk LZMA dictionary differs from the device compressor')
    entries = unpack_newc(data)
    from verify_hotdog import verify_fastboot_runtime, HEALTH_BINARY, HEALTH_PROVIDER, FASTBOOT_HAL_PROVIDER
    fastboot_runtime = verify_fastboot_runtime(entries)
    if b'terminal action handed off with graphics thread alive' not in entries.get('system/bin/recovery', (0, b''))[1]:
        raise ValueError('Native UI power handoff repair is missing from recovery')
    if b'terminal action retained across startup page' not in entries.get('system/bin/recovery', (0, b''))[1]:
        raise ValueError('Native UI must preserve terminal actions across startup pages')
    if b'AERA: ignoring unsupported --fastboot request.' not in entries.get('system/bin/recovery', (0, b''))[1]:
        raise ValueError('Native Fastbootd capability guard is missing from recovery')
    required = ['system/bin/recovery','system/etc/recovery.fstab',
                'init.recovery.qcom.rc','init.recovery.usb.rc','init.recovery.qcom_decrypt.rc',
                'system/bin/qseecomd','system/bin/android.hardware.keymaster@4.0-service-qti',
                'system/bin/android.hardware.gatekeeper@1.0-service-qti']
    missing = [p for p in required if p not in entries]
    if missing: raise ValueError(f'Missing ramdisk files: {missing}')
    usb_configuration = verify_usb_configuration(entries['init.recovery.usb.rc'][1])
    forbidden = ['system/bin/oplus_h40_credential_helper','system/bin/phoenix','ramdisk-stock.cpio.gz']
    if any(p in entries for p in forbidden): raise ValueError('Stock/custom recovery runtime was imported')
    native_init = verify_native_init(entries)
    native_services = verify_native_service_configuration(entries)
    crypto_services = verify_crypto_service_configuration(entries)
    gpu_runtime = verify_gpu_runtime(entries)
    wifi_runtime = verify_wifi_runtime(entries, json.loads((root/'modules/manifest.json').read_text()))
    inputs = json.loads((root/'proprietary/manifest.json').read_text())
    for n, record in inputs['files'].items():
        if n not in entries or hashlib.sha256(entries[n][1]).hexdigest() != record['sha256']:
            raise ValueError(f'Packaged vendor input differs or is absent: {n}')
    # Check the compiled provider closure, not just dependency names in the tree.
    libraries = {}
    for n, (mode, blob) in entries.items():
        if '/lib64/' in n and n.endswith('.so') and blob[:5] == b'\x7fELF\x02':
            libraries[PurePosixPath(n).name] = blob
    abi_errors = []
    def dynamic(blob):
        elf = ELFFile(io.BytesIO(blob)); dyn = elf.get_section_by_name('.dynamic')
        deps = [t.needed for t in dyn.iter_tags() if t.entry.d_tag == 'DT_NEEDED'] if dyn else []
        symbols = elf.get_section_by_name('.dynsym')
        defined, undefined = set(), set()
        if symbols:
            for s in symbols.iter_symbols():
                if s.entry.st_shndx != 'SHN_UNDEF': defined.add(s.name)
                elif s.entry.st_info.bind == 'STB_GLOBAL': undefined.add(s.name)
        return deps, defined, undefined
    audited = {n for n, record in inputs['files'].items() if 'needed' in record} | set(WLAN_EXECUTABLES) | {'system/bin/fastbootd', HEALTH_BINARY, HEALTH_PROVIDER, FASTBOOT_HAL_PROVIDER}
    for n in sorted(audited):
        deps, defined, undefined = dynamic(entries[n][1]); seen = set(); todo = list(deps)
        while todo:
            name = todo.pop()
            if name in seen: continue
            seen.add(name)
            if name not in libraries:
                abi_errors.append(f'{n}: missing {name}'); continue
            children, exports, _ = dynamic(libraries[name]); defined |= exports; todo += children
        absent = sorted(undefined - defined - {'__cxa_finalize'})
        if absent: abi_errors.append(f'{n}: unresolved strong symbols {absent[:12]}')
    result = {'kernel_input':kernel_record,'image_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
              'ramdisk_bytes':len(compressed),'ramdisk_entries':len(entries),
              'ramdisk_compression':compression,
              'lzma_dictionary_bytes':int.from_bytes(compressed[1:5], 'little') if compression == 'lzma' else None,
              'architecture':verify_arm64_runtime(entries),'bootloader_layout':loading,
              'native_init_script':native_init,'native_init_target':'/system/bin/init',
              'native_service_configuration':native_services,
              'official_crypto_services':crypto_services,
              'gatekeeper_startup':verify_gatekeeper_spu_configuration(entries),
              'ui_power_handoff':{'graphics_thread_kept_alive':True,'terminal_action_retained':True,'device_reboot_tested':False},
              'fastbootd_enabled':True, 'fastbootd_runtime':fastboot_runtime,
              'fastbootd_capability_guard':True,
              'screen_lock':verify_screen_lock_configuration(entries['system/bin/recovery'][1]),
              'filesystem_format':verify_filesystem_format_configuration(entries['system/bin/recovery'][1], entries),
              'usb_configuration':usb_configuration,
              'gpu_native_buffer_library':gpu_runtime,
              'gpu_startup':verify_gpu_startup_configuration(entries['system/bin/recovery'][1], image_properties(entries), entries),
              'wifi_runtime':wifi_runtime,
              'vendor_inputs':len(inputs['files']),'abi_errors':abi_errors}
    target = Path(report); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2)+'\n')
    if abi_errors: raise ValueError('Vendor/AERA ABI audit failed; see verification report')
    print(json.dumps(result,indent=2))

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('image'); p.add_argument('--report',required=True)
    a=p.parse_args(); verify(a.image,a.report)
