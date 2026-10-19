#!/usr/bin/env bash
set -euo pipefail
inputs=$(cd -- "$(dirname -- "$0")/.." && pwd)
test "$(realpath "${AERA_SOURCE_DIR:?}")" = /aera
test "$(realpath "${AERA_CHECKPOINT_DIR:?}")" = /checkpoint
test -s /aera/out/target/product/hotdog/recovery.img
test -s /aera/out/.ninja_log
python3 "$inputs/tools/environment_fingerprint.py" --write /aera/.aera-prepared-environment.json
python3 - "$inputs" <<'PY'
import hashlib, json, os, pathlib, sys
source = pathlib.Path('/aera')
objects = [p for p in (source / 'out/soong/.intermediates').rglob('*.o')
           if any(part.startswith('android_') and '_arm64' in part for part in p.parts)]
assert objects, 'No compiled ARM64 objects to retain'
record = {'schema': 1, 'kind': 'compiled',
          'device_revision': os.environ['AERA_DEVICE_REVISION'],
          'recovery_commit': json.load(open('/artifacts/recovery-source.json'))['commit'],
          'image_sha256': hashlib.sha256((source / 'out/target/product/hotdog/recovery.img').read_bytes()).hexdigest(),
          'arm64_object_count': len(objects), 'ninja_state_retained': True,
          'device_and_source_timestamps_retained': True}
(source / '.aera-compiled-checkpoint.json').write_text(json.dumps(record, indent=2) + '\n')
pathlib.Path('/artifacts/compiled-checkpoint.json').write_text(json.dumps(record, indent=2) + '\n')
PY
python3 "$inputs/tools/prepared_snapshot.py" pack /aera /checkpoint --remove-source
cp /checkpoint/manifest.json /artifacts/compiled-checkpoint-snapshot.json
# These are fixed paths inside this disposable builder. The source and objects
# are now in the verified snapshot, outside the container's writable layer.
rm -rf /aera /builder-archive
