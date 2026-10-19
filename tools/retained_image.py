#!/usr/bin/env python3
"""Recover an exact caller-approved Image from a private build checkpoint."""
import hashlib
from pathlib import Path
import re
import shutil
import sys


def select(source, expected):
    source = Path(source).resolve()
    if not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('Retained Image requires the caller-approved SHA256')
    target = source / '.external-inputs/Image'
    for candidate in (target, source / 'device/oneplus/hotdog/prebuilt/kernel',
                      source / 'device/oneplus/hotdog/prebuilt/Image',
                      source / 'out/target/product/hotdog/kernel'):
        if candidate.is_file() and not candidate.is_symlink():
            if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
                continue
            if candidate != target:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, target)
            return target
    raise ValueError('Approved Image is absent from the private checkpoint; supply its HTTPS URL')


if __name__ == '__main__':
    print(select(sys.argv[1], sys.argv[2]))
