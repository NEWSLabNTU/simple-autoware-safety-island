#!/usr/bin/env python3
"""The island's runtime contract violations, off the board (phase9-W4).

  violations.py read     --elf <zephyr.elf> --out <dir>/violations   attach, no halt
  violations.py decode   --elf <zephyr.elf> <dir>/violations.bin [--words <json>]
  violations.py overrun  --elf <zephyr.elf> <ms>                     the debug hook
  violations.py fault-overrun --elf <zephyr.elf> <ms>|stall          the same, on the fault tick
  violations.py spin-stall --elf <zephyr.elf>                        stall the spin (SWT0 bench)
  violations.py supervisor --elf <zephyr.elf> [--out <prefix>]       the supervisor record
  violations.py --dry-run read|overrun ...                           resolve, touch nothing

nano-ros (phase-474 I1) writes every STORED violation, at detection, into the
SWD record `NROS_VIOLATION_RECORD` (`CONFIG_NROS_BOOT_REPORT`): a versioned,
all-u32 header (total, head, dropped, suppressed_before_arm, armed) and the
latest `capacity` slots (seq, rule code, endpoint FNV-1a, measured, declared,
fqn address and length). The record is never drained. This reads it by
symbol, with the island's two arming words beside it
(`island_monitors_armed_uptime_ms`, `island_monitors_armed_via`,
mrm_handler_core.cpp), and decodes it with the PINNED nano-ros decoder
(third-party/nano-ros/scripts/read-violation-record.py: layout, rule table,
the fqn text out of the ELF's rodata). An endpoint the ELF cannot name is
named from markers.json's endpoint hashes (the contract's endpoint refs).
It replaces phase8-W31's vscan.py, which scanned RAM for (ptr, len) pairs
naming a rule literal because the ring had no fixed address.

tools/timeline/readout.py reads the same words inside its halted read at the
end of every run-board.sh act and writes <run dir>/violations.txt with
`report()` below, so every act's run directory has one.

Two latency rules, two quantities (phase10-B3). `max-latency-runtime` is ONE
dispatch that published the endpoint (callback entry to exit, ms).
`route-latency-runtime` is an input-triggered path's route: from the take of
its trigger input to the end of the dispatch that published the endpoint, the
wait for the next tick included (ms; the contract's `call_mrm` 149 ms on the
handler's mrm_state and takeover_request_state). Each slot line says which.

`overrun N` writes N into `island_debug_overrun_ms` (CONFIG_ISLAND_DEBUG_OVERRUN,
Kconfig.island_trace): the handler's next RUN tick busy-waits N ms, once.

phase11-S7. `fault-overrun N` writes N into `island_debug_fault_overrun_ms`:
the next tick that runs call_mrm (the fault tick) busy-waits N ms right after
its ENTRY, before the reaction, so the route itself is late; `stall` writes
0xffffffff, a busy-wait that never ends. `spin-stall` writes
`island_debug_spin_stall` (CONFIG_ISLAND_DEBUG_SPIN_STALL, not in the gate
image): the next spin never ends, with no route pending -- SWT0's case.
`supervisor` reads `island_supervisor_record` (CONFIG_ISLAND_SUPERVISOR,
src/zephyr_entry/src/island_supervisor.c; attach, no halt): whether the
safe-state output is latched, by what and when, each route's arms, dones and
deadline verdicts, SWT0's state and the longest feed-to-feed gap.
readout.py reads it in the halted read of every act into supervisor.txt.
"""
import argparse
import importlib.util
import json
import os
import struct
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NROS_SCRIPTS = os.path.join(ROOT, "third-party/nano-ros/scripts")
TABLE = os.path.join(ROOT, "src/safety_island_tracing/markers.json")
RECORD = "NROS_VIOLATION_RECORD"
ARM_WORDS = ["island_monitors_armed_uptime_ms", "island_monitors_armed_via",
             "island_trace_hb_last_uptime_ms"]
