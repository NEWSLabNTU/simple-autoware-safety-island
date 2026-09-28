# phase 8 -- the RTSS@Work 2026 takeover demo (docs/roadmap/phase-8-rtss-work-demo.md).
# Imported by one line at the end of the main justfile. Units W2, W3, W7 and
# W8 add their recipes here; each recipe names the unit that owns it.

# List the phase-8 recipes.
l3-help:
    @echo "phase 8 recipes land here: l3-container (W3), l3-peer (W2), l3-run (W3), l3-timeline (W7), l3-board (W8)"

# ---- l3-peer (phase8-W2) ------------------------------------------------------
# The ISLAND GATEWAY router of design D1 (brief C option (a')): its own
# rmw_zenohd, listening on the board's serial line at 921,600 baud and
# connecting to Autoware's stock router, so every serial-specific setting lives
# in demo/l3/router/island-gateway.json5 and the stock router stays untouched:
# keep_alive 6, egress downsampling of kinematic_state / control_mode /
# gear_cmd, and no liveliness tokens toward the island. docs/serial-link.md has
# the measurements behind each one.
#
# Same traps as `board-peer` (just/board-peer.just), handled the same way: env -i
# with ROS 2 sourced fresh, a fuser check on the tty, its own binary name. Plus:
#   * the tty is the /dev/serial/by-id path, so a re-plug that renumbers
#     ttyUSB* does not move the board;
#   * the FTDI latency timer is set to 1 ms (ASYNC_LOW_LATENCY, no root
#     needed); the default 16 ms adds up to 16 ms to every island -> host
#     sample;
#   * the stock router must answer on `stock` (tcp/127.0.0.1:7447, what every
#     rmw_zenoh process dials); the gateway retries until it does
#     (connect timeout_ms router -1), so start order does not matter, but the
#     board must be reset AFTER this is listening;
#   * TCP `port` (7449) serves diagnostics only, as in board-peer.
# The image must carry the same rate: CONFIG_NROS_ZENOH_LOCATOR in
# src/zephyr_entry/snippets/island-serial/serial.conf.
L3_PEER_TTY := "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0"

# Run the island gateway router on the board's serial line (foreground; Ctrl-C stops). phase8-W2
l3-peer tty=L3_PEER_TTY baud="921600" stock="tcp/127.0.0.1:7447" port="7449" log="build/trace/l3-peer-router.log":
    #!/usr/bin/env bash
    set -eo pipefail
    [ -e "{{tty}}" ] || { echo "l3-peer: {{tty}} does not exist -- is the DCD-LZ cable plugged in?"; exit 1; }
    if holders="$(fuser "{{tty}}" 2>/dev/null)" && [ -n "$holders" ]; then
        echo "l3-peer: {{tty}} is held by pid(s)$holders -- stop them first:"
        fuser -v "{{tty}}" 2>&1 || true
        exit 1
    fi
    if ss -ltn | awk '{print $4}' | grep -qE "[:.]{{port}}$"; then
        echo "l3-peer: tcp port {{port}} is already listening -- another board-peer/l3-peer? (pass port=...)"
        exit 1
    fi
    stock_port="{{stock}}"; stock_port="${stock_port##*:}"
    ss -ltn | awk '{print $4}' | grep -qE "[:.]${stock_port}$" \
        || echo "l3-peer: nothing listens on {{stock}} yet -- the gateway will keep dialling it"
    python3 -c 'import serial,sys; s=serial.Serial(sys.argv[1], int(sys.argv[2])); s.set_low_latency_mode(True); s.close()' "{{tty}}" "{{baud}}" \
        || echo "l3-peer: could not set the FTDI low-latency flag (pyserial missing?); latency_timer stays at 16 ms"
    dev="$(basename "$(readlink -f "{{tty}}")")"
    [ -r "/sys/bus/usb-serial/devices/$dev/latency_timer" ] && echo "l3-peer: $dev latency_timer = $(cat /sys/bus/usb-serial/devices/$dev/latency_timer) ms"
    mkdir -p "$(dirname "{{log}}")"
    cfg="$PWD/demo/l3/router/island-gateway.json5"
    rust_log="${L3_PEER_RUST_LOG:-zenoh=info,zenoh_transport=debug}"
    bin="$PWD/build/trace/l3-peer-zenohd"
    ln -sfn /opt/ros/humble/lib/rmw_zenoh_cpp/rmw_zenohd "$bin"
    echo "l3-peer: rmw_zenohd on serial/{{tty}}#baudrate={{baud}} + tcp/[::]:{{port}}, connecting {{stock}}; log {{log}}"
    echo "l3-peer: now reset the board (pyocd reset -t s32k344); Ctrl-C stops the router"
    env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c '
        source /opt/ros/humble/setup.bash
        echo "$LD_LIBRARY_PATH" | tr : "\n" | grep -q zenoh_cpp_vendor \
            || { echo "l3-peer: zenoh_cpp_vendor is not on LD_LIBRARY_PATH (ros-humble-zenoh-cpp-vendor missing?)"; exit 1; }
        export ZENOH_ROUTER_CONFIG_URI="'"$cfg"'"
        export ZENOH_CONFIG_OVERRIDE="listen/endpoints=[\"serial/{{tty}}#baudrate={{baud}}\",\"tcp/[::]:{{port}}\"];connect/endpoints=[\"{{stock}}\"]"
        export RUST_LOG="'"$rust_log"'"
        exec "'"$bin"'"
    ' 2>&1 | tee "{{log}}"

