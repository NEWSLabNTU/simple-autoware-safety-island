#!/usr/bin/env python3
"""The scenario controller (phase8-W7, W16): the availability gate and the buttons.

  scenario.py gate  [--log F]      the availability gate (a process of its own)
  scenario.py press <button> [--log F]
  scenario.py buttons [--log F]    a window with the buttons
  scenario.py run a|b|encore [--log F]   the whole act, scripted

Buttons: odd-exit, odd-enter, takeover, hpc-loss, hpc-restore.

THE GATE stands in for takeover_demo's availability_gate (phase8-W3) on the
native_sim demo, under the same node name, so the live contract's
`/availability_gate/availability` names it truthfully: Autoware is launched
with operation_mode_availability_topic:=/system/operation_mode/availability_raw,
and the gate republishes on /system/operation_mode/availability (the
island's guard) with `autonomous &= !odd_exit`, same QoS, at 10 Hz from its
own timer: each tick republishes the LATEST raw sample while it is younger
than RAW_MAX_AGE (1.0 s) and nothing once it is older. One-out-per-one-in
(W3's gate) passed the aggregator's jitter straight to the island: on this
host, loaded, Autoware's converter left gaps of 400 to 704 ms (run b1 of
docs/takeover-trace.md), and one of 602 ms fired the island's 500 ms
HPC-loss timeout in the middle of the takeover window. A stalled converter
still stops the stream, 1.0 s later.

`scenario.py gate` execs the C++ gate, demo/host_ws/src/availability_gate
(phase8-W16; `just demo-host-ws` builds it), through its gate-rt wrapper
(SCHED_FIFO when the rtprio limit allows). W7's rclpy gate went silent for
250-1134 ms on a loaded host: its one executor thread rewrote a count file
every tick and ext4 blocked the truncating close() behind writeback
(docs/takeover-trace.md, "The gate stall"). The C++ gate does no file I/O
on its executor thread.

The ODD flag is SIGUSR1 (exit) / SIGUSR2 (enter) to the gate, or a
std_msgs/Bool on /demo/odd/exit (the topic W3's odd_monitor publishes). The
gate's pid is in build/timeline/gate.pid, followed by the path of its count
record ("<samples> <t of the last>", on /dev/shm), which hpc-loss reads. It
writes a `gate` event for the first sample it publishes with a new
`autonomous` value: the fault on the wire, which is where the odd_exit
hazard's detection ends; a `stall` event whenever its own timer (`tick`) or
the raw stream (`availability_raw`) was more than GATE_STALL_MS (250) late,
so a silence the island sees can be laid at the door of the gate or of
Autoware's converter; and a `stats` event at exit with its largest publish
gap.

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

SCENARIO_SIM=carla (CARLA demo unit C3, run-board.sh --sim carla): the world
is CARLA's and an SSv2 scenario, started beside this act, poses, routes and
engages the ego, so steps 1-3 are skipped and the act waits up to
ENGAGE_SECS (300) for the ego to move. The act also reads /clock and writes
a `scenario` `rtf` event: simulated over wall seconds from the fault to the
verdict (docs/design/carla-island-demo.md 4.2: the island's terms are wall
time, the vehicle's sim time; an act below 0.95 is not judged), and holds
CARLA_HOLD_SECS (5) before the restore buttons (odd-enter, hpc-restore), so
the stop lasts long enough for the scenario's StandStillCondition (3 s of
sim time) before Autoware may drive on.
SCENARIO_TRIGGER=scenario (CARLA demo unit C4, run-board.sh --sim carla's
default): the scenario, not this act, decides when the fault comes, at its
place on the road. encore: the scenario's CustomCommandAction runs
demo/carla/act_trigger.py, which sends `hpc-loss` to the unix datagram
socket SCENARIO_ACT_SOCKET, bound here before anything else; the act then
presses hpc-loss as before (the press is the measured edge; the datagram's
arrival and the ego's pose go in a `trigger` event). a and b: no press;
odd_monitor (started by run-board.sh with the scenario's own ODD,
scenario_file:=) sees the ego leave the polygon and publishes
/demo/odd/exit, the gate takes it as it takes SIGUSR1. The act's start edge
(the `inject` event the tables measure from) is the gate's receipt of that
verdict, its `odd` event in gate.jsonl (SCENARIO_GATE_LOG, default beside
--log): where the contract's odd_exit detection starts (the gate's 10 Hz
timer, 126 ms). odd_monitor's own `ODD EXIT (<reason>) wall= mono=` line
(SCENARIO_ODD_LOG, default odd_monitor.log beside --log) gives the reason,
the pose and the stamp; the hop from it to the gate is reported in the
`trigger` event, not charged. odd-enter is not pressed afterwards: the
monitor's verdict is latched and would set the flag again. Both wait up to
TRIGGER_SECS (180) after the ego drives. The act also records Autoware's
external velocity limit (/planning/scenario_planning/max_velocity_default,
what SSv2's setVelocityLimit reaches, and the selector's
/planning/scenario_planning/max_velocity) in a `velocity_limit` event.
SCENARIO_REARM (run-board.sh --sim carla, board): a command run once the ego
drives, before DRIVE_SECS, that re-arms the island's trace window
(readout.py --rearm-only, attach, no halt): with CARLA the scenario takes a
minute or more from the island's arming to the act, longer than the window
holds (c3-b1 filled it 15 s before the act's end), so the window is opened
at the act as on a --keep-boot act. A `scenario` `rearm` event records it.
"""
import argparse
import json
import os
import re
import signal
import socket
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
    """Exec the C++ gate (demo/host_ws/src/availability_gate, phase8-W16)."""
    try:
        from ament_index_python.packages import PackageNotFoundError, get_package_prefix
        prefix = get_package_prefix("availability_gate")
    except (ImportError, PackageNotFoundError):
        sys.exit("scenario: the availability_gate package is not on AMENT_PREFIX_PATH; "
                 "build the overlay (`just demo-host-ws`) and source scripts/env.sh")
    exe = os.path.join(prefix, "lib/availability_gate/gate-rt")
    os.makedirs(os.path.dirname(GATE_PID), exist_ok=True)
    argv = [exe, "--log", log, "--pid-file", GATE_PID, "--ros-args", "--disable-external-lib-logs",
            "-p", "raw_max_age_ms:=%d" % round(float(ENV("RAW_MAX_AGE", "1.0")) * 1000),
            "-p", "stall_ms:=%d" % round(float(ENV("GATE_STALL_MS", "250")))]
    sys.stdout.flush()
    os.execv(exe, argv)


