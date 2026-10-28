#!/usr/bin/env bash
# The proof cast of the CARLA island demo (docs/design/carla-island-demo.md,
# unit C8): one act on the board with CARLA (tools/timeline/run-board.sh
# --sim carla), the dashboard (demo/carla/cast_dashboard.py) on a TurboVNC
# display, recorded with ffmpeg x11grab, and stills at the act's transitions.
#
#   demo/carla/cast.sh [run-board options] a|b|encore <run-id>
#   e.g. demo/carla/cast.sh --elf build-board/zephyr/zephyr.elf b cast-b1
#
# The display must exist: a 1920x1080 TurboVNC server of its own, e.g.
#   /opt/TurboVNC/bin/vncserver :3 -geometry 1920x1080 -xstartup <a script that runs `sleep infinity`>
# (no desktop, no window manager: the dashboard is the only window).
# CAST_DISPLAY (default :3) names it; :1, :2 and :9 are refused (other desktops on
# this host). Nothing else may draw on it while it records.
#
# Sequence: run-board.sh starts in the background (its own log, as always);
# at its step 6 the dashboard starts on the display; at step 7 (the scenario
# starts) ffmpeg records; at step 8 (the readout, after the act's verdict)
# CAST_TAIL s more (8), then ffmpeg stops (SIGINT, so the mp4 is finalized)
# and the dashboard closes. run-board.sh then finishes its teardown and
# SUMMARY as usual; this waits for it and exits with its status.
#
# Out, in CAST_DIR (default build/casts):
#   <run-id>.mp4             H.264 (h264_nvenc, CAST_CODEC to change), 30 fps, 1920x1080
#   <run-id>.events.jsonl    the dashboard's transitions, wall and sim time each
#   <run-id>.meta            the recording's wall start, the run directory
#   <run-id>-NN-<what>.png   one still per transition the act is about
#                            (ODD exit, takeover request, MRM, standstill,
#                            MANUAL), CAST_STILL_AFTER s (1.0) after it
# The act's own record is build/timeline/<run-id>/ as for any run-board act;
# with a booth image (CONFIG_ISLAND_LED) also led.txt and led_vs_trace.md (C5).
set -u
cd "$(dirname "$0")/../.."
repo="$PWD"
args=("$@")
[ $# -ge 2 ] || { sed -n '2,/^set -u/p' "$0" | sed '$d'; exit 2; }
act="${args[-2]}" id="${args[-1]}"
case "$act" in a|b|encore) ;; *) echo "cast: act is a, b or encore" >&2; exit 2;; esac
disp="${CAST_DISPLAY:-:3}"
case "$disp" in :1|:2|:9) echo "cast: $disp is not ours to record (the user's or another user's desktop)" >&2; exit 2;; esac
[ -S "/tmp/.X11-unix/X${disp#:}" ] || { echo "cast: no X server on $disp -- start one (see the head of $0)" >&2; exit 2; }
out="${CAST_DIR:-build/casts}"
mkdir -p "$out"
dir="build/timeline/$id"
xosc_default=demo/carla/scenarios/town01_island_odd.xosc
[ "$act" = a ] && xosc_default=demo/carla/scenarios/town01_island_takeover.xosc
[ "$act" = encore ] && xosc_default=demo/carla/scenarios/town01_island_encore.xosc
xosc="$(readlink -f "${RB_XOSC:-$xosc_default}")"
ws="${RB_HOST_WS:-$repo/build/l3-host-ws/install}"
rm -f "$out/$id".{mp4,events.jsonl,meta} "$out/$id"-[0-9][0-9]-*.png

