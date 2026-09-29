#!/usr/bin/env python3
"""table.py RUNS_DIR PREFIX OUT1,OUT2,...: one markdown row per join from the saved verdicts."""
import json, sys
runs, pre, outs = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
for k in range(1, 6):
    try:
        lines = open(f"{runs}/{pre}-{k}.verdict").read().splitlines()
    except FileNotFoundError:
        continue
    for l in lines:
        d = json.loads(l)
        b = d.get("board_delta", {}); t = d.get("segment_totals_from_boot", {})
        rates = " / ".join(str(d["out_rates"][o]) for o in outs)
        print(f"| {pre}-{k} | {d['kind']} | {d['join_after_reset_done_s']} | {rates} | "
              f"{len(d['false_emergency'])} | {len(d['mrm_gaps_gt_0.3s_after_join'])} | "
              f"{t.get('ring_overflows')} | {b.get('rx_bad_frames')} | {t.get('ring_high_water')} | {d['verdict']} |")
