#!/usr/bin/env python3
"""Island trace markers onto the host's CLOCK_MONOTONIC (phase8-W7).

  merge.py <trace> <run_dir> [--zephyr 4.4] [--out <run_dir>/island.jsonl]

The trace is the native_sim dump (`just trace-native`, `ISLTRC01` header), or
the board's or QEMU's `ram_tracing` as tools/timeline/readout.py wraps it (the
same header; a bare read needs `--zephyr 4.4`). Its stamps
are the island's own clock (native_sim: simulated ns since boot; the board:
cycle-counter time), so they are never subtracted from host stamps. As in
phase7-W3 (docs/reaction-trace.md), the two clocks are aligned on events both
sides saw, and the disagreement between two anchors is the error bar:

  anchor 1  the island's first publish of the reaction state, against the
            host probe's receipt of that sample: the takeover-request state
            going OPERATING (the ODD exit), or mrm_state going MRM_OPERATING
            (the HPC loss);
  anchor 2  an availability sample both received from the gate: the first
            one with autonomous=false (the ODD exit), or the last one before
            the gate was stopped (the HPC loss).

When the island holds more than one onset (a flap of the availability
before or after the act), the one taken is the one whose offset explains
the most publish/receipt pairs (best_onset, phase8-W17), and anchor 2 is the
sample that raised it.

Anchor 1 gives a coarse offset (host receipt - island stamp). It is then
refined on every island publish the probe also received -- each change of
the takeover-request state and of mrm_state, and the velocity limit --
paired within 250 ms: a receipt is never earlier than its publish, so every
pair bounds the offset from above, and the smallest (the least-delayed
sample) is the one used. The spread of the pairs is the transport and probe
latency, and anchor 2 (which arrives at both sides from the gate) is the
independent check. Each marker is written as an `island` `marker` event at
island stamp + offset; the `align` event records all of it.
Markers from 5 s before the first injection to the end of the trace are
written; heartbeats and thread switches are not.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tlcommon as tl  # noqa: E402

sys.path.insert(0, os.path.join(tl.ROOT, "src/safety_island_tracing"))
import island_trace  # noqa: E402

MRM_OPERATING, OPERATING = 2, 2
TOR = "PUB_MRM_HANDLER_TAKEOVER_REQUEST_STATE"
MRM = "PUB_MRM_HANDLER_MRM_STATE"
TAKE_AV = "TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY"


def onsets(mk, name, pred):
    """Island stamps where `pred(arg)` becomes true for marker `name`."""
    out, prev = [], False
    for r in mk:
        if r["name"] != name:
            continue
        cur = bool(pred(r["arg"]))
        if cur and not prev:
            out.append(r["t_ns"])
        prev = cur
    return out


def best_onset(mk, ev, cands, host):
    """Of several island onsets, the one that, taken as the host receipt's
    publish, explains the most other publish/receipt pairs (phase8-W17).

    A run can hold more than one onset: the availability flaps to
    autonomous=false for one sample before or after the act (run w17-nb2: two
    before the button, seven after), each flap raising the takeover request for
    one tick, and a trace from boot holds the boot-time MRM. The last onset,
    which this used to take, was a flap in w17-nb2 and put the offset 34 s
    off; the longest-held one is the boot MRM in w8a-e. The right offset is the
    one under which the island's changes line up with what the probe received,
    so each candidate is scored by refine()'s pair count; ties go to the last
    one, the old choice."""
    best = None
    for c in cands:
        n = len(refine(mk, ev, host - c))
        if best is None or n >= best[1]:
            best = (c, n)
    return best[0] if best else None


def host_first(ev, marker, pred, after=None):
    for e in ev:
        if e["source"] == "probe" and e.get("marker") == marker and pred(e["value"]):
            if after is None or e["t_mono_ns"] >= after:
                return e["t_mono_ns"]
    return None


def align(mk, ev):
    injects = [e for e in ev if e["source"] == "scenario" and e["kind"] == "inject"]
    kinds = {e["marker"] for e in injects}
    first_inject = min((e["t_mono_ns"] for e in injects), default=None)
    res = dict(anchor1=None, anchor2=None)
    if "odd_exit" in kinds:
        t_inj = next(e["t_mono_ns"] for e in injects if e["marker"] == "odd_exit")
        host = host_first(ev, "takeover_request_state", lambda v: v == "OPERATING", after=t_inj)
        isl = best_onset(mk, ev, onsets(mk, TOR, lambda a: a == OPERATING), host) if host else None
        if isl is not None and host:
            res["anchor1"] = dict(what="takeover_request_state OPERATING", island_ns=isl, host_ns=host)
        isl2 = onsets(mk, TAKE_AV, lambda a: a == 0)
        # the sample that raised the request anchor 1 is on: the last onset
        # at or before it (the last onset overall can be a later flap)
        if isl is not None:
            isl2 = [t for t in isl2 if t <= isl]
        host2 = host_first(ev, "availability", lambda v: v["autonomous"] is False, after=t_inj)
        if isl2 and host2:
            res["anchor2"] = dict(what="first availability sample with autonomous=false",
                                  island_ns=isl2[-1], host_ns=host2)
    if "hpc_loss" in kinds:
        t_inj = next(e["t_mono_ns"] for e in injects if e["marker"] == "hpc_loss")
        host = host_first(ev, "mrm_state", lambda v: v["state"] == "MRM_OPERATING", after=t_inj)
        isl = best_onset(mk, ev, onsets(mk, MRM, lambda a: (a >> 16) == MRM_OPERATING), host) if host else None
        if isl is not None and host:
            res["anchor1"] = dict(what="mrm_state MRM_OPERATING", island_ns=isl, host_ns=host)
        takes = [r["t_ns"] for r in mk if r["name"] == TAKE_AV]
        gaps = [(a, b) for a, b in zip(takes, takes[1:]) if b - a > 500e6]
        host_av = [e["t_mono_ns"] for e in ev if e["source"] == "probe" and e.get("marker") == "availability"
                   and e["t_mono_ns"] <= t_inj]
        if gaps and host_av:
            a, _ = max(gaps, key=lambda g: g[1] - g[0])
            res["anchor2"] = dict(what="last availability sample before the gate stopped",
                                  island_ns=a, host_ns=host_av[-1])
    for k in ("anchor1", "anchor2"):
        if res[k]:
            res[k]["offset_ns"] = res[k]["host_ns"] - res[k]["island_ns"]
    a1, a2 = res["anchor1"], res["anchor2"]
    if not a1 and not a2:
        return None, res, first_inject
    off = (a1 or a2)["offset_ns"]
    res["used"] = "anchor1" if a1 else "anchor2"
    res["disagreement_ms"] = (a1["offset_ns"] - a2["offset_ns"]) / 1e6 if a1 and a2 else None
    return off, res, first_inject


def changes(mk, name, fmt):
    out, prev = [], None
    for r in mk:
        if r["name"] != name:
            continue
        if r["arg"] != prev:
            out.append((r["t_ns"], fmt(r["arg"])))
            prev = r["arg"]
    return out


def refine(mk, ev, coarse):
    isl = changes(mk, TOR, lambda a: tl.BEHAVIOR_STATUS.get(a))
    isl += [(t, ("mrm", v)) for t, v in changes(mk, MRM, lambda a: (tl.MRM_STATE.get(a >> 16),
                                                                      tl.MRM_BEHAVIOR.get(a & 0xFFFF)))]
    isl += [(r["t_ns"], "limit") for r in mk if r["name"] == "PUB_MRM_COMFORTABLE_STOP_OPERATOR_MAX_VELOCITY_CANDIDATES"]
    host = []
    for e in ev:
        if e["source"] != "probe":
            continue
        if e.get("marker") == "takeover_request_state":
            host.append((e["t_mono_ns"], e["value"]))
        elif e.get("marker") == "mrm_state":
            host.append((e["t_mono_ns"], ("mrm", (e["value"]["state"], e["value"]["behavior"]))))
        elif e.get("marker") == "velocity_limit":
            host.append((e["t_mono_ns"], "limit"))
    pairs = []
    for ti, v in isl:
        guess = ti + coarse
        cand = [th for th, hv in host if hv == v and guess - 50_000_000 <= th <= guess + 250_000_000]
        if cand:
            pairs.append(min(cand) - ti)
    return pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace")
    ap.add_argument("run_dir")
    ap.add_argument("--zephyr", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = a.out or os.path.join(a.run_dir, "island.jsonl")
    tr = island_trace.load(a.trace, zephyr=a.zephyr)
    if tr.error:
        sys.exit(f"merge: decode error: {tr.error}")
    mk = [r for r in tr.records if r["kind"] == "marker"]
    ev = tl.read_events([p for p in tl.run_files(a.run_dir) if os.path.abspath(p) != os.path.abspath(out)])
    off, res, first_inject = align(mk, ev)
    if off is None:
        sys.exit(f"merge: no anchor found (injections: "
                 f"{[e['marker'] for e in ev if e['kind'] == 'inject']}); cannot align {a.trace}")
    pairs = sorted(refine(mk, ev, off))
    if pairs:
        off = pairs[0]
        res["used"] = f"min over {len(pairs)} publish/receipt pairs"
        res["pairs_spread_ms"] = (pairs[-1] - pairs[0]) / 1e6
        res["pairs_median_minus_min_ms"] = (pairs[len(pairs) // 2] - pairs[0]) / 1e6
        res["n_pairs"] = len(pairs)
        if res.get("anchor2"):
            res["disagreement_ms"] = (off - res["anchor2"]["offset_ns"]) / 1e6
    res["offset_ns"] = off
    if os.path.exists(out):
        os.remove(out)
    w = tl.Writer(out)
    w.write("island", "align", t_mono_ns=(first_inject or 0), value=res,
            clock=("native_sim simulated ns since boot" if tr.zephyr.startswith("3.")
                   else f"island cycle counter (zephyr {tr.zephyr})"),
            trace=os.path.relpath(a.trace, tl.ROOT))
    lo = (first_inject or 0) - 5_000_000_000
    n = 0
    for r in mk:
        t = r["t_ns"] + off
        if t < lo:
            continue
        w.write("island", "marker", t_mono_ns=t, marker=r["name"], value=r["arg"], island_ns=r["t_ns"])
        n += 1
    w.close()
    print(f"merge: offset from {res.get('used')}, pair spread {res.get('pairs_spread_ms')} ms; "
          f"{n} markers -> {out}; anchor 1 {res['anchor1'] and res['anchor1']['what']}, "
          f"anchor 2 {res['anchor2'] and res['anchor2']['what']}, "
          f"disagreement {res['disagreement_ms'] if res['disagreement_ms'] is None else round(res['disagreement_ms'], 3)} ms")


if __name__ == "__main__":
    main()
