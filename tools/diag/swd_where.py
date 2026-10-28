#!/usr/bin/env python3
"""Where is the core: one SWD halt of a running S32K344, PC/LR/SP/xPSR and
the fault status registers, resumed, and whether the island heartbeat moved
in the second after.

  swd_where.py <zephyr.elf>

Attaches without reset (pyocd, MCU-Link). PC and LR are named with the SDK's
addr2line (tools/board/spin_diag.py find_addr2line: $ADDR2LINE, then
$ZEPHYR_SDK_INSTALL_DIR, then the nros store). A heartbeat that does not move
with the core resumed means the island is wedged; IPSR (xPSR & 0x1ff) != 0
means it was halted inside an exception handler.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "board"))
from spin_diag import ADDR2LINE, symbols  # noqa: E402


def main():
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit(__doc__)
    elf = sys.argv[1]
    from pyocd.core.helpers import ConnectHelper
    hb = symbols(elf, {"island_trace_hb_seq"}).get("island_trace_hb_seq", (None,))[0]
    s = ConnectHelper.session_with_chosen_probe(target_override="s32k344", connect_mode="attach",
                                                options={"frequency": 4000000})
    s.open()
    t = s.board.target
    hb0 = t.read32(hb) if hb else None
    t.halt()
    regs = {r: t.read_core_register(r) for r in ("pc", "lr", "sp", "xpsr")}
    fsr = {n: t.read32(a) for n, a in (("CFSR", 0xE000ED28), ("HFSR", 0xE000ED2C),
                                       ("MMFAR", 0xE000ED34), ("BFAR", 0xE000ED38))}
    t.resume()
    time.sleep(1)
    hb1 = t.read32(hb) if hb else None
    s.close()
    print(" ".join(f"{k}={v:#x}" for k, v in regs.items()), f"IPSR={regs['xpsr'] & 0x1ff}",
          " ".join(f"{k}={v:#x}" for k, v in fsr.items()), f"heartbeat {hb0} -> {hb1} in 1 s")
    print(subprocess.run([ADDR2LINE, "-f", "-p", "-e", elf, hex(regs["pc"]), hex(regs["lr"] & ~1)],
                         capture_output=True, text=True).stdout, end="")


if __name__ == "__main__":
    main()
