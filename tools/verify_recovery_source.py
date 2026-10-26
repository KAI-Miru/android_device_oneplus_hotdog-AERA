#!/usr/bin/env python3
"""Verify the pinned recovery fork without modifying its source files."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def verify_checkpoint_source(source_root, lock, checkout):
    metadata = Path(checkout) / 'aera_checkpoint/source.json'
    if not metadata.is_file():
        return None
    origin = json.loads(metadata.read_text())
    if origin['symbol'] != '_ZN7android4vold18cp_needsCheckpointEv':
        raise ValueError('Unexpected recovery checkpoint query symbol')
    reviewed = []
    for dependency in origin['projects']:
        project = next((p for p in lock['projects'] if p['path'] == dependency['path']), None)
        if not project or (project['commit'], project['url']) != (dependency['commit'], dependency['url']):
            raise ValueError('Recovery checkpoint query requires review against pinned ' + dependency['path'])
        for name, expected in dependency['files'].items():
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unexpected recovery checkpoint source path')
            source = Path(source_root) / dependency['path'] / relative
            if not source.is_file() or hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != expected:
                raise ValueError('Recovery checkpoint upstream source identity differs: ' + name)
        reviewed.append({'path': project['path'], 'commit': project['commit']})
    return {'symbol': origin['symbol'], 'dependencies': reviewed,
            'platform_sources_unchanged': True, 'pending_transactions_preserved': True}


def keystore_source_pin(lock, device):
    origin = json.loads((Path(device) / 'tools/keystore-source.json').read_text())
    projects = [p for p in lock['projects'] if p['path'] == 'system/security']
    if len(projects) != 1 or any(projects[0][field] != origin[field]
                                 for field in ('url', 'branch', 'commit')):
        raise ValueError('Recovery keystore requires review against the pinned system/security source')
    if set(origin['files']) != {'keystore2/src/keystore2_main.rs',
                                'keystore2/src/globals.rs', 'keystore2/Android.bp'}:
        raise ValueError('Unexpected recovery keystore source paths')
    return projects[0], origin


def verify_keystore_source(source_root, lock, checkout, device_root=None):
    device = Path(device_root) if device_root else Path(__file__).resolve().parents[1]
    if (not any(p['path'] == 'system/security' for p in lock['projects'])
            and not (device / 'tools/keystore-source.json').exists()):
        return None  # Source fixtures without a Keystore project have no dependency.
    project, origin = keystore_source_pin(lock, device)
    security = Path(source_root) / 'system/security'
    git = ['git', '-C', str(security)]
    revision = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
    if revision != project['commit']:
        raise ValueError('Recovery keystore source requires the exact pinned revision')
    if subprocess.check_output(git + ['status', '--porcelain', '--untracked-files=no']):
        raise ValueError('Recovery keystore source has uncommitted changes')
    for name, expected in origin['files'].items():
        source = security / name
        if not source.is_file() or hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != expected:
            raise ValueError('Recovery keystore source identity differs: ' + name)
    from verify_keystore import verify_keystore_configuration
    verify_keystore_configuration((Path(checkout) / 'etc/init/keystore2.rc').read_bytes())
    if (Path(checkout) / 'aera_keystore').exists():
        raise ValueError('Recovery must use the standard platform keystore2, not a copied entrypoint')
    return {'commit': revision, 'source_sha256': origin['files'],
            'recovery_argument': '--recovery', 'tracked_source_clean': True,
            'platform_crypto_unchanged': True, 'boot_completed_gc_gate_preserved': True}


def verify(source_root, artifact_root, device_root=None):
    device = Path(device_root) if device_root else Path(__file__).resolve().parents[1]
    lock = json.loads((device / 'sources.lock.json').read_text())
    project = next(p for p in lock['projects'] if p['path'] == 'bootable/recovery')
    checkout = Path(source_root).resolve() / project['path']
    git = ['git', '-C', str(checkout)]
    revision = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
    if revision != project['commit']:
        raise ValueError(f'Recovery source requires {project["commit"]}, found {revision}')
    if subprocess.check_output(git + ['status', '--porcelain', '--untracked-files=no']):
        raise ValueError('Recovery checkout has uncommitted source changes')
    record = {'repository': project['url'], 'branch': project['branch'],
              'commit': revision, 'tracked_source_clean': True,
              'build_time_source_patches': False}
    record['keystore_source'] = verify_keystore_source(source_root, lock, checkout, device)
    record['checkpoint_source'] = verify_checkpoint_source(source_root, lock, checkout)
    artifacts = Path(artifact_root)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / 'recovery-source.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'Verified clean recovery source: {revision}')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_root')
    parser.add_argument('artifact_root')
    args = parser.parse_args()
    verify(args.source_root, args.artifact_root)
