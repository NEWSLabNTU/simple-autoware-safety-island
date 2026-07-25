#!/usr/bin/env python3
"""Phase-2 demo driver — pure rclpy (no ros2-CLI daemon dependency).

Sequence: init pose -> goal -> engage -> drive DRIVE_SECS -> SIGSTOP the
bridge group(s) (heartbeat fault) -> verify island MRM on domain 2 ->
verify vehicle stops -> resume bridges -> print VERDICT (exit 0 = PASS).

Env: DRIVE_SECS (15), INIT_X/Y/QZ/QW, GOAL_X/Y/QZ/QW.
Run under an env with ROS 2 Humble + the Autoware msgs sourced; the split
lo cyclone config is set inside (both domains) unless CYCLONEDDS_URI is set.
"""
import os, sys, time, signal, subprocess, math

LO_URI = ('<CycloneDDS><Domain Id="any"><General>'
          '<Interfaces><NetworkInterface name="lo"/></Interfaces>'
          '<AllowMulticast>spdp</AllowMulticast></General>'
          '<Discovery><ParticipantIndex>auto</ParticipantIndex>'
          '<MaxAutoParticipantIndex>60</MaxAutoParticipantIndex>'
          '<Peers><Peer Address="127.0.0.1"/></Peers></Discovery>'
          '</Domain></CycloneDDS>')
os.environ['CYCLONEDDS_URI'] = LO_URI  # FORCE: the sourced Autoware env's URI lacks
# the unicast peer scan the ZEPHYR island's baked discovery needs (domain 2)
os.environ['RMW_IMPLEMENTATION'] = 'rmw_cyclonedds_cpp'

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

def main():
    ctx1, n1, ex1 = ctx_node(1, 'si_demo_driver_d1')
    ctx2, n2, ex2 = ctx_node(2, 'si_demo_driver_d2')
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

    print('== 5. cut the bridge (SIGSTOP both legs — nano-ros #267 caveat) ==', flush=True)
    pgids = []
    for f in ('demo/.bridge-fwd.pgid', 'demo/.bridge-rev.pgid', 'demo/.bridge.pgid'):
        try: pgids.append(int(open(f).read().strip()))
        except Exception: pass
    for pg in pgids:
        try: os.killpg(pg, signal.SIGSTOP); print(f'bridge group {pg} paused', flush=True)
        except ProcessLookupError: pass

    time.sleep(3)
    print('== 6. island verdict (expect state=2, behavior=2) ==', flush=True)
    st = latest(n2, ex2, MrmState, '/system/fail_safe/mrm_state', 8)
    print(f'state: {st.state if st else None}\nbehavior: {st.behavior if st else None}', flush=True)

    time.sleep(7)
    v1 = vel(8)
    print(f'velocity after island MRM: {v1}', flush=True)

    print('== 7. restore bridges ==', flush=True)
    for pg in pgids:
        try: os.killpg(pg, signal.SIGCONT)
        except ProcessLookupError: pass

    ok_mrm = st is not None and st.state == 2 and st.behavior == 2
    if v0 > 0.5 and v1 is not None and abs(v1) < 0.3 and ok_mrm:
        print(f'VERDICT: PASS — island stopped the vehicle ({v0:.2f} -> {v1:.2f} m/s)'); sys.exit(0)
    print(f'VERDICT: FAIL (v {v0} -> {v1}, mrm={st.state if st else None}/{st.behavior if st else None})'); sys.exit(1)

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    main()
