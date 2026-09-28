"""Shared pieces of the phase-8 timeline (unit phase8-W7).

The event schema, one JSON object per line, ASCII:

  t_mono_ns  int    CLOCK_MONOTONIC of the host, ns (time.monotonic_ns());
                    island markers are mapped onto it by merge.py
  source     str    probe | gate | scenario | island | observer | timeline
  kind       str    what happened (see below)
  hazard     str    hazard name, when the event belongs to one, else null
  rung       str    ladder rung (mode) name, when the event belongs to one
  marker     str    island trace marker name, or the event's own name
  value             the payload: a number, a string or a small object

Kinds written by the tools here:

  probe     predicate  a `when:` predicate changed truth (hazard or function)
            sample     one sample of a topic the probe watches (value = the
                       fields the timeline reads)
            velocity   |v| from /localization/kinematic_state, m/s
  gate      publish    the availability gate's first sample with a new
                       `autonomous` value (the fault on the wire)
            odd        the gate's ODD flag changed (value = true on exit)
            stall      the gate's timer (marker tick) or the raw stream (marker
                       availability_raw) was late by more than 250 ms
            last       the gate's last sample before a SIGSTOP (written by
                       the scenario, which knows the gate's count)
  scenario  inject     a button: odd_exit, odd_enter, takeover, hpc_loss,
                       hpc_restore (value = the button's detail)
  island    marker     one island trace marker, aligned (value = its arg)
            align      the alignment itself (value = offsets, disagreement)

This module also reads the declared side: the resolved SystemModel (topic
types, the contract inputs and their sha256), the contract sidecar the model
was resolved from (the `when:`, `window:`, `exit:` and `entry_speed` keys,
which play_launch 92043c82 checks but does not write into the SystemModel),
and the fault-reaction table of `play_launch check --explain`.
"""
import hashlib
import json
import math
import os
import re
import subprocess
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MODEL = os.path.join(ROOT, "build/nros/models/safety_island_bringup/system_model.yaml")
BRINGUP = os.path.join(ROOT, "src/safety_island_bringup")
LAUNCH = os.path.join(BRINGUP, "launch/safety_island.launch.xml")
PLAY_LAUNCH_W6 = "/home/aeon/repos/play_launch/install/play_launch/lib/play_launch/play_launch"

# Message constants the timeline names (tier4 / autoware msgs, 1.5.0).
MRM_STATE = {0: "UNKNOWN", 1: "NORMAL", 2: "MRM_OPERATING", 3: "MRM_SUCCEEDED", 4: "MRM_FAILED"}
MRM_BEHAVIOR = {0: "UNKNOWN", 1: "NONE", 2: "EMERGENCY_STOP", 3: "COMFORTABLE_STOP", 4: "PULL_OVER"}
BEHAVIOR_STATUS = {0: "NOT_AVAILABLE", 1: "AVAILABLE", 2: "OPERATING"}
CONTROL_MODE = {0: "NO_COMMAND", 1: "AUTONOMOUS", 2: "AUTONOMOUS_STEER_ONLY",
                3: "AUTONOMOUS_VELOCITY_ONLY", 4: "MANUAL", 5: "DISENGAGED", 6: "NOT_READY"}
HAZARD_LIGHTS = {0: "NO_COMMAND", 1: "DISABLE", 2: "ENABLE"}
STOPPED_MPS = 0.001  # mrm_handler's isStopped() threshold


# ------------------------------------------------------------ events ----
def now_ns():
    return time.monotonic_ns()


def event(source, kind, hazard=None, rung=None, marker=None, value=None, t_mono_ns=None, **extra):
    ev = dict(t_mono_ns=int(t_mono_ns if t_mono_ns is not None else now_ns()), source=source,
              kind=kind, hazard=hazard, rung=rung, marker=marker, value=value)
    ev.update(extra)
    return ev


class Writer:
    """Line-buffered JSONL writer; every line is flushed, so a tail sees it."""

    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.f = open(path, "a", buffering=1)

    def write(self, source, kind, **kw):
        ev = event(source, kind, **kw)
        self.f.write(json.dumps(ev, ensure_ascii=True) + "\n")
        return ev

    def close(self):
        self.f.close()


def read_events(paths):
    out = []
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue  # a line being written
    out.sort(key=lambda e: e["t_mono_ns"])
    return out


class Tail:
    """Incremental reader of a growing JSONL file (the live view's input)."""

    def __init__(self, path):
        self.path, self.pos, self.buf = path, 0, ""

    def poll(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path) as f:
            f.seek(self.pos)
            chunk = f.read()
            self.pos = f.tell()
        self.buf += chunk
        lines = self.buf.split("\n")
        self.buf = lines.pop()
        out = []
        for line in lines:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out


def run_files(run_dir):
    return sorted(os.path.join(run_dir, f) for f in os.listdir(run_dir) if f.endswith(".jsonl"))


