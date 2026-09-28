#!/usr/bin/env python3
"""phase8-W2: decode a `socat -x -v` dump of the zenoh serial link, per direction,
with timestamps. z-serial framing: COBS(hdr(1) len(2 LE) payload crc32(4)) 0x00.
Prints one line per frame: time, direction, serial flags, payload len, the
transport message id and, for FRAME, the network message ids in it (first-level
walk, best effort) and printable key strings. `--stats` prints totals only."""
import re, sys, collections
T_IDS = {0:"OAM",1:"INIT",2:"OPEN",3:"CLOSE",4:"KEEPALIVE",5:"FRAME",6:"FRAGMENT",7:"JOIN"}
N_IDS = {0x1f:"N_OAM",0x1e:"DECLARE",0x1d:"PUSH",0x1c:"REQUEST",0x1b:"RESPONSE",0x1a:"RESP_FINAL",0x19:"INTEREST"}
D_IDS = {0:"D_KEYEXPR",1:"U_KEYEXPR",2:"D_SUB",3:"U_SUB",4:"D_QBL",5:"U_QBL",6:"D_TOKEN",7:"U_TOKEN",0x1a:"D_FINAL"}

def cobs_decode(data):
    out = bytearray(); i = 0; n = len(data)
    while i < n:
        code = data[i]
        if code == 0: return None
        i += 1; take = code - 1
        if i + take > n: return None
        out += data[i:i+take]; i += take
        if code < 0xFF and i < n: out.append(0)
    return bytes(out)

def strings(b, minlen=6):
    return [m.decode() for m in re.findall(rb"[ -~]{%d,}" % minlen, b)]

def classify(payload):
    if not payload: return "empty", []
    h = payload[0]; tid = h & 0x1f
    name = T_IDS.get(tid, f"T?{tid:#x}")
    net = []
    if tid == 5 and len(payload) > 2:
        # skip SN varint
        i = 1
        while i < len(payload) and payload[i] & 0x80: i += 1
        i += 1
        # extensions on frame (Z flag 0x80) -- skip heuristically not needed for the first msg id
        if i < len(payload):
            nh = payload[i]; nid = nh & 0x1f
            nn = N_IDS.get(nid, f"N?{nid:#x}")
            if nid == 0x1e and i + 1 < len(payload):
                j = i + 1
                if nh & 0x20:  # interest id
                    while j < len(payload) and payload[j] & 0x80: j += 1
                    j += 1
                # skip declare extensions (Z flag): best effort, ext header then value
                if nh & 0x80 and j < len(payload):
                    while True:
                        eh = payload[j]; enc = (eh >> 5) & 0x3; j += 1
                        if enc == 0: pass
                        elif enc == 1:
                            while payload[j] & 0x80: j += 1
                            j += 1
                        elif enc == 2:
                            ln = 0; sh = 0
                            while True:
                                b = payload[j]; ln |= (b & 0x7f) << sh; sh += 7; j += 1
                                if not b & 0x80: break
                            j += ln
                        if not eh & 0x80: break
                if j < len(payload):
                    nn += ":" + D_IDS.get(payload[j] & 0x1f, f"D?{payload[j]&0x1f:#x}")
            net.append(nn)
    return name, net

def frames(path):
    cur = {"board->router": bytearray(), "router->board": bytearray()}
    direction = "?"; ts = ""
    for raw in open(path, "rb"):
        t = raw.decode("latin1").rstrip("\n")
        if t.startswith(">") or t.startswith("<"):
            direction = "board->router" if t[0] == ">" else "router->board"
            ts = t[13:28]
            continue
        if not t.startswith(" "): continue
        for tok in re.findall(r"[0-9a-fA-F]{2}", t[1:49]):
            b = int(tok, 16); buf = cur[direction]
            if b == 0:
                if buf:
                    yield ts, direction, bytes(buf); buf.clear()
            else:
                buf.append(b)

def main():
    path = sys.argv[1]; stats = "--stats" in sys.argv
    tfrom = None; tto = None
    for a in sys.argv[2:]:
        if a.startswith("--from="): tfrom = a[7:]
        if a.startswith("--to="): tto = a[5:]
    tot = collections.Counter(); byt = collections.Counter(); bad = collections.Counter()
    for ts, d, raw in frames(path):
        dec = cobs_decode(raw)
        byt[d] += len(raw) + 1
        if dec is None or len(dec) < 7:
            bad[d] += 1
            if not stats and (tfrom is None or ts >= tfrom) and (tto is None or ts <= tto):
                print(f"{ts} {d} UNDECODABLE {len(raw)}B")
            continue
        hdr = dec[0]; ln = int.from_bytes(dec[1:3], "little"); payload = dec[3:3+ln]
        if len(payload) != ln:
            bad[d] += 1
        name, net = classify(payload)
        tot[(d, name, tuple(net))] += 1
        if stats: continue
        if (tfrom is None or ts >= tfrom) and (tto is None or ts <= tto):
            fl = ",".join(v for k, v in {1:"INIT",2:"ACK",4:"RESET"}.items() if hdr & k) or "-"
            ss = [s for s in strings(payload)][:3]
            trunc = "" if len(payload) == ln else f" TRUNC {len(payload)}/{ln}"
            print(f"{ts} {d} ser={fl} len={ln} {name} {' '.join(net)}{trunc} {ss}")
    if stats:
        for d in byt: print(f"{d}: {byt[d]} wire bytes, {bad[d]} bad frames")
        for k, v in sorted(tot.items(), key=lambda x: -x[1])[:40]:
            print(f"  {v:6d}  {k[0]} {k[1]} {' '.join(k[2])}")

main()
