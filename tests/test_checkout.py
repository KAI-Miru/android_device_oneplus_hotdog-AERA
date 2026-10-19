from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from prepare_checkout import configure, exclusions, SPARSE_PREBUILTS


class CheckoutTests(unittest.TestCase):
    def test_configures_cold_rust_before_repo_initializes_its_git_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git_dir = root / '.repo/projects/prebuilts/rust.git'
            git_dir.mkdir(parents=True)
            # repo's network-only phase has configuration, but no local HEAD,
            # index or project worktree yet.
            (git_dir / 'config').write_text('[core]\n\tsparseCheckout = true\n')
            before = subprocess.run(['git', '--git-dir', str(git_dir), 'remote'],
                                    capture_output=True)
            self.assertNotEqual(before.returncode, 0)
            with patch('prepare_checkout.SPARSE_PREBUILTS', {}):
                configure(root)
            value = subprocess.check_output(['git', 'config', '--file', str(git_dir / 'config'),
                                             'core.sparseCheckout'], text=True)
            self.assertEqual(value.strip(), 'false')
            self.assertFalse((git_dir / 'HEAD').exists())
            self.assertFalse((root / 'prebuilts/rust').exists())

    def test_restores_build_definitions_in_a_retained_sparse_source_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / 'cts'
            tree.mkdir()

            def git(*args):
                return subprocess.run(['git', '-C', str(tree), *args], check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            git('init', '-q')
            git('config', 'user.name', 'Source fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            for name in ('Android.bp', 'build/Android.bp', 'tests/Android.bp'):
                target = tree / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(name)
            git('add', '.')
            git('commit', '-qm', 'Source build definitions')
            git('sparse-checkout', 'init', '--no-cone')
            (tree / '.git/info/sparse-checkout').write_text('/*\n!/*/\n/build/\n')
            git('read-tree', '-mu', 'HEAD')
            self.assertFalse((tree / 'tests/Android.bp').exists())
            git_dir = root / '.repo/projects/cts.git'
            git_dir.parent.mkdir(parents=True)
            (tree / '.git').rename(git_dir)
            (tree / '.git').write_text('gitdir: ' + git_dir.as_posix() + '\n')
            git('config', 'core.worktree', str(tree))
            with patch('prepare_checkout.SPARSE_PREBUILTS', {}):
                configure(root)
            self.assertTrue((tree / 'tests/Android.bp').is_file())
            self.assertEqual(git('status', '--porcelain').stdout, b'')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux SDK symlinks')
    def test_retained_sdk_checkout_keeps_root_symlink_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / 'prebuilts/sdk'
            tree.mkdir(parents=True)
            def git(*args):
                return subprocess.run(['git', '-C', str(tree), *args], check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git('init', '-q')
            git('config', 'user.name', 'SDK fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            for name in ['Android.bp', '36/public/android.jar',
                         '35/public/android.jar', 'update_prebuilts/update_prebuilts.py']:
                target = tree / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(name)
            (tree / 'update_prebuilts.py').symlink_to('update_prebuilts/update_prebuilts.py')
            git('add', '.')
            git('commit', '-qm', 'SDK symlink fixture')
            git_dir = root / '.repo/projects/prebuilts/sdk.git'
            git_dir.parent.mkdir(parents=True)
            (tree / '.git').rename(git_dir)
            (tree / '.git').write_text('gitdir: ' + git_dir.as_posix() + '\n')
            git('config', 'core.worktree', str(tree))
            with patch('prepare_checkout.SPARSE_PREBUILTS', {'prebuilts/sdk': SPARSE_PREBUILTS['prebuilts/sdk']}):
                configure(root)
            self.assertTrue((tree / 'update_prebuilts.py').is_file())
            self.assertTrue((tree / '36/public/android.jar').is_file())
            self.assertFalse((tree / '35').exists())

    def test_clang_fetch_is_complete_while_checkout_remains_sparse(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.xml'
            manifest.write_text('<manifest>'
                '<project name="platform/prebuilts/clang/host/linux-x86" path="prebuilts/clang/host/linux-x86"/>'
                '<project name="platform/prebuilts/sdk" path="prebuilts/sdk"/>'
                '</manifest>')
            self.assertEqual(exclusions(manifest), 'platform/prebuilts/clang/host/linux-x86')
            self.assertIn('clang-r547379', SPARSE_PREBUILTS['prebuilts/clang/host/linux-x86'])
            self.assertIn('clang-r530567', SPARSE_PREBUILTS['prebuilts/clang/host/linux-x86'])

    def test_manifest_implicit_paths_do_not_break_filter_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.xml'
            manifest.write_text('<manifest><project name="kernel/configs"/>'
                                '<project name="platform/prebuilts/rust" path="prebuilts/rust"/>'
                                '<project name="platform/bionic" path="bionic"/></manifest>')
            self.assertEqual(exclusions(manifest), 'kernel/configs,platform/prebuilts/rust,platform/bionic')

    def test_git_retains_selected_nested_tools_and_omits_other_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / 'prebuilts/rust'
            tree.mkdir(parents=True)

            def git(*args):
                return subprocess.run(['git', '-C', str(tree), *args], check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            git('init', '-q')
            git('config', 'user.name', 'Checkout test')
            git('config', 'user.email', 'test@example.invalid')
            paths = ['Android.bp', 'soong/config.go', 'linux-x86/1.83.0/bin/rustc',
                     'linux-x86/stable/version.txt', 'linux-musl-x86/1.83.0/bin/rustc',
                     'linux-x86/1.82.0/bin/rustc', 'darwin-x86/1.83.0/bin/rustc']
            for name in paths:
                target = tree / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(name)
            git('add', '.')
            git('commit', '-qm', 'Tool fixture')
            git_dir = root / '.repo/projects/prebuilts/rust.git'
            git_dir.parent.mkdir(parents=True)
            (tree / '.git').rename(git_dir)
            (tree / '.git').write_text('gitdir: ' + git_dir.as_posix() + '\n')
            git('config', 'core.worktree', str(tree))
            selected = ['soong', 'linux-x86/1.83.0', 'linux-x86/stable', 'linux-musl-x86/1.83.0']
            with patch('prepare_checkout.FULL_SOURCE_PROJECTS', ()), \
                 patch('prepare_checkout.SPARSE_PREBUILTS', {'prebuilts/rust': selected}):
                configure(root)
            for name in paths[:5]:
                self.assertTrue((tree / name).is_file(), name)
            for name in paths[5:]:
                self.assertFalse((tree / name).exists(), name)


if __name__ == '__main__':
    unittest.main()
