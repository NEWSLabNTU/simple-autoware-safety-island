#!/usr/bin/env python3
"""One line per board run, from the files the run wrote (phase9-U1).

  run_summary.py <run dir>

run-board.sh prints it last and keeps it as <run dir>/summary.txt:

  SUMMARY d12-e1 encore: PASS; load 21.85 at act; table 9/9 PASS, total 3472.95 of 4934.67 ms;
  trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0
  (overruns/bad frames); heap peak 66640 of 107008 B

Each field reads one file and says "-" when the file is not there (a QEMU
run has no serial.txt, an older run no bootrec.txt), so a missing input
never reads as a clean one. A run whose readout found a failing assert
(assert.txt, phase9-C4) ends the line with `; ASSERT <file>:<line>`.

phase9-C6 / U5: `load <1-min> at act` is island.trace.meta's loadavg_act
(the load the act ran under). A run refused before its act (refused.txt)
prints `REFUSED <reason>` and nothing else; a run whose probe or gate did
not run (void.txt) reads `VOID (<reason>)` in place of the verdict.

phase9-W2: an act whose trace window was re-armed on the same boot reads
`trace-check PASS (window <n> of the boot)`. Its `stored` count is the
boot's: nano-ros's violation record is never drained, so it includes the
verdicts of the acts before it on that boot.

CARLA demo C3 (run-board.sh --sim carla, island.trace.meta `sim=carla`): the
line gains `; sim carla, RTF <r>, SSv2 junit <PASS|FAIL|->` (the act's `rtf`
event in scenario.jsonl; <dir>/result.junit.xml), and an act whose RTF is
below RB_RTF_MIN (env, 0.95) or unknown reads `INVALID (RTF <r> < 0.95)` in
place of PASS/FAIL: its wall-time and sim-time terms are not comparable
(docs/design/carla-island-demo.md 4.2). A PASS whose SSv2 junit is not PASS
reads FAIL: the act passes only when the island's verdict and the world's
agree (design 2.3).

CARLA demo C4 (the scenario's trigger, scenario.py SCENARIO_TRIGGER=scenario):
the suffix adds `trigger <what>`: `ODD EXIT <odd_monitor's reason>, odd_monitor
-> gate <ms>` for a and b, `hpc-loss at (<x>, <y>)` for the encore (the
`trigger` event), or `button` when the act pressed it itself; and `vlimit
<a> m/s asked, <s> selected`: the external velocity limit SSv2 set through
/api/autoware/set/velocity_limit (max_velocity_default) and what Autoware's
selector made of it with its own max_vel (max_velocity), as the act read
them (the `velocity_limit` event).
"""
import json
import os
import re
import sys
from collections import Counter


def read(d, name):
    p = os.path.join(d, name)
    return open(p, errors="replace").read() if os.path.exists(p) else None


def verdict(d):
    v = read(d, "void.txt")
    if v is not None:
        return f"VOID ({v.strip()})"
    t = read(d, "scenario.jsonl")
    if t is None:
        return "-"
    for line in t.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("kind") == "verdict":
            return "PASS" if e["value"]["ok"] else "FAIL"
    return "no verdict"


def events(d, kind):
    t = read(d, "scenario.jsonl") or ""
    out = []
    for line in t.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("kind") == kind:
            out.append(e)
    return out


def rtf(d):
    e = events(d, "rtf")
    return e[-1]["value"].get("rtf") if e else None


def junit(d):
    t = read(d, "result.junit.xml")
    if t is None:
        return "-"
    m = re.search(r"<testsuites[^>]*failures=\"(\d+)\"[^>]*errors=\"(\d+)\"[^>]*tests=\"(\d+)\"", t)
    if not m:
        return "?"
    f, e, n = (int(x) for x in m.groups())
    return "PASS" if f == 0 and e == 0 and n > 0 else f"FAIL ({f} failures, {e} errors)"


def sim(d, meta, v):
    """CARLA runs: (verdict, the suffix)."""
    m = re.search(r"^sim=(\S+)", meta or "", re.M)
    if not m or m.group(1) != "carla":
        return v, ""
    r = rtf(d)
    rmin = float(os.environ.get("RB_RTF_MIN", "0.95"))
    j = junit(d)
    if v == "PASS" and j != "PASS":  # design 2.3: an act passes only when both verdicts agree
        v = f"FAIL (the island's verdict PASS, SSv2 junit {j})"
    if v in ("PASS", "FAIL") and (r is None or r < rmin):
        v = f"INVALID (RTF {'-' if r is None else f'{r:.3f}'} < {rmin}; the scenario said {v})"
    return v, f"; sim carla, RTF {'-' if r is None else f'{r:.3f}'}, SSv2 junit {j}{trigger(d)}"


