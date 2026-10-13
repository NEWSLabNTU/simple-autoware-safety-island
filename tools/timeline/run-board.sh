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
#   --keep-link           board: leave the island's link up after the act (the
#                         gateway, and the router if this run started it),
#                         the island joined, for a --keep-boot act; the
#                         link's process groups are kept in
#                         build/timeline/link.state (phase9-W2)
#   --keep-boot           board: the next act on the same boot, over a link
#                         a --keep-link act left up: no flash, no reset, the
#                         trace window re-armed (readout.py --rearm-only) at
#                         step 1; refused without a live kept link, or when
#                         --elf is not the image that link's run flashed.
#                         Combine with --keep-link for a third act
#   --link-down           stop a kept link (build/timeline/link.state) and exit
#   --late-join           board: the island joins after Autoware (phase9-W12):
#                         the core is held halted from step 1 until Autoware,
#                         the gate and the probe are up, then reset (step 6b)
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
#  6b. --late-join only: reset the held island now, then step 4's wait
#   7. the act ($RB_ACT, after RB_SETTLE s): tools/timeline/scenario.py run
#   8. the readout: tools/timeline/readout.py (board: pyocd over SWD;
#      qemu: the QEMU monitor) -> island.trace, wrapped; in the same halt the
#      nano-ros violation record -> violations.txt (phase9-W4)
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
# L3_IMAGE (the Autoware image; default sai-l3-autoware:1.5.0-c8, main's
# overlay with phase9-C8's diagnostic graph, built by `L3_IMAGE=... just
# l3-container`, also the justfile's default since phase9-W21; before it
# 1.5.0-w24, W24's C++ gate image, which lacks both
# C8's graph and W18's hazard relay. On this host the bare tag
# sai-l3-autoware:1.5.0 is still W3's build without W11's rmw_zenoh 0.1.10
# and rclcpp patch, and sat at 63-64/68 composables in 3 of 5 starts),
# DRIVE_SECS / OBSERVE_SECS / RESPOND_AFTER (scenario.py's), SAI_DEMO_LOCK,
# RB_HOST_WS (the host overlay; default build/l3-host-ws/install, else
# demo/host_ws/install), RB_LOAD_MAX (the 1-min load ceiling, 35),
# RB_LOAD_WAIT (how long to wait for the load to drop, 180 s), FUSER_TIMEOUT
# (10 s, the bound on `fuser` here and in just l3-peer).
#
# Preflight (phase9-U5), after the lock, before anything is flashed. Each
# failure prints one line `run-board: REFUSED <reason>` (kept in
# <dir>/run.log and <dir>/refused.txt), the SUMMARY line, and exits 3:
#   - the host overlay the gate needs exists (just l3-host-ws);
#   - the SystemModel is fresh against its inputs: the check probe.py runs at
#     its start (tlcommon.load_model), so a stale model is refused here, not
#     found after the act (u1-e1: the probe refused it, the run said PASS);
#   - no sai-l3* container is running (this run starts its own);
#   - board: `pyocd list` shows the probe (MCU-Link), and no other pyocd user
#     (the pyocd CLI, readout.py, spin_diag.py) runs on this host;
#   - board: the gateway tty exists and nothing holds it, `fuser` bounded by
#     FUSER_TIMEOUT (it took over 60 s under a filesystem walk, d12-e3);
#   - the 1-min load (phase9-C6) is at most RB_LOAD_MAX, waiting up to
#     RB_LOAD_WAIT s for it to drop.
# The load is checked again right before the act (after the settle): still
# above the ceiling after the wait, the act is refused, torn down, exit 3.
# 35 is the ceiling the section-9/10 rounds of docs/takeover-trace.md kept by
# hand on this 20-thread host; d12-b3r escalated at 189 (Autoware withdrew
# comfortable-stop availability for a sample; the island's escalation was
# correct and still reads FAIL). island.trace.meta keeps loadavg_start,
# loadavg_act (what the act ran under) and loadavg_end.
# A probe or gate already gone when the act is due: the act is refused,
# exit 3. After the act, a run whose probe or gate did not run through it
# (probe.jsonl or gate.jsonl missing or empty, STALE in their stdout, or the
# process gone before the act ended) prints `VERDICT: VOID <reason>` instead
# of the scenario's verdict (<dir>/void.txt) and exits 4.
#
# The board steps (1, 3 and 8) ran on the S32K344 in phase8-W8
# (docs/takeover-trace.md, section 9); W17 wrote them against the QEMU island.
set -u
# the image that starts; the same default as L3_IMAGE in just/l3-demo.just
: "${L3_IMAGE:=sai-l3-autoware:1.5.0-c8}"
export L3_IMAGE
target=board elf="" flash=1 dry=0 keep_link=0 keep_boot=0 link_down=0 late_join=0
while [ $# -gt 0 ]; do
    case "$1" in
        --target) target="$2"; shift 2;;
        --elf) elf="$2"; shift 2;;
        --no-flash) flash=0; shift;;
        --keep-link) keep_link=1; shift;;
        --keep-boot) keep_boot=1; flash=0; shift;;
        --link-down) link_down=1; shift;;
        --late-join) late_join=1; shift;;
        --dry-run) dry=1; shift;;
        -h|--help) sed -n '2,/^set -u/p' "$0" | sed '$d'; exit 0;;
        --*) echo "run-board: unknown option $1" >&2; exit 2;;
        *) break;;
    esac
