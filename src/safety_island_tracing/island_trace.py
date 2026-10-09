#!/usr/bin/env python3
"""Decode and check an island trace (phase7-W1).

The island writes Zephyr CTF into the RAM tracing backend: Zephyr's own events
(thread switches and the few others the Kconfig cut leaves on) plus three
record types from src/safety_island_tracing/include/island_trace.h -- MARKER,
HEARTBEAT, PROVENANCE. CTF records carry no length, so the layout of every
Zephyr event is read from the TSDL metadata of the PINNED tree the image was
built from (subsys/tracing/ctf/tsdl/metadata); an id that is in neither the
TSDL nor island_trace.h stops the decode rather than resynchronising on
garbage.

Input: a native_sim dump (`ISLTRC01` header, written by the image at exit), a
raw `ram_tracing` read from the board (`--zephyr 4.4`, no header), or such a
read wrapped in the same header by `wrap` (tools/timeline/readout.py does, with
the heartbeat counter it read beside the buffer).

  island_trace.py decode <file> [--timeline N] [--perfetto out.json]
  island_trace.py check  <file>
  island_trace.py violations <file>
  island_trace.py takes <file>
  island_trace.py ticks <file>
  island_trace.py wrap   <raw> --zephyr 4.4 --hb-emitted N [--hb-last-uptime MS] -o <out>

A trace recorded with the trace window (phase8-W17, CONFIG_ISLAND_TRACE_WINDOW;
the provenance says `window=trigger`) starts at its pre-trigger history and
carries one TRIGGER record; `check` then asks for the trigger instead of every
marker, and for heartbeats contiguous from the first one kept instead of 0.

phase9-W4: nano-ros's contract-violation markers are forwarded into the stream
at island id NROS_BASE + nano-ros id (markers.json `nros`; 277-280 for
nano-ros 21-24). load() joins each run of four (rule|seq, endpoint hash,
measured, declared) into one violation, naming the rule from the pinned
RULE_IDS and the endpoint from the FNV-1a hashes of the contract's endpoint
refs (both in markers.json); `violations` lists them, `check` reports them
(a violation is a finding, not a decode failure), and `decode --timeline`
prints each beside its markers.

phase9-W4 rerun (nano-ros phase-474 I3, F4): the takes of three inputs are
forwarded at 281-283 (nano-ros 25-27; markers.json `nros.take_inputs`). The
sink puts the input's index where nano-ros had the slot handle, sends the
stamp's sec only when it changed for that input, and one take in `keep`.
load() joins each take (input, seq, source stamp) into `tr.takes`; `takes`
lists them with the count per input, `check` counts them.

phase9-W4 rerun: the bound timer's dispatch events (nano-ros 18/19, the
emergency operator's 30 Hz timer, every tick) are forwarded at 274/275
(NROS_BASE + id; every other slot's are dropped). `ticks` prints the
start-to-start spacing: count, mean, min, max and a histogram at 1 ms bins,
and the callback duration (start to end); `check` reports the count and mean.

`check` exits 0 only if: the decode is clean; the provenance names the marker
table in markers.json; every marker is present at least once, except those
unreachable.yaml ties to a parameter value that the resolved model confirms;
the heartbeat sequence is contiguous from 0; and (native_sim dumps) the last
recorded heartbeat is the last one the image emitted, i.e. the buffer did not
fill before the run ended.
"""
import argparse
import json
import os
import re
import struct
import sys
from collections import Counter

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TABLE = os.path.join(HERE, "markers.json")
UNREACHABLE = os.path.join(HERE, "unreachable.yaml")
MODEL = os.path.join(ROOT, "build/nros/models/safety_island_bringup/system_model.yaml")
MAGIC = b"ISLTRC01"


# ---------------------------------------------------------------- TSDL ----
def tsdl_path(version, override=None):
    if override:
        return override
    ws = os.environ.get("NROS_ZEPHYR_STORE", os.path.expanduser("~/.nros/workspaces/zephyr"))
    return os.path.join(ws, version, "zephyr/subsys/tracing/ctf/tsdl/metadata")


