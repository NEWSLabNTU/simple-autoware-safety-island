#!/usr/bin/env python3
"""DIAG (spin latency): one line per late interval of a spin_diag.py decode.

  late_records.py <spin-diag-*.txt> [min_late_us]

Each `late#N` / `WORST` record of the decode (the shared ring of the latest
intervals at least 2 ms past their own park bound, and each level's worst)
as one line: the level, uptime ms, lateness, park bound, idle path,
callbacks and takes, ISR time / calls in the interval; then the segments
longer than 1.5 ms as `S<n>:wall/spin/idle/other` (us), the level thread's
lock waits (n/total/max and where), the longest callback (slot:wall/spin)
and the other threads' CPU. min_late_us (default 0) drops the shorter ones.
"""
import re
import sys

REC = re.compile(r"(late#\d+|WORST)(?: lvl=(\S+))? t=(\d+)ms interval=(\d+)us late=(\d+)us "
                 r"park_bound=(\d+us|none) idle_path=(\d) ncb=(\d+) ntake=(\d+) isr=(\d+)us/(\d+)")


def lines(txt, minlate=0):
    out = []
    for b in re.split(r"\n(?=late#|WORST)", txt):
        m = REC.match(b)
        if not m or int(m.group(5)) < minlate:
            continue
        lvl = m.group(2) or "-"
        t, late, pb, ip, ncb, ntk, isr, isrn = m.group(3, 5, 6, 7, 8, 9, 10, 11)
        segs = re.findall(r"(S\d) \w+: wall=\s*(\d+) spin=\s*(\d+) idle=\s*(\d+) other=\s*(-?\d+)", b)
        oth = re.search(r"other threads: (.*)", b)
        lk = re.search(r"spin lock waits: n=(\d+) total=(\d+)us max=(\d+)us in (\S+)", b)
        cb = re.search(r"longest cb: slot=(\d+) wall=(\d+) spin=(\d+)", b)
        s = " ".join(f"{n}:{w}/{sp}/{i}/{o}" for n, w, sp, i, o in segs if int(w) > 1500)
        lks = f"lk={lk.group(1)}/{lk.group(2)}/{lk.group(3)} {lk.group(4)}" if lk else "lk=-"
        cbs = f"cbmax={cb.group(1)}:{cb.group(2)}/{cb.group(3)}" if cb else "cbmax=-"
        pb = pb[:-2] if pb.endswith("us") else pb
        out.append(f"lvl={lvl} {t:>6} late={int(late):6d} pb={pb:>5} ip={ip} cb={ncb} "
                   f"tk={ntk} isr={isr}/{isrn} | {s} | {lks} {cbs} | {oth.group(1) if oth else '-'}")
    return out


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit(__doc__)
    with open(sys.argv[1]) as f:
        txt = f.read()
    minlate = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    for line in lines(txt, minlate):
        print(line)


if __name__ == "__main__":
    main()
