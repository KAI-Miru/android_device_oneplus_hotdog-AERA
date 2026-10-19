#!/usr/bin/env bash
set -euo pipefail
device_repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
bash "$device_repo/ci/build.sh"
# Keep host tools, their intermediate dependencies and the build graph. Removing
# host objects would make Ninja rebuild the tools even with installed binaries.
test "$(realpath "$AERA_SOURCE_DIR")" = /aera
rm -rf /aera/out/target
# Drop native device variants while retaining host variants and common generated
# files. These are dedicated, reproducible outputs inside the verified builder.
find /aera/out/soong/.intermediates -depth -type d \
    \( -name 'android_arm_*' -o -name 'android_arm64_*' \
       -o -name 'android_*_arm_*' -o -name 'android_*_arm64_*' \) \
    -exec rm -rf -- {} +
python3 "$device_repo/tools/environment_fingerprint.py" --write /aera/.aera-prepared-environment.json
du -sh /aera /aera/out