done
# phase9-W2: the kept link's record (process groups, image, run)
linkstate="$(cd "$(dirname "$0")/../.." && pwd)/build/timeline/link.state"
link_alive() {  # the kept link's gateway is still running
    [ -f "$linkstate" ] || return 1
    local pg; pg="$(sed -n 's/^peer_pgid=//p' "$linkstate")"
    [ -n "$pg" ] && kill -0 -- "-$pg" 2>/dev/null
}
if [ "$link_down" = 1 ]; then
    [ -f "$linkstate" ] || { echo "run-board: no kept link ($linkstate)"; exit 0; }
    for k in peer_pgid router_pgid; do
        pg="$(sed -n "s/^$k=//p" "$linkstate")"
        [ -n "$pg" ] && kill -TERM -- "-$pg" 2>/dev/null && echo "run-board: stopped ${k%_pgid} (process group $pg)"
    done
    sleep 3
    for k in peer_pgid router_pgid; do
        pg="$(sed -n "s/^$k=//p" "$linkstate")"; [ -n "$pg" ] && kill -KILL -- "-$pg" 2>/dev/null
    done
    rm -f "$linkstate"; echo "run-board: the kept link is down"
    exit 0
fi
act="${1:?act: a|b|encore}"
id="${2:?run id}"
case "$act" in a|b|encore) ;; *) echo "run-board: act is a, b or encore" >&2; exit 2;; esac
case "$target" in board|qemu) ;; *) echo "run-board: --target board|qemu" >&2; exit 2;; esac
if [ "$target" != board ] && [ $((keep_link + keep_boot + late_join)) -gt 0 ]; then
    echo "run-board: --keep-link, --keep-boot and --late-join are board-only" >&2; exit 2
