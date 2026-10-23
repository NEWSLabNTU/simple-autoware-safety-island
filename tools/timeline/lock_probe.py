#!/usr/bin/env python3
"""Read and decode island_lock_probe_record (src/zephyr_entry/src/island_lock_probe.c).

The measurement image (CONFIG_ISLAND_LOCK_PROBE) prices the executor lock on
target for nano-ros RFC-0108: the k_mutex lock cost at boot, every hold of
the executor's lock per holding thread (L_max), and each thread's stack
high-water.

  lock_probe.py read --elf build-board-lockprobe/zephyr/zephyr.elf [--out PREFIX]
  lock_probe.py decode DUMP.bin --elf ...

`read` attaches over SWD without halting (no other pyocd user may run).
"""
import argparse
import struct
import sys

RECORD = "island_lock_probe_record"
MAGIC = 0x4C4B5052
HOLDERS, STACKS, BUCKETS = 4, 16, 8
EDGES_US = [2, 5, 10, 50, 100, 500, 1000]
HEAD = "<4I"
BENCH = "<3I"
TAIL = "<5I"
HOLDER = "<Ii16s" + "10I" + f"{BUCKETS}I"
STACK = "<16s2I"


def symbols(elf, names):
    from elftools.elf.elffile import ELFFile
    out = {}
    with open(elf, "rb") as f:
        st = ELFFile(f).get_section_by_name(".symtab")
        for s in st.iter_symbols():
            if s.name in names and s.name not in out:
                out[s.name] = (s["st_value"], s["st_size"])
    return out


def cstr(b):
    return b.split(b"\0", 1)[0].decode("ascii", "replace")


def decode(blob):
    o = 0
    magic, hz, n, empty = struct.unpack_from(HEAD, blob, o); o += struct.calcsize(HEAD)
    if magic != MAGIC:
        raise SystemExit(f"lock_probe: bad magic {magic:#x} (not the probe image, or not booted)")
    bench = {}
    keys = ["kmutex_pair", "kmutex_nested", "rec_pair"]
    # nano-ros phase-509 P10: the exec_pair bench, in records 840 + 12 B on.
    if len(blob) >= 852:
        keys.append("exec_pair")
    for k in keys:
        mn, avg, mx = struct.unpack_from(BENCH, blob, o); o += struct.calcsize(BENCH)
        bench[k] = {"min": mn, "avg": avg, "max": mx}
    installed, overflow, depth_err, steady_ms, scans = struct.unpack_from(TAIL, blob, o); o += struct.calcsize(TAIL)
    holders = []
    for _ in range(HOLDERS):
        v = struct.unpack_from(HOLDER, blob, o); o += struct.calcsize(HOLDER)
        tid, prio, name = v[0], v[1], cstr(v[2])
        (holds, hmax, hmax_ms, shmax, shmax_ms, slo, shi, wmax, swmax, w5) = v[3:13]
        if tid == 0:
            continue
        holders.append({"tid": tid, "prio": prio, "name": name, "holds": holds,
                        "hold_max": hmax, "hold_max_ms": hmax_ms,
                        "steady_hold_max": shmax, "steady_hold_max_ms": shmax_ms,
                        "hold_sum": slo | (shi << 32), "wait_max": wmax,
                        "steady_wait_max": swmax, "waits_over_5us": w5,
                        "buckets": list(v[13:13 + BUCKETS])})
    stacks = []
    for _ in range(STACKS):
        name, size, used = struct.unpack_from(STACK, blob, o); o += struct.calcsize(STACK)
        if name[0]:
            stacks.append({"name": cstr(name), "size": size, "used": used})
    return {"hz": hz, "n": n, "empty": empty, "bench": bench, "installed": installed,
            "holder_overflow": overflow, "depth_errors": depth_err, "steady_ms": steady_ms,
            "stack_scans": scans, "holders": holders, "stacks": stacks}


def report(d):
    us = lambda c: c * 1e6 / d["hz"]
    L = [f"lock probe (island_lock_probe_record), {d['hz']} cycles/s, DWT read pair {d['empty']} cycles subtracted",
         f"  lock cost, {d['n']} pairs each (cycles min/avg/max, us avg):"]
    for k, label in (("kmutex_pair", "k_mutex lock+unlock, uncontended"),
                     ("kmutex_nested", "k_mutex nested pair (already held)"),
                     ("rec_pair", "nros_platform_mutex_rec lock+unlock"),
                     ("exec_pair", "nros_zephyr_exec_lock+unlock (P10)")):
        b = d["bench"].get(k)
        if b is None or b["min"] == 0 and b["avg"] == 0:
            continue
        L.append(f"    {label:38s} {b['min']}/{b['avg']}/{b['max']}  ({us(b['avg']):.3f} us)")
    L.append(f"  executor lock wrapped: {'yes' if d['installed'] else 'NO'}; holder overflow {d['holder_overflow']}, "
             f"depth errors {d['depth_errors']}; steady from {d['steady_ms']} ms")
    edges = ["<2", "2-5", "5-10", "10-50", "50-100", "100-500", "500-1000", ">=1000"]
    for h in d["holders"]:
        avg = h["hold_sum"] / h["holds"] if h["holds"] else 0
        L.append(f"  holder {h['name'] or hex(h['tid'])} prio {h['prio']}: holds {h['holds']}, avg {us(avg):.3f} us, "
                 f"max {us(h['hold_max']):.1f} us (uptime {h['hold_max_ms']} ms), "
                 f"steady max {us(h['steady_hold_max']):.1f} us (uptime {h['steady_hold_max_ms']} ms); "
                 f"wait max {us(h['wait_max']):.1f} us, steady {us(h['steady_wait_max']):.1f} us, "
                 f"waits over 5 us {h['waits_over_5us']}")
        L.append("    holds by us: " + ", ".join(f"{e} {c}" for e, c in zip(edges, h["buckets"]) if c))
    L.append(f"  stack high-water ({d['stack_scans']} scans, 1 s apart):")
    for s in sorted(d["stacks"], key=lambda s: s["name"]):
        L.append(f"    {s['name']:16s} {s['used']:6d} of {s['size']:6d} B ({100.0 * s['used'] / s['size'] if s['size'] else 0:.0f}%), "
                 f"{s['size'] - s['used']} spare")
    return "\n".join(L) + "\n"



def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["read", "decode"])
    ap.add_argument("dump", nargs="?")
    ap.add_argument("--elf", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    addr, size = symbols(a.elf, {RECORD}).get(RECORD, (None, None))
    if addr is None:
        sys.exit(f"lock_probe: {a.elf} has no {RECORD} (built without CONFIG_ISLAND_LOCK_PROBE)")
    if a.cmd == "decode":
        blob = open(a.dump, "rb").read()
    else:
        from pyocd.core.helpers import ConnectHelper
        s = ConnectHelper.session_with_chosen_probe(
            target_override="s32k344", connect_mode="attach", options={"frequency": 4000000})
        s.open()
        try:
            blob = bytes(s.board.target.read_memory_block8(addr, size))
        finally:
            s.close()
    text = report(decode(blob))
    if a.out:
        open(a.out + ".bin", "wb").write(blob)
        open(a.out + ".txt", "w").write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
