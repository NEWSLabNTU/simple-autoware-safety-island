import subprocess, sys, struct
from pyocd.core.helpers import ConnectHelper
NM = "/home/aeon/.nros/sdk/arm-none-eabi-gcc/13.2-nros4/bin/arm-none-eabi-nm"
elf = sys.argv[1]
code = []; data = []; syms = {}
for l in subprocess.run([NM, "-S", "--defined-only", elf], capture_output=True, text=True).stdout.splitlines():
    p = l.split()
    if len(p) >= 4:
        a = int(p[0], 16); z = int(p[1], 16); syms[p[3]] = a
        (code if p[2] in "tTwW" else data).append((a & ~1 if p[2] in "tTwW" else a, z, p[3]))
def nm(tab, a):
    a2 = a & ~1 if tab is code else a
    for s, z, n in tab:
        if s <= a2 < s + max(z, 1): return f"{n}+{a2 - s:#x}"
    return hex(a)
with ConnectHelper.session_with_chosen_probe(target_override="s32k344", options={"connect_mode": "attach"}) as s:
    t = s.target
    t.halt()
    ths = [syms["z_main_thread"]] + [syms["posix_thread_pool"] + 320 * i for i in range(16)]
    for th in ths:
        name = bytes(t.read_memory_block8(th + 144, 16)).split(b"\0")[0].decode(errors="replace")
        state = t.read8(th + 16); prio = struct.unpack("b", bytes([t.read8(th + 14)]))[0]
        pend = t.read32(th + 8); psp = t.read32(th + 96); entry = t.read32(th + 124)
        if state == 0 and psp == 0: continue
        stk = []
        for k in range(200):
            v = t.read32(psp + 4 * k)
            if 0x400000 <= v < 0x800000:
                n = nm(code, v)
                if not n.startswith("0x"): stk.append(n)
        print(f"{th:#x} {name or '?'} entry={nm(code, entry)} prio={prio} state={state:#x} pended_on={nm(data, pend) if pend else 0}")
        print("     " + " < ".join(stk[:16]))
    t.resume()
