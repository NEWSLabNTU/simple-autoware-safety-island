#!/usr/bin/env python3
"""analyze.py RUNDIR [SETTLE_S]: per-join verdict for a gate.sh run.

Segments start at each RESET line of poll.log. For each segment:
  join      first island mrm_state the host received after the reset (s after the reset)
  outputs   per-output host receive rate over [join+SETTLE, segment end]
  falseEm   mrm_state transitions to a state other than NORMAL (1) inside the segment
  gap       the longest mrm_state silence after the join (the reset's own gap excluded)
  board     serial counters' deltas over the in-run window, and per-subscription
            samples accepted vs samples the host published in the same window
"""
import ast, json, re, sys, bisect

import os
R = sys.argv[1]; SETTLE = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
# the outputs this image publishes (phase8-W8a's demo image drops gear and turn indicators)
EXPECT = os.environ.get("EXPECT", "mrm_state,emergency_control_cmd,emergency_gear_cmd,emergency_hazard,emergency_turn").split(",")
poll = open(f"{R}/poll.log").read().splitlines()
pub = open(f"{R}/pub.log").read().splitlines()

resets = [float(re.search(r"RESET issued wall=([\d.]+)", l).group(1)) for l in poll if "RESET issued" in l]
dones = [float(re.search(r"done=([\d.]+)", l).group(1)) for l in poll if "RESET issued" in l]
samples = []
for l in poll:
    m = re.search(r" wall=([\d.]+) (.*) tails=\[([^\]]*)\]", l)
    if not m or "RESET" in l:
        continue
    kv = dict(x.split("=") for x in m.group(2).split())
    kv = {k: int(v) for k, v in kv.items()}
    samples.append((float(m.group(1)), kv, [int(x) for x in m.group(3).split()]))

reports = []  # (wall, sent, recv)
for l in pub:
    m = re.match(r"wall=([\d.]+) t=\s*[\d.]+s sent=(\{.*?\}) recv=(\{.*?\}) ", l)
    if m:
        reports.append((float(m.group(1)), ast.literal_eval(m.group(2)), ast.literal_eval(m.group(3))))
rw = [r[0] for r in reports]

def interp(w, field, key):
    i = bisect.bisect_left(rw, w)
    if i <= 0: return reports[0][field][key]
    if i >= len(reports): return reports[-1][field][key]
    (w0, *a), (w1, *b) = reports[i - 1], reports[i]
    v0 = a[field - 1][key]; v1 = b[field - 1][key]
    return v0 + (v1 - v0) * (w - w0) / (w1 - w0)

firsts = []
for l in pub:
    m = re.search(r"island first mrm_state \(this instance\) at t=[\d.]+s wall=([\d.]+)", l)
    if m: firsts.append(float(m.group(1)))
gaps = []
for l in pub:
    m = re.search(r"GAP mrm_state ([\d.]+)s ending t=[\d.]+s wall=([\d.]+)", l)
    if m: gaps.append((float(m.group(2)), float(m.group(1))))
states = []
for l in pub:
    m = re.search(r"mrm_state -> state=(\d+) behavior=(\d+) at t=[\d.]+s wall=([\d.]+)", l)
    if m: states.append((float(m.group(3)), int(m.group(1)), int(m.group(2))))

