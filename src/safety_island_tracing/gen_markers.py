#!/usr/bin/env python3
"""Generate the island's trace-marker ids from the contract (phase7-W1).

The marker set is NOT typed by hand. It is read from the resolved SystemModel
(`just sync` writes build/nros/models/safety_island_bringup/system_model.yaml
from src/safety_island_bringup/launch/safety_island.contract.yaml), and one
marker is emitted per contract element that executes:

  node path        PATH_<node>_<path>_ENTRY / _EXIT     every `paths:` entry
  trigger input    TAKE_<node>_<endpoint>                every input that
                                                         triggers a path
  service client   CALL_<node>_<endpoint>                every `cli:` call site
  service server   SERVE_<node>_<endpoint>_ENTRY / _EXIT every `srv:` callback
  publisher        PUB_<node>_<endpoint>                 every contracted `pub:`

Ids are assigned in that order, sorted by contract name inside each group,
starting at 1 (0 is never a marker). A contract change regenerates the table;
the header carries the model digest and the table digest, and the running
image writes both into the trace buffer, so a trace names the table it was
recorded against.

Usage (from the repository root; `just trace-gen` runs the first):
  gen_markers.py gen      write include/island_trace_markers.h + markers.json
  gen_markers.py check    exit 1 if either file differs from a fresh generation
  gen_markers.py sites    print the marker table with the source site of each
                          ISLAND_TRACE call (markdown), and exit 1 if a marker
                          has no call site
"""
import argparse
import hashlib
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MODEL = os.path.join(ROOT, "build/nros/models/safety_island_bringup/system_model.yaml")
BRINGUP = os.path.join(ROOT, "src/safety_island_bringup")
HEADER = os.path.join(HERE, "include/island_trace_markers.h")
TABLE = os.path.join(HERE, "markers.json")
COMPONENT_DIRS = [
    "src/autoware_mrm_handler",
    "src/autoware_mrm_emergency_stop_operator",
    "src/autoware_mrm_comfortable_stop_operator",
    "src/autoware_stop_mode_operator",
]
# Integer Kconfig values stated in these files are the knobs that size the
# image; the provenance record carries the value each one had in the BUILD
# (read from autoconf.h at compile time, not from these files).
KNOB_FILES = [
    "src/native_sim_entry/prj.conf",
    "src/native_sim_entry/prj-cyclonedds.conf",
    "src/zephyr_entry/prj.conf",
    "src/zephyr_entry/boards/mr_canhubk3_s32k344.conf",
]


def c_ident(s):
    return re.sub(r"[^A-Za-z0-9]", "_", s).strip("_").upper()


def split_endpoint(ep):
    # "/mrm_handler/operation_mode_availability" -> ("mrm_handler", "operation_mode_availability")
    parts = ep.strip("/").split("/", 1)
    return parts[0], parts[1]


def load_model(path):
    with open(path) as f:
        model = yaml.safe_load(f)
    stale = []
    for inp in model.get("meta", {}).get("inputs", []):
        p = os.path.join(BRINGUP, inp["path"])
        if not os.path.exists(p):
            continue
        with open(p, "rb") as f:
            if hashlib.sha256(f.read()).hexdigest() != inp["sha256"]:
                stale.append(inp["path"])
    if stale:
        sys.exit(f"gen_markers: the model is STALE against {', '.join(stale)} -- run `just sync` first")
    return model


