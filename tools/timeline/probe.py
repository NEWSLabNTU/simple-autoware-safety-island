#!/usr/bin/env python3
"""The contract probe and logger (phase8-W7, design D7 and brief D G1).

  probe.py [--out build/timeline/live/probe.jsonl] [--model <system_model.yaml>]

Configured from the resolved SystemModel: every topic named in a `when:`
(a hazard's or a function's) is subscribed with the message type the model
gives it, and each predicate is evaluated on every sample; a change of truth
is one `predicate` event (value = true when the predicate holds: for a hazard
the fault is present, for a function the function is LOST). The contract's
`when:` keys come from the sidecar the model names in meta.inputs (sha256
checked): play_launch 92043c82 checks them but does not write them into the
SystemModel.

Also logged, for the timeline's lanes and its alignment anchors: every
availability sample (`sample`), the island's mrm_state, takeover-request
state, hazard lights and braking command, the operator's velocity limit, the
vehicle's control mode, hazard lights status and control command, and
|v| from /localization/kinematic_state (`velocity`, every sample).

Every event carries the receive time on CLOCK_MONOTONIC (time.monotonic_ns()).
Needs ROS 2 Humble + Autoware 1.5.0 msgs sourced (scripts/env.sh).
"""
import argparse
import importlib
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tlcommon as tl  # noqa: E402

import rclpy  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy  # noqa: E402


def msg_class(type_name):
    pkg, sub, name = type_name.split("/")
    return getattr(importlib.import_module(f"{pkg}.{sub}"), name)


