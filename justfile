# Autoware Safety Island Example — task runner.
#
# Requires a nano-ros checkout. Point NANO_ROS_ROOT at it (default: sibling
# ~/repos/nano-ros) and `source $NANO_ROS_ROOT/activate.sh` first so the
# `nros` CLI + play_launch are on PATH (`just doctor` checks).

NANO_ROS_ROOT := env("NANO_ROS_ROOT", justfile_directory() / "../nano-ros")
BUILD_DIR := "build"
BRINGUP := "safety_island_bringup"

default:
    @just --list

# Verify the environment is usable (nros CLI, play_launch, cmake, ROS 2).
doctor:
    #!/usr/bin/env bash
    set -u
    ok=1
    command -v nros >/dev/null || { echo "MISSING: nros CLI — source $NANO_ROS_ROOT/activate.sh"; ok=0; }
    command -v play_launch >/dev/null || { echo "MISSING: play_launch — source $NANO_ROS_ROOT/activate.sh"; ok=0; }
    command -v cmake >/dev/null || { echo "MISSING: cmake"; ok=0; }
    [ -d "{{NANO_ROS_ROOT}}/cmake" ] || { echo "MISSING: NANO_ROS_ROOT ({{NANO_ROS_ROOT}}) is not a nano-ros checkout"; ok=0; }
    [ "$ok" = 1 ] && echo "doctor: OK (NANO_ROS_ROOT={{NANO_ROS_ROOT}})"
    [ "$ok" = 1 ]

# Resolve the declarative system into the baked model consumed by the entry.
# Re-run after editing system.toml or any launch/*.xml.
# NOTE: needs a play_launch with the `resolve` verb (>= phase 46); a stale
# ~/.local/bin install shadows it — override with PLAY_LAUNCH=<path>.
PLAY_LAUNCH := env("PLAY_LAUNCH", "play_launch")

resolve-model:
    {{PLAY_LAUNCH}} resolve \
        src/{{BRINGUP}}/launch/safety_island.launch.xml \
        --system src/{{BRINGUP}}/system.toml \
        -o src/{{BRINGUP}}/config/system_model.yaml

# One-time workspace prep: model resolve (interface codegen runs at configure).
setup: doctor resolve-model

# Native build (fast dev loop).
# NROS_EXECUTOR_MAX_CBS: compile-time executor callback-slot count (nros-node
# build.rs env knob, default 4); NROS_CYCLONEDDS_MAX_TYPES: cyclone type-registry
# capacity (default 32 — the island vendors ~35+ msg types). Both compile-time;
# clean-rebuild after changing. The island registers ~9 entries
# (subs + services + timers) + the handler ~10 more; 32 gives headroom.
build:
    env NROS_EXECUTOR_MAX_CBS=32 cmake -S . -B {{BUILD_DIR}} -DNANO_ROS_ROOT={{NANO_ROS_ROOT}}
    env NROS_EXECUTOR_MAX_CBS=32 cmake --build {{BUILD_DIR}} -j

# Boot the island on the native board (domain 2, pinned cyclonedds — a
# sourced ROS env otherwise shadows the SDK lib → SIGSEGV; porting-notes env).
run: build
    env LD_LIBRARY_PATH="{{env("HOME")}}/.nros/sdk/cyclonedds/0.10.5-nros1/lib" \
        ROS_DOMAIN_ID=2 \
        ./{{BUILD_DIR}}/src/native_entry/native_entry

# Build the vendored msg pkgs as a host colcon overlay so ros2 CLI tools can
# echo/call the island's typed topics (also proves the pkgs build verbatim).
host-msgs:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    mkdir -p tmp/host_msgs_ws/src && cd tmp/host_msgs_ws/src
    ln -sfn ../../../src/autoware_common_msgs ../../../src/autoware_control_msgs ../../../src/tier4_system_msgs .
    cd .. && colcon build --symlink-install
    echo "source tmp/host_msgs_ws/install/setup.bash + RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=2"

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

# ── Autoware co-sim demo ─────────────────────────────────────────────────────
# Phase-2 host path (Autoware 1.5.0 install). `ros2 launch` leaves ORPHANS on
# a plain kill — every recipe runs the tree in its own PROCESS GROUP (setsid)
# and the -down recipe kills the whole group.

# Host Autoware planning_simulator (domain 1, stock MRM shadowed out by
# demo/host_ws). RViz shows on $DISPLAY (TurboVNC).
demo-sim:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1
    source demo/host_ws/install/setup.bash
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=1
    setsid nohup ros2 launch autoware_launch planning_simulator.launch.xml         map_path:=$PWD/demo/map/sample-map-planning vehicle_model:=sample_vehicle         sensor_model:=sample_sensor_kit rviz:=true > tmp_sim.log 2>&1 < /dev/null &
    echo $! > demo/.sim.pgid
    echo "sim started, pgid $(cat demo/.sim.pgid) (log tmp_sim.log)"

demo-sim-down:
    -kill -TERM -- -$(cat demo/.sim.pgid 2>/dev/null) 2>/dev/null; sleep 3;      kill -KILL -- -$(cat demo/.sim.pgid 2>/dev/null) 2>/dev/null; rm -f demo/.sim.pgid;      echo "sim group killed"

# domain_bridge (host_ws build) with the split-domain cyclone config.
demo-bridge:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1
    source demo/host_ws/install/setup.bash
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
    export CYCLONEDDS_URI=file://$PWD/demo/cyclonedds.xml
    setsid nohup ros2 run domain_bridge domain_bridge --wait-for-publisher false demo/bridge/bridge-forward.yaml > tmp_bridge_fwd.log 2>&1 < /dev/null &
    echo $! > demo/.bridge-fwd.pgid
    setsid nohup ros2 run domain_bridge domain_bridge --wait-for-publisher false demo/bridge/bridge-reverse.yaml > tmp_bridge_rev.log 2>&1 < /dev/null &
    echo $! > demo/.bridge-rev.pgid
    echo "bridges: fwd pgid $(cat demo/.bridge-fwd.pgid) (heartbeat leg — the demo faults this), rev pgid $(cat demo/.bridge-rev.pgid) (island commands — stays alive)"

demo-bridge-down:
    -kill -TERM -- -$(cat demo/.bridge-fwd.pgid 2>/dev/null) 2>/dev/null; rm -f demo/.bridge-fwd.pgid
    -kill -TERM -- -$(cat demo/.bridge-rev.pgid 2>/dev/null) 2>/dev/null; rm -f demo/.bridge-rev.pgid


# Build the host_ws overlay (domain_bridge + MRM-shadowed tier4_system_launch).
demo-host-ws:
    #!/usr/bin/env bash
    set -e
    source /opt/ros/humble/setup.bash
    cd demo/host_ws && colcon build --symlink-install

# ── Containerized alternative (Autoware 0.40 image; velocity-limit rows
#    dropped there — see bridge-config comments) ────────────────────────────
demo-up:
    cd demo && docker compose up -d

demo-down:
    cd demo && docker compose down

# Scenario: pause the domain bridge (heartbeat loss) → island engages MRM.
demo-kill-heartbeat:
    bash demo/scenario-kill-heartbeat.sh

# Print the host-side env needed to talk to the ZEPHYR island (native_sim
# bakes multicast-off unicast-peer discovery — porting-notes 19).
host-env:
    @echo 'export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=2'
    @echo 'export CYCLONEDDS_URI="<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"lo\"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>30</MaxAutoParticipantIndex><Peers><Peer Address=\"127.0.0.1\"/></Peers></Discovery></Domain></CycloneDDS>"'


