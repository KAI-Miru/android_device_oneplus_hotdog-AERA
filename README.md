# AERA Recovery for OnePlus 7T Pro

Native AERA device tree for **hotdog** (HD191x), derived from our
[guacamole AERA tree](https://github.com/KAI-Miru/android_device_oneplus_guacamole-AERA).
The bundled F22 kernel migration requires a new image build and hardware testing.

## Device layout

- ARM64-only, Snapdragon 855+ / Adreno 640.
- Dynamic A/B logical partitions and dedicated, slotted **recovery** partitions.
- Boot header v2, 4096-byte pages, and a 96 MiB recovery image.
- Native fastbootd enabled, with its userspace HAL and logical-partition support.
- No super image is generated from guessed partition geometry.
- Original F22 kernel, header, reference ramdisk, DTB and recovery DTBO are versioned as blobs.

The ramdisk, init, policy and recovery executable are built by AERA. The stock
F22 ramdisk is retained as a verified reference, and is not installed as AERA runtime. Device init,
fstab, firmware helpers and the complete H.40 graphics stack live in this tree;
rendering does not depend on keeping installed vendor mounted.

## Shared inputs

All 82 proprietary files, their source manifests, the official TeamWin Qualcomm
crypto providers are shared with guacamole. The WLAN module comes from the
original F22 vendor dump and matches the bundled F22 kernel. Recovery source is pinned directly to our
[`miru` branch](https://github.com/KAI-Miru/android_bootable_recovery/tree/miru).
No runtime recovery-source patches are applied.

Builds select `prebuilt/kernel` and check all original components against
`prebuilt/manifest.json`, including exact reconstruction of the stock payload.
No external Image, download URL, caller checksum or kernel secret is required.
AERA generates its own ramdisk and boot header; the stock ramdisk remains a reference.

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
