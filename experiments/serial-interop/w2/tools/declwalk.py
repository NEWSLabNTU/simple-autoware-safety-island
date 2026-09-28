#!/usr/bin/env python3
"""phase8-W2: walk every zenoh network message in the router->board direction of a
socat tap and print declarations (D/U KEYEXPR/SUB/QBL/TOKEN, D_FINAL) with ids,
interest ids and keys; PUSH counted per key. Best effort zenoh 1.x codec."""
import sys, collections
src = open(sys.argv[0].replace("declwalk.py", "tapdecode.py")).read().replace("\nmain()\n", "\n")
ns = {}; exec(src, ns)
want = sys.argv[2] if len(sys.argv) > 2 else "router->board"

class R:
    def __init__(s, b): s.b = b; s.i = 0
    def u8(s): v = s.b[s.i]; s.i += 1; return v
    def z(s):
        v = 0; sh = 0
        while True:
            c = s.u8(); v |= (c & 0x7f) << sh; sh += 7
            if not c & 0x80: return v
    def bytes_(s, n): v = s.b[s.i:s.i+n]; s.i += n; return v
    def zbuf(s): return s.bytes_(s.z())
    def left(s): return len(s.b) - s.i

def exts(r):
    out = []
    while True:
        h = r.u8(); enc = (h >> 5) & 3; eid = h & 0x0f
        if enc == 1: out.append((eid, r.z()))
        elif enc == 2: out.append((eid, r.zbuf()))
        else: out.append((eid, None))
        if not h & 0x80: return out

def wire(r, h):
    scope = r.z(); suf = r.zbuf().decode(errors="replace") if h & 0x20 else ""
    return f"{scope}:{suf}" if suf else f"{scope}"

keys = {}
def walk(p, ts, out):
    r = R(p)
    h = r.u8(); tid = h & 0x1f
    if tid != 5: out.append((ts, "T", ns["T_IDS"].get(tid, tid))); return
    r.z()  # sn
    if h & 0x80: exts(r)
    while r.left() > 0:
        nh = r.u8(); nid = nh & 0x1f
        if nid == 0x1e:  # DECLARE
            iid = r.z() if nh & 0x20 else None
            if nh & 0x80: exts(r)
            dh = r.u8(); did = dh & 0x1f
            name = ns["D_IDS"].get(did, f"D?{did}")
            if did == 0:
                eid = r.z(); k = wire(r, dh); keys[eid] = k
                out.append((ts, name, iid, eid, k))
            elif did in (2, 4, 6):
                eid = r.z(); k = wire(r, dh)
                if dh & 0x80: exts(r)
                out.append((ts, name, iid, eid, k))
            elif did in (1, 3, 5, 7):
                eid = r.z(); e = exts(r) if dh & 0x80 else []
                we = [x[1].hex() for x in e if x[0] == 0x0f]
                out.append((ts, name, iid, eid, we))
            elif did == 0x1a:
                if dh & 0x80: exts(r)
                out.append((ts, name, iid, None, None))
            else:
                out.append((ts, name, iid, "?", None)); return
        elif nid == 0x1d:  # PUSH
            k = wire(r, nh)
            if nh & 0x80: exts(r)
            bh = r.u8()
            if bh & 0x1f == 1:  # PUT
                if bh & 0x20: r.z(); r.zbuf()
                if bh & 0x40:
                    e = r.z()
                    if e & 1: r.zbuf()
                if bh & 0x80: exts(r)
                r.zbuf()
            else:
                if bh & 0x20: r.z(); r.zbuf()
                if bh & 0x80: exts(r)
            out.append((ts, "PUSH", None, None, k))
        elif nid == 0x1a:  # RESPONSE_FINAL
            rid = r.z()
            if nh & 0x80: exts(r)
            out.append((ts, "RESP_FINAL", None, rid, None))
        else:
            out.append((ts, ns["N_IDS"].get(nid, f"N?{nid:#x}"), None, None, f"unparsed rest {r.left()}B")); return

out = []
for ts, d, raw in ns["frames"](sys.argv[1]):
    if d != want: continue
    dec = ns["cobs_decode"](raw)
    if dec is None or len(dec) < 7: out.append((ts, "BAD", None, None, None)); continue
    ln = int.from_bytes(dec[1:3], "little"); p = dec[3:3+ln]
    try: walk(p, ts, out)
    except IndexError: out.append((ts, "TRUNC-PARSE", None, None, None))
pushes = collections.Counter()
for o in out:
    if o[1] == "PUSH": pushes[o[4]] += 1; continue
    print(*o)
print("PUSH per wire key:", dict(pushes))
