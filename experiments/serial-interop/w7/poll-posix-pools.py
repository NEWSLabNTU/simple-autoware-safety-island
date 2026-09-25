# phase7-W7: poll island RAM over SWD while the image registers (pyocd API, halt-mode connect,
# hardware reset, resume). Addresses are from the flashed ELF sha256 4dbf4163...d1d094 (image
# 828ea599...); re-derive them with arm-zephyr-eabi-nm / gdb for any other build.
import time, sys
from pyocd.core.helpers import ConnectHelper
MUT=0x20425204; COND=0x20425140; EID=0x20431840; HB=0x20425acc
def pc(ws): return sum(bin(w).count('1') for w in ws)
with ConnectHelper.session_with_chosen_probe(target_override='s32k344', options={'connect_mode':'halt'}) as s:
    t=s.target
    from pyocd.core.target import Target; t.reset(Target.ResetType.HARDWARE); t.resume() if t.is_halted() else None
    t0=time.time(); last=None; mx=0; log=[]
    while time.time()-t0 < 4.0:
        m=t.read_memory_block32(MUT,2); c=t.read_memory_block32(COND,1)[0]; e=t.read32(EID)
        st=t.read32(HB)
        cur=(pc(m), bin(c).count('1'), e, st)
        mx=max(mx,cur[0])
        if cur!=last:
            log.append((round(time.time()-t0,3),)+cur); last=cur
    for l in log: print("t=%.3fs mutex_used=%d cond_used=%d next_adv_eid=%d hb_seq=%d" % l)
    print("max mutex_used", mx)
