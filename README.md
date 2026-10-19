# AERA Recovery for OnePlus 7T Pro

Native AERA device tree for **hotdog** (HD191x), derived from our
[guacamole AERA tree](https://github.com/KAI-Miru/android_device_oneplus_guacamole-AERA).
This is an initial port; no Hotdog AERA image has been built or tested yet.

## Device layout

- ARM64-only, Snapdragon 855+ / Adreno 640.
- Dynamic A/B logical partitions and dedicated, slotted **recovery** partitions.
- Boot header v2, 4096-byte pages, and a 96 MiB recovery image.
- Native fastbootd enabled, with its userspace HAL and logical-partition support.
- No super image is generated from guessed partition geometry.
- DTB and recovery DTBO extracted from the supplied OnePlus 7T Pro F22 image.

The ramdisk, init, policy and recovery executable are built by AERA. The stock
F22 ramdisk and the old TWRP stock-first overlays are not used. Device init,
fstab, firmware helpers and the complete H.40 graphics stack live in this tree;
rendering does not depend on keeping installed vendor mounted.

## Shared inputs

All 82 proprietary files, their source manifests, the official TeamWin Qualcomm
crypto providers, and the matched CI59 WLAN module are copied unchanged from
guacamole. Recovery source is pinned directly to our
[`miru` branch](https://github.com/KAI-Miru/android_bootable_recovery/tree/miru).
No runtime recovery-source patches are applied.

Use the same external universal Miru CI59 ARM64 Image as guacamole:
`b81679da7c59d5e66968f9006c2ed5ff5181c46acee053c306e17a954914aaea`.
Its release must match the included WLAN module. Kernel binaries stay outside Git.
The F22 reference kernel is not selected for this build.

## Validation and building

See [build instructions](docs/build.md), [device notes](docs/device-notes.md),
and [sources and licensing](NOTICES.md). Device changes are on `main`; hosted
build machinery is on [`ci-runner`](https://github.com/KAI-Miru/android_device_oneplus_hotdog-AERA/tree/ci-runner).
The output is `AERA-hotdog-ALPHA-recovery.img`, not a boot-partition image.

The first Hotdog build needs fresh preparation. Guacamole compiled checkpoints
are not interchangeable with this product. The strict SM8150 loader guard is
retained, but its inherited runtime addresses still need Hotdog confirmation.
Fastbootd adds runtime content, so final size and load-window checks must pass
on the actual built image. A green build would establish construction and ABI
checks; boot, display, touch, decryption, USB, Wi-Fi, slots and fastbootd still
require device testing.
