#!/usr/bin/env bash
# phase7-W3: one reaction-trace run on native_sim.
#
#   experiments/reaction-trace/run.sh <run-id>
#
# As `just trace-demo`, with inject.py in place of the demo scenario: host
# Autoware (planning_simulator), the TRACED native_sim island, and the
# injector, under one GNU parallel supervisor that tears everything down when
# the injector exits. The injector's job stops the island itself first
# (stop-island.sh) and waits for the dump: runs r2-r4 of the first batch
# lost the whole trace when parallel's TERM,5000,KILL teardown killed the
# island inside its exit-time write. Writes build/trace/w3-<id>.trace (+ .meta, .log), the
# injector's JSONL log beside it, then runs trace-check and extract.py.
# The trace itself (~10 MB) stays under build/; its .meta and the extracted
# numbers are copied into experiments/reaction-trace/runs/.
set -u
id="${1:?run id}"
cd "$(dirname "$0")/../.."
out="build/trace/w3-$id.trace"
ev="build/trace/w3-$id.events.jsonl"
mkdir -p build/trace experiments/reaction-trace/runs
just _not-running demo/.sim.pgid sim && just _not-running demo/.island.pgid island || exit 1
rm -f tmp_sim.log tmp_island.log
: > "$out"
just _trace-meta "$out" build-zephyr/zephyr/zephyr.exe
echo "loadavg_start=$(cut -d' ' -f1-3 /proc/loadavg)" >> "$out.meta"
start=$(date +%s)
parallel --lb --halt now,done=1 --termseq TERM,5000,KILL,1000 ::: \
    "just _svc-sim" \
    "just _job-traced-island '$PWD/$out'" \
    "just _wait-sim && echo '-- settle 10 s' && sleep 10 && bash -c 'source scripts/env.sh >/dev/null 2>&1; W3_LOG=$PWD/$ev python3 experiments/reaction-trace/inject.py; rc=\$?; experiments/reaction-trace/stop-island.sh $PWD/$out; exit \$rc'" \
    2>&1 | tee "build/trace/w3-$id.run.log"
rc=${PIPESTATUS[0]}
for _ in 1 2 3 4 5 6 7 8; do pgrep -f 'build-zephyr/zephyr/zephyr.exe' >/dev/null || break; sleep 1; done
cp tmp_island.log "$out.log" 2>/dev/null || true
echo "loadavg_end=$(cut -d' ' -f1-3 /proc/loadavg)" >> "$out.meta"
echo "wall_secs=$(( $(date +%s) - start ))" >> "$out.meta"
echo "== run $id: supervisor exit $rc; trace $(stat -c %s "$out") B"
python3 src/safety_island_tracing/island_trace.py check "$out" > "$out.check.txt"; trc=$?
tail -8 "$out.check.txt"
cp "$out.meta" "$out.check.txt" experiments/reaction-trace/runs/ 2>/dev/null
python3 experiments/reaction-trace/extract.py "$out" --events "$ev" --run "$id" \
    --json "experiments/reaction-trace/runs/w3-$id.json"
exit $(( rc != 0 ? rc : trc ))