def trigger(d):
    """C4: what started the act, and the velocity limit Autoware ran under."""
    t = events(d, "trigger")
    if not t:
        s = ", trigger button"
    else:
        v = t[-1]["value"]
        if v.get("how") == "odd_monitor":
            hop = v.get("odd_to_gate_ms")
            s = f", trigger ODD EXIT {v.get('reason')}, odd_monitor -> gate {'-' if hop is None else hop} ms"
        else:
            x, y = v.get("x"), v.get("y")
            s = f", trigger {v.get('cmd')} at " + ("-" if x is None else f"({x:.1f}, {y:.1f})")
    vl = events(d, "velocity_limit")
    if vl:
        v = vl[-1]["value"]
        api = (v.get("/planning/scenario_planning/max_velocity_default") or {}).get("max_velocity")
        sel = (v.get("/planning/scenario_planning/max_velocity") or {}).get("max_velocity")
        f = lambda x: "-" if x is None else f"{x:.2f}"  # noqa: E731
        s += f", vlimit {f(api)} m/s asked, {f(sel)} selected"
    return s


def table(d):
    t = read(d, "table.md")
    if t is None:
        return "table -"
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in t.splitlines()
            if l.startswith("| ") and not l.startswith("| term")]
    ok = sum(1 for r in rows if len(r) > 3 and r[3] == "PASS")
    total = next((r for r in rows if r[0].startswith("total")), None)
    s = f"table {ok}/{len(rows)} PASS"
    if total:
        s += f", total {total[2]} of {total[1]} ms"
    return s


def trace_check(d):
    t = read(d, "island.trace.check.txt")
    m = re.search(r"trace-check: (\w+)", t or "")
    return f"trace-check {m.group(1) if m else '-'}{window(d)}"


def window(d):
    """phase9-W2: a re-armed window (an act on the same boot as the one
    before it) says which window of the boot the trace is."""
    t = read(d, "island.trace.readout.json")
    try:
        n = json.loads(t)["values"].get("island_trace_rearms", 0) if t else 0
    except (ValueError, KeyError):
        return ""
    return f" (window {n + 1} of the boot)" if n else ""


def stored(d):
    t = read(d, "violations.txt")
    if t is None:
        return "stored -"
    m = re.search(r"total=(\d+)", t)
    rules = Counter(re.findall(r"#\d+: (\S+) ", t))
    detail = ", ".join(f"{r} x{n}" for r, n in sorted(rules.items()))
    return f"stored {m.group(1) if m else '?'}" + (f" ({detail})" if detail else "")


def serial(d):
    t = read(d, "serial.txt")
    if t is None:
        return "serial -"
    m = re.search(r"in the act: overruns=(\w+) bad_frames=(\w+)", t)
    if m:
        return f"serial in act {m.group(1)}/{m.group(2)} (overruns/bad frames)"
    m = re.search(r"since boot: overruns=(\d+) bad_frames=(\d+)", t)
    return f"serial since boot {m.group(1)}/{m.group(2)} (no act-start snapshot)" if m else "serial ?"


def heap(d):
    t = read(d, "bootrec.txt")
    m = re.search(r"peak (\d+) of (\d+)", t or "")
    return f"heap peak {m.group(1)} of {m.group(2)} B" if m else "heap -"


def load(meta):
    m = re.search(r"^loadavg_act=(\S+)", meta or "", re.M)
    return f"load {m.group(1)} at act" if m else "load -"


def asserted(d):
    """phase9-C4: only when readout.py found a failing assert (assert.txt)."""
    t = read(d, "assert.txt")
    m = re.match(r"ASSERT (\S+)", t or "")
    return f"; ASSERT {m.group(1)}" if m else ""


def main():
    d = sys.argv[1].rstrip("/")
    run = os.path.basename(d)
    act = ""
    meta = read(d, "island.trace.meta")
    if meta:
        m = re.search(r"^act=(\S+)", meta, re.M)
        act = f" {m.group(1)}" if m else ""
    refused = read(d, "refused.txt")
    if refused is not None:
        print(f"SUMMARY {run}{act}: REFUSED {refused.strip()}")
        return 0
    v, carla = sim(d, meta, verdict(d))
    print(f"SUMMARY {run}{act}: {v}; {load(meta)}; {table(d)}; {trace_check(d)}; {stored(d)}; "
          f"{serial(d)}; {heap(d)}{asserted(d)}{carla}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
