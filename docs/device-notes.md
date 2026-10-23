# Hotdog device notes

## Reference and packaging

The reference TWRP tree is pinned in `config/device.json`. It describes dynamic
A/B partitions, physical slotted recovery partitions and a 96 MiB recovery
partition. The supplied F22 image independently confirms header v2 and 4096-byte
pages. Its DTB/DTBO, addresses and command line are recorded in
`prebuilt/manifest.json`. Its original ramdisk, init, SELinux policy and kernel
are not part of this tree.

This port uses the external universal CI59 Miru Image and the exact same WLAN
module as guacamole, as requested. No CI58 or stock-F22 module substitution is
allowed. Kernel identity and module release are checked before building and
against the final image.

## Native recovery runtime

The complete ramdisk comes from pinned AERA sources. The shared H.40 GPU,
official crypto, boot-control providers and WLAN userspace remain byte-identical
to guacamole. Only device identities, logical-partition fstab, dedicated recovery
packaging, native fastbootd and USB profile declarations differ in the port.
The boot-control HAL handles physical slot attributes; AERA manages logical
mappings. No custom TWRP crypto adapter or stock ramdisk overlay is used.

The fallback Data row matches F22's ext4/ICE configuration. Native additional-
fstab processing may import only Data and Metadata settings from the installed
ROM, so other supported ROMs can supply their actual encryption options. The
TWRP display flags do not override those options. Logical partitions are read-
only mount targets; native fastbootd handles writes through its own flow.

## Bounds and test status

The physical recovery limit is 100,663,296 bytes. Legacy LZMA uses a 32 MiB
dictionary and the inherited strict SM8150 kernel/BSS, DTB reservation and guard-
page check remains enabled. The loader addresses came from the guacamole port;
`config/bootloader-layout.json` marks them unverified on Hotdog rather than
claiming the supplied recovery image proves every runtime address.

Nothing has been flashed or tested on Hotdog. Existing guacamole reports do not
establish Hotdog behavior. Formatting tests use fake partitions only.

The recovery pin includes a scoped metadata-mount checkpoint query. An
unmarked boot slot alone must not put recovery userdata writes into rollback
mode: recovery has no Android boot-success commit sequence. When mounted
metadata has no pending checkpoint record, the mount keeps normal durable
writes. Active or unverifiable Android transactions retain Vold's original
decision. The device and installed-ROM checkpoint flags are retained; the fix
does not mark a slot successful, commit an OTA or edit its records. Source
validation checks the reviewed Vold and fs_mgr identities. Host tests cover
the policy and linkage; a rebuilt image still needs a retention test.
