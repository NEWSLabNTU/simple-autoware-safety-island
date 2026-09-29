#!/usr/bin/env python3
"""bpn.py ELF sym1,sym2 SECONDS MAXHITS: reset-and-halt, breakpoints, log every hit (pc, lr, r0-r3) and continue."""
import subprocess, sys, time
from pyocd.core.helpers import ConnectHelper
NM = "/home/aeon/.nros/sdk/arm-none-eabi-gcc/13.2-nros4/bin/arm-none-eabi-nm"
elf = sys.argv[1]; names = sys.argv[2].split(","); secs = float(sys.argv[3]); maxh = int(sys.argv[4])
syms = {}; byaddr = []
for l in subprocess.run([NM, "-S", "--defined-only", "-C", elf], capture_output=True, text=True).stdout.splitlines():
    p = l.split(None, 3)
    if len(p) >= 4 and p[2] in "tTwW":
        a = int(p[0], 16) & ~1; syms.setdefault(p[3], a); byaddr.append((a, int(p[1], 16), p[3]))
def name(a):
    a &= ~1
    for s, z, n in byaddr:
        if s <= a < s + z: return f"{n[:90]}+{a - s:#x}"
    return hex(a)
with ConnectHelper.session_with_chosen_probe(target_override="s32k344", options={"connect_mode": "halt"}) as s:
    t = s.target
    t.reset_and_halt()
    addrs = []
    for n in names:
        a = syms[n] if n in syms else int(n, 16)
        t.set_breakpoint(a); addrs.append(a)
    t.resume(); t0 = time.time(); hits = 0
    while time.time() - t0 < secs and hits < maxh:
        if t.is_halted():
            hits += 1
            pc = t.read_core_register("pc"); lr = t.read_core_register("lr")
            regs = " ".join(f"{r}={t.read_core_register(r):#x}" for r in ("r0", "r1", "r2", "r3"))
            print(f"{time.time()-t0:7.3f} pc={name(pc)} lr={name(lr)} {regs}", flush=True)
            a0 = pc & ~1
            if a0 in addrs: t.remove_breakpoint(a0)
            t.step()
            if a0 in addrs: t.set_breakpoint(a0)
            t.resume()
        time.sleep(0.01)
    for a in addrs: t.remove_breakpoint(a)
    t.resume()
