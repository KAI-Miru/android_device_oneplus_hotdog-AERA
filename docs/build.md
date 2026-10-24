# Building and checking Hotdog

## Device checks

On Linux, from this tree:

```sh
python3 -m pip install -r tools/requirements.txt
python3 tools/verify_tree.py
python3 -m unittest discover -s tests -v
```

Checks cover F22 DTB/DTBO identity, all shared vendor hashes, native init and
crypto boundaries, dynamic-partition flags, recovery partition selection,
fastbootd, the matched WLAN module and the strict boot-image parser.

## Building

The original F22 kernel, boot-v2 header, compressed stock reference ramdisk,
DTB and recovery DTBO are versioned under `prebuilt/`. The matching original
F22 WLAN module is under `modules/`. Manifests pin every byte and reconstruct
the original stock recovery payload. AERA builds its own native ramdisk and header.

The **Hotdog native AERA recovery** workflow calls `ci-runner` and takes no
external Image URL, kernel checksum or kernel secret. Fresh preparation is the
default. Old CI59 checkpoints are rejected because the environment fingerprint
includes both boot and module manifests. Preserve old caches for their original
inputs; prepare a new compatible environment for F22.

For local Linux builds with Android build prerequisites and Google's repo tool:

```sh
git clone --branch ci-runner --single-branch \
  https://github.com/KAI-Miru/android_device_oneplus_hotdog-AERA.git ../hotdog-runner
python3 ../hotdog-runner/ci/assemble_inputs.py \
  --device "$PWD" --runner ../hotdog-runner --output /tmp/hotdog-build-inputs
export AERA_DEVICE_REVISION=$(git rev-parse HEAD)
export AERA_SOURCE_DIR=/path/to/dedicated/aera-source
export AERA_ARTIFACT_DIR=/path/to/artifacts
export BUILD_JOBS=4
bash /tmp/hotdog-build-inputs/ci/build.sh
```

The product is `twrp_hotdog-bp2a-eng`; its target is `recoveryimage` and its
output is `AERA-hotdog-ALPHA-recovery.img`. The source lock pins the current
miru source and its native NAS dependencies. The first build needs a fresh
source/toolchain plan; recovery source is never rewritten by build-time Python.

The final verifier checks the physical partition and strict loader window,
exact bundled F22 kernel and DTB/DTBO, complete GPU/crypto/WLAN inputs, native
fastbootd and full strong-symbol dependency closure. The runner also verifies
AVB. No feature may be removed and no bound relaxed merely to fit an image.
Construction checks do not replace device testing.

## Bundled inputs and WLAN compatibility

`python3 tools/kernel_input.py` verifies bundled input hashes, stock payload
reconstruction, native LZMA support, and the kernel/module release match.
The archive selector remains a standalone tested tool outside the build path.
The stock ramdisk is not installed or executed by AERA.

WLAN startup reads `modinfo -F vermagic` from the actual bundled module and
compares its release with the running kernel before starting radio helpers.
Normal `insmod` retains the kernel's vermagic and symbol-version checks; modules
are never force-loaded. Rebuilding with a different kernel/module pair also
requires updating the module manifest and passing the existing image/ABI audits.
