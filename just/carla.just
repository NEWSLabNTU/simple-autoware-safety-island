# ---- CARLA demo, unit C1: the CARLA ego on the island's domain ----------------
# docs/design/carla-island-demo.md section 1.2 and 5; how to run it:
# demo/carla/README.md. The ego (Autoware 1.5.0 + acb_bridge + acb_agent,
# carla-scenario-bridge's `just ego-av`) runs on rmw_zenoh_cpp, domain 10,
# through the stock router (`just l3-router`), with this repo's overlay
# (build/l3-host-ws, `just l3-host-ws`) sourced between Autoware and acb, so
# tier4_system_launch is the overlay's (stock MRM off) and the availability
# converter publishes .../availability_raw for takeover_demo's gate. The
# scenario side (csb bridge, agent relay, SSv2) stays on Cyclone domain 9; the
# two meet over the relay's TCP socket (5560).
#
#   just carla-server              1. CARLA 0.9.16 offscreen (blocks)
#   just l3-router                 2. the stock zenoh router, 7447 (blocks)
#   just carla-sim                 3. csb bridge + agent relay, Cyclone domain 9 (blocks)
#   just carla-ego                 4. the ego on zenoh, domain 10 (blocks; wait for Startup complete)
#   just carla-takeover            5. availability gate, odd_monitor, ... (blocks)
#   just carla-scenario <xosc>     6. one SSv2 scenario -> its junit
#   just l3-nodes                  the domain-10 graph
#
# SAI_ACT_TRIGGER (C4) reaches the scenario: town01_island_encore.xosc runs
# `$(env SAI_ACT_TRIGGER true) hpc-loss` at its place (run-board.sh sets it to
# demo/carla/act_trigger.py and the act's socket; unset, `true`, a no-op).
#
# Every recipe runs under `env -i`: the login shell on this host carries
# demo/host_ws/install ahead of /opt/autoware and the Cyclone env of .envrc.
# ZENOH_RUNTIME as in the L3 image (demo/l3/README.md trap 2c): with zenoh's
# Net runtime on one worker a session deadlocks under the join churn of ~200
# peer sessions; C1's first start hung one composable (iv_msgs) in its
# constructor for 7 min without it. It made the hang rarer, not impossible:
# demo/carla/play_launch.yaml paces the start and reloads a wedged composable.
# EGO_CONTAINER_MODE observable (CSB's default is isolated): every process is
# a zenoh peer and peers mesh, so one process per container (~80) instead of
# one per composable (~200); in isolated mode 2 of 5 starts failed (a
# subscription that never received; a drive that did not arrive).

CSB_DIR := env("CSB_DIR", "/mnt/evo/aeon/repos/carla-scenario-bridge")
CARLA_DIR := env("CARLA_DIR", home_directory() + "/carla-0.9.16")
CARLA_GRAPH := "share/tier4_system_launch/config/diagnostics/autoware-carla-l3.yaml"

[private]
_carla-env cmd:
    #!/usr/bin/env bash
    [ -f {{L3_HOST_WS}}/install/setup.bash ] || { echo "no host overlay -- run: just l3-host-ws"; exit 1; }
    [ -f "{{CSB_DIR}}/justfile" ] || { echo "no carla-scenario-bridge at {{CSB_DIR}} (set CSB_DIR)"; exit 1; }
    ws="$PWD/{{L3_HOST_WS}}/install"
    exec env -i HOME="$HOME" USER="$USER" TERM=dumb \
        PATH=/usr/local/bin:/usr/bin:/bin:$HOME/.cargo/bin:$HOME/.local/bin \
        CARLA_PORT="${CARLA_PORT:-2000}" MAP_NAME="${MAP_NAME:-Town01}" \
        EGO_ROS_DOMAIN_ID=10 EGO_RMW_IMPLEMENTATION=rmw_zenoh_cpp \
        EGO_OVERLAY="$PWD/demo/carla/ego-overlay.bash" \
        EGO_LAUNCH_ARGS="operation_mode_availability_topic:=/system/operation_mode/availability_raw l3_diagnostic_graph_path:=$ws/{{CARLA_GRAPH}} ${CARLA_EGO_ARGS:-}" \
        LAUNCH_RVIZ="${LAUNCH_RVIZ:-false}" OUTPUT_DIR="${OUTPUT_DIR:-/tmp}" \
        SAI_ACT_TRIGGER="${SAI_ACT_TRIGGER:-true}" \
        ZENOH_RUNTIME="(net: (worker_threads: 8))" \
        EGO_PLAY_LAUNCH_ARGS="-c $PWD/demo/carla/play_launch.yaml" \
        EGO_CONTAINER_MODE="${EGO_CONTAINER_MODE:-observable}" \
        bash -c '{{cmd}}'

# CARLA 0.9.16 offscreen on the NVIDIA card, Town01 at boot (blocks). C1
carla-server:
    #!/usr/bin/env bash
    if ss -ltn | awk '{print $4}' | grep -qE "[:.]${CARLA_PORT:-2000}$"; then echo "carla-server: ${CARLA_PORT:-2000} is already listening"; exit 1; fi
    exec env -u DISPLAY CARLA_DIR="{{CARLA_DIR}}" CARLA_RENDER=offscreen \
        "{{CSB_DIR}}/src/autoware_carla_bridge/third_party/carla/run.sh"

# csb's simulation side: bridge + agent relay, Cyclone domain 9 (blocks). C1
carla-sim:
    just _carla-env 'exec just -f "{{CSB_DIR}}/justfile" run'

