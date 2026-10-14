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

CARLA demo C5 trace margin: the trace-check field adds `trace <used> of
<buffer> B over <s> s` (the window after its trigger, from the check) and
where scenario.py re-armed it: `re-armed <s> s before the ODD exit (go ->
ack <ms> ms)` (a, b) or `re-armed when the ego drove` (the encore).

CARLA demo C4 (the scenario's trigger, scenario.py SCENARIO_TRIGGER=scenario):
the suffix adds `trigger <what>`: `ODD EXIT <odd_monitor's reason>, odd_monitor
-> gate <ms>` for a and b, `hpc-loss at (<x>, <y>)` for the encore (the
`trigger` event), `board SW1|SW2 (...)` under RB_TRIGGER=board (C6: the
board's button, injected or pressed, the island's uptime of the press, and
the host's latencies), `button` when the act pressed it itself (RB_TRIGGER=button,
or a run from before C4), `none (the scenario's fault never fired)` when the
scenario was to trigger it and nothing came, or `ODD EXIT (...) fired, but the
act recorded no trigger` when odd_monitor fired and the act missed it; and `vlimit
<a> m/s asked, <s> selected`: the external velocity limit SSv2 set through
/api/autoware/set/velocity_limit (max_velocity_default) and what Autoware's
selector made of it with its own max_vel (max_velocity), as the act read
them (the `velocity_limit` event).

phase10-B9: the verdict is the act's and the table's together. The
scenario's verdict (the safe state reached, scenario.py) alone read PASS
while settle and total were over budget (b6-e2: table 6/8). A table row
that FAILs now turns PASS into `FAIL (the act PASS; <n> table row(s) FAIL:
<terms>; within the FTTI PASS)` (budget()). Exit codes are unchanged:
run-board.sh exits with the scenario's code (0 the act passed, 1 it
failed), 3 refused, 4 void; the budget verdict is in this line only.
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
    return v, f"; sim carla, RTF {'-' if r is None else f'{r:.3f}'}, SSv2 junit {j}{trigger(d, meta)}"


def trigger(d, meta=""):
    """C4: what started the act, and the velocity limit Autoware ran under.

    The mode is island.trace.meta's `trigger=` (run-board.sh RB_TRIGGER);
    a run from before C4 has none and pressed the button. Under `scenario`
    with no `trigger` event the fault was not recorded: odd_monitor's log
    says whether the ODD exit fired at all."""
    m = re.search(r"^trigger=(\S+)", meta or "", re.M)
    mode = m.group(1) if m else "button"
    t = events(d, "trigger")
    if not t and mode == "button":
        s = ", trigger button"
    elif not t:
        o = read(d, "odd_monitor.log") or ""
        x = re.search(r"ODD EXIT \((.*)\) wall=", o)
        waited = "the scenario's trigger" in (read(d, "act.log") or "")
        s = (f", trigger ODD EXIT ({x.group(1)}) fired, but the act recorded no trigger (act.log)" if x
             else ", trigger none (the scenario's fault never fired)" if waited
             else ", trigger none (the act ended before it waited for the scenario's fault; act.log)")
    else:
        v = t[-1]["value"]
        if v.get("how") == "odd_monitor":
            hop = v.get("odd_to_gate_ms")
            s = f", trigger ODD EXIT {v.get('reason')}, odd_monitor -> gate {'-' if hop is None else hop} ms"
        elif v.get("how") == "board":
            x, y = v.get("x"), v.get("y")
            s = f", trigger board {button_text(v)} at " + ("-" if x is None else f"({x:.1f}, {y:.1f})")
        else:
            x, y = v.get("x"), v.get("y")
            s = f", trigger {v.get('cmd')} at " + ("-" if x is None else f"({x:.1f}, {y:.1f})")
    if mode == "board":
        # C6: act a's SW1 (the driver's takeover; its trigger is the ODD exit above)
        bt = events(d, "button")
        if bt:
            s = f", trigger board {button_text(bt[-1]['value'])}" + (f" after{s[len(', trigger'):]}" if t else "")
        elif t and t[-1]["value"].get("how") != "board":
            s = ", trigger board SW1 none (no accepted press recorded)" + s
    vl = events(d, "velocity_limit")
    if vl:
        v = vl[-1]["value"]
        api = (v.get("/planning/scenario_planning/max_velocity_default") or {}).get("max_velocity")
        sel = (v.get("/planning/scenario_planning/max_velocity") or {}).get("max_velocity")
        f = lambda x: "-" if x is None else f"{x:.2f}"  # noqa: E731
        s += f", vlimit {f(api)} m/s asked, {f(sel)} selected"
    return s


def button_text(v):
    """C6: one board press, as scenario.py's `button`/`trigger` event has it."""
    if v.get("t_seen_ns") is None:
        return f"{v.get('button')} none ({v.get('summary')})"
    parts = ["injected" if v.get("injected") else "pressed", f"island uptime {v.get('island_uptime_ms')} ms"]
    if v.get("inject_to_seen_ms") is not None:
        parts.append(f"inject -> seen {v['inject_to_seen_ms']} ms")
    if v.get("seen_to_press_ms") is not None:
        parts.append(f"seen -> {'MANUAL request' if v.get('button') == 'SW1' else 'SIGSTOP'} {v['seen_to_press_ms']} ms")
    return f"{v.get('button')} ({', '.join(parts)})"


