#!/usr/bin/env python3
"""The scenario controller (phase8-W7): the availability gate and the buttons.

  scenario.py gate  [--log F]      the availability gate (a process of its own)
  scenario.py press <button> [--log F]
  scenario.py buttons [--log F]    a window with the buttons
  scenario.py run a|b|encore [--log F]   the whole act, scripted

Buttons: odd-exit, odd-enter, takeover, hpc-loss, hpc-restore.

THE GATE stands in for takeover_demo's availability_gate (phase8-W3) on the
native_sim demo, under the same node name, so the live contract's
`/availability_gate/availability` names it truthfully: Autoware is launched
with operation_mode_availability_topic:=/system/operation_mode/availability_raw,
and the gate republishes every raw sample on /system/operation_mode/availability
(the island's guard) with `autonomous &= !odd_exit`, one out per one in, same
QoS, at 10 Hz from its own timer: each tick republishes the LATEST raw
sample while it is younger than RAW_MAX_AGE (1.0 s) and nothing once it is
older. One-out-per-one-in (W3's gate) passed the aggregator's jitter straight
to the island: on this host, loaded, Autoware's converter left gaps of 400 to
704 ms (run b1 of docs/takeover-trace.md), and one of 602 ms fired the
island's 500 ms HPC-loss timeout in the middle of the takeover window. A
stalled converter still stops the stream, 1.0 s later.

The ODD flag is SIGUSR1 (exit) / SIGUSR2 (enter) to the gate, or a
std_msgs/Bool on /demo/odd/exit (the topic W3's odd_monitor publishes). The
gate's pid is in build/timeline/gate.pid. It writes a `gate` event for the
first sample it publishes with a new `autonomous` value: the fault on the
wire, which is where the odd_exit hazard's detection ends; and a `stall`
event whenever its own timer (`tick`) or the raw stream (`availability_raw`)
was more than GATE_STALL_MS (250) late, so a silence the island sees can be
laid at the door of the gate or of Autoware's converter.

THE BUTTONS: odd-exit / odd-enter signal the gate. takeover asks the VEHICLE
for MANUAL (/control/control_mode_request, the planning simulator's service),
as takeover_demo's takeover_hmi does: the takeover is vehicle-sensed, as in a
real L3. hpc-loss SIGSTOPs the gate (the availability stream stops; the island
alone detects it), hpc-restore SIGCONTs it. Each press is a `scenario`
`inject` event on CLOCK_MONOTONIC.

`run` does the whole act from a fresh Autoware: initial pose, goal, engage,
drive DRIVE_SECS past MIN_SPEED, then
  a       odd-exit, takeover after RESPOND_AFTER s (3), observe
  b       odd-exit, nobody answers, observe to standstill
  encore  hpc-loss, observe to standstill, hpc-restore
and prints one VERDICT line (exit 0 = PASS). Env: DRIVE_SECS (3),
RESPOND_AFTER (3), OBSERVE_SECS (30), MIN_SPEED (1.0), INIT_*/GOAL_* as
demo/scenario_driver.py.
"""
import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tlcommon as tl  # noqa: E402

GATE_PID = os.path.join(tl.ROOT, "build/timeline/gate.pid")
RAW = "/system/operation_mode/availability_raw"
AVAIL = "/system/operation_mode/availability"
ENV = os.environ.get


def default_log():
    return os.path.join(tl.ROOT, "build/timeline/live/scenario.jsonl")


