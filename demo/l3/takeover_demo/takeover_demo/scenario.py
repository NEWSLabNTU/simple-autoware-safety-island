"""scenario: the phase-8 acts, scripted, on rmw_zenoh_cpp in domain 10.

  ros2 run takeover_demo scenario drive         engage and drive DRIVE_SECS
  ros2 run takeover_demo scenario hpc           HPC loss: SIGSTOP the availability
                                                gate -> the island's emergency stop
  ros2 run takeover_demo scenario odd           ODD exit, nobody responds
  ros2 run takeover_demo scenario odd-respond   ODD exit, the driver responds
                                                after RESPOND_AFTER seconds (2)

Every act starts the same way as demo/scenario_driver.py (initial pose,
goal, engage, wait for motion), then injects its fault and prints every
transition of the island's mrm_state, the takeover HMI state, the control
mode and the velocity, with the time since the injection. It ends with one
`VERDICT:` line; exit 0 is PASS.

Needs the takeover launch running (the gate, the ODD monitor, the HMI and
the button) and Autoware launched with
operation_mode_availability_topic:=/system/operation_mode/availability_raw.
The HPC-loss act signals the gate's process, so it must run in the same PID
namespace (the same container, or the host).

Env: DRIVE_SECS (10), OBSERVE_SECS (15), RESPOND_AFTER (2), MIN_SPEED (1.0), REROUTE (0),
INIT_X/Y/QZ/QW, GOAL_X/Y/QZ/QW (the sample map's, as scenario_driver.py).
"""
import os
import signal
import subprocess
import sys
import time

import rclpy
from autoware_adapi_v1_msgs.msg import MrmState, OperationModeState
from autoware_adapi_v1_msgs.srv import ChangeOperationMode, ClearRoute
from autoware_planning_msgs.msg import RouteState
from autoware_vehicle_msgs.msg import ControlModeReport
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tier4_system_msgs.msg import OperationModeAvailability

from . import common as c

ENV = os.environ.get
DRIVE_SECS = float(ENV('DRIVE_SECS', '10'))
OBSERVE_SECS = float(ENV('OBSERVE_SECS', '15'))
RESPOND_AFTER = float(ENV('RESPOND_AFTER', '2'))
MIN_SPEED = float(ENV('MIN_SPEED', '1.0'))
INIT = [float(ENV(k, d)) for k, d in
        (('INIT_X', '3730.47'), ('INIT_Y', '73727.89'), ('INIT_QZ', '0.2312'), ('INIT_QW', '0.9729'))]
GOAL = [float(ENV(k, d)) for k, d in
        (('GOAL_X', '3760.41'), ('GOAL_Y', '73755.91'), ('GOAL_QZ', '-0.49896'), ('GOAL_QW', '0.86662'))]
MRM_S = {0: 'UNKNOWN', 1: 'NORMAL', 2: 'MRM_OPERATING', 3: 'MRM_SUCCEEDED', 4: 'MRM_FAILED'}
MRM_B = {0: 'UNKNOWN', 1: 'NONE', 2: 'EMERGENCY_STOP', 3: 'COMFORTABLE_STOP', 4: 'PULL_OVER'}
CTRL = {0: 'NO_COMMAND', 1: 'AUTONOMOUS', 2: 'AUTONOMOUS_STEER_ONLY', 3: 'AUTONOMOUS_VELOCITY_ONLY',
        4: 'MANUAL', 5: 'DISENGAGED', 6: 'NOT_READY'}


def log(msg):
    print(msg, flush=True)