def parse_tsdl(path):
    text = open(path).read()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    sizes = {}
    for m in re.finditer(r"typealias integer\s*\{([^}]*)\}\s*:=\s*(\w+)\s*;", text):
        sizes[m.group(2)] = int(re.search(r"size\s*=\s*(\d+)", m.group(1)).group(1)) // 8
    hdr = re.search(r"struct event_header\s*\{([^}]*)\}", text).group(1)
    hdr_fields = re.findall(r"(\w+)\s+(\w+)\s*;", hdr)
    id_size = sizes[dict((n, t) for t, n in hdr_fields)["id"]]
    events = {}
    for m in re.finditer(r"event\s*\{", text):
        i, depth = m.end(), 1
        while depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[m.end():i - 1]
        name = re.search(r"name\s*=\s*(\w+)\s*;", body).group(1)
        eid = int(re.search(r"id\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*;", body).group(1), 0)
        fields = []
        fm = re.search(r"fields\s*:=\s*struct\s*\{(.*)\}", body, flags=re.S)
        if fm:
            for t, n, arr in re.findall(r"(\w+)\s+(\w+)\s*(?:\[(\d+)\])?\s*;", fm.group(1)):
                fields.append((n, t, int(arr) if arr else None, sizes[t]))
        events[eid] = (name, fields)
    return id_size, events


def field_value(t, raw, arr):
    if t == "ctf_bounded_string_t":
        return raw.split(b"\0", 1)[0].decode("ascii", "replace")
    signed = t.startswith("int")
    return int.from_bytes(raw, "little", signed=signed)


# -------------------------------------------------------------- decode ----
class Trace:
    pass


def load(path, zephyr=None, tsdl=None):
    data = open(path, "rb").read()
    tr = Trace()
    tr.header = None
    if data[:8] == MAGIC:
        hlen = struct.unpack_from("<I", data, 8)[0]
        f = struct.unpack_from("<7I", data, 12)
        tr.header = dict(zephyr_version=f[0], buffer_size=f[1], heartbeats_emitted=f[2],
                         heartbeat_ms=f[3], last_heartbeat_uptime_ms=f[4], dumped_len=f[5])
        v = f[0]
        zephyr = zephyr or f"{v >> 16}.{(v >> 8) & 0xff}"
        buf = data[hlen:hlen + f[5]]
    else:
        if not zephyr:
            sys.exit("island_trace: a raw buffer needs --zephyr <major.minor> (the board is 4.4)")
        buf = data
    tr.zephyr = zephyr
    tr.tsdl = tsdl_path(zephyr, tsdl)
    id_size, events = parse_tsdl(tr.tsdl)
    base = 0x1E0 if id_size == 2 else 0xE0
    ev_marker, ev_hb, ev_prov, ev_trig = base, base + 1, base + 2, base + 3
    for e in (ev_marker, ev_hb, ev_prov, ev_trig):
        if e in events:
            sys.exit(f"island_trace: id {e:#x} collides with a Zephyr CTF event in {tr.tsdl}")
    buf = buf + b"\0" * 64  # the dump trims trailing zeros; a record may end in them
    table = json.load(open(TABLE))
    names = {m["id"]: m["name"] for m in table["markers"]}
    names.update({m["id"]: m["name"] for m in table.get("nros", {}).get("markers", [])})
    recs, sizes = [], Counter()
    pos, prev_ts, ext = 0, None, 0
    seg_start = None
    tr.error = None
    hsz = 4 + id_size
    while pos + hsz <= len(buf):
        ts, = struct.unpack_from("<I", buf, pos)
        eid = int.from_bytes(buf[pos + 4:pos + 4 + id_size], "little")
        if eid == 0:
            break  # unused space (no CTF or island id is 0)
        # u32 ns wraps every 4.29 s; records are close together, so take the
        # signed modular difference (also absorbs the small reordering 3.7's
        # CTF_EVENT allows: its timestamp is read outside the lock).
        if prev_ts is None:
            t = ts
        else:
            d = (ts - prev_ts) & 0xFFFFFFFF
            if d >= 0x80000000:
                d -= 0x100000000
            t = ext + d
        prev_ts, ext = ts, t
        p = pos + hsz
        rec = dict(off=pos, t_ns=t, id=eid)
        if eid == ev_marker:
            mk, arg = struct.unpack_from("<HI", buf, p)
            rec.update(kind="marker", marker=mk, name=names.get(mk, f"UNKNOWN_{mk}"), arg=arg)
            p += 6
        elif eid == ev_hb:
            seq, up = struct.unpack_from("<II", buf, p)
            rec.update(kind="heartbeat", seq=seq, uptime_ms=up)
            p += 8
        elif eid == ev_prov:
            n, = struct.unpack_from("<H", buf, p)
            rec.update(kind="provenance", text=buf[p + 2:p + 2 + n].decode("ascii", "replace"))
            p += 2 + n
        elif eid == ev_trig:
            mk, pre_ms, kept, spin, lost, filt = struct.unpack_from("<HHHHII", buf, p)
            rec.update(kind="trigger", marker=mk, name=names.get(mk, f"UNKNOWN_{mk}"), pre_ms=pre_ms,
                       pre_kept=kept, spin_keep=spin, pre_lost=lost, filtered=filt)
            p += 16
        elif eid in events:
            name, fields = events[eid]
            rec.update(kind=name)
            for fname, t_, arr, sz in fields:
                n = sz * (arr or 1)
                rec[fname] = field_value(t_, buf[p:p + n], arr)
                p += n
        else:
            tr.error = f"unknown event id {eid:#x} at buffer offset {pos} (after {len(recs)} records)"
            break
        sizes[rec["kind"]] += p - pos
        recs.append(rec)
        pos = p
        if rec["kind"] == "provenance" and "window=trigger" in rec["text"]:
            # phase8-W17: with the trace window nothing else need follow the
            # provenance until the trigger, an unknown time later (the board
            # writes nothing in between), so the next record starts a new
            # segment, anchored below on a heartbeat's uptime.
            prev_ts, seg_start = None, len(recs)
    if seg_start is not None:
        hb = next((r for r in recs[seg_start:] if r["kind"] == "heartbeat"), None)
        if hb is not None:
            # the segment's stamps are the island clock mod 2^32; the heartbeat's
            # uptime_ms (same kernel clock, ms) says which multiple of 2^32 ns
            k = round((hb["uptime_ms"] * 1_000_000 - hb["t_ns"]) / 2**32)
            for r in recs[seg_start:]:
                r["t_ns"] += k * 2**32
    tr.records, tr.bytes_by_kind, tr.used = recs, sizes, pos
    tr.table = table
    tr.violations = join_violations(recs, table)
    tr.takes = join_takes(recs, table)
    return tr


