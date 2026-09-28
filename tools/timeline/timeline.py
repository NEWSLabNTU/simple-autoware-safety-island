#!/usr/bin/env python3
"""The live timeline (phase8-W7): pyqtgraph, fed by tailing JSONL files.

  timeline.py <run_dir> [--explain FILE] [--launch <launch.xml>] [--png OUT]

Tails every *.jsonl in <run_dir> (the probe's, the gate's, the scenario
controller's, the merged island markers, and a play_launch observer log
dropped there) at 20 Hz. The declared bars are the checker's own arithmetic:
the fault-reaction table of `play_launch check --explain` (a saved
explain.txt in the run directory, or a fresh run on the live contract).

Before the first injection the velocity lane scrolls over the last 60 s.
At the first injection t = 0 is the button and the declared bars are laid
from it; observed bars grow as their edges arrive. The takeover-request rung
turns red the moment its dwell exceeds its window plus one handler tick; the
velocity lane flags an entry speed above the hazard's declared bound.
--png writes a screenshot of the window on exit (render.py is the slide
renderer; this is the booth view).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis as an  # noqa: E402
import render as rd  # noqa: E402
import tlcommon as tl  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--explain", default=None)
    ap.add_argument("--launch", default=tl.LAUNCH)
    ap.add_argument("--png", default=None)
    ap.add_argument("--quit-after", type=float, default=None, help="close after N s (tests)")
    a = ap.parse_args()

    import pyqtgraph as pg
    from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

    if a.explain and os.path.exists(a.explain):
        text = open(a.explain).read()
    elif os.path.exists(os.path.join(a.run_dir, "explain.txt")):
        text = open(os.path.join(a.run_dir, "explain.txt")).read()
    else:
        text = tl.explain_text(a.launch)
    rows = tl.parse_explain(text)
    os.makedirs(a.run_dir, exist_ok=True)

    pg.setConfigOptions(antialias=True, background="#fcfcfb", foreground="#52514e")
    app = QtWidgets.QApplication([])
    win = QtWidgets.QWidget()
    win.setWindowTitle(f"takeover timeline - {a.run_dir}")
    win.resize(1500, 900)
    lay = QtWidgets.QHBoxLayout(win)
    glw = pg.GraphicsLayoutWidget()
    lay.addWidget(glw, 4)
    side = QtWidgets.QLabel()
    side.setTextFormat(QtCore.Qt.RichText)
    side.setAlignment(QtCore.Qt.AlignTop)
    side.setMinimumWidth(360)
    side.setStyleSheet("font-family: monospace; font-size: 12px; color: #0b0b0b; background: #fcfcfb;")
    lay.addWidget(side, 1)

    pv = glw.addPlot(row=0, col=0, title="velocity (m/s)")
    pv.showGrid(y=True, alpha=0.2)
    vcurve = pv.plot(pen=pg.mkPen(rd.TERM["detect"], width=2))
    dcurve = pv.plot(pen=pg.mkPen(rd.TERM["settle"], width=2, style=QtCore.Qt.DashLine))
    bound_line = pg.InfiniteLine(angle=0, pen=pg.mkPen("#52514e", style=QtCore.Qt.DashLine))
    pv.addItem(bound_line)
    flag = pg.TextItem("", color=rd.CRIT, anchor=(1, 0))
    pv.addItem(flag)
    pm = glw.addPlot(row=1, col=0)
    pm.hideAxis("left")
    pm.setMaximumHeight(70)
    pm.setXLink(pv)
    pb = glw.addPlot(row=2, col=0, title="declared (hatched, pale) / observed (solid), ms bars")
    pb.setXLink(pv)
    pb.hideAxis("left")
    pe = glw.addPlot(row=3, col=0)
    pe.setMaximumHeight(110)
    pe.hideAxis("left")
    pe.setXLink(pv)
    pe.setLabel("bottom", "s (0 = the button; before it, s before now)")

    tails = {}
    events = []
    dyn = dict(items=[], r=None, n_seen=0)

    def poll():
        for f in os.listdir(a.run_dir):
            if f.endswith(".jsonl") and f not in tails:
                tails[f] = tl.Tail(os.path.join(a.run_dir, f))
        new = []
        for t in tails.values():
            new += t.poll()
        if new:
            events.extend(new)
            events.sort(key=lambda e: e["t_mono_ns"])

    def clear_dyn():
        for plot, it in dyn["items"]:
            plot.removeItem(it)
        dyn["items"] = []

    def add(plot, it):
        plot.addItem(it)
        dyn["items"].append((plot, it))

    tick = dict(n=0)

    def redraw():
        poll()
        tick["n"] += 1
        now = tl.now_ns()
        cfg = next((e["value"] for e in events if e["source"] == "probe" and e["kind"] == "config"), {})
        r = an.analyze(events, rows, text, windows=cfg.get("windows"), entry_speed=cfg.get("entry_speed")) \
            if tick["n"] % 5 == 1 or dyn["r"] is None else dyn["r"]
        dyn["r"] = r
        t0 = r["t0"] if r else now
        vel = [e for e in events if e["source"] == "probe" and e["kind"] == "velocity"]
        xs = [(e["t_mono_ns"] - t0) / 1e9 for e in vel]
        vcurve.setData(xs, [e["value"] for e in vel])
        bound = (cfg.get("entry_speed") or {}).get(r["hazard"] if r else "odd_exit")
        if bound:
            bound_line.setValue(bound)
        if r is None:
            pv.setXRange(-60, 0, padding=0)
            side.setText("<b>waiting for the first button</b><br>" + "<br>".join(
                f"{x['hazard']}/{x['rung']}: {x['role']} total {an.fmt(x['total'])} / FTTI {an.fmt(x['ftti'])}"
                for x in rows))
            return
        if tick["n"] % 5 != 1:
            return
        clear_dyn()
        now_ms = (now - t0) / 1e6
        E = r["edges"]
        t_end = max([v for v in E.values() if v is not None] + [now_ms if now_ms < 60000 else 0.0])
        shown = [row.get("total") or 0.0 for row in r["declared"].values() if row.get("role") != "skipped"]
        shown += [r["window_ms"] + 110.0] if r["act"] in ("a", "b") else []
        pv.setXRange(-2, max([t_end / 1000 + 2, 12] + [x / 1000 + 1 for x in shown if x]), padding=0)
        if r["profile"] and r["entry_speed_observed"] and E.get("safe_cmd") is not None:
            a_, j_, _ = r["profile"]
            c = tl.stop_curve(r["entry_speed_observed"], -a_, -j_)
            dcurve.setData([E["safe_cmd"] / 1000 + p[0] for p in c], [p[1] for p in c])
        flag.setText("ENTRY SPEED ABOVE THE DECLARED BOUND" if r["entry_speed_exceeded"] else "")
        flag.setPos(max(t_end / 1000, 10), (bound or 8) * 1.1)
        # mode band
        for name, lo, hi in rd.mode_spans(r, t_end if E.get("standstill") else now_ms):
            reg = pg.LinearRegionItem(values=(max(lo, -2000) / 1000, hi / 1000), movable=False,
                                      brush=pg.mkBrush(rd.MODE[name]), pen=pg.mkPen(None))
            add(pm, reg)
            txt = pg.TextItem(name, color="#0b0b0b", anchor=(0.5, 0.5))
            txt.setPos((max(lo, -2000) + hi) / 2000, 0.5)
            add(pm, txt)
        pm.setYRange(0, 1)
        # bars; the live window bar grows while the request is on
        y = 0
        for label, dseg, oseg in rd.bar_segments(r):
            if label == "takeover_request" and E.get("tor_on") is not None and E.get("tor_off") is None:
                oseg = [s_ for s_ in oseg if s_[0] != "windows"] + [("windows", E["tor_on"], now_ms - E["tor_on"])]
            for kind, segs in (("declared", dseg), ("observed", oseg)):
                for term, x, w in segs:
                    if w is None or w <= 0:
                        continue
                    col = rd.TERM[term]
                    if (kind == "observed" and label == "takeover_request" and term == "windows"
                            and w > r["window_ms"] + an.TICK_MS):
                        col = rd.CRIT
                    brush = pg.mkBrush(col) if kind == "observed" else pg.mkBrush(QtGui.QColor(col).lighter(160))
                    bar = pg.BarGraphItem(x0=[x / 1000], y=[y], height=0.6, width=[w / 1000], brush=brush,
                                          pen=pg.mkPen("#fcfcfb", width=2))
                    add(pb, bar)
                    if w > 600:
                        lab = pg.TextItem(f"{rd.TERM_LABEL[term]} {w:.0f}", color="#0b0b0b", anchor=(0.5, 0.5))
                        lab.setPos((x + w / 2) / 1000, y)
                        add(pb, lab)
                lab = pg.TextItem(f"{label} {kind}", color="#52514e", anchor=(0, 0.5))
                lab.setPos(-1.95, y)
                add(pb, lab)
                y -= 1
            row = r["declared"].get(label, {})
            if row.get("ftti"):
                ln = pg.InfiniteLine(pos=row["ftti"] / 1000, angle=90, pen=pg.mkPen(rd.CRIT, width=2))
                add(pb, ln)
            y -= 0.5
        # ticks
        k = 0
        for key, name, col in (("press", "button", "#0b0b0b"), ("tor_on", "request on", rd.TERM["windows"]),
                               ("manual_host", "MANUAL", rd.GOOD), ("tor_off", "request off", rd.TERM["windows"]),
                               ("safe_cmd", "safe-state command", rd.TERM["route"]),
                               ("hazard_lights_on", "hazard lights", rd.CRIT), ("standstill", "standstill", "#0b0b0b"),
                               ("detect_tick", "reaction tick", rd.TERM["detect"])):
            t = E.get(key)
            if t is None:
                continue
            add(pe, pg.InfiniteLine(pos=t / 1000, angle=90, pen=pg.mkPen(col)))
            txt = pg.TextItem(name, color=col, anchor=(0, 0))
            txt.setPos(t / 1000, 1.0 - 0.25 * (k % 4))
            add(pe, txt)
            k += 1
        pe.setYRange(0, 1.2)
        # verdicts
        html = [f"<b>{r['act'].upper()} &nbsp; hazard {r['hazard']}</b><br><br>"]
        for v in r["verdicts"]:
            ok = v["ok"]
            col = rd.GOOD if ok else (rd.CRIT if ok is False else "#52514e")
            st = "PASS" if ok else ("FAIL" if ok is False else "...")
            html.append(f"<span style='color:{col}'>{st}</span> {v['term']}<br>"
                        f"&nbsp;&nbsp;obs {an.fmt(v['observed'])} &nbsp;decl {an.fmt(v['declared'])}<br>")
        al = r.get("align") or {}
        if al.get("disagreement_ms") is not None:
            html.append(f"<br>island aligned, anchors disagree by {al['disagreement_ms']:.2f} ms")
        side.setText("".join(html))

    timer = QtCore.QTimer()
    timer.timeout.connect(redraw)
    timer.start(50)
    if a.quit_after:
        def done():
            redraw()
            if a.png:
                win.grab().save(a.png)
            app.quit()
        QtCore.QTimer.singleShot(int(a.quit_after * 1000), done)
    win.show()
    app.exec_()
    if a.png and not a.quit_after:
        win.grab().save(a.png)


if __name__ == "__main__":
    main()
