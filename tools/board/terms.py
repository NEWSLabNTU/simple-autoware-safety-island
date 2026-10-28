#!/usr/bin/env python3
"""The board budget terms, measured from a round of board runs (phase8-W30),
and the budgets the contract's rule gives for them (phase10-B4).

  terms.py <timeline_dir> [run ...] [--prefix w8-] [--propose [--period 100]]

Reads each run's island.jsonl (merged island markers; `island_ns` is the
island's own clock), gate.jsonl and scenario.jsonl. Prints, per run and over
all runs, the terms the contract's mrm_handler paths are sized from:

  link      gate publish (host clock) -> island take of the same edge
            (island marker on the host clock, merge.py's min-pair offset).
            CROSS-CLOCK: see the note printed at the end.
  spacing   consecutive handler ticks, island clock: the `call_mrm` ENTRY of
            one tick to the next (recorded on every faulted tick)
  work      handler tick start (`call_mrm` ENTRY) -> the path's last
            publish in that tick (`call_mrm` EXIT, after the mrm_state and
            takeover-request publishes), island clock; the TOR-on, call and
            TOR-off offsets are printed on their own
  limit     handler tick start on the expiry tick -> the comfortable-stop
            operator's velocity-limit publish, island clock: the reaction's
            last publish, served after the handler's tick returns
  operate   the handler's `call_mrm` EXIT on the expiry tick -> that
            velocity-limit publish, island clock
  exit      the handler's take of MANUAL -> the TOR-off publish, island clock
  wait      island take of the fault edge -> the next `call_mrm` ENTRY

Runs: the named ones, else every directory under <timeline_dir> whose name
starts with --prefix (default: every directory with an island.jsonl).

--propose prints, per budget, the value the contract's measurement rule
gives (rtss-work-2026-demo:docs/takeover-trace.md section 10): the observed maximum plus 20 %,
rounded up to the next ms. A timer's period takes no margin: the tick is
the period (--period, ms; 100 = mrm_handler update_rate 10) plus the
largest lateness (spacing - period) x 1.2, rounded up. So

  max_transport (link)  ceil(max link x 1.2)
  tick                  period + ceil((max spacing - period) x 1.2)
  work                  ceil(max(work, limit) x 1.2)  (the reaction's last
                        publish, the velocity limit on the expiry tick when
                        the round has one)
  call_mrm, driver_exit tick + work (the link is charged on the guard edge,
                        not inside the path)
"""
import argparse
import json
import math
import os

TICK = "PATH_MRM_HANDLER_CALL_MRM_ENTRY"
TICK_X = "PATH_MRM_HANDLER_CALL_MRM_EXIT"
TAKE = "TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY"
TOR = "PUB_MRM_HANDLER_TAKEOVER_REQUEST_STATE"
CALL_CS = "CALL_MRM_HANDLER_COMFORTABLE_STOP_OPERATE"
LIMIT = "PUB_MRM_COMFORTABLE_STOP_OPERATOR_MAX_VELOCITY_CANDIDATES"
TAKE_CM = "TAKE_MRM_HANDLER_CONTROL_MODE"
KEYS = ("link", "wait", "spacing", "work", "limit", "tor_on", "call", "tor_off", "operate", "exit")
MARGIN = 1.2


def load(p):
    return [json.loads(ln) for ln in open(p)] if os.path.exists(p) else []


def run_terms(d):
    isl = load(os.path.join(d, "island.jsonl"))
    gate = load(os.path.join(d, "gate.jsonl"))
    scen = load(os.path.join(d, "scenario.jsonl"))
    mk = [e for e in isl if e["kind"] == "marker"]
    act = next((e["marker"] for e in scen if e["kind"] == "verdict"), None)
    out = dict(act=act, **{k: [] for k in KEYS})
    ms = lambda a, b: (b - a) / 1e6  # noqa: E731
    # ticks on the island clock
    ticks = [e for e in mk if e["marker"] == TICK]
    for a, b in zip(ticks, ticks[1:]):
        s = ms(a["island_ns"], b["island_ns"])
        if s < 150:  # consecutive faulted ticks only
            out["spacing"].append(s)
    exits = [e for e in mk if e["marker"] == TICK_X]
    for t in ticks:
        x = next((e for e in exits if e["island_ns"] >= t["island_ns"]), None)
        if x and ms(t["island_ns"], x["island_ns"]) < 100:
            out["work"].append(ms(t["island_ns"], x["island_ns"]))

    def tick_before(ns):
        c = [t for t in ticks if t["island_ns"] <= ns]
        return c[-1] if c else None
    tors = [e for e in mk if e["marker"] == TOR]
    for e in tors:
        t = tick_before(e["island_ns"])
        if t and ms(t["island_ns"], e["island_ns"]) < 100:
            out["tor_on" if e["value"] == 2 else "tor_off"].append(ms(t["island_ns"], e["island_ns"]))
    for e in (e for e in mk if e["marker"] == CALL_CS and e["value"] == 1):
        t = tick_before(e["island_ns"])
        if t:
            out["call"].append(ms(t["island_ns"], e["island_ns"]))
        x = next((x for x in exits if x["island_ns"] >= e["island_ns"]), None)
        lim = next((m for m in mk if m["marker"] == LIMIT and m["island_ns"] >= e["island_ns"]), None)
        if x and lim:
            out["operate"].append(ms(x["island_ns"], lim["island_ns"]))
        if t and lim:
            out["limit"].append(ms(t["island_ns"], lim["island_ns"]))
    for e in (e for e in mk if e["marker"] == TAKE_CM and e["value"] == 4):
        off = next((t for t in tors if t["island_ns"] >= e["island_ns"] and t["value"] != 2), None)
        if off:
            out["exit"].append(ms(e["island_ns"], off["island_ns"]))
    # the link, on each edge of the gate's verdict both sides saw
    pubs = [e for e in gate if e["kind"] == "publish"]
    takes = [e for e in mk if e["marker"] == TAKE]
    for p in pubs:
        want = 1 if p["value"]["autonomous"] else 0
        prev = None
        for e in takes:
            if e["t_mono_ns"] >= p["t_mono_ns"] - 50_000_000 and e["value"] == want and \
                    (prev is None or prev["value"] != want):
                if e["t_mono_ns"] - p["t_mono_ns"] < 500_000_000:
                    out["link"].append(ms(p["t_mono_ns"], e["t_mono_ns"]))
                    nt = next((t for t in ticks if t["island_ns"] > e["island_ns"]), None)
                    if want == 0 and nt:
                        out["wait"].append(ms(e["island_ns"], nt["island_ns"]))
                break
            prev = e
    return out


