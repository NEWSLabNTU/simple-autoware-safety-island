#!/usr/bin/env python3
"""phase9-W9: the island's hazard command through Autoware's real
vehicle_cmd_gate, without the board.

Starts the installed autoware_vehicle_cmd_gate (1.5.0, the demo's parameter
file) and, with --wiring restamp, island_restamp's hazard_lights_restamp in
front of its emergency hazard input, then plays an EMERGENCY_STOP as the
board does: mrm_state NORMAL, then MRM_OPERATING / EMERGENCY_STOP, then
NORMAL again, at 10 Hz, with the island's hazard command (NO_COMMAND, ENABLE,
NO_COMMAND) stamped from the island's boot, and the planner's hazard command
(DISABLE, the selector's output) stamped by the host. It reads the gate's
/control/command/hazard_lights_cmd in each phase.

  --clock wall   the planning simulator: the host runs on the wall clock
  --clock sim    CARLA: the gate runs on /clock (published here, from
                 --sim-s); the island's boot stamp (--boot-s) is later than
                 the simulation time by default

Verdict (exit 0 when it holds): the gate's output is ENABLE while the
emergency stop runs and the planner's DISABLE again after it ends. With
--wiring stock the same run reproduces W9: wall, no ENABLE in the emergency
stop (the gate drops the boot stamp as older than its last output); sim with
a boot stamp later than /clock, the ENABLE gets through, and after the
emergency the gate stays latched at the island's last command (NO_COMMAND,
which acb ignores, so the vehicle's lights stay ENABLE into the next act). Run it on a domain of its own, e.g.

  env -i HOME=$HOME PATH=/usr/bin:/bin ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 \\
    bash -c 'source /opt/ros/humble/setup.bash && source /opt/autoware/1.5.0/setup.bash \\
             && source <overlay>/install/setup.bash \\
             && python3 gate_replay.py --wiring restamp --clock wall'
"""
import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time

import rclpy
from autoware_adapi_v1_msgs.msg import MrmState
from autoware_vehicle_msgs.msg import Engage, HazardLightsCommand
from builtin_interfaces.msg import Time
from rclpy.node import Node
from rclpy.qos import QoSProfile
from rosgraph_msgs.msg import Clock

ISLAND = '/system/emergency/hazard_lights_cmd'
RESTAMPED = '/system/emergency/hazard_lights_cmd_restamped'
NAMES = {0: 'NO_COMMAND', 1: 'DISABLE', 2: 'ENABLE'}


def gate_params(tmp):
    """The demo's gate parameters with the external heartbeat check off (no
    external API here); the substitution the launch file would make."""
    share = subprocess.check_output(['ros2', 'pkg', 'prefix', '--share', 'autoware_launch'], text=True).strip()
    src = os.path.join(share, 'config/control/vehicle_cmd_gate/vehicle_cmd_gate.param.yaml')
    with open(src) as f:
        text = f.read().replace('$(var check_external_emergency_heartbeat)', 'false')
    path = os.path.join(tmp, 'vehicle_cmd_gate.param.yaml')
    with open(path, 'w') as f:
        f.write(text)
    vinfo = os.path.join(subprocess.check_output(
        ['ros2', 'pkg', 'prefix', '--share', 'sample_vehicle_description'], text=True).strip(),
        'config/vehicle_info.param.yaml')
    return path, vinfo


