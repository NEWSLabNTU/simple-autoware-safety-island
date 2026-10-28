#!/usr/bin/env python3
"""The diagnostic graph's leaves, recorded beside an act (phase9-C8).

  diaggraph.py --out <run dir>/diag.rec

Writes JSON lines (not .jsonl: the timeline tools read every *.jsonl in a run
directory as events): `struct` once (/diagnostics_graph/struct, leaf names and
node paths), `status` on every aggregator tick that has a leaf at ERROR or
STALE or a mode not OK (the bad leaves with [level, input_level, message] and
every /autoware/modes/* level), and `diag` for every /diagnostics status that
names a graph leaf (its arrival). `t` is the receive time on CLOCK_MONOTONIC.
From the arrivals and the ticks one reads a leaf's period and how old its
last sample was at each tick, i.e. how close it came to its graph timeout.

With run-board.sh, beside the probe (the path literal, $dir is not expanded):
  RB_PROBE="python3 $PWD/tools/eval/diaggraph.py --out $PWD/build/timeline/<id>/diag.rec &
            exec python3 tools/board/probe.py --out $PWD/build/timeline/<id>/probe.jsonl"
"""
import argparse
import json
import time

import rclpy
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from diagnostic_msgs.msg import DiagnosticArray
from tier4_system_msgs.msg import DiagGraphStatus, DiagGraphStruct

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
a = ap.parse_args()
f = open(a.out, "w", buffering=1)


def lv(x):
    return x[0] if isinstance(x, (bytes, bytearray)) else int(x)


def w(**kw):
    kw["t"] = time.monotonic_ns()
    f.write(json.dumps(kw) + "\n")


rclpy.init()
node = rclpy.create_node("diag_rec")
latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
vol = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
st = {"diags": None, "nodes": None, "id": None, "bad": {}}


def on_struct(m):
    st["diags"] = [d.name for d in m.diags]
    st["nodes"] = [n.path for n in m.nodes]
    st["id"] = m.id
    w(k="struct", id=m.id, diags=st["diags"], nodes=st["nodes"])


def on_status(m):
    if st["diags"] is None or m.id != st["id"]:
        return
    bad = {}
    for i, d in enumerate(m.diags):
        if lv(d.level) >= 2 or lv(d.input_level) >= 2:
            bad[st["diags"][i]] = [lv(d.level), lv(d.input_level), d.message]
    modes = {}
    for i, n in enumerate(m.nodes):
        p = st["nodes"][i]
        if p.startswith("/autoware/modes/"):
            modes[p[16:]] = lv(n.level)
    if bad or any(v >= 2 for v in modes.values()):
        w(k="status", stamp=m.stamp.sec * 10**9 + m.stamp.nanosec, bad=bad, modes=modes)


def on_diag(m):
    if st["diags"] is None:
        return
    names = set(st["diags"])
    for s in m.status:
        if s.name in names:
            w(k="diag", name=s.name, level=lv(s.level))


node.create_subscription(DiagGraphStruct, "/diagnostics_graph/struct", on_struct, latched)
node.create_subscription(DiagGraphStatus, "/diagnostics_graph/status", on_status, vol)
node.create_subscription(DiagnosticArray, "/diagnostics", on_diag, QoSProfile(depth=1000, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE))
try:
    rclpy.spin(node)
except KeyboardInterrupt:
    pass
