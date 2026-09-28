#!/usr/bin/env python3
"""phase8-W2: publish the island's contracted inputs at contract rates, with
real message sizes, and watch the island's outputs the way Autoware would.

Run under rmw_zenoh_cpp, domain 10, connected to the island gateway router.
  island_inputs.py --duration 600 [--stop-availability-at 30] [--only a,b]
Prints one status line every 10 s and a summary at the end (JSON on the
last line). Every availability publish is logged with CLOCK_MONOTONIC and
wall time when --stop-availability-at is given, for the reaction.
"""
import argparse, json, sys, time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from tier4_system_msgs.msg import OperationModeAvailability
from nav_msgs.msg import Odometry
from autoware_vehicle_msgs.msg import ControlModeReport, GearCommand, SteeringReport, VelocityReport
from autoware_adapi_v1_msgs.msg import OperationModeState, MrmState
from autoware_control_msgs.msg import Control
from autoware_planning_msgs.msg import RouteState
from tier4_system_msgs.msg import MrmBehaviorStatus
from autoware_vehicle_msgs.msg import HazardLightsCommand, TurnIndicatorsCommand

# name: (topic, type, rate Hz from safety_island.contract.yaml)
INPUTS = {
    "availability":   ("/system/operation_mode/availability", OperationModeAvailability, 10.0),
    "kinematic_state": ("/localization/kinematic_state", Odometry, 10.0),
    "control_mode":   ("/vehicle/status/control_mode", ControlModeReport, 10.0),
    "gear_cmd":       ("/control/command/gear_cmd", GearCommand, 10.0),
    "operation_mode_state": ("/api/operation_mode/state", OperationModeState, 10.0),
    "control_cmd":    ("/control/command/control_cmd", Control, 30.0),
    "steering_status": ("/vehicle/status/steering_status", SteeringReport, 30.0),
    "velocity_status": ("/vehicle/status/velocity_status", VelocityReport, 30.0),
    "route_state":    ("/planning/route_state", RouteState, 30.0),
}
# What vehicle_cmd_gate and friends read from the island (brief C 2.2).
OUTPUTS = {
    "mrm_state": ("/system/fail_safe/mrm_state", MrmState),
    "emergency_control_cmd": ("/system/emergency/control_cmd", Control),
    "emergency_gear_cmd": ("/system/emergency/gear_cmd", GearCommand),
    "emergency_hazard": ("/system/emergency/hazard_lights_cmd", HazardLightsCommand),
    "emergency_turn": ("/system/emergency/turn_indicators_cmd", TurnIndicatorsCommand),
}

def fill(name, msg, now):
    if hasattr(msg, "stamp"):
        msg.stamp = now
    if name == "availability":
        msg.stop = msg.autonomous = msg.local = msg.remote = True
        msg.emergency_stop = msg.comfortable_stop = True
        msg.pull_over = False
    elif name == "kinematic_state":
        msg.header.stamp = now; msg.header.frame_id = "map"; msg.child_frame_id = "base_link"
        msg.pose.pose.position.x = 3700.0; msg.pose.pose.position.y = 73700.0
        msg.pose.pose.orientation.w = 1.0
        msg.pose.covariance = [0.01 * (i % 7) for i in range(36)]
        msg.twist.twist.linear.x = 4.0
        msg.twist.covariance = [0.001 * (i % 5) for i in range(36)]
    elif name == "control_mode":
        msg.mode = ControlModeReport.AUTONOMOUS
    elif name == "gear_cmd":
        msg.command = GearCommand.DRIVE
    elif name == "operation_mode_state":
        msg.mode = OperationModeState.AUTONOMOUS
        msg.is_autoware_control_enabled = True
        msg.is_stop_mode_available = msg.is_autonomous_mode_available = True
    elif name == "control_cmd":
        msg.control_time = now
        msg.lateral.stamp = now; msg.lateral.control_time = now
        msg.lateral.steering_tire_angle = 0.01
        msg.longitudinal.stamp = now; msg.longitudinal.control_time = now
        msg.longitudinal.velocity = 4.0
    elif name == "steering_status":
        msg.steering_tire_angle = 0.01
    elif name == "velocity_status":
        msg.header.stamp = now; msg.header.frame_id = "base_link"
        msg.longitudinal_velocity = 4.0
    elif name == "route_state":
        msg.state = RouteState.SET
    return msg


