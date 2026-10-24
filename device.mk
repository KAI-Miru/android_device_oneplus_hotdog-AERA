# Copyright (C) 2018-2019 The LineageOS Project
# Copyright (C) 2026 KAI-Miru
# SPDX-License-Identifier: Apache-2.0
$(call inherit-product, $(SRC_TARGET_DIR)/product/base.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/emulated_storage.mk)
LOCAL_PATH := device/oneplus/hotdog
PRODUCT_PLATFORM := msmnile
PRODUCT_SHIPPING_API_LEVEL := 29
AB_OTA_UPDATER := true
AB_OTA_PARTITIONS := boot dtbo odm product recovery system system_ext vendor vbmeta vbmeta_system
PRODUCT_USE_DYNAMIC_PARTITIONS := true
PRODUCT_VIRTUAL_AB_OTA := false
PRODUCT_BUILD_SUPER_PARTITION := false
PRODUCT_BUILD_RECOVERY_IMAGE := true
PRODUCT_SOONG_NAMESPACES += $(LOCAL_PATH)
# mkbootfs reads this generated permission table from TARGET_OUT before packing.
TARGET_RECOVERY_DEVICE_MODULES += fs_config_files_system

PRODUCT_PACKAGES += \
    android.hardware.boot@1.0-impl:64 \
    android.hardware.boot@1.0-service \
    android.hardware.boot@1.1-service \
    bootctrl.msmnile \
    bootctrl.msmnile.recovery \
    qcom_decrypt \
    qcom_decrypt_fbe \
    update_engine \
    update_engine_sideload \
    update_verifier \
    resetprop \
    libion \
    libnativewindow \
    libui \
    fastbootd \
    android.hardware.fastboot@1.1-impl-mock

TARGET_RECOVERY_DEVICE_MODULES += libion libnativewindow libui hotdog_recovery_graphics \
    android.hardware.common-V2-ndk \
    android.hardware.graphics.common-V6-ndk \
    android.hardware.graphics.allocator-V2-ndk \
    android.hardware.graphics.allocator@2.0
# Native libui/libgralloctypes/libnativewindow also need these providers in
# the ramdisk; building their transitive dependencies does not stage them.
RECOVERY_LIBRARY_SOURCE_FILES += \
    $(TARGET_OUT_SHARED_LIBRARIES)/libion.so \
    $(TARGET_OUT_SHARED_LIBRARIES)/libnativewindow.so \
    $(TARGET_OUT_SHARED_LIBRARIES)/libui.so \
    $(TARGET_OUT_SHARED_LIBRARIES)/android.hardware.common-V2-ndk.so \
    $(TARGET_OUT_SHARED_LIBRARIES)/android.hardware.graphics.common-V6-ndk.so \
    $(TARGET_OUT_SHARED_LIBRARIES)/android.hardware.graphics.allocator-V2-ndk.so \
    $(TARGET_OUT_SHARED_LIBRARIES)/android.hardware.graphics.allocator@2.0.so

PRODUCT_VENDOR_PROPERTIES += ro.hardware.egl=adreno ro.hardware.gralloc=msmnile
DEVICE_MANIFEST_FILE := $(LOCAL_PATH)/manifest.xml

# All copied init files are device-specific extensions to AERA's native init.
PRODUCT_COPY_FILES += \
    system/core/libprocessgroup/profiles/task_profiles.json:$(TARGET_COPY_OUT_RECOVERY)/root/system/etc/task_profiles.json \
    system/libhidl/vintfdata/manifest.xml:$(TARGET_COPY_OUT_RECOVERY)/root/system/etc/vintf/manifest.xml \
    system/hwservicemanager/hwservicemanager.xml:$(TARGET_COPY_OUT_RECOVERY)/root/system/etc/vintf/manifest/hwservicemanager.xml \
    $(LOCAL_PATH)/recovery/root/system/etc/vintf/manifest/hotdog-boot.xml:$(TARGET_COPY_OUT_RECOVERY)/root/system/etc/vintf/manifest/hotdog-boot.xml \
    $(LOCAL_PATH)/recovery/root/init.recovery.qcom.rc:$(TARGET_COPY_OUT_RECOVERY)/root/init.recovery.qcom.rc \
    $(LOCAL_PATH)/recovery/root/init.recovery.hotdog-crypto.rc:$(TARGET_COPY_OUT_RECOVERY)/root/init.recovery.hotdog-crypto.rc \
    $(LOCAL_PATH)/recovery/root/init.recovery.wifi.rc:$(TARGET_COPY_OUT_RECOVERY)/root/init.recovery.wifi.rc \
    $(LOCAL_PATH)/recovery/root/init.recovery.usb.rc:$(TARGET_COPY_OUT_RECOVERY)/root/init.recovery.usb.rc \
    $(LOCAL_PATH)/recovery/root/ueventd.qcom.rc:$(TARGET_COPY_OUT_RECOVERY)/root/ueventd.qcom.rc \
    $(LOCAL_PATH)/recovery/root/system/etc/twrp.flags:$(TARGET_COPY_OUT_RECOVERY)/root/system/etc/twrp.flags \
    $(LOCAL_PATH)/recovery/root/system/bin/runatboot.sh:$(TARGET_COPY_OUT_RECOVERY)/root/system/bin/runatboot.sh \
    $(LOCAL_PATH)/recovery/root/system/bin/postscreenunblank.sh:$(TARGET_COPY_OUT_RECOVERY)/root/system/bin/postscreenunblank.sh \
    $(LOCAL_PATH)/recovery/root/system/bin/hotdog-wlan-firmware.sh:$(TARGET_COPY_OUT_RECOVERY)/root/system/bin/hotdog-wlan-firmware.sh \
    $(LOCAL_PATH)/recovery/root/system/bin/hotdog-wlan-domains.sh:$(TARGET_COPY_OUT_RECOVERY)/root/system/bin/hotdog-wlan-domains.sh \
    $(LOCAL_PATH)/recovery/root/system/bin/hotdog-wlan-prepare.sh:$(TARGET_COPY_OUT_RECOVERY)/root/system/bin/hotdog-wlan-prepare.sh \
    $(LOCAL_PATH)/recovery/root/system/bin/hotdog-wlan-storage.sh:$(TARGET_COPY_OUT_RECOVERY)/root/system/bin/hotdog-wlan-storage.sh \
    $(LOCAL_PATH)/recovery/root/system/bin/hotdog-wpa-supplicant.sh:$(TARGET_COPY_OUT_RECOVERY)/root/system/bin/hotdog-wpa-supplicant.sh \
    $(LOCAL_PATH)/recovery/root/system/etc/hotdog-wpa_supplicant.conf:$(TARGET_COPY_OUT_RECOVERY)/root/system/etc/hotdog-wpa_supplicant.conf \
    $(LOCAL_PATH)/modules/qca_cld3_wlan.ko:$(TARGET_COPY_OUT_RECOVERY)/root/system/lib/modules/msmnile/qca_cld3_wlan.ko \
    $(LOCAL_PATH)/recovery/root/vendor/etc/init/aera-gralloc.rc:$(TARGET_COPY_OUT_RECOVERY)/root/vendor/etc/init/aera-gralloc.rc \
    $(LOCAL_PATH)/manifest.xml:$(TARGET_COPY_OUT_RECOVERY)/root/vendor/etc/vintf/manifest.xml

include $(LOCAL_PATH)/proprietary-files.mk