def nros_names(table):
    """{island id: name} of the forwarded nano-ros markers (phase9-W4)."""
    return {m["id"]: m["name"] for m in table.get("nros", {}).get("markers", [])}


def rule_name(table, code):
    rules = table.get("nros", {}).get("rule_ids", [])
    return rules[code - 1] if 1 <= code <= len(rules) else f"rule#{code}"


def endpoint_name(table, h):
    return table.get("nros", {}).get("endpoint_hashes", {}).get(f"{h:08x}", f"fqn#{h:08x}")


def join_violations(recs, table):
    """phase9-W4: each stored violation is four markers in a row on one thread
    (nano-ros callback_trace: 21 seq|rule, 22 fqn hash, 23 measured, 24
    declared). Join them; a 22-24 without its 21 is dropped, as nano-ros's own
    decoder does, and a 21 whose followers are missing is kept with what it
    has."""
    order = [m["name"] for m in table.get("nros", {}).get("markers", [])
             if m.get("kind", "nros_violation") == "nros_violation"]
    if len(order) != 4:
        return []
    head, f_fqn, f_meas, f_decl = order
    out, cur = [], None
    for r in recs:
        if r.get("kind") != "marker":
            continue
        n = r["name"]
        if n == head:
            cur = dict(t_ns=r["t_ns"], seq=r["arg"] >> 8, rule_code=r["arg"] & 0xFF,
                       rule=rule_name(table, r["arg"] & 0xFF))
            out.append(cur)
        elif cur is not None and n == f_fqn and "fqn_hash" not in cur:
            cur["fqn_hash"] = r["arg"]
            cur["endpoint"] = endpoint_name(table, r["arg"])
        elif cur is not None and n == f_meas and "measured" not in cur:
            cur["measured"] = r["arg"]
        elif cur is not None and n == f_decl and "declared" not in cur:
            cur["declared"] = r["arg"]
            cur = None
        elif n in (f_fqn, f_meas, f_decl):
            continue
    return out