def rng(v):
    return "-" if not v else f"{min(v):.2f}-{max(v):.2f} (n={len(v)})"


def up(x):
    """Rounded up to the next ms (a float product such as 25.0 x 1.2 is not
    pushed past its integer by representation error)."""
    return int(math.ceil(round(x, 6)))


def propose(allv, period):
    """[(budget, value or None, how)] by the measurement rule (module doc)."""
    rows = []
    if allv["link"]:
        m = max(allv["link"])
        rows.append(("max_transport (link)", up(m * MARGIN), f"max {m:.2f} x {MARGIN} = {m * MARGIN:.2f}"))
    else:
        rows.append(("max_transport (link)", None, "no link edges"))
    tick = work = None
    if allv["spacing"]:
        m = max(allv["spacing"])
        late = max(0.0, m - period)
        tick = period + up(late * MARGIN)
        rows.append(("tick", tick, f"period {period:g} + lateness {late:.2f} x {MARGIN} = {late * MARGIN:.2f}"
                                   f" (max spacing {m:.2f}; the period takes no margin)"))
    else:
        rows.append(("tick", None, "no consecutive ticks"))
    wv = allv["work"] + allv["limit"]
    if wv:
        m = max(wv)
        src = "limit (tick -> velocity limit)" if allv["limit"] and m == max(allv["limit"]) else "work (tick -> call_mrm exit)"
        work = up(m * MARGIN)
        rows.append(("work", work, f"max {m:.2f} from {src} x {MARGIN} = {m * MARGIN:.2f}"))
    else:
        rows.append(("work", None, "no handler ticks"))
    s = tick + work if tick is not None and work is not None else None
    rows.append(("call_mrm = tick + work", s, f"{tick} + {work}"))
    rows.append(("driver_exit = tick + work", s, f"{tick} + {work}"
                 + (f"; exit observed {rng(allv['exit'])}" if allv["exit"] else "")))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("runs", nargs="*")
    ap.add_argument("--prefix", default="", help="runs: directories starting with this (default: all)")
    ap.add_argument("--propose", action="store_true", help="print the budgets the measurement rule gives")
    ap.add_argument("--period", type=int, default=100, help="the handler timer's period, ms (100)")
    a = ap.parse_args()
    runs = a.runs or sorted(x for x in os.listdir(a.root) if x.startswith(a.prefix)
                            and os.path.exists(os.path.join(a.root, x, "island.jsonl")))
    allv = {k: [] for k in KEYS}
    print("run     act     " + "  ".join(f"{k:>24}" for k in KEYS))
    for r in runs:
        t = run_terms(os.path.join(a.root, r))
        for k in KEYS:
            allv[k].extend(t[k])
        print(f"{r:7} {str(t['act']):7} " + "  ".join(f"{rng(t[k]):>24}" for k in KEYS))
    print("ALL             " + "  ".join(f"{rng(allv[k]):>24}" for k in KEYS))
    print("max: " + ", ".join(f"{k} {max(allv[k]):.2f}" for k in KEYS if allv[k]))
    print("note: `link` compares the gate's host stamp with an island stamp moved onto the host clock by the")
    print("smallest publish->receipt pair (merge.py). A receipt is never before its publish, so that offset")
    print("places island events no EARLIER than they happened: `link` is over-stated by the smallest out-link")
    print("delay, never under-stated. Every other term is on one clock (island).")
    if a.propose:
        print(f"\nproposed budgets (max x {MARGIN}, rounded up to the next ms; the timer period takes no margin),"
              f" over {len(runs)} run(s):")
        for name, v, how in propose(allv, a.period):
            print(f"  {name:28} {('-' if v is None else f'{v} ms'):>8}   {how}")


if __name__ == "__main__":
    main()
