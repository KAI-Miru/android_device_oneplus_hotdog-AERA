#!/usr/bin/env python3
"""Import selected ARM64 vendor files and their explicit dependency closure."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]
# Compiled from AERA/platform source, never copied from Android 15 userspace.
PLATFORM_LIBRARIES = {
    'libc.so', 'libm.so', 'libdl.so', 'libc++.so', 'libc++demangle.so',
    'liblog.so', 'libbase.so', 'libcutils.so', 'libutils.so', 'libhardware.so',
    # libhidltransport is an empty compatibility shim in both vendor R and
    # pinned AERA; AERA stages its native build alongside libhidlbase.
    'libhidlbase.so', 'libhidltransport.so', 'libhwbinder.so', 'libbinder.so', 'libbinder_ndk.so',
    'libcrypto.so', 'libz.so', 'libion.so', 'libsync.so', 'libnativewindow.so',
    'libui.so', 'libprocessgroup.so', 'libvndksupport.so', 'liblzma.so',
    'libunwindstack.so', 'libbacktrace.so', 'liblz4.so', 'libfmq.so',
    'libdl_android.so', 'libziparchive.so', 'libpng.so', 'libgralloctypes.so',
    'libexpat.so', 'libxml2.so', 'libhidlmemory.so', 'libnl.so', 'libssl.so',
}

def elf_info(path):
    with path.open('rb') as f:
        if f.read(4) != b'\x7fELF':
            raise ValueError(f'Not an ELF file (possibly an extracted symlink): {path}')
        f.seek(0)
        e = ELFFile(f)
        if e.elfclass != 64 or e.header.e_machine != 'EM_AARCH64':
            raise ValueError(f'Expected ARM64 ELF: {path}')
        dynamic = e.get_section_by_name('.dynamic')
        needed = [t.needed for t in dynamic.iter_tags() if t.entry.d_tag == 'DT_NEEDED'] if dynamic else []
        return {'elf_class': 64, 'machine': 'EM_AARCH64', 'needed': needed}

def select_library(soname, search):
    # Ignore Windows symlink placeholders and require a real ARM64 ELF.
    choices = [base / soname for base in search if (base / soname).is_file()
               and (base / soname).read_bytes()[:4] == b'\x7fELF']
    if not choices:
        raise FileNotFoundError(f'Unresolved vendor library {soname}')
    return choices[0]


def official_crypto_root(checkout, source):
    checkout = checkout.resolve()
    actual = subprocess.check_output(['git', '-c', f'safe.directory={checkout}',
        '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != source['commit']:
        raise ValueError(f'Official crypto checkout must be {source["commit"]}, found {actual}')
    return checkout / 'recovery/root'


def platform_library(soname):
    return soname in PLATFORM_LIBRARIES or re.fullmatch(r'android\.hardware\.[\w.]+@[\d.]+\.so', soname)


def graphics_inputs(dump, seeds):
    """Keep the entire graphics dependency set from one supplied vendor build."""
    search = [dump / 'vendor/lib64', dump / 'vendor/lib64/egl', dump / 'vendor/lib64/hw']
    pending, records = list(seeds.items()), {}
    while pending:
        source, dest = pending.pop(0)
        if dest in records:
            if records[dest] != source:
                raise ValueError(f'Conflicting graphics provider for {dest}')
            continue
        info = elf_info(dump / source)
        records[dest] = source
        for soname in info['needed']:
            if platform_library(soname): continue
            candidate = select_library(soname, search)
            relative = candidate.relative_to(dump).as_posix()
            pending.append((relative, seeds.get(relative, 'system/lib64/' + soname)))
    return records


def import_vendor(dump, official_checkout, gpu_dump):
    dump = dump.resolve()
    seeds = json.loads((ROOT / 'tools/vendor-seeds.json').read_text())
    crypto = json.loads((ROOT / 'tools/official-crypto-source.json').read_text())
    gpu = json.loads((ROOT / 'tools/gpu-source.json').read_text())
    gpu_dump = gpu_dump.resolve()
    if gpu_dump.name != gpu['source_dump']:
        raise ValueError(f'Graphics inputs must come from {gpu["source_dump"]}')
    graphics = graphics_inputs(gpu_dump, gpu['seeds'])
    official = official_crypto_root(official_checkout, crypto)
    search = [dump / 'vendor/lib64', dump / 'vendor/lib64/egl', dump / 'vendor/lib64/hw']
    official_search = [official / 'vendor/lib64', official / 'vendor/lib64/hw']
    crypto_destinations = set(crypto['seeds'].values())
    pending = [('official', src, dst) for src, dst in crypto['seeds'].items()]
    pending += [('dump', src, dst) for src, dst in seeds.items()
                if dst not in crypto_destinations and dst not in graphics]
    pending += [('graphics', src, dst) for dst, src in graphics.items()]
    records, built = {}, set()
    previous = json.loads((ROOT / 'proprietary/manifest.json').read_text())
    while pending:
        kind, source, dest = pending.pop(0)
        if dest in records:
            continue
        source_root = official if kind == 'official' else gpu_dump if kind == 'graphics' else dump
        p = source_root / source
        if not p.is_file():
            raise FileNotFoundError(f'Missing required vendor file: {source}')
        info = elf_info(p); data = p.read_bytes()
        if kind == 'official':
            # HEAD alone does not prove a blob was not changed in the checkout.
            pinned = subprocess.check_output(['git', '-c', f'safe.directory={official_checkout.resolve()}',
                '-C', str(official_checkout), 'show', f'{crypto["commit"]}:recovery/root/{source}'])
            if data != pinned:
                raise ValueError(f'Official crypto blob differs from its pinned Git revision: {source}')
        target = ROOT / 'proprietary' / dest
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        records[dest] = {'source': source, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), **info}
        if kind == 'official':
            records[dest].update(source_repository=crypto['repository'], source_commit=crypto['commit'])
        else:
            records[dest]['source_dump'] = source_root.name
        if kind == 'graphics': records[dest]['runtime'] = 'graphics'
        for soname in info['needed']:
            if platform_library(soname):
                built.add(soname); continue
            graphics_dest = next((name for name in graphics if Path(name).name == soname), None)
            if graphics_dest:
                pending.append(('graphics', graphics[graphics_dest], graphics_dest))
                continue
            provider_kind, provider_root = 'dump', dump
            if kind == 'official':
                try:
                    candidate = select_library(soname, official_search)
                    provider_kind, provider_root = 'official', official
                except FileNotFoundError:
                    # Some Qualcomm display providers used by secure UI are
                    # outside the official crypto bundle. Record the supplied
                    # vendor provider independently; never replace platform ELFs.
                    candidate = select_library(soname, search)
            else:
                candidate = select_library(soname, search)
            dependency_source = candidate.relative_to(provider_root).as_posix()
            pending.append((provider_kind, dependency_source,
                            seeds.get(dependency_source, 'system/lib64/' + soname)))

    # libhardware and QSEE load seeds dynamically, outside DT_NEEDED.
    original = 'vendor/lib64/hw/android.hardware.gatekeeper@1.0-impl-qti.so'
    mirror = 'system/lib64/hw/android.hardware.gatekeeper@1.0-impl-qti.so'
    (ROOT / 'proprietary' / mirror).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'proprietary' / original, ROOT / 'proprietary' / mirror)
    records[mirror] = dict(records[original])

    # No calibration, persist contents, keys, or stock policy are imported.
    firmware = []
    for pattern in ('a630*', 'a640*', 'a6xx*', 'aw8697_rtp.bin', 'aw8697_haptic_170.bin', '40ms_RTP_170Hz.bin', '80ms_RTP_170Hz.bin'):
        firmware += list((dump / 'vendor/firmware').glob(pattern))
    for p in sorted(set(firmware)):
        if not p.is_file(): continue
        dest = 'vendor/firmware/' + p.name; target = ROOT / 'proprietary' / dest
        target.parent.mkdir(parents=True, exist_ok=True); data = p.read_bytes(); target.write_bytes(data)
        records[dest] = {'source': p.relative_to(dump).as_posix(), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    # Remove only previously manifested binary inputs made obsolete by this
    # explicit source change. Do not delete other files or whole directories.
    output_root = (ROOT / 'proprietary').resolve()
    for name in set(previous['files']) - set(records):
        obsolete = (output_root / name).resolve()
        if not obsolete.is_relative_to(output_root):
            raise ValueError(f'Unsafe obsolete vendor path: {name}')
        obsolete.unlink()
    metadata = {'source_dump': dump.name, 'source_vendor_sdk': 30, 'source_system_sdk': 35,
                'official_crypto_source': {k: crypto[k] for k in ('repository', 'commit')},
                'graphics_source': gpu,
                'platform_libraries': sorted(built), 'files': dict(sorted(records.items()))}
    (ROOT / 'proprietary/manifest.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8', newline='\n')
    lines = ['# Generated by tools/import_vendor.py; providers retain their original terms.', 'PRODUCT_COPY_FILES += \\']
    entries = [f'    $(LOCAL_PATH)/proprietary/{dest}:$(TARGET_COPY_OUT_RECOVERY)/root/{dest}' for dest in sorted(records)]
    lines += [entry + (' \\' if i + 1 < len(entries) else '') for i, entry in enumerate(entries)]
    modules = sorted(s[:-3] for s in built if s not in {'libc.so', 'libm.so', 'libdl.so', 'libdl_android.so'})
    lines += ['', 'TARGET_RECOVERY_DEVICE_MODULES += ' + ' '.join(modules), 'RECOVERY_LIBRARY_SOURCE_FILES += \\']
    lines += [f'    $(TARGET_OUT_SHARED_LIBRARIES)/{m}.so' + (' \\' if i + 1 < len(modules) else '') for i, m in enumerate(modules)]
    (ROOT / 'proprietary-files.mk').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    (ROOT / 'proprietary-files.txt').write_text('\n'.join(
        f"{r.get('source_repository', r.get('source_dump', dump.name))}@{r.get('source_commit', 'supplied-dump')}/{r['source']}:{dest}|{r['sha256']}"
        for dest, r in sorted(records.items())) + '\n', encoding='utf-8', newline='\n')
    print(f'Imported {len(records)} files ({sum(r["bytes"] for r in records.values()) / 1048576:.1f} MiB); {len(built)} dependencies supplied by AERA/platform source.')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('dump', type=Path)
    p.add_argument('--official-crypto-tree', type=Path, required=True)
    p.add_argument('--gpu-dump', type=Path, required=True)
    args = p.parse_args()
    import_vendor(args.dump, args.official_crypto_tree, args.gpu_dump)
