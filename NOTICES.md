# Sources and licensing

- Partition configuration and fstab: KAI-Miru guacamole tree,
  commit `119755d82528e4c4c9fe2bba61893a230fda318c`.
- Qualcomm decryption providers: TeamWin guacamole,
  commit `abef9b8a105c9feee847a6b4ed0903bda8ffb5f9`.
- Architecture and GPT sources: TeamWin SM8150 common,
  commit `e50e7874b52ee1f03f7ab88d86169988eb5a7141`.
- Boot-control sources: TeamWin android_hardware_qcom_bootctrl,
  commit `69f2d8d08699fdec49605c6b95fc06163952b6fa`. BSD notices remain in
  the source files and `bootctrl/NOTICE`.
- UFS userspace ioctl headers: LineageOS SM8150 UAPI definitions,
  commit `32f26bf34ddf17df8e224ae0703656b9fe0c1a8d`, retained under
  `bootctrl/include` with their original notices.
- DTB and recovery DTBO: user-supplied boot image. Sources and identities are
  recorded in `prebuilt/manifest.json`.
- Proprietary inputs: user-supplied `C15_PORT_GUAC_4G`, the matching graphics
  runtime from `7Pro_H40`, and the official TeamWin guacamole tree.
  Per-file origins and hashes are in `proprietary/manifest.json`.
- AERA sources: revisions in `sources.lock.json`, retaining their AOSP,
  TeamWin, OrangeFox, LineageOS and LVGL ancestry.

Files with an Apache-2.0 SPDX marker use that license. Existing source,
firmware and proprietary components retain their original licenses and terms.

- This Hotdog AERA tree derives from KAI-Miru guacamole AERA
  `efb8210e76adf37746b3bfa92a21992a6feb2c2c`; proprietary manifests are unchanged.
- Hotdog partition reference: KAI-Miru/android_device_oneplus_hotdog,
  `eb19fbf1379b8a2d01c8402c03c695591aafd283`.
- Hotdog DTB/DTBO: supplied OnePlus 7T Pro F22 recovery image, with exact hashes
  in `prebuilt/manifest.json`. Its stock ramdisk and kernel are not redistributed.
