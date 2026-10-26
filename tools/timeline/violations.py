#!/usr/bin/env python3
"""The island's runtime contract violations, off the board (phase9-W4).

  violations.py read     --elf <zephyr.elf> --out <dir>/violations   attach, no halt
  violations.py decode   --elf <zephyr.elf> <dir>/violations.bin [--words <json>]
  violations.py overrun  --elf <zephyr.elf> <ms>                     the debug hook
  violations.py fault-overrun --elf <zephyr.elf> <ms>|stall          the same, on the fault tick
  violations.py spin-stall --elf <zephyr.elf>                        stall the spin (SWT0 bench)
  violations.py comfortable-inert --elf <zephyr.elf>                 the next comfortable stop brakes not
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
`late-return N` writes N (1..100 ms) into `island_debug_late_return_ms`
(the same Kconfig): the next spin that answered route 1 before its due holds
until N ms past that due before the supervisor hears of it, once -- a route
answered in time by a spin that runs past its due (the late notice).
phase11-S6. `comfortable-inert` writes `island_debug_comfortable_inert`
(the comfortable operator, CONFIG_ISLAND_DEBUG_OVERRUN): the next operate=1
request is answered OPERATING and no velocity limit is published, once, so
the comfortable stop does not decelerate and the supervised standstill
(route 2) is what stops the vehicle.

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
COMFORT_INERT = "island_debug_comfortable_inert"
LATE_RETURN = "island_debug_late_return_ms"
SUPERVISOR = "island_supervisor_record"
STALL = 0xFFFFFFFF
# island_supervisor.c's record, all u32: the header, then `routes` routes.
SUP_HEADER = ["magic", "latched", "latch_cause", "latch_uptime_us", "wakes", "timer_expiries",
              "swt_started", "swt_timeout_ms", "swt_fires", "swt_fire_uptime_us", "swt_errors",
              "spins", "spin_gap_max_us", "spin_gap_max_at_ms", "gpio_errors", "routes", "hook_calls",
              "hook_last_rule"]
SUP_ROUTE = ["armed", "due_ms", "arms", "dones", "fired", "fire_due_ms", "fire_verdict_us"]
# phase11-S6: after the routes, the direct emergency path's slots and route
# 2's standstill words.
SUP_DIRECT = ["registered", "calls", "first_uptime_us", "handover", "handover_uptime_ms"]
SUP_DIRECT_SLOTS = 2
SUP_DIRECT_NAME = {0: "mrm_handler (mrm_state, hazard lights)", 1: "emergency operator (braking command)"}
SUP_TAIL = ["standstill_met", "speed_mm_s", "speed_at_ms"]
# phase13-D4: after the tail, the priority plan the image was built from and
# what the kernel gave the threads at the first spin (int32 but prio_taken
# and prio_threads), then SUP_PRIO_THREADS x (name[16], int32 prio).
SUP_PRIO = ["prio_taken", "prio_plan_transport_lo", "prio_plan_transport_hi", "prio_plan_app_lo",
            "prio_plan_app_hi", "prio_plan_tier", "prio_plan_reaction", "prio_spin", "prio_reaction",
            "prio_threads"]
SUP_PRIO_THREADS = 12
# The late notice (carla-island-demo.md), after the threads: route 1 judged at
# its expiry from the executor's route cells (nano-ros RouteWatch).
SUP_LATE = ["watch_ok", "answered_at_expiry", "answered_first_due_ms", "answered_first_us",
            "later_take_at_expiry"]
# nano-ros phase-509 I1, after the late notice: the executor levels (one per
# spinning thread), then (P9b) the nano-ros level that hosts mrm_handler and
# the image's level count, then `levels` x (spins, gap_max_us, gap_max_at_ms,
# int32 prio, route_foreign, name[16], nros_level).
SUP_LEVELS = ["levels", "level_count", "level_overflow", "checkin_mask", "feeds", "route_owner",
              "route_nros_level", "nros_level_count"]
SUP_LEVEL = ["spins", "gap_max_us", "gap_max_at_ms", "prio", "route_foreign"]
SUP_LEVEL_BYTES = len(SUP_LEVEL) * 4 + 16 + 4
# zenoh-pico's tasks, by the name the platform gives them, sit in the
# transport band. Since zenoh-pico 1.9 (nano-ros phase-508, RFC-0110 D2) one
# executor thread, `zpico_exec`, runs the read path, the lease and every
# callback, beside the tx flush task; before it, `zpico_read` and
# `zpico_lease` were two tasks. A record names one set or the other.
TRANSPORT_THREADS = ("zpico_exec", "zpico_flush")
TRANSPORT_THREADS_PRE_1_9 = ("zpico_read", "zpico_lease", "zpico_flush")
SUP_MAGIC = 0x56505553
SUP_CAUSE = {0: "-", 1: "route deadline", 2: "SWT0 first timeout", 3: "the executor's reaction hook"}
SUP_ROUTE_NAME = {0: "hpc_loss reaction (mrm_handler/call_mrm)",
                  1: "the executor's next supervised route (nano-ros phase-503)",
                  2: "the comfortable stop's standstill (call + settle + response)"}
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
    off = len(SUP_HEADER) + hdr.get("routes", 0) * len(SUP_ROUTE)
    direct = []
    for i in range(SUP_DIRECT_SLOTS):
        o = off + i * len(SUP_DIRECT)
        if o + len(SUP_DIRECT) <= n:
            direct.append(dict(zip(SUP_DIRECT, w[o:o + len(SUP_DIRECT)])))
    hdr["direct"] = direct
    o = off + SUP_DIRECT_SLOTS * len(SUP_DIRECT)
    if o + len(SUP_TAIL) <= n:
        hdr.update(zip(SUP_TAIL, w[o:o + len(SUP_TAIL)]))
    o += len(SUP_TAIL)
    if o + len(SUP_PRIO) <= n:
        signed = struct.unpack(f"<{len(SUP_PRIO)}i", blob[o * 4:(o + len(SUP_PRIO)) * 4])
        hdr.update(zip(SUP_PRIO, signed))
        b = (o + len(SUP_PRIO)) * 4
        threads = []
        for i in range(min(max(hdr["prio_threads"], 0), SUP_PRIO_THREADS)):
            e = blob[b + i * 20:b + (i + 1) * 20]
            if len(e) < 20:
                break
            name = e[:16].split(b"\0", 1)[0].decode("ascii", "replace")
            threads.append((name, struct.unpack("<i", e[16:20])[0]))
        hdr["threads"] = threads
        o2 = o + len(SUP_PRIO) + SUP_PRIO_THREADS * 5
        if o2 + len(SUP_LATE) <= n:
            hdr.update(zip(SUP_LATE, w[o2:o2 + len(SUP_LATE)]))
        o3 = o2 + len(SUP_LATE)
        if o3 + len(SUP_LEVELS) <= n:
            hdr.update(zip(SUP_LEVELS, w[o3:o3 + len(SUP_LEVELS)]))
            b = (o3 + len(SUP_LEVELS)) * 4
            levels = []
            for i in range(min(hdr["level_count"], hdr["levels"])):
                e = blob[b + i * SUP_LEVEL_BYTES:b + (i + 1) * SUP_LEVEL_BYTES]
                if len(e) < SUP_LEVEL_BYTES:
                    break
                lv = dict(zip(SUP_LEVEL, struct.unpack("<IIIiI", e[:20])))
                lv["name"] = e[20:36].split(b"\0", 1)[0].decode("ascii", "replace")
                lv["nros_level"] = struct.unpack("<I", e[36:40])[0]
                levels.append(lv)
            hdr["level"] = levels
    return hdr


def priority_findings(d):
    """phase13-D4: the record's plan against what the kernel gave. Empty when
    every thread is where the plan put it; None when the record has no
    priority words (an image before phase 13, or no spin yet)."""
    if not d.get("prio_taken"):
        return None
    out = []
    if d["prio_spin"] != d["prio_plan_tier"]:
        out.append(f"spin thread at {d['prio_spin']}, the plan's tier at {d['prio_plan_tier']}")
    if d["prio_reaction"] != d["prio_plan_reaction"]:
        out.append(f"reaction thread at {d['prio_reaction']}, planned {d['prio_plan_reaction']}")
    lo, hi = d["prio_plan_transport_lo"], d["prio_plan_transport_hi"]
    seen = {n: p for n, p in d.get("threads", [])}
    names = TRANSPORT_THREADS if "zpico_exec" in seen else TRANSPORT_THREADS_PRE_1_9
    for name in names:
        if name not in seen:
            out.append(f"no thread named {name} in the record")
        elif not lo <= seen[name] <= hi:
            out.append(f"{name} at {seen[name]}, outside the transport band [{lo}, {hi}]")
    # The spin thread's side of the transport is the plan's (an authored
    # `above = "transport"` or not, nano-ros #1967), checked above as
    # spin == tier; only the supervisor must be above both.
    if not d["prio_reaction"] < min(lo, d["prio_spin"]):
        out.append(f"reaction thread at {d['prio_reaction']} is not above the transport ({lo}) "
                   f"and the spin thread ({d['prio_spin']})")
    return out


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
                 f"gpio_errors={d['gpio_errors']}; reaction hook calls={d.get('hook_calls', 0)}"
                 + (f" (last rule {d['hook_last_rule']})" if d.get("hook_calls") else ""))
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
    if "watch_ok" in d:
        line = (f"  route 1 at its expiry: {'read from the executor' + chr(39) + 's route cells' if d['watch_ok'] else 'NO route watch (the armed due stands)'}"
                f"; expiries answered by then={d['answered_at_expiry']}")
        if d["answered_at_expiry"]:
            line += (f" (first read at {d['answered_first_us'] / 1000:.3f} ms for the due at "
                     f"{d['answered_first_due_ms']} ms)")
        line += f"; re-armed to a later take={d['later_take_at_expiry']}"
        lines.append(line)
    for i, dd in enumerate(d.get("direct") or []):
        if not dd["registered"]:
            continue
        line = f"  direct emergency slot {i} {SUP_DIRECT_NAME.get(i, '')}: calls={dd['calls']}"
        if dd["calls"]:
            line += f", first at uptime {dd['first_uptime_us'] / 1000:.3f} ms"
        line += (f"; handed over to the executor at uptime {dd['handover_uptime_ms']} ms" if dd["handover"]
                 else "; not handed over")
        lines.append(line)
    if "level_count" in d:
        owner = d["route_owner"]
        lines.append(f"  levels={d['level_count']} of {d['levels']} (overflow spins {d['level_overflow']}); "
                     f"nano-ros levels {d['nros_level_count']}, mrm_handler's level {d['route_nros_level']}; "
                     f"SWT0 fed {d['feeds']} times, each once every level had checked in; route 1 owned by "
                     + (f"level {owner - 1}" if owner else "no level yet"))
        for i, lv in enumerate(d.get("level") or []):
            nl = lv.get("nros_level", 0xFF)
            lines.append(f"  level {i} {lv['name'] or '?'} prio {lv['prio']} (nano-ros level "
                         f"{nl if nl != 0xFF else '?'}): spins={lv['spins']}; longest "
                         f"spin-to-spin gap {lv['gap_max_us'] / 1000:.3f} ms (ended at uptime "
                         f"{lv['gap_max_at_ms']} ms); foreign route-1 dues {lv['route_foreign']}")
    if "standstill_met" in d:
        lines.append(f"  route 2 dues met at standstill={d['standstill_met']}; last speed {d['speed_mm_s']} mm/s "
                     f"at uptime {d['speed_at_ms']} ms")
    pf = priority_findings(d)
    if pf is not None:
        lines.append(f"  priority plan: transport [{d['prio_plan_transport_lo']}, {d['prio_plan_transport_hi']}], "
                     f"pool.app [{d['prio_plan_app_lo']}, {d['prio_plan_app_hi']}], tier {d['prio_plan_tier']}, "
                     f"reaction {d['prio_plan_reaction']}")
        lines.append(f"  priorities at the first spin: spin thread {d['prio_spin']}, reaction thread "
                     f"{d['prio_reaction']}; " + ", ".join(f"{n or '?'} {p}" for n, p in d["threads"]))
        lines.append("  priorities: " + ("AGREE with the plan" if not pf else "DISAGREE: " + "; ".join(pf)))
    return "\n".join(lines) + "\n"


def board():
    from pyocd.core.helpers import ConnectHelper
    s = ConnectHelper.session_with_chosen_probe(
        target_override="s32k344", connect_mode="attach", options={"frequency": 4000000})
    s.open()
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["read", "decode", "overrun", "fault-overrun", "spin-stall",
                                        "comfortable-inert", "late-return", "supervisor"])
    ap.add_argument("arg", nargs="?", help="decode: the record dump; overrun: ms; fault-overrun: ms or stall")
    ap.add_argument("--elf", required=True)
    ap.add_argument("--out", help="read: output prefix (<out>.bin, <out>.txt)")
    ap.add_argument("--words", help="decode: a JSON file of the arming words read beside the dump")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_intermixed_args()
    syms = symbols(a.elf, {RECORD, OVERRUN, FAULT_OVERRUN, SPIN_STALL, COMFORT_INERT, LATE_RETURN, SUPERVISOR,
                           *ARM_WORDS})
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
    if a.cmd in ("fault-overrun", "spin-stall", "comfortable-inert", "late-return"):
        word = {"fault-overrun": FAULT_OVERRUN, "spin-stall": SPIN_STALL,
                "comfortable-inert": COMFORT_INERT, "late-return": LATE_RETURN}[a.cmd]
        if word not in syms:
            sys.exit(f"violations: {a.elf} has no {word}")
        if a.cmd in ("spin-stall", "comfortable-inert"):
            val = 1
        elif a.cmd == "late-return":
            val = int(a.arg or 0)
            if not 0 < val <= 100:
                sys.exit("violations: late-return takes 1..100 ms")
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