# ------------------------------------------------------------- the gate ----
def gate(log):
    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import Bool
    from tier4_system_msgs.msg import OperationModeAvailability

    w = tl.Writer(log)
    rclpy.init()
    node = rclpy.create_node("availability_gate")
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
    pub = node.create_publisher(OperationModeAvailability, AVAIL, qos)
    st = dict(odd_exit=False, last=None, n=0)
    raw_max_age_ns = int(float(ENV("RAW_MAX_AGE", "1.0")) * 1e9)

    def set_odd(v, how):
        if st["odd_exit"] != v:
            st["odd_exit"] = v
            w.write("gate", "odd", hazard="odd_exit", value=v, how=how)
            print(f"gate: odd_exit -> {v} ({how})", flush=True)

    signal.signal(signal.SIGUSR1, lambda *_: set_odd(True, "SIGUSR1"))
    signal.signal(signal.SIGUSR2, lambda *_: set_odd(False, "SIGUSR2"))
    node.create_subscription(Bool, "/demo/odd/exit", lambda m: set_odd(bool(m.data), "/demo/odd/exit"), qos)

    stall_ns = int(float(ENV("GATE_STALL_MS", "250")) * 1e6)

    def on_raw(raw):
        t = tl.now_ns()
        if st.get("raw_t") is not None and t - st["raw_t"] > stall_ns:
            # the converter (Autoware) was late: which side of the gate a
            # gap the island sees came from (docs/takeover-trace.md, b3/b4)
            w.write("gate", "stall", t_mono_ns=t, marker="availability_raw",
                    value=dict(gap_ms=round((t - st["raw_t"]) / 1e6, 3)))
        st["raw"], st["raw_auto"], st["raw_t"] = raw, bool(raw.autonomous), t

    def on_tick():
        # 10 Hz from the gate's own timer: the latest raw sample while it is
        # fresh (RAW_MAX_AGE in the module doc); nothing once it is not.
        tn = tl.now_ns()
        if st.get("tick_t") is not None and tn - st["tick_t"] > stall_ns:
            # the gate itself was late (its 10 Hz timer did not run)
            w.write("gate", "stall", t_mono_ns=tn, marker="tick",
                    value=dict(gap_ms=round((tn - st["tick_t"]) / 1e6, 3)))
        st["tick_t"] = tn
        if st.get("raw") is None or tn - st["raw_t"] > raw_max_age_ns:
            return
        out = st["raw"]
        out.autonomous = bool(st["raw_auto"] and not st["odd_exit"])
        pub.publish(out)
        t = tl.now_ns()
        st["n"] += 1
        if out.autonomous != st["last"]:
            w.write("gate", "publish", t_mono_ns=t, hazard="odd_exit", marker="availability",
                    value=dict(autonomous=out.autonomous, raw_autonomous=st["raw_auto"], n=st["n"]))
            print(f"gate: availability.autonomous -> {out.autonomous} (sample {st['n']})", flush=True)
            st["last"] = out.autonomous
        with open(GATE_PID + ".count", "w") as f:  # read by hpc-loss: the last sample before the stop
            f.write(f"{st['n']} {t}\n")

    node.create_subscription(OperationModeAvailability, RAW, on_raw, qos)
    node.create_timer(0.1, on_tick)
    os.makedirs(os.path.dirname(GATE_PID), exist_ok=True)
    with open(GATE_PID, "w") as f:
        f.write(f"{os.getpid()}\n")
    print(f"gate: {RAW} -> {AVAIL} (pid {os.getpid()}), log {log}", flush=True)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    while not stop:
        rclpy.spin_once(node, timeout_sec=0.1)
    os._exit(0)


def gate_pid():
    try:
        pid = int(open(GATE_PID).read().split()[0])
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError, IndexError):
        sys.exit(f"scenario: no running gate (pid file {GATE_PID}); start `scenario.py gate` first")


# ---------------------------------------------------------- the buttons ----
class Buttons:
    def __init__(self, log, node=None):
        self.w = tl.Writer(log)
        self.node = node

    def _ros(self):
        if self.node is None:
            import rclpy
            rclpy.init()
            self.node = rclpy.create_node("timeline_scenario")
        return self.node

    def press(self, button):
        if button == "odd-exit":
            t = tl.now_ns()
            os.kill(gate_pid(), signal.SIGUSR1)
            self.w.write("scenario", "inject", t_mono_ns=t, hazard="odd_exit", marker="odd_exit",
                         value="SIGUSR1 to the availability gate")
        elif button == "odd-enter":
            t = tl.now_ns()
            os.kill(gate_pid(), signal.SIGUSR2)
            self.w.write("scenario", "inject", t_mono_ns=t, hazard="odd_exit", marker="odd_enter",
                         value="SIGUSR2 to the availability gate")
        elif button == "hpc-loss":
            pid = gate_pid()
            t = tl.now_ns()
            os.kill(pid, signal.SIGSTOP)
            t1 = tl.now_ns()
            try:
                n, tl_last = open(GATE_PID + ".count").read().split()
            except (OSError, ValueError):
                n, tl_last = None, None
            self.w.write("scenario", "inject", t_mono_ns=t, hazard="hpc_loss", marker="hpc_loss",
                         value=dict(how="SIGSTOP the availability gate", pid=pid, t_after_ns=t1,
                                    gate_samples=int(n) if n else None))
            if tl_last:
                self.w.write("gate", "last", t_mono_ns=int(tl_last), hazard="hpc_loss", marker="availability",
                             value=dict(n=int(n)))
        elif button == "hpc-restore":
            t = tl.now_ns()
            os.kill(gate_pid(), signal.SIGCONT)
            self.w.write("scenario", "inject", t_mono_ns=t, hazard="hpc_loss", marker="hpc_restore",
                         value="SIGCONT the availability gate")
        elif button == "takeover":
            from autoware_vehicle_msgs.srv import ControlModeCommand
            import rclpy
            node = self._ros()
            cli = node.create_client(ControlModeCommand, "/control/control_mode_request")
            if not cli.wait_for_service(timeout_sec=5.0):
                print("scenario: /control/control_mode_request not available", flush=True)
            req = ControlModeCommand.Request()
            req.mode = ControlModeCommand.Request.MANUAL
            t = tl.now_ns()
            fut = cli.call_async(req)
            self.w.write("scenario", "inject", t_mono_ns=t, marker="takeover",
                         value="control_mode_request MANUAL")
            t0 = time.time()
            while not fut.done() and time.time() - t0 < 5.0:
                rclpy.spin_once(node, timeout_sec=0.05)
            ok = fut.done() and fut.result() is not None and fut.result().success
            self.w.write("scenario", "reply", marker="takeover", value=dict(success=bool(ok)))
        else:
            sys.exit(f"scenario: unknown button {button}")
        print(f"scenario: pressed {button}", flush=True)