def stamp(ns):
    return Time(sec=ns // 1_000_000_000, nanosec=ns % 1_000_000_000)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--wiring', choices=['stock', 'restamp'], required=True)
    ap.add_argument('--clock', choices=['wall', 'sim'], required=True)
    ap.add_argument('--boot-s', type=float, default=None,
                    help='the island stamp at the start (default: 120 on wall, sim-s + 400 on sim)')
    ap.add_argument('--sim-s', type=float, default=500.0, help='/clock at the start (sim only)')
    ap.add_argument('--phase-s', type=float, default=3.0, help='length of each of the three phases')
    a = ap.parse_args()
    sim = a.clock == 'sim'
    boot0 = int(((a.sim_s + 400.0) if sim and a.boot_s is None else (a.boot_s or 120.0)) * 1e9)
    sim0 = int(a.sim_s * 1e9)

    procs = []
    tmp = tempfile.mkdtemp(prefix='w9-gate-')
    params, vinfo = gate_params(tmp)
    st = 'true' if sim else 'false'
    gate_in = RESTAMPED if a.wiring == 'restamp' else ISLAND
    procs.append(subprocess.Popen(
        ['ros2', 'run', 'autoware_vehicle_cmd_gate', 'vehicle_cmd_gate_exe', '--ros-args',
         '-r', '__node:=vehicle_cmd_gate', '--params-file', params, '--params-file', vinfo,
         '-p', f'use_sim_time:={st}',
         '-r', 'input/mrm_state:=/system/fail_safe/mrm_state',
         '-r', 'input/auto/hazard_lights_cmd:=/planning/hazard_lights_cmd',
         '-r', f'input/emergency/hazard_lights_cmd:={gate_in}',
         '-r', 'input/engage:=/autoware/engage',
         '-r', 'output/hazard_lights_cmd:=/control/command/hazard_lights_cmd'],
        stdout=open(os.path.join(tmp, 'gate.log'), 'w'), stderr=subprocess.STDOUT, start_new_session=True))
    if a.wiring == 'restamp':
        procs.append(subprocess.Popen(
            ['ros2', 'run', 'island_restamp', 'hazard_lights_restamp', '--ros-args',
             '-p', f'use_sim_time:={st}', '-r', f'input:={ISLAND}', '-r', f'output:={RESTAMPED}'],
            stdout=open(os.path.join(tmp, 'restamp.log'), 'w'), stderr=subprocess.STDOUT,
            start_new_session=True))

    rclpy.init()
    node = Node('w9_gate_replay')
    q = QoSProfile(depth=1)
    pub_mrm = node.create_publisher(MrmState, '/system/fail_safe/mrm_state', q)
    pub_engage = node.create_publisher(Engage, '/autoware/engage', q)
    pub_auto = node.create_publisher(HazardLightsCommand, '/planning/hazard_lights_cmd', q)
    pub_island = node.create_publisher(HazardLightsCommand, ISLAND, q)
    pub_clock = node.create_publisher(Clock, '/clock', QoSProfile(depth=10))
    seen = []  # (phase, command)
    phase = ['warmup']
    node.create_subscription(HazardLightsCommand, '/control/command/hazard_lights_cmd',
                             lambda m: seen.append((phase[0], m.command)), QoSProfile(depth=10))

    t_start = time.monotonic()

    def host_ns():
        el = int((time.monotonic() - t_start) * 1e9)
        return sim0 + el if sim else time.time_ns()

    def tick(emergency):
        el = int((time.monotonic() - t_start) * 1e9)
        if sim:
            pub_clock.publish(Clock(clock=stamp(sim0 + el)))
        m = MrmState(stamp=stamp(host_ns()))
        m.state = MrmState.MRM_OPERATING if emergency else MrmState.NORMAL
        m.behavior = MrmState.EMERGENCY_STOP if emergency else MrmState.NONE
        pub_mrm.publish(m)
        pub_engage.publish(Engage(stamp=stamp(host_ns()), engage=True))
        pub_auto.publish(HazardLightsCommand(stamp=stamp(host_ns()), command=HazardLightsCommand.DISABLE))
        pub_island.publish(HazardLightsCommand(
            stamp=stamp(boot0 + el),
            command=HazardLightsCommand.ENABLE if emergency else HazardLightsCommand.NO_COMMAND))

    def run(name, secs, emergency):
        phase[0] = name
        end = time.monotonic() + secs
        while time.monotonic() < end:
            tick(emergency)
            t = time.monotonic() + 0.1
            while time.monotonic() < t:
                rclpy.spin_once(node, timeout_sec=0.01)

    try:
        run('warmup', 3.0, False)      # discovery, the gate's first outputs
        run('before', a.phase_s, False)
        run('emergency', a.phase_s, True)
        run('after', a.phase_s, False)
    finally:
        for p in procs:
            try:
                os.killpg(p.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
        node.destroy_node()
        rclpy.shutdown()

    def summary(name):
        cs = [c for p, c in seen if p == name]
        return cs, ' '.join(f'{NAMES.get(c, c)}x{cs.count(c)}' for c in sorted(set(cs))) or 'nothing'

    print(f'wiring {a.wiring}, clock {a.clock}, island boot stamp {boot0 / 1e9:.1f} s'
          + (f', /clock {sim0 / 1e9:.1f} s' if sim else ', host wall clock'))
    for name in ('before', 'emergency', 'after'):
        print(f'  {name:9s} gate output: {summary(name)[1]}')
    em, _ = summary('emergency')
    af, _ = summary('after')
    # the last half of each phase: past the 10 Hz edges
    on = bool(em) and em[len(em) // 2:].count(HazardLightsCommand.ENABLE) == len(em[len(em) // 2:])
    # the planner's DISABLE gets through again: a gate latched at the island's
    # last NO_COMMAND is not "cleared" (acb ignores NO_COMMAND and keeps the
    # vehicle's lights ENABLE)
    off = bool(af) and af[len(af) // 2:].count(HazardLightsCommand.DISABLE) == len(af[len(af) // 2:])
    ok = on and off
    print(f'  ENABLE in the emergency stop: {"yes" if on else "NO"}; '
          f'the planner\'s DISABLE after it: {"yes" if off else "NO"} -> {"PASS" if ok else "FAIL"} (logs {tmp})')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
