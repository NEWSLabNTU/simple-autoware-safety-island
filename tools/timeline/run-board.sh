#!/usr/bin/env bash
# phase8-W17: one traced takeover act with the island off the host -- the
# board (the demo) or the QEMU island (the rehearsal) -- and the timeline's
# inputs, into build/timeline/<id>/ exactly as run-native.sh writes them.
#
#   tools/timeline/run-board.sh [options] a|b|encore <run-id>
#
#   --target board|qemu   board (default): flash --elf with pyocd, the island
#                         gateway on the UART (just l3-peer), reset. qemu: boot
#                         --elf under QEMU behind the same gateway config,
#                         with a monitor socket for the readout (build it with
#                         just trace-qemu-build). Nothing is flashed.
#   --elf <zephyr.elf>    default build-board/zephyr/zephyr.elf (board),
#                         build-qemu-trace/zephyr/zephyr.elf (qemu)
#   --no-flash            board: the image on the board is --elf already
#   --dry-run             print every step, run none of them
#
# The sequence (each step prints `== <n>. <what>`):
#   1. flash --elf (board: pyocd flash -t s32k344; qemu: nothing)
#   2. the stock router on 7447 (just l3-router), unless one listens
#   3. the island's link: board, just l3-peer and then pyocd reset (the
#      gateway must listen before the reset, just/l3-demo.just); qemu, the
#      same gateway config with its island face on a unix socket, and just
#      l3-island-qemu with guestfwd into that socket and a monitor socket
#   4. wait for the island to join: a sample of /system/mrm/emergency_stop/status
#      (the operator publishes it at 30 Hz from boot, Autoware or not)
#   5. Autoware in the container (just l3-autoware), until play_launch says
#      "Startup complete"
#   6. the availability gate ($RB_GATE), the probe ($RB_PROBE)
#   7. the act ($RB_ACT, after RB_SETTLE s): tools/timeline/scenario.py run
#   8. the readout: tools/timeline/readout.py (board: pyocd over SWD;
#      qemu: the QEMU monitor) -> island.trace, wrapped
#   9. teardown: act helpers, Autoware, the link, the router if this started it
#  10. island_trace.py check, merge.py, render.py --table, the VERDICT
#
# The host side runs on rmw_zenoh_cpp, domain 10, under `env -i` with the
# L3 environment (demo/l3/container/bin/l3-env): this machine's login shell
# carries the Cyclone demo environment. The script takes the demo lock itself,
# ${XDG_RUNTIME_DIR:-/tmp}/sai-demo.lock (flock, non-blocking; SAI_DEMO_LOCK
# overrides the path), and refuses to start while another run holds it. Do not
# wrap it in `flock` on the same file: that holder would refuse this one.
#
# Env: RB_GATE (the gate command; default `scenario.py gate`, which execs the
# C++ availability_gate through gate-rt and writes build/timeline/gate.pid as
# "<pid> <count path>", phase8-W16; needs just l3-host-ws or just
# demo-host-ws), RB_PROBE,
# RB_ROUTER_TIMEOUT (90 s),
# RB_ACT (the act command, $act and $dir expanded), RB_SETTLE (15 s after
# Startup complete), RB_JOIN_TIMEOUT (120 s), RB_AW_TIMEOUT (300 s),
# RB_QEMU_SECS (900, QEMU's own bound), L3_PEER_TTY (the gateway's tty),
# L3_IMAGE (the Autoware image; default sai-l3-autoware:1.5.0-w24, W24's C++
# gate image: on this host the bare tag sai-l3-autoware:1.5.0 is still W3's
# build without W11's rmw_zenoh 0.1.10 and rclcpp patch, and sat at 63-64/68
# composables in 3 of 5 starts; `just l3-container` rebuilds the tag),
# DRIVE_SECS / OBSERVE_SECS / RESPOND_AFTER (scenario.py's), SAI_DEMO_LOCK.
#
# The board steps (1, 3 and 8) ran on the S32K344 in phase8-W8
# (docs/takeover-trace.md, section 9); W17 wrote them against the QEMU island.
set -u
# the image that starts (W24); the justfile's default tag is W3's (above)
: "${L3_IMAGE:=sai-l3-autoware:1.5.0-w24}"
export L3_IMAGE
target=board elf="" flash=1 dry=0
while [ $# -gt 0 ]; do
    case "$1" in
        --target) target="$2"; shift 2;;
        --elf) elf="$2"; shift 2;;
        --no-flash) flash=0; shift;;
        --dry-run) dry=1; shift;;
        -h|--help) sed -n '2,/^set -u/p' "$0" | sed '$d'; exit 0;;
        --*) echo "run-board: unknown option $1" >&2; exit 2;;
        *) break;;
    esac
