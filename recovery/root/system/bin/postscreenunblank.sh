#!/system/bin/sh
# CI59's OEM notifier uses 1 for UNBLANK. Atomic DRM activation alone leaves
# the S6SY761 touch controller suspended. This only notifies the live kernel.
printf '1\n' > /sys/kernel/oplus_display/notify_panel_blank