OVERRUN = "island_debug_overrun_ms"
FAULT_OVERRUN = "island_debug_fault_overrun_ms"
SPIN_STALL = "island_debug_spin_stall"
SUPERVISOR = "island_supervisor_record"
STALL = 0xFFFFFFFF
# island_supervisor.c's record, all u32: the header, then `routes` routes.
SUP_HEADER = ["magic", "latched", "latch_cause", "latch_uptime_us", "wakes", "timer_expiries",
              "swt_started", "swt_timeout_ms", "swt_fires", "swt_fire_uptime_us", "swt_errors",
              "spins", "spin_gap_max_us", "spin_gap_max_at_ms", "gpio_errors", "routes"]
SUP_ROUTE = ["armed", "due_ms", "arms", "dones", "fired", "fire_due_ms", "fire_verdict_us"]
SUP_MAGIC = 0x56505553
SUP_CAUSE = {0: "-", 1: "route deadline", 2: "SWT0 first timeout"}
SUP_ROUTE_NAME = {0: "hpc_loss reaction (mrm_handler/call_mrm)"}
ARM_VIA = {0: "not armed", 1: "INIT_DONE", 2: "init failure cleared"}
# phase10-B3: what `measured` is, for the rules whose name does not say it.
RULE_NOTE = {
    "max-latency-runtime": "one dispatch, ms",
    "route-latency-runtime": "take of the trigger to the output, ms",
}


