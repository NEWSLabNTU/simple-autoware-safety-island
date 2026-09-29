#!/usr/bin/env python3
"""phase8-W10: poll the island's serial link over SWD while it runs (attach, no halt).

  poll.py ELF OFFSETS_JSON SECONDS PERIOD [--reset-at s1,s2,...] [--threads-every N]

Every symbol is read from the ELF (nm); struct offsets come from offsets.sh (gdb).
--reset-at: issue a hardware reset through the same probe session at these offsets
(seconds from start; 0 = at once). Each reset prints a RESET line with wall time.
Prints one line per period: the zenoh-pico serial counters (_z_zephyr_serial_stats),
the rejected-message counter (_z_rx_rejections), the RX ring fill, every
subscription ring's tail (monotonic count of samples accepted), and optionally every
thread's CPU usage.
"""
import json, struct, subprocess, sys, time
from pyocd.core.helpers import ConnectHelper

NM = "/home/aeon/.nros/sdk/arm-none-eabi-gcc/13.2-nros4/bin/arm-none-eabi-nm"
elf, offp, secs, period = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
resets = []
if "--reset-at" in sys.argv:
    resets = [float(x) for x in sys.argv[sys.argv.index("--reset-at") + 1].split(",") if x != ""]
th_every = 0
if "--threads-every" in sys.argv:
    th_every = int(sys.argv[sys.argv.index("--threads-every") + 1])
O = json.load(open(offp))
syms, byaddr, sizes = {}, {}, {}
for line in subprocess.run([NM, "-S", elf], capture_output=True, text=True).stdout.splitlines():
    p = line.split()
    if len(p) >= 3:
        a = int(p[0], 16)
        syms.setdefault(p[-1], a)
        if len(p) >= 4: sizes.setdefault(p[-1], int(p[1], 16))
        byaddr.setdefault(a & ~1, p[-1])
STATS = ["rx_bytes", "rx_frames", "rx_bad_frames", "rx_partial", "overruns", "ring_overflows",
         "ring_high_water", "tx_bytes", "tx_frames", "tx_busy_cycles"]
extra_stats = []
if "_z_zephyr_serial_tx_stats" in syms:
    extra_stats = ["tx_irq_bytes", "tx_waits", "tx_timeouts", "tx_ring_high_water"]

def snap(t):
    d = {"tick": t.read32(syms["curr_tick"])}
    if "_z_zephyr_serial_stats" in syms:
        nw = sizes.get("_z_zephyr_serial_stats", 40) // 4
        v = struct.unpack(f"<{nw}I", bytes(t.read_memory_block8(syms["_z_zephyr_serial_stats"], 4 * nw)))
        d.update(zip(STATS + ["framing_errors", "noise_errors", "parity_errors"], v))
    if extra_stats:
        v = struct.unpack("<4I", bytes(t.read_memory_block8(syms["_z_zephyr_serial_tx_stats"], 16)))
        d.update(zip(extra_stats, v))
    if "_z_rx_rejections" in syms:
        c, e = struct.unpack("<Ii", bytes(t.read_memory_block8(syms["_z_rx_rejections"], 8)))
        d["rej"] = c; d["rej_err"] = e
    r = bytes(t.read_memory_block8(syms["_z_serial_rx_ring"], 20))
    buf, ph, pt, pb, gh, gt, gb, size = struct.unpack("<IHHHHHHI", r)
    d["ring"] = (pt - gh) & 0xffff; d["ring_size"] = size
    gs = syms["g_sessions"]
    tails = []
    for i in range(O["sub_n"]):
        e = gs + O["subs_off"] + i * O["sub_size"]
        ring = t.read32(e + (O["sub_ring_off"] - O["subs_off"]))
        tails.append(t.read32(t.read32(ring + O["ring_tail_off"])) if ring else -1)
    d["tails"] = tails
    return d

def threads(t):
    out = []
    th = t.read32(syms["_kernel"] + O["k_threads"]); n = 0
    while th and n < 32:
        name = bytes(t.read_memory_block8(th + O["th_name"], 16)).split(b"\0")[0].decode(errors="replace")
        if not name:
            name = "<" + byaddr.get(t.read32(th + O["th_entry"]) & ~1, "?") + ">"
        prio = struct.unpack("b", bytes([t.read8(th + O["th_prio"])]))[0]
        us = t.read32(th + O["th_usage"]) | (t.read32(th + O["th_usage"] + 4) << 32)
        out.append((name, prio, us))
        th = t.read32(th + O["th_next"]); n += 1
    return out

def ts():
    x = time.time()
    return f"{time.strftime('%H:%M:%S', time.localtime(x))}.{int(x*1000)%1000:03d}"

t0 = time.time(); k = 0
pending = sorted(resets)
def do_reset():
    a = time.time()
    r = subprocess.run(["pyocd", "reset", "-t", "s32k344"], capture_output=True, text=True)
    print(f"{ts()} RESET issued wall={a:.3f} done={time.time():.3f} rc={r.returncode}", flush=True)
while time.time() - t0 < secs:
    if pending and time.time() - t0 >= pending[0]:
        pending.pop(0); do_reset()
    until = t0 + (pending[0] if pending else secs)
    with ConnectHelper.session_with_chosen_probe(target_override="s32k344", options={"connect_mode": "attach"}) as s:
        t = s.target
        while time.time() < until and time.time() - t0 < secs:
            start = time.time()
            try:
                d = snap(t)
                tails = " ".join(str(x) for x in d.pop("tails"))
                kv = " ".join(f"{a}={b}" for a, b in d.items())
                print(f"{ts()} wall={start:.3f} {kv} tails=[{tails}]", flush=True)
                if th_every and k % th_every == 0:
                    kus = t.read32(syms["_kernel"] + O["k_usage"]) | (t.read32(syms["_kernel"] + O["k_usage"] + 4) << 32)
                    print(f"    kus={kus} " + " ".join(f"{n}:{p}:{u}" for n, p, u in threads(t)), flush=True)
            except Exception as ex:
                print(f"{ts()} read error {ex}", flush=True)
            k += 1
            dt = min(period - (time.time() - start), until - time.time())
            if dt > 0:
                time.sleep(dt)
