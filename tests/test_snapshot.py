from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from complete_snapshot import ensure_snapshot
from compact_checkout import compact


class SnapshotTests(unittest.TestCase):
    def test_partial_cache_is_refilled_and_checks_out_with_origin_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            origin = root / 'origin'
            origin.mkdir()

            def git(*args, cwd=origin):
                return subprocess.check_output(['git', '-C', str(cwd), *args], stderr=subprocess.PIPE)

            git('init', '-q')
            git('config', 'user.name', 'Snapshot fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            git('config', 'uploadpack.allowFilter', 'true')
            data = bytes(range(256)) * 4096
            (origin / 'rustc').write_bytes(data)
            git('add', '.')
            git('commit', '-qm', 'Pinned tool')
            old_revision = git('rev-parse', 'HEAD')
            data += b'Pinned revision differs from the retained default HEAD'
            (origin / 'rustc').write_bytes(data)
            git('commit', '-qam', 'Updated pinned tool')
            revision = git('rev-parse', 'HEAD')
            git('tag', '-a', '-m', 'Pinned release', 'pinned')
            source = root / 'source'
            tree = source / 'prebuilts/rust'
            tree.mkdir(parents=True)
            git_dir = source / '.repo/projects/prebuilts/rust.git'
            git_dir.parent.mkdir(parents=True)
            git('clone', '--bare', '--no-tags', '--depth=2', '--filter=blob:none', origin.as_uri(), str(git_dir))
            git('config', 'core.bare', 'false', cwd=git_dir)
            git('config', 'core.worktree', str(tree), cwd=git_dir)
            (tree / '.git').write_text('gitdir: ' + git_dir.as_posix() + '\n')
            git('update-ref', '--no-deref', 'HEAD', old_revision.decode().strip(), cwd=tree)
            missing_tag = subprocess.run(['git', '-C', str(tree), 'show-ref', '--verify',
                                          'refs/tags/pinned'], capture_output=True)
            self.assertNotEqual(missing_tag.returncode, 0)
            self.assertIn(b'?', git('rev-list', '--objects', '--missing=print', 'HEAD', cwd=tree))
            restored = ensure_snapshot(source, 'prebuilts/rust', require_full=True, revision='refs/tags/pinned')
            self.assertEqual(restored.encode() + b'\n', revision)
            git('checkout', '--force', '--detach', restored, cwd=tree)
            git('repack', '-ad', cwd=tree)
            compact(source, minimum=0)
            self.assertIn(b'?', git('rev-list', '--objects', '--missing=print', 'HEAD^{tree}', cwd=tree))
            ensure_snapshot(source, 'prebuilts/rust', require_objects=True)
            origin.rename(root / 'offline-origin')
            self.assertEqual((tree / 'rustc').read_bytes(), data)
            self.assertEqual(git('rev-parse', 'HEAD', cwd=tree), revision)
            self.assertEqual(git('status', '--porcelain', cwd=tree), b'')
            (tree / 'rustc').write_bytes(data + b'Build-time local edit')
            diff = subprocess.run(['git', '-C', str(tree), 'diff', '--quiet'], capture_output=True)
            self.assertEqual(diff.returncode, 1, diff.stderr)
            self.assertFalse(list(source.glob('.aera-snapshot-*')))

    def test_network_only_checkout_fetches_exact_missing_tag_without_worktree_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            origin = root / 'origin'
            origin.mkdir()

            def git(*args, cwd=origin):
                return subprocess.check_output(['git', '-C', str(cwd), *args],
                                               stderr=subprocess.PIPE)

            git('init', '-q')
            git('config', 'user.name', 'Network-only fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (origin / 'rustc').write_text('pinned compiler')
            git('add', '.')
            git('commit', '-qm', 'Pinned compiler')
            revision = git('rev-parse', 'HEAD').decode().strip()
            git('tag', 'pinned')
            (origin / 'rustc').write_text('different default compiler')
            git('commit', '-qam', 'Unrelated default HEAD')

            source = root / 'source'
            tree = source / 'prebuilts/rust'
            tree.mkdir(parents=True)
            git_dir = source / '.repo/projects/prebuilts/rust.git'
            git_dir.parent.mkdir(parents=True)
            git('init', '--bare', '-q', str(git_dir))
            git('remote', 'add', 'origin', origin.as_uri(), cwd=git_dir)
            git('fetch', '--depth=1', '--no-tags', 'origin', 'refs/tags/pinned', cwd=git_dir)
            git('config', 'core.bare', 'false', cwd=git_dir)
            git('config', 'core.worktree', str(tree), cwd=git_dir)
            missing_head = subprocess.run(['git', '--git-dir', str(git_dir),
                                            'rev-parse', '--verify', 'HEAD'], capture_output=True)
            self.assertNotEqual(missing_head.returncode, 0)
            self.assertFalse((git_dir / 'index').exists())
            restored = ensure_snapshot(source, 'prebuilts/rust', require_full=True,
                                       revision='refs/tags/pinned')
            self.assertEqual(restored, revision)
            self.assertEqual(git('rev-parse', 'refs/tags/pinned', cwd=git_dir).decode().strip(),
                             revision)
            origin.rename(root / 'offline-origin')
            (tree / '.git').write_text('gitdir: ' + git_dir.as_posix() + '\n')
            git('checkout', '--force', '--detach', restored, cwd=tree)
            self.assertEqual((tree / 'rustc').read_text(), 'pinned compiler')
            self.assertEqual(git('status', '--porcelain', cwd=tree), b'')


if __name__ == '__main__':
    unittest.main()
