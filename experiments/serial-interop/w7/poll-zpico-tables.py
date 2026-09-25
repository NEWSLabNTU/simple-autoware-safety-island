# phase7-W7: poll island RAM over SWD while the image registers (pyocd API, halt-mode connect,
# hardware reset, resume). Addresses are from the flashed ELF sha256 4dbf4163...d1d094 (image
# 828ea599...); re-derive them with arm-zephyr-eabi-nm / gdb for any other build.
import time
from pyocd.core.helpers import ConnectHelper
from pyocd.core.target import Target
B=0x20405d50
def cnt(t, off, n, sz, act):
    blk=bytes(t.read_memory_block8(B+off, n*sz))
    return sum(1 for i in range(n) if blk[i*sz+act])
with ConnectHelper.session_with_chosen_probe(target_override='s32k344', options={'connect_mode':'halt'}) as s:
    t=s.target
    t.reset(Target.ResetType.HARDWARE)
    if t.is_halted(): t.resume()
    t0=time.time(); last=None; log=[]
    while time.time()-t0 < 2.0:
        cur=(cnt(t,0x1c,14,80,76), cnt(t,0x1a80,31,32,28), cnt(t,0x6b8,58,16,12), t.read32(0x20431840))
        if cur!=last:
            log.append((round(time.time()-t0,3),)+cur); last=cur
    for l in log: print("t=%.3fs publishers=%d/14 queryables=%d/31 liveliness=%d/58 next_adv_eid=%d" % l)