def join_takes(recs, table):
    """phase9-W4 rerun: each forwarded take is NROS_TAKE (input << 24 | seq),
    then NROS_TAKE_STAMP_SEC when the stamp's second changed for that input,
    then NROS_TAKE_STAMP_NSEC. The sec of a take without one is the input's
    last one; a take before any sec (the first after a window opened) has no
    stamp. `stamp_ns` is the sample's source stamp (the publisher's clock)."""
    inputs = {t["index"]: t["endpoint"] for t in table.get("nros", {}).get("take_inputs", [])}
    if not inputs:
        return []
    out, cur, sec = [], None, {}
    for r in recs:
        if r.get("kind") != "marker":
            continue
        n = r["name"]
        if n == "NROS_TAKE":
            i = r["arg"] >> 24
            cur = dict(t_ns=r["t_ns"], input=i, endpoint=inputs.get(i, f"input#{i}"),
                       seq=r["arg"] & 0xFFFFFF)
            out.append(cur)
        elif n == "NROS_TAKE_STAMP_SEC" and cur is not None:
            sec[cur["input"]] = r["arg"]
        elif n == "NROS_TAKE_STAMP_NSEC" and cur is not None:
            s_ = sec.get(cur["input"])
            if s_ is not None:
                cur["stamp_ns"] = s_ * 1_000_000_000 + r["arg"]
            cur = None
    return out


def timer_ticks(tr):
    """phase9-W4 rerun: the bound timer's starts and ends (274/275), as
    (start_ns, end_ns or None) pairs in order."""
    out = []
    for r in tr.records:
        if r.get("kind") != "marker":
            continue
        if r["name"] == "NROS_TIMER_START":
            out.append([r["t_ns"], None])
        elif r["name"] == "NROS_TIMER_END" and out and out[-1][1] is None:
            out[-1][1] = r["t_ns"]
    return out


def tick_stats(ticks):
    st = [t for t, _ in ticks]
    d = [(b - a) / 1e6 for a, b in zip(st, st[1:])]
    if not d:
        return None
    hist = Counter(int(x) for x in d)
    dur = [(e - s_) / 1e6 for s_, e in ticks if e is not None]
    return dict(n=len(st), gaps=len(d), mean=sum(d) / len(d), min=min(d), max=max(d), hist=hist,
                span_ms=(st[-1] - st[0]) / 1e6, dur_max=max(dur) if dur else None,
                dur_mean=sum(dur) / len(dur) if dur else None)


def take_counts(tr):
    c = Counter(t["endpoint"] for t in getattr(tr, "takes", []))
    stamped = Counter(t["endpoint"] for t in getattr(tr, "takes", []) if "stamp_ns" in t)
    return {t["endpoint"]: (c.get(t["endpoint"], 0), stamped.get(t["endpoint"], 0))
            for t in tr.table.get("nros", {}).get("take_inputs", [])}


def fmt_violation(v):
    return (f"#{v['seq']}: {v['rule']} {v.get('endpoint', '?')} "
            f"measured={v.get('measured', '?')} declared={v.get('declared', '?')}")


def fmt_ms(ns):
    return f"{ns / 1e6:12.3f}"


def summarize(tr, out=sys.stdout):
    recs = tr.records
    kinds = Counter(r["kind"] for r in recs)
    print(f"trace: zephyr {tr.zephyr}, TSDL {tr.tsdl}", file=out)
    if tr.header:
        h = tr.header
        print(f"dump : buffer {h['buffer_size']} B, {h['dumped_len']} B used, "
              f"{h['heartbeats_emitted']} heartbeats emitted, last at uptime {h['last_heartbeat_uptime_ms']} ms",
              file=out)
    if recs:
        span = recs[-1]["t_ns"] - recs[0]["t_ns"]
        unit = ("simulated time on native_sim" if getattr(tr, "header", None)
                else f"cycle-counter time, zephyr {tr.zephyr}")
        print(f"span : {len(recs)} records over {span / 1e9:.3f} s ({unit})", file=out)
    print(f"{'event':<28}{'count':>10}{'bytes':>12}{'B/event':>9}", file=out)
    for k, n in sorted(kinds.items(), key=lambda x: -tr.bytes_by_kind[x[0]]):
        b = tr.bytes_by_kind[k]
        print(f"{k:<28}{n:>10}{b:>12}{b / n:>9.1f}", file=out)
    print(f"{'total':<28}{len(recs):>10}{tr.used:>12}", file=out)
    for r in recs:
        if r["kind"] == "provenance":
            print(f"provenance: {r['text']}", file=out)
    for v in getattr(tr, "violations", []):
        print(f"violation: {fmt_violation(v)}", file=out)
    if tr.error:
        print(f"DECODE ERROR: {tr.error}", file=out)


