#!/usr/bin/env python3
"""The evaluation tools' selftest (CI): what they take from the checker
and from a run still reads the same.

  python3 tools/eval/selftest.py

Runs the board half's selftest first (tools/board/tlcommon.py: the
`--explain` table parser, the braking-profile arithmetic), then the checks
that need the evaluation's analysis on the same captured table
(tools/board/testdata/explain.txt): the overrun rows by the keys analysis.py
reads, every settle-derived profile recomputed (settle_s + response =
the checker's settle), the link and supervised rows, merge's clock
alignment and the run summary's verdict.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "board"))
import tlcommon as tl  # noqa: E402
import analysis  # noqa: E402
import merge  # noqa: E402
import run_summary  # noqa: E402


def selftest(path=os.path.join(HERE, "..", "board", "testdata", "explain.txt")):
    rc = tl.selftest(path)
    text = open(path).read()
    rows = tl.parse_explain(text)
    by = {(r["hazard"], r["rung"]): r for r in rows if r.get("role") != "overrun"}
    fails = []

    def check(what, ok):
        print(("ok   " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)
    # phase11-S7: the supervised settle's overrun row (play_launch 0.18.1),
    # which analysis.py's escalation total reads by its key
    ov = {(r["hazard"], r["rung"], r["term"]): r for r in rows if r.get("role") == "overrun"}
    st = ov.get(("odd_exit",) + analysis.OVERRUN_ROWS[2], {})
    cm = ov.get(("hpc_loss",) + analysis.OVERRUN_ROWS[1], {})
    check(f"odd_exit settle overrun row: total {st.get('total')} = DETECT+WINDOWS+ROUTE+SETTLE, "
          f"hpc_loss call_mrm overrun row: total {cm.get('total')}",
          st.get("total") is not None and cm.get("total") is not None
          and abs(st["detect"] + st["windows"] + st["route"] + st["settle"] - st["total"]) < 0.02
          and abs(cm["detect"] + cm["windows"] + cm["route"] + cm["settle"] - cm["total"]) < 0.02)
    prof = analysis.settle_profiles(text)
    resp = analysis.settle_responses(text, contract=False)  # phase10-B2: profile + response
    check(f"{len(prof)} settle-derived profiles parsed (want 3)", len(prof) == 3)
    for (hz, rung), (a, j, v0) in sorted(prof.items()):
        r = by.get((hz, rung))
        rs = resp.get((hz, rung), 0.0)
        mine = tl.settle_s(v0, a, j) * 1000 + rs
        check(f"{hz}/{rung}: settle_s({v0}, a {a}, j {j}) + response {rs} {mine:.2f} = checker "
              f"{r and r['settle']}",
              r is not None and abs(mine - r["settle"]) < 0.02)
    analysis.selftest_rows(check)  # phase10-B8 link rows, phase10-B2 settle row
    analysis.selftest_supervised(check)  # phase11-S7 supervised rows, HPC alive from the island
    merge.selftest(check)  # phase11-S6 the direct path's mrm_state aligns the clocks
    run_summary.selftest(check)  # phase10-B9 the verdict with the table
    print("eval selftest: " + ("OK" if not fails else f"{len(fails)} FAILED"))
    return 1 if rc or fails else 0


if __name__ == "__main__":
    sys.exit(selftest())
