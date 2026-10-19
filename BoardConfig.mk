# Copyright (C) 2018-2019 The LineageOS Project
# Copyright (C) 2026 KAI-Miru
# SPDX-License-Identifier: Apache-2.0
DEVICE_PATH := device/oneplus/hotdog

# Standalone recovery product: do not inherit the full SM8150 ROM tree.
TARGET_ARCH := arm64
TARGET_ARCH_VARIANT := armv8-2a
TARGET_CPU_ABI := arm64-v8a
TARGET_CPU_ABI2 :=
TARGET_CPU_VARIANT := generic
TARGET_CPU_VARIANT_RUNTIME := cortex-a76
# Recovery and its vendor services use ARM64. Avoid unused ARM32 build variants.
TARGET_2ND_ARCH :=
TARGET_2ND_ARCH_VARIANT :=
TARGET_2ND_CPU_ABI :=
TARGET_2ND_CPU_ABI2 :=
TARGET_2ND_CPU_VARIANT :=
TARGET_2ND_CPU_VARIANT_RUNTIME :=
TARGET_SUPPORTS_32_BIT_APPS := false
TARGET_SUPPORTS_64_BIT_APPS := true
TARGET_BOARD_PLATFORM := msmnile
TARGET_BOARD_PLATFORM_GPU := qcom-adreno640
TARGET_BOOTLOADER_BOARD_NAME := msmnile
TARGET_NO_BOOTLOADER := true
TARGET_USES_UEFI := true
BOARD_VENDOR := oneplus

TARGET_NO_KERNEL := false
ifeq ($(strip $(AERA_PREBUILT_KERNEL)),)
$(error Set AERA_PREBUILT_KERNEL to a compatible ARM64 Image)
endif
TARGET_PREBUILT_KERNEL := $(AERA_PREBUILT_KERNEL)
BOARD_KERNEL_IMAGE_NAME := Image
TARGET_PREBUILT_DTB := $(DEVICE_PATH)/prebuilt/dtb.img
BOARD_INCLUDE_DTB_IN_BOOTIMG := true
BOARD_INCLUDE_RECOVERY_DTBO := true
BOARD_PREBUILT_DTBOIMAGE := $(DEVICE_PATH)/prebuilt/recovery-dtbo.img
BOARD_PREBUILT_RECOVERY_DTBOIMAGE := $(DEVICE_PATH)/prebuilt/recovery-dtbo.img
BOARD_BOOT_HEADER_VERSION := 2
BOARD_KERNEL_PAGESIZE := 4096
# The bootloader's kernel/DTB/ramdisk load window is smaller than boot's
# physical partition. The supplied Image must support legacy LZMA ramdisks.
# Compress the full native ramdisk without dropping any runtime components.
BOARD_RAMDISK_USE_LZMA := true
BOARD_KERNEL_BASE := 0x00000000
BOARD_KERNEL_OFFSET := 0x00008000
BOARD_RAMDISK_OFFSET := 0x01000000
BOARD_KERNEL_SECOND_OFFSET := 0x00000000
BOARD_KERNEL_TAGS_OFFSET := 0x00000100
BOARD_DTB_OFFSET := 0x01f00000
BOARD_KERNEL_CMDLINE := console=ttyMSM0,115200n8 earlycon=msm_geni_serial,0xa90000 androidboot.hardware=qcom androidboot.console=ttyMSM0 androidboot.memcg=1 lpm_levels.sleep_disabled=1 video=vfb:640x400,bpp=32,memsize=3072000 msm_rtb.filter=0x237 service_locator.enable=1 swiotlb=2048 loop.max_part=7 androidboot.usbcontroller=a600000.dwc3 buildvariant=user
BOARD_MKBOOTIMG_ARGS += --base $(BOARD_KERNEL_BASE) --pagesize $(BOARD_KERNEL_PAGESIZE)
BOARD_MKBOOTIMG_ARGS += --kernel_offset $(BOARD_KERNEL_OFFSET) --ramdisk_offset $(BOARD_RAMDISK_OFFSET)
BOARD_MKBOOTIMG_ARGS += --second_offset $(BOARD_KERNEL_SECOND_OFFSET) --tags_offset $(BOARD_KERNEL_TAGS_OFFSET)
BOARD_MKBOOTIMG_ARGS += --dtb_offset $(BOARD_DTB_OFFSET) --header_version $(BOARD_BOOT_HEADER_VERSION)

