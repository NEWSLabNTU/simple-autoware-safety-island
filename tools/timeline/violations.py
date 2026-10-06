#!/usr/bin/env python3
"""The island's runtime contract violations, off the board (phase9-W4).

  violations.py read     --elf <zephyr.elf> --out <dir>/violations   attach, no halt
  violations.py decode   --elf <zephyr.elf> <dir>/violations.bin [--words <json>]
  violations.py overrun  --elf <zephyr.elf> <ms>                     the debug hook
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

`overrun N` writes N into `island_debug_overrun_ms` (CONFIG_ISLAND_DEBUG_OVERRUN,
Kconfig.island_trace): the handler's next RUN tick busy-waits N ms, once.
"""
import argparse
import importlib.util
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NROS_SCRIPTS = os.path.join(ROOT, "third-party/nano-ros/scripts")
TABLE = os.path.join(ROOT, "src/safety_island_tracing/markers.json")
RECORD = "NROS_VIOLATION_RECORD"
ARM_WORDS = ["island_monitors_armed_uptime_ms", "island_monitors_armed_via",
             "island_trace_hb_last_uptime_ms"]
OVERRUN = "island_debug_overrun_ms"
ARM_VIA = {0: "not armed", 1: "INIT_DONE", 2: "init failure cleared"}


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
            raw = helpers.elf_bytes(elf, s["fqn_addr"], s["fqn_len"])
            fqn = raw.decode("utf-8", "replace") if raw is not None else None
        if fqn is None:
            fqn = hashes.get(f"{s['fqn_hash']:08x}", f"fqn#{s['fqn_hash']:08x}")
        lines.append(f"  #{seq}: {dec.rule_name(s['rule'])} {fqn} "
                     f"measured={s['measured']} declared={s['declared']}")
    return "\n".join(lines) + "\n"


def board():
    from pyocd.core.helpers import ConnectHelper
    s = ConnectHelper.session_with_chosen_probe(
        target_override="s32k344", connect_mode="attach", options={"frequency": 4000000})
    s.open()
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["read", "decode", "overrun"])
    ap.add_argument("arg", nargs="?", help="decode: the record dump; overrun: ms")
    ap.add_argument("--elf", required=True)
    ap.add_argument("--out", help="read: output prefix (<out>.bin, <out>.txt)")
    ap.add_argument("--words", help="decode: a JSON file of the arming words read beside the dump")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    syms = symbols(a.elf, {RECORD, OVERRUN, *ARM_WORDS})
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
