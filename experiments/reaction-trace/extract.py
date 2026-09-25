#!/usr/bin/env python3
"""phase7-W3: the fault-reaction timeline from an island trace.

  extract.py <trace> [--events run.events.jsonl] [--run ID] [--json out.json]
  extract.py summary runs/*.json [--csv out.csv]

Reads the trace with src/safety_island_tracing/island_trace.py (no decoder of
its own) and walks the reaction the contract declares for the hazard
operation_mode_unavailable:

  T_take    last TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY before the gap
  T_fresh   the last handler tick that still saw the sample as fresh
  T_detect  the handler tick where PATH_MRM_HANDLER_CALL_MRM_ENTRY first fires
  T_call    CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE (operate=1)
  T_serve   SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_ENTRY / _EXIT (operate=1)
  T_brake   the operator's first PATH_..._ON_TIMER_ENTRY in OPERATING, and its
            PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD
  T_stopped the first PUB_MRM_HANDLER_MRM_STATE with state MRM_SUCCEEDED: the
            handler saw |v| < 0.001 m/s on its kinematic_state input

All times are native_sim SIMULATED time. native_sim executes code in zero
simulated time, so an interval inside one callback is an artefact (it is 0,
or a few microseconds of timer-read granularity), never an execution time.
What is real are the WAITS between callbacks.

With --events (inject.py's log), the host wall-clock events (the SIGSTOP,
the odometry, the island's mrm_state as received on the host) are mapped
into simulated time by aligning the first MRM_OPERATING mrm_state sample the
host received with the island's PUB_MRM_HANDLER_MRM_STATE that carried it;
a second anchor (the last availability sample, received by both the island
and the host) bounds the alignment error.
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src/safety_island_tracing"))
import island_trace  # noqa: E402

DECLARED = dict(detection=500.0, reaction=110.0, sampling=1000.0 / 30, settle=2034.0, ftti=3000.0)
MRM_OPERATING, MRM_SUCCEEDED, OPERATING = 2, 3, 2

QUAL = ("native_sim SIMULATED time. Code runs in zero simulated time: an interval inside one "
        "callback is an artefact, not an execution time; the waits between callbacks are real.")


def ms(ns):
    return ns / 1e6


def first(ms_, pred, after=None, before=None):
    for r in ms_:
        if after is not None and r["t_ns"] < after:
            continue
        if before is not None and r["t_ns"] > before:
            return None
        if pred(r):
            return r
    return None


def last(ms_, pred, before):
    out = None
    for r in ms_:
        if r["t_ns"] > before:
            break
        if pred(r):
            out = r
    return out


def gaps(mk, min_ms=500.0):
    takes = [r["t_ns"] for r in mk if r["name"] == "TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY"]
    return [(a, b) for a, b in zip(takes, takes[1:] + [None]) if b is None or ms(b - a) > min_ms]


def read_events(path):
    ev = [json.loads(l) for l in open(path) if l.strip()]
    return ev


def extract(path, events=None, run=None):
    tr = island_trace.load(path)
    if tr.error:
        sys.exit(f"extract: decode error: {tr.error}")
    mk = [r for r in tr.records if r["kind"] == "marker"]
    n = lambda s: (lambda r: r["name"] == s)  # noqa: E731
    CALLMRM = "PATH_MRM_HANDLER_CALL_MRM_ENTRY"
    all_gaps = gaps(mk)
    # the fault gap: the first silence > 500 ms that the handler answered with
    # an operate=1 call to the emergency-stop operator
    # The fault gap: the LONGEST silence > 500 ms that the handler
    # answered with an operate=1 call to the emergency-stop operator. Not the
    # first: every trace also has a boot gap (first sample ~0.2 s, second
    # ~0.8 s, while discovery settles) that the handler answers with a call at
    # 0.8 s, before the vehicle is engaged; and the last gap is open (Autoware
    # shut down before the island) and short, unless availability never came
    # back (W1's demo.trace). Both are reported under other_gaps.
    answered = [(a, b) for a, b in all_gaps if first(
        mk, lambda r: r["name"] == "CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE" and r["arg"] == 1,
        after=a, before=b)]
    end = mk[-1]["t_ns"]
    chosen = max(answered, key=lambda g: (g[1] or end) - g[0]) if answered else None
    if not chosen:
        sys.exit(f"extract: no availability gap > 500 ms answered by an operate call in {path} "
                 f"(gaps: {[(ms(a), ms(b) if b else None) for a, b in all_gaps]})")
    t_take, t_resume = chosen
    ticks = [r["t_ns"] for r in mk if r["name"] == "PATH_MRM_HANDLER_ON_TIMER_ENTRY"]
    detect = first(mk, n(CALLMRM), after=t_take)
    t_detect = detect["t_ns"]
    t_fresh = max(t for t in ticks if t < t_detect)
    call = first(mk, lambda r: r["name"] == "CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE" and r["arg"] == 1,
                 after=t_detect)
    mstate = first(mk, lambda r: r["name"] == "PUB_MRM_HANDLER_MRM_STATE" and r["arg"] >> 16 == MRM_OPERATING,
                   after=t_detect)
    s_in = first(mk, lambda r: r["name"] == "SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_ENTRY" and r["arg"] == 1,
                 after=call["t_ns"])
    s_out = first(mk, n("SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_EXIT"), after=s_in["t_ns"])
    op_prev = last(mk, n("PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER_ENTRY"), before=s_in["t_ns"])
    op = first(mk, lambda r: r["name"] == "PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER_ENTRY" and r["arg"] == OPERATING,
               after=s_out["t_ns"])
    pub = first(mk, lambda r: r["name"] == "PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD" and r["arg"] == OPERATING,
                after=op["t_ns"])
    succ = first(mk, lambda r: r["name"] == "PUB_MRM_HANDLER_MRM_STATE" and r["arg"] >> 16 == MRM_SUCCEEDED,
                 after=t_detect)
    op_ticks = [r["t_ns"] for r in mk if r["name"] == "PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER_ENTRY"
                and t_take - 1e9 < r["t_ns"] < t_take + 3e9]
    op_periods = [ms(b - a) for a, b in zip(op_ticks, op_ticks[1:])]
    h_periods = [ms(b - a) for a, b in zip(ticks, ticks[1:]) if t_take - 1e9 < a < t_take + 3e9]
    # threads that ran between the call and the serve (the service hop)
    sw = [r for r in tr.records if r["kind"] == "thread_switched_in" and call["t_ns"] <= r["t_ns"] <= s_in["t_ns"]]

    T = dict(take=t_take, fresh=t_fresh, detect=t_detect, call=call["t_ns"], mrm_state=mstate["t_ns"],
             serve_entry=s_in["t_ns"], serve_exit=s_out["t_ns"], op_prev_tick=op_prev["t_ns"],
             op_brake_tick=op["t_ns"], brake_pub=pub["t_ns"],
             stopped_state=succ["t_ns"] if succ else None, resume_take=t_resume)
    # the marker record order inside the callback, to show order where time is 0
    order = [r["name"] for r in mk if t_detect <= r["t_ns"] <= pub["t_ns"]
             and "COMFORTABLE" not in r["name"]
             and (r["name"].startswith(("PATH_MRM_HANDLER", "CALL_", "SERVE_", "PUB_MRM_HANDLER_MRM_STATE"))
                  or r["t_ns"] == pub["t_ns"])]
    iv = {}
    d = lambda a, b: None if T[a] is None or T[b] is None else ms(T[b] - T[a])  # noqa: E731
    iv["take_to_stale"] = 500.0  # the threshold itself: a parameter, not an observation
    iv["take_to_fresh_tick"] = d("take", "fresh")
    iv["stale_to_detect_tick"] = ms(T["detect"] - T["take"]) - 500.0
    iv["take_to_detect"] = d("take", "detect")
    iv["detect_to_call"] = d("detect", "call")
    iv["call_to_serve_entry"] = d("call", "serve_entry")
    iv["serve_entry_to_exit"] = d("serve_entry", "serve_exit")
    iv["serve_exit_to_brake_pub"] = d("serve_exit", "brake_pub")
    iv["op_tick_phase_before_serve"] = d("op_prev_tick", "serve_entry")
    iv["detect_to_brake_pub"] = d("detect", "brake_pub")
    iv["take_to_brake_pub"] = d("take", "brake_pub")
    iv["brake_pub_to_stopped_state"] = d("brake_pub", "stopped_state")
    iv["take_to_stopped_state"] = d("take", "stopped_state")
    res = dict(run=run, trace=os.path.relpath(path, ROOT), qualifier=QUAL,
               times_ms={k: (ms(v) if v is not None else None) for k, v in T.items()},
               intervals_ms=iv, marker_order=order,
               thread_switches_call_to_serve=[r.get("name") or hex(r.get("thread_id", 0)) for r in sw],
               handler_tick_periods_ms=[round(x, 3) for x in h_periods],
               operator_tick_periods_ms=[round(x, 3) for x in op_periods],
               other_gaps_over_500ms=[(round(ms(a), 3), round(ms(b), 3) if b else None)
                                      for a, b in all_gaps if a != t_take],
               boot_call_mrm_ms=[round(ms(r['t_ns']), 3) for r in mk if r['name'] == CALLMRM and r['t_ns'] < 5e9][:3],
               header=tr.header)
    meta = path + ".meta"
    if os.path.exists(meta):
        res["meta"] = dict(l.strip().split("=", 1) for l in open(meta) if "=" in l)
    if events:
        res["host"] = host_side(read_events(events), T, mk)
    return res


def host_side(ev, T, mk):
    """Map the injector's wall-clock log into the trace's simulated time."""
    h = {}
    stop = [e for e in ev if e["ev"] == "sigstop"]
    if not stop:
        return dict(error="no sigstop in the events log")
    w_stop = stop[0]["wall"]
    ms_rx = [e for e in ev if e["ev"] == "mrm_state" and e["wall"] > w_stop]
    op_rx = next((e for e in ms_rx if e["state"] == MRM_OPERATING), None)
    succ_rx = next((e for e in ms_rx if e["state"] == MRM_SUCCEEDED), None)
    # anchor 1: the first MRM_OPERATING sample, host receipt vs island publish
    off1 = op_rx["wall"] - T["mrm_state"] / 1e9 if op_rx else None
    # anchor 2: the last availability sample before the fault, host receipt vs island take
    av = [e for e in ev if e["ev"] == "avail" and e["wall"] <= w_stop + 0.05]
    off2 = av[-1]["wall"] - T["take"] / 1e9 if av else None
    h["offset_anchor_mrm_state_s"] = off1
    h["offset_anchor_availability_s"] = off2
    h["alignment_disagreement_ms"] = (off1 - off2) * 1e3 if off1 is not None and off2 is not None else None
    off = off1 if off1 is not None else off2
    sim = lambda w: (w - off) * 1e3  # noqa: E731  wall -> simulated ms
    h["sigstop_sim_ms"] = sim(w_stop)
    h["sigstop_after_last_take_ms"] = sim(w_stop) - T["take"] / 1e6
    h["host_last_avail_before_stop_ms_before_stop"] = (w_stop - av[-1]["wall"]) * 1e3 if av else None
    avp = [e["wall"] for e in ev if e["ev"] == "avail" and w_stop - 5 < e["wall"] <= w_stop]
    h["availability_period_ms_host"] = (
        round((avp[-1] - avp[0]) * 1e3 / (len(avp) - 1), 2) if len(avp) > 1 else None)
    od = [e for e in ev if e["ev"] == "odom"]
    before = [e for e in od if e["wall"] <= w_stop]
    h["v_at_fault_mps"] = before[-1]["v"] if before else None
    after = [e for e in od if e["wall"] > w_stop]
    brake_w = off + T["brake_pub"] / 1e9
    # first odometry sample after the braking command that shows deceleration,
    # and the first at |v| < 0.001 (the handler's own stopped threshold)
    z = next((e for e in after if abs(e["v"]) < 0.001), None)
    h["odom_stamp_minus_recv_ms"] = (
        round(sum(e["stamp"] - e["wall"] for e in after[:50]) / max(len(after[:50]), 1) * 1e3, 1) if after else None)
    if z:
        h["v0_sim_ms_by_stamp"] = sim(z["stamp"])
        h["v0_sim_ms_by_receipt"] = sim(z["wall"])
        h["brake_pub_to_v0_ms"] = (z["stamp"] - brake_w) * 1e3
        h["take_to_v0_ms"] = sim(z["stamp"]) - T["take"] / 1e6
        h["sigstop_to_v0_ms"] = (z["stamp"] - w_stop) * 1e3
        h["v_at_brake_mps"] = next((e["v"] for e in reversed(od) if e["stamp"] <= brake_w), None)
    em = [e for e in ev if e["ev"] == "emerg_cmd" and e["wall"] >= brake_w - 0.01]
    h["first_emergency_cmd_rx"] = em[0] if em else None
    h["first_negative_acc_cmd_rx"] = next((e for e in em if e["acc"] < 0), None)
    h["mrm_succeeded_rx_sim_ms"] = sim(succ_rx["wall"]) if succ_rx else None
    return h


def fmt(v, nd=3):
    return "-" if v is None else f"{v:.{nd}f}"


def report(r):
    t, iv = r["times_ms"], r["intervals_ms"]
    print(f"run {r['run']}  trace {r['trace']}")
    print(f"  ({r['qualifier']})")
    print("  event (simulated ms since island boot)")
    for k in ("take", "fresh", "detect", "call", "mrm_state", "serve_entry", "serve_exit",
              "op_prev_tick", "op_brake_tick", "brake_pub", "stopped_state", "resume_take"):
        print(f"    {k:<16}{fmt(t[k]):>14}")
    print("  interval (simulated ms)")
    for k, v in iv.items():
        print(f"    {k:<32}{fmt(v):>12}")
    print(f"  order detect..brake: {' > '.join(r['marker_order'])}")
    print(f"  threads switched in between CALL and SERVE: {r['thread_switches_call_to_serve']}")
    print(f"  handler tick periods near the fault (ms): min {min(r['handler_tick_periods_ms'])} "
          f"max {max(r['handler_tick_periods_ms'])}")
    print(f"  operator tick periods near the fault (ms): min {min(r['operator_tick_periods_ms'])} "
          f"max {max(r['operator_tick_periods_ms'])}")
    print(f"  other availability gaps > 500 ms: {r['other_gaps_over_500ms']}")
    if "host" in r:
        for k, v in r["host"].items():
            print(f"  host {k}: {v}")


# rows of the declared-vs-observed table: (label, interval key or host key, declared, kind)
ROWS = [
    ("last take -> last fresh tick", "take_to_fresh_tick", None, "wait (tick phase)"),
    ("last take -> call_mrm tick", "take_to_detect", "500 + tick<=100", "wait (staleness + tick phase)"),
    ("  of which past the 500 ms bound", "stale_to_detect_tick", "<=100 (tick in the 110)", "wait (tick phase)"),
    ("call_mrm entry -> CALL", "detect_to_call", "(inside the 110)", "zero-time artefact"),
    ("CALL -> operate callback entry", "call_to_serve_entry", "10 (timeout_call_mrm_behavior)", "wait (executor turn)"),
    ("operate callback entry -> exit", "serve_entry_to_exit", "-", "zero-time artefact"),
    ("operate exit -> first braking PUB", "serve_exit_to_brake_pub", "33.33 (sampling)", "wait (30 Hz tick phase)"),
    ("call_mrm tick -> first braking PUB", "detect_to_brake_pub", "110 + 33.33 = 143.33", "wait"),
    ("last take -> first braking PUB", "take_to_brake_pub", "500 + 143.33 = 643.33", "wait"),
    ("first braking PUB -> v < 0.001 (odom stamp)", "host:brake_pub_to_v0_ms", "2034 (settle, at 3.0 m/s)", "plant (host wall clock)"),
    ("first braking PUB -> MRM_SUCCEEDED pub", "brake_pub_to_stopped_state", "2034 + odom + tick", "plant + wait"),
    ("last take -> v < 0.001 (odom stamp)", "host:take_to_v0_ms", "2677.33 (FTTI 3000)", "whole budget"),
]


def summary(files, csv_path=None):
    rs = [json.load(open(f)) for f in files]
    rs.sort(key=lambda r: str(r["run"]))
    def val(r, key):
        if key.startswith("host:"):
            return (r.get("host") or {}).get(key[5:])
        return r["intervals_ms"].get(key)
    hdr = ["interval", "declared_ms", "kind"] + [f"run {r['run']}" for r in rs] + ["max"]
    rows = []
    for label, key, decl, kind in ROWS:
        vals = [val(r, key) for r in rs]
        good = [v for v in vals if v is not None]
        rows.append([label, decl or "-", kind] + [fmt(v, 2) for v in vals] + [fmt(max(good), 2) if good else "-"])
    extra = [("v at fault (m/s)", "host:v_at_fault_mps"), ("SIGSTOP after last take (ms)", "host:sigstop_after_last_take_ms"),
             ("alignment disagreement (ms)", "host:alignment_disagreement_ms")]
    for label, key in extra:
        vals = [val(r, key) for r in rs]
        rows.append([label, "-", "context"] + [fmt(v, 2) for v in vals] + ["-"])
    w = [max(len(str(x[i])) for x in rows + [hdr]) for i in range(len(hdr))]
    print("All values in native_sim SIMULATED ms (plant rows: host wall clock mapped onto it).")
    print("Zero-time artefact = inside one callback; native_sim runs code in zero simulated time.")
    for row in [hdr] + rows:
        print("  ".join(str(x).ljust(w[i]) for i, x in enumerate(row)))
    if csv_path:
        with open(csv_path, "w", newline="") as f:
            cw = csv.writer(f)
            cw.writerow(hdr)
            cw.writerows(rows)
        print(f"csv: {csv_path}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        ap = argparse.ArgumentParser()
        ap.add_argument("cmd")
        ap.add_argument("files", nargs="+")
        ap.add_argument("--csv")
        a = ap.parse_args()
        summary(a.files, a.csv)
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace")
    ap.add_argument("--events")
    ap.add_argument("--run")
    ap.add_argument("--json")
    a = ap.parse_args()
    r = extract(a.trace, a.events, a.run or os.path.basename(a.trace))
    report(r)
    if a.json:
        json.dump(r, open(a.json, "w"), indent=1)
        print(f"json: {a.json}")


if __name__ == "__main__":
    main()
