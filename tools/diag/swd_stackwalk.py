#!/usr/bin/env python3
"""A crude stack walk over SWD: halt, read 8 KiB above SP, resume, and name
every word that looks like a Thumb return address in the image's flash or
ITCM (odd, in 0x400000-0x5fffff or 0x100-0xffff) with addr2line.

  swd_stackwalk.py <zephyr.elf> [bytes]

Heuristic: stale frames show up too; read it top down from the current SP.
It found the C4 assert recursion (docs/roadmap/phase-9-rtss-demo-open-items.md
section 8, C4). Attaches without reset (pyocd, MCU-Link).
"""
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "board"))
from spin_diag import ADDR2LINE  # noqa: E402


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit(__doc__)
    elf = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 8192
    from pyocd.core.helpers import ConnectHelper
    s = ConnectHelper.session_with_chosen_probe(target_override="s32k344", connect_mode="attach",
                                                options={"frequency": 4000000})
    s.open()
    t = s.board.target
    t.halt()
    sp = t.read_core_register("sp")
    r = {k: t.read_core_register(k) for k in ("pc", "lr", "r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7")}
    blob = bytes(t.read_memory_block8(sp, n))
    t.resume()
    s.close()
    print(f"sp={sp:#x}", " ".join(f"{k}={v:#x}" for k, v in r.items()))
    w = struct.unpack(f"<{n // 4}I", blob)
    cands = [(i, x) for i, x in enumerate(w) if (0x400000 <= x < 0x600000 or 0x100 <= x < 0x10000) and x & 1]
    out = subprocess.run([ADDR2LINE, "-f", "-p", "-e", elf] + [hex(x - 1) for _, x in cands],
                         capture_output=True, text=True).stdout.splitlines()
    for (i, x), line in zip(cands, out):
        print(f"sp+{i * 4:4d} {x:#x} {line}")


if __name__ == "__main__":
    main()