# ------------------------------------------------------- the declared ----
def load_model(path=MODEL):
    """The resolved SystemModel, refused when stale against its inputs."""
    with open(path) as f:
        model = yaml.safe_load(f)
    stale = []
    for inp in model.get("meta", {}).get("inputs", []):
        p = os.path.join(BRINGUP, inp["path"])
        if os.path.exists(p):
            with open(p, "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() != inp["sha256"]:
                    stale.append(inp["path"])
    if stale:
        raise SystemExit(f"timeline: the model is STALE against {', '.join(stale)} -- run `just sync`")
    return model


def contract_path(model):
    for inp in model["meta"]["inputs"]:
        if inp["path"].endswith(".contract.yaml"):
            return os.path.join(BRINGUP, inp["path"])
    raise SystemExit("timeline: the model records no contract input")


class YamlLoader(yaml.SafeLoader):
    """YAML 1.2 booleans: `on:` is a key, not True (PyYAML is YAML 1.1)."""


YamlLoader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}
YamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"))


def _pred(w):
    ops = [k for k in ("equals", "not_equals", "lt", "le", "gt", "ge") if k in w]
    return dict(field=w["field"], op=ops[0], value=w[ops[0]])


def declared(model=None):
    """What the probe and the timeline need, from the model and its contract.

    topics:     topic -> message type (the model)
    predicates: list of {name, kind: hazard|function, topic, field, op, value}
    windows:    rung -> {duration_ms, param}
    exits:      rung -> {on, to}
    entry_speed: hazard -> m/s
    hazards:    hazard -> {on, ftti_ms, severity}
    """
    model = model or load_model()
    with open(contract_path(model)) as f:
        c = yaml.load(f, Loader=YamlLoader)
    topics = {t: v.get("type") for t, v in model["structure"]["topics"].items()}
    preds = []
    for name, fn in (c.get("functions") or {}).items():
        if isinstance(fn, dict) and fn.get("when"):
            for t in fn.get("of", []):
                preds.append(dict(name=name, kind="function", topic=t, **_pred(fn["when"])))
    hazards, entry = {}, {}
    for name, hz in (c.get("hazards") or {}).items():
        hazards[name] = dict(on=hz.get("on"), ftti_ms=duration_ms(hz.get("ftti")),
                             severity=hz.get("severity"), guards=hz.get("guards", []))
        if hz.get("entry_speed") is not None:
            entry[name] = float(hz["entry_speed"])
        if hz.get("when"):
            for t in hz.get("guards", []):
                preds.append(dict(name=name, kind="hazard", topic=t, **_pred(hz["when"])))
    windows, exits = {}, {}
    for name, m in (c.get("modes") or {}).items():
        w = m.get("window")
        if w is not None:
            windows[name] = dict(duration_ms=duration_ms(w["duration"] if isinstance(w, dict) else w),
                                 param=w.get("param") if isinstance(w, dict) else None)
        if m.get("exit"):
            exits[name] = dict(m["exit"])
    return dict(topics=topics, predicates=preds, windows=windows, exits=exits,
                entry_speed=entry, hazards=hazards, contract=contract_path(model))


def duration_ms(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) * 1000.0
    m = re.match(r"^\s*([0-9.]+)\s*(ns|us|ms|s)\s*$", str(v))
    if not m:
        raise ValueError(f"not a duration: {v!r}")
    return float(m.group(1)) * {"ns": 1e-6, "us": 1e-3, "ms": 1.0, "s": 1000.0}[m.group(2)]


def resolve_constant(topic_type, field, value):
    """A message constant name (MANUAL) -> its number, read from the .msg."""
    if not isinstance(value, str) or not re.match(r"^[A-Z][A-Z0-9_]*$", value):
        return value
    pkg, _, name = topic_type.split("/")
    for prefix in os.environ.get("AMENT_PREFIX_PATH", "").split(":"):
        p = os.path.join(prefix, "share", pkg, "msg", name + ".msg")
        if os.path.exists(p):
            for line in open(p):
                m = re.match(r"^\s*\w+\s+" + value + r"\s*=\s*(-?\d+)", line)
                if m:
                    return int(m.group(1))
    raise SystemExit(f"timeline: constant {value} of {topic_type} not found on AMENT_PREFIX_PATH")


def evaluate(pred, msg_value):
    op, v = pred["op"], pred["value_resolved"]
    return {"equals": msg_value == v, "not_equals": msg_value != v, "lt": msg_value < v,
            "le": msg_value <= v, "gt": msg_value > v, "ge": msg_value >= v}[op]


def get_field(msg, dotted):
    for part in dotted.split("."):
        msg = getattr(msg, part)
    return msg


# ---------------------------------------------- the checker's arithmetic ----
def explain_text(launch=LAUNCH, play_launch=None):
    """`play_launch check <launch> --explain`, colour codes stripped."""
    pl = play_launch or os.environ.get("PLAY_LAUNCH_CHECK") or (
        PLAY_LAUNCH_W6 if os.path.exists(PLAY_LAUNCH_W6) else "play_launch")
    r = subprocess.run([pl, "check", os.path.basename(launch), "--explain"], cwd=os.path.dirname(launch),
                       capture_output=True, text=True)
    return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)