def perfetto(tr, path):
    ev = []
    t0 = tr.records[0]["t_ns"] if tr.records else 0
    node_of = {m["id"]: m.get("node", "?") for m in tr.table["markers"]}
    for r in tr.records:
        us = (r["t_ns"] - t0) / 1000.0
        k = r["kind"]
        if k == "marker":
            m = r["name"]
            track = "node " + node_of.get(r["marker"], "?")
            ph = "B" if m.endswith("_ENTRY") else "E" if m.endswith("_EXIT") else "i"
            label = m[:-6] if ph == "B" else m[:-5] if ph == "E" else m
            e = dict(name=label, ph=ph, ts=us, pid=1, tid=track, args=dict(arg=r["arg"]))
            if ph == "i":
                e["s"] = "t"
            ev.append(e)
        elif k in ("thread_switched_in", "thread_switched_out"):
            ev.append(dict(name=r.get("name") or hex(r.get("thread_id", 0)), ph="B" if k.endswith("in") else "E",
                           ts=us, pid=2, tid=f"thread {r.get('name') or hex(r.get('thread_id', 0))}"))
        elif k == "heartbeat":
            ev.append(dict(name="heartbeat_seq", ph="C", ts=us, pid=1, args=dict(seq=r["seq"])))
    json.dump(dict(traceEvents=ev, displayTimeUnit="ms"), open(path, "w"))


# --------------------------------------------------------------- check ----
def param_value(model, node, param):
    n = model["structure"]["nodes"].get(node)
    if not n:
        return None
    val = None
    for src in n.get("param_sources", []):
        if src.get("kind") == "file":
            doc = yaml.safe_load(src["content"]) or {}
            for sect in doc.values():
                cur = (sect or {}).get("ros__parameters", {})
                for part in param.split("."):
                    cur = cur.get(part) if isinstance(cur, dict) else None
                if cur is not None:
                    val = cur
        elif src.get("kind") == "inline" and src.get("name") == param:
            val = src.get("value")
    return val


# bytes of one island record on the board (Zephyr 4.x, u16 event id)
BOARD_BYTES = dict(marker=12, heartbeat=14, trigger=22)


def window_stats(tr):
    """The window's figures: where the trigger is, what came before it, and the
    island's own record rate after it, in this trace's bytes and the board's."""
    recs = tr.records
    ti = next((i for i, r in enumerate(recs) if r["kind"] == "trigger"), None)
    if ti is None:
        return None
    trig = recs[ti]
    pre = [r for r in recs[:ti] if r["kind"] in ("marker", "heartbeat")
           and r["t_ns"] <= trig["t_ns"] and r["t_ns"] >= trig["t_ns"] - 2_100_000_000]
    post = [r for r in recs[ti + 1:] if r["kind"] in ("marker", "heartbeat")]
    t_end = post[-1]["t_ns"] if post else trig["t_ns"]
    span = (t_end - trig["t_ns"]) / 1e9
    per = {k: tr.bytes_by_kind[k] / n for k, n in Counter(r["kind"] for r in recs).items()}
    post_bytes = sum(per[r["kind"]] for r in post)
    post_board = sum(BOARD_BYTES[r["kind"]] for r in post)
    pre_board = sum(BOARD_BYTES[r["kind"]] for r in pre)
    prov_board = sum(4 + 2 + 2 + len(r["text"]) for r in recs if r["kind"] == "provenance")
    return dict(trigger=trig, pre=pre, post=post, span_s=span,
                pre_span_ms=(trig["t_ns"] - pre[0]["t_ns"]) / 1e6 if pre else 0.0,
                post_bytes=post_bytes, post_board=post_board, pre_board=pre_board,
                prov_board=prov_board,
                board_rate=post_board / span if span > 0 else None)


