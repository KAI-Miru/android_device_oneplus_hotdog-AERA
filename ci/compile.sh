#!/usr/bin/env bash
set -eo pipefail
cd "${AERA_SOURCE_DIR:?}"
export AERA_BUILD_DEVICE=hotdog
export LC_ALL=C TZ=UTC
# Explain bootstrap cache invalidation without changing generated build rules.
# This helps verify that a prepared builder actually reuses its dependency graph.
export SOONG_UI_NINJA_ARGS="${SOONG_UI_NINJA_ARGS:-} -d explain"
# Leave headroom for the launcher, filesystem cache and compiler processes.
memory_kib=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
if (( memory_kib < 12 * 1024 * 1024 )); then
    export GOGC=${GOGC:-50} GOMEMLIMIT=${GOMEMLIMIT:-10GiB}
elif (( memory_kib < 20 * 1024 * 1024 )); then
    export GOGC=${GOGC:-50} GOMEMLIMIT=${GOMEMLIMIT:-12GiB}
fi
printf 'Host memory controls: GOGC=%s GOMEMLIMIT=%s\n' "${GOGC:-default}" "${GOMEMLIMIT:-default}"
# Android's environment scripts inspect optional, unset variables.
source build/envsetup.sh
lunch twrp_hotdog-bp2a-eng
m -j"${BUILD_JOBS:-2}" adbd recoveryimage 2>&1 | tee "${AERA_ARTIFACT_DIR:?}/build.log"
