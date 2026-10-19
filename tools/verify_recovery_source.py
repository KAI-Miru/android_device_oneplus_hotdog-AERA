#!/usr/bin/env python3
"""Verify the pinned recovery fork without modifying its source files."""
import argparse
import json
from pathlib import Path
import subprocess


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