done
act="${1:?act: a|b|encore}"
id="${2:?run id}"
case "$act" in a|b|encore) ;; *) echo "run-board: act is a, b or encore" >&2; exit 2;; esac
case "$target" in board|qemu) ;; *) echo "run-board: --target board|qemu" >&2; exit 2;; esac
cd "$(dirname "$0")/../.."
repo="$PWD"
[ -n "$elf" ] || elf=$([ "$target" = board ] && echo build-board/zephyr/zephyr.elf || echo build-qemu-trace/zephyr/zephyr.elf)
dir="build/timeline/$id"
out="$dir/island.trace"
mon="$repo/$dir/qemu-monitor.sock"
gws="$repo/$dir/gw.sock"
settle="${RB_SETTLE:-15}"
: "${RB_GATE:=python3 tools/timeline/scenario.py gate --log $dir/gate.jsonl}"
: "${RB_PROBE:=python3 tools/timeline/probe.py --out $dir/probe.jsonl}"
: "${RB_ACT:=python3 tools/timeline/scenario.py run $act --log $dir/scenario.jsonl}"
started_router=0
pids=()

step() { echo "== $*"; }
run() {  # run a foreground command, or print it under --dry-run
    if [ "$dry" = 1 ]; then echo "   [dry-run] $*"; return 0; fi
    "$@"
}
bg() {  # bg <log> <cmd...>: a background job in its own process group
    local log="$1"; shift
    if [ "$dry" = 1 ]; then echo "   [dry-run] (background, log $log) $*"; return 0; fi
    # its own session and process group, so teardown stops the whole tree
    # (just -> bash -> docker / qemu / rmw_zenohd); `l3` is exported below
    # fd 9 (the demo lock) closed: a helper that outlives teardown must not
    # keep the next run out
    setsid bash -c '"$@"' bg "$@" > "$log" 2>&1 < /dev/null 9>&- &
    pids+=($!)
    echo "   started pid $! -> $log"
}
# The host side of the demo: ROS 2 + Autoware messages, rmw_zenoh_cpp,
# domain 10, a clean environment (see the head of this file).
l3() {
    # the overlay that carries the C++ availability gate (phase8-W16), which
    # `scenario.py gate` execs: just l3-host-ws, else just demo-host-ws
    local ws="$repo/build/l3-host-ws/install"
    [ -f "$ws/setup.bash" ] || ws="$repo/demo/host_ws/install"
    [ -f "$ws/setup.bash" ] || ws=/nonexistent
    env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin:$HOME/.local/bin \
        ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-10}" L3_WS="$ws" \
        DRIVE_SECS="${DRIVE_SECS:-3}" OBSERVE_SECS="${OBSERVE_SECS:-30}" RESPOND_AFTER="${RESPOND_AFTER:-3}" \
        bash -c "cd '$repo'; source demo/l3/container/bin/l3-env >/dev/null 2>&1; $*"
}
export -f l3
export repo

wait_for() {  # wait_for <secs> <what> <cmd...>
    local secs="$1" what="$2"; shift 2
    if [ "$dry" = 1 ]; then echo "   [dry-run] wait up to ${secs} s for $what: $*"; return 0; fi
    local t0=$SECONDS
    until "$@" > /dev/null 2>&1; do
        if (( SECONDS - t0 >= secs )); then echo "   TIMEOUT after ${secs} s waiting for $what"; return 1; fi
        sleep 2
    done
    echo "   $what after $(( SECONDS - t0 )) s"
}
teardown() {
    step "9. teardown"
    [ "$dry" = 1 ] && { echo "   [dry-run] stop the act helpers, docker stop ${L3_NAME:-sai-l3}, the link, the router"; return; }
    for p in "${pids[@]}"; do kill -TERM -- "-$p" 2>/dev/null; done
    # only what this run started (its own process groups, its container):
    # never a pkill by name, another run may own a router on this host
    docker stop -t 10 "${L3_NAME:-sai-l3}" > /dev/null 2>&1
    sleep 3
    for p in "${pids[@]}"; do kill -KILL -- "-$p" 2>/dev/null; done
    rm -f "$mon" "$gws"
}

