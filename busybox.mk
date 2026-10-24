# SPDX-License-Identifier: Apache-2.0
# AERA_A16.sh installs its pinned ARM64 prebuilt before native ramdisk packing.
# Pass the resolved setting after the hook imports cached fox_env.sh values.
ifneq ($(AERA_USE_BUSYBOX_BINARY),1)
$(error This device requires AERA_USE_BUSYBOX_BINARY=1)
endif
ifneq ($(strip $(AERA_VENDOR)),)
AERA_VENDOR += AERA_USE_BUSYBOX_BINARY="$(AERA_USE_BUSYBOX_BINARY)"
endif

# core/Makefile runs this after Fox_Before_Recovery_Image and before mkbootfs.
# Resolve LOCAL_PATH now; later Android modules change its value.
BOARD_RECOVERY_IMAGE_PREPARE := /usr/bin/python3 $(LOCAL_PATH)/tools/verify_busybox.py --source vendor/recovery/prebuilt/$(TARGET_ARCH)/busybox --ramdisk $(TARGET_RECOVERY_ROOT_OUT) --fs-config $(TARGET_OUT_ETC)/fs_config_files
