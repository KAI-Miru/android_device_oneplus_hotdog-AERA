"""Verify the standard Keystore executable and its recovery-only startup option."""
import io
import shlex
import stat
from elftools.elf.elffile import ELFFile


def verify_keystore_configuration(data):
    declarations = []
    section = []
    started = False
    for raw in data.decode().splitlines():
        line = shlex.split(raw, comments=True)
        if not line:
            continue
        if not raw[0].isspace():
            section = line
        if line[:2] == ['service', 'keystore2']:
            declarations.append(line)
        if section == ['on', 'late-init'] and line == ['start', 'keystore2']:
            started = True
        if line[:2] == ['setprop', 'sys.boot_completed']:
            raise ValueError('Recovery keystore must not spoof Android boot completion')
    expected = ['service', 'keystore2', '/system/bin/keystore2', '/tmp/misc/keystore', '--recovery']
    if declarations != [expected] or not started:
        raise ValueError('Recovery keystore requires the standard executable, --recovery, temporary database and late-init startup')
    return {'executable': 'system/bin/keystore2', 'database': '/tmp/misc/keystore',
            'recovery_argument': '--recovery', 'source_verification_required': True}


def verify_keystore_runtime(entries):
    for name in ('system/bin/keystore2', 'system/etc/init/keystore2.rc'):
        if name not in entries or not stat.S_ISREG(entries[name][0]):
            raise ValueError(f'Missing recovery keystore runtime: {name}')
    result = verify_keystore_configuration(entries['system/etc/init/keystore2.rc'][1])
    mode, blob = entries[result['executable']]
    elf = ELFFile(io.BytesIO(blob))
    if not mode & 0o111 or elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
        raise ValueError('Recovery keystore must be executable ARM64')
    return result
