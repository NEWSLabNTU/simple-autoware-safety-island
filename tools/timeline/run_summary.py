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
    return f"trace-check {m.group(1) if m else '-'}"


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
    print(f"SUMMARY {run}{act}: {verdict(d)}; {load(meta)}; {table(d)}; {trace_check(d)}; {stored(d)}; "
          f"{serial(d)}; {heap(d)}{asserted(d)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
