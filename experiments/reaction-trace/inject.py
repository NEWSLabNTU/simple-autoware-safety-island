#!/usr/bin/env python3
"""phase7-W3 fault injector: the demo sequence, with every step time-stamped.

Same sequence as demo/scenario_driver.py (whose helpers it imports): initial
pose, goal, engage, drive, SIGSTOP the process publishing
/system/operation_mode/availability (the fault), hold, SIGCONT, wait for the
island to go back to NORMAL, resume. What it adds is a log, written as JSON
lines to $W3_LOG (one object per line, `wall` = host time.time()):

  - the injection itself: wall time just before and just after each os.kill;
  - a background subscriber (its own context and thread) recording the
    receive wall time of every /system/operation_mode/availability sample,
    every /system/fail_safe/mrm_state (the island's), every
    /system/emergency/control_cmd (the island's operator) and, from 5 s
    before the fault to 20 s after it, every /localization/kinematic_state.

The island's trace is in simulated time and this log is in host wall time;
extract.py aligns the two on the island's first MRM_OPERATING mrm_state
sample (a unique event present in both) and says how far off that can be.

Env: W3_LOG (required), DRIVE_SECS (15), HOLD_SECS (10, the demo's 3 + 7).
"""
import json
import os
import signal
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, 'demo'))
import scenario_driver as sd  # noqa: E402  (sets the Cyclone/RMW env before rclpy)

from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.qos import QoSProfile  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from autoware_adapi_v1_msgs.msg import MrmState  # noqa: E402
from autoware_adapi_v1_msgs.srv import ChangeOperationMode  # noqa: E402
from autoware_planning_msgs.msg import RouteState  # noqa: E402
from autoware_control_msgs.msg import Control  # noqa: E402
from tier4_system_msgs.msg import OperationModeAvailability  # noqa: E402
from geometry_msgs.msg import PoseWithCovarianceStamped, PoseStamped  # noqa: E402

LOG = open(os.environ['W3_LOG'], 'w', buffering=1)
_lock = threading.Lock()
ODOM_WINDOW = [None, None]  # [from, to] wall; None = not logging


def log(ev, **kw):
    kw.update(ev=ev, wall=kw.get('wall', time.time()))
    with _lock:
        LOG.write(json.dumps(kw) + '\n')


def stamp(s):
    return s.sec + s.nanosec * 1e-9


def logger_thread(domain):
    ctx, node, ex = sd.ctx_node(domain, 'si_w3_logger')
    q = QoSProfile(depth=10)
    node.create_subscription(OperationModeAvailability, sd.FAULT_TOPIC,
                             lambda m: log('avail', stamp=stamp(m.stamp)), q)
    node.create_subscription(MrmState, '/system/fail_safe/mrm_state',
                             lambda m: log('mrm_state', state=m.state, behavior=m.behavior,
                                           stamp=stamp(m.stamp)), q)
    node.create_subscription(Control, '/system/emergency/control_cmd',
                             lambda m: log('emerg_cmd', acc=m.longitudinal.acceleration,
                                           vel=m.longitudinal.velocity, stamp=stamp(m.stamp)), q)

    def odom(m):
        w = time.time()
        a, b = ODOM_WINDOW
        if a is not None and a <= w and (b is None or w <= b):
            log('odom', wall=w, v=m.twist.twist.linear.x, stamp=stamp(m.header.stamp))
    node.create_subscription(Odometry, '/localization/kinematic_state', odom, q)
    while True:
        ex.spin_once(timeout_sec=0.1)


