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

The kernel is an external input. Use the same universal Miru CI59 Image as
guacamole, SHA256
`b81679da7c59d5e66968f9006c2ed5ff5181c46acee053c306e17a954914aaea`.
No kernel binary or stock F22 ramdisk is committed.

The **Hotdog native AERA recovery** workflow calls the `ci-runner` branch.
Supply the kernel's HTTPS URL and hash, and use fresh preparation for the first
Hotdog build (`use_prepared=false`). No Guacamole checkpoint is selected by
this repository. A compatible private Hotdog checkpoint can be retained after
a successful build.

For local Linux builds with Android build prerequisites and Google's repo tool:

```sh
git clone --branch ci-runner --single-branch \
  https://github.com/KAI-Miru/android_device_oneplus_hotdog-AERA.git ../hotdog-runner
python3 ../hotdog-runner/ci/assemble_inputs.py \
  --device "$PWD" --runner ../hotdog-runner --output /tmp/hotdog-build-inputs
export AERA_DEVICE_REVISION=$(git rev-parse HEAD)
export AERA_PREBUILT_KERNEL=/absolute/path/to/CI59/Image
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
exact DTB/DTBO and supplied Image, complete GPU/crypto/WLAN inputs, native
fastbootd and full strong-symbol dependency closure. The runner also verifies
AVB. No feature may be removed and no bound relaxed merely to fit an image.
Construction checks do not replace device testing.
