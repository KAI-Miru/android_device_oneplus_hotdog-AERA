#!/usr/bin/env python3
"""Refill an incomplete partial clone from a complete, pinned shallow fetch."""
import argparse
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile


def ensure_snapshot(source_root, project, require_full=False, revision=None, require_objects=False):
    root = Path(source_root).resolve()
    relative = PurePosixPath(project)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Project must stay inside the source checkout')
    git_dir = root / '.repo/projects' / (project + '.git')
    tree = root / project

    def git(*args, check=True):
        result = subprocess.run(['git', '--git-dir', str(git_dir), '--work-tree', str(tree), *args],
                                check=False, capture_output=True, text=True)
        if check and result.returncode:
            raise ValueError(f'Git failed for {project} ({" ".join(args)}): {result.stderr.strip()}')
        return result

    requested = revision or 'HEAD'
    resolved = git('rev-parse', '--verify', requested + '^{commit}', check=False)
    if resolved.returncode:
        if requested == 'HEAD':
            raise ValueError(f'Source project has no initialized HEAD: {project}')
        remotes = git('remote').stdout.splitlines()
        if not remotes:
            raise ValueError('Pinned source project has no remote')
        remote_url = git('remote', 'get-url', remotes[0]).stdout.strip()
        # repo sync --no-tags can fetch the pinned commit without creating its
        # tag ref. Fetch that exact tag; never substitute the remote default HEAD.
        refspec = requested + ':' + requested if requested.startswith('refs/tags/') else requested
        print(f'Fetching missing pinned revision: {project} at {requested}', flush=True)
        fetched = git('-c', 'http.version=HTTP/1.1', '-c', 'http.lowSpeedTime=600',
                      'fetch', '--depth=1', '--no-tags', remote_url, refspec, check=False)
        if fetched.returncode:
            raise ValueError(f'Cannot fetch pinned revision for {project}: {fetched.stderr.strip()}')
        resolved = git('rev-parse', '--verify', 'FETCH_HEAD^{commit}')
    revision = resolved.stdout.strip()
    # A network-only repo sync does not necessarily initialize worktree HEAD.
    head = git('rev-parse', '--verify', 'HEAD^{commit}', check=False).stdout.strip()
    if not require_objects and head == revision and (git_dir / 'index').exists() and (tree / '.git').exists():
        sparse_entries = git('ls-files', '-t').stdout.splitlines()
        if (not require_full or not any(line.startswith('S ') for line in sparse_entries)) and \
                git('diff', '--cached', '--quiet', revision, check=False).returncode == 0 and \
                not git('ls-files', '--deleted').stdout:
            return revision
    missing = git('rev-list', '--objects', '--missing=print', revision + '^{tree}').stdout
    if not any(line.startswith('?') for line in missing.splitlines()):
        return revision
    remotes = git('remote').stdout.splitlines()
    if not remotes:
        raise ValueError('Pinned source project has no remote')
    remote_url = git('remote', 'get-url', remotes[0]).stdout.strip()
    objects = Path(git('rev-parse', '--git-path', 'objects').stdout.strip()).resolve()
    objects.relative_to(root / '.repo')
    print(f'Fetching complete pinned snapshot: {project} at {revision}', flush=True)
    with tempfile.TemporaryDirectory(prefix='.aera-snapshot-', dir=root) as directory:
        bare = Path(directory) / 'snapshot.git'
        subprocess.run(['git', '-c', 'init.defaultBranch=aera-snapshot', 'init', '--bare', '--quiet', str(bare)], check=True)
        # A fresh object store avoids advertising incomplete "have" commits to
        # the server and requests one normal pack instead of individual blobs.
        subprocess.run(['git', '--git-dir', str(bare), '-c', 'http.version=HTTP/1.1',
                        '-c', 'http.lowSpeedTime=600', 'fetch', '--depth=1', '--no-tags',
                        remote_url, revision], check=True)
        origin = bare / 'objects'
        for item in origin.rglob('*'):
            if not item.is_file() or item.relative_to(origin).as_posix() == 'info/alternates':
                continue
            target = objects / item.relative_to(origin)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                continue
            try:
                os.link(item, target)
            except OSError:
                shutil.copy2(item, target)
    remaining = git('rev-list', '--objects', '--missing=print', revision + '^{tree}').stdout
    if any(line.startswith('?') for line in remaining.splitlines()):
        raise ValueError(f'Complete snapshot still has missing objects: {project}')
    print(f'Pinned snapshot restored: {project}', flush=True)
    return revision


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_root')
    parser.add_argument('project')
    parser.add_argument('--require-full', action='store_true')
    parser.add_argument('--revision')
    parser.add_argument('--require-objects', action='store_true')
    args = parser.parse_args()
    ensure_snapshot(args.source_root, args.project, args.require_full, args.revision, args.require_objects)