fi
[ "$keep_boot" = 1 ] && [ "$late_join" = 1 ] && { echo "run-board: --late-join resets the board; not with --keep-boot" >&2; exit 2; }
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
# the host overlay: RB_HOST_WS, else just l3-host-ws's, else demo-host-ws's
host_ws() {
    local ws
    if [ -n "${RB_HOST_WS:-}" ]; then ws="$RB_HOST_WS"
    else ws="$repo/build/l3-host-ws/install"; [ -f "$ws/setup.bash" ] || ws="$repo/demo/host_ws/install"; fi
    echo "$ws"; [ -f "$ws/setup.bash" ]
}
export -f host_ws
# The host side of the demo: ROS 2 + Autoware messages, rmw_zenoh_cpp,
# domain 10, a clean environment (see the head of this file).
l3() {
    # the overlay that carries the C++ availability gate (phase8-W16), which
    # `scenario.py gate` execs: just l3-host-ws, else just demo-host-ws
    local ws; ws="$(host_ws)" || ws=/nonexistent
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
# phase9-W2: the link's process groups (the gateway, the router if this run
# started it, or the ones a --keep-link run left), kept out of pids so that
# --keep-link can leave them up
peer_pg="" router_pg=""
teardown() {
    step "9. teardown"
    [ "$dry" = 1 ] && { echo "   [dry-run] stop the act helpers, docker stop ${L3_NAME:-sai-l3}," \
        "$([ "$keep_link" = 1 ] && echo "keep the link (link.state)" || echo "the link, the router")"; return; }
    local link=()
    if [ "$keep_link" = 0 ]; then
        [ -n "$peer_pg" ] && link+=("$peer_pg")
        [ -n "$router_pg" ] && link+=("$router_pg")
    fi
    for p in "${pids[@]}" "${link[@]}"; do kill -TERM -- "-$p" 2>/dev/null; done
    # only what this run started (its own process groups, its container):
    # never a pkill by name, another run may own a router on this host
    docker stop -t 10 "${L3_NAME:-sai-l3}" > /dev/null 2>&1
    sleep 3
    for p in "${pids[@]}" "${link[@]}"; do kill -KILL -- "-$p" 2>/dev/null; done
    rm -f "$mon" "$gws"
    if [ "$keep_link" = 1 ] && [ -n "$peer_pg" ] && kill -0 -- "-$peer_pg" 2>/dev/null; then
        { echo "peer_pgid=$peer_pg"; echo "router_pgid=$router_pg"; echo "elf=$(readlink -f "$elf")"
          echo "elf_sha256=$(sha256sum "$elf" | cut -d' ' -f1)"; echo "run=$id"; } > "$linkstate"
        echo "   the link is kept (gateway $peer_pg${router_pg:+, router $router_pg}): $linkstate;" \
             "next: --keep-boot, or --link-down"
    else
        [ "$keep_boot" = 1 ] && rm -f "$linkstate"
    fi
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
if [ "$dry" = 0 ]; then
    mkdir -p "$dir"
    rm -f "$dir"/*.jsonl "$dir"/{refused,void,summary}.txt
    # phase9-U5: the run keeps its own log, so a refusal is on disk even when
    # the caller did not redirect (run-diag.sh redirects into this same file)
    if [ "$(readlink -f /proc/$$/fd/1)" != "$(readlink -f "$dir/run.log")" ]; then
        exec > >(tee "$dir/run.log") 2>&1
    fi
fi
[ -f "$elf" ] || { echo "run-board: no $elf"; [ "$dry" = 1 ] || exit 1; }
echo "run-board: act $act, run $id, target $target, image $elf"
if [ "$dry" = 0 ]; then
    : > "$out"
    just _trace-meta "$out" "$elf"
    { echo "target=$target"; echo "act=$act"; echo "loadavg_start=$(cut -d' ' -f1-3 /proc/loadavg)"; } >> "$out.meta"
fi
start=$SECONDS

# ---- phase9-U5 / C6: refuse what cannot run, with one line of reason ----
load_max="${RB_LOAD_MAX:-35}"
load_wait="${RB_LOAD_WAIT:-180}"
fuser_to="${FUSER_TIMEOUT:-10}"
export FUSER_TIMEOUT="$fuser_to"
tty="${L3_PEER_TTY:-/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0}"
refuse() {  # refuse <reason>: one line, kept in refused.txt
    echo "run-board: REFUSED $*"
    [ "$dry" = 1 ] || echo "$*" > "$dir/refused.txt"
}
finish_refused() {  # the record of a refused run, then exit 3
    echo "loadavg_end=$(cut -d' ' -f1-3 /proc/loadavg)" >> "$out.meta"
    python3 tools/timeline/run_summary.py "$dir" | tee "$dir/summary.txt"
    exit 3
}
load_ok() { awk -v l="$(cut -d' ' -f1 /proc/loadavg)" -v m="$load_max" 'BEGIN { exit !(l + 0 <= m + 0) }'; }
wait_load() {  # wait_load <where>: the 1-min load at most RB_LOAD_MAX, or a refusal
    local t0=$SECONDS
    until load_ok; do
        if (( SECONDS - t0 >= load_wait )); then
            refuse "host load: 1-min load $(cut -d' ' -f1 /proc/loadavg) above RB_LOAD_MAX=$load_max $1," \
                   "still after ${load_wait} s (RB_LOAD_WAIT); busiest: $(timeout 5 top -b -n 1 -w 200 2>/dev/null | awk 'NR > 7 && NF >= 12 { print $12 " " $9 "%" }' | head -n 3 | paste -sd, -)"
            return 1
        fi
        echo "   1-min load $(cut -d' ' -f1 /proc/loadavg) above $load_max $1; waiting (up to ${load_wait} s)"
        sleep 5
    done
    echo "   1-min load $(cut -d' ' -f1 /proc/loadavg) (ceiling $load_max) $1"
}
others_pyocd() {  # pids of other pyocd users on this host, not this run's ancestors
    local anc=" " p=$$
    while [ -n "$p" ] && [ "$p" != 0 ] && [ "$p" != 1 ]; do anc+="$p "; p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' '); done
    # Only a process whose PROGRAM is pyocd, or python running one of the SWD
    # scripts, holds the probe. A shell whose command line merely names one
    # (a loop that calls readout.py) does not: matching on the whole command
    # line refused fr-b3 on the caller's own `zsh -c '... readout.py ...'`.
    pgrep -af 'pyocd|readout\.py|spin_diag\.py|violations\.py' 2>/dev/null | while read -r pid cmd; do
        case "$anc" in *" $pid "*) continue;; esac
        read -r prog arg1 _ <<< "$cmd"
        case "${prog##*/}" in
            pyocd|pyocd-*) ;;
            python|python3|python3.*)
                case "${arg1##*/}" in pyocd|readout.py|spin_diag.py|violations.py) ;; *) continue;; esac ;;
            *) continue;;
        esac
        echo "$pid ${cmd:0:80}"
    done
}
preflight() {
    step "0. preflight"
    if [ "$dry" = 1 ]; then
        echo "   [dry-run] host overlay, model freshness, no sai-l3 container, the probe free," \
             "the tty free (fuser, ${fuser_to} s bound), 1-min load <= $load_max (wait ${load_wait} s)"
        return 0
    fi
    local ws; ws="$(host_ws)" || { refuse "no host overlay: $ws/setup.bash missing -- run \`just l3-host-ws\`"; return 1; }
    echo "   host overlay $ws"
    local m
    m="$(timeout 60 python3 -c 'import sys; sys.path.insert(0, "tools/timeline"); import tlcommon as tl; tl.load_model()' 2>&1)" \
        || { refuse "${m##*$'\n'}"; return 1; }
    echo "   the model is fresh against its inputs"
    local c rc
    c="$(timeout 20 docker ps --format '{{.Names}}' 2>&1)"; rc=$?
    [ "$rc" = 0 ] || { refuse "docker ps failed or took over 20 s (exit $rc): ${c##*$'\n'}"; return 1; }
    c="$(grep -E "^(sai-l3|${L3_NAME:-sai-l3}$)" <<< "$c" | paste -sd' ' -)"
    [ -z "$c" ] || { refuse "container(s) running: $c -- another act or a leftover; \`docker stop $c\` if nothing uses it"; return 1; }
    echo "   no sai-l3 container running"
    if [ "$target" = board ]; then
        local o
        o="$(others_pyocd)"
        [ -z "$o" ] || { refuse "the probe is in use by another process: $(head -n1 <<< "$o")$( [ "$(wc -l <<< "$o")" -gt 1 ] && echo " (+$(( $(wc -l <<< "$o") - 1 )) more)")"; return 1; }
        o="$(timeout 30 pyocd list 2>&1)"; rc=$?
        [ "$rc" != 124 ] || { refuse "\`pyocd list\` took over 30 s -- is the probe wedged? replug the MCU-Link"; return 1; }
        grep -qiE 'mcu-?link|cmsis-dap' <<< "$o" || { refuse "no debug probe: \`pyocd list\` shows no MCU-Link (${o##*$'\n'})"; return 1; }
        echo "   probe: $(grep -iE 'mcu-?link|cmsis-dap' <<< "$o" | head -n1 | tr -s ' ' | cut -c1-80)"
        [ -e "$tty" ] || { refuse "the gateway tty $tty does not exist -- is the DCD-LZ cable plugged in?"; return 1; }
        local h
        h="$(timeout "$fuser_to" fuser "$tty" 2>/dev/null)"; rc=$?
        [ "$rc" != 124 ] || { refuse "fuser on $tty took over ${fuser_to} s (host /proc busy: a filesystem walk?)"; return 1; }
        if [ "$keep_boot" = 1 ]; then
            # phase9-W2: the tty is the kept gateway's, and only its
            link_alive || { refuse "no kept link ($linkstate missing or its gateway gone): run the previous act with --keep-link"; return 1; }
            local kp ks q; kp="$(sed -n 's/^peer_pgid=//p' "$linkstate")"
            ks="$(sed -n 's/^elf_sha256=//p' "$linkstate")"
            [ "$ks" = "$(sha256sum "$elf" | cut -d' ' -f1)" ] || { refuse "--elf $elf is not the image the kept link's run ($(sed -n 's/^run=//p' "$linkstate")) flashed"; return 1; }
            for q in $h; do
                [ "$(ps -o pgid= -p "$q" 2>/dev/null | tr -d ' ')" = "$kp" ] || { refuse "the gateway tty $tty is held by pid $q, not the kept gateway (process group $kp)"; return 1; }
            done
            echo "   the kept link of run $(sed -n 's/^run=//p' "$linkstate") holds the tty (gateway $kp)"
        else
            if [ -n "$h" ] && link_alive; then
                refuse "a kept link (run $(sed -n 's/^run=//p' "$linkstate")) holds the gateway tty: --keep-boot to use it, or --link-down"; return 1
            fi
            [ -z "$h" ] || { refuse "the gateway tty $tty is held by pid(s)$h"; return 1; }
            echo "   gateway tty free"
        fi
    fi
    wait_load "before flashing"
}
preflight || finish_refused
trap 'teardown; exit 130' INT TERM

