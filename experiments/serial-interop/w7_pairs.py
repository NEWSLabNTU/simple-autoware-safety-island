#!/usr/bin/env python3
"""Per-tick durations of the island's marker pairs, from a board trace (phase7-W7).

Reads a raw `ram_tracing` read (`just trace-board`) with the phase7-W1 decoder
(src/safety_island_tracing/island_trace.py), pairs every *_ENTRY marker with the
next *_EXIT of the same path, and prints, per pair: N, min, median, max of the
duration, and the same for the period between successive ENTRY markers. Also
writes every marker as CSV and every pair as CSV when --csv-dir is given.

Time is the CTF timestamp: the board's 32-bit cycle counter (160 MHz) read by
k_cycle_get_32() and converted to ns (u32, wraps every 4.29 s; the decoder
unwraps by neighbouring records, which are never 2.1 s apart while the 100 ms
heartbeat runs). Each marker's own cost (the locked write) falls inside the
interval it bounds: the EXIT marker's timestamp is taken after the ENTRY's
write completed, so a duration includes one marker's cost.

  w7_pairs.py <trace.bin> [--csv-dir DIR] [--zephyr 4.4] [--timeline N]
"""
import argparse
import csv
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src", "safety_island_tracing"))
import island_trace  # noqa: E402


def stats(xs):
    if not xs:
        return None
    return dict(n=len(xs), min=min(xs), med=statistics.median(xs), max=max(xs))


def us(ns):
    return ns / 1e3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--zephyr", default="4.4")
    ap.add_argument("--csv-dir")
    ap.add_argument("--timeline", type=int, default=0,
                    help="print the first N marker/heartbeat records")
    a = ap.parse_args()

    tr = island_trace.load(a.trace, a.zephyr)
    if tr.error:
        print(f"DECODE ERROR: {tr.error}")
    recs = tr.records
    t0 = recs[0]["t_ns"] if recs else 0
    markers = [r for r in recs if r["kind"] == "marker"]
    hbs = [r for r in recs if r["kind"] == "heartbeat"]
    print(f"trace: {a.trace}: {len(recs)} records, {tr.used} B used of the buffer, "
          f"{len(markers)} markers, {len(hbs)} heartbeats")
    if hbs:
        print(f"heartbeats: seq {hbs[0]['seq']}..{hbs[-1]['seq']}, uptime "
              f"{hbs[0]['uptime_ms']}..{hbs[-1]['uptime_ms']} ms")
    if markers:
        print(f"markers: first at {us(markers[0]['t_ns'] - t0) / 1e3:.3f} ms, last at "
              f"{us(markers[-1]['t_ns'] - t0) / 1e3:.3f} ms after the first record")

    # Pair ENTRY -> next EXIT of the same path. A second ENTRY before the EXIT
    # is reported (it would mean re-entry, which a single executor cannot do).
    open_at, pairs, anomalies = {}, {}, []
    entries = {}
    for r in markers:
        n = r["name"]
        if n.endswith("_ENTRY"):
            base = n[:-6]
            if base in open_at:
                anomalies.append(f"{base}: ENTRY at {r['t_ns']} while open since {open_at[base]}")
            open_at[base] = r["t_ns"]
            entries.setdefault(base, []).append(r["t_ns"])
        elif n.endswith("_EXIT"):
            base = n[:-5]
            if base not in open_at:
                anomalies.append(f"{base}: EXIT at {r['t_ns']} with no ENTRY (buffer start?)")
                continue
            pairs.setdefault(base, []).append((open_at.pop(base), r["t_ns"]))
    for base, t in open_at.items():
        anomalies.append(f"{base}: ENTRY at {t} never closed (buffer end?)")

    print()
    print(f"{'pair (ENTRY->EXIT)':<52}{'N':>6}{'min us':>11}{'median us':>11}{'max us':>11}")
    for base in sorted(pairs):
        s = stats([e - b for b, e in pairs[base]])
        print(f"{base:<52}{s['n']:>6}{us(s['min']):>11.1f}{us(s['med']):>11.1f}{us(s['max']):>11.1f}")
    print()
    print(f"{'period (ENTRY->next ENTRY)':<52}{'N':>6}{'min ms':>11}{'median ms':>11}{'max ms':>11}")
    for base in sorted(entries):
        ts = entries[base]
        s = stats([b - a for a, b in zip(ts, ts[1:])])
        if s:
            print(f"{base:<52}{s['n']:>6}{s['min'] / 1e6:>11.3f}{s['med'] / 1e6:>11.3f}{s['max'] / 1e6:>11.3f}")
    print()
    counts = {}
    for r in markers:
        counts[r["name"]] = counts.get(r["name"], 0) + 1
    print("marker counts:")
    for n in sorted(counts):
        print(f"  {n:<58}{counts[n]:>6}")
    if anomalies:
        print("pairing notes:")
        for x in anomalies:
            print("  " + x)

    if a.timeline:
        print()
        k = 0
        for r in recs:
            if r["kind"] not in ("marker", "heartbeat"):
                continue
            label = (f"{r['name']} arg={r['arg']}" if r["kind"] == "marker"
                     else f"heartbeat seq={r['seq']} uptime={r['uptime_ms']} ms")
            print(f"{(r['t_ns'] - t0) / 1e6:12.3f} ms  {label}")
            k += 1
            if k >= a.timeline:
                break

    if a.csv_dir:
        os.makedirs(a.csv_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(a.trace))[0]
        with open(os.path.join(a.csv_dir, stem + ".markers.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_ns_from_first_record", "kind", "name", "arg_or_seq", "uptime_ms"])
            for r in recs:
                if r["kind"] == "marker":
                    w.writerow([r["t_ns"] - t0, "marker", r["name"], r["arg"], ""])
                elif r["kind"] == "heartbeat":
                    w.writerow([r["t_ns"] - t0, "heartbeat", "", r["seq"], r["uptime_ms"]])
        with open(os.path.join(a.csv_dir, stem + ".pairs.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["pair", "entry_t_ns_from_first_record", "duration_ns"])
            for base in sorted(pairs):
                for b, e in pairs[base]:
                    w.writerow([base, b - t0, e - b])


if __name__ == "__main__":
    main()