def nros_decoder():
    """The pinned nano-ros decoder module (read-violation-record.py)."""
    path = os.path.join(NROS_SCRIPTS, "read-violation-record.py")
    if not os.path.exists(path):
        sys.exit(f"violations: no {path} -- the nano-ros pin predates phase-474 I1")
    spec = importlib.util.spec_from_file_location("read_violation_record", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def symbols(elf, names):
    from elftools.elf.elffile import ELFFile
    out = {}
    with open(elf, "rb") as f:
        st = ELFFile(f).get_section_by_name(".symtab")
        if st is None:
            sys.exit(f"violations: {elf} has no symbol table")
        for s in st.iter_symbols():
            if s.name in names and s.name not in out:
                out[s.name] = (s["st_value"], s["st_size"])
    return out


def endpoint_hashes():
    try:
        return json.load(open(TABLE)).get("nros", {}).get("endpoint_hashes", {})
    except OSError:
        return {}


def report(elf, blob, words=None):
    """The readout as text: header counts, the arming words, the slots newest
    first. `blob` is the record's bytes, `words` the arming words read beside
    it (missing ones are left out)."""
    dec = nros_decoder()
    hdr, slots = dec.decode(blob)
    lines = [f"violation record ({RECORD}, layout v{hdr['version']}, capacity {hdr['capacity']}):",
             f"  total={hdr['total']} dropped={hdr['dropped']} "
             f"suppressed_before_arm={hdr['suppressed_before_arm']} armed={hdr['armed']}"]
    words = words or {}
    if "island_monitors_armed_via" in words:
        via = words["island_monitors_armed_via"]
        up = words.get("island_monitors_armed_uptime_ms", 0)
        lines.append(f"  handler armed the monitors: {ARM_VIA.get(via, f'via#{via}')}"
                     + (f" at uptime {up} ms" if via else ""))
    if "island_trace_hb_last_uptime_ms" in words:
        lines.append(f"  read at uptime ~{words['island_trace_hb_last_uptime_ms']} ms (last trace heartbeat)")
    if hdr["total"] == 0:
        lines.append("  EMPTY: no violation stored since boot")
    helpers = None
    try:
        helpers = dec._boot_report_helpers()
    except Exception:  # noqa: BLE001 -- the ELF names are a convenience
        helpers = None
    hashes = endpoint_hashes()
    for seq, s in dec.newest_first(hdr, slots):
        if s is None:
            lines.append(f"  #{seq}: (being written or overwritten)")
            continue
        fqn = None
        if helpers is not None and s["fqn_len"]:
            raw = helpers.elf_bytes(Path(elf), s["fqn_addr"], s["fqn_len"])
            fqn = raw.decode("utf-8", "replace") if raw is not None else None
        if fqn is None:
            fqn = hashes.get(f"{s['fqn_hash']:08x}", f"fqn#{s['fqn_hash']:08x}")
        rule = dec.rule_name(s["rule"]) or f"rule#{s['rule']}"
        note = RULE_NOTE.get(rule)
        lines.append(f"  #{seq}: {rule} {fqn} "
                     f"measured={s['measured']} declared={s['declared']}"
                     + (f" ({note})" if note else ""))
    return "\n".join(lines) + "\n"


def supervisor_decode(blob):
    n = len(blob) // 4
    w = struct.unpack(f"<{n}I", blob[:n * 4])
    hdr = dict(zip(SUP_HEADER, w[:len(SUP_HEADER)]))
    routes = []
    for i in range(hdr.get("routes", 0)):
        off = len(SUP_HEADER) + i * len(SUP_ROUTE)
        if off + len(SUP_ROUTE) <= n:
            routes.append(dict(zip(SUP_ROUTE, w[off:off + len(SUP_ROUTE)])))
    hdr["route"] = routes
    return hdr


def supervisor_report(blob):
    d = supervisor_decode(blob)
    if d.get("magic") != SUP_MAGIC:
        return f"supervisor record ({SUPERVISOR}): magic {d.get('magic', 0):#010x}, not initialised\n"
    lines = [f"supervisor record ({SUPERVISOR}):"]
    if d["latched"]:
        lines.append(f"  safe-state output LATCHED by {SUP_CAUSE.get(d['latch_cause'], d['latch_cause'])} "
                     f"at uptime {d['latch_uptime_us'] / 1000:.3f} ms")
    else:
        lines.append("  safe-state output not driven")
    lines.append(f"  reaction thread wakes={d['wakes']} timer expiries={d['timer_expiries']} "
                 f"gpio_errors={d['gpio_errors']}")
    if d["swt_started"]:
        lines.append(f"  SWT0 running, timeout {d['swt_timeout_ms']} ms; first-timeout callbacks {d['swt_fires']}"
                     + (f" (first at uptime {d['swt_fire_uptime_us'] / 1000:.3f} ms)" if d["swt_fires"] else "")
                     + f"; errors {d['swt_errors']}")
    else:
        lines.append(f"  SWT0 not running (errors {d['swt_errors']})")
    lines.append(f"  spins={d['spins']}; longest feed-to-feed gap {d['spin_gap_max_us'] / 1000:.3f} ms "
                 f"(ended at uptime {d['spin_gap_max_at_ms']} ms)")
    for i, r in enumerate(d["route"]):
        name = SUP_ROUTE_NAME.get(i, f"route {i}")
        line = (f"  route {i} {name}: arms={r['arms']} dones={r['dones']} deadline verdicts={r['fired']}"
                f"; {'armed, due at ' + str(r['due_ms']) + ' ms' if r['armed'] else 'not armed'}")
        if r["fired"]:
            line += (f"; first verdict at {r['fire_verdict_us'] / 1000:.3f} ms for the due at "
                     f"{r['fire_due_ms']} ms ({r['fire_verdict_us'] / 1000 - r['fire_due_ms']:+.3f} ms)")
        lines.append(line)
    return "\n".join(lines) + "\n"


def board():
    from pyocd.core.helpers import ConnectHelper
    s = ConnectHelper.session_with_chosen_probe(
        target_override="s32k344", connect_mode="attach", options={"frequency": 4000000})
    s.open()
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["read", "decode", "overrun", "fault-overrun", "spin-stall", "supervisor"])
    ap.add_argument("arg", nargs="?", help="decode: the record dump; overrun: ms; fault-overrun: ms or stall")
    ap.add_argument("--elf", required=True)
    ap.add_argument("--out", help="read: output prefix (<out>.bin, <out>.txt)")
    ap.add_argument("--words", help="decode: a JSON file of the arming words read beside the dump")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_intermixed_args()
    syms = symbols(a.elf, {RECORD, OVERRUN, FAULT_OVERRUN, SPIN_STALL, SUPERVISOR, *ARM_WORDS})
    if a.cmd == "supervisor":
        if SUPERVISOR not in syms:
            sys.exit(f"violations: {a.elf} has no {SUPERVISOR} (built without CONFIG_ISLAND_SUPERVISOR)")
        addr, size = syms[SUPERVISOR]
        print(f"violations: read {SUPERVISOR} @ {addr:#010x}, {size} B (attach, no halt)")
        if a.dry_run:
            return 0
        s = board()
        try:
            blob = bytes(s.board.target.read_memory_block8(addr, size))
        finally:
            s.close()
        text = supervisor_report(blob)
        if a.out:
            open(a.out + ".bin", "wb").write(blob)
            open(a.out + ".txt", "w").write(text)
        sys.stdout.write(text)
        return 0
    if a.cmd in ("fault-overrun", "spin-stall"):
        word = FAULT_OVERRUN if a.cmd == "fault-overrun" else SPIN_STALL
        if word not in syms:
            sys.exit(f"violations: {a.elf} has no {word}")
        if a.cmd == "spin-stall":
            val = 1
        elif (a.arg or "") == "stall":
            val = STALL
        else:
            val = int(a.arg or 0)
            if not 0 < val <= 2000:
                sys.exit("violations: fault-overrun takes 1..2000 ms or `stall`")
        addr = syms[word][0]
        print(f"violations: write {val:#x} -> {word} @ {addr:#010x}")
        if a.dry_run:
            return 0
        s = board()
        try:
            s.board.target.write32(addr, val)
            back = s.board.target.read32(addr)
        finally:
            s.close()
        print(f"violations: {word} reads {back:#x} after the write "
              f"({'not yet taken' if back else 'already taken'})")
        return 0
    if a.cmd == "decode":
        words = json.load(open(a.words)) if a.words else {}
        sys.stdout.write(report(a.elf, open(a.arg, "rb").read(), words))
        return 0
    if a.cmd == "overrun":
        if OVERRUN not in syms:
            sys.exit(f"violations: {a.elf} has no {OVERRUN} (built without CONFIG_ISLAND_DEBUG_OVERRUN)")
        ms = int(a.arg or 0)
        if not 0 < ms <= 2000:
            sys.exit("violations: overrun takes 1..2000 ms")
        addr = syms[OVERRUN][0]
        print(f"violations: write {ms} -> {OVERRUN} @ {addr:#010x}")
        if a.dry_run:
            return 0
        s = board()
        try:
            s.board.target.write32(addr, ms)
            back = s.board.target.read32(addr)
        finally:
            s.close()
        print(f"violations: {OVERRUN} reads {back} after the write "
              f"({'not yet taken' if back else 'already taken by a tick'})")
        return 0
    if RECORD not in syms:
        sys.exit(f"violations: {a.elf} has no {RECORD} (built without CONFIG_NROS_BOOT_REPORT, or a pin "
                 f"before phase-474 I1)")
    if not a.out:
        sys.exit("violations: read needs --out <prefix>")
    addr, size = syms[RECORD]
    print(f"violations: read {RECORD} @ {addr:#010x}, {size} B; "
          + ", ".join(f"{n} @ {syms[n][0]:#010x}" for n in ARM_WORDS if n in syms))
    if a.dry_run:
        return 0
    s = board()
    try:
        t = s.board.target
        blob = bytes(t.read_memory_block8(addr, size))
        words = {n: t.read32(syms[n][0]) for n in ARM_WORDS if n in syms}
    finally:
        s.close()
    open(a.out + ".bin", "wb").write(blob)
    json.dump(words, open(a.out + ".words.json", "w"))
    text = report(a.elf, blob, words)
    open(a.out + ".txt", "w").write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
