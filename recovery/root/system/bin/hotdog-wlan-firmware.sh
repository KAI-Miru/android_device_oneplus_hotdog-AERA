#!/system/bin/sh
# CI59's subsystem char devices acquire firmware references on open and
# release them on close. Init stops this process when Wi-Fi is disabled.
exec 3</dev/subsys_modem || exit 1
exec 4</dev/subsys_adsp || exit 1
trap 'exit 0' TERM INT HUP
while :; do sleep 30; done
