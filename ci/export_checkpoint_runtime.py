#!/usr/bin/env python3
"""Flatten the exact container runtime while excluding all build inputs."""
from pathlib import Path, PurePosixPath
import sys
import tarfile

EXCLUDE = {'aera', 'builder-archive', 'device-tree', 'checkpoint', 'artifacts'}
output = Path(sys.argv[1])
if output.exists():
    raise ValueError('Runtime export already exists')
with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as source:
    with tarfile.open(output, mode='w', format=tarfile.PAX_FORMAT) as destination:
        for member in source:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('Unsafe runtime export path')
            if name.parts and name.parts[0] in EXCLUDE:
                continue
            if any(part in {'.docker', '.git-credentials', '.ssh'} for part in name.parts):
                raise ValueError('Credential material found in runtime export')
            stream = source.extractfile(member) if member.isfile() else None
            destination.addfile(member, stream)
