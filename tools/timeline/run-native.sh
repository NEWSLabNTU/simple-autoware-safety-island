#!/usr/bin/env bash
# phase8-W7: one traced takeover run on native_sim, with the timeline's inputs.
#
#   tools/timeline/run-native.sh a|b|encore <run-id>
#
# As experiments/reaction-trace/run.sh (phase7-W3), under one GNU parallel
# supervisor: Autoware's planning simulator with the availability converter
# renamed to /system/operation_mode/availability_raw (the demo overlay's
# `operation_mode_availability_topic` argument, phase8-W3), the TRACED
# native_sim island, the availability gate (tools/timeline/scenario.py gate),
# the contract probe, and the scripted act; the act's job stops the island
# itself first so its exit-time trace dump lands (W3's r2-r4 lesson).
# Writes build/timeline/<id>/: probe.jsonl, gate.jsonl, scenario.jsonl,
# island.jsonl (merged markers), explain.txt, island.trace(.meta, .log),
# timeline.png, and table.md.
set -u
act="${1:?act: a|b|encore}"
id="${2:?run id}"
cd "$(dirname "$0")/../.."
dir="build/timeline/$id"
out="$dir/island.trace"
mkdir -p "$dir"
rm -f "$dir"/*.jsonl
just _not-running demo/.sim.pgid sim && just _not-running demo/.island.pgid island || exit 1
rm -f tmp_sim.log tmp_island.log build/timeline/gate.pid
: > "$out"
just _trace-meta "$out" build-zephyr/zephyr/zephyr.exe
echo "loadavg_start=$(cut -d' ' -f1-3 /proc/loadavg)" >> "$out.meta"
echo "act=$act" >> "$out.meta"
start=$(date +%s)
sim='source scripts/env.sh >/dev/null 2>&1; export DISPLAY="${DISPLAY:-:1}"; ps -o pgid= -p $$ | tr -d " " > demo/.sim.pgid; exec "$(command -v play_launch)" launch autoware_launch planning_simulator.launch.xml map_path:=$PWD/demo/map/sample-map-planning vehicle_model:=sample_vehicle sensor_model:=sample_sensor_kit rviz:=false operation_mode_availability_topic:=/system/operation_mode/availability_raw > tmp_sim.log 2>&1'
py='source scripts/env.sh >/dev/null 2>&1; exec python3'
parallel --lb --halt now,done=1 --termseq TERM,5000,KILL,1000 ::: \
    "bash -c '$sim'" \
    "just _job-traced-island '$PWD/$out'" \
    "just _wait-sim >/dev/null && bash -c '$py tools/timeline/scenario.py gate --log $PWD/$dir/gate.jsonl'" \
    "just _wait-sim >/dev/null && bash -c '$py tools/timeline/probe.py --out $PWD/$dir/probe.jsonl'" \
    "just _wait-sim && echo '-- settle 15 s' && sleep 15 && bash -c 'source scripts/env.sh >/dev/null 2>&1; python3 tools/timeline/scenario.py run $act --log $PWD/$dir/scenario.jsonl; rc=\$?; experiments/reaction-trace/stop-island.sh $PWD/$out; exit \$rc'" \
    2>&1 | tee "$dir/run.log"
rc=${PIPESTATUS[0]}
for _ in 1 2 3 4 5 6 7 8; do pgrep -f 'build-zephyr/zephyr/zephyr.exe' >/dev/null || break; sleep 1; done
cp tmp_island.log "$out.log" 2>/dev/null || true
cp tmp_island.stamped.log "$out.stamped.log" 2>/dev/null || true
cp tmp_sim.log "$dir/sim.log" 2>/dev/null || true
echo "loadavg_end=$(cut -d' ' -f1-3 /proc/loadavg)" >> "$out.meta"
echo "wall_secs=$(( $(date +%s) - start ))" >> "$out.meta"
echo "== run $id ($act): supervisor exit $rc; trace $(stat -c %s "$out") B"
python3 src/safety_island_tracing/island_trace.py check "$out" > "$out.check.txt" 2>&1; trc=$?
tail -4 "$out.check.txt"
python3 -c 'import sys; sys.path.insert(0,"tools/timeline"); import tlcommon as tl; open(sys.argv[1],"w").write(tl.explain_text())' "$dir/explain.txt"
python3 tools/timeline/merge.py "$out" "$dir" || echo "merge failed: the plot has host events only"
python3 tools/timeline/render.py "$dir" --table | tee "$dir/table.md"
# GNU parallel can drop the act's last line when --halt ends the run, so the
# verdict is read back from the act's own log.
python3 -c 'import json,sys
for l in open(sys.argv[1]):
    e = json.loads(l)
    if e["kind"] == "verdict":
        v = e["value"]
        print("VERDICT: %s %s: v at the fault %.2f m/s; %s" % ("PASS" if v["ok"] else "FAIL", e["marker"], v["v0"], v["why"]))' "$dir/scenario.jsonl"
exit $rc
