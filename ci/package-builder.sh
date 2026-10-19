#!/usr/bin/env bash
set -euo pipefail
device_repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
# These are dedicated paths inside the compiled Docker stage, never host paths.
test "$(realpath "${AERA_SOURCE_DIR:?}")" = /aera
python3 "$device_repo/tools/prepared_snapshot.py" pack /aera /builder-archive
cp /builder-archive/manifest.json "${AERA_ARTIFACT_DIR:?}/prepared-snapshot.json"
# Drop expanded data in the layer that created it, after the snapshot is complete.
rm -rf /aera
