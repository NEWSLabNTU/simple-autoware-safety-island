#!/usr/bin/env python3
"""The LED record against the trace, for one act (CARLA demo unit C5).

  led_vs_trace.py <run dir> [--led <led_readout output>] [--tick-ms 100]

The booth image (CONFIG_ISLAND_LED, snippet island-booth) keeps the last 8
LED transitions with the island's uptime (island_led_record; read after the
act with `led_readout.py --elf <elf> > <run dir>/led.txt`). The trace keeps
every mrm_state the handler published (PUB_MRM_HANDLER_MRM_STATE, value
state << 16 | behavior) and every takeover-request state
(PUB_MRM_HANDLER_TAKEOVER_REQUEST_STATE, 2 = on), on the island's clock
(island.jsonl `island_ns`, merge.py). Both are stamped in the same handler
tick (the LED is set after publishHazardCmd()), so each edge of the act
should appear in both within one tick:

  edge            trace (island ms)   LED (uptime ms)   LED - trace
  mrm_operating   ...                 ...               ...

and the act's mrm_operating -> mrm_succeeded duration is also given from the
host's probe edges (table.md), the comparison section 3.3 made for led-e3.
Exit 0 when every edge the act has is matched within --tick-ms.
"""
import argparse
import json
import os
import re
import sys

STATE = {"NORMAL": 1, "MRM_OPERATING": 2, "MRM_SUCCEEDED": 3, "MRM_FAILED": 4}
BEH = {"NONE": 1, "EMERGENCY_STOP": 2, "COMFORTABLE_STOP": 3, "PULL_OVER": 4}
LINE = re.compile(r"#(\d+)\s+([0-9.]+) s\s+([A-Z_]+)(?:/([A-Z_]+))?( \+takeover)?\s+-> (.+)$")


def led_transitions(path):
    out = []
    for line in open(path):
        m = LINE.search(line.rstrip())
        if m:
            out.append(dict(n=int(m.group(1)), up_ms=float(m.group(2)) * 1000, state=STATE.get(m.group(3)),
                            beh=BEH.get(m.group(4) or "NONE"), tor=bool(m.group(5)), pattern=m.group(6).strip()))
    return out


def trace_edges(run):
    mk = []
    for line in open(os.path.join(run, "island.jsonl")):
        e = json.loads(line)
        if e.get("kind") == "marker" and e.get("marker") in ("PUB_MRM_HANDLER_MRM_STATE",
                                                            "PUB_MRM_HANDLER_TAKEOVER_REQUEST_STATE"):
            mk.append(e)
    mk.sort(key=lambda e: e["island_ns"])
    edges, last_mrm, last_tor = [], None, None
    for e in mk:
        ms = e["island_ns"] / 1e6
        if e["marker"] == "PUB_MRM_HANDLER_MRM_STATE":
            v = (e["value"] >> 16, e["value"] & 0xFFFF)
            if v != last_mrm:  # the trace keeps a publish only on a change (filtered)
                name = {2: "mrm_operating", 3: "mrm_succeeded", 1: "normal", 4: "mrm_failed"}.get(v[0], str(v))
                edges.append(dict(edge=name, ms=ms, state=v[0], beh=v[1]))
            last_mrm = v
        else:
            on = e["value"] == 2
            if on != last_tor:
                edges.append(dict(edge="tor_on" if on else "tor_off", ms=ms, tor=on))
            last_tor = on
    return edges


def host_edges(run):
    t = open(os.path.join(run, "table.md")).read() if os.path.exists(os.path.join(run, "table.md")) else ""
    m = re.search(r"^edges \(ms from the button\): (.*)$", t, re.M)
    out = {}
    for kv in (m.group(1).split(", ") if m else []):
        k, _, v = kv.partition(" ")
        try:
            out[k] = float(v)
        except ValueError:
            pass
    return out


def match(edge, leds):
    """The LED transition the edge caused: same state (and behavior), or the
    takeover flag's change, nearest in time."""
    def ok(l):
        if edge["edge"] == "tor_on":
            return l["tor"] and l["state"] == 1
        if edge["edge"] == "tor_off":  # the LED leaves the takeover pattern, for G or an MRM's
            return not l["tor"]
        return l["state"] == edge["state"] and (edge["state"] == 1 or l["beh"] == edge["beh"])
    c = [l for l in leds if ok(l)]
    return min(c, key=lambda l: abs(l["up_ms"] - edge["ms"])) if c else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--led", default=None)
    ap.add_argument("--tick-ms", type=float, default=100.0)
    a = ap.parse_args()
    leds = led_transitions(a.led or os.path.join(a.run, "led.txt"))
    edges = trace_edges(a.run)
    lo = min((l["up_ms"] for l in leds), default=0)
    edges = [e for e in edges if e["ms"] >= lo - a.tick_ms]  # the ring keeps the last 8 only
    print(f"{os.path.basename(a.run.rstrip('/'))}: {len(edges)} trace edges in the LED ring's span, "
          f"{len(leds)} LED transitions")
    print("| edge | trace, island ms | LED, uptime ms | LED pattern | LED - trace ms | within a tick |")
    print("|---|---|---|---|---|---|")
    bad = 0
    for e in edges:
        l = match(e, leds)
        if l is None:
            bad += 1
            print(f"| {e['edge']} | {e['ms']:.1f} | - | - | - | NO |")
            continue
        d = l["up_ms"] - e["ms"]
        ok = abs(d) <= a.tick_ms
        bad += not ok
        print(f"| {e['edge']} | {e['ms']:.1f} | {l['up_ms']:.0f} | {l['pattern']} | {d:+.1f} | {'yes' if ok else 'NO'} |")
    h = host_edges(a.run)
    led_op = next((x for x in edges if x["edge"] == "mrm_operating"), None)
    led_su = next((x for x in edges if x["edge"] == "mrm_succeeded"), None)
    if led_op and led_su and "mrm_operating" in h and "mrm_succeeded" in h:
        lo_, ls_ = match(led_op, leds), match(led_su, leds)
        if lo_ and ls_:
            print(f"mrm_operating -> mrm_succeeded: LED {ls_['up_ms'] - lo_['up_ms']:.0f} ms, "
                  f"trace (island) {led_su['ms'] - led_op['ms']:.1f} ms, "
                  f"host probe {h['mrm_succeeded'] - h['mrm_operating']:.1f} ms")
    print("LED vs trace: " + ("PASS" if bad == 0 and edges else "FAIL"))
    return 0 if bad == 0 and edges else 1


if __name__ == "__main__":
    sys.exit(main())