def gate_pid():
    try:
        pid = int(open(GATE_PID).read().split()[0])
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError, IndexError):
        sys.exit(f"scenario: no running gate (pid file {GATE_PID}); start `scenario.py gate` first")


def gate_count_path():
    # "<pid> <count record>" (the C++ gate keeps the record on /dev/shm)
    f = open(GATE_PID).read().split()
    return f[1] if len(f) > 1 else GATE_PID + ".count"


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
            try:  # the gate's count record: "<samples> <t of the last>", read while it is stopped
                n, tl_last = open(gate_count_path()).read().split()[:2]
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
    from autoware_planning_msgs.msg import RouteState
    from autoware_vehicle_msgs.msg import ControlModeReport
    from nav_msgs.msg import Odometry
    from rclpy.qos import DurabilityPolicy, QoSProfile
    from tier4_system_msgs.msg import MrmBehaviorStatus

    trigger = ENV("SCENARIO_TRIGGER", "button")
    sock = None
    if trigger == "scenario" and act == "encore":
        # bound before anything else: the scenario may reach its trigger
        # while this act still waits for the ego (it never has, but a lost
        # datagram would be a silent no-act)
        path = ENV("SCENARIO_ACT_SOCKET") or sys.exit("scenario: SCENARIO_TRIGGER=scenario needs SCENARIO_ACT_SOCKET")
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(path)
        sock.setblocking(False)
    drive = float(ENV("DRIVE_SECS", "3"))
    respond = float(ENV("RESPOND_AFTER", "3"))
    observe = float(ENV("OBSERVE_SECS", "30"))
    min_speed = float(ENV("MIN_SPEED", "1.0"))
    carla = ENV("SCENARIO_SIM", "planning") == "carla"
    hold = float(ENV("CARLA_HOLD_SECS", "5")) if carla else 0.0
    rclpy.init()
    node = rclpy.create_node("timeline_scenario")
    b = Buttons(log, node)
    st = dict(v=None, mrm=None, tor=None, ctrl=None, route=None, x=None, y=None, odd=None, vlim={})
    q = QoSProfile(depth=5)
    ql = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    node.create_subscription(Odometry, "/localization/kinematic_state",
                             lambda m: st.update(v=m.twist.twist.linear.x, x=m.pose.pose.position.x,
                                                 y=m.pose.pose.position.y), q)
    node.create_subscription(MrmState, "/system/fail_safe/mrm_state",
                             lambda m: st.update(mrm=(m.state, m.behavior)), q)
    node.create_subscription(MrmBehaviorStatus, "/system/takeover_request/state",
                             lambda m: st.update(tor=m.state), q)
    node.create_subscription(ControlModeReport, "/vehicle/status/control_mode",
                             lambda m: st.update(ctrl=m.mode), q)
    node.create_subscription(RouteState, "/planning/route_state", lambda m: st.update(route=m.state), ql)
    if trigger == "scenario":
        from std_msgs.msg import Bool
        node.create_subscription(Bool, "/demo/odd/exit", lambda m: st.update(odd=m.data), q)
        try:
            from autoware_internal_planning_msgs.msg import VelocityLimit
            for topic in ("/planning/scenario_planning/max_velocity_default", "/planning/scenario_planning/max_velocity"):
                node.create_subscription(
                    VelocityLimit, topic,
                    lambda m, t=topic: st["vlim"].update({t: dict(max_velocity=round(m.max_velocity, 3), sender=m.sender)}),
                    ql)
        except ImportError:
            pass
    clock = dict(sim=None, wall=None)  # the latest /clock sample and the wall time it arrived
    if carla:
        from rclpy.qos import ReliabilityPolicy
        from rosgraph_msgs.msg import Clock
        node.create_subscription(
            Clock, "/clock",
            lambda m: clock.update(sim=m.clock.sec + m.clock.nanosec * 1e-9, wall=time.monotonic()),
            QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT))

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
    if carla:
        engage = float(ENV("ENGAGE_SECS", "300"))
        say(f"== 1-3. CARLA: the SSv2 scenario poses, routes and engages the ego (up to {engage:.0f} s) ==")
        if not spin_for(engage, lambda: (st["v"] or 0) > min_speed):
            say(f"FATAL: the vehicle did not reach {min_speed} m/s (v={st['v']}, route {st['route']})"); os._exit(2)
        rearm = ENV("SCENARIO_REARM", "")
        if rearm:
            import subprocess
            t = tl.now_ns()
            # its own session, killed whole on a timeout: c4-e1's re-arm wrote
            # the word (the window counted it) and then never exited under a
            # 1-min load of 54; subprocess.run's timeout killed the shell, the
            # pyocd process kept the probe and the readout after the act
            # failed with "Resource busy"
            pr = subprocess.Popen(rearm, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, start_new_session=True)
            try:
                o, _ = pr.communicate(timeout=float(ENV("SCENARIO_REARM_TIMEOUT", "60")))
                rc = pr.returncode
            except subprocess.TimeoutExpired:
                os.killpg(pr.pid, signal.SIGKILL)
                o, _ = pr.communicate()
                rc = "timeout"
            out = (o or "").strip().splitlines()
            done = next((l for l in out if "re-armed:" in l), out[-1] if out else "")
            say(f"trace window re-armed (exit {rc}): {done}")
            b.w.write("scenario", "rearm", t_mono_ns=t, value=dict(rc=rc, out=done))
    else:
        engage_planning(node, st, spin_for, say, sd, min_speed)
    log_dir = os.path.dirname(os.path.abspath(log))
    if trigger == "scenario":
        trig = scenario_trigger(act, b, st, sock, spin_for, say, log_dir)
        if trig is None:
            os._exit(2)
    else:
        spin_for(drive)
    v0 = st["v"]
    say(f"== 4. driving at {v0:.2f} m/s; mrm {st['mrm']}, TOR {st['tor']}, control mode {st['ctrl']} ==")
    if trigger == "scenario":
        b.w.write("scenario", "velocity_limit", value=st["vlim"])
        say(f"velocity limit: {st['vlim'] or '- (none received)'}")
    ok, why = False, ""
    t_inject = time.time()
    c0 = (clock["sim"], clock["wall"])
    if act in ("a", "b"):
        if trigger != "scenario":
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
        c1 = (clock["sim"], clock["wall"])
        spin_for(1.0 + hold)
        if trigger != "scenario":  # odd_monitor's verdict is latched: it would set the flag again
            b.press("odd-enter")
        spin_for(3.0)
    elif act == "encore":
        if trigger != "scenario":  # scenario_trigger pressed it on the scenario's word
            b.press("hpc-loss")
        spin_for(observe, lambda: st["mrm"] and st["mrm"][0] == MrmState.MRM_SUCCEEDED)
        spin_for(1.0)
        ok = st["mrm"] is not None and st["mrm"][0] == MrmState.MRM_SUCCEEDED and st["mrm"][1] == 2 \
            and st["v"] is not None and abs(st["v"]) < 0.01
        why = f"mrm {st['mrm']} (2 = EMERGENCY_STOP), v {st['v']:.3f}"
        c1 = (clock["sim"], clock["wall"])
        spin_for(hold)
        b.press("hpc-restore")
        spin_for(5.0, lambda: st["mrm"] and st["mrm"][0] == MrmState.NORMAL)
        why += f", after restore mrm {st['mrm']}"
    else:
        sys.exit(f"scenario: unknown act {act}")
    rtf = None
    if carla:
        if None not in c0 and None not in c1 and c1[1] > c0[1]:
            rtf = (c1[0] - c0[0]) / (c1[1] - c0[1])
            b.w.write("scenario", "rtf", marker=act,
                      value=dict(rtf=round(rtf, 4), sim_s=round(c1[0] - c0[0], 3), wall_s=round(c1[1] - c0[1], 3)))
            why += f"; RTF {rtf:.3f} ({c1[0] - c0[0]:.2f} sim s over {c1[1] - c0[1]:.2f} wall s)"
        else:
            b.w.write("scenario", "rtf", marker=act, value=dict(rtf=None))
            why += "; RTF - (no /clock)"
    say(f"VERDICT: {'PASS' if ok else 'FAIL'} {act}: v at the fault {v0:.2f} m/s; {why}")
    b.w.write("scenario", "verdict", marker=act, value=dict(ok=bool(ok), why=why, v0=v0, rtf=rtf))
    os._exit(0 if ok else 1)


