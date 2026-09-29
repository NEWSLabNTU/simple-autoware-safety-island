#!/usr/bin/env python3
"""Host stamps for the island's console (phase8-W29).

  zephyr.exe ... 2>&1 | stamp.py <raw log> <stamped log>

Copies stdin to <raw log> unchanged and to <stamped log> with each line
prefixed by the host CLOCK_MONOTONIC ns at which it was read (the clock of
every tlcommon event). native_sim line-buffers its stdout, so the stamp is
when the island printed the line, in host time: set beside the simulated
time the line carries, it shows how far the island's clock is from the
host's (docs/takeover-trace.md, section 8).
"""
import sys
import time

raw = open(sys.argv[1], "wb", buffering=0)
stamped = open(sys.argv[2], "wb", buffering=0)
for line in sys.stdin.buffer:
    t = time.monotonic_ns()
    raw.write(line)
    stamped.write(b"%d " % t + line)