def stamp_ns(s):
    return s.sec * 1_000_000_000 + s.nanosec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(tl.ROOT, "build/timeline/live/probe.jsonl"))
    ap.add_argument("--model", default=tl.MODEL)
    a = ap.parse_args()
    d = tl.declared(tl.load_model(a.model))
    w = tl.Writer(a.out)
    rclpy.init()
    node = rclpy.create_node("timeline_probe")
    vol = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
    latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
    subs = []

    # 1. every `when:`, grouped by topic
    by_topic = {}
    for p in d["predicates"]:
        t = d["topics"].get(p["topic"])
        if not t:
            sys.exit(f"probe: {p['topic']} (in the `when:` of {p['name']}) has no type in the model")
        p["type"] = t
        p["value_resolved"] = tl.resolve_constant(t, p["field"], p["value"])
        by_topic.setdefault(p["topic"], []).append(p)
    state = {}
    w.write("probe", "config", value=dict(
        predicates=[{k: p[k] for k in ("name", "kind", "topic", "field", "op", "value")} for p in d["predicates"]],
        windows=d["windows"], exits=d["exits"], entry_speed=d["entry_speed"],
        contract=os.path.relpath(d["contract"], tl.ROOT), model=os.path.relpath(a.model, tl.ROOT)))

    def on_pred_topic(topic, preds):
        def cb(msg):
            t = tl.now_ns()
            for p in preds:
                v = tl.get_field(msg, p["field"])
                holds = bool(tl.evaluate(p, v))
                key = (p["kind"], p["name"])
                if state.get(key) != holds:
                    state[key] = holds
                    w.write("probe", "predicate", t_mono_ns=t, hazard=p["name"] if p["kind"] == "hazard" else None,
                            marker=f"{p['kind']}:{p['name']}", value=holds, field=p["field"], observed=v,
                            topic=topic)
            if topic == "/system/operation_mode/availability":
                w.write("probe", "sample", t_mono_ns=t, marker="availability",
                        value=dict(autonomous=msg.autonomous, comfortable_stop=msg.comfortable_stop,
                                   emergency_stop=msg.emergency_stop, stamp_ns=stamp_ns(msg.stamp)))
            elif topic == "/vehicle/status/control_mode":
                if state.get(("cm", topic)) != msg.mode:
                    state[("cm", topic)] = msg.mode
                    w.write("probe", "sample", t_mono_ns=t, marker="control_mode",
                            value=dict(mode=msg.mode, name=tl.CONTROL_MODE.get(msg.mode)))
        return cb

    for topic, preds in by_topic.items():
        subs.append(node.create_subscription(msg_class(preds[0]["type"]), topic, on_pred_topic(topic, preds), vol))

    # 2. the lanes: states on change, signals every sample
    def on_change(name, fn):
        def cb(msg):
            t = tl.now_ns()
            v = fn(msg)
            if state.get(("chg", name)) != v:
                state[("chg", name)] = v
                w.write("probe", "sample", t_mono_ns=t, marker=name, value=v)
        return cb

    from autoware_adapi_v1_msgs.msg import MrmState
    from autoware_control_msgs.msg import Control
    from autoware_vehicle_msgs.msg import HazardLightsCommand, HazardLightsReport
    from nav_msgs.msg import Odometry
    from tier4_system_msgs.msg import MrmBehaviorStatus

    subs.append(node.create_subscription(
        MrmState, "/system/fail_safe/mrm_state",
        on_change("mrm_state", lambda m: dict(state=tl.MRM_STATE.get(m.state), behavior=tl.MRM_BEHAVIOR.get(m.behavior))),
        vol))
    subs.append(node.create_subscription(
        MrmBehaviorStatus, "/system/takeover_request/state",
        on_change("takeover_request_state", lambda m: tl.BEHAVIOR_STATUS.get(m.state)), vol))
    subs.append(node.create_subscription(
        MrmBehaviorStatus, "/system/mrm/emergency_stop/status",
        on_change("emergency_stop_status", lambda m: tl.BEHAVIOR_STATUS.get(m.state)), vol))
    subs.append(node.create_subscription(
        MrmBehaviorStatus, "/system/mrm/comfortable_stop/status",
        on_change("comfortable_stop_status", lambda m: tl.BEHAVIOR_STATUS.get(m.state)), vol))
    subs.append(node.create_subscription(
        HazardLightsCommand, "/system/emergency/hazard_lights_cmd",
        on_change("island_hazard_lights_cmd", lambda m: tl.HAZARD_LIGHTS.get(m.command)), vol))
    subs.append(node.create_subscription(
        HazardLightsReport, "/vehicle/status/hazard_lights_status",
        on_change("vehicle_hazard_lights", lambda m: {1: "DISABLE", 2: "ENABLE"}.get(m.report, m.report)), vol))

    def on_emerg(m):
        # the island operator's command, every sample (30 Hz): its first
        # braking sample is the emergency rung's safe-state command
        w.write("probe", "sample", marker="island_emergency_control_cmd",
                value=dict(acc=round(m.longitudinal.acceleration, 4), vel=round(m.longitudinal.velocity, 4)))
    subs.append(node.create_subscription(Control, "/system/emergency/control_cmd", on_emerg, vol))

    def on_ctrl(m):
        t = tl.now_ns()
        w.write("probe", "sample", t_mono_ns=t, marker="control_cmd",
                value=dict(acc=round(m.longitudinal.acceleration, 4), vel=round(m.longitudinal.velocity, 4)))
    subs.append(node.create_subscription(Control, "/control/command/control_cmd", on_ctrl, vol))

    try:
        from autoware_internal_planning_msgs.msg import VelocityLimit
        subs.append(node.create_subscription(
            VelocityLimit, "/planning/scenario_planning/max_velocity_candidates",
            lambda m: w.write("probe", "sample", marker="velocity_limit",
                              value=dict(max_velocity=m.max_velocity, sender=m.sender,
                                         use_constraints=m.use_constraints)), latched))
    except ImportError:
        pass

    def on_odom(m):
        w.write("probe", "velocity", marker="kinematic_state", value=round(abs(m.twist.twist.linear.x), 5))
    subs.append(node.create_subscription(Odometry, "/localization/kinematic_state", on_odom, vol))

    print(f"probe: {len(d['predicates'])} predicate(s) on {sorted(by_topic)} -> {a.out}", flush=True)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    while not stop:
        rclpy.spin_once(node, timeout_sec=0.1)
    w.close()
    os._exit(0)


if __name__ == "__main__":
    main()