def buttons_window(log):
    from pyqtgraph.Qt import QtWidgets
    b = Buttons(log)
    app = QtWidgets.QApplication([])
    win = QtWidgets.QWidget()
    win.setWindowTitle("takeover scenario")
    lay = QtWidgets.QVBoxLayout(win)
    for name, label in (("odd-exit", "ODD exit"), ("takeover", "Driver takes over"),
                        ("hpc-loss", "HPC loss"), ("odd-enter", "Back in the ODD"),
                        ("hpc-restore", "HPC restored")):
        btn = QtWidgets.QPushButton(label)
        btn.setMinimumHeight(48)
        btn.clicked.connect(lambda _=False, n=name: b.press(n))
        lay.addWidget(btn)
    win.show()
    app.exec_()


# ------------------------------------------------------------- the acts ----
def run(act, log):
    import rclpy
    sys.path.insert(0, os.path.join(tl.ROOT, "demo"))
    import scenario_driver as sd  # the demo's pose, goal and helpers
    from autoware_adapi_v1_msgs.msg import MrmState
    from autoware_adapi_v1_msgs.srv import ChangeOperationMode
    from autoware_planning_msgs.msg import RouteState
    from autoware_vehicle_msgs.msg import ControlModeReport
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
    from nav_msgs.msg import Odometry
    from rclpy.qos import DurabilityPolicy, QoSProfile
    from tier4_system_msgs.msg import MrmBehaviorStatus

    drive = float(ENV("DRIVE_SECS", "3"))
    respond = float(ENV("RESPOND_AFTER", "3"))
    observe = float(ENV("OBSERVE_SECS", "30"))
    min_speed = float(ENV("MIN_SPEED", "1.0"))
    rclpy.init()
    node = rclpy.create_node("timeline_scenario")
    b = Buttons(log, node)
    st = dict(v=None, mrm=None, tor=None, ctrl=None, route=None)
    q = QoSProfile(depth=5)
    ql = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    node.create_subscription(Odometry, "/localization/kinematic_state",
                             lambda m: st.update(v=m.twist.twist.linear.x), q)
    node.create_subscription(MrmState, "/system/fail_safe/mrm_state",
                             lambda m: st.update(mrm=(m.state, m.behavior)), q)
    node.create_subscription(MrmBehaviorStatus, "/system/takeover_request/state",
                             lambda m: st.update(tor=m.state), q)
    node.create_subscription(ControlModeReport, "/vehicle/status/control_mode",
                             lambda m: st.update(ctrl=m.mode), q)
    node.create_subscription(RouteState, "/planning/route_state", lambda m: st.update(route=m.state), ql)

    def spin_for(secs, until=None):
        t0 = time.time()
        while time.time() - t0 < secs:
            rclpy.spin_once(node, timeout_sec=0.05)
            if until and until():
                return True
        return bool(until and until())

    def say(s):
        print(f"[{time.strftime('%H:%M:%S')}] {s}", flush=True)

    say("== 0. wait for the planning stack ==")
    if not spin_for(300, lambda: st["route"] is not None):
        say("FATAL: no /planning/route_state in 300 s"); os._exit(2)
    gate_pid()
    say("== 1. initial pose ==")
    pub = node.create_publisher(PoseWithCovarianceStamped, "/initialpose", 1)
    m = PoseWithCovarianceStamped()
    m.header.frame_id = "map"
    m.pose.pose.position.x, m.pose.pose.position.y = sd.INIT[0], sd.INIT[1]
    m.pose.pose.orientation.z, m.pose.pose.orientation.w = sd.INIT[2], sd.INIT[3]
    m.pose.covariance[0] = m.pose.covariance[7] = 0.25
    m.pose.covariance[35] = 0.068
    for _ in range(3):
        pub.publish(m)
        spin_for(1.0)
    spin_for(4.0)
    say("== 2. goal ==")
    pg = node.create_publisher(PoseStamped, "/planning/mission_planning/goal", 1)
    g = PoseStamped()
    g.header.frame_id = "map"
    g.pose.position.x, g.pose.position.y = sd.GOAL[0], sd.GOAL[1]
    g.pose.orientation.z, g.pose.orientation.w = sd.GOAL[2], sd.GOAL[3]
    for _ in range(10):
        pg.publish(g)
        if spin_for(4.0, lambda: st["route"] == RouteState.SET):
            break
    if st["route"] != RouteState.SET:
        say("FATAL: route not set"); os._exit(2)
    say("== 3. engage ==")
    cli = node.create_client(ChangeOperationMode, "/api/operation_mode/change_to_autonomous")
    for i in range(8):
        if not cli.wait_for_service(timeout_sec=5):
            continue
        fut = cli.call_async(ChangeOperationMode.Request())
        t0 = time.time()
        while not fut.done() and time.time() - t0 < 10:
            rclpy.spin_once(node, timeout_sec=0.1)
        ok = fut.done() and fut.result() and fut.result().status.success
        say(f"engage attempt {i + 1}: {ok}")
        if ok:
            break
        spin_for(4.0)
    if not spin_for(60, lambda: (st["v"] or 0) > min_speed):
        say(f"FATAL: the vehicle did not reach {min_speed} m/s (v={st['v']})"); os._exit(2)
    spin_for(drive)
    v0 = st["v"]
    say(f"== 4. driving at {v0:.2f} m/s; mrm {st['mrm']}, TOR {st['tor']}, control mode {st['ctrl']} ==")
    ok, why = False, ""
    t_inject = time.time()
    if act in ("a", "b"):
        b.press("odd-exit")
        tor_on = spin_for(3.0, lambda: st["tor"] == 2)
        say(f"takeover request on: {tor_on}")
        if act == "a":
            spin_for(respond)
            b.press("takeover")
            spin_for(8.0, lambda: st["tor"] == 1 and st["ctrl"] == ControlModeReport.MANUAL)
            spin_for(max(0.0, 14.0 - (time.time() - t_inject)))  # past the would-be expiry
            mrm_normal = st["mrm"] is not None and st["mrm"][0] == MrmState.NORMAL
            ok = tor_on and st["tor"] == 1 and st["ctrl"] == ControlModeReport.MANUAL and mrm_normal
            why = f"TOR on {tor_on}, TOR now {st['tor']}, control mode {st['ctrl']}, mrm {st['mrm']}"
        else:
            spin_for(observe, lambda: st["mrm"] and st["mrm"][0] == MrmState.MRM_SUCCEEDED)
            spin_for(1.0)
            ok = (tor_on and st["mrm"] is not None and st["mrm"][0] == MrmState.MRM_SUCCEEDED
                  and st["mrm"][1] == 3 and st["v"] is not None and abs(st["v"]) < 0.01)
            why = f"TOR on {tor_on}, mrm {st['mrm']} (3 = COMFORTABLE_STOP), v {st['v']:.3f}"
        spin_for(1.0)
        b.press("odd-enter")
        spin_for(3.0)
    elif act == "encore":
        b.press("hpc-loss")
        spin_for(observe, lambda: st["mrm"] and st["mrm"][0] == MrmState.MRM_SUCCEEDED)
        spin_for(1.0)
        ok = st["mrm"] is not None and st["mrm"][0] == MrmState.MRM_SUCCEEDED and st["mrm"][1] == 2 \
            and st["v"] is not None and abs(st["v"]) < 0.01
        why = f"mrm {st['mrm']} (2 = EMERGENCY_STOP), v {st['v']:.3f}"
        b.press("hpc-restore")
        spin_for(5.0, lambda: st["mrm"] and st["mrm"][0] == MrmState.NORMAL)
        why += f", after restore mrm {st['mrm']}"
    else:
        sys.exit(f"scenario: unknown act {act}")
    say(f"VERDICT: {'PASS' if ok else 'FAIL'} {act}: v at the fault {v0:.2f} m/s; {why}")
    b.w.write("scenario", "verdict", marker=act, value=dict(ok=bool(ok), why=why, v0=v0))
    os._exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["gate", "press", "buttons", "run"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--log", default=None)
    a = ap.parse_args()
    if a.cmd == "gate":
        gate(a.log or os.path.join(os.path.dirname(default_log()), "gate.jsonl"))
    elif a.cmd == "press":
        Buttons(a.log or default_log()).press(a.arg)
        os._exit(0)
    elif a.cmd == "buttons":
        buttons_window(a.log or default_log())
    else:
        run(a.arg, a.log or default_log())


if __name__ == "__main__":
    main()