step "1. flash"
if [ "$target" = board ] && [ "$flash" = 1 ]; then
    run pyocd flash -t s32k344 "$elf" || { echo "run-board: flash failed"; exit 1; }
else
    echo "   (nothing to flash: target $target, flash=$flash)"
fi
if [ "$keep_boot" = 1 ]; then
    # phase9-W2: the same boot; the trace window re-armed for this act. The
    # previous act's teardown stopped Autoware and the gate, so the re-armed
    # window opens when this act's availability stream starts.
    echo "   keep-boot: no reset; re-arming the trace window"
    if [ "$dry" = 1 ]; then echo "   [dry-run] python3 tools/timeline/readout.py --target board --elf $elf --out $out --rearm-only"
    else
        r="$(python3 tools/timeline/readout.py --target board --elf "$elf" --out "$out" --rearm-only 2>&1)"; rc=$?
        echo "$r" | sed 's/^/   /'
        [ "$rc" = 0 ] || { refuse "the trace window was not re-armed: $(tail -n1 <<< "$r")"; finish_refused; }
        echo "rearm=$(grep -o 're-arm [0-9]* at uptime [0-9]* ms' <<< "$r")" >> "$out.meta"
    fi
fi
if [ "$late_join" = 1 ]; then
    # phase9-W12: the island stays off the link until Autoware is up
    echo "   late join: the core held halted until step 6b"
    run pyocd cmd -t s32k344 -O resume_on_disconnect=false -c halt > /dev/null 2>&1 || { echo "run-board: halt failed"; exit 1; }
