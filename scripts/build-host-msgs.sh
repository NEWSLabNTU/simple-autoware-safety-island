#!/usr/bin/env bash
# Build the island's message packages as a ROS 2 (colcon) overlay:
# safety_island_msgs and every vendored Autoware subset under src/. It proves
# they build verbatim under rosidl, lets ros2 CLI tools echo the island's
# typed topics, and puts their .msg files on the ament index, where
# `play_launch check` resolves every `when:` and `commands` field
# (.github/check-contracts.sh requires that).
#
#   scripts/build-host-msgs.sh [<workspace dir>]   (default tmp/host_msgs_ws)
#   source <workspace dir>/install/setup.bash
#
# Run with ROS 2 Humble sourced. Not src/nav_msgs: it is an Odometry-only
# subset, and ROS Humble ships the full package.
set -eu
cd "$(dirname "$0")/.."
ws="${1:-tmp/host_msgs_ws}"
pkgs="autoware_adapi_v1_msgs autoware_common_msgs autoware_control_msgs
      autoware_internal_planning_msgs autoware_planning_msgs
      autoware_vehicle_msgs tier4_system_msgs safety_island_msgs"
mkdir -p "$ws/src"
for p in $pkgs; do ln -sfn "$PWD/src/$p" "$ws/src/$p"; done
cd "$ws"
colcon build --symlink-install --event-handlers console_direct- \
    --cmake-args -DBUILD_TESTING=OFF
