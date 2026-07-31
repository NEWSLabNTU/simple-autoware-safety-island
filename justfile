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

# Boot the island on the native board (domain 2, pinned cyclonedds — a
# sourced ROS env otherwise shadows the SDK lib → SIGSEGV; porting-notes env).
#
# Build and boot the island on the native board (foreground).
run: build
    env LD_LIBRARY_PATH="{{CYCLONEDDS_HOME}}/lib" \
        ROS_DOMAIN_ID=2 \
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
    echo "source tmp/host_msgs_ws/install/setup.bash + RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=2"

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
#   1. just autoware         Autoware planning_simulator, domain 1, stock MRM
#                            DISABLED (demo/host_ws shadows tier4_system_launch)
#   2. just island           safety island on domain 2 + domain bridges + relay
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
    exec parallel --lb --halt now,fail=1 --termseq {{TERMSEQ}} ::: \
        "just _svc-sim" \
        "just _wait-sim && echo '== autoware up (stock MRM off) — Ctrl-C stops it =='"

[private]
_sim-prereq-check:
    @[ -f demo/host_ws/install/setup.bash ] || { echo "demo/host_ws not built — run: just demo-host-ws"; exit 1; }
    @command -v {{PLAY_LAUNCH}} >/dev/null || { echo "no play_launch on PATH — run: just setup"; exit 1; }

# Foreground sim service (single source — `autoware` supervises it,
# demo-all reuses it).
[private]
_svc-sim:
    #!/usr/bin/env bash
    set -e
    PL="$(command -v {{PLAY_LAUNCH}})"
    source /opt/ros/humble/setup.bash
    source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1
    source demo/host_ws/install/setup.bash
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=1
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

# ── 2. Safety island (island process + bridges + relay) ─────────────────────
#   just island            # zephyr native_sim image (default)
#   just island native     # native_entry build
#
# 2. Safety island + bridges + relay (blocks; Ctrl-C stops all four).
island target="zephyr": (_not-running "demo/.bridge-fwd.pgid" "bridge-fwd") (_not-running "demo/.bridge-rev.pgid" "bridge-rev") (_not-running "demo/.relay.pgid" "relay") (_not-running "demo/.island.pgid" "island") (_island-image-check target)
    #!/usr/bin/env bash
    exec parallel --lb --halt now,fail=1 --termseq {{TERMSEQ}} ::: \
        "just _svc-bridge forward fwd" \
        "just _svc-bridge reverse rev" \
        "just _svc-relay" \
        "just _svc-island {{target}}" \
        "sleep 10 && echo '== island side up ({{target}}) — Ctrl-C stops it =='"

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
            ROS_DOMAIN_ID=2 CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>spdp</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>30</MaxAutoParticipantIndex><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>' \
            ./{{BUILD_DIR}}/src/native_entry/native_entry > tmp_island.log 2>&1
    fi

# Foreground bridge-leg service (single source). The scenario SIGSTOPs the
# recorded groups to fault the heartbeat.
[private]
_svc-bridge dir tag:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1
    source demo/host_ws/install/setup.bash
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
    export CYCLONEDDS_URI=file://$PWD/demo/cyclonedds.xml
    ps -o pgid= -p $$ | tr -d ' ' > demo/.bridge-{{tag}}.pgid
    echo "bridge-{{tag}} starting (log tmp_bridge_{{tag}}.log)"
    exec ros2 run domain_bridge domain_bridge --wait-for-publisher false demo/bridge/bridge-{{dir}}.yaml > tmp_bridge_{{tag}}.log 2>&1

# Typed relay for the island's emergency Control (d2 -> d1): stands in for
# the dropped bridge row until nano-ros #267; ALSO the honest actuation path —
# it survives the bridge fault, so the island's ramp reaches the vehicle.
[private]
_svc-relay:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1
    ps -o pgid= -p $$ | tr -d ' ' > demo/.relay.pgid
    echo "control relay starting (log tmp_relay.log)"
    exec python3 demo/control_relay.py > tmp_relay.log 2>&1

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

