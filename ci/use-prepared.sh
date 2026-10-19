#!/usr/bin/env bash
set -euo pipefail
device_repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
if [[ ! -f /builder-archive/restored ]]; then
    python3 "$device_repo/tools/prepared_snapshot.py" restore /builder-archive /
fi
python3 "$device_repo/tools/verify_prepared_environment.py" "$device_repo" /aera "${AERA_ARTIFACT_DIR:?}"
export GIT_CONFIG_GLOBAL=/aera/.aera-ci.gitconfig
git config --file "$GIT_CONFIG_GLOBAL" --add safe.directory /device-tree
if [[ ! -s ${AERA_PREBUILT_KERNEL:-/device-tree/external-inputs/Image} ]]; then
    export AERA_PREBUILT_KERNEL
    AERA_PREBUILT_KERNEL=$(python3 "$device_repo/tools/retained_image.py" /aera "${AERA_KERNEL_SHA256:?}")
fi
python3 "$device_repo/tools/kernel_input.py" "$AERA_PREBUILT_KERNEL" \
    --sha256 "${AERA_KERNEL_SHA256:?}" --module-manifest "$device_repo/modules/manifest.json" \
    --report "$AERA_ARTIFACT_DIR/kernel-input.json"
echo 'Using verified prepared sources, host tools and build graph.'
export AERA_PREPARED_SOURCE=1
bash "$device_repo/ci/build.sh"
if [[ -n ${AERA_CHECKPOINT_DIR:-} ]]; then
    bash "$device_repo/ci/save-checkpoint.sh"
fi
