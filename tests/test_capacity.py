import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process-group guard')
class CapacityTests(unittest.TestCase):
    def test_low_space_stops_its_child_and_preserves_command_exit_status(self):
        script = Path(__file__).resolve().parents[1] / 'ci/run-with-capacity.sh'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bin').mkdir()
            (root / 'source').mkdir()
            (root / 'artifacts').mkdir()
            commands = {
                'fallocate': '#!/bin/sh\ntouch "$3"\n',
                'free': '''#!/bin/sh
if [ "$CAPACITY_TEST_MODE" = memory ]; then
  available=1000
else
  available=100000000
fi
printf 'Mem: 200000000 100000000 100000000 0 0 %s\\n' "$available"
printf 'Swap: 100000000 100000000 %s\\n' "$available"
''',
                'df': '''#!/bin/sh
if [ "$CAPACITY_TEST_MODE" = low ]; then
  for n in $(seq 1 100); do
    [ -f "$AERA_ARTIFACT_DIR/child.pid" ] && break
    sleep 0.02
  done
  available=200000
else
  available=100000000
fi
printf 'Filesystem 1024-blocks Used Available Capacity Mounted\n'
printf 'fixture 200000000 100000000 %s 50%% /\n' "$available"
''',
            }
            for name, content in commands.items():
                target = root / 'bin' / name
                target.write_text(content)
                target.chmod(0o755)
            env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'],
                       AERA_SOURCE_DIR=str(root / 'source'),
                       AERA_ARTIFACT_DIR=str(root / 'artifacts'), CAPACITY_TEST_MODE='low')
            child = 'sleep 120 & child=$!; echo "$child" > "$AERA_ARTIFACT_DIR/child.pid"; wait "$child"'
            result = subprocess.run(['bash', str(script), 'bash', '-c', child], env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
            self.assertFalse((root / 'source/.aera-disk-reserve').exists())
            pid = (root / 'artifacts/child.pid').read_text().strip()
            state = subprocess.run(['ps', '-p', pid, '-o', 'stat='], capture_output=True, text=True).stdout.strip()
            self.assertTrue(not state or state.startswith('Z'), state)
            env['CAPACITY_TEST_MODE'] = 'memory'
            result = subprocess.run(['bash', str(script), 'bash', '-c', child], env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 76, result.stdout + result.stderr)
            self.assertFalse((root / 'source/.aera-disk-reserve').exists())
            env['CAPACITY_TEST_MODE'] = 'high'
            result = subprocess.run(['bash', str(script), 'bash', '-c', 'exit 7'], env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 7, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
