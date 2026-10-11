#!/usr/bin/env python3
"""DIAG (spin latency): read and decode island_spin_diag over SWD.

  spin_diag.py read   --elf <zephyr.elf> --out <prefix>   attach, no halt
  spin_diag.py decode --elf <zephyr.elf> <prefix>.bin

The struct is src/safety_island_tracing/include/island_spin_diag.h
(CONFIG_ISLAND_SPIN_DIAG): every spin_once-to-spin_once interval of the
executor thread, its lateness against 10 ms, and for each interval at least
2 ms late the five segments (S0 entry->wait, S1 wait+drive_io, S2 dispatch,
S3 post rules, S4 caller loop) charged to the spin thread / idle / rest.
"""
import argparse
import os
import struct
import subprocess
import sys

SYM = "island_spin_diag"
EXTRA = ["_z_zephyr_serial_stats", "_z_zephyr_serial_tx_stats"]
SEGS = ["S0 pre", "S1 wait", "S2 disp", "S3 post", "S4 loop"]
REC = ["uptime_ms", "interval_us"] + [f"wall{i}" for i in range(5)] + [f"main{i}" for i in range(5)] \
    + [f"idle{i}" for i in range(5)] + ["park_bound_us", "idle_path", "ncb", "ntake", "cb_slot", "cb_wall_us",
                                        "cb_main_us", "cb_idle_us", "cb_off_us", "lk_main_n", "lk_main_us",
                                        "lk_main_max_us", "lk_main_max_ra", "lk_main_max_m", "lk_oth_n",
                                        "lk_oth_us", "lk_oth_max_us", "lk_oth_max_ra", "isr_us", "isr_n",
                                        "tt0", "tt1", "tt2", "tu0", "tu1", "tu2"]
BINS, RING, NTHR = 40, 48, 16
ADDR2LINE = ("/home/aeon/.nros/sdk/zephyr-sdk-1-0-1/1.0.1/zephyr-sdk-1.0.1/gnu/arm-zephyr-eabi/bin/"
             "arm-zephyr-eabi-addr2line")


def symbols(elf, names):
    from elftools.elf.elffile import ELFFile
    out = {}
    with open(elf, "rb") as f:
        for s in ELFFile(f).get_section_by_name(".symtab").iter_symbols():
            if s.name in names and s.name not in out:
                out[s.name] = (s["st_value"], s["st_size"])
    return out


def fn_at(elf, addr, cache={}):
    if not addr:
        return "-"
    if addr not in cache:
        try:
            r = subprocess.run([ADDR2LINE, "-f", "-s", "-e", elf, hex(addr & ~1)], capture_output=True, text=True)
            lines = r.stdout.split()
            cache[addr] = f"{lines[0]}@{lines[1]}" if len(lines) >= 2 else hex(addr)
        except OSError:
            cache[addr] = hex(addr)
    return cache[addr]


def decode(elf, blob):
    w = lambda off, n: struct.unpack_from(f"<{n}I", blob, off)
    magic, rec_words, spins, late, max_late = w(0, 5)
    if magic != 0x31474453:
        return f"spin_diag: bad magic {magic:#x} (no spin yet?)\n"
    if rec_words != len(REC):
        return f"spin_diag: record is {rec_words} words, decoder knows {len(REC)}\n"
    off = 20
    hist = w(off, BINS); off += 4 * BINS
    segmax = w(off, 5); off += 20
    ring_next, nthr = w(off, 2); off += 8
    thr = {}
    for i in range(NTHR):
        tid, prio = w(off, 2)
        name = blob[off + 8:off + 24].split(b"\0")[0].decode(errors="replace")
        off += 24
        if i < nthr:
            thr[tid] = f"{name or hex(tid)}(p{prio - (1 << 32) if prio >= 1 << 31 else prio})"
    recsz = 4 * rec_words

    def rec(o):
        return dict(zip(REC, w(o, rec_words)))
    worst = rec(off); off += recsz
    ring = [rec(off + i * recsz) for i in range(RING)]
    out = [f"spins={spins} late(>=2ms)={late} max_late_us={max_late}",
           "lateness histogram (ms bin: count): " + " ".join(f"{i}:{c}" for i, c in enumerate(hist) if c),
           "segment max wall us: " + " ".join(f"{SEGS[i]}={segmax[i]}" for i in range(5)),
           "threads: " + " ".join(f"{hex(t)}={n}" for t, n in thr.items())]
    n = min(ring_next, RING)
    order = [(ring_next - n + i) % RING for i in range(n)]

    def fmt(r, tag):
        late_us = max(0, r["interval_us"] - 10000)
        s = [f"{tag} t={r['uptime_ms']}ms interval={r['interval_us']}us late={late_us}us park_bound={r['park_bound_us']}us"
             f" idle_path={r['idle_path']} ncb={r['ncb']} ntake={r['ntake']} isr={r['isr_us']}us/{r['isr_n']}"]
        for i in range(5):
            wl, mn, idl = r[f"wall{i}"], r[f"main{i}"], r[f"idle{i}"]
            s.append(f"    {SEGS[i]}: wall={wl:6d} spin={mn:6d} idle={idl:6d} other={wl - mn - idl:6d}")
        s.append(f"    longest cb: slot={r['cb_slot']} wall={r['cb_wall_us']} spin={r['cb_main_us']} "
                 f"idle={r['cb_idle_us']} at +{r['cb_off_us']}us")
        s.append(f"    spin lock waits: n={r['lk_main_n']} total={r['lk_main_us']}us max={r['lk_main_max_us']}us "
                 f"in {fn_at(elf, r['lk_main_max_ra'])} m={r['lk_main_max_m']:#x}")
        s.append(f"    other lock waits: n={r['lk_oth_n']} total={r['lk_oth_us']}us max={r['lk_oth_max_us']}us "
                 f"in {fn_at(elf, r['lk_oth_max_ra'])}")
        s.append("    other threads: " + " ".join(f"{thr.get(r[f'tt{k}'], hex(r[f'tt{k}']))}={r[f'tu{k}']}us"
                                                  for k in range(3) if r[f"tt{k}"]))
        return "\n".join(s)
    out.append(fmt(worst, "WORST"))
    for i in order:
        out.append(fmt(ring[i], f"late#{i}"))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["read", "decode"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--elf", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    syms = symbols(a.elf, {SYM, *EXTRA})
    if a.cmd == "decode":
        sys.stdout.write(decode(a.elf, open(a.arg, "rb").read()))
        return 0
    from pyocd.core.helpers import ConnectHelper
    s = ConnectHelper.session_with_chosen_probe(target_override="s32k344", connect_mode="attach",
                                                options={"frequency": 4000000})
    s.open()
    try:
        t = s.board.target
        addr, size = syms[SYM]
        blob = bytes(t.read_memory_block8(addr, size))
        extra = {n: bytes(t.read_memory_block8(*syms[n])) for n in EXTRA if n in syms}
    finally:
        s.close()
    open(a.out + ".bin", "wb").write(blob)
    text = decode(a.elf, blob)
    for n, b in extra.items():
        text += f"{n}: " + " ".join(str(x) for x in struct.unpack(f"<{len(b) // 4}I", b)) + "\n"
    open(a.out + ".txt", "w").write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