fi

step "2. the stock router, tcp/127.0.0.1:7447"
if [ "$keep_boot" = 1 ]; then
    router_pg="$(sed -n 's/^router_pgid=//p' "$linkstate" 2>/dev/null)"
    peer_pg="$(sed -n 's/^peer_pgid=//p' "$linkstate" 2>/dev/null)"
    echo "   the kept link's${router_pg:+ (router $router_pg)}"
fi
if ss -ltn | awk '{print $4}' | grep -qE '[:.]7447$'; then
    echo "   already listening"
else
    bg "$dir/router.log" just l3-router; started_router=1
    [ "$dry" = 1 ] || { router_pg="${pids[-1]}"; unset 'pids[-1]'; }
    wait_for "${RB_ROUTER_TIMEOUT:-90}" "the router" bash -c "ss -ltn | awk '{print \$4}' | grep -qE '[:.]7447\$'" || { teardown; exit 1; }
fi

step "3. the island's link"
if [ "$keep_boot" = 1 ]; then
    echo "   the kept gateway (process group $peer_pg), the island joined on this boot: no reset"
elif [ "$target" = board ]; then
    # the gateway on the UART, then the reset (the board must be reset AFTER
    # the gateway listens; just/l3-demo.just).
    bg "$dir/l3-peer.stdout" just l3-peer "${L3_PEER_TTY:-/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0}" \
        921600 tcp/127.0.0.1:7447 7449 "$repo/$dir/l3-peer-router.log"
    # phase9-U5: stop waiting when l3-peer itself gave up (a held tty, a slow
    # fuser) and say why, rather than a 60 s timeout and an empty directory
    if [ "$dry" = 1 ]; then echo "   [dry-run] wait up to 60 s for the gateway on the serial line"
    else
        peer=${pids[-1]} t0=$SECONDS
        peer_pg="$peer"; unset 'pids[-1]'
        until grep -qs "reached at: serial" "$dir/l3-peer-router.log"; do
            if ! kill -0 "$peer" 2>/dev/null; then
                refuse "the gateway (just l3-peer) exited: $(grep -v '^\s*$' "$dir/l3-peer.stdout" | tail -n1)"
                teardown; finish_refused
            fi
            if (( SECONDS - t0 >= 60 )); then
                refuse "the gateway did not reach the serial line in 60 s (see $dir/l3-peer.stdout)"
                teardown; finish_refused
            fi
            sleep 1
        done
        echo "   the gateway on the serial line after $(( SECONDS - t0 )) s"
    fi
    if [ "$late_join" = 1 ]; then echo "   (no reset: late join, step 6b)"
    else run pyocd reset -t s32k344; fi
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

