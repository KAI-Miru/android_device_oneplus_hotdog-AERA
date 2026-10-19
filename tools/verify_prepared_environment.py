#!/usr/bin/env python3
"""Verify cached host inputs and allow a pinned recovery-only source update."""
import argparse
import hashlib
import json
from pathlib import Path
from environment_fingerprint import INPUTS, fingerprint

LEGACY = set()
READER_INPUTS = {'tools/prepared_snapshot.py', 'ci/use-prepared.sh'}


def recovery_delta(retained, current):
    old, new = (json.loads((root / 'sources.lock.json').read_text())
                for root in (retained, current))
    before = next(p for p in old['projects'] if p['path'] == 'bootable/recovery')
    after = next(p for p in new['projects'] if p['path'] == 'bootable/recovery')
    permitted = {'url', 'remote', 'branch', 'commit'}
    if any(before[k] != after[k] for k in before.keys() - permitted):
        raise ValueError('Recovery project identity changed')
    if (after['url'] != 'https://github.com/KAI-Miru/android_bootable_recovery.git' or
            after['branch'] != 'miru' or after['remote'] != 'Miru'):
        raise ValueError('Prepared recovery update must select the reviewed miru fork')
    import re
    if not re.fullmatch('[0-9a-f]{40}', after['commit']):
        raise ValueError('Recovery update must use an exact commit')
    old['projects'] = [p for p in old['projects'] if p['path'] != 'bootable/recovery']
    new['projects'] = [p for p in new['projects'] if p['path'] != 'bootable/recovery']
    if old != new:
        raise ValueError('Non-recovery source or toolchain plan changed')
    return {'path': 'bootable/recovery', 'from': before['commit'],
            'to': after['commit'], 'repository': after['url']}


def compiled_checkpoint(source):
    marker = source / '.aera-compiled-checkpoint.json'
    if not marker.exists():
        return None
    record = json.loads(marker.read_text())
    image = source / 'out/target/product/hotdog/recovery.img'
    if (record.get('schema') != 1 or record.get('kind') != 'compiled' or
            not record.get('ninja_state_retained') or record.get('arm64_object_count', 0) <= 0 or
            not (source / 'out/.ninja_log').is_file() or
            hashlib.sha256(image.read_bytes()).hexdigest() != record.get('image_sha256')):
        raise ValueError('Invalid compiled checkpoint')
    return record


def verify(device, source, artifacts, legacy=LEGACY):
    device, source = Path(device), Path(source)
    recorded = json.loads((source / '.aera-prepared-environment.json').read_text())['fingerprint']
    expected = fingerprint(device)
    changed = []
    update = None
    checkpoint = compiled_checkpoint(source)
    if recorded != expected:
        retained = source / 'device/oneplus/hotdog'
        if (recorded not in legacy and checkpoint is None) or fingerprint(retained) != recorded:
            raise ValueError('Unknown or altered prepared environment; prepare again')
        changed = [name for name in INPUTS
                   if (device / name).read_bytes() != (retained / name).read_bytes()]
        if 'sources.lock.json' in changed:
            try:
                update = recovery_delta(retained, device)
            except (KeyError, StopIteration, json.JSONDecodeError) as error:
                raise ValueError('Prepared source/tool inputs changed; invalid source plan') from error
        allowed = READER_INPUTS | {'sources.lock.json', 'tools/prepare_manifest.py'}
        if not changed or not set(changed) <= allowed:
            raise ValueError(f'Prepared source/tool inputs changed; prepare again: {changed}')
    result = {'prepared_fingerprint': recorded, 'current_fingerprint': expected,
              'compatible_reader_repair': changed,
              'source_toolchain_host_build_inputs_match': update is None,
              'non_recovery_sources_toolchains_host_inputs_match': True,
              'recovery_source_update': update,
              'compiled_checkpoint': checkpoint}
    artifacts = Path(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / 'prepared-environment-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device')
    parser.add_argument('source')
    parser.add_argument('artifacts')
    args = parser.parse_args()
    verify(args.device, args.source, args.artifacts)
