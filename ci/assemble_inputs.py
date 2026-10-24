#!/usr/bin/env python3
"""Combine a device checkout and runner checkout for the existing build scripts."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

HOST_TOOLS = {'prepare_manifest.py', 'prepare_checkout.py', 'prepare_build.py',
              'compact_checkout.py', 'complete_snapshot.py', 'environment_fingerprint.py',
              'prepared_snapshot.py', 'verify_prepared_environment.py', 'select_recovery_source.py'}
HOST_TESTS = {'test_build_cache.py', 'test_build_kernel_preflight.py', 'test_capacity.py', 'test_checkout.py',
              'test_compact.py', 'test_environment.py', 'test_manifest.py',
              'test_prepared_snapshot.py', 'test_repair.py', 'test_restore.py', 'test_snapshot.py',
              'test_assembly.py', 'test_compiled_checkpoint.py', 'test_hotdog_target.py', 'test_kernel_archive.py',
              'test_image_artifact.py'}

def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])

def tracked(root):
    return [name.decode() for name in git(root, 'ls-files', '-z').split(b'\0') if name]

def is_runner_file(name):
    if name == 'ci/bootloader-layout.json': return False
    return (name.startswith('ci/') or name == '.dockerignore' or
            (name.startswith('tools/') and Path(name).name in HOST_TOOLS) or
            (name.startswith('tests/') and Path(name).name in HOST_TESTS))

def assemble(device, runner, output):
    device, runner, output = (Path(p).resolve() for p in (device, runner, output))
    for root in (device, runner):
        if output == root or root in output.parents:
            raise ValueError('Build inputs must be outside both checkouts')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Build input directory must be empty')
    # Resolve identities before copying; an invalid checkout leaves no partial assembly.
    revisions = {name: git(root, 'rev-parse', 'HEAD').decode().strip()
                 for name, root in (('device', device), ('runner', runner))}
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for root, owner in ((device, 'device'), (runner, 'runner')):
        for name in tracked(root):
            if name.startswith('.github/') or name == 'README.md': continue
            if owner == 'device' and is_runner_file(name): continue
            if owner == 'runner' and not is_runner_file(name): continue
            source, target = root / name, output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError(f'Conflicting build input: {name}')
            shutil.copy2(source, target, follow_symlinks=False)
            records.append({'path': name, 'owner': owner})
    metadata = {'device_revision': revisions['device'], 'runner_revision': revisions['runner'],
                'files': records}
    (output / 'assembly-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True)
    parser.add_argument('--runner', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = assemble(args.device, args.runner, args.output)
    print(json.dumps({k: result[k] for k in ('device_revision', 'runner_revision')}))