tools/timeline/run-board.sh --sim carla "${args[@]}" > "$out/$id.run-board.out" 2>&1 &
rb=$!
echo "cast: run-board.sh pid $rb (log $dir/run.log, also $out/$id.run-board.out)"
dash="" ff=""
stop_all() {
    [ -n "$ff" ] && kill -INT "$ff" 2>/dev/null && wait "$ff" 2>/dev/null
    [ -n "$dash" ] && kill -TERM -- "-$dash" 2>/dev/null
    ff="" dash=""
}
trap 'stop_all; kill -INT $rb 2>/dev/null; wait $rb; exit 130' INT TERM
until_step() {  # until_step <n>: wait for run-board's "== <n>." line, or its exit
    until grep -qs "^== $1\." "$dir/run.log"; do
        kill -0 $rb 2>/dev/null || return 1
        sleep 1
    done
}
if until_step 6; then
    setsid env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin:$HOME/.local/bin DISPLAY="$disp" \
        L3_WS="$ws" ROS_DOMAIN_ID=10 QT_X11_NO_MITSHM=1 \
        bash -c "cd '$repo'; source demo/l3/container/bin/l3-env >/dev/null 2>&1; exec python3 demo/carla/cast_dashboard.py --xosc '$xosc' --log '$out/$id.events.jsonl'" \
        > "$out/$id.dashboard.log" 2>&1 < /dev/null &
    dash=$!
    echo "cast: dashboard pid $dash on $disp"
fi
if until_step 7; then
    t0=$(date +%s.%N)
    ffmpeg -nostdin -loglevel error -y -f x11grab -draw_mouse 0 -framerate 30 -video_size 1920x1080 -i "$disp" \
        -c:v "${CAST_CODEC:-h264_nvenc}" -pix_fmt yuv420p -r 30 -b:v 8M "$out/$id.mp4" \
        > "$out/$id.ffmpeg.log" 2>&1 &
    ff=$!
    { echo "wall_start=$t0"; echo "display=$disp"; echo "run_dir=$repo/$dir"; echo "act=$act"; echo "xosc=$xosc"; } > "$out/$id.meta"
    echo "cast: recording $out/$id.mp4 from $(date -d @"${t0%.*}" +%T)"
fi
if until_step 8; then sleep "${CAST_TAIL:-8}"; fi
stop_all
echo "cast: recording stopped"
wait $rb; rc=$?

# a booth image (CONFIG_ISLAND_LED): the LED record against the trace (C5)
elf=build-board/zephyr/zephyr.elf
for ((i = 0; i < ${#args[@]} - 1; i++)); do [ "${args[i]}" = --elf ] && elf="${args[i + 1]}"; done
if [ -s "$dir/island.jsonl" ] && python3 tools/timeline/led_readout.py --elf "$elf" --dry-run > /dev/null 2>&1; then
    timeout -s KILL 120 python3 tools/timeline/led_readout.py --elf "$elf" > "$dir/led.txt" 2>&1
    python3 tools/timeline/led_vs_trace.py "$dir" > "$dir/led_vs_trace.md" 2>&1
    echo "cast: $(tail -n1 "$dir/led_vs_trace.md") ($dir/led_vs_trace.md)"
fi

# stills at the transitions, CAST_STILL_AFTER s after each
if [ -s "$out/$id.mp4" ] && [ -s "$out/$id.events.jsonl" ]; then
    python3 - "$out" "$id" "${CAST_STILL_AFTER:-1.0}" <<'EOF'
import json, re, subprocess, sys
out, rid, after = sys.argv[1], sys.argv[2], float(sys.argv[3])
meta = dict(l.strip().split("=", 1) for l in open(f"{out}/{rid}.meta") if "=" in l)
t0 = float(meta["wall_start"])
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                            f"{out}/{rid}.mp4"], capture_output=True, text=True).stdout.strip() or 0)
keys = [("ODD EXIT", "odd-exit"), ("TAKEOVER REQUESTED", "takeover-request"), ("THE DRIVER TOOK OVER", "manual"),
        ("island MRM: MRM_OPERATING", "mrm-operating"), ("island MRM: MRM_SUCCEEDED", "mrm-succeeded"),
        ("STANDSTILL", "standstill")]
n, seen = 0, set()
for line in open(f"{out}/{rid}.events.jsonl"):
    e = json.loads(line)
    for k, name in keys:
        if k in e["text"] and name not in seen:
            seen.add(name)
            t = e["wall"] - t0 + after
            if 0 <= t < dur:
                n += 1
                png = f"{out}/{rid}-{n:02d}-{name}.png"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", f"{out}/{rid}.mp4",
                                "-frames:v", "1", png])
                print(f"cast: still {png} (t {t:.1f} s: {e['text']})")
EOF
fi
echo "cast: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out/$id.mp4" 2>/dev/null) s in $out/$id.mp4; run-board exit $rc"
grep -h '^SUMMARY' "$dir/summary.txt" 2>/dev/null
exit $rc
