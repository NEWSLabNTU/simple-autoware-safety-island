#!/usr/bin/env bash
# run island_inputs.py under a clean env: ROS 2 Humble + Autoware 1.5.0 msgs, rmw_zenoh, domain 10
port="${PORT:-7449}"
here="$(cd "$(dirname "$0")" && pwd)"
exec env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c '
  source /opt/ros/humble/setup.bash
  source /opt/autoware/1.5.0/setup.bash
  export ROS_DOMAIN_ID=10 RMW_IMPLEMENTATION=rmw_zenoh_cpp
  export ZENOH_CONFIG_OVERRIDE="connect/endpoints=[\"tcp/127.0.0.1:'"$port"'\"]"
  exec python3 -u '"$here"'/island_inputs.py "$@"
' _ "$@"