def main():
    domain = int(os.environ.get('ROS_DOMAIN_ID', '1'))
    drive = float(os.environ.get('DRIVE_SECS', '15'))
    hold = float(os.environ.get('HOLD_SECS', '10'))
    threading.Thread(target=logger_thread, args=(domain,), daemon=True).start()
    ctx1, n1, ex1 = sd.ctx_node(domain, 'si_w3_driver')
    vel = lambda t=8: sd.latest(n1, ex1, Odometry, '/localization/kinematic_state', t,
                                field=lambda m: m.twist.twist.linear.x)
    log('start', island_pid=os.environ.get('W3_ISLAND_PID'))

    print('== 0. wait for the sim stack ==', flush=True)
    while sd.latest(n1, ex1, RouteState, '/planning/route_state', 5, transient=True) is None:
        time.sleep(2)

    print('== 1. initial pose ==', flush=True)
    pub_init = n1.create_publisher(PoseWithCovarianceStamped, '/initialpose', 1)
    m = PoseWithCovarianceStamped()
    m.header.frame_id = 'map'
    m.pose.pose.position.x, m.pose.pose.position.y = sd.INIT[0], sd.INIT[1]
    m.pose.pose.orientation.z, m.pose.pose.orientation.w = sd.INIT[2], sd.INIT[3]
    m.pose.covariance[0] = m.pose.covariance[7] = 0.25
    m.pose.covariance[35] = 0.068
    for _ in range(3):
        pub_init.publish(m); ex1.spin_once(timeout_sec=0.3); time.sleep(1)
    time.sleep(4)

    print('== 2. goal ==', flush=True)
    pub_goal = n1.create_publisher(PoseStamped, '/planning/mission_planning/goal', 1)
    g = PoseStamped(); g.header.frame_id = 'map'
    g.pose.position.x, g.pose.position.y = sd.GOAL[0], sd.GOAL[1]
    g.pose.orientation.z, g.pose.orientation.w = sd.GOAL[2], sd.GOAL[3]
    route = None
    for _ in range(10):
        pub_goal.publish(g); time.sleep(2)
        st = sd.latest(n1, ex1, RouteState, '/planning/route_state', 4, transient=True)
        route = st.state if st else None
        if route == RouteState.SET:
            break
    print(f'route state: {route} (SET={RouteState.SET})', flush=True)
    if route != RouteState.SET:
        print('route not set'); sys.exit(2)

    print('== 3. engage autonomous ==', flush=True)
    cli = n1.create_client(ChangeOperationMode, '/api/operation_mode/change_to_autonomous')
    for i in range(8):
        if not cli.wait_for_service(timeout_sec=5):
            continue
        fut = cli.call_async(ChangeOperationMode.Request())
        t0 = time.time()
        while not fut.done() and time.time() - t0 < 10:
            ex1.spin_once(timeout_sec=0.2)
        ok = fut.done() and fut.result() and fut.result().status.success
        print(f'engage attempt {i+1}: {ok}', flush=True)
        if ok:
            break
        time.sleep(4)

    print('== 4. wait for motion ==', flush=True)
    v0 = 0.0
    for _ in range(20):
        v = vel(4)
        if v and v > 0.3:
            v0 = v; break
        time.sleep(2)
    print(f'velocity: {v0}', flush=True)
    print(f'== 4b. driving for {drive:.0f}s ==', flush=True)
    time.sleep(max(drive - 5, 0))
    ODOM_WINDOW[0] = time.time()
    time.sleep(min(drive, 5))
    v = vel(4)
    v0 = v if v is not None else v0
    print(f'velocity before fault: {v0}', flush=True)

    print(f'== 5. FAULT: SIGSTOP the {sd.FAULT_TOPIC} publisher ==', flush=True)
    pids = sd.fault_pids(n1)
    if not pids:
        print(f'FATAL: no process publishing {sd.FAULT_TOPIC}'); sys.exit(2)
    for p in pids:
        w0 = time.time()
        try:
            os.kill(p, signal.SIGSTOP)
        except ProcessLookupError:
            continue
        w1 = time.time()
        log('sigstop', pid=p, wall=w0, wall_after=w1)
        print(f'pid {p} paused at wall {w0:.6f}', flush=True)
    t_fault = time.time()
    ODOM_WINDOW[1] = t_fault + 20
    time.sleep(3)
    st = sd.latest(n1, ex1, MrmState, '/system/fail_safe/mrm_state', 8)
    print(f'state: {st.state if st else None} behavior: {st.behavior if st else None}', flush=True)
    time.sleep(max(hold - (time.time() - t_fault), 0))
    v1 = vel(8)
    print(f'velocity after island MRM: {v1}', flush=True)

    print('== 7. revive (SIGCONT) ==', flush=True)
    for p in pids:
        try:
            os.kill(p, signal.SIGCONT)
            log('sigcont', pid=p)
        except ProcessLookupError:
            pass

    print('== 8. wait for MRM recovery ==', flush=True)
    st2 = None
    t0 = time.time()
    while time.time() - t0 < 40:
        st2 = sd.latest(n1, ex1, MrmState, '/system/fail_safe/mrm_state', 5)
        if st2 and st2.state == MrmState.NORMAL:
            break
    ok_recover = st2 is not None and st2.state == MrmState.NORMAL
    print(f'mrm after restore: state={st2.state if st2 else None}', flush=True)
    ok_mrm = st is not None and st.state in (2, 3) and st.behavior == 2
    ok_stop = v0 > 0.5 and v1 is not None and abs(v1) < 0.3
    log('verdict', v0=v0, v1=v1, mrm=[st.state, st.behavior] if st else None,
        recover=ok_recover)
    if ok_stop and ok_mrm and ok_recover:
        print(f'VERDICT: PASS -- island stopped the vehicle ({v0:.2f} -> {v1:.2f} m/s), MRM recovered')
        finish(0)
    print(f'VERDICT: FAIL (stop={ok_stop} v {v0} -> {v1}, mrm={st.state if st else None}/'
          f'{st.behavior if st else None}, recover={ok_recover})')
    finish(1)


def finish(code):
    # os._exit: a normal exit tears rclpy down under the logger thread's
    # spin_once and aborts ("terminate called without an active exception",
    # exit 134 in run r1), which the supervisor then reports as the run's status.
    sys.stdout.flush()
    with _lock:
        LOG.flush()
    os._exit(code)


if __name__ == '__main__':
    os.chdir(_REPO)
    main()
