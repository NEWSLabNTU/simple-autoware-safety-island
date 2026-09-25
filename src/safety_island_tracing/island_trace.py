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

Input: a native_sim dump (`ISLTRC01` header, written by the image at exit) or
a raw `ram_tracing` read from the board (`--zephyr 4.4`, no header).

  island_trace.py decode <file> [--timeline N] [--perfetto out.json]
  island_trace.py check  <file>

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
    ev_marker, ev_hb, ev_prov = base, base + 1, base + 2
    for e in (ev_marker, ev_hb, ev_prov):
        if e in events:
            sys.exit(f"island_trace: id {e:#x} collides with a Zephyr CTF event in {tr.tsdl}")
    buf = buf + b"\0" * 64  # the dump trims trailing zeros; a record may end in them
    table = json.load(open(TABLE))
    names = {m["id"]: m["name"] for m in table["markers"]}
    recs, sizes = [], Counter()
    pos, prev_ts, ext = 0, None, 0
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
    tr.records, tr.bytes_by_kind, tr.used = recs, sizes, pos
    tr.table = table
    return tr


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
        print(f"span : {len(recs)} records over {span / 1e9:.3f} s (host time on native_sim)", file=out)
    print(f"{'event':<28}{'count':>10}{'bytes':>12}{'B/event':>9}", file=out)
    for k, n in sorted(kinds.items(), key=lambda x: -tr.bytes_by_kind[x[0]]):
        b = tr.bytes_by_kind[k]
        print(f"{k:<28}{n:>10}{b:>12}{b / n:>9.1f}", file=out)
    print(f"{'total':<28}{len(recs):>10}{tr.used:>12}", file=out)
    for r in recs:
        if r["kind"] == "provenance":
            print(f"provenance: {r['text']}", file=out)
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
    if not provs:
        ok = False
        say("FAIL provenance: no provenance record")
    else:
        kv = dict(x.split("=", 1) for x in provs[0]["text"].split(";")[1:] if "=" in x)
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
                note = f"  unreachable: {ex[1]['node']} {ex[1]['param']}={ex[2]!r} (unreachable.yaml)"
            else:
                missing.append(m["name"])
                note = "  MISSING" + (f" (exemption lapsed: {ex[1]['param']} is {ex[2]!r})" if ex else "")
        say(f"{m['id']:>3}  {m['name']:<56}{n:>8}{note}")
    unknown = sorted(set(seen) - {m["id"] for m in tr.table["markers"]})
    say("")
    if unknown:
        ok = False
        say(f"FAIL markers: ids not in the table: {unknown}")
    if missing:
        ok = False
        say(f"FAIL markers: {len(missing)} of {len(tr.table['markers'])} never seen: {', '.join(missing)}")
    else:
        say(f"ok   markers: {len(tr.table['markers']) - len(excused)} of {len(tr.table['markers'])} seen at least once; "
            f"{len(excused)} unreachable under the configured parameters")
    hbs = [r["seq"] for r in tr.records if r["kind"] == "heartbeat"]
    gaps = [(a, b) for a, b in zip(hbs, hbs[1:]) if b != a + 1]
    if not hbs:
        ok = False
        say("FAIL heartbeat: none recorded")
    elif hbs[0] != 0 or gaps:
        ok = False
        say(f"FAIL heartbeat: first seq {hbs[0]}, {len(gaps)} gap(s): {gaps[:5]}")
    else:
        say(f"ok   heartbeat: seq 0..{hbs[-1]} contiguous ({len(hbs)} records)")
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["decode", "check"])
    ap.add_argument("file")
    ap.add_argument("--zephyr", help="major.minor of the tree (needed for a raw board buffer)")
    ap.add_argument("--tsdl", help="explicit path to the CTF TSDL metadata")
    ap.add_argument("--timeline", type=int, default=0, help="print the first N marker/heartbeat records")
    ap.add_argument("--perfetto", help="write a Chrome/Perfetto trace-event JSON here")
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()
    tr = load(a.file, a.zephyr, a.tsdl)
    if a.cmd == "decode":
        summarize(tr)
        if a.timeline:
            t0 = tr.records[0]["t_ns"] if tr.records else 0
            n = 0
            for r in tr.records:
                if r["kind"] == "marker":
                    print(f"{fmt_ms(r['t_ns'] - t0)} ms  {r['name']:<56} arg={r['arg']}")
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
