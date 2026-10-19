# Copyright (C) 2019 The LineageOS Project
# Copyright (C) 2026 KAI-Miru
# SPDX-License-Identifier: Apache-2.0
$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit.mk)
$(call inherit-product, vendor/twrp/config/common.mk)
$(call inherit-product, device/oneplus/hotdog/device.mk)
PRODUCT_NAME := twrp_hotdog
PRODUCT_DEVICE := hotdog
PRODUCT_BRAND := OnePlus
PRODUCT_MODEL := HD1910
PRODUCT_MANUFACTURER := OnePlus
PRODUCT_RELEASE_NAME := hotdog
AERA_MAINTAINER := KAI-Miru
TARGET_OTA_ASSERT_DEVICE := hotdog,OnePlus7TPro
