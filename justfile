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

# Island process only, in its own process group (`island-up` wraps this
# together with the bridges + relay).
#
# Start just the island process.
island-proc-up island="zephyr": (_not-running "demo/.island.pgid" "island")
    #!/usr/bin/env bash
    set -e
    just _island-image-check {{island}}
    setsid nohup just _svc-island {{island}} > /dev/null 2>&1 < /dev/null &
    sleep 1
    echo "{{island}} island started, pgid $(cat demo/.island.pgid) (log tmp_island.log)"

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
_island-image-check island:
    #!/usr/bin/env bash
    if [ "{{island}}" = "zephyr" ]; then
        [ -x ./build-zephyr/zephyr/zephyr.exe ] || { echo "no zephyr image — run: just zephyr-build"; exit 1; }
    else
        [ -x ./{{BUILD_DIR}}/src/native_entry/native_entry ] || { echo "no native image — run: just build"; exit 1; }
    fi

# Foreground island service (single source — island-proc-up detaches it,
# demo-all supervises it). Records its process group for the -down recipes.
[private]
_svc-island island="zephyr":
    #!/usr/bin/env bash
    set -e
    ps -o pgid= -p $$ | tr -d ' ' > demo/.island.pgid
    if [ "{{island}}" = "zephyr" ]; then
        exec ./build-zephyr/zephyr/zephyr.exe > tmp_island.log 2>&1
    else
        exec env LD_LIBRARY_PATH="{{CYCLONEDDS_HOME}}/lib" \
            ROS_DOMAIN_ID=2 CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>spdp</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>30</MaxAutoParticipantIndex><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>' \
            ./{{BUILD_DIR}}/src/native_entry/native_entry > tmp_island.log 2>&1
    fi

# Stop just the island process.
island-proc-down:
    -kill -TERM -- -$(cat demo/.island.pgid 2>/dev/null) 2>/dev/null; rm -f demo/.island.pgid

# ══ THE DEMO ════════════════════════════════════════════════════════════════
# Three parts, each runnable on its own (in this order):
#
#   1. just autoware-up      Autoware planning_simulator, domain 1, stock MRM
#                            DISABLED (demo/host_ws shadows tier4_system_launch)
#   2. just island-up        safety island on domain 2 + domain bridges + relay
#   3. just demo-scenario    drive → fault the heartbeat → island MRM → VERDICT
#
# All three, one command:  just demo-all     Teardown: just demo-down
#
# Host path (Autoware 1.5.0 install). `ros2 launch` / play_launch leave
# ORPHANS on a plain kill — every service is a foreground `_svc-*` wrapper
# that records its own PROCESS GROUP: the *-up recipes detach it (setsid),
# each -down kills the group, and `demo-all` runs the same wrappers under a
# GNU parallel supervisor (whole-group teardown when the scenario finishes).

# ── 1. Autoware (no MRM) ────────────────────────────────────────────────────
# planning_simulator via play_launch >= {{PLAY_LAUNCH_MIN}} (40s bring-up, 62/62
# composables, clean teardown; 0.5.x stalls on the busy composable containers).
# RViz renders on the VNC display ({{VNC_DISPLAY}}).
#
# 1. Start Autoware (planning_simulator, domain 1, stock MRM disabled).
autoware-up: (_not-running "demo/.sim.pgid" "sim") _sim-prereq-check
    #!/usr/bin/env bash
    set -e
    setsid nohup just _svc-sim > /dev/null 2>&1 < /dev/null &
    sleep 1
    echo "sim started, pgid $(cat demo/.sim.pgid) (log tmp_sim.log) — 'just autoware-wait' blocks until ready"

[private]
_sim-prereq-check:
    @[ -f demo/host_ws/install/setup.bash ] || { echo "demo/host_ws not built — run: just demo-host-ws"; exit 1; }
    @command -v {{PLAY_LAUNCH}} >/dev/null || { echo "no play_launch on PATH — run: just setup"; exit 1; }

# Foreground sim service (single source — autoware-up detaches it, demo-all
# supervises it).
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
autoware-wait timeout="300":
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

# Stop Autoware (process-group kill).
autoware-down:
    -kill -TERM -- -$(cat demo/.sim.pgid 2>/dev/null) 2>/dev/null; sleep 3;      kill -KILL -- -$(cat demo/.sim.pgid 2>/dev/null) 2>/dev/null; rm -f demo/.sim.pgid;      echo "sim group killed"

# ── 2. Safety island (island process + bridges + relay) ─────────────────────
#   just island-up             # zephyr native_sim image (default)
#   just island-up native      # native_entry build
#
# 2. Start the safety island: island process + domain bridges + control relay.
island-up island="zephyr":
    #!/usr/bin/env bash
    set -e
    just bridge-up
    just relay-up
    just island-proc-up {{island}}
    echo "-- letting the island settle (latched inputs)..."
    sleep 10
    echo "island side up (island: {{island}})"

# Stop the island process, relay and bridges.
island-down:
    -just island-proc-down
    -just relay-down
    -just bridge-down

