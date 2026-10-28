#!/usr/bin/env python3
"""DIAG (spin latency): late spins in the ACT segment of diag runs.

  actseg.py [--survival] <run>...

A <run> is a run directory, or a run id under build/timeline/ of this
checkout. Each must hold spin-diag-pre.txt and spin-diag-act.txt, the two
`spin_diag.py read` decodes that tools/eval/run-diag.sh takes just
before and just after the act (a CONFIG_ISLAND_SPIN_DIAG image, built by
`just board-build-diag`).

The act segment is the act read minus the pre read: the whole-run rates
mislead, since a run idles for minutes before its act and the counters run
from boot. Columns:

  act spins      spins between the two reads
  >=1ms, >=2ms   spins at least 1 / 2 ms late against their due release
                 (the diagnostic's 1 ms lateness bins), and the same per 10k
  worst bin      the highest non-empty lateness bin in the act (ms)
  isr us/call    zenoh-pico's serial ISR cycles / calls at the act read
                 (CONFIG_NROS_ZENOH_SERIAL_ISR_STATS; 160 MHz core), "-"
                 when the image did not count them
  isr cpu s      the same cycles in seconds, cumulative from boot

--survival also prints, per run, how many act spins were at least x ms late
for x = 1, 2, ... (per 10k in brackets): the curve the deck's spin-latency
figure plots.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "..", "..", "build", "timeline")
CPU_HZ = 160_000_000


def read_diag(path):
    """(spins, {bin_ms: count}, {extra symbol: value string}) of one decode."""
    with open(path) as f:
        t = f.read()
    m = re.search(r"spins=(\d+)", t)
    hl = re.search(r"histogram[^\n]*", t)
    if not m or not hl:
        raise ValueError(f"{path}: no `spins=` / histogram line (not a spin_diag.py decode?)")
    hist = {int(a): int(b) for a, b in re.findall(r"(\d+):(\d+)", hl.group(0))}
    extra = dict(re.findall(r"^(_z_\w+): (.*)$", t, re.M))
    return int(m.group(1)), hist, extra


def act_segment(run_dir):
    s0, h0, _ = read_diag(os.path.join(run_dir, "spin-diag-pre.txt"))
    s1, h1, extra = read_diag(os.path.join(run_dir, "spin-diag-act.txt"))
    hist = {k: h1.get(k, 0) - h0.get(k, 0) for k in set(h0) | set(h1)}
    return s1 - s0, hist, extra


def resolve(run):
    if os.path.isdir(run):
        return run
    d = os.path.join(RUNS, run)
    if os.path.isdir(d):
        return d
    sys.exit(f"actseg: no run directory {run} (nor {os.path.normpath(d)})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--survival", action="store_true", help="per-ms counts of late act spins")
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    print(f"{'run':16s} {'act spins':>9s} {'>=1ms':>6s} {'>=2ms':>6s} {'/10k>=1':>8s} {'/10k>=2':>8s} "
          f"{'worst bin':>9s} {'isr us/call':>11s} {'isr cpu s':>9s}")
    curves = []
    for r in a.runs:
        d = resolve(r)
        n, h, ex = act_segment(d)
        late = lambda x: sum(v for k, v in h.items() if k >= x)  # noqa: E731
        g1, g2 = late(1), late(2)
        wb = max([k for k, v in h.items() if v > 0], default=0)
        cyc, calls = ex.get("_z_zephyr_serial_isr_cycles"), ex.get("_z_zephyr_serial_isr_calls")
        per = f"{int(cyc) / int(calls) / (CPU_HZ / 1e6):.2f}" if cyc and calls and int(calls) else "-"
        cpu = f"{int(cyc) / CPU_HZ:.2f}" if cyc else "-"
        rate = lambda g: f"{g * 1e4 / n:8.1f}" if n else f"{'-':>8s}"  # noqa: E731
        name = os.path.basename(os.path.normpath(d))
        print(f"{name:16s} {n:9d} {g1:6d} {g2:6d} {rate(g1)} {rate(g2)} {wb:>7d}ms {per:>11s} {cpu:>9s}")
        curves.append((name, n, [(x, late(x)) for x in range(1, wb + 1)]))
    if a.survival:
        for name, n, pts in curves:
            body = " ".join(f"{x}:{c}({c * 1e4 / n:.1f})" for x, c in pts) if n else ""
            print(f"survival {name}: {body or 'none late'}")


if __name__ == "__main__":
    main()
