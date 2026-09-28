#!/usr/bin/env bash
# Entrypoint of the L3 demo image: bend the build-time user to the host's
# ids, publish the ROS environment to every shell, report what the container
# can reach, then drop to that user and run the command.
#
# The permission model is autosdv's desktop image (docker/desktop/entrypoint.sh
# at 6e7b709), by the user's decision (phase-8 section 3, D3 addition):
# start as root, usermod/groupmod the account to HOST_UID/HOST_GID, blank
# its password (sudo is NOPASSWD), gosu to it. NOT `docker run --user`: a uid
# with no passwd entry has no $HOME and no ~/.ros.
#
# Additions for this demo, not in autosdv:
#   * HOST_DIALOUT_GID / HOST_VIDEO_GID / HOST_PLUGDEV_GID: the host's gids
#     for those groups, so a --device'd serial port, /dev/dri or a USB button
#     opens. gosu takes supplementary groups from the container's /etc/group,
#     so `docker run --group-add` alone does not survive the drop.
#   * no router, no VNC server: the zenoh router and the display are the
#     host's (the container shares the host network and, for RViz, the X
#     socket).

set -euo pipefail

CONTAINER_USER="${CONTAINER_USER:-aw}"
HOST_UID="${HOST_UID:-1000}"
HOST_GID="${HOST_GID:-1000}"

say() { printf '  %s\n' "$*"; }

reconcile_user() {
    if [ "$(id -u)" -ne 0 ]; then
        say "user: $(id -un) (not root; leaving ids alone)"
        return
    fi
    if [ "$HOST_UID" = "0" ]; then
        CONTAINER_USER=root
        say "user: root (HOST_UID=0)"
        return
    fi
    local cur_uid cur_gid home
    cur_uid="$(id -u "$CONTAINER_USER")"
    cur_gid="$(id -g "$CONTAINER_USER")"
    [ "$cur_gid" != "$HOST_GID" ] && groupmod -o -g "$HOST_GID" "$CONTAINER_USER"
    [ "$cur_uid" != "$HOST_UID" ] && usermod -o -u "$HOST_UID" "$CONTAINER_USER"
    local g v
    for g in dialout video plugdev; do
        v="HOST_$(echo "$g" | tr a-z A-Z)_GID"
        if [ -n "${!v:-}" ] && [ "$(getent group "$g" | cut -d: -f3)" != "${!v}" ]; then
            groupmod -o -g "${!v}" "$g"
        fi
    done
    home="$(getent passwd "$CONTAINER_USER" | cut -d: -f6)"
    chown -R "$HOST_UID:$HOST_GID" "$home" 2>/dev/null || true
    passwd -d "$CONTAINER_USER" >/dev/null 2>&1 || true
    say "user: $CONTAINER_USER (uid $HOST_UID, gid $HOST_GID; $(id -Gn "$CONTAINER_USER" | tr ' ' ','); sudo without a password)"
}

# Every shell -- `docker exec`, a terminal in the VNC desktop -- gets the same
# environment the demo scripts use, from the one file that defines it.
publish_ros_env() {
    printf '%s\n' '# Written by the L3 demo entrypoint.' \
        '[ -f /usr/local/bin/l3-env ] && . /usr/local/bin/l3-env' \
        > /etc/profile.d/l3-ros.sh
    grep -q l3-ros /etc/bash.bashrc || \
        printf '\n[ -f /etc/profile.d/l3-ros.sh ] && . /etc/profile.d/l3-ros.sh\n' >> /etc/bash.bashrc
}

report() {
    say "middleware: ${RMW_IMPLEMENTATION} domain ${ROS_DOMAIN_ID} (never autoware-env.bash: it forces Cyclone)"
    if (exec 3<>/dev/tcp/127.0.0.1/7447) 2>/dev/null; then
        say "router: tcp/127.0.0.1:7447 reachable"
    else
        say "router: NOTHING on tcp/127.0.0.1:7447 -- start the host's rmw_zenohd (just l3-router), and run with --network host"
    fi
    if [ -n "${DISPLAY:-}" ] && [ -d /tmp/.X11-unix ]; then
        say "display: $DISPLAY (host X socket mounted)"
    else
        say "display: none (RViz belongs on the host: just l3-rviz)"
    fi
    if [ -n "${L3_SERIAL:-}" ]; then
        if [ -e "$L3_SERIAL" ]; then say "serial: $L3_SERIAL ($(stat -c '%G' "$L3_SERIAL"))"; else say "serial: $L3_SERIAL MISSING"; fi
    fi
}

echo
echo "  L3 demo container (Autoware 1.5.0, rmw_zenoh_cpp)"
reconcile_user
publish_ros_env
report
echo

cd "$(getent passwd "$CONTAINER_USER" | cut -d: -f6)"
if [ "$(id -u)" -eq 0 ] && [ "$CONTAINER_USER" != "root" ]; then
    exec gosu "$CONTAINER_USER" "$@"
fi
exec "$@"
