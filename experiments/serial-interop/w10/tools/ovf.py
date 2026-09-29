#!/usr/bin/env python3
"""ovf.py ELF: dump the W10 overflow snapshots, naming threads and wait queues."""
import struct, subprocess, sys
from pyocd.core.helpers import ConnectHelper
NM = "/home/aeon/.nros/sdk/arm-none-eabi-gcc/13.2-nros4/bin/arm-none-eabi-nm"
elf = sys.argv[1]
data = []; syms = {}
for l in subprocess.run([NM, "-S", "--defined-only", "-C", elf], capture_output=True, text=True).stdout.splitlines():
    p = l.split(None, 3)
    if len(p) >= 4:
        a = int(p[0], 16); syms[p[3]] = a; data.append((a, int(p[1], 16), p[3]))
def nm(a):
    for s, z, n in data:
        if s <= a < s + max(z, 1): return f"{n[:60]}+{a - s:#x}"
    return hex(a)
with ConnectHelper.session_with_chosen_probe(target_override="s32k344", options={"connect_mode": "attach"}) as s:
    t = s.target
    n = t.read32(syms["_z_w10_ovf_n"])
    print("snapshots", n, "overflows", struct.unpack("<10I", bytes(t.read_memory_block8(syms["_z_zephyr_serial_stats"], 40)))[5])
    def tname(th):
        if th == 0: return "-"
        nmb = bytes(t.read_memory_block8(th + 144, 16)).split(b"\0")[0].decode(errors="replace")
        if nmb: return nmb
        return "<" + nm(t.read32(th + 124) & ~1) + ">"
    names = {}
    for i in range(min(n, 32)):
        ms, run, rd, st, pend, held = struct.unpack("<IIIIII", bytes(t.read_memory_block8(syms["_z_w10_ovf"] + 24 * i, 24)))
        for th in (run, rd):
            if th not in names: names[th] = tname(th)
        print(f"{ms:8d} ms running={names[run]:28s} reader={names[rd]:12s} state={st:#04x} pended_on={nm(pend) if pend else 0} held={held}")
