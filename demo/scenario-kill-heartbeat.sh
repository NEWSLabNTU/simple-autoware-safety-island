#!/usr/bin/env bash
# P5 scenario: engage autonomous driving in the planning simulator, then stop
# the availability heartbeat reaching the island and watch it stop the vehicle.
#
# Prereqs: `just demo-up` (sim + bridge on domain 1), `just run` (island on
# domain 2), a route set in the sim (noVNC :6080 → RViz → 2D Goal Pose).
set -euo pipefail

source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

echo "== engage autonomous (domain 1) =="
ROS_DOMAIN_ID=1 ros2 service call /api/operation_mode/change_to_autonomous \
    autoware_adapi_v1_msgs/srv/ChangeOperationMode "{}" || true

echo "== island MRM state before (domain 2) =="
ROS_DOMAIN_ID=2 timeout 5 ros2 topic echo /system/fail_safe/mrm_state --once | grep -E "^state|^behavior"

echo "== killing the heartbeat: pausing the bridge container =="
docker compose -f "$(dirname "$0")/docker-compose.yaml" pause bridge

sleep 2
echo "== island MRM state after (expect MRM_OPERATING / EMERGENCY_STOP) =="
ROS_DOMAIN_ID=2 timeout 5 ros2 topic echo /system/fail_safe/mrm_state --once | grep -E "^state|^behavior"
echo "== emergency decel ramp =="
ROS_DOMAIN_ID=2 timeout 5 ros2 topic echo /system/emergency/control_cmd --once | grep -E "velocity|acceleration" | head -2

echo "== restore bridge =="
docker compose -f "$(dirname "$0")/docker-compose.yaml" unpause bridge