def table_rows(d):
    t = read(d, "table.md")
    if t is None:
        return None
    return [[c.strip() for c in l.strip().strip("|").split("|")] for l in t.splitlines()
            if l.startswith("| ") and not l.startswith("| term")]


def budget(d, v):
    """phase10-B9: the act's verdict, honest about the table. The scenario's
    verdict is the act's outcome (the safe state reached); a table row that
    FAILs (a budget over, a wrong rung, ...) turns a PASS into
    `FAIL (the act PASS; <n> table row(s) FAIL: <terms>; within the FTTI
    PASS)`, the FTTI row named when it still passes, and is appended to a
    FAIL. VOID, INVALID and REFUSED stay as they are: their terms are not
    evidence."""
    rows = table_rows(d) or []
    bad = [r[0].split(" (")[0] for r in rows if len(r) > 3 and r[3] == "FAIL"]
    if not bad or not (v == "PASS" or v.startswith("FAIL")):
        return v
    ftti = next((r for r in rows if r[0].startswith("within the FTTI") and len(r) > 3), None)
    what = f"{len(bad)} table row{'s' if len(bad) > 1 else ''} FAIL: {', '.join(bad)}"
    if ftti is not None and ftti[3] == "PASS":
        what += "; within the FTTI PASS"
    return f"FAIL (the act PASS; {what})" if v == "PASS" else f"{v}; {what}"


def selftest(check):
    """budget() on synthetic tables (tlcommon.py selftest, phase10-B9)."""
    import tempfile
    head = "| term | declared ms | observed ms | verdict | note |\n|---|---|---|---|---|\n"
    ok_rows = "| settle (braking command -> standstill) | 4165.33 | 3000.00 | PASS |  |\n" \
              "| within the FTTI | 10000.00 | 4900.00 | PASS |  |\n"
    bad_rows = "| settle (braking command -> standstill) | 4165.33 | 4300.00 | FAIL |  |\n" \
               "| total (last sample -> standstill) | 4934.67 | 4957.25 | FAIL |  |\n" \
               "| within the FTTI | 10000.00 | 4957.25 | PASS |  |\n"
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "table.md"), "w") as f:
            f.write(head + ok_rows)
        check("budget: a clean table keeps PASS", budget(d, "PASS") == "PASS")
        with open(os.path.join(d, "table.md"), "w") as f:
            f.write(head + bad_rows)
        got = budget(d, "PASS")
        check(f"budget: rows over turn PASS into FAIL, the FTTI named: {got}",
              got == "FAIL (the act PASS; 2 table rows FAIL: settle, total; within the FTTI PASS)")
        check("budget: a VOID stays VOID", budget(d, "VOID (no probe)") == "VOID (no probe)")
        check("budget: an INVALID stays INVALID", budget(d, "INVALID (RTF 0.5 < 0.95)").startswith("INVALID"))
        check("budget: a FAIL gets the rows appended",
              budget(d, "FAIL").startswith("FAIL; 2 table rows FAIL: settle, total"))


def table(d):
    rows = table_rows(d)
    if rows is None:
        return "table -"
    ok = sum(1 for r in rows if len(r) > 3 and r[3] == "PASS")
    # phase10-B2: a row stated for the record (the settle at the observed
    # speed while no response is declared) carries no verdict; it is counted
    # apart, so a clean table still reads n/n
    na = sum(1 for r in rows if len(r) > 3 and r[3] == "n/a" and r[0].startswith("settle at the observed"))
    total = next((r for r in rows if r[0].startswith("total")), None)
    s = f"table {ok}/{len(rows) - na} PASS" + (f" (+{na} n/a)" if na else "")
    if total:
        s += f", total {total[2]} of {total[1]} ms"
    return s


def trace_check(d):
    t = read(d, "island.trace.check.txt")
    m = re.search(r"trace-check: (\w+)", t or "")
    return f"trace-check {m.group(1) if m else '-'}{window(d)}{trace_use(d, t)}"


def trace_use(d, t):
    """C5 trace margin: the bytes the act's window used of the buffer, over
    how long, and where it was re-armed (the `rearm` event, scenario.py)."""
    m = re.search(r"window: \d+ records over ([0-9.]+) s after the trigger, \d+ B here, (\d+) B in the board", t or "")
    if not m:
        return ""
    try:
        size = json.loads(read(d, "island.trace.readout.json"))["buffer_size"]
    except (TypeError, ValueError, KeyError):
        size = None
    s = f", trace {int(m.group(2)):,} of {'-' if size is None else f'{size:,}'} B over {float(m.group(1)):.1f} s"
    r = events(d, "rearm")
    if r:
        v = r[-1]["value"] or {}
        if v.get("how") == "at the ODD exit":
            ok = (v.get("done_before_edge_ms") or 0) > 0 and v.get("go_before_edge_ms") is not None
            s += (f", re-armed {v['go_before_edge_ms'] / 1000:.2f} s before the ODD exit"
                  f" (go -> ack {v.get('go_to_done_ms')} ms)" if ok else ", NOT re-armed before the ODD exit")
        else:
            s += ", re-armed when the ego drove"
    return s


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
    v = budget(d, v)
    print(f"SUMMARY {run}{act}: {v}; {load(meta)}; {table(d)}; {trace_check(d)}; {stored(d)}; "
          f"{serial(d)}; {heap(d)}{asserted(d)}{carla}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
