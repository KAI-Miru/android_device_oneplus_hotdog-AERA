#!/usr/bin/env python3
"""Release duplicate blob packs in a dedicated CI checkout, retaining Git metadata."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def compact(source_root, minimum=16 * 1024 * 1024):
    root = Path(source_root).resolve()
    repo_root = (root / '.repo').resolve()
    configs = sorted((repo_root / 'projects').rglob('config'))
    stores = [(config, (config.parent / 'objects').resolve()) for config in configs]
    counts = {}
    for _, objects in stores:
        counts[objects] = counts.get(objects, 0) + 1
    reclaimed = 0
    for config, objects in stores:
        git_dir = config.parent
        # Native AERA invokes git diff while parsing Android.mk inside nsjail.
        # Keep its blobs available because that sandbox has no network access.
        if git_dir == repo_root / 'projects/bootable/recovery.git':
            continue
        if not objects.is_relative_to(repo_root):
            raise ValueError(f'Object store outside dedicated checkout: {objects}')
        # A shared object store can contain another worktree's pinned HEAD.
        if counts[objects] != 1:
            continue
        packs = (objects / 'pack').resolve()
        if not packs.is_relative_to(repo_root):
            raise ValueError(f'Pack directory outside dedicated checkout: {packs}')
        old_files = list(packs.glob('pack-*'))
        before = sum(p.stat().st_size for p in old_files)
        if before < minimum or any(p.suffix == '.keep' for p in old_files):
            continue
        git = ['git', '--git-dir', str(git_dir)]
        head = subprocess.run(git + ['rev-parse', '--verify', 'HEAD'],
                              capture_output=True, text=True)
        # Only compact projects that have completed a local checkout.
        if head.returncode or not (git_dir / 'index').is_file():
            continue
        remotes = subprocess.check_output(git + ['remote'], text=True).splitlines()
        if not remotes:
            continue
        refs = subprocess.check_output(git + ['for-each-ref', '--format=%(objectname)'], text=True)
        revisions = (head.stdout + refs).encode()
        with tempfile.NamedTemporaryFile(dir=packs, suffix='.pack', delete=False) as output:
            temporary = Path(output.name)
            try:
                subprocess.run(git + ['pack-objects', '--revs', '--filter=blob:none',
                    '--missing=allow-promisor', '--stdout'], input=revisions,
                    stdout=output, check=True)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            digest = subprocess.check_output(git + ['index-pack', str(temporary)], text=True).strip()
            new_pack = packs / f'pack-{digest}.pack'
            temporary.replace(new_pack)
            temporary.with_suffix('.idx').replace(new_pack.with_suffix('.idx'))
            new_pack.with_suffix('.promisor').touch()
            subprocess.run(git + ['config', 'remote.' + remotes[0] + '.promisor', 'true'], check=True)
            subprocess.run(git + ['config', 'remote.' + remotes[0] + '.partialclonefilter', 'blob:none'], check=True)
            subprocess.run(git + ['config', 'core.repositoryformatversion', '1'], check=True)
            subprocess.run(git + ['config', 'extensions.partialClone', remotes[0]], check=True)
            # Keep source files, index, commits, trees and refs. Missing blobs can
            # be fetched from the original remote if a later checkout needs them.
            for old in old_files:
                if old.stem != new_pack.stem:
                    old.chmod(old.stat().st_mode | 0o200)
                    old.unlink()
            (packs / 'multi-pack-index').unlink(missing_ok=True)
            after = sum(p.stat().st_size for p in packs.glob('pack-*'))
            reclaimed += before - after
            print(f'Git cache compacted: {git_dir.relative_to(repo_root)}: '
                  f'{before // 1048576} -> {after // 1048576} MiB', flush=True)
        finally:
            temporary.unlink(missing_ok=True)
            temporary.with_suffix('.idx').unlink(missing_ok=True)
    print(f'Released {reclaimed // 1048576} MiB of duplicate Git blobs', flush=True)
    return reclaimed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_root')
    compact(parser.parse_args().source_root)
