#!/usr/bin/env python3
"""phase8-W2: poll the island's zenoh-pico serial link state over SWD while it runs.

Attach mode (no halt, no reset). Addresses from the ELF (nm); struct offsets for
Zephyr 4.4 / this nano-ros pin, read with arm-none-eabi-gdb from the d8q ELF:
  k_thread: base.pended_on 0x8, prio 0xe, thread_state 0x10, usage.total 0x30,
            callee_saved.psp 0x60, next_thread 0x8c, name 0x90[32]
  _kernel.threads = &_kernel+0x2c ; _kernel.usage.total = &_kernel+0x30
  ring_buf (20 B): buffer, put{head,tail,base u16}, get{head,tail,base u16}, size
  zpico_session: session._rc._val at +0x10; subscribers[11] x 52 B at +0x47c,
            ring ptr at entry+48; ring desc: head ptr +28, tail ptr +32
  _z_session_t._tp at +0xc; transport read_task_running +0x6c, lease +0x6d
Usage: swd_poll.py ELF SECONDS PERIOD [--threads]
"""
import subprocess, sys, time, struct, os
from pyocd.core.helpers import ConnectHelper

NM = "/home/aeon/.nros/sdk/arm-none-eabi-gcc/13.2-nros4/bin/arm-none-eabi-nm"
elf, secs, period = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
show_threads = "--threads" in sys.argv
syms = {}
for line in subprocess.run([NM, "-S", elf], capture_output=True, text=True).stdout.splitlines():
    p = line.split()
    if len(p) >= 3:
        syms.setdefault(p[-1], int(p[0], 16))
def sym(n): return syms[n]
LPUART2 = 0x40330000
wanted = ["_z_serial_rx_ring", "_z_serial_rx_ring_full", "g_sessions", "_kernel"]
for w in wanted: sym(w)
# optional W2 counters (present only in instrumented images)
opt = [s for s in syms if s.startswith("_z_serial_stat")]

def rd32(t, a): return t.read32(a)
def rd8(t, a): return t.read8(a)

def threads(t):
    out = []
    th = rd32(t, sym("_kernel") + 0x2c); n = 0
    while th and n < 32:
        name = bytes(t.read_memory_block8(th + 0x90, 32)).split(b"\0")[0].decode(errors="replace")
        prio = struct.unpack("b", bytes([rd8(t, th + 0xe)]))[0]
        state = rd8(t, th + 0x10)
        pend = rd32(t, th + 0x8)
        lo, hi = rd32(t, th + 0x30), rd32(t, th + 0x34)
        out.append((th, name, prio, state, pend, (hi << 32) | lo))
        th = rd32(t, th + 0x8c); n += 1
    return out

def snapshot(t):
    r = bytes(t.read_memory_block8(sym("_z_serial_rx_ring"), 20))
    buf, ph, pt, pb, gh, gt, gb, size = struct.unpack("<IHHHHHHI", r)
    full = rd8(t, sym("_z_serial_rx_ring_full"))
    stat = rd32(t, LPUART2 + 0x14); fifo = rd32(t, LPUART2 + 0x28); water = rd32(t, LPUART2 + 0x2c)
    ctrl = rd32(t, LPUART2 + 0x18)
    gs = sym("g_sessions")
    sval = rd32(t, gs + 0x10)
    rt = lt = -1; snr = snb = -1
    if sval:
        rt = rd8(t, sval + 0xc + 0x6c); lt = rd8(t, sval + 0xc + 0x6d)
        node = rd32(t, sval + 0xc + 0x98)
        if node:
            snr = rd32(t, node + 4 + 0x60); snb = rd32(t, node + 4 + 0x64)
    tails = []
    for i in range(11):
        e = gs + 0x47c + i * 52
        active = rd8(t, e + 0x1c) if False else None
        ring = rd32(t, e + 48)
        if ring:
            tp = rd32(t, ring + 32); hp = rd32(t, ring + 28)
            tails.append((rd32(t, tp), rd32(t, hp), rd32(t, ring + 4)))
        else:
            tails.append(None)
    gc = gs + 0x929 - 1 if False else None
    gcl = rd32(t, sym("g_sessions") + 0x1928 + 4096 - 0x1928 + 0x928) if False else None
    kus = rd32(t, sym("_kernel") + 0x30) | (rd32(t, sym("_kernel") + 0x34) << 32)
    extra = {s: rd32(t, sym(s)) for s in opt}
    return dict(ring_put_tail=pt, ring_get_head=gh, ring_used=(pt - gh) & 0xffff, ring_size=size,
                ring_full=full, stat=stat, fifo=fifo, water=water, ctrl=ctrl,
                read_task=rt, lease_task=lt, snr=snr, snb=snb, put=pt, subs=tails, kusage=kus, extra=extra)

with ConnectHelper.session_with_chosen_probe(target_override="s32k344", options={"connect_mode": "attach"}) as s:
    t = s.target
    if "--reset" in sys.argv:
        from pyocd.core.target import Target
        t.reset(Target.ResetType.HARDWARE)
        if t.is_halted(): t.resume()
        print(f"{time.time():.3f} RESET issued", flush=True)
    t0 = time.time()
    # graph cache: g_sessions.graph_cache at +0x928 (buf[4096], len, entry_count, dropped)
    gcb = sym("g_sessions") + 0x928 + 4096
    while time.time() - t0 < secs:
        ts = time.time()
        try:
            sn = snapshot(t)
            gcl, gce, gcd = rd32(t, gcb), rd32(t, gcb + 4), rd32(t, gcb + 8)
        except Exception as ex:
            print(f"{ts:.3f} read error {ex}", flush=True); time.sleep(period); continue
        st = sn["stat"]
        flags = []
        for bit, nm in ((19, "OR"), (18, "NF"), (17, "FE"), (16, "PF"), (21, "RDRF"), (20, "IDLE"), (23, "TDRE"), (22, "TC"), (24, "RAF")):
            if st & (1 << bit): flags.append(nm)
        subs = " ".join("-" if x is None else f"{x[0]}" for x in sn["subs"])
        ex = " ".join(f"{k.replace('_z_serial_stat_','')}={v}" for k, v in sn["extra"].items())
        print(f"{time.strftime('%H:%M:%S', time.localtime(ts))}.{int(ts*1000)%1000:03d} "
              f"readtask={sn['read_task']} lease={sn['lease_task']} sn_rel={sn['snr']} sn_be={sn['snb']} put={sn['put']} ring={sn['ring_used']}/{sn['ring_size']} "
              f"rfull={sn['ring_full']} STAT={st:08x}[{','.join(flags)}] FIFO={sn['fifo']:08x} "
              f"gc(len={gcl},n={gce},drop={gcd}) tails=[{subs}] kus={sn['kusage']} {ex}", flush=True)
        if show_threads:
            for (th, name, prio, state, pend, us) in threads(t):
                print(f"    th {th:08x} {name:24s} prio={prio:4d} state={state:02x} pended_on={pend:08x} usage={us}", flush=True)
        dt = period - (time.time() - ts)
        if dt > 0: time.sleep(dt)