class Scenario(Node):
    def __init__(self):
        super().__init__('l3_scenario')
        self.v = None
        self.mrm = None
        self.mrm_t = None
        self.hmi = None
        self.ctrl = None
        self.op = None
        self.route = None
        self.avail_t = None
        self.avail_n = 0
        self.t0 = None
        self.events = []
        self.create_subscription(Odometry, c.KINEMATIC_STATE, self.on_odom, c.qos_volatile())
        self.create_subscription(MrmState, c.MRM_STATE, self.on_mrm, c.qos_volatile())
        self.create_subscription(String, c.TAKEOVER_STATE, self.on_hmi, c.qos_volatile())
        self.create_subscription(ControlModeReport, c.CONTROL_MODE, self.on_ctrl, c.qos_volatile())
        self.create_subscription(OperationModeState, c.OPERATION_MODE_STATE, self.on_op, c.qos_latched())
        self.create_subscription(RouteState, '/planning/route_state', self.on_route, c.qos_latched())
        self.create_subscription(OperationModeAvailability, c.AVAILABILITY, self.on_avail, c.qos_volatile())

    # -- observation ------------------------------------------------------
    def rel(self):
        return f'+{time.monotonic() - self.t0:7.3f} s' if self.t0 else '         '

    def note(self, what):
        line = f'  {self.rel()}  {what}'
        self.events.append((time.monotonic(), what))
        log(line)

    def on_odom(self, m):
        self.v = m.twist.twist.linear.x

    def on_mrm(self, m):
        k = (m.state, m.behavior)
        self.mrm_t = time.monotonic()
        if k != self.mrm:
            self.mrm = k
            self.note(f'mrm_state {MRM_S.get(m.state)}/{MRM_B.get(m.behavior)}  v={self.v or 0:.2f} m/s')

    def on_hmi(self, m):
        if m.data != self.hmi:
            self.hmi = m.data
            self.note(f'takeover {m.data}')

    def on_ctrl(self, m):
        if m.mode != self.ctrl:
            self.ctrl = m.mode
            self.note(f'control_mode {CTRL.get(m.mode, m.mode)}')

    def on_op(self, m):
        self.op = m.mode

    def on_route(self, m):
        self.route = m.state

    def on_avail(self, m):
        self.avail_t = time.monotonic()
        self.avail_n += 1

    def spin_for(self, secs, until=None):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.05)
            if until is not None and until():
                return True
        return until() if until else True

    def call(self, srv_type, name, req, timeout=10.0):
        cli = self.create_client(srv_type, name)
        if not cli.wait_for_service(timeout_sec=timeout):
            log(f'service {name} not available')
            return None
        fut = cli.call_async(req)
        self.spin_for(timeout, lambda: fut.done())
        return fut.result() if fut.done() else None

    def init_and_route(self):
        log('== 1. initial pose ==')
        pub = self.create_publisher(PoseWithCovarianceStamped, '/initialpose', 1)
        m = PoseWithCovarianceStamped()
        m.header.frame_id = 'map'
        m.pose.pose.position.x, m.pose.pose.position.y = INIT[0], INIT[1]
        m.pose.pose.orientation.z, m.pose.pose.orientation.w = INIT[2], INIT[3]
        m.pose.covariance[0] = m.pose.covariance[7] = 0.25
        m.pose.covariance[35] = 0.068
        for _ in range(3):
            pub.publish(m)
            self.spin_for(1.0)
        self.spin_for(4.0)
        log('== 2. goal ==')
        pub_g = self.create_publisher(PoseStamped, '/planning/mission_planning/goal', 1)
        g = PoseStamped()
        g.header.frame_id = 'map'
        g.pose.position.x, g.pose.position.y = GOAL[0], GOAL[1]
        g.pose.orientation.z, g.pose.orientation.w = GOAL[2], GOAL[3]
        for _ in range(10):
            pub_g.publish(g)
            if self.spin_for(4.0, lambda: self.route == RouteState.SET):
                break
        log(f'route state {self.route} (SET={RouteState.SET})')
        if self.route != RouteState.SET:
            log('FATAL: route not set')
            sys.exit(2)

    # -- the common prologue ------------------------------------------------
    def engage_and_drive(self):
        log('== 0. wait for the planning stack (route state latched) ==')
        if not self.spin_for(300, lambda: self.route is not None and self.op is not None):
            log('FATAL: no /planning/route_state or /api/operation_mode/state in 300 s')
            sys.exit(2)
        # A previous act may have left Autoware engaged or the island holding an
        # MRM: go to STOP first (the state change also tells a late-joined
        # island the current mode; brief C, M1). A route that is still SET is
        # kept by default: re-initialising the pose and re-routing on this
        # graph is what left behavior_path_planner silent (0 Hz path, engage
        # refused) in two of three tries (demo/l3/README.md, traps).
        if self.op not in (None, OperationModeState.STOP):
            log(f'== 0b. operation mode {self.op}: change to STOP ==')
            self.call(ChangeOperationMode, '/api/operation_mode/change_to_stop', ChangeOperationMode.Request())
            self.spin_for(20, lambda: self.op == OperationModeState.STOP and abs(self.v or 0) < 0.05)
        if self.ctrl == ControlModeReport.MANUAL:
            # the driver took over in a previous act: hand control back
            log('== 0c. vehicle in MANUAL: enable Autoware control ==')
            self.call(ChangeOperationMode, '/api/operation_mode/enable_autoware_control',
                      ChangeOperationMode.Request())
            self.spin_for(10, lambda: self.ctrl == ControlModeReport.AUTONOMOUS)
        if self.route == RouteState.SET and ENV('REROUTE', '0') != '1':
            log('== 1-2. route still SET: keeping the pose and the route (REROUTE=1 redoes them) ==')
        else:
            if self.route not in (None, RouteState.UNSET):
                self.call(ClearRoute, '/api/routing/clear_route', ClearRoute.Request())
                self.spin_for(10, lambda: self.route == RouteState.UNSET)
            self.init_and_route()
        log('== 3. engage autonomous ==')
        for i in range(8):
            r = self.call(ChangeOperationMode, '/api/operation_mode/change_to_autonomous',
                          ChangeOperationMode.Request())
            ok = bool(r and r.status.success)
            log(f'engage attempt {i + 1}: {ok}{"" if ok or not r else " (" + r.status.message + ")"}')
            if ok:
                break
            self.spin_for(4.0)
        log(f'== 4. wait for motion (> {MIN_SPEED} m/s) ==')
        if not self.spin_for(60, lambda: (self.v or 0) > MIN_SPEED):
            log(f'FATAL: the vehicle did not reach {MIN_SPEED} m/s (v={self.v})')
            sys.exit(2)
        log(f'== 4b. driving {DRIVE_SECS:.0f} s ==')
        self.spin_for(DRIVE_SECS)
        log(f'velocity {self.v:.2f} m/s, mrm_state {MRM_S.get(self.mrm[0]) if self.mrm else None}, '
            f'control_mode {CTRL.get(self.ctrl)}, availability samples so far {self.avail_n}')

    # -- the acts -------------------------------------------------------------
    def gate_pids(self):
        # The installed executable of each publisher's node, whatever package
        # holds it: lib/availability_gate/availability_gate (W16's C++ gate,
        # exec'd by gate-rt, so the wrapper leaves no process of its own).
        pids = set()
        for info in self.get_publishers_info_by_topic(c.AVAILABILITY):
            out = subprocess.run(['pgrep', '-f', f'/lib/[^ ]+/{info.node_name}( |$)'],
                                 capture_output=True, text=True)
            found = [int(p) for p in out.stdout.split()]
            log(f'publisher /{info.node_name} on {c.AVAILABILITY}: pids {found}')
            pids.update(found)
        return sorted(pids)

    def act_drive(self):
        v0 = self.v
        n0, t0 = self.avail_n, time.monotonic()
        self.spin_for(5.0)
        hz = (self.avail_n - n0) / (time.monotonic() - t0)
        ok = (self.v or 0) > MIN_SPEED and self.mrm and self.mrm[0] == MrmState.NORMAL
        log(f'VERDICT: {"PASS" if ok else "FAIL"} drive: v {v0:.2f} -> {self.v:.2f} m/s, '
            f'availability {hz:.1f} Hz, mrm {MRM_S.get(self.mrm[0]) if self.mrm else None}')
        return ok

    def act_hpc(self):
        pids = self.gate_pids()
        if not pids:
            log('FATAL: no availability gate process to stop')
            return False
        v0 = self.v
        log(f'== 5. HPC loss: SIGSTOP the availability gate (pids {pids}) ==')
        self.t0 = time.monotonic()
        last_avail = self.avail_t
        for p in pids:
            os.kill(p, signal.SIGSTOP)
        self.note(f'SIGSTOP availability_gate  v={v0:.2f} m/s')
        got = self.spin_for(5.0, lambda: self.mrm and self.mrm[0] == MrmState.MRM_OPERATING)
        t_mrm = time.monotonic()
        self.spin_for(OBSERVE_SECS, lambda: abs(self.v or 0) < 0.05)
        t_stop = time.monotonic()
        v1 = self.v
        self.spin_for(1.0)
        log('== 6. SIGCONT the gate ==')
        for p in pids:
            os.kill(p, signal.SIGCONT)
        self.note('SIGCONT availability_gate')
        rec = self.spin_for(20.0, lambda: self.mrm and self.mrm[0] == MrmState.NORMAL)
        det = (t_mrm - last_avail) * 1000 if got and last_avail else None
        ok = bool(got and self.mrm and abs(v1 or 0) < 0.3 and v0 > MIN_SPEED)
        log(f'VERDICT: {"PASS" if ok else "FAIL"} hpc: MRM_OPERATING {"seen" if got else "NOT seen"}'
            + (f' {det:.0f} ms after the last availability sample' if det else '')
            + f', v {v0:.2f} -> {v1:.2f} m/s, standstill {t_stop - self.t0:.2f} s after SIGSTOP,'
            f' recovered to NORMAL: {rec}')
        return ok

    def act_odd(self, respond):
        v0 = self.v
        log('== 5. ODD exit (the presenter\'s button) ==')
        self.t0 = time.monotonic()
        r = self.call(Trigger, '/odd_monitor/inject_exit', Trigger.Request())
        self.note(f'ODD exit injected ({r.message if r else "service failed"})  v={v0:.2f} m/s')
        if respond:
            self.spin_for(RESPOND_AFTER)
            r = self.call(Trigger, '/driver_button/take_over', Trigger.Request())
            self.note(f'driver response ({r.message if r else "service failed"})')
        self.spin_for(OBSERVE_SECS)
        mrm_seen = [e for e in self.events if 'MRM_OPERATING' in e[1] and e[0] >= self.t0]
        manual = self.ctrl == ControlModeReport.MANUAL
        first = f'{(mrm_seen[0][0] - self.t0) * 1000:.0f} ms' if mrm_seen else 'never'
        # Since W7 the island holds the takeover window (10 s) before its rung
        # fires, so a driver who answers inside it sees NO MRM (measured W24:
        # TOR_ACTIVE, MANUAL 2.06 s, DRIVER_TOOK_OVER, mrm_state NORMAL). PASS:
        # with a response, the vehicle reports MANUAL and the HMI
        # DRIVER_TOOK_OVER; without one, the window expires and the island
        # reacts (MRM_OPERATING).
        if respond:
            ok = manual and self.hmi == 'DRIVER_TOOK_OVER'
        else:
            ok = bool(mrm_seen) and self.hmi == 'TOR_EXPIRED'
        log(f'VERDICT: {"PASS" if ok else "FAIL"} {"odd-respond" if respond else "odd"}: island '
            f'MRM_OPERATING {first} after the exit; takeover state {self.hmi}; '
            f'control_mode {CTRL.get(self.ctrl)}; v {v0:.2f} -> {self.v:.2f} m/s')
        log('== 6. clear the ODD exit ==')
        self.call(Trigger, '/odd_monitor/clear', Trigger.Request())
        return ok


def main():
    act = sys.argv[1] if len(sys.argv) > 1 else 'drive'
    if act not in ('drive', 'hpc', 'odd', 'odd-respond'):
        log(__doc__)
        sys.exit(2)
    rclpy.init()
    node = Scenario()
    log(f'l3 scenario "{act}" on {ENV("RMW_IMPLEMENTATION")} domain {ENV("ROS_DOMAIN_ID")}')
    node.engage_and_drive()
    ok = {'drive': node.act_drive, 'hpc': node.act_hpc,
          'odd': lambda: node.act_odd(False), 'odd-respond': lambda: node.act_odd(True)}[act]()
    sys.exit(0 if ok else 1)
