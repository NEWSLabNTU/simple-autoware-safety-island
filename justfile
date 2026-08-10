# Autoware Safety Island Example — task runner.
#
# Environment: `direnv allow` (see .envrc) sources ROS 2 Humble, the Autoware
# install, the nano-ros activate.sh and the play_launch overlay, and checks the
# prerequisites; without direnv, source those four by hand. Every recipe still
# sources what it needs, so it also works from a bare shell.
#
#   just setup     one-time prep (play_launch build+install, demo overlay, model)
#   just build     build the island (native)
#   just demo-all  Autoware (no MRM) + island + demo sequence, one command
#
# Prerequisites NOT installed here: ROS 2 Humble, Autoware 1.5.0, and a
# nano-ros checkout ($NANO_ROS_ROOT, default sibling ~/repos/nano-ros).
# play_launch IS installed by `just setup` (onto PATH). `just doctor` verifies.

NANO_ROS_ROOT := env("NANO_ROS_ROOT", justfile_directory() / "../nano-ros")
# Optional: a play_launch SOURCE checkout to build+install from. Unset (the
# default) means `just setup` installs the published package instead.
PLAY_LAUNCH_REPO := env("PLAY_LAUNCH_REPO", "")
BUILD_DIR := "build"
BRINGUP := "safety_island_bringup"
# RViz needs an X display; the demo box runs TurboVNC on :1 (`vncserver :1`).
VNC_DISPLAY := env("VNC_DISPLAY", ":1")
# The nano-ros SDK CycloneDDS the island builds and runs against (NOT the ROS one).
CYCLONEDDS_HOME := env("NROS_CYCLONEDDS_HOME", env("HOME") / ".nros/sdk/cyclonedds/0.10.5-nros1")
# play_launch comes from PATH (installed by `just setup`); override with
# PLAY_LAUNCH=<path> to point at a specific binary. The demo needs >= 0.8.2 —
# 0.5.x stalls on Autoware's busy composable containers and has no `resolve`.
PLAY_LAUNCH := env("PLAY_LAUNCH", "play_launch")
PLAY_LAUNCH_MIN := "0.8.2"

default:
    @just --list

# Verify the environment is usable (nros CLI, play_launch, cmake, ROS 2).
doctor:
    #!/usr/bin/env bash
    set -u
    ok=1
    command -v nros >/dev/null || { echo "MISSING: nros CLI — source $NANO_ROS_ROOT/activate.sh"; ok=0; }
    command -v cmake >/dev/null || { echo "MISSING: cmake"; ok=0; }
    command -v parallel >/dev/null || { echo "MISSING: GNU parallel (apt install parallel) — supervises demo-all"; ok=0; }
    [ -d "{{NANO_ROS_ROOT}}/cmake" ] || { echo "MISSING: NANO_ROS_ROOT ({{NANO_ROS_ROOT}}) is not a nano-ros checkout"; ok=0; }
    [ -f /opt/ros/humble/setup.bash ] || { echo "MISSING: /opt/ros/humble"; ok=0; }
    [ -f /opt/autoware/1.5.0/setup.bash ] || { echo "MISSING: /opt/autoware/1.5.0 (needed by the demo recipes)"; ok=0; }
    if ! command -v {{PLAY_LAUNCH}} >/dev/null; then
        echo "MISSING: play_launch — run: just setup   (or PLAY_LAUNCH=<path>)"; ok=0
    else
        ver="$({{PLAY_LAUNCH}} --version 2>/dev/null | awk '{print $2}')"
        echo "play_launch: $(command -v {{PLAY_LAUNCH}}) ($ver)"
        case "$ver" in 0.[0-7].*|"")
            echo "  WARNING: need >= {{PLAY_LAUNCH_MIN}} (older stalls on Autoware's composable containers, no 'resolve' verb) — run: just setup-play-launch force"; ok=0;;
        esac
    fi
    [ "$ok" = 1 ] && echo "doctor: OK (NANO_ROS_ROOT={{NANO_ROS_ROOT}}, DISPLAY={{VNC_DISPLAY}})"
    [ "$ok" = 1 ]

