#!/usr/bin/env python3
"""Keep required tools and recovery build definitions in the CI checkout."""
import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import xml.etree.ElementTree as ET
from complete_snapshot import ensure_snapshot

SPARSE_PREBUILTS = {
    # C/C++ uses r547379; the pinned Rust bindgen explicitly uses r530567.
    'prebuilts/clang/host/linux-x86': ['clang-r547379', 'clang-r530567', 'clang-stable', 'soong',
        'llvm-binutils-stable', 'mlgo-models', 'profiles'],
    'prebuilts/sdk': ['36', 'current', 'tools',
        'opt', 'perm', 'extensions', 'renderscript', 'sdk-annotations', 'vendor', 'update_prebuilts'],
    'prebuilts/abi-dumps/ndk': [f'{version}/{arch}' for version in (28, 30, 35, 36)
        for arch in ('arm', 'arm64')],
    'prebuilts/abi-dumps/platform': [f'{version}/64/{arch}' for version in (35, 36)
        for arch in ('arm', 'arm64', 'arm_arm64')],
    'prebuilts/abi-dumps/vndk': ['30', '202504'],
    'prebuilts/vndk/v30': ['arm', 'arm64', 'common'],
    'prebuilts/tools': ['common', 'linux-x86_64'],
    'prebuilts/build-tools': ['common', 'linux-x86', 'linux_musl-x86', 'path', 'sysroots'],
}

# Restore source projects pruned by older repair attempts. Their Android.bp
# files can supply plugins/defaults even when their test targets are not built.
FULL_SOURCE_PROJECTS = ('cts', 'prebuilts/rust')


def exclusions(manifest):
    return ','.join(p.attrib['name'] for p in ET.parse(manifest).getroot().findall('project')
                    if p.attrib.get('path', p.attrib['name']) not in SPARSE_PREBUILTS)


def configure(source_root):
    source_root = Path(source_root).resolve()
    for project in FULL_SOURCE_PROJECTS:
        git_dir = source_root / '.repo/projects' / (project + '.git')
        if not (git_dir / 'config').is_file():
            continue
        initialized = (git_dir / 'index').is_file() and (source_root / project / '.git').exists()
        # Before repo's local checkout, the project Git directory can contain
        # only configuration. Rust is already fetched without a blob filter;
        # let repo initialize its worktree before inspecting or restoring HEAD.
        if project == 'prebuilts/rust' and initialized:
            lock = json.loads((Path(__file__).resolve().parents[1] / 'sources.lock.json').read_text())
            revision = ensure_snapshot(source_root, project, require_full=True,
                                       revision='refs/tags/' + lock['aosp_revision'])
            current = subprocess.run(['git', '--git-dir', str(git_dir),
                                      'rev-parse', '--verify', 'HEAD'], check=False,
                                     capture_output=True, text=True).stdout.strip()
            # A failed repo checkout can leave HEAD on the remote's default
            # branch. Restore the locked revision before expanding it.
            if current != revision:
                subprocess.run(['git', '--git-dir', str(git_dir), '--work-tree',
                                str(source_root / project), 'checkout', '--force', '--detach', revision], check=True)
        if initialized:
            subprocess.run(['git', '--git-dir', str(git_dir), '--work-tree',
                            str(source_root / project), 'sparse-checkout', 'disable'], check=True)
        else:
            subprocess.run(['git', 'config', '--file', str(git_dir / 'config'),
                            'core.sparseCheckout', 'false'], check=True)
        print(f'Full source checkout: {project}')
    for project, directories in SPARSE_PREBUILTS.items():
        git_dir = source_root / '.repo/projects' / (project + '.git')
        if not (git_dir / 'config').is_file():
            raise ValueError(f'Network sync must initialize {project} first')
        subprocess.run(['git', 'config', '--file', str(git_dir / 'config'),
                        'core.sparseCheckout', 'true'], check=True)
        subprocess.run(['git', 'config', '--file', str(git_dir / 'config'),
                        'core.sparseCheckoutCone', 'false'], check=True)
        info = git_dir / 'info'
        info.mkdir(exist_ok=True)
        # Root metadata and build declarations are preserved in every project.
        parents = {str(parent) for directory in directories
                   for parent in PurePosixPath(directory).parents if str(parent) != '.'}
        patterns = ['/*', '!/*/']
        for parent in sorted(parents, key=lambda p: (p.count('/'), p)):
            patterns += [f'/{parent}/', f'!/{parent}/*/']
        patterns += [f'/{directory}/' for directory in directories]
        (info / 'sparse-checkout').write_text('\n'.join(patterns) + '\n', newline='\n')
        print(f'Sparse prebuilt checkout: {project}: {", ".join(directories)}')
        if (git_dir / 'index').is_file() and (source_root / project / '.git').exists():
            # repo may skip checkout when HEAD is unchanged. Apply new patterns
            # explicitly so retained repair sessions also release excluded files.
            subprocess.run(['git', '--git-dir', str(git_dir), '--work-tree',
                            str(source_root / project), 'read-tree', '-mu', 'HEAD'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['exclusions', 'configure'])
    parser.add_argument('path')
    args = parser.parse_args()
    if args.mode == 'exclusions':
        print(exclusions(args.path))
    else:
        configure(args.path)