join_island() {
    wait_for "${RB_JOIN_TIMEOUT:-120}" "the island's first /system/mrm/emergency_stop/status sample" \
        l3 "timeout 8 ros2 topic echo --once /system/mrm/emergency_stop/status" || { teardown; exit 1; }
}
step "4. wait for the island to join"
if [ "$late_join" = 1 ]; then echo "   (late join: after Autoware, step 6b)"; else join_island; fi

step "5. Autoware (container)"
# demo/l3/README.md's trap: play_launch can sit at "N composable(s) still
# constructing"; the cure is to stop it, wait out the zenoh lease, start again.
# One retry (run w17-qb2 sat at 64/68 composables for 300 s). A start that
# completes short is refused the same way (phase9-W8): w31-r07-aw6668 printed
# "Startup complete with failures ... composable 66/68 loaded" and a
# STARTUP_SUMMARY with "ok":false, and its act never engaged.
aw_ok=0
for attempt in 1 2; do
    bg "$dir/autoware.log" just l3-autoware
    if wait_for "${RB_AW_TIMEOUT:-300}" "Autoware (Startup complete), attempt $attempt" \
            grep -qa "Startup complete" "$dir/autoware.log"; then
        if ! grep -qsaE 'Startup complete with failures|"ok":false' "$dir/autoware.log"; then aw_ok=1; break; fi
        echo "   REFUSED: a short start, $(grep -aoE 'composable [0-9]+/[0-9]+ loaded' "$dir/autoware.log" | head -n1)" \
             "(\"ok\":false); stopping it"
    fi
    [ "$dry" = 1 ] && { aw_ok=1; break; }
    kill -TERM -- "-${pids[-1]}" 2>/dev/null; docker stop -t 10 "${L3_NAME:-sai-l3}" > /dev/null 2>&1
    mv "$dir/autoware.log" "$dir/autoware.attempt$attempt.log"; sleep 10
done
[ "$aw_ok" = 1 ] || { teardown; exit 1; }

step "6. the gate and the probe"
bg "$dir/gate.stdout" l3 "exec $RB_GATE"; gate_pid="${pids[*]: -1}"
bg "$dir/probe.stdout" l3 "exec $RB_PROBE"; probe_pid="${pids[*]: -1}"
if [ "$late_join" = 1 ]; then
    step "6b. the island joins late: reset"
    [ "$dry" = 1 ] || sleep 5
    [ "$dry" = 1 ] || echo "late_join_reset_mono_ns=$(python3 -c 'import time; print(time.monotonic_ns())')" >> "$out.meta"
    run pyocd reset -t s32k344
    join_island
fi

step "7. the act ($act), after ${settle} s"
[ "$dry" = 1 ] || sleep "$settle"
# phase9-C6: the act runs under the ceiling or not at all
if [ "$dry" = 1 ]; then echo "   [dry-run] 1-min load <= $load_max (wait ${load_wait} s)"
else
    wait_load "at the act" || { echo "loadavg_act=$(cut -d' ' -f1-3 /proc/loadavg)" >> "$out.meta"; teardown; finish_refused; }
    echo "loadavg_act=$(cut -d' ' -f1-3 /proc/loadavg)" >> "$out.meta"
    # phase9-U5: an act without its probe or its gate is not run at all
    # (u1-e1: the probe refused a stale model at its start, the act ran
    # and the scenario said PASS over an empty table)
    for w in probe gate; do
        p="${w}_pid"
        if ! kill -0 "${!p}" 2>/dev/null; then
            refuse "the $w exited before the act: $(grep -v '^\s*$' "$dir/$w.stdout" | tail -n1)"
            teardown; finish_refused
        fi
    done
