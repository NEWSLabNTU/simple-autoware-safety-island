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
# Placeholders — wired up when src/zephyr_entry lands. native_sim first,
# then the QEMU board bring-up (see the phase doc, P4).

zephyr-build:
    @echo "phase 4 — not wired yet (see docs/roadmap/phase-1-safety-island-port.md)"; exit 1

zephyr-run:
    @echo "phase 4 — not wired yet"; exit 1

# ── Autoware co-sim demo (phase 5) ──────────────────────────────────────────

# Start Autoware planning_simulator + domain_bridge (stock MRM nodes disabled).
demo-up:
    cd demo && docker compose up -d

demo-down:
    cd demo && docker compose down

# Scenario: stop publishing the heartbeat and watch the island engage MRM.
demo-kill-heartbeat:
    @echo "phase 5 — not wired yet"; exit 1