# The demo lock (phase9-W22, DX 6.7): one act at a time on this host. Held on
# fd 9 until the script exits; the holder's pid and run id are in the file.
lock="${SAI_DEMO_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/sai-demo.lock}"
if [ "$dry" = 1 ]; then
    echo "   [dry-run] take the demo lock $lock (flock -n)"
else
    exec 9<>"$lock" || { echo "run-board: cannot open the demo lock $lock" >&2; exit 1; }
    if ! flock -n 9; then
        echo "run-board: the demo lock $lock is held (by: $(cat "$lock" 2>/dev/null || echo unknown));" \
             "another act is running on this host -- wait for it, or stop it" >&2
        exit 1
    fi
    echo "pid $$ run $id act $act" > "$lock"
fi
[ "$dry" = 1 ] || { mkdir -p "$dir"; rm -f "$dir"/*.jsonl; }
[ -f "$elf" ] || { echo "run-board: no $elf"; [ "$dry" = 1 ] || exit 1; }
echo "run-board: act $act, run $id, target $target, image $elf"
if [ "$dry" = 0 ]; then
    : > "$out"
    just _trace-meta "$out" "$elf"
    { echo "target=$target"; echo "act=$act"; echo "loadavg_start=$(cut -d' ' -f1-3 /proc/loadavg)"; } >> "$out.meta"
fi
start=$SECONDS
trap 'teardown; exit 130' INT TERM

step "1. flash"
if [ "$target" = board ] && [ "$flash" = 1 ]; then
    run pyocd flash -t s32k344 "$elf" || { echo "run-board: flash failed"; exit 1; }
else
    echo "   (nothing to flash: target $target, flash=$flash)"
fi

step "2. the stock router, tcp/127.0.0.1:7447"
if ss -ltn | awk '{print $4}' | grep -qE '[:.]7447$'; then
    echo "   already listening"
else
    bg "$dir/router.log" just l3-router; started_router=1
    wait_for "${RB_ROUTER_TIMEOUT:-90}" "the router" bash -c "ss -ltn | awk '{print \$4}' | grep -qE '[:.]7447\$'" || { teardown; exit 1; }
fi

step "3. the island's link"
if [ "$target" = board ]; then
    # the gateway on the UART, then the reset (the board must be reset AFTER
    # the gateway listens; just/l3-demo.just).
    bg "$dir/l3-peer.stdout" just l3-peer "${L3_PEER_TTY:-/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0}" \
        921600 tcp/127.0.0.1:7447 7449 "$repo/$dir/l3-peer-router.log"
    wait_for 60 "the gateway on the serial line" grep -q "reached at: serial" "$dir/l3-peer-router.log" || { teardown; exit 1; }
    run pyocd reset -t s32k344
else
    # The board's topology, with a unix socket for the UART: the island
    # gateway (demo/l3/router/island-gateway.json5, its island face moved
    # from `serial` to `unixsock-stream`, so the same no-graph rule and
    # downsampling apply to it) connected to the stock router, and QEMU's
    # guestfwd piped into the gateway's socket by socat. Straight into the
    # stock router, the QEMU island (heap 102,400) took Autoware's graph and
    # died: "HEAP EXHAUSTED: request 193 bytes" in zpico_read, 7.3 s after
    # boot (run w17-qb1, first attempt).
    rm -f "$mon" "$gws"
    if [ "$dry" = 1 ]; then echo "   [dry-run] demo/l3/router/island-gateway.json5, serial -> unixsock-stream, > $dir/qemu-gateway.json5"
    else sed 's/link_protocols: \["serial"\]/link_protocols: ["unixsock-stream"]/' \
        demo/l3/router/island-gateway.json5 > "$dir/qemu-gateway.json5"; fi
    bg "$dir/qemu-gateway.log" env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c "
        source /opt/ros/humble/setup.bash
        export ZENOH_ROUTER_CONFIG_URI='$repo/$dir/qemu-gateway.json5'
        export ZENOH_CONFIG_OVERRIDE='listen/endpoints=[\"unixsock-stream/$gws\"];connect/endpoints=[\"tcp/127.0.0.1:7447\"]'
        exec /opt/ros/humble/lib/rmw_zenoh_cpp/rmw_zenohd"
    wait_for 60 "the gateway's unix socket" test -S "$gws" || { teardown; exit 1; }
    bg "$dir/island.console.log" just l3-island-qemu "$elf" 7447 "${RB_QEMU_SECS:-900}" 127.0.0.1 "$mon" \
        "cmd:socat - UNIX-CONNECT:$gws"
fi

step "4. wait for the island to join"
wait_for "${RB_JOIN_TIMEOUT:-120}" "the island's first /system/mrm/emergency_stop/status sample" \
    l3 "timeout 8 ros2 topic echo --once /system/mrm/emergency_stop/status" || { teardown; exit 1; }

step "5. Autoware (container)"
# demo/l3/README.md's trap: play_launch can sit at "N composable(s) still
# constructing"; the cure is to stop it, wait out the zenoh lease, start again.
# One retry (run w17-qb2 sat at 64/68 composables for 300 s).
aw_ok=0
for attempt in 1 2; do
    bg "$dir/autoware.log" just l3-autoware
    if wait_for "${RB_AW_TIMEOUT:-300}" "Autoware (Startup complete), attempt $attempt" \
            grep -qa "Startup complete" "$dir/autoware.log"; then aw_ok=1; break; fi
    [ "$dry" = 1 ] && { aw_ok=1; break; }
    kill -TERM -- "-${pids[-1]}" 2>/dev/null; docker stop -t 10 "${L3_NAME:-sai-l3}" > /dev/null 2>&1
    mv "$dir/autoware.log" "$dir/autoware.attempt$attempt.log"; sleep 10
done
[ "$aw_ok" = 1 ] || { teardown; exit 1; }

step "6. the gate and the probe"
bg "$dir/gate.stdout" l3 "exec $RB_GATE"
bg "$dir/probe.stdout" l3 "exec $RB_PROBE"

step "7. the act ($act), after ${settle} s"
[ "$dry" = 1 ] || sleep "$settle"
if [ "$dry" = 1 ]; then echo "   [dry-run] $RB_ACT"; rc=0; else
    l3 "$RB_ACT" 2>&1 | tee "$dir/act.log"; rc=${PIPESTATUS[0]}; fi

step "8. the readout ($target)"
if [ "$dry" = 1 ] && [ -f "$elf" ]; then
    # harmless and worth doing: resolve every address the read will use
    python3 tools/timeline/readout.py --target "$target" --elf "$elf" --out /dev/null --dry-run | sed 's/^/   /'
fi
if [ "$target" = board ]; then
    # pyocd over SWD, attach mode, the core halted for the read (about 0.2 s)
    run python3 tools/timeline/readout.py --target board --elf "$elf" --out "$out"
else
    run python3 tools/timeline/readout.py --target qemu --elf "$elf" --out "$out" --monitor "$mon"
fi
trc_read=$?

teardown
trap - INT TERM
[ "$dry" = 1 ] && { echo "run-board: --dry-run done"; exit 0; }
[ "$started_router" = 1 ] && echo "   (the router this run started is stopped)"
{ echo "loadavg_end=$(cut -d' ' -f1-3 /proc/loadavg)"; echo "wall_secs=$(( SECONDS - start ))"; } >> "$out.meta"

step "10. check, merge, analysis"
echo "== run $id ($act, $target): act exit $rc; readout exit $trc_read; trace $(stat -c %s "$out" 2>/dev/null || echo 0) B"
python3 src/safety_island_tracing/island_trace.py check "$out" > "$out.check.txt" 2>&1
grep -E "^(ok|FAIL|info) +window|trace-check" "$out.check.txt"
python3 -c 'import sys; sys.path.insert(0,"tools/timeline"); import tlcommon as tl; open(sys.argv[1],"w").write(tl.explain_text())' "$dir/explain.txt"
python3 tools/timeline/merge.py "$out" "$dir" || echo "merge failed: the plot has host events only"
python3 tools/timeline/render.py "$dir" --table | tee "$dir/table.md"
[ -f "$dir/scenario.jsonl" ] && python3 -c 'import json,sys
for l in open(sys.argv[1]):
    e = json.loads(l)
    if e["kind"] == "verdict":
        v = e["value"]
        print("VERDICT: %s %s: v at the fault %.2f m/s; %s" % ("PASS" if v["ok"] else "FAIL", e["marker"], v["v0"], v["why"]))' "$dir/scenario.jsonl"
exit $rc