# The raw sequence, no readiness gating.
[private]
_scenario:
    #!/usr/bin/env bash
    source /opt/ros/humble/setup.bash
    source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1
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
demo-all island="zephyr": (_not-running "demo/.sim.pgid" "sim") (_not-running "demo/.bridge-fwd.pgid" "bridge-fwd") (_not-running "demo/.bridge-rev.pgid" "bridge-rev") (_not-running "demo/.relay.pgid" "relay") (_not-running "demo/.island.pgid" "island") _sim-prereq-check (_island-image-check island)
    #!/usr/bin/env bash
    exec parallel --lb --halt now,done=1 --termseq {{TERMSEQ}} ::: \
        "just _svc-sim" \
        "just _svc-bridge forward fwd" \
        "just _svc-bridge reverse rev" \
        "just _svc-relay" \
        "just _svc-island {{island}}" \
        "just demo"

# ── Crash cleanup ───────────────────────────────────────────────────────────
# Normal teardown is just Ctrl-C / recipe exit. After a crashed or killed
# supervisor: kill the recorded groups, then sweep pattern-matched orphans
# whose pgid file was overwritten by a double-start.
#
# Crash cleanup: kill recorded groups + sweep orphans.
demo-down: (_kill-group "demo/.island.pgid") (_kill-group "demo/.relay.pgid") (_kill-group "demo/.bridge-fwd.pgid") (_kill-group "demo/.bridge-rev.pgid") (_kill-group "demo/.sim.pgid") _sweep-orphans

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

# Pattern-kill demo processes that outlived their pgid file. Patterns are
# demo-specific (bridge yaml paths, this repo's binaries) so unrelated ROS
# processes are untouched.
[private]
_sweep-orphans:
    #!/usr/bin/env bash
    pkill -KILL -f 'domain_bridge --wait-for-publisher' 2>/dev/null
    pkill -KILL -f 'demo/control_relay.py' 2>/dev/null
    pkill -KILL -f 'build-zephyr/zephyr/zephyr.exe' 2>/dev/null
    pkill -KILL -f 'native_entry/native_entry' 2>/dev/null
    pkill -KILL -f 'launch autoware_launch planning_simulator' 2>/dev/null
    rm -f demo/.*.pgid
    echo "orphan sweep done"

# Fetch + build the host_ws overlay: ros2/domain_bridge (upstream checkout,
# not vendored) and the MRM-shadowed tier4_system_launch that disables
# Autoware's stock MRM nodes.
#
# Fetch + build the demo overlay (domain_bridge + MRM-shadowed launch).
demo-host-ws:
    #!/usr/bin/env bash
    set -e
    [ -d demo/host_ws/src/domain_bridge ] || \
        git clone -b humble --depth 1 https://github.com/ros2/domain_bridge.git demo/host_ws/src/domain_bridge
    source /opt/ros/humble/setup.bash
    cd demo/host_ws && colcon build --symlink-install

# Host-side cyclone config matching the island's discovery (lo, multicast
# off, unicast 127.0.0.1 peer scan — porting-notes 19).
ISLAND_HOST_URI := '<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>30</MaxAutoParticipantIndex><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'

# Print the host-side env needed to talk to the island (eval "$(just host-env)").
host-env:
    @echo 'export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=2'
    @echo "export CYCLONEDDS_URI='{{ISLAND_HOST_URI}}'"

# Inspect the island's domain-2 graph while `just island` runs in another
# terminal. Wraps the env every time (a plain `ros2 topic list` sees the
# wrong domain + discovery config and an empty cached daemon graph).
#
# List the island's nodes and topics (needs `just island` running).
topics:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=2
    export CYCLONEDDS_URI='{{ISLAND_HOST_URI}}'
    ros2 daemon stop >/dev/null 2>&1 || true
    echo "== nodes (domain 2) =="
    timeout 30 ros2 node list
    echo "== topics (domain 2) =="
    timeout 30 ros2 topic list