def window_report(tr, kv, say):
    w = window_stats(tr)
    if w is None:
        say("FAIL window: the provenance says window=trigger and there is no TRIGGER record "
            "(the detector path never ran after the arm, or the buffer was read before the act)")
        return False
    t = w["trigger"]
    say(f"ok   window: trigger {t['name']} (id {t['marker']}); history {len(w['pre'])} records over "
        f"{w['pre_span_ms']:.0f} ms before it (pre_ms {t['pre_ms']}, kept {t['pre_kept']}, not flushed "
        f"{t['pre_lost']}); spin_keep {t['spin_keep']}, {t['filtered']} markers dropped by policy before it")
    if w["board_rate"]:
        say(f"ok   window: {len(w['post'])} records over {w['span_s']:.2f} s after the trigger, "
            f"{w['post_bytes']:.0f} B here, {w['post_board']} B in the board's format = "
            f"{w['board_rate']:.0f} B/s = {1024 / w['board_rate']:.2f} s of act per KiB")
        fixed = w["prov_board"] + w["pre_board"] + BOARD_BYTES["trigger"]
        say(f"info window: fixed cost {fixed} B (provenance {w['prov_board']}, history {w['pre_board']}, "
            f"trigger 22); at this rate 16 KiB holds {(16384 - fixed) / w['board_rate']:.1f} s, "
            f"24 KiB {(24576 - fixed) / w['board_rate']:.1f} s, 32 KiB {(32768 - fixed) / w['board_rate']:.1f} s")
    return True


