#!/usr/bin/env python3
"""The static timeline of one run, for the slides (phase8-W7).

  render.py <run_dir> [--out <run_dir>/timeline.png] [--explain <run_dir>/explain.txt]
            [--table]  (print the declared-vs-observed table as markdown)

Reads the same JSONL files the live view tails (every *.jsonl in the run
directory) and the checker's `--explain` output saved beside them (or runs
`play_launch check` on the live contract when there is none). Lanes, top to
bottom: velocity with the ODD bound and the derived stop curve; the mode
band; declared bars (hatched) over observed bars (solid), one pair per rung
the hazard reaches, with the FTTI; event ticks; the verdicts.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis as an  # noqa: E402
import tlcommon as tl  # noqa: E402

# Categorical slots (dataviz reference palette, validated light): one per
# budget term, labelled on the bar; status colours only for PASS / FAIL.
TERM = {"detect": "#2a78d6", "windows": "#eb6834", "route": "#1baf7a", "settle": "#eda100"}
GOOD, CRIT, INK, INK2, GRID = "#0ca30c", "#d03b3b", "#0b0b0b", "#52514e", "#e4e3df"
MODE = {"l3_engaged": "#dbe8f8", "takeover_request": "#fbe0d4", "comfortable_stop": "#fdecc4",
        "emergency_stop": "#f6d3d3", "manual": "#d6efe4"}


def load_run(run_dir, explain_path=None):
    ev = tl.read_events(tl.run_files(run_dir))
    p = explain_path or os.path.join(run_dir, "explain.txt")
    if os.path.exists(p):
        text = open(p).read()
    else:
        text = tl.explain_text()
    cfg = next((e["value"] for e in ev if e["source"] == "probe" and e["kind"] == "config"), {})
    return ev, text, tl.parse_explain(text), cfg


def s(t_ms):
    return None if t_ms is None else t_ms / 1000.0


def mode_spans(r, t_end):
    E = r["edges"]
    spans = []
    if r["act"] in ("a", "b"):
        on, off = E.get("tor_on"), E.get("tor_off")
        spans.append(("l3_engaged", -1e9, on if on is not None else t_end))
        if on is not None:
            spans.append(("takeover_request", on, off if off is not None else t_end))
        if r["act"] == "a" and off is not None:
            spans.append(("manual", off, t_end))
        if r["act"] == "b" and off is not None:
            # one span per rung the run passed through: an escalation part
            # way through the comfortable stop shows as its own span
            seq = [(t, {"EMERGENCY_STOP": "emergency_stop"}.get(b, "comfortable_stop"))
                   for t, b in (r.get("behaviors") or [])] or [(off, "comfortable_stop")]
            seq = [(off, seq[0][1])] + seq[1:]
            for i, (t, name) in enumerate(seq):
                if i and name == seq[i - 1][1]:
                    continue
                nxt = next((u for u, m in seq[i + 1:] if m != name), t_end)
                spans.append((name, t, nxt))
    else:
        op = E.get("detect_tick")
        spans.append(("l3_engaged", -1e9, op if op is not None else t_end))
        if op is not None:
            spans.append(("emergency_stop", op, t_end))
    return spans


def bar_segments(r):
    """[(label, declared segments, observed segments)], segments (term, start_ms, len_ms)."""
    E, o, dr = r["edges"], r["observed"], r["declared"]
    out = []
    if r["act"] in ("a", "b"):
        tr = dr.get("takeover_request", {})
        dseg = [("detect", 0.0, tr.get("detect") or 0.0)]
        x = dseg[-1][1] + dseg[-1][2]
        dseg += [("route", x, tr.get("route") or 0.0)]
        x += tr.get("route") or 0.0
        dseg += [("windows", x, r["window_ms"])]
        oseg = []
        if E.get("fault_on_wire") is not None:
            oseg.append(("detect", 0.0, E["fault_on_wire"]))
            if E.get("tor_on") is not None:
                oseg.append(("route", E["fault_on_wire"], E["tor_on"] - E["fault_on_wire"]))
                if E.get("tor_off") is not None:
                    oseg.append(("windows", E["tor_on"], E["tor_off"] - E["tor_on"]))
        out.append(("takeover_request", dseg, oseg))
        if r["act"] == "b":
            cs = dr.get("comfortable_stop", {})
            d = [("detect", 0.0, cs["detect"]), ("windows", cs["detect"], cs["windows"]),
                 ("route", cs["detect"] + cs["windows"], cs["route"]),
                 ("settle", cs["detect"] + cs["windows"] + cs["route"], cs["settle"])] if cs else []
            oseg = []
            # Cut at the deadline (request on + window), where the checker
            # ends WINDOWS; the late notice is in the route (phase8-W12).
            if E.get("fault_on_wire") is not None and E.get("deadline") is not None:
                oseg = [("detect", 0.0, E["fault_on_wire"]),
                        ("windows", E["fault_on_wire"], E["deadline"] - E["fault_on_wire"])]
                if E.get("safe_cmd") is not None:
                    oseg.append(("route", E["deadline"], E["safe_cmd"] - E["deadline"]))
                    if E.get("standstill") is not None:
                        oseg.append(("settle", E["safe_cmd"], E["standstill"] - E["safe_cmd"]))
            out.append(("comfortable_stop", d, oseg))
    else:
        fl = dr.get("emergency_stop", {})
        base = E.get("island_take") if E.get("island_take") is not None else E.get("host_take")
        b0 = base or 0.0
        d = [("detect", b0, fl["detect"]), ("route", b0 + fl["detect"], fl["route"]),
             ("settle", b0 + fl["detect"] + fl["route"], fl["settle"])] if fl else []
        oseg = []
        if base is not None and E.get("detect_tick") is not None:
            oseg.append(("detect", base, E["detect_tick"] - base))
            if E.get("safe_cmd") is not None:
                oseg.append(("route", E["detect_tick"], E["safe_cmd"] - E["detect_tick"]))
                if E.get("standstill") is not None:
                    oseg.append(("settle", E["safe_cmd"], E["standstill"] - E["safe_cmd"]))
        out.append(("emergency_stop", d, oseg))
    return out


TERM_LABEL = {"detect": "detect", "windows": "window", "route": "route", "settle": "settle"}


def render(run_dir, out, explain_path=None, title=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    ev, text, rows, cfg = load_run(run_dir, explain_path)
    r = an.analyze(ev, rows, text, windows=cfg.get("windows"), entry_speed=cfg.get("entry_speed"))
    if r is None:
        sys.exit("render: no injection in this run")
    t0 = r["t0"]
    vel = [((e["t_mono_ns"] - t0) / 1e9, e["value"]) for e in ev if e["source"] == "probe" and e["kind"] == "velocity"]
    E = r["edges"]
    ends = [v for v in E.values() if v is not None]
    t_end = max(ends + [0.0]) + 2500.0
    if r["act"] == "a":
        t_end = max(t_end, r["window_ms"] + 2500.0)
    shown = [row.get("total") or 0.0 for row in r["declared"].values() if row.get("role") != "skipped"]
    shown = [x for x in shown if x] + ([r["window_end_ms"] or r["window_ms"]] if r["act"] in ("a", "b") else [])
    t_end = max([t_end] + [x + 1000.0 for x in shown])
    x_lo, x_hi = -2.0, t_end / 1000.0
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2, "font.family": "DejaVu Sans"})
    fig = plt.figure(figsize=(12.5, 7.4), dpi=130, facecolor="#fcfcfb")
    gs = fig.add_gridspec(4, 1, height_ratios=[2.2, 0.45, 2.0, 0.9], hspace=0.12,
                          left=0.11, right=0.72, top=0.90, bottom=0.07)
    axv, axm, axb, axe = [fig.add_subplot(gs[i]) for i in range(4)]
    for ax in (axv, axm, axb, axe):
        ax.set_facecolor("#fcfcfb")
        ax.set_xlim(x_lo, x_hi)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    for ax in (axv, axm, axb):
        ax.tick_params(labelbottom=False)
    # 1. velocity
    axv.plot([v[0] for v in vel if x_lo <= v[0] <= x_hi], [v[1] for v in vel if x_lo <= v[0] <= x_hi],
             color=TERM["detect"], lw=2, label="|v| (kinematic_state)")
    bound = r["entry_speed_declared"]
    if bound:
        axv.axhline(bound, color=INK2, lw=1, ls=(0, (4, 3)))
        axv.text(x_lo + 0.1, bound + 0.15, f"ODD bound = entry_speed {bound} m/s", color=INK2, fontsize=8)
    if r["profile"] and r["entry_speed_observed"] and E.get("safe_cmd") is not None:
        a, j, _ = r["profile"]
        curve = tl.stop_curve(r["entry_speed_observed"], -a, -j)
        x0 = s(E["safe_cmd"])
        axv.plot([x0 + c[0] for c in curve], [c[1] for c in curve], color=TERM["settle"], lw=2,
                 ls=(0, (5, 3)), label=f"derived stop from {r['entry_speed_observed']:.2f} m/s (a {a}, j {j})")
    ymax = max([v[1] for v in vel] + [bound or 0]) * 1.15 + 0.5
    axv.set_ylim(0, ymax)
    axv.set_ylabel("m/s")
    axv.grid(axis="y", color=GRID, lw=0.6)
    if r["entry_speed_exceeded"]:
        axv.text(x_hi, ymax * 0.92, "ENTRY SPEED ABOVE THE DECLARED BOUND", color=CRIT, ha="right", fontsize=9,
                 fontweight="bold")
    axv.legend(loc="upper right", frameon=False, fontsize=8)
    # 2. mode band
    for name, a_, b_ in mode_spans(r, t_end):
        lo, hi = max(s(a_), x_lo), min(s(b_), x_hi)
        if hi > lo:
            axm.axvspan(lo, hi, color=MODE[name], lw=0)
            axm.text((lo + hi) / 2, 0.5, name, ha="center", va="center", fontsize=8, color=INK)
    axm.set_yticks([])
    axm.set_ylabel("mode", rotation=0, ha="right", va="center")
    # 3. bars
    pairs = bar_segments(r)
    y, yt, yl = 0, [], []
    fttis = []
    for label, dseg, oseg in pairs:
        for kind, segs in (("declared", dseg), ("observed", oseg)):
            for term, x, w in segs:
                if w is None:
                    continue
                red = False
                if kind == "observed" and label == "takeover_request" and term == "windows" and r["act"] == "b":
                    red = w < r["window_ms"] or (r["window_end_ms"] is not None and w > r["window_end_ms"])
                axb.barh(y, w / 1000.0, left=x / 1000.0, height=0.62,
                         color=(CRIT if red else TERM[term]), alpha=(0.35 if kind == "declared" else 1.0),
                         hatch=("////" if kind == "declared" else None), edgecolor="#fcfcfb", linewidth=1.5)
                if w / 1000.0 > 0.06 * (x_hi - x_lo) / 3:
                    axb.text((x + w / 2) / 1000.0, y, f"{TERM_LABEL[term]} {w:.0f}", ha="center", va="center",
                             fontsize=7.5, color=INK)
            yt.append(y)
            yl.append(f"{label}\n{kind}")
            y -= 1
        y -= 0.4
        row = r["declared"].get(label, {})
        if row.get("ftti"):
            fttis.append(row["ftti"])
    for f in sorted(set(fttis)):
        if f / 1000.0 <= x_hi:
            axb.axvline(f / 1000.0, color=CRIT, lw=1.2)
            axb.text(f / 1000.0, 0.7, f"FTTI {f / 1000:.0f} s", color=CRIT, fontsize=8, ha="right")
        else:
            axb.text(x_hi, 0.7, f"FTTI {f / 1000:.0f} s (off the right edge)", color=CRIT, fontsize=8, ha="right")
    axb.set_yticks(yt)
    axb.set_yticklabels(yl, fontsize=7.5)
    axb.set_ylim(y + 0.6, 1.9)  # headroom: the legend sits above the first bar
    axb.grid(axis="x", color=GRID, lw=0.6)
    axb.legend(handles=[Patch(facecolor=c, label=TERM_LABEL[k]) for k, c in TERM.items()] +
               [Patch(facecolor="white", edgecolor=INK2, hatch="////", label="declared (checker)"),
                Patch(facecolor=INK2, label="observed (events)")],
               loc="upper left", frameon=False, fontsize=7.5, ncol=6)
    # 4. event ticks
    ticks = [("press", "button", INK), ("fault_on_wire", "verdict on the wire", INK2),
             ("tor_on", "request on", TERM["windows"]), ("takeover_press", "takeover pressed", INK),
             ("manual_host", "MANUAL", GOOD), ("tor_off", "request off", TERM["windows"]),
             ("safe_cmd", "safe-state command", TERM["route"]), ("first_decel", "planner brakes", TERM["settle"]),
             ("hazard_lights_on", "hazard lights", CRIT), ("standstill", "standstill", INK),
             ("island_take", "last island take" if r["act"] == "encore" else "island take", INK2),
             ("detect_tick", "reaction tick", TERM["detect"])]
    lvl = 0
    if r["act"] != "encore":
        ticks = [tk for tk in ticks if tk[0] != "island_take"]
    for key, name, col in sorted((tk for tk in ticks if E.get(tk[0]) is not None), key=lambda tk: E[tk[0]]):
        t = E[key]
        axe.axvline(s(t), color=col, lw=1)
        axe.text(s(t), 0.95 - 0.19 * (lvl % 5), f" {name} {t / 1000:.3f}", fontsize=7, color=col, va="top")
        lvl += 1
    axe.set_yticks([])
    axe.set_ylim(0, 1)
    axe.set_xlabel("s since the button (host CLOCK_MONOTONIC; island markers aligned)")
    # verdicts
    lines = []
    for v in r["verdicts"]:
        st = "PASS" if v["ok"] else ("FAIL" if v["ok"] is False else "n/a")
        term = v["term"] if len(v["term"]) <= 44 else v["term"][:43] + "."  # the panel is 44 wide
        lines.append((f"{st:4}  {term}", f"      obs {an.fmt(v['observed'])}  decl {an.fmt(v['declared'])}",
                      v["ok"]))
    yv = 0.90
    fig.text(0.74, yv, "Verdicts (ms)", fontsize=10, fontweight="bold", color=INK)
    for a_, b_, ok in lines:
        yv -= 0.033
        fig.text(0.74, yv, a_, fontsize=7.8, color=(GOOD if ok else CRIT if ok is False else INK2),
                 family="DejaVu Sans Mono")
        yv -= 0.024
        fig.text(0.74, yv, b_, fontsize=7.3, color=INK2, family="DejaVu Sans Mono")
    al = r.get("align") or {}
    yv -= 0.045
    dis = al.get("disagreement_ms")
    fig.text(0.74, yv, "island markers: " + (("aligned, anchors disagree by %.2f ms" % dis) if dis is not None
                                              else ("aligned on one anchor" if al else "none in this file")),
             fontsize=7.5, color=INK2)
    yv -= 0.03
    # the rung from the trace's meta (run-board.sh writes target=board|qemu; run-native.sh none)
    target = "native_sim"
    try:
        for ln in open(os.path.join(run_dir, "island.trace.meta")):
            if ln.startswith("target="):
                target = ln.split("=", 1)[1].strip()
    except OSError:
        pass
    rung = {"board": "S32K344 silicon (island clock real)",
            "qemu": "QEMU (TCG, no icount; island clock not the host's)"}.get(
        target, "native_sim (simulated time; zero-time callbacks)")
    fig.text(0.74, yv, "rung: " + rung, fontsize=7.5, color=INK2)
    names = {"a": "Branch A: ODD exit, the driver takes over", "b": "Branch B: ODD exit, nobody answers",
             "encore": "Encore: HPC loss"}
    fig.suptitle(title or f"{names[r['act']]}  ({os.path.basename(os.path.normpath(run_dir))})", x=0.07,
                 ha="left", fontsize=12, fontweight="bold", color=INK)
    fig.text(0.07, 0.925, "declared bars: play_launch check --explain on the island contract; observed: probe, "
             "gate, scenario and island trace events", fontsize=8, color=INK2)
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    return r


def table(r):
    out = ["| term | declared ms | observed ms | verdict | note |", "|---|---|---|---|---|"]
    for v in r["verdicts"]:
        st = "PASS" if v["ok"] else ("FAIL" if v["ok"] is False else "n/a")
        out.append(f"| {v['term']} | {an.fmt(v['declared'])} | {an.fmt(v['observed'])} | {st} | {v['note']} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--explain", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args()
    out = a.out or os.path.join(a.run_dir, "timeline.png")
    r = render(a.run_dir, out, a.explain, a.title)
    print(f"render: {out}")
    if a.table:
        print(table(r))
        print("edges (ms from the button): " + ", ".join(f"{k} {an.fmt(v)}" for k, v in r["edges"].items()))
        print("observed: " + ", ".join(f"{k} {an.fmt(v)}" for k, v in r["observed"].items()))
        for n in r["notes"]:
            print(f"note: {n}")
        print(f"entry speed: observed {an.fmt(r['entry_speed_observed'], 3)} m/s, declared "
              f"{r['entry_speed_declared']}; settle derived at the observed speed "
              f"{an.fmt(r['settle_at_observed_speed_ms'])} ms")


if __name__ == "__main__":
    main()
