#!/usr/bin/env python3
"""phase9-W9: the island's hazard command through the whole host chain, in
every MRM state, without the board.

Starts Autoware's real autoware_hazard_lights_selector and
autoware_vehicle_cmd_gate (1.5.0, the demo's parameters), island_restamp's
hazard_lights_restamp in front of the gate's emergency input (the overlay's
wiring), and the publisher(s) of the selector's system input,
/system/hazard_lights_cmd:

  --wiring new   takeover_demo's hazard_relay alone (its one owner)
  --wiring old   hazard_relay AND W18's topic_tools relay (the race)

It then plays the island as the board does, at 10 Hz, its hazard command
stamped from its boot, and reads the gate's /control/command/hazard_lights_cmd
(what the vehicle gets) in each phase:

  phase              mrm_state                        island    expected
  normal             NORMAL / NONE                    NO_CMD    DISABLE
  takeover_request   NORMAL / NONE (TOR running)      ENABLE    ENABLE
  comfortable_stop   MRM_OPERATING / COMFORTABLE_STOP ENABLE    ENABLE
  emergency_stop     MRM_OPERATING / EMERGENCY_STOP   ENABLE    ENABLE
  normal_after       NORMAL / NONE                    NO_CMD    DISABLE

A phase passes when every gate output in its second half is the expected
command; exit 0 when all pass. Run it on a domain of its own, with Autoware
and the demo overlay sourced, e.g.

  env -i HOME=$HOME PATH=/usr/bin:/bin ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 \\
    bash -c 'source /opt/ros/humble/setup.bash && source /opt/autoware/1.5.0/setup.bash \\
             && source <overlay>/install/setup.bash \\
             && python3 hazard_chain_replay.py --wiring new'
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

ISLAND = '/system/emergency/hazard_lights_cmd'
RESTAMPED = '/system/emergency/hazard_lights_cmd_restamped'
SYSTEM = '/system/hazard_lights_cmd'
PLANNER = '/planning/behavior_path_planner/hazard_lights_cmd'
SELECTED = '/planning/hazard_lights_cmd'
OUT = '/control/command/hazard_lights_cmd'
NAMES = {0: 'NO_COMMAND', 1: 'DISABLE', 2: 'ENABLE'}
E, D, N = HazardLightsCommand.ENABLE, HazardLightsCommand.DISABLE, HazardLightsCommand.NO_COMMAND
PHASES = [  # name, mrm state, mrm behavior, island command, expected gate output
    ('normal', MrmState.NORMAL, MrmState.NONE, N, D),
    ('takeover_request', MrmState.NORMAL, MrmState.NONE, E, E),
    ('comfortable_stop', MrmState.MRM_OPERATING, MrmState.COMFORTABLE_STOP, E, E),
    ('emergency_stop', MrmState.MRM_OPERATING, MrmState.EMERGENCY_STOP, E, E),
    ('normal_after', MrmState.NORMAL, MrmState.NONE, N, D),
]


def share(pkg):
    return subprocess.check_output(['ros2', 'pkg', 'prefix', '--share', pkg], text=True).strip()


def gate_params(tmp):
    with open(os.path.join(share('autoware_launch'),
                           'config/control/vehicle_cmd_gate/vehicle_cmd_gate.param.yaml')) as f:
        text = f.read().replace('$(var check_external_emergency_heartbeat)', 'false')
    path = os.path.join(tmp, 'vehicle_cmd_gate.param.yaml')
    with open(path, 'w') as f:
        f.write(text)
    return path, os.path.join(share('sample_vehicle_description'), 'config/vehicle_info.param.yaml')


def stamp(ns):
    return Time(sec=ns // 1_000_000_000, nanosec=ns % 1_000_000_000)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--wiring', choices=['new', 'old'], required=True)
    ap.add_argument('--phase-s', type=float, default=3.0)
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix='w9-chain-')
    gparams, vinfo = gate_params(tmp)
    cmds = {
        'gate': ['ros2', 'run', 'autoware_vehicle_cmd_gate', 'vehicle_cmd_gate_exe', '--ros-args',
                 '-r', '__node:=vehicle_cmd_gate', '--params-file', gparams, '--params-file', vinfo,
                 '-r', 'input/mrm_state:=/system/fail_safe/mrm_state',
                 '-r', f'input/auto/hazard_lights_cmd:={SELECTED}',
                 '-r', f'input/emergency/hazard_lights_cmd:={RESTAMPED}',
                 '-r', 'input/engage:=/autoware/engage',
                 '-r', f'output/hazard_lights_cmd:={OUT}'],
        'selector': ['ros2', 'run', 'autoware_hazard_lights_selector',
                     'autoware_hazard_lights_selector_node', '--ros-args',
                     '--params-file', os.path.join(share('autoware_hazard_lights_selector'),
                                                   'config/hazard_lights_selector.param.yaml'),
                     '-r', f'input/planning/hazard_lights_command:={PLANNER}',
                     '-r', f'input/system/hazard_lights_command:={SYSTEM}',
                     '-r', f'output/hazard_lights_command:={SELECTED}'],
        'restamp': ['ros2', 'run', 'island_restamp', 'hazard_lights_restamp', '--ros-args',
                    '-r', f'input:={ISLAND}', '-r', f'output:={RESTAMPED}'],
        'hazard_relay': ['ros2', 'run', 'takeover_demo', 'hazard_relay', '--ros-args',
                         '-p', 'rate_hz:=10.0', '-p', 'input_timeout_s:=1.0'],
    }
    if a.wiring == 'old':
        cmds['topic_tools_relay'] = ['ros2', 'run', 'topic_tools', 'relay', '--ros-args',
                                     '-p', f'input_topic:={ISLAND}', '-p', f'output_topic:={SYSTEM}']
    procs = [subprocess.Popen(c, stdout=open(os.path.join(tmp, f'{k}.log'), 'w'),
                              stderr=subprocess.STDOUT, start_new_session=True)
             for k, c in cmds.items()]

    rclpy.init()
    node = Node('w9_chain_replay')
    q = QoSProfile(depth=1)
    pub_mrm = node.create_publisher(MrmState, '/system/fail_safe/mrm_state', q)
    pub_engage = node.create_publisher(Engage, '/autoware/engage', q)
    pub_planner = node.create_publisher(HazardLightsCommand, PLANNER, q)
    pub_island = node.create_publisher(HazardLightsCommand, ISLAND, q)
    phase = ['warmup']
    seen = []
    node.create_subscription(HazardLightsCommand, OUT, lambda m: seen.append((phase[0], m.command)),
                             QoSProfile(depth=10))
    t0 = time.monotonic()

    def run(name, secs, state, behavior, island):
        phase[0] = name
        end = time.monotonic() + secs
        while time.monotonic() < end:
            now = time.time_ns()
            pub_mrm.publish(MrmState(stamp=stamp(now), state=state, behavior=behavior))
            pub_engage.publish(Engage(stamp=stamp(now), engage=True))
            pub_planner.publish(HazardLightsCommand(stamp=stamp(now), command=D))
            boot = int((120.0 + time.monotonic() - t0) * 1e9)
            pub_island.publish(HazardLightsCommand(stamp=stamp(boot), command=island))
            t = time.monotonic() + 0.1
            while time.monotonic() < t:
                rclpy.spin_once(node, timeout_sec=0.01)

    try:
        run('warmup', 4.0, MrmState.NORMAL, MrmState.NONE, N)
        n_system_pubs = node.count_publishers(SYSTEM)
        for name, st, bh, isl, _ in PHASES:
            run(name, a.phase_s, st, bh, isl)
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

    print(f'wiring {a.wiring}: {n_system_pubs} publisher(s) on {SYSTEM}')
    ok = True
    for name, _, _, _, want in PHASES:
        cs = [c for p, c in seen if p == name]
        tail = cs[len(cs) // 2:]
        good = bool(tail) and all(c == want for c in tail)
        ok &= good
        counts = ' '.join(f'{NAMES[c]}x{cs.count(c)}' for c in sorted(set(cs))) or 'nothing'
        print(f'  {name:17s} want {NAMES[want]:8s} got {counts:28s} {"ok" if good else "FAIL"}')
    print(f'  -> {"PASS" if ok else "FAIL"} (logs {tmp})')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