# ---- phase8-W3: Autoware 1.5.0 on rmw_zenoh_cpp, in a container -------------
# Design D2/D3 (docs/roadmap/phase-8-rtss-work-demo.md); how to run it:
# demo/l3/README.md. One domain (10), one stock router on the host (7447);
# the island's gateway (l3-peer, W2) connects to that router. Autoware runs
# in the container on the host network; RViz and the routers stay on the host.
#
#   just l3-router                 1. the stock router, 7447 (blocks)
#   just l3-autoware               2. Autoware in the container (blocks)
#   just l3-takeover               3. the takeover nodes, same container (blocks)
#   just l3-run hpc|odd|odd-respond|drive   4. one scripted act
#   just l3-nodes                  the graph as ros2 sees it
#
# `where=host` runs 2-4 on the host instead, under `env -i` with ROS sourced
# fresh (this shell carries demo/host_ws/install ahead of /opt/autoware and
# the Cyclone env of `.envrc`); build that overlay first with l3-host-ws.
L3_IMAGE := env("L3_IMAGE", "sai-l3-autoware:1.5.0")
L3_NAME := env("L3_NAME", "sai-l3")
L3_HOST_WS := "build/l3-host-ws"

[private]
_l3-host cmd:
    #!/usr/bin/env bash
    [ -f {{L3_HOST_WS}}/install/setup.bash ] || { echo "no host overlay -- run: just l3-host-ws"; exit 1; }
    exec env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin:$HOME/.local/bin \
        DISPLAY="${DISPLAY:-}" XAUTHORITY="${XAUTHORITY:-}" ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-10}" \
        L3_WS="$PWD/{{L3_HOST_WS}}/install" L3_MAP="$PWD/demo/map/sample-map-planning" \
        L3_LOG_DIR="$PWD/{{L3_HOST_WS}}/play_log" L3_GATE="${L3_GATE:-1}" \
        L3_CONTAINER_MODE="${L3_CONTAINER_MODE:-stock}" L3_RVIZ="${L3_RVIZ:-false}" \
        DRIVE_SECS="${DRIVE_SECS:-10}" OBSERVE_SECS="${OBSERVE_SECS:-15}" RESPOND_AFTER="${RESPOND_AFTER:-2}" \
        bash -c '{{cmd}}'

# Build the Autoware image from the localrepo (layers cached; prints time and size). phase8-W3
l3-container:
    #!/usr/bin/env bash
    set -eo pipefail
    start=$(date +%s)
    DOCKER_BUILDKIT=1 docker build -f demo/l3/container/Dockerfile -t {{L3_IMAGE}} .
    echo "l3-container: {{L3_IMAGE}} in $(( $(date +%s) - start )) s, $(docker image inspect -f '{{{{.Size}}' {{L3_IMAGE}} | awk '{printf "%.2f GB", $1/1e9}')"
    docker image prune -f --filter label=org.newslab.sai.image=l3-autoware

# Build the demo overlay + takeover_demo on the host (build/l3-host-ws). phase8-W3
l3-host-ws:
    env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin:$HOME/.local/bin bash -c 'source /opt/ros/humble/setup.bash && source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1 && colcon --log-base {{L3_HOST_WS}}/log build --base-paths demo/host_ws/src demo/l3/takeover_demo --build-base {{L3_HOST_WS}}/build --install-base {{L3_HOST_WS}}/install --merge-install'

# The stock rmw_zenohd on 7447, the one router Autoware dials (blocks). phase8-W3
l3-router port="7447":
    #!/usr/bin/env bash
    if ss -ltn | awk '{print $4}' | grep -qE "[:.]{{port}}$"; then echo "l3-router: {{port}} is already listening"; exit 1; fi
    exec env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c \
        'source /opt/ros/humble/setup.bash; export ZENOH_CONFIG_OVERRIDE="listen/endpoints=[\"tcp/[::]:{{port}}\"]"; exec ros2 run rmw_zenoh_cpp rmw_zenohd'