fi
# phase9-U1: the serial counters at the act's start (attach, no halt), so the
# readout can say which overruns and bad frames fell inside the act
if [ "$target" = board ] && [ "$dry" != 1 ]; then
    python3 tools/timeline/readout.py --target board --elf "$elf" --out "$dir/serial-pre" --serial-only \
        2>&1 | sed 's/^/   /'
fi
if [ "$dry" = 1 ]; then echo "   [dry-run] $RB_ACT"; rc=0; else
    l3 "$RB_ACT" 2>&1 | tee "$dir/act.log"; rc=${PIPESTATUS[0]}; fi
# phase9-U5: were the probe and the gate still up when the act ended?
gone=""
if [ "$dry" != 1 ]; then
    kill -0 "$probe_pid" 2>/dev/null || gone+="the probe exited before the act ended; "
    kill -0 "$gate_pid" 2>/dev/null || gone+="the gate exited before the act ended; "
fi

step "8. the readout ($target)"
if [ "$dry" = 1 ] && [ -f "$elf" ]; then
    # harmless and worth doing: resolve every address the read will use
    python3 tools/timeline/readout.py --target "$target" --elf "$elf" --out /dev/null --dry-run | sed 's/^/   /'
fi
if [ "$target" = board ]; then
    # pyocd over SWD, attach mode, the core halted for the read (about 0.2 s)
    run python3 tools/timeline/readout.py --target board --elf "$elf" --out "$out" --serial-pre "$dir/serial-pre.json"
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
# phase9-U5: a run whose probe or gate did not run is VOID, whatever the
# scenario says (u1-e1 printed PASS over an empty table)
void="$gone"
for f in probe gate; do [ -s "$dir/$f.jsonl" ] || void+="$f.jsonl missing or empty; "; done
stale="$(grep -hs STALE "$dir/probe.stdout" "$dir/gate.stdout" | head -n1)"
[ -z "$stale" ] || void+="${stale}; "
void="${void%; }"
[ -z "$void" ] || echo "$void" > "$dir/void.txt"
echo "== run $id ($act, $target): act exit $rc; readout exit $trc_read; trace $(stat -c %s "$out" 2>/dev/null || echo 0) B"
python3 src/safety_island_tracing/island_trace.py check "$out" > "$out.check.txt" 2>&1
grep -E "^(ok|FAIL|info) +(window|violations)|trace-check" "$out.check.txt"
# phase9-W4: the board's own record of runtime contract violations (SWD)
[ -f "$dir/violations.txt" ] && sed 's/^/   /' "$dir/violations.txt"
python3 -c 'import sys; sys.path.insert(0,"tools/timeline"); import tlcommon as tl; open(sys.argv[1],"w").write(tl.explain_text())' "$dir/explain.txt"
python3 tools/timeline/merge.py "$out" "$dir" || echo "merge failed: the plot has host events only"
python3 tools/timeline/render.py "$dir" --table | tee "$dir/table.md"
if [ -n "$void" ]; then
    echo "VERDICT: VOID $void (the scenario's own verdict is not evidence without them)"
    [ -f "$dir/scenario.jsonl" ] && python3 -c 'import json,sys
for l in open(sys.argv[1]):
    e = json.loads(l)
    if e["kind"] == "verdict":
        print("   (the scenario said %s)" % ("PASS" if e["value"]["ok"] else "FAIL"))' "$dir/scenario.jsonl"
else
[ -f "$dir/scenario.jsonl" ] && python3 -c 'import json,sys
for l in open(sys.argv[1]):
    e = json.loads(l)
    if e["kind"] == "verdict":
        v = e["value"]
        print("VERDICT: %s %s: v at the fault %.2f m/s; %s" % ("PASS" if v["ok"] else "FAIL", e["marker"], v["v0"], v["why"]))' "$dir/scenario.jsonl"
fi
# phase9-U1: one line per run, from the files this run wrote
python3 tools/timeline/run_summary.py "$dir" | tee "$dir/summary.txt"
[ -z "$void" ] || exit 4
exit $rc