# Start both domain_bridge legs (host_ws build, split-domain cyclone config).
bridge-up: (_not-running "demo/.bridge-fwd.pgid" "bridge-fwd") (_not-running "demo/.bridge-rev.pgid" "bridge-rev")
    #!/usr/bin/env bash
    set -e
    setsid nohup just _svc-bridge forward fwd > /dev/null 2>&1 < /dev/null &
    setsid nohup just _svc-bridge reverse rev > /dev/null 2>&1 < /dev/null &
    sleep 1
    echo "bridges: fwd pgid $(cat demo/.bridge-fwd.pgid) (heartbeat leg — the demo faults this), rev pgid $(cat demo/.bridge-rev.pgid) (island commands — stays alive)"

# Foreground bridge-leg service (single source — bridge-up detaches both,
# demo-all supervises them). The scenario SIGSTOPs the recorded groups.
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

# Stop both bridge legs.
bridge-down:
    -kill -TERM -- -$(cat demo/.bridge-fwd.pgid 2>/dev/null) 2>/dev/null; rm -f demo/.bridge-fwd.pgid
    -kill -TERM -- -$(cat demo/.bridge-rev.pgid 2>/dev/null) 2>/dev/null; rm -f demo/.bridge-rev.pgid

# Typed relay for the island's emergency Control (d2 -> d1): stands in for
# the dropped bridge row until nano-ros #267; ALSO the honest actuation path —
# it survives the bridge fault, so the island's ramp reaches the vehicle.
#
# Start the d2 -> d1 control relay.
relay-up: (_not-running "demo/.relay.pgid" "relay")
    #!/usr/bin/env bash
    set -e
    setsid nohup just _svc-relay > /dev/null 2>&1 < /dev/null &
    sleep 1
    echo "control relay started, pgid $(cat demo/.relay.pgid)"

# Foreground relay service (single source — relay-up detaches it, demo-all
# supervises it).
[private]
_svc-relay:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1
    ps -o pgid= -p $$ | tr -d ' ' > demo/.relay.pgid
    echo "control relay starting (log tmp_relay.log)"
    exec python3 demo/control_relay.py > tmp_relay.log 2>&1

# Stop the control relay.
relay-down:
    -kill -TERM -- -$(cat demo/.relay.pgid 2>/dev/null) 2>/dev/null; rm -f demo/.relay.pgid

# ── 3. Demo sequence ────────────────────────────────────────────────────────
# The full driving sequence (pure rclpy — the ros2-CLI daemon is unreliable
# under heavy graphs): init pose -> goal -> engage -> drive -> fault -> verdict.
#
# 3. Run the demo sequence and print the VERDICT.
demo-scenario:
    #!/usr/bin/env bash
    source /opt/ros/humble/setup.bash
    source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1
    python3 demo/scenario_driver.py

# ── All of it, one command ──────────────────────────────────────────────────
#   just demo-all              # zephyr island (default)
#   just demo-all native       # native island
#
# One GNU parallel supervisor runs every service (same _svc-* wrappers the
# *-up recipes detach) plus the scenario as a finishing job: when the
# scenario prints its VERDICT, parallel tears every service group down
# (--termseq TERM→KILL) and exits with the scenario's status. Ctrl-C
# mid-run tears everything down too — no orphans either way.
#
# Autoware + island + demo sequence, one command; exits with the VERDICT.
demo-all island="zephyr": (_not-running "demo/.sim.pgid" "sim") (_not-running "demo/.bridge-fwd.pgid" "bridge-fwd") (_not-running "demo/.bridge-rev.pgid" "bridge-rev") (_not-running "demo/.relay.pgid" "relay") (_not-running "demo/.island.pgid" "island") _sim-prereq-check (_island-image-check island)
    #!/usr/bin/env bash
    exec parallel --lb --halt now,done=1 --termseq TERM,5000,KILL,1000 ::: \
        "just _svc-sim" \
        "just _svc-bridge forward fwd" \
        "just _svc-bridge reverse rev" \
        "just _svc-relay" \
        "just _svc-island {{island}}" \
        "just _job-scenario"

# The demo-all finishing job: readiness-gate, settle, then the sequence.
[private]
_job-scenario:
    #!/usr/bin/env bash
    set -e
    just autoware-wait
    echo "-- letting the island settle (latched inputs)..."
    sleep 10
    exec just demo-scenario

# Tear the whole demo down.
demo-down:
    -just island-down
    -just autoware-down

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

# Back-compat names (the pre-phase-6 recipe set).
alias demo-sim := autoware-up
alias demo-sim-down := autoware-down
alias demo-bridge := bridge-up
alias demo-bridge-down := bridge-down
alias demo-relay := relay-up
alias demo-relay-down := relay-down
alias demo-down-all := demo-down



# Print the host-side env needed to talk to the ZEPHYR island (native_sim
# bakes multicast-off unicast-peer discovery — porting-notes 19).
#
# Print the host-side env needed to talk to the Zephyr island.
host-env:
    @echo 'export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=2'
    @echo 'export CYCLONEDDS_URI="<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"lo\"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>30</MaxAutoParticipantIndex><Peers><Peer Address=\"127.0.0.1\"/></Peers></Discovery></Domain></CycloneDDS>"'


