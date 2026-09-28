#!/usr/bin/env bash
# brief B's host side: three `ros2 topic pub -r 10` processes (three nodes), for DURATION seconds
dur=${1:-40}
exec env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c '
  source /opt/ros/humble/setup.bash; source /opt/autoware/1.5.0/setup.bash
  export ROS_DOMAIN_ID=10 RMW_IMPLEMENTATION=rmw_zenoh_cpp
  export ZENOH_CONFIG_OVERRIDE="connect/endpoints=[\"tcp/127.0.0.1:'"${PORT:-7449}"'\"]"
  timeout '"$dur"' ros2 topic pub -r 10 /vehicle/status/control_mode autoware_vehicle_msgs/msg/ControlModeReport "{mode: 1}" > /dev/null &
  timeout '"$dur"' ros2 topic pub -r 10 /api/operation_mode/state autoware_adapi_v1_msgs/msg/OperationModeState "{mode: 2, is_autoware_control_enabled: true}" > /dev/null &
  timeout '"$dur"' ros2 topic pub -r 10 /system/operation_mode/availability tier4_system_msgs/msg/OperationModeAvailability "{autonomous: true, stop: true, emergency_stop: true, comfortable_stop: true}" > /dev/null &
  wait
'
