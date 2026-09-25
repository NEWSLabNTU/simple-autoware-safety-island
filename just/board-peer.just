# phase7-W7 -- a transport peer for the board on its serial link. Imported by
# one line at the end of the main justfile.
#
# The island image's zenoh locator is serial/uart@40330000#baudrate=115200, the
# board's only wired UART (P6 -> FTDI -> /dev/ttyUSB0). With no peer the image
# waits in the session open-retry loop and no node ever starts (docs/board-facts.md,
# Z1a). This is experiments/serial-interop's host side as a recipe: rmw_zenohd
# LISTENING on the serial line, bridging to TCP for the ROS 2 CLI.
#
# The traps experiments/serial-interop/README.md records, and what this does
# about each:
#   * router-serial.json5 is a full copy of rmw_zenoh's router default with
#     keep_alive 6, so the board (20 s zenoh-pico lease) is not expired every
#     20 s. The listen endpoints must come from ZENOH_CONFIG_OVERRIDE.
#   * libzenohc.so must be on LD_LIBRARY_PATH (zenoh_cpp_vendor). An inherited
#     environment can predate that package, and the login shell here also
#     resolves ROS packages to demo/host_ws. So the router runs under `env -i`
#     with ROS 2 sourced fresh, and the recipe checks the vendor path is there.
#   * the ROS 2 CLI must be told RMW_IMPLEMENTATION=rmw_zenoh_cpp or it talks
#     DDS and silently sees nothing of the board (`board-peer-nodes` sets it),
#     and ROS_DOMAIN_ID must be 10, the image's CONFIG_NROS_DOMAIN_ID.
#   * the router must be listening BEFORE the board dials: start this, then
#     reset the board.
#   * `just board-flash` is `west flash`, which REBUILDS first in its own
#     environment: an image built with triage env vars (ZPICO_*) is flashed
#     without them unless they are set for board-flash too (seen in W7).
#   * nothing else may hold /dev/ttyUSB0 (a console `cat` makes the router's
#     open fail or split the bytes); checked with fuser.
#   * `grep "transport opened"` on the log means nothing without
#     zenoh_transport=debug; RUST_LOG sets it (BOARD_PEER_RUST_LOG overrides,
#     e.g. zenoh=debug to see the board's declarations arrive).

PEER_TTY := "/dev/ttyUSB0"
# NOT 7447. That is the port every rmw_zenoh process on this host dials by
# default, and the one the QEMU island's locator reaches (tcp/10.0.2.100:7447,
# just/emulation.just). On 2026-09-25 a router here on 7447 was joined by
# another session's QEMU island and by TCP clients this recipe never started,
# whose entities are easy to mistake for the board's. The board side is
# serial; the TCP port only serves `board-peer-nodes`.
PEER_TCP := "7449"
PEER_DIR := "build/trace"

# Run the host zenoh router on the board's serial line (foreground; Ctrl-C stops).
board-peer tty=PEER_TTY port=PEER_TCP log=(PEER_DIR / "board-peer-router.log"):
    #!/usr/bin/env bash
    set -eo pipefail
    if holders="$(fuser "{{tty}}" 2>/dev/null)" && [ -n "$holders" ]; then
        echo "board-peer: {{tty}} is held by pid(s)$holders -- stop them first:"
        fuser -v "{{tty}}" 2>&1 || true
        exit 1
    fi
    if ss -ltn | awk '{print $4}' | grep -qE "[:.]{{port}}$"; then
        echo "board-peer: tcp port {{port}} is already listening -- another router? (pass port=...)"
        exit 1
    fi
    mkdir -p "$(dirname "{{log}}")"
    cfg="$PWD/experiments/serial-interop/router-serial.json5"
    rust_log="${BOARD_PEER_RUST_LOG:-zenoh=info,zenoh_transport=debug}"
    # Run the router under its own name: on 2026-09-25 a concurrent session's
    # name-based cleanup of `rmw_zenohd` closed this router twice mid-run
    # (a clean "close session" in the log, nothing from the board side).
    bin="$PWD/{{PEER_DIR}}/board-peer-zenohd"
    ln -sfn /opt/ros/humble/lib/rmw_zenoh_cpp/rmw_zenohd "$bin"
    echo "board-peer: rmw_zenohd on serial/{{tty}}#baudrate=115200 + tcp/[::]:{{port}}; log {{log}}"
    echo "board-peer: now reset the board (pyocd reset -t s32k344); Ctrl-C stops the router"
    env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c '
        source /opt/ros/humble/setup.bash
        echo "$LD_LIBRARY_PATH" | tr : "\n" | grep -q zenoh_cpp_vendor \
            || { echo "board-peer: zenoh_cpp_vendor is not on LD_LIBRARY_PATH (ros-humble-zenoh-cpp-vendor missing?)"; exit 1; }
        export ROS_DOMAIN_ID=10
        export ZENOH_ROUTER_CONFIG_URI="'"$cfg"'"
        export ZENOH_CONFIG_OVERRIDE="listen/endpoints=[\"serial/{{tty}}#baudrate=115200\",\"tcp/[::]:{{port}}\"]"
        export RUST_LOG="'"$rust_log"'"
        exec "'"$bin"'"
    ' 2>&1 | tee "{{log}}"

# List the ROS 2 graph through the board-peer router (rmw_zenoh, domain 10, no daemon).
board-peer-nodes port=PEER_TCP:
    #!/usr/bin/env bash
    exec env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c '
        source /opt/ros/humble/setup.bash
        export ROS_DOMAIN_ID=10 RMW_IMPLEMENTATION=rmw_zenoh_cpp
        export ZENOH_CONFIG_OVERRIDE="connect/endpoints=[\"tcp/127.0.0.1:{{port}}\"]"
        echo "== ros2 node list (rmw_zenoh_cpp, domain 10, router tcp/127.0.0.1:{{port}})"
        timeout 60 ros2 node list --no-daemon
        echo "== ros2 topic list"
        timeout 60 ros2 topic list --no-daemon
    '