def build_table(model):
    c = model["contracts"]
    markers = []

    def add(name, kind, element, **extra):
        markers.append(dict(id=len(markers) + 1, name=name, kind=kind, element=element, **extra))

    paths = c.get("node_paths", {})
    for key in sorted(paths):
        p = paths[key]
        node, path = split_endpoint(key)
        trig = p.get("trigger", {})
        info = dict(node=node, trigger=trig.get("kind"))
        if "max_latency_ms" in p:
            info["max_latency_ms"] = p["max_latency_ms"]
        if trig.get("kind") == "timer":
            info["rate_hz"] = trig["value"]["rate_hz"]
        add(f"PATH_{c_ident(node)}_{c_ident(path)}_ENTRY", "path_entry", key, **info)
        add(f"PATH_{c_ident(node)}_{c_ident(path)}_EXIT", "path_exit", key, **info)
    takes = set()
    for key in sorted(paths):
        for ep in paths[key].get("input", []) or []:
            takes.add((ep, key))
    for ep, key in sorted(takes):
        node, name = split_endpoint(ep)
        add(f"TAKE_{c_ident(node)}_{c_ident(name)}", "take", ep, node=node, triggers=key)
    services = model["structure"].get("services", {})
    for srv in sorted(services):
        for ep in services[srv].get("client", []):
            node, name = split_endpoint(ep)
            add(f"CALL_{c_ident(node)}_{c_ident(name)}", "service_call", ep, node=node, service=srv)
    for srv in sorted(services):
        for ep in services[srv].get("server", []):
            node, name = split_endpoint(ep)
            add(f"SERVE_{c_ident(node)}_{c_ident(name)}_ENTRY", "service_serve_entry", ep, node=node, service=srv)
            add(f"SERVE_{c_ident(node)}_{c_ident(name)}_EXIT", "service_serve_exit", ep, node=node, service=srv)
    topics_by_pub = {}
    for topic, t in model["structure"].get("topics", {}).items():
        for ep in t.get("pub", []):
            topics_by_pub[ep] = topic
    for ep in sorted(c.get("pub_endpoints", {})):
        node, name = split_endpoint(ep)
        add(f"PUB_{c_ident(node)}_{c_ident(name)}", "publish", ep, node=node, topic=topics_by_pub.get(ep))
    return markers


def knob_names():
    names = set()
    for rel in KNOB_FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        for line in open(p):
            m = re.match(r"\s*(CONFIG_[A-Z0-9_]+)=(-?\d+|0x[0-9a-fA-F]+)\s*(#.*)?$", line)
            if m:
                names.add(m.group(1))
    # The tracing knobs themselves are always part of the provenance.
    names |= {"CONFIG_RAM_TRACING_BUFFER_SIZE", "CONFIG_TRACING_PACKET_MAX_SIZE",
              "CONFIG_TRACING_BUFFER_SIZE", "CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC"}
    return sorted(names)


def entity_counts(model):
    c = model["contracts"]
    s = model["structure"]["services"]
    timers = sum(1 for p in c.get("node_paths", {}).values() if p.get("trigger", {}).get("kind") == "timer")
    return dict(
        pub=len(c.get("pub_endpoints", {})),
        sub=len(c.get("sub_endpoints", {})),
        srv=sum(len(v.get("server", [])) for v in s.values()),
        cli=sum(len(v.get("client", [])) for v in s.values()),
        timer=timers,
    )


def render(model, markers):
    inputs = {i["path"]: i["sha256"] for i in model["meta"]["inputs"]}
    contract_sha = inputs.get("launch/safety_island.contract.yaml", "unknown")
    table_sha = hashlib.sha256(
        json.dumps([[m["id"], m["name"], m["element"]] for m in markers]).encode()).hexdigest()
    counts = entity_counts(model)
    knobs = knob_names()
    out = []
    w = out.append
    w("/* GENERATED by src/safety_island_tracing/gen_markers.py -- DO NOT EDIT.")
    w(" *")
    w(" * Trace-marker ids for the safety island, one per executing contract element")
    w(" * of src/safety_island_bringup/launch/safety_island.contract.yaml, read from")
    w(" * the resolved model (`just sync`). Regenerate with `just trace-gen`; the")
    w(" * meaning of every id is in markers.json beside this file and in")
    w(" * docs/tracing.md. */")
    w("#ifndef ISLAND_TRACE_MARKERS_H")
    w("#define ISLAND_TRACE_MARKERS_H")
    w("")
    w(f'#define ISLAND_TRACE_CONTRACT_SHA256 "{contract_sha}"')
    w(f'#define ISLAND_TRACE_TABLE_SHA256 "{table_sha}"')
    w(f"#define ISLAND_TRACE_MARKER_COUNT {len(markers)}")
    w('#define ISLAND_TRACE_ENTITIES "pub={pub},sub={sub},srv={srv},cli={cli},timer={timer}"'.format(**counts))
    w("")
    width = max(len(m["name"]) for m in markers) + len("ISLAND_MK_")
    for m in markers:
        w(f"#define {('ISLAND_MK_' + m['name']).ljust(width)} {m['id']:3d} /* {m['kind']:<20} {m['element']} */")
    w("")
    w("/* Knobs that size the image, as the build delivered them (autoconf.h). */")
    for k in knobs:
        short = k[len("CONFIG_"):]
        w(f"#ifdef {k}")
        w(f'#define ISLAND_TRACE_KNOB_{short} ";{short}=" ISLAND_TRACE_STR({k})')
        w("#else")
        w(f'#define ISLAND_TRACE_KNOB_{short} ""')
        w("#endif")
    w("#define ISLAND_TRACE_KNOBS \\")
    for k in knobs:
        w(f"  ISLAND_TRACE_KNOB_{k[len('CONFIG_'):]} \\")
    w("  \"\"")
    w("")
    w("#endif /* ISLAND_TRACE_MARKERS_H */")
    header = "\n".join(out) + "\n"
    table = json.dumps(dict(
        generator="src/safety_island_tracing/gen_markers.py",
        contract_sha256=contract_sha,
        table_sha256=table_sha,
        entities=counts,
        knobs=knobs,
        markers=markers,
    ), indent=1) + "\n"
    return header, table


