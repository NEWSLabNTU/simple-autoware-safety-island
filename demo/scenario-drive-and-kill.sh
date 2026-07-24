#!/usr/bin/env bash
# Phase-2 W3 — the full driving sequence: init pose → goal → engage → cut the
# availability heartbeat → verify the ISLAND stops the vehicle. Exit 0 = PASS.
#
# Prereqs: `just demo-sim` (host Autoware 1.5.0, MRM shadowed out),
# `just demo-bridge`, `just run` (island, domain 2). Watch in RViz (TurboVNC).
#
# Poses are for demo/map/sample-map-planning: the init pose is the Autoware
# tutorial spawn; the goal was captured from an RViz 2D-Goal-Pose click on
# this map (2026-07-24). Override: INIT_POSE_ARGS / GOAL_X/GOAL_Y/GOAL_QZ/GOAL_QW.
set -o pipefail
cd "$(dirname "$0")/.."

source /opt/ros/humble/setup.bash
source /opt/autoware/1.5.0/setup.bash >/dev/null 2>&1
source demo/host_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
LO_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>spdp</AllowMulticast></General></Domain></CycloneDDS>'
d1() { env ROS_DOMAIN_ID=1 "$@"; }
d2() { env ROS_DOMAIN_ID=2 CYCLONEDDS_URI="$LO_URI" "$@"; }

INIT_X=${INIT_X:-3730.47}; INIT_Y=${INIT_Y:-73727.89}
INIT_QZ=${INIT_QZ:-0.2312}; INIT_QW=${INIT_QW:-0.9729}
GOAL_X=${GOAL_X:-3760.41}; GOAL_Y=${GOAL_Y:-73755.91}
GOAL_QZ=${GOAL_QZ:--0.49896}; GOAL_QW=${GOAL_QW:-0.86662}

vel() { d1 timeout 8 ros2 topic echo /localization/kinematic_state --once --field twist.twist.linear.x 2>/dev/null | head -1; }

echo "== 0. wait for the sim stack (ADAPI routing up) =="
until d1 timeout 5 ros2 topic echo /api/routing/state --once --field state >/dev/null 2>&1; do sleep 5; done
echo "== 1. initial pose =="
d1 timeout 8 ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {position: {x: ${INIT_X}, y: ${INIT_Y}, z: 0.0}, orientation: {z: ${INIT_QZ}, w: ${INIT_QW}}}, covariance: [0.25,0,0,0,0,0, 0,0.25,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0, 0,0,0,0,0,0.068]}}" >/dev/null 2>&1
sleep 5

echo "== 2. goal =="
d1 timeout 8 ros2 topic pub --once /planning/mission_planning/goal geometry_msgs/msg/PoseStamped \
  "{header: {frame_id: map}, pose: {position: {x: ${GOAL_X}, y: ${GOAL_Y}, z: 0.0}, orientation: {z: ${GOAL_QZ}, w: ${GOAL_QW}}}}" >/dev/null 2>&1
for i in $(seq 1 10); do
  ROUTE=$(d1 timeout 6 ros2 topic echo /api/routing/state --once --field state 2>/dev/null | head -1)
  [ "$ROUTE" = "2" ] && break; sleep 2
done
echo "route state: ${ROUTE:-none} (2=SET)"
[ "$ROUTE" != "2" ] && { echo "route not set — check goal placement (RViz 2D Goal Pose to test)"; exit 2; }

echo "== 3. engage autonomous =="
for i in $(seq 1 6); do
  OK=$(d1 timeout 12 ros2 service call /api/operation_mode/change_to_autonomous \
       autoware_adapi_v1_msgs/srv/ChangeOperationMode "{}" 2>/dev/null | grep -o "success=[A-Za-z]*" | head -1)
  echo "engage attempt $i: ${OK:-timeout}"
  [ "$OK" = "success=True" ] && break; sleep 5
done

echo "== 4. wait for motion =="
V0=""
for i in $(seq 1 15); do
  V0=$(vel); case "$V0" in ""|0.0|-0.0) sleep 2;; *) break;; esac
done
echo "velocity: ${V0:-n/a}"

# Let it actually DRIVE before the fault — makes the stop visible in RViz.
DRIVE_SECS=${DRIVE_SECS:-15}
echo "== 4b. driving for ${DRIVE_SECS}s =="
sleep "$DRIVE_SECS"
V0=$(vel); echo "velocity before fault: ${V0:-n/a}"

echo "== 5. cut the availability heartbeat (SIGSTOP the bridge group) =="
BRIDGE_PGID=$(cat demo/.bridge.pgid 2>/dev/null)
if [ -n "$BRIDGE_PGID" ]; then kill -STOP -- -"$BRIDGE_PGID" && echo "bridge group $BRIDGE_PGID paused"
else BP=$(pgrep -x domain_bridge | head -1); kill -STOP "$BP" && echo "bridge $BP paused"; fi

sleep 3
echo "== 6. island verdict (expect state=2 MRM_OPERATING, behavior=2 EMERGENCY_STOP) =="
d2 timeout 8 ros2 topic echo /system/fail_safe/mrm_state --once 2>/dev/null | grep -E "^state|^behavior"

sleep 7
V1=$(vel); echo "velocity after island MRM: ${V1:-n/a}"

echo "== 7. restore bridge =="
if [ -n "$BRIDGE_PGID" ]; then kill -CONT -- -"$BRIDGE_PGID"; else kill -CONT "$BP" 2>/dev/null; fi

python3 - "$V0" "$V1" <<'EOF'
import sys
try:
    v0, v1 = float(sys.argv[1]), float(sys.argv[2])
except Exception:
    print("VERDICT: INCONCLUSIVE (missing velocity samples)"); sys.exit(2)
if v0 > 0.5 and abs(v1) < 0.3:
    print(f"VERDICT: PASS — island stopped the vehicle ({v0:.2f} -> {v1:.2f} m/s)"); sys.exit(0)
print(f"VERDICT: FAIL ({v0:.2f} -> {v1:.2f} m/s)"); sys.exit(1)
EOF
