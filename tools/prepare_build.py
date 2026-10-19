#!/usr/bin/env python3
"""Apply and record pinned host-build memory and configuration-cache patches."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def prepare(source_root, artifact_root):
    device_root = Path(__file__).resolve().parents[1]
    lock = json.loads((device_root / 'sources.lock.json').read_text())
    records = []
    for project, name, purpose in (
            ('build/soong', 'soong-go-memory.patch', 'Pass GOGC/GOMEMLIMIT through the hermetic host builder launcher'),
            ('build/make', 'make-config-cache.patch', 'Preserve unchanged configuration timestamps; regenerate for changed settings')):
        patch = device_root / 'ci/patches' / name
        checkout = Path(source_root).resolve() / project
        expected = next(p['commit'] for p in lock['projects'] if p['path'] == project)
        git = ['git', '-C', str(checkout)]
        actual = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
        if actual != expected:
            raise ValueError(f'Host patch requires pinned {project} {expected}, found {actual}')
        already = subprocess.run(git + ['apply', '--reverse', '--check', str(patch)],
                                 capture_output=True).returncode == 0
        if not already:
            subprocess.run(git + ['apply', '--check', str(patch)], check=True)
            subprocess.run(git + ['apply', str(patch)], check=True)
        records.append({'project': project, 'commit': actual, 'patch': name,
                        'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(), 'purpose': purpose})
    artifacts = Path(artifact_root)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / 'host-build-patches.json').write_text(json.dumps({'patches': records}, indent=2) + '\n')
    print('Pinned host-memory and configuration-cache patches applied and recorded')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_root')
    parser.add_argument('artifact_root')
    args = parser.parse_args()
    prepare(args.source_root, args.artifact_root)
