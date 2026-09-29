#!/usr/bin/env python3
"""bp.py ELF sym1,sym2 SECONDS: reset-and-halt, hardware breakpoints on the symbols,
run, and on a hit print pc/lr and every code address found on the stack."""
import subprocess, sys, time
from pyocd.core.helpers import ConnectHelper
NM = "/home/aeon/.nros/sdk/arm-none-eabi-gcc/13.2-nros4/bin/arm-none-eabi-nm"
elf = sys.argv[1]; names = sys.argv[2].split(",")
syms = {}; byaddr = []
for l in subprocess.run([NM, "-S", "--defined-only", elf], capture_output=True, text=True).stdout.splitlines():
    p = l.split()
    if len(p) >= 4 and p[2] in "tTwW":
        a = int(p[0], 16) & ~1; syms.setdefault(p[3], a); byaddr.append((a, int(p[1], 16), p[3]))
def name(a):
    a &= ~1
    for s, z, n in byaddr:
        if s <= a < s + z:
            return f"{n}+{a - s:#x}"
    return hex(a)
with ConnectHelper.session_with_chosen_probe(target_override="s32k344", options={"connect_mode": "halt"}) as s:
    t = s.target
    t.reset_and_halt()
    for n in names:
        t.set_breakpoint(syms[n]); print("bp", n, hex(syms[n]), flush=True)
    t.resume()
    t0 = time.time()
    while time.time() - t0 < float(sys.argv[3]) and not t.is_halted():
        time.sleep(0.05)
    if not t.is_halted():
        print("no hit"); sys.exit()
    pc = t.read_core_register("pc"); lr = t.read_core_register("lr"); sp = t.read_core_register("sp")
    print("HALT after", round(time.time() - t0, 2), "s pc", name(pc), "lr", name(lr),
          "r0", hex(t.read_core_register("r0")), "r1", hex(t.read_core_register("r1")), "r4", hex(t.read_core_register("r4")), flush=True)
    def cstr(a):
        try: return bytes(t.read_memory_block8(a, 240)).split(b"\0")[0].decode(errors="replace")
        except Exception: return "?"
    for r in ("r0", "r1", "r2", "r3"):
        v = t.read_core_register(r)
        print(f"  {r}={v:#x}", repr(cstr(v)) if 0x20000000 <= v < 0x20500000 or 0x400000 <= v < 0x800000 else "")
    for i in range(256):
        v = t.read32(sp + 4 * i)
        if 0x400000 <= v < 0x800000:
            n = name(v)
            if not n.startswith("0x"):
                print("  stack", hex(sp + 4 * i), n)
    for n in names:
        t.remove_breakpoint(syms[n])
    t.resume()
