#!/usr/bin/env python3
"""DIAG (spin latency): one line per late interval of a spin_diag.py decode.

  late_records.py <spin-diag-*.txt> [min_late_us]

Each `late#N` / `WORST` record of the decode (the ring of the latest
intervals at least 2 ms late) as one line: uptime ms, lateness, park bound,
idle path, callbacks and takes, ISR time / calls in the interval; then the
segments longer than 1.5 ms as `S<n>:wall/spin/idle/other` (us), the spin
thread's lock waits (n/total/max and where), the longest callback
(slot:wall/spin) and the other threads' CPU. min_late_us (default 0) drops
the shorter ones.
"""
import re
import sys


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit(__doc__)
    with open(sys.argv[1]) as f:
        txt = f.read()
    minlate = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    for b in re.split(r"\n(?=late#|WORST)", txt):
        m = re.match(r"(late#\d+|WORST) t=(\d+)ms interval=(\d+)us late=(\d+)us park_bound=(\d+)us "
                     r"idle_path=(\d) ncb=(\d+) ntake=(\d+) isr=(\d+)us/(\d+)", b)
        if not m or int(m.group(4)) < minlate:
            continue
        segs = re.findall(r"(S\d) \w+: wall=\s*(\d+) spin=\s*(\d+) idle=\s*(\d+) other=\s*(-?\d+)", b)
        oth = re.search(r"other threads: (.*)", b)
        lk = re.search(r"spin lock waits: n=(\d+) total=(\d+)us max=(\d+)us in (\S+)", b)
        cb = re.search(r"longest cb: slot=(\d+) wall=(\d+) spin=(\d+)", b)
        s = " ".join(f"{n}:{w}/{sp}/{i}/{o}" for n, w, sp, i, o in segs if int(w) > 1500)
        lks = f"lk={lk.group(1)}/{lk.group(2)}/{lk.group(3)} {lk.group(4)}" if lk else "lk=-"
        cbs = f"cbmax={cb.group(1)}:{cb.group(2)}/{cb.group(3)}" if cb else "cbmax=-"
        print(f"{m.group(2):>6} late={int(m.group(4)):6d} pb={m.group(5):>5} ip={m.group(6)} cb={m.group(7)} "
              f"tk={m.group(8)} isr={m.group(9)}/{m.group(10)} | {s} | {lks} {cbs} | {oth.group(1) if oth else '-'}")


if __name__ == "__main__":
    main()
