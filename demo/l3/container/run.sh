#!/usr/bin/env bash
# Run the L3 demo image (phase8-W3). The just recipes call this; it is also
# the one place the container's run-time contract is written down.
#
#   demo/l3/container/run.sh                     a shell in a new container
#   demo/l3/container/run.sh l3-autoware         Autoware (blocks)
#   docker exec -it sai-l3 l3-takeover           more commands, same container
#
# What the container gets, and why:
#   --network host      the zenoh router is the HOST's (stock rmw_zenohd on
#                       7447; the island's gateway router, unit W2, connects
#                       to it). rmw_zenoh peers also listen on ephemeral
#                       ports and gossip their locators, so a bridge network
#                       would advertise container addresses host tools
#                       cannot reach (brief A, risk 6). No -p needed.
#   --shm-size 2g       Autoware's containers; the 64 MB default fails in
#                       ways that look like middleware faults (autosdv).
#   HOST_UID/HOST_GID   the entrypoint bends the image's user to them, so
#                       play_log and bags written to mounts are the user's.
#   HOST_*_GID          the host's dialout/video/plugdev gids, for a passed
#                       serial port, /dev/dri or a USB button.
#   L3_X=1              RViz inside: the host X socket (TurboVNC :1 on the
#                       demo box counts) and /dev/dri. Default off: RViz runs
#                       on the host over zenoh (just l3-rviz).
#   L3_SERIAL=<by-id>   a serial device by its /dev/serial/by-id path,
#                       inside as /dev/ttyL3. Default none: the board link is
#                       the host's (W2's router holds the port; two openers
#                       of one tty corrupt each other's frames).
#   L3_LOG_HOST=<dir>   where play_launch's log lands on the host
#                       (default build/l3-container-log).
#   L3_DEBUG=1          SYS_PTRACE, for gdb inside.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
IMAGE="${L3_IMAGE:-sai-l3-autoware:1.5.0}"
NAME="${L3_NAME:-sai-l3}"
LOG_HOST="${L3_LOG_HOST:-$repo/build/l3-container-log}"
mkdir -p "$LOG_HOST"

gid_of() { getent group "$1" | cut -d: -f3; }

args=(
    --rm --name "$NAME"
    --network host --shm-size 2g
    --init
    -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)"
    -e HOST_DIALOUT_GID="$(gid_of dialout)"
    -e HOST_VIDEO_GID="$(gid_of video)"
    -e HOST_PLUGDEV_GID="$(gid_of plugdev)"
    -e ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-10}"
    -e L3_LOG_DIR=/l3-log -v "$LOG_HOST:/l3-log"
)
# A router other than the host's 7447 (a second demo on one host): both or neither.
[ -n "${L3_ROUTER_PORT:-}" ] && args+=(-e L3_ROUTER_PORT="$L3_ROUTER_PORT")
[ -n "${ZENOH_CONFIG_OVERRIDE:-}" ] && args+=(-e ZENOH_CONFIG_OVERRIDE="$ZENOH_CONFIG_OVERRIDE")
[ -t 0 ] && [ -t 1 ] && args+=(-it)

if [ "${L3_X:-0}" = "1" ]; then
    [ -n "${DISPLAY:-}" ] || { echo "run.sh: L3_X=1 needs DISPLAY" >&2; exit 1; }
    args+=(-e DISPLAY="$DISPLAY" -v /tmp/.X11-unix:/tmp/.X11-unix:ro -e L3_RVIZ=true)
    if [ -n "${XAUTHORITY:-}" ] && [ -f "$XAUTHORITY" ]; then
        args+=(-e XAUTHORITY=/tmp/.l3-xauth -v "$XAUTHORITY:/tmp/.l3-xauth:ro")
    fi
    [ -d /dev/dri ] && args+=(--device /dev/dri)
fi

# L3_DEBUG=1: ptrace for gdb inside (a component container that stops
# serving its services is diagnosed with a backtrace, nothing else).
if [ "${L3_DEBUG:-0}" = "1" ]; then
    args+=(--cap-add SYS_PTRACE --security-opt seccomp=unconfined)
fi

if [ -n "${L3_SERIAL:-}" ]; then
    case "$L3_SERIAL" in /dev/serial/by-id/*) ;; *)
        echo "run.sh: pass the serial device by its /dev/serial/by-id path (it survives re-enumeration)" >&2; exit 1;;
    esac
    [ -e "$L3_SERIAL" ] || { echo "run.sh: $L3_SERIAL does not exist" >&2; exit 1; }
    args+=(--device "$L3_SERIAL:/dev/ttyL3" -e L3_SERIAL=/dev/ttyL3)
fi

exec docker run "${args[@]}" "$IMAGE" "$@"
