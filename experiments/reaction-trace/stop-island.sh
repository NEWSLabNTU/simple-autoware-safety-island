#!/usr/bin/env bash
# Stop the traced native_sim island with SIGTERM and wait (up to 120 s) for
# its exit-time trace dump to land, before the supervisor tears anything down.
out="$1"
pid=$(pgrep -f 'build-zephyr/zephyr/zephyr.exe' | head -1)
[ -n "$pid" ] || { echo "stop-island: no island running"; exit 0; }
t0=$(date +%s.%N)
kill -TERM "$pid"
for _ in $(seq 1 240); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
echo "stop-island: island $pid exited after $(echo "$(date +%s.%N) - $t0" | bc) s; trace $(stat -c %s "$out") B"
