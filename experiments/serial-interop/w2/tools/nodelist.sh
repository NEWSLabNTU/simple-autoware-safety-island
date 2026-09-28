#!/usr/bin/env bash
# a transient ROS 2 CLI node: joins the graph, lists it, leaves (what `just board-peer-nodes` does)
port=${PORT:-7449}
exec env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c '
  source /opt/ros/humble/setup.bash
  export ROS_DOMAIN_ID=10 RMW_IMPLEMENTATION=rmw_zenoh_cpp
  export ZENOH_CONFIG_OVERRIDE="connect/endpoints=[\"tcp/127.0.0.1:'"$port"'\"]"
  date +%T.%N; timeout 60 ros2 node list --no-daemon; date +%T.%N
'
