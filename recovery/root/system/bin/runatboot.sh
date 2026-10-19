#!/system/bin/sh
# Native AERA invokes this hook after starting its UI thread. Wait for that
# process's completed renderer initialization, rather than racing DRM setup.
recovery_pid=$(pidof recovery)
[ -n "$recovery_pid" ] || exit 1
attempt=0
while [ "$attempt" -lt 50 ]; do
    if logcat -d -b main --pid="$recovery_pid" -v brief 2>/dev/null |
            grep -q 'engine initialized'; then
        exec /system/bin/postscreenunblank.sh
    fi
    sleep 0.2
    attempt=$((attempt + 1))
done
echo 'Hotdog touch: native renderer did not become ready' >&2
exit 1