# Dynamic A/B with dedicated, slotted recovery partitions.
BOARD_USES_RECOVERY_AS_BOOT :=
TARGET_NO_RECOVERY := false
TW_HAS_RECOVERY_PARTITION := true
BOARD_RECOVERYIMAGE_PARTITION_SIZE := 100663296
BOARD_BOOTIMAGE_PARTITION_SIZE := 100663296
BOARD_DTBOIMG_PARTITION_SIZE := 25165824
BOARD_FLASH_BLOCK_SIZE := 262144
BOARD_AVB_ENABLE := true
BOARD_AVB_RECOVERY_ADD_HASH_FOOTER_ARGS += --hash_algorithm sha256
BOARD_VENDORIMAGE_FILE_SYSTEM_TYPE := ext4
TARGET_COPY_OUT_VENDOR := vendor
TARGET_USERIMAGES_USE_EXT4 := true
TARGET_USERIMAGES_USE_F2FS := true
TARGET_USES_MKE2FS := true
BOARD_USES_METADATA_PARTITION := true
RECOVERY_SDCARD_ON_DATA := true
TARGET_RECOVERY_FSTAB := $(DEVICE_PATH)/recovery/root/system/etc/recovery.fstab

# Standard TeamWin/AERA Qualcomm decryption; no custom H.40 adapter.
BOARD_USES_QCOM_FBE_DECRYPTION := true
AERA_INCLUDE_CRYPTO := true
AERA_INCLUDE_CRYPTO_FBE := true
AERA_INCLUDE_FBE_METADATA_DECRYPT := true
AERA_USE_FSCRYPT_POLICY := 1
# prepdecrypt loads the installed system version before Keymaster starts.
PLATFORM_VERSION := 99.87.36
PLATFORM_VERSION_LAST_STABLE := $(PLATFORM_VERSION)
PLATFORM_SECURITY_PATCH := 2099-12-31
VENDOR_SECURITY_PATCH := 2099-12-31

TARGET_RECOVERY_PIXEL_FORMAT := RGBX_8888
TARGET_RECOVERY_QCOM_RTC_FIX := true
AERA_UI_ADAPTIVE_RESOLUTION := true
AERA_SCREEN_H := 2340
AERA_STATUS_H := 100
AERA_STATUS_INDENT_LEFT := 40
AERA_STATUS_INDENT_RIGHT := 40
AERA_BRIGHTNESS_PATH := "/sys/class/backlight/panel0-backlight/brightness"
AERA_MAX_BRIGHTNESS := 1023
AERA_DEFAULT_BRIGHTNESS := 200
AERA_INPUT_BLACKLIST := "hbtp_vm"
AERA_NO_SCREEN_BLANK := true
AERA_EXCLUDE_DEFAULT_USB_INIT := true
# Native AERA imports only /data and /metadata from the installed vendor fstab,
# as the working CI59 recovery does. Encryption options belong to that ROM.
AERA_SKIP_ADDITIONAL_FSTAB := false
AERA_INCLUDE_REPACKTOOLS := true
AERA_INCLUDE_FASTBOOTD := true
AERA_INCLUDE_LOGCAT := true
AERA_INCLUDE_RESETPROP := true
AERA_INCLUDE_LIBRESETPROP := true
AERA_ENABLE_WLAN := 1
BOARD_WPA_SUPPLICANT_DRIVER := NL80211
WPA_SUPPLICANT_VERSION := VER_0_8_X
AERA_EXTRA_LANGUAGES := true
TARGET_USES_LOGD := true

# Recovery uses AERA's generated policy, not the stock compiled policy.
# The reduced manifest omits unrelated ROM/test modules. Ninja still rejects
# missing dependencies used by a requested target; the image audit checks ELFs.
ALLOW_MISSING_DEPENDENCIES := true
BUILD_BROKEN_ELF_PREBUILT_PRODUCT_COPY_FILES := true
BUILD_BROKEN_DUP_RULES := true
BUILD_BROKEN_PLUGIN_VALIDATION := soong-libaosprecovery_defaults soong-libguitwrp_defaults soong-libminuitwrp_defaults soong-vold_defaults soong-aera_host_defaults
TARGET_SYSTEM_PROP += $(DEVICE_PATH)/system.prop
