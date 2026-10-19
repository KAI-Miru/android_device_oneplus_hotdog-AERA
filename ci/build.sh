#!/usr/bin/env bash
set -euo pipefail
device_repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
build_root=${AERA_SOURCE_DIR:?Set AERA_SOURCE_DIR to a dedicated source directory}
artifact_root=${AERA_ARTIFACT_DIR:?Set AERA_ARTIFACT_DIR}
jobs=${BUILD_JOBS:-2}
export AERA_PREBUILT_KERNEL=${AERA_PREBUILT_KERNEL:-$device_repo/external-inputs/Image}
python3 "$device_repo/tools/kernel_input.py" "$AERA_PREBUILT_KERNEL" \
    --module-manifest "$device_repo/modules/manifest.json"
mkdir -p "$build_root" "$artifact_root"
trap 'df -h "$build_root" | tee "$artifact_root/source-capacity.txt"' EXIT
if [[ -n ${AERA_DEVICE_REVISION:-} ]]; then
    [[ "$AERA_DEVICE_REVISION" =~ ^[0-9a-f]{40}$ ]]
    printf '%s\n' "$AERA_DEVICE_REVISION" > "$artifact_root/device-tree.txt"
else
    git -C "$device_repo" rev-parse HEAD > "$artifact_root/device-tree.txt"
fi
python3 "$device_repo/tools/verify_tree.py"
manifest_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["manifest_commit"])' "$device_repo/sources.lock.json")
aosp_revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["aosp_revision"])' "$device_repo/sources.lock.json")
# Upstream still declares SSH remotes. All pinned dependencies are public;
# HTTPS needs no user PAT or SSH key, and no token is written into the manifest.
git_config="$build_root/.aera-ci.gitconfig"
export GIT_CONFIG_GLOBAL="$git_config"
git config --file "$git_config" user.name 'AERA CI'
git config --file "$git_config" user.email 'aera-ci@users.noreply.github.com'
git config --file "$git_config" url."https://github.com/".insteadOf "ssh://git@github.com/"
git config --file "$git_config" http.lowSpeedLimit 1024
git config --file "$git_config" http.lowSpeedTime 120
cd "$build_root"
# Resume a retained checkout without keeping duplicate compressed copies of
# already checked-out source files. Pinned commits and trees remain available.
du -h --max-depth=1 "$build_root" | sort -h | tee "$artifact_root/source-footprint.txt"
python3 "$device_repo/tools/compact_checkout.py" "$build_root"
source_lock=$(sha256sum "$device_repo/sources.lock.json" "$device_repo/tools/prepare_manifest.py" "$device_repo/tools/prepare_checkout.py" "$device_repo/tools/complete_snapshot.py" | sha256sum | cut -d' ' -f1)
if [[ ${AERA_PREPARED_SOURCE:-0} == 1 ]]; then
    # The prepared verifier already checked every other source/tool input.
    # Update only the committed recovery fork and the local manifest overrides.
    python3 "$device_repo/tools/select_recovery_source.py" "$device_repo" "$build_root"
    python3 "$device_repo/tools/prepare_manifest.py" .repo/local_manifests/hotdog-pins.xml
    printf '%s\n' "$source_lock" > .aera-source-lock