# Autoware's planning simulator on rmw_zenoh_cpp, stock MRM off (blocks). phase8-W3
l3-autoware where="container":
    #!/usr/bin/env bash
    if [ "{{where}}" = host ]; then exec just _l3-host 'exec bash demo/l3/container/bin/l3-autoware'; fi
    exec demo/l3/container/run.sh l3-autoware

# The takeover_demo nodes, beside Autoware (blocks). phase8-W3
l3-takeover where="container" *args="":
    #!/usr/bin/env bash
    if [ "{{where}}" = host ]; then exec just _l3-host 'exec bash demo/l3/container/bin/l3-takeover {{args}}'; fi
    exec docker exec -it {{L3_NAME}} l3-takeover {{args}}

# The booth keyboard: SPACE/t take over, o ODD exit, c clear (blocks). phase8-W3
l3-button where="container":
    #!/usr/bin/env bash
    if [ "{{where}}" = host ]; then exec just _l3-host 'exec bash demo/l3/container/bin/l3-button'; fi
    exec docker exec -it {{L3_NAME}} l3-button

# One scripted act: hpc | odd | odd-respond | drive -> VERDICT. phase8-W3
l3-run act="hpc" where="container":
    #!/usr/bin/env bash
    if [ "{{where}}" = host ]; then exec just _l3-host 'exec bash demo/l3/container/bin/l3-scenario {{act}}'; fi
    exec docker exec -e DRIVE_SECS="${DRIVE_SECS:-10}" -e OBSERVE_SECS="${OBSERVE_SECS:-15}" \
        -e RESPOND_AFTER="${RESPOND_AFTER:-2}" {{L3_NAME}} l3-scenario {{act}}

# `ros2 node list` on domain 10 over zenoh (no daemon). phase8-W3
l3-nodes where="host":
    #!/usr/bin/env bash
    if [ "{{where}}" = container ]; then exec docker exec {{L3_NAME}} l3-nodes; fi
    exec env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-10}" L3_WS=/nonexistent bash -c \
        'source demo/l3/container/bin/l3-env 2>/dev/null; echo "== ros2 node list (RMW $RMW_IMPLEMENTATION, domain $ROS_DOMAIN_ID) $(date -Is) =="; timeout 20 ros2 node list --no-daemon'

# RViz on the host, over zenoh, with Autoware's config (blocks). phase8-W3
l3-rviz config="/opt/autoware/1.5.0/share/autoware_launch/rviz/autoware.rviz":
    just _l3-host 'source demo/l3/container/bin/l3-env; exec rviz2 -d {{config}}'

# The QEMU island (an existing image; default build-qemu) into a router on the
# host: guestfwd 10.0.2.100:7447 -> {{host}}:{{port}} (bounded). phase8-W3
l3-island-qemu elf="build-qemu/zephyr/zephyr.elf" port="7447" secs="60" host="127.0.0.1":
    #!/usr/bin/env bash
    set -eo pipefail
    [ -f "{{elf}}" ] || { echo "l3-island-qemu: no {{elf}} (just qemu-build)"; exit 1; }
    qemu_dir="$("{{NANO_ROS_ROOT}}/packages/cli/target/release/nros" sdk-path qemu --require --index "{{NANO_ROS_ROOT}}/nros-sdk-index.toml" 2>/dev/null || true)"
    qemu="${qemu_dir:+$qemu_dir/bin/}qemu-system-arm"
    mkdir -p build/emulation; log="build/emulation/l3-island-$(date +%Y%m%dT%H%M%S).log"
    echo "l3-island-qemu: {{elf}} ($(sha256sum "{{elf}}" | cut -c1-12)) -> tcp/{{host}}:{{port}}, console $log, {{secs}} s"
    timeout --foreground -s INT {{secs}} "$qemu" -cpu cortex-m3 -machine mps2-an385 -nographic -vga none \
        -nic "user,model=lan9118,guestfwd=tcp:10.0.2.100:7447-tcp:{{host}}:{{port}}" \
        -kernel "{{elf}}" </dev/null 2>&1 | tee "$log" || true

# play_launch check on every contract with the CI's pinned wheel (build/l3-ci). phase8-W3
l3-check:
    #!/usr/bin/env bash
    set -eo pipefail
    ver="$(sed -n 's/^ *PLAY_LAUNCH_VERSION: *"\(.*\)"/\1/p' .github/workflows/check.yml)"
    venv=build/l3-ci/play_launch-$ver
    [ -x $venv/bin/play_launch ] || { python3 -m venv $venv && $venv/bin/pip install -q "play_launch==$ver"; }
    env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin PLAY_LAUNCH="$PWD/$venv/bin/play_launch" \
        bash -c 'source /opt/ros/humble/setup.bash && exec .github/check-contracts.sh'