# The ego on rmw_zenoh_cpp, domain 10, the island's overlay, the merged graph (blocks). C1
carla-ego:
    #!/usr/bin/env bash
    if ! (exec 3<>/dev/tcp/127.0.0.1/7447) 2>/dev/null; then
        echo "carla-ego: nothing listens on 127.0.0.1:7447 -- start the router first (just l3-router)" >&2; exit 1
    fi
    exec just _carla-env 'echo "carla-ego: $EGO_RMW_IMPLEMENTATION, domain $EGO_ROS_DOMAIN_ID, overlay $EGO_OVERLAY"; echo "carla-ego: launch args $EGO_LAUNCH_ARGS"; exec just -f "{{CSB_DIR}}/justfile" ego-av'

# takeover_demo beside the CARLA ego: gate, odd_monitor, HMI, hazard relay (blocks). C1
carla-takeover *args="":
    just _l3-host 'exec bash demo/l3/container/bin/l3-takeover driver_button:=false {{args}}'

# One SSv2 scenario against the zenoh ego (csb `just scenario`; junit in $OUTPUT_DIR). C1
carla-scenario xosc:
    just _carla-env 'exec just -f "{{CSB_DIR}}/justfile" scenario "$(realpath "{{xosc}}")"'

# The island's two always-on outputs (mrm_state NORMAL, emergency control_cmd) for a run with NO island (blocks). C1
carla-standin:
    just _l3-host 'source demo/l3/container/bin/l3-env; exec python3 demo/carla/island_standin.py'

# The patched librclcpp for the native ego (demo/l3/README.md trap 2b), built for
# the host's own rclcpp version into build/l3-host-rclcpp. The L3 image carries
# the same patch over 16.0.19 (demo/l3/container/Dockerfile, stage rclcpp);
# without it behavior_path_planner went silent on the first route in every C1
# scenario on rmw_zenoh_cpp (the agent stuck in PLANNING). Only the ego loads it:
# demo/carla/ego-overlay.bash puts its lib first on LD_LIBRARY_PATH. C1
carla-rclcpp:
    #!/usr/bin/env bash
    set -eo pipefail
    ver="$(dpkg-query -W -f '${Version}' ros-humble-rclcpp | cut -d- -f1)"
    dir=build/l3-host-rclcpp
    patch="$PWD/demo/l3/container/patches/rclcpp-16.0.19-executor-keep-group-guard-conditions.patch"
    if [ -f $dir/install/rclcpp/lib/librclcpp.so ] && [ "$(cat $dir/version 2>/dev/null)" = "$ver" ]; then
        echo "carla-rclcpp: $dir has rclcpp $ver patched already"; exit 0
    fi
    rm -rf $dir; mkdir -p $dir/src
    git clone -q -c advice.detachedHead=false --depth 1 --branch "$ver" https://github.com/ros2/rclcpp.git $dir/src/rclcpp
    git -C $dir/src/rclcpp apply "$patch"
    start=$(date +%s)
    env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c "source /opt/ros/humble/setup.bash && cd $dir && \
        MAKEFLAGS=-j${CARLA_RCLCPP_JOBS:-8} colcon build --packages-select rclcpp --event-handlers console_direct- \
        --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF" > $dir/build.log 2>&1 \
        || { tail -40 $dir/build.log; exit 1; }
    strip --strip-debug $dir/install/rclcpp/lib/librclcpp.so
    echo "$ver" > $dir/version
    echo "carla-rclcpp: rclcpp $ver + $(basename "$patch") in $(( $(date +%s) - start )) s -> $dir/install/rclcpp/lib"

# ---- C8: the proof cast ---------------------------------------------------------
# One act on the board (run-board.sh --sim carla, args as there: [options] a|b|encore
# <run-id>), the dashboard demo/carla/cast_dashboard.py on CAST_DISPLAY (:3, a
# 1920x1080 TurboVNC display of its own; demo/carla/cast.sh says how to start one),
# recorded with ffmpeg into CAST_DIR (/mnt/evo/aeon/casts) with stills. C8
#
# Record one act with the cast dashboard (needs the :3 display). C8
carla-cast *args:
    scripts/ienv.sh 'CAST_DISPLAY="{{env("CAST_DISPLAY", ":3")}}" CAST_DIR="{{env("CAST_DIR", "/mnt/evo/aeon/casts")}}" demo/carla/cast.sh {{args}}'

# Start the cast's display: TurboVNC :3, 1920x1080, no desktop (only the dashboard draws). C8
carla-cast-display:
    #!/usr/bin/env bash
    d="${CAST_DISPLAY:-:3}"
    case "$d" in :1|:2|:9) echo "carla-cast-display: $d is not ours" >&2; exit 2;; esac
    if [ -S "/tmp/.X11-unix/X${d#:}" ]; then echo "carla-cast-display: $d is up"; exit 0; fi
    pid="$HOME/.vnc/$(hostname):${d#:}.pid"
    if [ -f "$pid" ] && ! kill -0 "$(cat "$pid")" 2>/dev/null; then echo "carla-cast-display: removing the stale $pid"; rm -f "$pid"; fi
    x="${CAST_DIR:-/mnt/evo/aeon/casts}/xstartup-bare.sh"
    mkdir -p "$(dirname "$x")"
    printf '#!/bin/sh\n# bare display for the island cast: no desktop, no window manager\nexec sleep infinity\n' > "$x"; chmod +x "$x"
    /opt/TurboVNC/bin/vncserver "$d" -geometry 1920x1080 -xstartup "$x"
