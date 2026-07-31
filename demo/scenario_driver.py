#!/usr/bin/env python3
"""Demo driver — pure rclpy (no ros2-CLI daemon dependency).

Direct-connection structure: the island sits on Autoware's domain 1 (no
domain bridges, no relay). Sequence: init pose -> goal -> engage -> drive
DRIVE_SECS -> SIGSTOP the process publishing the availability heartbeat
(the fault) -> island MRM stops the vehicle -> SIGCONT it (heartbeat
revives) -> island back to NORMAL -> vehicle resumes -> VERDICT (exit 0 =
PASS). Set ARRIVE_SECS=300 to additionally wait for route ARRIVED (off by
default: the sample route's intersection stop lines can hold the planner
for a long time, which is Autoware behavior, not the island's).

Env: DRIVE_SECS (15), INIT_X/Y/QZ/QW, GOAL_X/Y/QZ/QW.
Run under an env with ROS 2 Humble + the Autoware msgs sourced. The shared
demo/cyclonedds.xml (auto participant index, range 120 — what makes this
participant visible to the multicast-less island) is applied unless
CYCLONEDDS_URI is already set.
"""
import os, sys, time, signal, subprocess

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('CYCLONEDDS_URI', 'file://' + os.path.join(_REPO, 'demo', 'cyclonedds.xml'))
os.environ['RMW_IMPLEMENTATION'] = 'rmw_cyclonedds_cpp'
os.environ.setdefault('ROS_DOMAIN_ID', '1')

import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile, DurabilityPolicy
from geometry_msgs.msg import PoseWithCovarianceStamped, PoseStamped
from nav_msgs.msg import Odometry
from autoware_adapi_v1_msgs.msg import MrmState
from autoware_planning_msgs.msg import RouteState  # /planning/route_state — the
# adapi /api/routing/state republish misses the latched sample under fast
# startup (volatile-sub race, exposed by play_launch's 40s bring-up)
from autoware_adapi_v1_msgs.srv import ChangeOperationMode

DRIVE_SECS = float(os.environ.get('DRIVE_SECS', '15'))
INIT = [float(os.environ.get(k, d)) for k, d in
        (('INIT_X', '3730.47'), ('INIT_Y', '73727.89'), ('INIT_QZ', '0.2312'), ('INIT_QW', '0.9729'))]
GOAL = [float(os.environ.get(k, d)) for k, d in
        (('GOAL_X', '3760.41'), ('GOAL_Y', '73755.91'), ('GOAL_QZ', '-0.49896'), ('GOAL_QW', '0.86662'))]

def ctx_node(domain, name):
    ctx = Context()
    rclpy.init(context=ctx, domain_id=domain)
    node = rclpy.create_node(name, context=ctx)
    ex = SingleThreadedExecutor(context=ctx)
    ex.add_node(node)
    return ctx, node, ex

def latest(node, ex, msg_type, topic, secs, transient=False, field=None):
    got = []
    qos = QoSProfile(depth=1)
    if transient:
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
    sub = node.create_subscription(msg_type, topic, lambda m: got.append(m), qos)
    t0 = time.time()
    while not got and time.time() - t0 < secs:
        ex.spin_once(timeout_sec=0.2)
    node.destroy_subscription(sub)
    if not got:
        return None
    m = got[-1]
    return field(m) if field else m

FAULT_TOPIC = '/system/operation_mode/availability'

def fault_pids(node):
    """PIDs of the process(es) publishing the availability heartbeat.

    Resolved from the live graph (publisher node names) -> `pgrep -f
    __node:=<name>` (works for standalone nodes; a composable would live in
    a container whose cmdline lacks the node name — then the container PID
    must be found by its container remap instead)."""
    pids = set()
    for info in node.get_publishers_info_by_topic(FAULT_TOPIC):
        name = info.node_name
        found = []
        # a node launched without an explicit name= has no __node:= remap in
        # its cmdline (e.g. the aggregator's converter_node) — fall back to
        # the ros2 executable naming convention <name>_node
        for pat in (f'__node:={name}', f'/{name}_node'):
            out = subprocess.run(['pgrep', '-f', pat], capture_output=True, text=True)
            found = [int(l) for l in out.stdout.split()]
            if found:
                break
        print(f'publisher {info.node_namespace}/{name}: pids {found}', flush=True)
        pids.update(found)
    return sorted(pids)