def find_sites(markers):
    sites = {m["name"]: [] for m in markers}
    pat = re.compile(r"ISLAND_TRACE\(\s*ISLAND_MK_([A-Z0-9_]+)")
    func = re.compile(r"^[A-Za-z][\w:<>,\s\*&]*?\b([A-Za-z_][\w]*::[A-Za-z_]\w*)\s*\(")
    for d in COMPONENT_DIRS:
        for dirpath, _, files in os.walk(os.path.join(ROOT, d)):
            for fn in sorted(files):
                if not fn.endswith((".cpp", ".hpp", ".c", ".h")):
                    continue
                p = os.path.join(dirpath, fn)
                cur = "?"
                for n, line in enumerate(open(p, encoding="utf-8"), 1):
                    fm = func.match(line)
                    if fm:
                        cur = fm.group(1).split("::")[-1]
                    for mm in pat.finditer(line):
                        sites.setdefault(mm.group(1), []).append(
                            f"{os.path.relpath(p, ROOT)}:{n} ({cur})")
    return sites


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["gen", "check", "sites"])
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()
    if not os.path.exists(a.model):
        sys.exit(f"gen_markers: no resolved model at {a.model} -- run `just sync` first")
    model = load_model(a.model)
    markers = build_table(model)
    header, table = render(model, markers)
    if a.cmd == "gen":
        os.makedirs(os.path.dirname(HEADER), exist_ok=True)
        open(HEADER, "w").write(header)
        open(TABLE, "w").write(table)
        print(f"gen_markers: {len(markers)} markers -> {os.path.relpath(HEADER, ROOT)}, {os.path.relpath(TABLE, ROOT)}")
        return 0
    if a.cmd == "check":
        bad = [p for p, want in ((HEADER, header), (TABLE, table))
               if not os.path.exists(p) or open(p).read() != want]
        for p in bad:
            print(f"gen_markers: {os.path.relpath(p, ROOT)} is stale against the model -- run `just trace-gen`")
        if not bad:
            print(f"gen_markers: header and table current ({len(markers)} markers)")
        return 1 if bad else 0
    sites = find_sites(markers)
    known = {m["name"] for m in markers}
    missing = 0
    print("| id | marker | contract element | source site |")
    print("| ---: | --- | --- | --- |")
    for m in markers:
        s = sites.get(m["name"]) or []
        if not s:
            missing += 1
        print(f"| {m['id']} | `{m['name']}` | `{m['element']}` ({m['kind']}) | "
              f"{'<br>'.join(s) if s else '**NO CALL SITE**'} |")
    unknown = sorted(set(sites) - known)
    for u in unknown:
        print(f"gen_markers: call site names an unknown marker ISLAND_MK_{u}", file=sys.stderr)
    if missing:
        print(f"gen_markers: {missing} marker(s) have no call site", file=sys.stderr)
    return 1 if (missing or unknown) else 0


if __name__ == "__main__":
    sys.exit(main())