def check(tr, model_path):
    ok = True
    lines = []
    say = lines.append
    if tr.error:
        ok = False
        say(f"FAIL decode: {tr.error}")
    else:
        say(f"ok   decode: {len(tr.records)} records, {tr.used} bytes, no unknown event id")
    provs = [r for r in tr.records if r["kind"] == "provenance"]
    kv = {}
    if provs:
        kv = dict(x.split("=", 1) for x in provs[0]["text"].split(";")[1:] if "=" in x)
    windowed = kv.get("window") == "trigger"
    if not provs:
        ok = False
        say("FAIL provenance: no provenance record")
    else:
        if kv.get("table_sha256") != tr.table["table_sha256"]:
            ok = False
            say(f"FAIL provenance: trace table {kv.get('table_sha256')} != markers.json {tr.table['table_sha256']}")
        else:
            say(f"ok   provenance: marker table {kv['table_sha256'][:12]}, contract {kv.get('contract_sha256', '?')[:12]}, "
                f"zephyr {kv.get('zephyr')}, board {kv.get('board')}")
    seen = Counter(r["marker"] for r in tr.records if r["kind"] == "marker")
    model = yaml.safe_load(open(model_path)) if os.path.exists(model_path) else None
    exempt = {}
    for e in (yaml.safe_load(open(UNREACHABLE)) or []) if os.path.exists(UNREACHABLE) else []:
        if "fault" in e:
            # a fault-path marker (phase8-W27): excused in a healthy run, never
            # lapses; the run that injects the fault is where it is required
            exempt[e["marker"]] = (True, e, None)
            continue
        actual = param_value(model, e["node"], e["param"]) if model else None
        exempt[e["marker"]] = (actual == e["value"], e, actual)
    missing, excused = [], []
    say("")
    say(f"{'id':>3}  {'marker':<56}{'count':>8}")
    for m in tr.table["markers"]:
        n = seen.get(m["id"], 0)
        note = ""
        if n == 0:
            ex = exempt.get(m["name"])
            if ex and ex[0]:
                excused.append(m["name"])
                note = (f"  fault path: {ex[1]['fault']} (unreachable.yaml)" if "fault" in ex[1] else
                        f"  unreachable: {ex[1]['node']} {ex[1]['param']}={ex[2]!r} (unreachable.yaml)")
            else:
                missing.append(m["name"])
                note = "  MISSING" + (f" (exemption lapsed: {ex[1]['param']} is {ex[2]!r})" if ex else "")
        say(f"{m['id']:>3}  {m['name']:<56}{n:>8}{note}")
    unknown = sorted(set(seen) - {m["id"] for m in tr.table["markers"]} - set(nros_names(tr.table)))
    say("")
    if unknown:
        ok = False
        say(f"FAIL markers: ids not in the table: {unknown}")
    if missing and windowed:
        # the window holds one act: markers of the other acts, and of boot, are not in it
        say(f"info markers: {len(tr.table['markers']) - len(missing) - len(excused)} of "
            f"{len(tr.table['markers'])} in the window; not in it: {', '.join(missing)}")
    elif missing:
        ok = False
        say(f"FAIL markers: {len(missing)} of {len(tr.table['markers'])} never seen: {', '.join(missing)}")
    else:
        say(f"ok   markers: {len(tr.table['markers']) - len(excused)} of {len(tr.table['markers'])} seen at least once; "
            f"{len(excused)} unreachable under the configured parameters or fault-path only")
    hbs = [r["seq"] for r in tr.records if r["kind"] == "heartbeat"]
    gaps = [(a, b) for a, b in zip(hbs, hbs[1:]) if b != a + 1]
    if not hbs:
        ok = False
        say("FAIL heartbeat: none recorded")
    elif (hbs[0] != 0 and not windowed) or gaps:
        ok = False
        say(f"FAIL heartbeat: first seq {hbs[0]}, {len(gaps)} gap(s): {gaps[:5]}")
    else:
        say(f"ok   heartbeat: seq {hbs[0]}..{hbs[-1]} contiguous ({len(hbs)} records)")
    if windowed:
        ok = window_report(tr, kv, say) and ok
    vs = getattr(tr, "violations", [])
    viol_ids = [m["id"] for m in tr.table.get("nros", {}).get("markers", [])
                if m.get("kind", "nros_violation") == "nros_violation"] or [0]
    if vs:
        # a finding of the run, not a fault of the trace: reported, never FAIL
        say(f"info violations: {len(vs)} stored contract violation(s) in the trace (nano-ros markers "
            f"{min(viol_ids)}-{max(viol_ids)})")
        t0 = tr.records[0]["t_ns"] if tr.records else 0
        for v in vs:
            say(f"info   at {(v['t_ns'] - t0) / 1e6:.3f} ms: {fmt_violation(v)}")
    else:
        say("ok   violations: none in the trace")
    if tr.table.get("nros", {}).get("take_inputs"):
        # F4's input (phase 9 W13): reported, never FAIL (an act may end before one arrives)
        tc = take_counts(tr)
        say(f"info takes: {sum(n for n, _ in tc.values())} forwarded take(s) (nano-ros 25-27): " +
            ", ".join(f"{ep} {n} ({st} stamped)" for ep, (n, st) in tc.items()))
    ts_ = tick_stats(timer_ticks(tr))
    if ts_:
        say(f"info timer ticks: {ts_['n']} of the bound timer (274/275), spacing mean {ts_['mean']:.3f} ms, "
            f"min {ts_['min']:.3f}, max {ts_['max']:.3f} (island_trace.py ticks)")
    if tr.header and hbs:
        emitted = tr.header["heartbeats_emitted"]
        if hbs[-1] + 1 != emitted:
            ok = False
            say(f"FAIL complete: the image emitted {emitted} heartbeats, the buffer holds {hbs[-1] + 1}: "
                f"it filled at {tr.used} of {tr.header['buffer_size']} B, ~{(emitted - hbs[-1] - 1) * tr.header['heartbeat_ms'] / 1000:.1f} s before exit")
        else:
            say(f"ok   complete: last heartbeat recorded is the last emitted ({emitted}); "
                f"buffer {tr.used} of {tr.header['buffer_size']} B")
    say("")
    say(f"trace-check: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def wrap(raw_path, out, zephyr, hb_emitted, hb_last_uptime_ms, hb_ms=100):
    """A raw buffer read off the target (SWD, the QEMU monitor), in the native_sim
    dump's format: the header carries what the buffer cannot hold about itself
    -- the heartbeat counter at the read, so `check` can tell a full buffer from
    a short act. The used length is up to the last non-zero byte, as on
    native_sim (the backend zeroes the buffer at init; no record id is 0)."""
    data = open(raw_path, "rb").read()
    used = len(data.rstrip(b"\0"))
    major, minor = (int(x) for x in zephyr.split(".")[:2])
    hdr = MAGIC + struct.pack("<8I", 36, (major << 16) | (minor << 8), len(data), hb_emitted, hb_ms,
                              hb_last_uptime_ms, used, 0)[:28]
    with open(out, "wb") as f:
        f.write(hdr)
        f.write(data[:used])
    print(f"island_trace: wrapped {raw_path} ({used} of {len(data)} B used, {hb_emitted} heartbeats "
          f"emitted) -> {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["decode", "check", "wrap", "violations", "takes", "ticks"])
    ap.add_argument("file")
    ap.add_argument("--zephyr", help="major.minor of the tree (needed for a raw board buffer)")
    ap.add_argument("--tsdl", help="explicit path to the CTF TSDL metadata")
    ap.add_argument("--timeline", type=int, default=0, help="print the first N marker/heartbeat records")
    ap.add_argument("--perfetto", help="write a Chrome/Perfetto trace-event JSON here")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--hb-emitted", type=int, help="wrap: island_trace_hb_seq read beside the buffer")
    ap.add_argument("--hb-last-uptime", type=int, default=0, help="wrap: island_trace_hb_last_uptime_ms")
    ap.add_argument("--hb-ms", type=int, default=100)
    ap.add_argument("-o", "--out", help="wrap: the output file")
    a = ap.parse_args()
    if a.cmd == "wrap":
        if not a.zephyr or a.hb_emitted is None or not a.out:
            sys.exit("island_trace: wrap needs --zephyr, --hb-emitted and -o")
        wrap(a.file, a.out, a.zephyr, a.hb_emitted, a.hb_last_uptime, a.hb_ms)
        return 0
    tr = load(a.file, a.zephyr, a.tsdl)
    if a.cmd == "violations":
        t0 = tr.records[0]["t_ns"] if tr.records else 0
        trig = next((r for r in tr.records if r["kind"] == "trigger"), None)
        print(f"trace violations: {len(tr.violations)}" +
              (f" (trace window opened by {trig['name']})" if trig else ""))
        for v in tr.violations:
            print(f"  {(v['t_ns'] - t0) / 1e6:12.3f} ms  {fmt_violation(v)}")
        return 1 if tr.error else 0
    if a.cmd == "takes":
        t0 = tr.records[0]["t_ns"] if tr.records else 0
        tc = take_counts(tr)
        print(f"trace takes: {len(tr.takes)}; " +
              ", ".join(f"{ep} {n} ({st} stamped)" for ep, (n, st) in tc.items()))
        for t in tr.takes:
            st = (f"stamp {t['stamp_ns'] // 1_000_000_000}.{t['stamp_ns'] % 1_000_000_000:09d}"
                  if "stamp_ns" in t else "no stamp")
            print(f"  {(t['t_ns'] - t0) / 1e6:12.3f} ms  {t['endpoint']} seq={t['seq']} {st}")
        return 1 if tr.error else 0
    if a.cmd == "ticks":
        ticks = timer_ticks(tr)
        ts_ = tick_stats(ticks)
        if not ts_:
            print(f"trace ticks: {len(ticks)} of the bound timer (274/275): no spacing to report")
            return 1 if tr.error else 0
        t0 = tr.records[0]["t_ns"] if tr.records else 0
        print(f"trace ticks: {ts_['n']} of the bound timer (274/275) over {ts_['span_ms']:.3f} ms, "
              f"from {(ticks[0][0] - t0) / 1e6:.3f} ms")
        print(f"  start-to-start: {ts_['gaps']} gaps, mean {ts_['mean']:.3f} ms, min {ts_['min']:.3f}, "
              f"max {ts_['max']:.3f}; {1e6 / ts_['mean']:.0f} mHz")
        if ts_["dur_max"] is not None:
            print(f"  callback (start to end): mean {ts_['dur_mean']:.3f} ms, max {ts_['dur_max']:.3f}")
        print("  histogram (1 ms bins, [k, k+1) ms):")
        for k in sorted(ts_["hist"]):
            print(f"    {k:5d}  {ts_['hist'][k]}")
        st = [t for t, _ in ticks]
        for a_, b_ in zip(st, st[1:]):
            if (b_ - a_) / 1e6 >= 1.5 * ts_["mean"]:
                print(f"  long gap at {(a_ - t0) / 1e6:.3f} ms: {(b_ - a_) / 1e6:.3f} ms")
        return 1 if tr.error else 0
    if a.cmd == "decode":
        summarize(tr)
        if a.timeline:
            t0 = tr.records[0]["t_ns"] if tr.records else 0
            n = 0
            for r in tr.records:
                if r["kind"] == "marker":
                    extra = ""
                    if r["name"] == "NROS_VIOLATION":
                        v = next((v for v in tr.violations if v["t_ns"] == r["t_ns"]
                                  and v["seq"] == r["arg"] >> 8), None)
                        extra = f"  {fmt_violation(v)}" if v else ""
                    print(f"{fmt_ms(r['t_ns'] - t0)} ms  {r['name']:<56} arg={r['arg']}{extra}")
                elif r["kind"] == "heartbeat":
                    print(f"{fmt_ms(r['t_ns'] - t0)} ms  heartbeat seq={r['seq']} uptime={r['uptime_ms']} ms")
                else:
                    continue
                n += 1
                if n >= a.timeline:
                    break
        if a.perfetto:
            perfetto(tr, a.perfetto)
            print(f"perfetto: {a.perfetto} (open in https://ui.perfetto.dev)")
        return 1 if tr.error else 0
    ok, lines = check(tr, a.model)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