def main():
    ctx1, n1, ex1 = ctx_node(int(os.environ.get('ROS_DOMAIN_ID', '1')), 'si_demo_driver')
    vel = lambda t=8: latest(n1, ex1, Odometry, '/localization/kinematic_state', t,
                             field=lambda m: m.twist.twist.linear.x)

    print('== 0. wait for the sim stack (route state latched by ADAPI) ==', flush=True)
    while latest(n1, ex1, RouteState, '/planning/route_state', 5, transient=True) is None:
        time.sleep(2)

    print('== 1. initial pose ==', flush=True)
    pub_init = n1.create_publisher(PoseWithCovarianceStamped, '/initialpose', 1)
    m = PoseWithCovarianceStamped()
    m.header.frame_id = 'map'
    m.pose.pose.position.x, m.pose.pose.position.y = INIT[0], INIT[1]
    m.pose.pose.orientation.z, m.pose.pose.orientation.w = INIT[2], INIT[3]
    m.pose.covariance[0] = m.pose.covariance[7] = 0.25
    m.pose.covariance[35] = 0.068
    for _ in range(3):
        pub_init.publish(m); ex1.spin_once(timeout_sec=0.3); time.sleep(1)
    time.sleep(4)

    print('== 2. goal ==', flush=True)
    pub_goal = n1.create_publisher(PoseStamped, '/planning/mission_planning/goal', 1)
    g = PoseStamped(); g.header.frame_id = 'map'
    g.pose.position.x, g.pose.position.y = GOAL[0], GOAL[1]
    g.pose.orientation.z, g.pose.orientation.w = GOAL[2], GOAL[3]
    route = None
    for _ in range(10):
        pub_goal.publish(g); time.sleep(2)
        st = latest(n1, ex1, RouteState, '/planning/route_state', 4, transient=True)
        route = st.state if st else None
        if route == RouteState.SET: break
    print(f"route state: {route} (SET={RouteState.SET})", flush=True)
    if route != RouteState.SET:
        print('route not set — check goal placement'); sys.exit(2)

    print('== 3. engage autonomous ==', flush=True)
    cli = n1.create_client(ChangeOperationMode, '/api/operation_mode/change_to_autonomous')
    ok = False
    for i in range(8):
        if not cli.wait_for_service(timeout_sec=5): continue
        fut = cli.call_async(ChangeOperationMode.Request())
        t0 = time.time()
        while not fut.done() and time.time() - t0 < 10: ex1.spin_once(timeout_sec=0.2)
        ok = fut.done() and fut.result() and fut.result().status.success
        print(f'engage attempt {i+1}: {ok}', flush=True)
        if ok: break
        time.sleep(4)

    print('== 4. wait for motion ==', flush=True)
    v0 = 0.0
    for _ in range(20):
        v = vel(4)
        if v and v > 0.3: v0 = v; break
        time.sleep(2)
    print(f'velocity: {v0}', flush=True)

    print(f'== 4b. driving for {DRIVE_SECS:.0f}s ==', flush=True)
    time.sleep(DRIVE_SECS)
    v = vel(4)
    v0 = v if v is not None else v0
    print(f'velocity before fault: {v0}', flush=True)

    print(f'== 5. cut the heartbeat (SIGSTOP the {FAULT_TOPIC} publisher) ==', flush=True)
    pids = fault_pids(n1)
    if not pids:
        print(f'FATAL: no process found publishing {FAULT_TOPIC}'); sys.exit(2)
    for p in pids:
        try: os.kill(p, signal.SIGSTOP); print(f'pid {p} paused', flush=True)
        except ProcessLookupError: pass

    time.sleep(3)
    print('== 6. island verdict (expect state=2, behavior=2) ==', flush=True)
    st = latest(n1, ex1, MrmState, '/system/fail_safe/mrm_state', 8)
    print(f'state: {st.state if st else None}\nbehavior: {st.behavior if st else None}', flush=True)

    time.sleep(7)
    v1 = vel(8)
    print(f'velocity after island MRM: {v1}', flush=True)

    print('== 7. revive the heartbeat (SIGCONT) ==', flush=True)
    for p in pids:
        try: os.kill(p, signal.SIGCONT)
        except ProcessLookupError: pass

    ok_mrm = st is not None and st.state == 2 and st.behavior == 2
    ok_stop = v0 > 0.5 and v1 is not None and abs(v1) < 0.3

    print('== 8. wait for MRM recovery (island back to NORMAL) ==', flush=True)
    st2 = None
    t0 = time.time()
    while time.time() - t0 < 40:
        st2 = latest(n1, ex1, MrmState, '/system/fail_safe/mrm_state', 5)
        if st2 and st2.state == MrmState.NORMAL:
            break
    print(f'mrm after restore: state={st2.state if st2 else None} '
          f'behavior={st2.behavior if st2 else None} (NORMAL={MrmState.NORMAL})', flush=True)
    ok_recover = st2 is not None and st2.state == MrmState.NORMAL

    print('== 9. resume driving ==', flush=True)
    v2 = 0.0
    for i in range(30):
        v = vel(4)
        if v and v > 0.3:
            v2 = v; break
        if i == 7:  # ~30 s without motion — operation mode may have dropped; re-engage
            print('re-engaging autonomous...', flush=True)
            if cli.wait_for_service(timeout_sec=5):
                fut = cli.call_async(ChangeOperationMode.Request())
                t1 = time.time()
                while not fut.done() and time.time() - t1 < 10:
                    ex1.spin_once(timeout_sec=0.2)
                print(f're-engage: {fut.done() and fut.result() and fut.result().status.success}', flush=True)
        time.sleep(2)
    print(f'velocity after recovery: {v2}', flush=True)

    # The demo verdict ends at the resume — the island's whole story (fault ->
    # MRM stop -> heartbeat revives -> MRM clears -> vehicle moves again) is
    # proven. Full drive to the goal is opt-in (ARRIVE_SECS=300): the sample
    # route has intersection stop lines where the planner can hold for a long
    # time, which is Autoware behavior, not the island's.
    arrived = None
    arrive_secs = float(os.environ.get('ARRIVE_SECS', '0'))
    if arrive_secs > 0:
        print('== 10. drive to the goal (route ARRIVED) ==', flush=True)
        arrived = False
        t0 = time.time()
        while time.time() - t0 < arrive_secs:
            rs = latest(n1, ex1, RouteState, '/planning/route_state', 5, transient=True)
            if rs and rs.state == RouteState.ARRIVED:
                arrived = True; break
            time.sleep(2)
        print(f'route arrived: {arrived} (ARRIVED={RouteState.ARRIVED})', flush=True)

    if ok_stop and ok_mrm and ok_recover and v2 > 0.3 and arrived is not False:
        tail = ' and reached the goal' if arrived else ''
        print(f'VERDICT: PASS — island stopped the vehicle ({v0:.2f} -> {v1:.2f} m/s), '
              f'MRM recovered, vehicle resumed ({v2:.2f} m/s){tail}'); sys.exit(0)
    print(f'VERDICT: FAIL (stop={ok_stop} v {v0} -> {v1}, '
          f'mrm={st.state if st else None}/{st.behavior if st else None}, '
          f'recover={ok_recover}, resume_v={v2}, arrived={arrived})'); sys.exit(1)

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    main()