class Driver(Node):
    def __init__(self, a):
        super().__init__("w2_island_inputs")
        self.a = a
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE, history=HistoryPolicy.KEEP_LAST)
        only = set(a.only.split(",")) if a.only else set(INPUTS)
        self.sent = {}; self.pubs = {}; self.tmrs = []
        self.t0 = time.monotonic()
        self.avail_log = []
        self.avail_stopped_at = None
        for name, (topic, typ, rate) in INPUTS.items():
            if name not in only:
                continue
            self.pubs[name] = (self.create_publisher(typ, topic, qos), typ)
            self.sent[name] = 0
            self.tmrs.append(self.create_timer(1.0 / rate, lambda n=name: self.tick(n)))
        self.recv = {k: 0 for k in OUTPUTS}
        self.first_mrm_t = None
        self.brake_seen = None   # (t_rel, mono, wall) of the first braking emergency control_cmd after the stop
        self.operating_seen = None
        self.mrm_states = []   # (t_rel, state, behavior) on change
        self.last_mrm = None
        self.mrm_gap_max = 0.0; self.mrm_last_t = None
        if not a.no_outputs:
            for name, (topic, typ) in OUTPUTS.items():
                self.create_subscription(typ, topic, lambda m, n=name: self.on_out(n, m), qos)
        self.create_timer(10.0, self.report)

    def tick(self, name):
        rel = time.monotonic() - self.t0
        if (name == "availability" and self.a.stop_after_first_mrm is not None and self.first_mrm_t is not None
                and self.a.stop_availability_at is None):
            self.a.stop_availability_at = self.first_mrm_t + self.a.stop_after_first_mrm
        if name == "availability" and self.a.stop_availability_at is not None and rel >= self.a.stop_availability_at:
            if self.avail_stopped_at is None:
                self.avail_stopped_at = rel
                self.get_logger().info(f"availability publisher STOPPED at t={rel:.3f}s mono={time.monotonic():.6f} wall={time.time():.6f}")
            return
        pub, typ = self.pubs[name]
        msg = fill(name, typ(), self.get_clock().now().to_msg())
        pub.publish(msg)
        self.sent[name] += 1
        if name == "availability":
            self.avail_log.append((time.monotonic(), time.time()))

    def on_out(self, name, msg):
        self.recv[name] += 1
        now_m = time.monotonic(); now_rel = now_m - self.t0
        if name == "mrm_state":
            # With --first-mrm-after-gap: the island's first mrm_state after a
            # silence of >= 1 s (a board reset shows as one), or, if no earlier
            # instance was heard, the first one after --arm-after seconds.
            last = getattr(self, "_last_mrm_rel", None)
            if self.first_mrm_t is None:
                if not self.a.first_mrm_after_gap or \
                        (last is None and now_rel > self.a.arm_after) or \
                        (last is not None and now_rel - last >= 1.0):
                    self.first_mrm_t = now_rel
                    self.get_logger().info(f"island first mrm_state (this instance) at t={now_rel:.3f}s")
            self._last_mrm_rel = now_rel
        if self.avail_stopped_at is not None:
            if name == "mrm_state" and msg.state == 2 and self.operating_seen is None:
                self.operating_seen = (round(now_rel, 4), now_m, time.time())
            if name == "emergency_control_cmd" and msg.longitudinal.acceleration < 0 and self.brake_seen is None:
                self.brake_seen = (round(now_rel, 4), now_m, time.time(), msg.longitudinal.acceleration)
        if name == "mrm_state":
            now = time.monotonic() - self.t0
            if self.mrm_last_t is not None:
                self.mrm_gap_max = max(self.mrm_gap_max, now - self.mrm_last_t)
            self.mrm_last_t = now
            key = (msg.state, msg.behavior)
            if key != self.last_mrm:
                self.last_mrm = key
                self.mrm_states.append((round(now, 3), msg.state, msg.behavior))
                self.get_logger().info(f"mrm_state -> state={msg.state} behavior={msg.behavior} at t={now:.3f}s wall={time.time():.6f}")

    def report(self):
        rel = time.monotonic() - self.t0
        print(f"t={rel:6.1f}s sent={self.sent} recv={self.recv} mrm_gap_max={self.mrm_gap_max:.3f}s", flush=True)
        if rel >= self.a.duration:
            raise SystemExit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=600)
    ap.add_argument("--stop-availability-at", type=float, default=None)
    ap.add_argument("--stop-after-first-mrm", type=float, default=None,
                    help="stop availability this many s after the first mrm_state arrives")
    ap.add_argument("--first-mrm-after-gap", action="store_true",
                    help="count the island's first mrm_state only after a >= 1 s silence (a reset)")
    ap.add_argument("--arm-after", type=float, default=6.0)
    ap.add_argument("--only", default="")
    ap.add_argument("--no-outputs", action="store_true")
    a = ap.parse_args()
    rclpy.init()
    n = Driver(a)
    try:
        rclpy.spin(n)
    except BaseException:
        pass
    summary = dict(duration=time.monotonic() - n.t0, sent=n.sent, recv=n.recv,
                   mrm_states=n.mrm_states, mrm_gap_max=round(n.mrm_gap_max, 3),
                   avail_stopped_at=n.avail_stopped_at,
                   last_avail=(n.avail_log[-1] if n.avail_log else None),
                   operating_seen=n.operating_seen, brake_seen=n.brake_seen,
                   host_last_avail_to_operating_ms=(round((n.operating_seen[1] - n.avail_log[-1][0]) * 1000, 1)
                                                    if n.operating_seen and n.avail_log else None),
                   host_last_avail_to_brake_ms=(round((n.brake_seen[1] - n.avail_log[-1][0]) * 1000, 1)
                                                if n.brake_seen and n.avail_log else None))
    print("SUMMARY " + json.dumps(summary), flush=True)

if __name__ == "__main__":
    main()
