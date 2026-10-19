#!/usr/bin/env bash
# Run a source-sync phase in its own process group and preserve runner health.
set -euo pipefail
build_root=${AERA_SOURCE_DIR:?}
artifact_root=${AERA_ARTIFACT_DIR:?}
reserve="$build_root/.aera-disk-reserve"
exhausted="$artifact_root/capacity-exhausted"
memory_exhausted="$artifact_root/memory-exhausted"
rm -f "$exhausted" "$memory_exhausted"
fallocate -l 1G "$reserve"
setsid "$@" &
command_pid=$!
(
    tick=0
    while kill -0 "$command_pid" 2>/dev/null; do
        free_kib=$(df -Pk "$build_root" | awk 'NR==2 {print $4}')
        if (( tick % 30 == 0 )); then
            printf 'Source capacity: %s MiB available\n' "$((free_kib / 1024))"
            {
                date -u '+Resource sample: %Y-%m-%d %H:%M:%S UTC'
                free -m
                ps -eo pid,comm,rss,etime,time,pcpu --sort=-rss | head -6 || true
                printf 'Active phase process group %s:\n' "$command_pid"
                ps -eo pid,ppid,pgid,stat,wchan:25,etime,time,comm |
                    awk -v group="$command_pid" 'NR==1 || $3==group' | head -40 || true
                soong_pid=$(pgrep -n -x soong_build || true)
                if [[ -n "$soong_pid" && -r "/proc/$soong_pid/environ" ]]; then
                    printf 'Soong process %s memory controls:\n' "$soong_pid"
                    # Read only these two nonsecret controls from the running
                    # process, never dump the runner's environment.
                    tr '\0' '\n' < "/proc/$soong_pid/environ" |
                        awk '/^(GOGC|GOMEMLIMIT)=/' || true
                fi
            } | tee -a "$artifact_root/runner-resources.log"
        fi
        if (( free_kib < 4 * 1024 * 1024 )); then
            touch "$exhausted"
            kill -TERM -- "-$command_pid" 2>/dev/null || true
            break
        fi
        available_memory_kib=$(free -k | awk '$1=="Mem:" {available=$7} $1=="Swap:" {print available+$4}')
        if (( available_memory_kib < 2 * 1024 * 1024 )); then
            touch "$memory_exhausted"
            kill -TERM -- "-$command_pid" 2>/dev/null || true
            break
        fi
        tick=$((tick + 1))
        sleep 2
    done
) &
monitor_pid=$!
status=0
wait "$command_pid" || status=$?
kill "$monitor_pid" 2>/dev/null || true
wait "$monitor_pid" 2>/dev/null || true
rm -f "$reserve"
df -h "$build_root" | tee "$artifact_root/source-capacity.txt"
if [[ -f "$exhausted" ]]; then
    du -h --max-depth=1 "$build_root" 2>/dev/null | sort -h | tee "$artifact_root/source-footprint.txt" || true
    du -h --max-depth=2 "$build_root/.repo/project-objects" "$build_root/prebuilts" 2>/dev/null | sort -h | tail -35 || true
    echo 'Source sync stopped before the runner exhausted its disk.' >&2
    exit 75
fi
if [[ -f "$memory_exhausted" ]]; then
    echo 'Build phase stopped before the runner exhausted RAM and swap.' >&2
    exit 76
fi
exit "$status"
