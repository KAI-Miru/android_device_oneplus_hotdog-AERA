#!/usr/bin/env python3
"""Identify the source plan and host tools required by a prepared builder."""
import argparse
import hashlib
import json
import os
from pathlib import Path

INPUTS = ('sources.lock.json', 'tools/prepare_manifest.py',
          'tools/prepare_checkout.py', 'tools/complete_snapshot.py', 'ci/patches/soong-go-memory.patch',
          'ci/patches/make-config-cache.patch',
          'ci/Builder.Dockerfile', 'tools/requirements.txt',
          'tools/prepare_build.py', 'tools/environment_fingerprint.py',
          'ci/compile.sh', 'ci/warm-builder.sh', 'ci/use-prepared.sh',
          'ci/package-builder.sh', 'tools/prepared_snapshot.py')


def fingerprint(root):
    digest = hashlib.sha256()
    for name in INPUTS:
        digest.update(name.encode() + b'\0')
        digest.update((Path(root) / name).read_bytes())
    return digest.hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write')
    args = parser.parse_args()
    value = fingerprint(Path(__file__).resolve().parents[1])
    if args.write:
        Path(args.write).write_text(json.dumps({
            'schema': 1, 'fingerprint': value,
            'prepared_device_revision': os.environ.get('AERA_DEVICE_REVISION'),
            'source_dir': '/aera', 'device_dir': '/device-tree',
        }, indent=2) + '\n')
    print(value)
