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
demo/scenario_driver.py. SCENARIO_FAULT_CMD (encore, phase11-S7): a command
run once the vehicle drives, before the fault, that arms the handler's
fault-tick overrun (run-board.sh RB_OVERRUN); an `overrun_armed` event
records it.

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
SCENARIO_REARM (run-board.sh --sim carla, board): the command that re-arms
the island's trace window (readout.py --rearm-only, attach, no halt): with
CARLA the scenario takes a minute or more from the island's arming to the
act, longer than the window holds (c3-b1 filled it 15 s before the act's
end), so the window is opened at the act as on a --keep-boot act. The
encore (and RB_TRIGGER=button) runs it once the ego drives, before
DRIVE_SECS: its fault comes about 11 s later (c5-e3: 11,884 B over 20 s).
a and b (SCENARIO_ODD_FILE, the scenario's .xosc) re-arm at the ODD exit
instead: from the first drive their window ran past the stop to the
readout and c5-b2 used 50,410 of 53,248 B over 74.9 s. The command starts
with --wait-go when the ego drives (the ELF's symbols, pyocd's probe and
session: 0.5 s warm, 5 s cold, far longer under I/O load) and the act
sends go when the ego, at its speed and heading, is SCENARIO_REARM_LEAD_S
(4.0) from the polygon's edge: the timeline plots 2 s before the start
edge and the table's earliest island edge is 50 ms before it. The window
must be acknowledged before the start edge (the gate's receipt of the
exit); if it was not (no go, the helper failed, or acknowledged after),
the act ends FATAL: its record would miss its start. A `scenario` `rearm`
event records either way, the latencies (attach, go -> acknowledged) and
the lead.
SCENARIO_TRIGGER=board (CARLA demo unit C6, a and encore, the booth image
with CONFIG_ISLAND_BUTTONS): the board's buttons stand in for the act's own.
The re-arm helper runs with --buttons and stays attached after the re-arm as
the button bridge (readout.py, board_buttons.py): one line per press the
island recorded, accepted or ignored, with its uptime and the handler's
state. a: the ODD exit as under `scenario`; the driver's answer is the
visitor's SW1, accepted by the island only while its takeover request is
on, which the act turns into the same MANUAL request as the takeover
button (the `inject` event, as before), and records a `button` event; no
accepted SW1 within TAKEOVER_WINDOW_S (10) and the act reads as a b, a FAIL
for a. encore: the fault is the visitor's SW2, accepted while the MRM state
is NORMAL; the act SIGSTOPs the gate on it (the hpc-loss button, as before)
and records the press as its `trigger` event. SCENARIO_BUTTON_INJECT=1
(nobody at the board, the gate): the act writes the button's inject word
through the bridge (the button reads pressed for SCENARIO_BUTTON_TICKS (3)
handler ticks, from the pin read on the same firmware path), SW1
RESPOND_AFTER s into the takeover request, SW2 when the encore scenario's
datagram comes (its place, x 285).
"""
import argparse
import json
import os
import re
import signal
import socket
import subprocess
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


# ------------------------------------------------------ the trace window ----
class Rearm:
    """readout.py --rearm-only in its own session, killed whole on a timeout
    (c4-e1: a re-arm that never exited kept the probe and the readout after
    the act failed with "Resource busy"). wait_go: --wait-go, the word is
    written on go(); its stdout is read on a thread, each line stamped."""

    def __init__(self, cmd, wait_go, buttons=False):
        import subprocess
        import threading
        self.wait_go, self.buttons = wait_go, buttons
        self.t_start, self.t_ready, self.t_go, self.t_done = tl.now_ns(), None, None, None
        self.rc, self.lines, self.stamped = None, [], []
        # C6 (SCENARIO_TRIGGER=board): after the re-arm the helper stays
        # attached as the button bridge (readout.py --buttons): one line per
        # press the island records, `inject`/`quit` on stdin
        self.t_bridge, self.presses = None, []
        self.pr = subprocess.Popen(cmd + (" --wait-go" if wait_go else "") + (" --buttons" if buttons else ""),
                                   shell=True, text=True,
                                   stdin=subprocess.PIPE if wait_go or buttons else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        # wait_go: started with the act, minutes before the exit; attaching
        # has until SCENARIO_REARM_ATTACH_S, the write after go its 2 s
        self.limit = float(ENV("SCENARIO_REARM_ATTACH_S" if wait_go else "SCENARIO_REARM_TIMEOUT",
                               "180" if wait_go else "60"))
        self.th = threading.Thread(target=self._read, daemon=True)
        self.th.start()

    def _read(self):
        for line in self.pr.stdout:
            line = line.rstrip()
            self.lines.append(line)
            self.stamped.append((round((tl.now_ns() - self.t_start) / 1e6), line))
            if "re-arm ready" in line:
                self.t_ready = tl.now_ns()
            elif "re-armed:" in line:
                self.t_done = tl.now_ns()
            elif line.startswith("buttons: bridge ready"):
                self.t_bridge = tl.now_ns()
            elif line.startswith("buttons: press "):
                self.presses.append((tl.now_ns(), line))
        self.rc = self.pr.wait()

    def ready(self):
        if self.t_ready is None and self.rc is None and (tl.now_ns() - self.t_start) / 1e9 > self.limit:
            self.kill()  # never attached: the exit will find it not re-armed
        return self.t_ready is not None and self.rc is None

    def go(self):
        self.t_go = tl.now_ns()
        self.send("go")
        return self.t_go

    def send(self, line):
        try:
            self.pr.stdin.write(line + "\n")
            self.pr.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass
        return tl.now_ns()

    def ok(self):
        """Re-armed: the helper exited 0, or (buttons) it acknowledged and bridges on."""
        if self.t_done is None:
            return False
        return self.rc == 0 or (self.buttons and self.rc is None)

    def close(self):
        """The bridge: quit (pyocd closes its session), else killed whole."""
        if self.pr.poll() is None:
            self.send("quit")
            self.th.join(3.0)
        self.kill()

    def wait(self, secs):
        if self.buttons:  # the helper bridges on: wait for the acknowledgement, not its exit
            t0 = time.time()
            while self.t_done is None and self.rc is None and time.time() - t0 < secs:
                time.sleep(0.05)
            if self.t_done is None:
                self.kill()
                self.th.join(5.0)
            return
        self.th.join(secs)
        if self.th.is_alive():
            self.kill()
            self.th.join(5.0)

    def kill(self):
        if self.pr.poll() is None:
            try:
                os.killpg(self.pr.pid, signal.SIGKILL)
            except OSError:
                pass
            self.rc = "killed"

    def done_line(self):
        return next((ln for ln in self.lines if "re-armed:" in ln), self.lines[-1] if self.lines else "")

    def value(self):
        ms = lambda a, b: None if a is None or b is None else round((b - a) / 1e6, 1)  # noqa: E731
        return dict(rc=self.rc, out=self.done_line(), t_start_ns=self.t_start, t_ready_ns=self.t_ready,
                    t_done_ns=self.t_done, start_to_ready_ms=ms(self.t_start, self.t_ready),
                    go_to_done_ms=ms(self.t_go, self.t_done), start_to_done_ms=ms(self.t_start, self.t_done),
                    lines_ms=self.stamped[-6:])


def read_odd_polygon(path):
    """The scenario's ODD polygon, read as odd_monitor reads it."""
    sys.path.insert(0, os.path.join(tl.ROOT, "demo/l3/takeover_demo/takeover_demo"))
    import odd_scenario  # noqa: E402 (no rclpy in it)
    try:
        text, _ = odd_scenario.read_scenario_odd(path)
    except (OSError, ValueError) as e:  # odd_monitor refuses it too; the act re-arms at the drive
        print(f"scenario: no ODD polygon for the re-arm ({e})", flush=True)
        return None
    return odd_scenario.parse_polygon(text) if text else None


def yaw_of(q):
    import math
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def time_to_exit(poly, st):
    """Seconds until the ego, held at its speed and heading, leaves `poly`:
    the nearest crossing of a polygon edge by the ray from its pose."""
    import math
    if None in (st["x"], st["y"], st["yaw"], st["v"]) or st["v"] < 0.5:
        return None
    px, py = st["x"], st["y"]
    dx, dy = math.cos(st["yaw"]), math.sin(st["yaw"])
    best = None
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        t = ((ax - px) * ey - (ay - py) * ex) / den  # along the ray
        u = ((ax - px) * dy - (ay - py) * dx) / den  # along the edge
        if t > 0 and 0.0 <= u <= 1.0 and (best is None or t < best):
            best = t
    return None if best is None else best / st["v"]


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
    # C6: board = the scenario's trigger for the ODD exit, the board's buttons
    # for the rest (SW1 the driver's takeover in a, SW2 the encore's HPC loss)
    board = trigger == "board"
    scen = trigger in ("scenario", "board")
    if board and act not in ("a", "encore"):
        sys.exit(f"scenario: SCENARIO_TRIGGER=board is for a and encore (b has no button), not {act}")
    held = {}  # the re-arm helper (the button bridge under board), closed on every exit

    def bye(code):
        if held.get("r"):
            held["r"].close()
        os._exit(code)
    sock = None
    if scen and act == "encore":
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
    # C5 trace margin: a and b re-arm the window just before the ODD exit
    # (module doc); the encore and the button trigger re-arm when the ego drives
    odd_poly = None
    if carla and scen and act in ("a", "b") and ENV("SCENARIO_ODD_FILE"):
        odd_poly = read_odd_polygon(ENV("SCENARIO_ODD_FILE"))
    rearm_at_exit = odd_poly is not None
    rearm_lead = float(ENV("SCENARIO_REARM_LEAD_S", "4.0"))
    rearm = None
    rclpy.init()
    node = rclpy.create_node("timeline_scenario")
    b = Buttons(log, node)
    st = dict(v=None, mrm=None, tor=None, ctrl=None, route=None, x=None, y=None, yaw=None, odd=None, vlim={})
    q = QoSProfile(depth=5)
    ql = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    node.create_subscription(Odometry, "/localization/kinematic_state",
                             lambda m: st.update(v=m.twist.twist.linear.x, x=m.pose.pose.position.x,
                                                 y=m.pose.pose.position.y, yaw=yaw_of(m.pose.pose.orientation)), q)
    node.create_subscription(MrmState, "/system/fail_safe/mrm_state",
                             lambda m: st.update(mrm=(m.state, m.behavior)), q)
    node.create_subscription(MrmBehaviorStatus, "/system/takeover_request/state",
                             lambda m: st.update(tor=m.state), q)
    node.create_subscription(ControlModeReport, "/vehicle/status/control_mode",
                             lambda m: st.update(ctrl=m.mode), q)
    node.create_subscription(RouteState, "/planning/route_state", lambda m: st.update(route=m.state), ql)
    if scen:
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
    if carla and rearm_at_exit and ENV("SCENARIO_REARM"):
        # C5 trace margin: attach now (tm-b1: a helper started when the ego
        # drove had not attached 22 s later, at a 1-min load of 50), write a
        # few seconds before the exit
        rearm = held["r"] = Rearm(ENV("SCENARIO_REARM"), wait_go=True, buttons=board)
        say(f"trace window: re-arm attaching now, written {rearm_lead:.1f} s before the ODD exit "
            f"(time to the polygon's edge along the heading)")
    if carla:
        engage = float(ENV("ENGAGE_SECS", "300"))
        say(f"== 1-3. CARLA: the SSv2 scenario poses, routes and engages the ego (up to {engage:.0f} s) ==")
        if not spin_for(engage, lambda: (st["v"] or 0) > min_speed):
            say(f"FATAL: the vehicle did not reach {min_speed} m/s (v={st['v']}, route {st['route']})")
            bye(2)
        cmd = ENV("SCENARIO_REARM", "")
        if cmd and not rearm_at_exit:
            rearm = held["r"] = Rearm(cmd, wait_go=False, buttons=board)
            rearm.wait(float(ENV("SCENARIO_REARM_TIMEOUT", "60")))
            say(f"trace window re-armed (exit {rearm.rc}): {rearm.done_line()}")
            b.w.write("scenario", "rearm", t_mono_ns=rearm.t_start, value=rearm.value())
            if board and not rearm.ok():
                say("FATAL: no button bridge (the re-arm helper did not re-arm and stay attached)")
                bye(2)
    else:
        engage_planning(node, st, spin_for, say, sd, min_speed)
    log_dir = os.path.dirname(os.path.abspath(log))
    if board and (rearm is None or not rearm.buttons):
        say("FATAL: SCENARIO_TRIGGER=board needs the button bridge (SCENARIO_REARM, the board)")
        bye(2)
    if scen:
        arm = dict(rearm=rearm, poly=odd_poly, lead=rearm_lead) if rearm_at_exit and rearm else None
        if board and act == "encore":
            trig = board_encore(b, st, rearm, sock, spin_for, say)
        else:
            trig = scenario_trigger(act, b, st, sock, spin_for, say, log_dir, arm)
        if trig is None:
            bye(2)
    else:
        spin_for(drive)
    # phase11-S7: the fault tick's overrun, armed before the fault
    # (SCENARIO_FAULT_CMD, run-board.sh RB_OVERRUN: violations.py
    # fault-overrun <ms>|stall over SWD, attach, no halt). The handler takes
    # it on its next call_mrm tick, the first one after the HPC loss.
    inject = ENV("SCENARIO_FAULT_CMD", "")
    if inject and act in ("encore", "b"):
        say(f"== 3b. fault-tick overrun armed: {inject} ==")
        t_inj = time.monotonic_ns()
        rc_inj = subprocess.run(inject, shell=True).returncode
        b.w.write("scenario", "overrun_armed", t_mono_ns=t_inj,
                  value=dict(cmd=inject, rc=rc_inj, took_s=round((time.monotonic_ns() - t_inj) / 1e9, 3)))
        if rc_inj != 0:
            say(f"FATAL: the overrun could not be armed (exit {rc_inj})")
            bye(2)
        spin_for(1.0)
    v0 = st["v"]
    say(f"== 4. driving at {v0:.2f} m/s; mrm {st['mrm']}, TOR {st['tor']}, control mode {st['ctrl']} ==")
    if scen:
        b.w.write("scenario", "velocity_limit", value=st["vlim"])
        say(f"velocity limit: {st['vlim'] or '- (none received)'}")
    ok, why = False, ""
    t_inject = time.time()
    c0 = (clock["sim"], clock["wall"])
    if act in ("a", "b"):
        if not scen:
            b.press("odd-exit")
        tor_on = spin_for(3.0, lambda: st["tor"] == 2)
        say(f"takeover request on: {tor_on}")
        if act == "a" and board:
            # C6: the visitor's SW1 is the driver's answer (inside the window)
            t_tor = time.time()
            window = float(ENV("TAKEOVER_WINDOW_S", "10"))
            say(f"== 5. the visitor's SW1 (board), up to {window:.0f} s ==")
            p = board_press(rearm, "SW1", window, spin_for, say,
                            inject_when=(lambda: time.time() - t_tor >= respond)
                            if ENV("SCENARIO_BUTTON_INJECT") == "1" else None)
            if p["t_seen_ns"] is not None:
                t_press = tl.now_ns()
                b.press("takeover")
                p.update(t_press_ns=t_press, seen_to_press_ms=round((t_press - p["t_seen_ns"]) / 1e6, 2))
            b.w.write("scenario", "button", t_mono_ns=p["t_seen_ns"] or tl.now_ns(), marker="takeover", value=p)
            say(f"button: {p['summary']}")
        elif act == "a":
            spin_for(respond)
            b.press("takeover")
        if act == "a":
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
        if not scen:  # odd_monitor's verdict is latched: it would set the flag again
            b.press("odd-enter")
        spin_for(3.0)
    elif act == "encore":
        if not scen:  # scenario_trigger (board_encore) pressed it on the scenario's word (SW2)
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
    bye(0 if ok else 1)


ODD_EXIT_LINE = re.compile(r"ODD EXIT \((.*)\) wall=([0-9.]+) mono=([0-9.]+)")


def scenario_trigger(act, b, st, sock, spin_for, say, log_dir, arm=None):
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
    go = dict(t=None, x=None, tte=None)

    def until():
        r = arm and arm["rearm"]
        if r and go["t"] is None and r.ready() and st["odd"] is not True:
            tte = time_to_exit(arm["poly"], st)
            if tte is not None and tte <= arm["lead"]:
                go.update(t=r.go(), x=st["x"], tte=round(tte, 3))
        return st["odd"] is True
    if not spin_for(wait, until):
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
    if arm:
        r = arm["rearm"]
        if go["t"] is not None:
            spin_for(2.0, lambda: r.t_done is not None)  # normally long done: the go came seconds before
        val = r.value()
        val.update(how="at the ODD exit", lead_s=arm["lead"], x_go=go["x"], time_to_exit_go_s=go["tte"],
                   t_go_ns=go["t"], t_edge_ns=t_gate,
                   done_before_edge_ms=None if r.t_done is None else round((t_gate - r.t_done) / 1e6, 1),
                   go_before_edge_ms=None if go["t"] is None else round((t_gate - go["t"]) / 1e6, 1))
        b.w.write("scenario", "rearm", t_mono_ns=go["t"] or r.t_start, value=val)
        if go["t"] is None or not r.ok() or r.t_done >= t_gate:
            r.kill()
            say(f"FATAL: the trace window was not re-armed before the start edge (go {go}, exit {r.rc}, "
                f"helper lines (ms after its start) {r.stamped}); the act's record would miss its start")
            return None
        say(f"trace window re-armed {val['go_before_edge_ms'] / 1000:.2f} s before the start edge "
            f"(at x {go['x']:.1f}, {go['tte']:.2f} s to the polygon's edge; go -> acknowledged "
            f"{val['go_to_done_ms']} ms; attached {val['start_to_ready_ms']} ms after the act started): {r.done_line()}")
    b.w.write("scenario", "inject", t_mono_ns=t_gate, hazard="odd_exit", marker="odd_exit",
              value=dict(how="odd_monitor's /demo/odd/exit, received by the gate", reason=reason))
    hop = None if t_odd is None else round((t_gate - t_odd) / 1e6, 2)
    val = dict(how="odd_monitor", reason=reason, t_odd_exit_ns=t_odd, t_gate_ns=t_gate, odd_to_gate_ms=hop,
               x=pose[0], y=pose[1], v=pose[2])
    b.w.write("scenario", "trigger", t_mono_ns=t_odd or t_gate, hazard="odd_exit", marker="odd_exit", value=val)
    say(f"trigger: ODD EXIT ({reason}); odd_monitor -> gate {hop} ms")
    return val


PRESS_LINE = re.compile(r"press (SW[12]) (accepted|ignored \([^)]*\)) uptime_ms=(\d+) state=(\S+) n=(\d+)")


def board_press(r, name, secs, spin_for, say, inject_when=None):
    """C6 (SCENARIO_TRIGGER=board): wait up to `secs` for a press of `name`
    (SW1|SW2) the island ACCEPTED, as the button bridge reports it
    (board_buttons.py). Presses the island ignored are said and skipped.
    inject_when: SCENARIO_BUTTON_INJECT=1, nobody at the board: the first
    time it returns true the bridge writes the button's inject word, and
    the press goes the firmware's whole way from the pin read on. Returns
    the `button` event's value (t_seen_ns None: no accepted press)."""
    ticks = int(ENV("SCENARIO_BUTTON_TICKS", "3"))
    seen, got, inj = [len(r.presses)], {}, {}

    def until():
        if inject_when is not None and "t" not in inj and inject_when():
            inj["t"] = r.send(f"inject {name.lower()} {ticks}")
            say(f"button: {name} injected through the firmware path (its inject word, {ticks} ticks; "
                f"nobody at the board)")
        for t, line in r.presses[seen[0]:]:
            seen[0] += 1
            m = PRESS_LINE.search(line)
            if m and m.group(1) == name and m.group(2) == "accepted":
                got.update(t=t, uptime_ms=int(m.group(3)), state=m.group(4), n=int(m.group(5)))
                return True
            say(f"button: {line[len('buttons: press '):]} (not this act's press)")
        return r.rc is not None  # the bridge is gone
    spin_for(secs, until)
    val = dict(how="board", button=name, injected="t" in inj, t_inject_ns=inj.get("t"),
               t_seen_ns=got.get("t"), island_uptime_ms=got.get("uptime_ms"), island_state=got.get("state"),
               presses=got.get("n"), bridge_rc=r.rc)
    if got.get("t") is not None and inj.get("t") is not None:
        val["inject_to_seen_ms"] = round((got["t"] - inj["t"]) / 1e6, 1)
    if got.get("t") is None:
        val["summary"] = (f"no accepted {name} press in {secs:.0f} s" +
                          (f" (the bridge exited: {r.rc})" if r.rc is not None else ""))
    else:
        val["summary"] = (f"{name} accepted at island uptime {got['uptime_ms']} ms ({got['state']})" +
                          (f", injected, inject -> seen {val['inject_to_seen_ms']} ms" if inj else ", pressed"))
    return val


def board_encore(b, st, r, sock, spin_for, say):
    """C6: the encore's fault is the visitor's SW2. Under
    SCENARIO_BUTTON_INJECT=1 the injection waits for the scenario's datagram
    (its place, x 285, as C4's trigger), so the act runs where C4's did."""
    wait = float(ENV("TRIGGER_SECS", "180"))
    dg = {}

    def datagram():
        try:
            dg["cmd"] = sock.recv(256).decode(errors="replace").strip()
            dg["t"] = tl.now_ns()
            dg["pose"] = (st["x"], st["y"], st["v"])
        except (BlockingIOError, AttributeError):
            pass
        return "cmd" in dg
    inject = ENV("SCENARIO_BUTTON_INJECT") == "1"
    say(f"== 4. the visitor's SW2 (board){', injected at the scenario' + chr(39) + 's place' if inject else ''},"
        f" up to {wait:.0f} s ==")
    p = board_press(r, "SW2", wait, spin_for, say, inject_when=datagram if inject else None)
    if p["t_seen_ns"] is None:
        say(f"FATAL: {p['summary']} (v={st['v']}, pose {st['x']}, {st['y']})")
        return None
    pose = (st["x"], st["y"], st["v"])
    t_press = tl.now_ns()
    b.press("hpc-loss")
    p.update(t_press_ns=t_press, seen_to_press_ms=round((t_press - p["t_seen_ns"]) / 1e6, 2),
             x=pose[0], y=pose[1], v=pose[2], cmd="hpc-loss",
             datagram=dg.get("cmd"), t_datagram_ns=dg.get("t"))
    b.w.write("scenario", "trigger", t_mono_ns=p["t_seen_ns"], hazard="hpc_loss", marker="hpc_loss", value=p)
    say(f"trigger: board SW2 -> hpc-loss at ({pose[0]:.1f}, {pose[1]:.1f}), {pose[2]:.2f} m/s; {p['summary']}")
    return p


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