def _num(tok):
    return None if tok == "-" else float(tok)


def parse_explain(text):
    """The `-- Fault-reaction budgets (--explain, ms) --` table, as rows.

    Each row: hazard, rung, role (rung | floor | window | skipped), detect,
    windows, route, settle, settle_kind (derived | literal | window), total,
    ftti, slack; ms, None where the table prints '-'.
    """
    rows, on = [], False
    for line in text.splitlines():
        if line.startswith("-- Fault-reaction budgets"):
            on = True
            continue
        if not on:
            continue
        if line.startswith("HAZARD"):
            continue
        tok = line.split()
        if not tok or line.startswith(" "):
            if rows and (not tok or not line.startswith("  ")):
                break
            continue
        hazard, rung, role = tok[0], tok[1], tok[2]
        rest = tok[3:]
        detect, windows, route = _num(rest[0]), _num(rest[1]), _num(rest[2])
        if rest[3] == "window":
            settle, kind, rest2 = _num(rest[4]), "window", rest[5:]
        elif rest[3] == "-":
            settle, kind, rest2 = None, None, rest[4:]
        else:
            settle, kind, rest2 = _num(rest[3]), rest[4], rest[5:]
        total, ftti, slack = _num(rest2[0]), _num(rest2[1]), _num(rest2[2])
        rows.append(dict(hazard=hazard, rung=rung, role=role, detect=detect, windows=windows,
                         route=route, settle=settle, settle_kind=kind, total=total, ftti=ftti,
                         slack=slack))
    return rows


# --------------------------------------------------- the plant model ----
def settle_s(v0, decel, jerk):
    """rlm's SettleProfile::settle_s: a = |decel|, j = |jerk|."""
    a, j = abs(decel), abs(jerk)
    vr = a * a / (2 * j)
    if v0 <= vr:
        return math.sqrt(2 * v0 / j)
    return a / j + (v0 - vr) / a


def stop_curve(v0, decel, jerk, n=200):
    """v(t) of the jerk-limited stop from v0, for the dashed derived curve."""
    a, j = abs(decel), abs(jerk)
    T = settle_s(v0, decel, jerk)
    out = []
    for i in range(n + 1):
        t = T * i / n
        if t <= a / j and v0 > a * a / (2 * j):
            v = v0 - 0.5 * j * t * t
        elif v0 <= a * a / (2 * j):
            v = max(v0 - 0.5 * j * t * t, 0.0)
        else:
            v = v0 - a * a / (2 * j) - a * (t - a / j)
        out.append((t, max(v, 0.0)))
    return out


# ------------------------------------------------------------ selftest ----
def selftest(path=os.path.join(HERE, "testdata/explain.txt")):
    """What the timeline takes from the checker still reads the same (CI).

    testdata/explain.txt is the `--explain` output of play_launch 92043c82 on
    the live contract (the settle-derived lines and the budget table, as
    captured in the W7 runs). The timeline's declared bars are parse_explain()
    of that table and its dashed stop curve is settle_s(); both must agree
    with the checker's own numbers, or every bar drawn is wrong.
    """
    import analysis
    text = open(path).read()
    rows = parse_explain(text)
    by = {(r["hazard"], r["rung"]): r for r in rows}
    fails = []

    def check(what, ok):
        print(("ok   " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)
    check(f"{len(rows)} budget rows parsed (want 6)", len(rows) == 6)
    for (hz, rung), r in sorted(by.items()):
        if r["role"] in ("rung", "floor"):
            s = r["detect"] + r["windows"] + r["route"] + r["settle"]
            check(f"{hz}/{rung}: DETECT+WINDOWS+ROUTE+SETTLE {s:.2f} = TOTAL {r['total']:.2f}",
                  abs(s - r["total"]) < 0.02)
    prof = analysis.settle_profiles(text)
    check(f"{len(prof)} settle-derived profiles parsed (want 3)", len(prof) == 3)
    for (hz, rung), (a, j, v0) in sorted(prof.items()):
        r = by.get((hz, rung))
        mine = settle_s(v0, a, j) * 1000
        check(f"{hz}/{rung}: settle_s({v0}, a {a}, j {j}) {mine:.2f} = checker {r and r['settle']}",
              r is not None and abs(mine - r["settle"]) < 0.02)
    w = by.get(("odd_exit", "takeover_request"), {})
    check(f"odd_exit/takeover_request: a window of {w.get('settle')} ms", w.get("settle_kind") == "window")
    print("selftest: " + ("OK" if not fails else f"{len(fails)} FAILED"))
    return 0 if not fails else 1


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["selftest"]:
        sys.exit(selftest())
    sys.exit("usage: tlcommon.py selftest")