elif [[ ! -f .aera-source-lock ]] || [[ $(cat .aera-source-lock) != "$source_lock" ]]; then
    repo init -u https://github.com/AERA-Recovery/android_manifest.git -b "$manifest_revision" --depth=1 --no-clone-bundle --no-use-superproject
    python3 "$device_repo/tools/prepare_manifest.py" .repo/local_manifests/hotdog-pins.xml
    repo manifest -o "$artifact_root/source-plan.xml"
    exclusions=$(python3 "$device_repo/tools/prepare_checkout.py" exclusions "$artifact_root/source-plan.xml")
    repo init -u https://github.com/AERA-Recovery/android_manifest.git -b "$manifest_revision" --depth=1 --no-clone-bundle --no-use-superproject --partial-clone --clone-filter=blob:none --partial-clone-exclude="$exclusions"
    bash "$device_repo/ci/run-with-capacity.sh" repo sync -v -n -c --force-sync --no-clone-bundle --no-tags --optimized-fetch --fail-fast --jobs-network=8
    bash "$device_repo/ci/run-with-capacity.sh" timeout --kill-after=30s 30m python3 "$device_repo/tools/prepare_checkout.py" configure "$build_root"
    checkout_status=0
    for checkout_attempt in 1 2 3 4; do
        checkout_status=0
        bash "$device_repo/ci/run-with-capacity.sh" timeout --kill-after=30s 30m repo sync -v -l -c --force-sync --fail-fast --jobs-checkout="$jobs" || checkout_status=$?
        python3 "$device_repo/tools/compact_checkout.py" "$build_root"
        (( checkout_status == 75 || checkout_status == 124 )) || break
        free_kib=$(df -Pk "$build_root" | awk 'NR==2 {print $4}')
        (( free_kib > 6 * 1024 * 1024 )) || break
    done
    if (( checkout_status == 75 )); then
        exit 75
    elif (( checkout_status == 76 )); then
        exit 76
    elif (( checkout_status != 0 )); then
        df -h "$build_root"
        du -sh .repo prebuilts
        # repo's worktree initializer hides the underlying read-tree failure.
        # Repeat affected tool checkouts directly so the Git error is visible.
        for diagnostic_project in prebuilts/clang/host/linux-x86 prebuilts/rust prebuilts/sdk; do
            if [[ "$diagnostic_project" != prebuilts/sdk ]]; then
                bash "$device_repo/ci/run-with-capacity.sh" timeout --kill-after=30s 30m python3 \
                    "$device_repo/tools/complete_snapshot.py" "$build_root" "$diagnostic_project" --require-full --revision "refs/tags/$aosp_revision"
            fi
            bash "$device_repo/ci/run-with-capacity.sh" timeout --kill-after=30s 15m git --git-dir="$build_root/.repo/projects/$diagnostic_project.git" \
                --work-tree="$build_root/$diagnostic_project" read-tree --reset -u -v HEAD
        done
        bash "$device_repo/ci/run-with-capacity.sh" timeout --kill-after=30s 30m repo sync -v -l -c --force-sync --fail-fast --jobs-checkout=1
    fi
    df -h "$build_root"
    du -sh .repo prebuilts
    printf '%s\n' "$source_lock" > .aera-source-lock
fi
mkdir -p device/oneplus/hotdog
rsync -rcp --delete --exclude='.git' --exclude='reports' --exclude='out' --exclude='__pycache__' "$device_repo/" device/oneplus/hotdog/
repo manifest -r -o "$artifact_root/source-manifest.xml"
for java8_jar in rt jce; do
    test -s "prebuilts/jdk/jdk8/linux-x86/jre/lib/$java8_jar.jar" || {
        echo "Missing pinned JDK 8 bootclasspath: $java8_jar.jar" >&2
        exit 1
    }
done
python3 "$device_repo/tools/prepare_build.py" "$build_root" "$artifact_root"
python3 "$device_repo/tools/verify_recovery_source.py" "$build_root" "$artifact_root"
recovery_revision=$(python3 -c 'import json,sys; print(next(p["commit"] for p in json.load(open(sys.argv[1]))["projects"] if p["path"] == "bootable/recovery"))' "$device_repo/sources.lock.json")
# Native version checks must be able to read original blobs without fetching
# from inside the network-isolated Android build sandbox.
bash "$device_repo/ci/run-with-capacity.sh" timeout --kill-after=30s 15m python3 \
    "$device_repo/tools/complete_snapshot.py" "$build_root" bootable/recovery --revision "$recovery_revision" --require-objects
# Hotdog builds its dedicated recovery partition as recovery.img.
bash "$device_repo/ci/run-with-capacity.sh" bash "$device_repo/ci/compile.sh"
image=out/target/product/hotdog/recovery.img
test -s "$image"
python3 "$device_repo/tools/verify_image.py" "$image" --report "$artifact_root/image-verification.json"
python3 external/avb/avbtool.py verify_image --image "$image" > "$artifact_root/avb-verification.txt"
du -h --max-depth=2 out | sort -h | tail -25 > "$artifact_root/build-footprint.txt"
cp "$image" "$artifact_root/AERA-hotdog-ALPHA-recovery.img"
cd "$artifact_root"
sha256sum AERA-hotdog-ALPHA-recovery.img > SHA256SUMS
