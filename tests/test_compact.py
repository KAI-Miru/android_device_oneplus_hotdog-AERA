import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from compact_checkout import compact


class CompactTests(unittest.TestCase):
    def test_keeps_files_revision_and_tree_and_can_fetch_evicted_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'upstream'
            source.mkdir()
            def git(*args, cwd=source):
                return subprocess.check_output(['git', '-C', str(cwd), *args], stderr=subprocess.PIPE)
            git('init', '-q')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            data = bytes(range(256)) * 4096
            (source / 'binary').write_bytes(data)
            git('add', '.')
            git('commit', '-qm', 'Pinned input')
            checkout = root / 'ci/prebuilts/tool'
            checkout.parent.mkdir(parents=True)
            git('clone', '--no-local', str(source), str(checkout))
            head = git('rev-parse', 'HEAD', cwd=checkout)
            blob = git('rev-parse', 'HEAD:binary', cwd=checkout).strip()
            git_dir = root / 'ci/.repo/projects/prebuilts/tool.git'
            git_dir.parent.mkdir(parents=True)
            (checkout / '.git').rename(git_dir)
            (checkout / '.git').write_text('gitdir: ' + git_dir.as_posix() + '\n')
            git('config', 'core.worktree', str(checkout), cwd=checkout)
            self.assertGreater(compact(root / 'ci', minimum=0), 0)
            self.assertEqual(git('rev-parse', 'HEAD', cwd=checkout), head)
            self.assertIn(blob, git('ls-tree', 'HEAD', cwd=checkout))
            self.assertEqual(hashlib.sha256((checkout / 'binary').read_bytes()).digest(), hashlib.sha256(data).digest())
            self.assertEqual(git('status', '--porcelain', cwd=checkout), b'')
            self.assertEqual(git('cat-file', 'blob', blob.decode(), cwd=checkout), data)


if __name__ == '__main__':
    unittest.main()