# Resolve the declarative system into the baked model consumed by the entry.
# Re-run after editing system.toml or any launch/*.xml.
#
# Bake system.toml + the island launch XML into config/system_model.yaml.
resolve-model:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    {{PLAY_LAUNCH}} resolve \
        src/{{BRINGUP}}/launch/safety_island.launch.xml \
        --system src/{{BRINGUP}}/system.toml \
        -o src/{{BRINGUP}}/config/system_model.yaml

# One-time workspace prep, in dependency order:
#   play_launch (source build + wheel install) -> env check -> demo overlay
#   (domain_bridge + MRM-shadowed tier4_system_launch) -> baked system model.
# Interface codegen runs at cmake-configure time, so `just build` is next.
#
# One-time workspace prep (play_launch, demo overlay, system model).
setup: setup-play-launch doctor demo-host-ws resolve-model

# Put play_launch (>= {{PLAY_LAUNCH_MIN}}) on PATH. Two sources:
#   * default          — pip install the published package
#   * PLAY_LAUNCH_REPO — a source checkout: build it (colcon + interception +
#                        wheel) and install THAT wheel, so PATH carries exactly
#                        the binary you built
# No-op when PATH already has a new enough one; `just setup-play-launch force`
# reinstalls regardless.
#
# Install play_launch onto PATH.
setup-play-launch force="":
    #!/usr/bin/env bash
    set -e
    if [ -z "{{force}}" ] && command -v {{PLAY_LAUNCH}} >/dev/null; then
        ver="$({{PLAY_LAUNCH}} --version 2>/dev/null | awk '{print $2}')"
        case "$ver" in 0.[0-7].*|"") ;; *) echo "play_launch $ver already on PATH ($(command -v {{PLAY_LAUNCH}}))"; exit 0;; esac
    fi
    if [ -n "{{PLAY_LAUNCH_REPO}}" ]; then
        [ -d "{{PLAY_LAUNCH_REPO}}" ] || { echo "PLAY_LAUNCH_REPO={{PLAY_LAUNCH_REPO}} does not exist"; exit 1; }
        echo "-- building play_launch from source: {{PLAY_LAUNCH_REPO}}"
        source /opt/ros/humble/setup.bash
        ( cd "{{PLAY_LAUNCH_REPO}}" && just build )
        pip install --force-reinstall --no-deps "{{PLAY_LAUNCH_REPO}}"/dist/*.whl
    else
        echo "-- installing play_launch (>= {{PLAY_LAUNCH_MIN}}) from the package index"
        pip install --upgrade "play_launch>={{PLAY_LAUNCH_MIN}}"
    fi
    command -v play_launch >/dev/null || { echo "play_launch still not on PATH — is ~/.local/bin in PATH?"; exit 1; }
    echo "play_launch: $(command -v play_launch) ($(play_launch --version 2>/dev/null))"

# Install play_launch's own build deps (colcon-cargo-ros2, rosdep packages) —
# only needed when building it from a source checkout. Interactive.
#
# Install play_launch's build dependencies (source builds only).
setup-deps:
    #!/usr/bin/env bash
    set -e
    [ -n "{{PLAY_LAUNCH_REPO}}" ] || { echo "set PLAY_LAUNCH_REPO=<play_launch checkout> first (only needed for source builds)"; exit 1; }
    cd "{{PLAY_LAUNCH_REPO}}" && just install-deps

# Native build (fast dev loop).
# NROS_EXECUTOR_MAX_CBS: compile-time executor callback-slot count (nros-node
# build.rs env knob, default 4); NROS_CYCLONEDDS_MAX_TYPES: cyclone type-registry
# capacity (default 32 — the island vendors ~35+ msg types). Both compile-time;
# clean-rebuild after changing. The island registers ~9 entries
# (subs + services + timers) + the handler ~10 more; 32 gives headroom.
# CycloneDDS_DIR is PINNED to the nano-ros SDK build: with a ROS env sourced
# (which .envrc does) find_package would otherwise pick /opt/ros/humble's
# Cyclone, and the island links against the SDK one at runtime anyway.
#
# Build the island for the native board.
build:
    env NROS_EXECUTOR_MAX_CBS=32 cmake -S . -B {{BUILD_DIR}} -DNANO_ROS_ROOT={{NANO_ROS_ROOT}} \
        -DCycloneDDS_DIR={{CYCLONEDDS_HOME}}/lib/cmake/CycloneDDS
    env NROS_EXECUTOR_MAX_CBS=32 cmake --build {{BUILD_DIR}} -j

# Boot the island on the native board (demo domain, pinned cyclonedds — a
# sourced ROS env otherwise shadows the SDK lib → SIGSEGV; porting-notes env).
#
# Build and boot the island on the native board (foreground).
run: build
    env LD_LIBRARY_PATH="{{CYCLONEDDS_HOME}}/lib" \
        ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-10}" \
        ./{{BUILD_DIR}}/src/native_entry/native_entry

# Build the vendored msg pkgs as a host colcon overlay so ros2 CLI tools can
# echo/call the island's typed topics (also proves the pkgs build verbatim).
#
# Build the vendored msg pkgs as a host colcon overlay.
host-msgs:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    mkdir -p tmp/host_msgs_ws/src && cd tmp/host_msgs_ws/src
    ln -sfn ../../../src/autoware_common_msgs ../../../src/autoware_control_msgs ../../../src/tier4_system_msgs .
    cd .. && colcon build --symlink-install
    echo "source tmp/host_msgs_ws/install/setup.bash + RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=$ROS_DOMAIN_ID"

# Remove the native build tree.
clean:
    rm -rf {{BUILD_DIR}}

# ── Zephyr (phase 4) ────────────────────────────────────────────────────────
# native_sim first; QEMU board bring-up is a follow-up item.

# Build the island as a Zephyr native_sim image.
zephyr-build:
    #!/usr/bin/env bash
    set -e
    source {{NANO_ROS_ROOT}}/zephyr-workspace/env.sh > /dev/null
    export NROS_EXECUTOR_MAX_CBS=32 NROS_INTERFACE_SEARCH_PATH=$PWD/src
    west build -b native_sim/native/64 -d build-zephyr src/zephyr_entry -- \
        -DCONF_FILE="prj.conf;prj-cyclonedds.conf" -DCMAKE_PREFIX_PATH=$NANO_ROS_ROOT

# Run the Zephyr island (domain 2 baked; host side: `just host-env`).
zephyr-run:
    ./build-zephyr/zephyr/zephyr.exe

# ══ THE DEMO — blocking recipes ═════════════════════════════════════════════
# Three parts, one terminal each. Every recipe BLOCKS on its services and
# tears its whole process tree down when it exits or is Ctrl-C'd — there are
# no detached -up/-down pairs to leak orphans:
#
#   1. just autoware         Autoware planning_simulator, demo domain, stock MRM
#                            DISABLED (demo/host_ws shadows tier4_system_launch)
#   2. just island           safety island, directly on Autoware's domain
#   3. just demo             drive → fault the heartbeat → island MRM stop →
#                            heartbeat revives → vehicle resumes → VERDICT
#
# All three, one command:  just demo-all   (exits with the VERDICT)
# Crash cleanup:           just demo-down  (kills recorded groups + sweeps)
#
# Each service is a foreground `_svc-*` wrapper that records its own PROCESS
# GROUP (the scenario SIGSTOPs the bridge groups to inject the heartbeat
# fault; demo-down uses the files after a crash). The blocking recipes run
# the wrappers under a GNU parallel supervisor: --termseq TERM→KILL on
# exit or Ctrl-C, so nothing outlives its recipe.

TERMSEQ := "TERM,5000,KILL,1000"

# ── 1. Autoware (no MRM) ────────────────────────────────────────────────────
# planning_simulator via play_launch >= {{PLAY_LAUNCH_MIN}} (40s bring-up,
# 0.5.x stalls on the busy composable containers). RViz renders on the VNC
# display ({{VNC_DISPLAY}}). Blocks; prints readiness; Ctrl-C stops the
# whole sim tree.
#
# 1. Autoware planning_simulator, stock MRM disabled (blocks; Ctrl-C stops).
autoware: (_not-running "demo/.sim.pgid" "sim") _sim-prereq-check
    #!/usr/bin/env bash
    rm -f tmp_sim.log
    exec parallel --lb --halt now,fail=1 --termseq {{TERMSEQ}} ::: \
        "just _svc-sim" \
        "just _wait-sim && echo '== autoware up (stock MRM off) — Ctrl-C stops it =='"

[private]
_sim-prereq-check:
    @[ -f demo/host_ws/install/setup.bash ] || { echo "demo/host_ws not built — run: just demo-host-ws"; exit 1; }
    @command -v {{PLAY_LAUNCH}} >/dev/null || { echo "no play_launch on PATH — run: just setup"; exit 1; }

# Foreground sim service (single source — `autoware` supervises it,
# demo-all reuses it). Env (ROS + Autoware + overlay + domain/rmw/cyclone
# config) comes from .envrc — `direnv allow` once.
[private]
_svc-sim:
    #!/usr/bin/env bash
    set -e
    PL="$(command -v {{PLAY_LAUNCH}})"
    export DISPLAY="${DISPLAY:-{{VNC_DISPLAY}}}"
    ps -o pgid= -p $$ | tr -d ' ' > demo/.sim.pgid
    echo "launching Autoware with $PL ($("$PL" --version 2>/dev/null)) on DISPLAY=$DISPLAY (log tmp_sim.log)"
    exec "$PL" launch autoware_launch planning_simulator.launch.xml map_path:=$PWD/demo/map/sample-map-planning vehicle_model:=sample_vehicle sensor_model:=sample_sensor_kit rviz:=true > tmp_sim.log 2>&1

# Block until the simulator reports readiness (Startup complete).
[private]
_wait-sim timeout="300":
    #!/usr/bin/env bash
    set -e
    echo "-- waiting for the sim (Startup complete), up to {{timeout}}s..."
    for _ in $(seq 1 $(( {{timeout}} / 5 ))); do
        if grep -qa "Startup complete" tmp_sim.log 2>/dev/null; then
            grep -a "Startup complete" tmp_sim.log | tail -1 | sed 's/\x1b\[[0-9;]*m//g' | grep -o "Startup complete.*"
            exit 0
        fi
        sleep 5
    done
    echo "TIMEOUT: no 'Startup complete' in tmp_sim.log after {{timeout}}s"; exit 1

# ── 2. Safety island — DIRECT connection ────────────────────────────────────
# The island sits on Autoware's own domain (10; see .envrc); no bridges, no relay.
# Discovery: the native_sim island is multicast-OFF (NSOS breaks cyclone's
# multicast waitset — nano-ros phase 180) and peer-scans 127.0.0.1 for
# participant indices 0..120; every host-side participant runs with
# demo/cyclonedds.xml (auto index, range 120) so the scan finds them.
#   just island            # zephyr native_sim image (default)
#   just island native     # native_entry build
#
# 2. Safety island, directly on the demo domain (blocks; Ctrl-C stops it).
island target="zephyr": (_not-running "demo/.island.pgid" "island") (_island-image-check target)
    #!/usr/bin/env bash
    rm -f tmp_island.log
    exec parallel --lb --halt now,fail=1 --termseq {{TERMSEQ}} ::: \
        "just _svc-island {{target}}" \
        "sleep 10 && echo '== island up ({{target}}, demo domain, direct) — Ctrl-C stops it =='"

# Refuse to double-start a service: a second copy orphans the first one's
# process group (the pgid file is overwritten) and the port/participant
# collision cyclone-aborts the island. Stale pgid files are cleaned up.
[private]
_not-running file label:
    #!/usr/bin/env bash
    pg=$(cat {{file}} 2>/dev/null) || exit 0
    if kill -0 -- -"$pg" 2>/dev/null; then
        echo "{{label}} already running (pgid $pg) — 'just demo-down' first"; exit 1
    fi
    rm -f {{file}}

[private]
_island-image-check target:
    #!/usr/bin/env bash
    if [ "{{target}}" = "zephyr" ]; then
        [ -x ./build-zephyr/zephyr/zephyr.exe ] || { echo "no zephyr image — run: just zephyr-build"; exit 1; }
    else
        [ -x ./{{BUILD_DIR}}/src/native_entry/native_entry ] || { echo "no native image — run: just build"; exit 1; }
    fi

# Foreground island service (single source — `island` supervises it,
# demo-all reuses it). Records its process group.
[private]
_svc-island target="zephyr":
    #!/usr/bin/env bash
    set -e
    ps -o pgid= -p $$ | tr -d ' ' > demo/.island.pgid
    if [ "{{target}}" = "zephyr" ]; then
        exec ./build-zephyr/zephyr/zephyr.exe > tmp_island.log 2>&1
    else
        exec env LD_LIBRARY_PATH="{{CYCLONEDDS_HOME}}/lib" \
            ./{{BUILD_DIR}}/src/native_entry/native_entry > tmp_island.log 2>&1
    fi

# The zephyr island's cyclone profile is COMPILE-TIME: env CYCLONEDDS_URI
# never reaches zephyr.exe (native_sim getenv sees no host environment —
# nano-ros issue 0367). It is baked via CONFIG_NROS_CYCLONE_CONFIG_XML in
# src/zephyr_entry/prj-cyclonedds.conf; edit there + `just zephyr-build`.

# ── 3. Demo sequence ────────────────────────────────────────────────────────
# The full driving sequence (pure rclpy — the ros2-CLI daemon is unreliable
# under heavy graphs): init pose -> goal -> engage -> drive -> fault ->
# island MRM stop -> heartbeat revives -> resume -> VERDICT (exit 0 = PASS).
# Waits for the sim + lets the island settle first, so it works standalone
# against `just autoware` + `just island` in other terminals.
#
# 3. Run the demo sequence -> VERDICT (needs autoware + island running).
demo:
    #!/usr/bin/env bash
    set -e
    just _wait-sim
    echo "-- letting the island settle (latched inputs)..."
    sleep 10
    exec just _scenario

# The raw sequence, no readiness gating (env from .envrc).
[private]
_scenario:
    exec python3 demo/scenario_driver.py

# ── All of it, one command ──────────────────────────────────────────────────
#   just demo-all              # zephyr island (default)
#   just demo-all native       # native island
#
# One GNU parallel supervisor runs every service plus the scenario as the
# finishing job: when the scenario prints its VERDICT, parallel tears every
# service group down and exits with the scenario's status. Ctrl-C mid-run
# tears everything down too.
#
# Autoware + island + demo sequence, one command; exits with the VERDICT.
demo-all island="zephyr": (_not-running "demo/.sim.pgid" "sim") (_not-running "demo/.island.pgid" "island") _sim-prereq-check (_island-image-check island)
    #!/usr/bin/env bash
    rm -f tmp_sim.log tmp_island.log
    exec parallel --lb --halt now,done=1 --termseq {{TERMSEQ}} ::: \
        "just _svc-sim" \
        "just _job-island {{island}}" \
        "just demo"

# demo-all's island job: boot AFTER the sim is up — an island booting into
# ~40 sim participants binding lo ports simultaneously cyclone-aborts.
[private]
_job-island island:
    #!/usr/bin/env bash
    set -e
    just _wait-sim > /dev/null
    exec just _svc-island {{island}}

# ── Crash cleanup ───────────────────────────────────────────────────────────
# Normal teardown is just Ctrl-C / recipe exit. After a crashed or killed
# supervisor: kill the recorded groups, then sweep pattern-matched orphans
# whose pgid file was overwritten by a double-start.
#
# Crash cleanup: kill recorded groups + sweep orphans.
demo-down: (_kill-group "demo/.island.pgid") (_kill-group "demo/.sim.pgid") _sweep-orphans

# Kill a recorded process group: TERM, up to 3 s to exit, then KILL.
# NOTE bash, not the default sh — dash's `kill -TERM -- -pgid` fails
# silently, which is exactly how orphans piled up before.
[private]
_kill-group file:
    #!/usr/bin/env bash
    pg=$(cat {{file}} 2>/dev/null) || exit 0
    kill -TERM -- -"$pg" 2>/dev/null
    for _ in 1 2 3; do kill -0 -- -"$pg" 2>/dev/null || break; sleep 1; done
    kill -KILL -- -"$pg" 2>/dev/null
    rm -f {{file}}
    echo "killed group $pg ({{file}})"

# Kill demo processes that outlived their pgid file.
#
# The discriminator is CYCLONEDDS_URI in /proc/<pid>/environ, not the command
# name. Name patterns cannot do this job: play_launch spawns each Autoware node
# under its own binary, so a live sim is ~110 processes across ~35 distinct
# names (68 `component_node`, plus `converter_node`, `relay`,
# `shape_estimation`, `autoware_*` ...). The old pattern list matched only the
# top-level `play_launch` invocation, so every node it had spawned survived —
# 220 of them accumulated over one afternoon's runs, and the pileup then made
# the next `just autoware` half-start (20/33 nodes, 0/13 containers), which
# reads as a regression in whatever you changed last (nano-ros issue 0371).
#
# CYCLONEDDS_URI is the right key because .envrc points it at an ABSOLUTE path
# inside this checkout and every demo participant inherits it, so the sweep is
# scoped to this repo's demo: a second checkout, another play_launch project,
# and any unrelated ROS process on the box are all untouched. Prefer the value
# this recipe itself inherited (that is literally what the children got);
# fall back to computing it for a bare shell with no direnv.
[private]
_sweep-orphans:
    #!/usr/bin/env bash
    uri="CYCLONEDDS_URI=${CYCLONEDDS_URI:-file://{{justfile_directory()}}/demo/cyclonedds.xml}"

    # demo-down runs inside that same env, so never kill self or an ancestor.
    keep=" $$ "
    p=$$
    while :; do
        p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
        [ -n "$p" ] && [ "$p" != 0 ] && [ "$p" != 1 ] || break
        keep="$keep$p "
    done

    victims=()
    for d in /proc/[0-9]*; do
        pid=${d#/proc/}
        case "$keep" in *" $pid "*) continue;; esac
        # -z: NUL-separated records; -x: match a whole record, not a prefix
        grep -qxzF "$uri" "$d/environ" 2>/dev/null && victims+=("$pid")
    done

    if [ ${#victims[@]} -eq 0 ]; then
        echo "orphan sweep: nothing left over"
    else
        echo "orphan sweep: ${#victims[@]} process(es) still holding this demo's CYCLONEDDS_URI"
        ps -o pid=,comm= -p "$(IFS=,; echo "${victims[*]}")" 2>/dev/null \
            | awk '{c[$2]++} END {for (n in c) printf "  %4d x %s\n", c[n], n}' | sort -rn
        kill -TERM "${victims[@]}" 2>/dev/null
        for _ in 1 2 3; do
            sleep 1
            alive=(); for pid in "${victims[@]}"; do kill -0 "$pid" 2>/dev/null && alive+=("$pid"); done
            [ ${#alive[@]} -eq 0 ] && break
        done
        [ ${#alive[@]} -gt 0 ] && kill -KILL "${alive[@]}" 2>/dev/null
    fi

    # Belt and braces: these carry no CYCLONEDDS_URI when started from a shell
    # with no direnv, and the island ignores the variable even when it has it.
    pkill -KILL -f 'demo/control_relay.py' 2>/dev/null
    pkill -KILL -f 'build-zephyr/zephyr/zephyr.exe' 2>/dev/null
    pkill -KILL -f 'native_entry/native_entry' 2>/dev/null
    rm -f demo/.*.pgid
    echo "orphan sweep done"

# Build the host_ws overlay: the MRM-shadowed tier4_system_launch that
# disables Autoware's stock MRM nodes (the domain_bridge checkout is gone —
# direct connection needs no bridge).
#
# Build the demo overlay (MRM-shadowed tier4_system_launch).
demo-host-ws:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    cd demo/host_ws && colcon build --symlink-install

# Inspect the demo graph while `just island` (and/or `just autoware`) runs
# in another terminal. Env from .envrc; the daemon restart drops the cached
# (possibly wrong-config) graph.
#
# List the demo's nodes and topics (needs island and/or autoware running).
topics:
    #!/usr/bin/env bash
    set -e
    ros2 daemon stop >/dev/null 2>&1 || true
    echo "== nodes (domain $ROS_DOMAIN_ID) =="
    timeout 30 ros2 node list
    echo "== topics (domain $ROS_DOMAIN_ID) =="
    timeout 30 ros2 topic list