ODD_EXIT_LINE = re.compile(r"ODD EXIT \((.*)\) wall=([0-9.]+) mono=([0-9.]+)")


def scenario_trigger(act, b, st, sock, spin_for, say, log_dir):
    """SCENARIO_TRIGGER=scenario: wait for the scenario's fault (module doc).

    encore: the scenario's `hpc-loss` datagram, then the press. a/b: the
    ODD exit odd_monitor publishes; the `inject` event is written at the
    gate's receipt of it. Returns the `trigger` event's value, or None
    (FATAL said) when nothing came within TRIGGER_SECS."""
    wait = float(ENV("TRIGGER_SECS", "180"))
    say(f"== 4. the scenario's trigger ({'hpc-loss datagram' if act == 'encore' else 'ODD exit from odd_monitor'}),"
        f" up to {wait:.0f} s ==")
    if act == "encore":
        got = {}

        def recv():
            try:
                got["cmd"] = sock.recv(256).decode(errors="replace").strip()
                got["t"] = tl.now_ns()
            except BlockingIOError:
                pass
            return "cmd" in got
        if not spin_for(wait, recv):
            say(f"FATAL: no trigger from the scenario in {wait:.0f} s (v={st['v']}, pose {st['x']}, {st['y']})")
            return None
        pose = (st["x"], st["y"], st["v"])
        if got["cmd"] != "hpc-loss":
            say(f"FATAL: the scenario sent {got['cmd']!r}, not hpc-loss")
            return None
        b.press("hpc-loss")
        val = dict(how="scenario", cmd=got["cmd"], t_datagram_ns=got["t"], x=pose[0], y=pose[1], v=pose[2])
        b.w.write("scenario", "trigger", t_mono_ns=got["t"], hazard="hpc_loss", marker="hpc_loss", value=val)
        say(f"trigger: hpc-loss from the scenario at ({pose[0]:.1f}, {pose[1]:.1f}), {pose[2]:.2f} m/s")
        return val
    if not spin_for(wait, lambda: st["odd"] is True):
        say(f"FATAL: no ODD exit in {wait:.0f} s (v={st['v']}, pose {st['x']}, {st['y']})")
        return None
    pose = (st["x"], st["y"], st["v"])
    gate_log = ENV("SCENARIO_GATE_LOG", os.path.join(log_dir, "gate.jsonl"))
    odd_log = ENV("SCENARIO_ODD_LOG", os.path.join(log_dir, "odd_monitor.log"))
    t_gate = reason = t_odd = None
    t0 = time.time()
    while time.time() - t0 < 3.0 and (t_gate is None or t_odd is None):
        try:
            for line in open(gate_log):
                e = json.loads(line)
                if e.get("kind") == "odd" and e.get("value") is True:
                    # the gate's first flip to true (its log is this run's
                    # alone); not "before we saw it": this act can take the
                    # topic sample a millisecond before the gate does (c4-b1)
                    t_gate = e["t_mono_ns"]
                    break
        except (OSError, ValueError):
            pass
        try:
            for line in open(odd_log, errors="replace"):
                m = ODD_EXIT_LINE.search(line)
                if m:
                    reason, t_odd = m.group(1), int(round(float(m.group(3)) * 1e9))
        except OSError:
            pass
        spin_for(0.1)
    if t_gate is None:
        say(f"FATAL: odd_exit seen on /demo/odd/exit but no `odd` event in {gate_log}")
        return None
    b.w.write("scenario", "inject", t_mono_ns=t_gate, hazard="odd_exit", marker="odd_exit",
              value=dict(how="odd_monitor's /demo/odd/exit, received by the gate", reason=reason))
    hop = None if t_odd is None else round((t_gate - t_odd) / 1e6, 2)
    val = dict(how="odd_monitor", reason=reason, t_odd_exit_ns=t_odd, t_gate_ns=t_gate, odd_to_gate_ms=hop,
               x=pose[0], y=pose[1], v=pose[2])
    b.w.write("scenario", "trigger", t_mono_ns=t_odd or t_gate, hazard="odd_exit", marker="odd_exit", value=val)
    say(f"trigger: ODD EXIT ({reason}); odd_monitor -> gate {hop} ms")
    return val


def engage_planning(node, st, spin_for, say, sd, min_speed):
    """Steps 1-3 on the planning simulator: initial pose, goal, engage."""
    import rclpy
    from autoware_adapi_v1_msgs.srv import ChangeOperationMode
    from autoware_planning_msgs.msg import RouteState
    from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
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
