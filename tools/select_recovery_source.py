#!/usr/bin/env python3
"""Select the locked recovery fork in an isolated, reusable Android checkout."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse


def select(inputs, source):
    lock = json.loads((Path(inputs) / 'sources.lock.json').read_text())
    project = next(p for p in lock['projects'] if p['path'] == 'bootable/recovery')
    url = urlparse(project['url'])
    if (url.scheme != 'https' or url.netloc != 'github.com' or url.username or
            url.query or url.fragment or not re.fullmatch('[0-9a-f]{40}', project['commit'])):
        raise ValueError('Recovery source must use an exact public HTTPS Git commit')
    checkout = Path(source).resolve() / 'bootable/recovery'
    git = ['git', '-C', str(checkout)]
    actual = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
    remotes = subprocess.check_output(git + ['remote'], text=True).splitlines()
    if remotes:
        remote = remotes[0]
        subprocess.run(git + ['remote', 'set-url', remote, project['url']], check=True)
    else:
        remote = 'origin'
        subprocess.run(git + ['remote', 'add', remote, project['url']], check=True)
    if actual != project['commit']:
        # This is the dedicated CI source cache. Replace its former patched
        # recovery checkout with the committed fork; other projects stay intact.
        subprocess.run(git + ['fetch', '--no-tags', '--depth=1', remote,
                              project['commit']], check=True)
        subprocess.run(git + ['reset', '--hard', project['commit']], check=True)
    elif subprocess.check_output(git + ['status', '--porcelain', '--untracked-files=no']):
        raise ValueError('Pinned recovery source has uncommitted changes')
    print(f'Recovery fork selected: {project["commit"]}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs')
    parser.add_argument('source')
    args = parser.parse_args()
    select(args.inputs, args.source)