pub_t0 = reports[0][0] - float(re.match(r"wall=[\d.]+ t=\s*([\d.]+)s", [l for l in pub if l.startswith("wall=")][0]).group(1)) if reports else None
RATE30 = ["control_cmd", "steering_status", "velocity_status", "route_state"]
RATE10 = ["availability", "kinematic_state", "control_mode", "gear_cmd", "operation_mode_state"]
end_all = samples[-1][0] if samples else 0
verdicts = []
for i, r in enumerate(resets):
    seg_end = resets[i + 1] if i + 1 < len(resets) else end_all
    # the join: first mrm_state after the reset
    cands = [f for f in firsts if r < f < seg_end] + [g[0] for g in gaps if r < g[0] < seg_end]
    join = min(cands) if cands else None
    out = {"seg": i, "kind": "cold" if i == 0 else "mid-run", "reset_wall": round(r, 3),
           "len_s": round(seg_end - r, 1)}
    out["inputs_flowing_before_reset_s"] = round(r - pub_t0, 1) if pub_t0 else None
    out["join_s"] = round(join - r, 3) if join is not None else None
    out["join_after_reset_done_s"] = round(join - dones[i], 3) if join is not None else None
    segs = [x for x in samples if r <= x[0] <= seg_end]
    if segs:
        k1 = segs[-1][1]
        out["segment_totals_from_boot"] = {k: k1[k] for k in ("ring_overflows", "rx_bad_frames", "overruns", "rej",
                                                               "ring_high_water", "framing_errors", "noise_errors") if k in k1}
    if join is None:
        join = r + 5.0
    a, b = join + SETTLE, seg_end - 1.0
    # host-side outputs
    rates = {}
    for k in reports[0][2]:
        rates[k] = round((interp(b, 2, k) - interp(a, 2, k)) / (b - a), 2)
    out["out_rates"] = rates
    out["false_emergency"] = [s for s in states if r < s[0] <= seg_end and s[1] != 1]
    g_in = [g for g in gaps if join + 0.5 < g[0] <= seg_end]
    out["mrm_gaps_gt_0.3s_after_join"] = g_in
    # a gap during which the HOST's own 30 Hz publisher also fell behind is the
    # harness stalling (host load), not the island or the link
    def host_rate(a, b):
        rows = [x for x in reports if a - 1.0 <= x[0] <= b + 1.0]
        worst = None
        for x0, x1 in zip(rows, rows[1:]):
            r_ = (x1[1][RATE30[0]] - x0[1][RATE30[0]]) / max(x1[0] - x0[0], 1e-3)
            worst = r_ if worst is None else min(worst, r_)
        return worst
    out["gaps_with_host_publisher_stalled"] = [(g[0], g[1], round(host_rate(g[0] - g[1], g[0]), 1)) for g in g_in
                                               if (host_rate(g[0] - g[1], g[0]) or 30) < 25]
    unexplained = [g for g in g_in if (host_rate(g[0] - g[1], g[0]) or 30) >= 25]
    # board window
    win = [s for s in samples if a <= s[0] <= b]
    if len(win) >= 2:
        (w0, k0, t0), (w1, k1, t1) = win[0], win[-1]
        d = {k: k1[k] - k0.get(k, 0) for k in ("overruns", "ring_overflows", "rx_bad_frames", "rx_partial", "rej",
                                                "tx_timeouts", "tx_waits", "framing_errors", "noise_errors", "parity_errors") if k in k1}
        d["rx_ring_high_water"] = k1.get("ring_high_water"); d["tx_ring_high_water"] = k1.get("tx_ring_high_water")
        out["board_delta"] = d
        sent30 = interp(w1, 1, RATE30[0]) - interp(w0, 1, RATE30[0])
        sent10 = interp(w1, 1, RATE10[0]) - interp(w0, 1, RATE10[0])
        tails = [x1 - x0 for x0, x1 in zip(t0, t1)]
        out["window_s"] = round(w1 - w0, 1)
        out["host_sent_per_topic"] = {"30Hz": round(sent30, 1), "10Hz": round(sent10, 1)}
        out["island_took_per_slot"] = tails
    fe = len(out["false_emergency"]) > 0
    silent = [k for k, v in rates.items() if v < 1.0 and k in EXPECT]
    if out["inputs_flowing_before_reset_s"] is None or out["inputs_flowing_before_reset_s"] < 5:
        out["verdict"] = "INVALID (inputs not flowing before the reset)"; verdicts.append(out); print(json.dumps(out)); continue
    out["verdict"] = "FAIL" if (fe or silent or unexplained or out["join_s"] is None) else "ok"
    if silent: out["silent_outputs"] = silent
    verdicts.append(out)
    print(json.dumps(out))
