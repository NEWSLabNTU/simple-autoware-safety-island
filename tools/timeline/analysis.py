"""Declared against observed, for one run (phase8-W7). Used by the live view,
the renderer and the per-run tables in docs/takeover-trace.md.

Declared: the rows of `play_launch check --explain` (tlcommon.parse_explain)
and the braking profiles its `settle-derived` lines print. Observed: edges
found in the run's events (host CLOCK_MONOTONIC; island markers aligned by
merge.py). All times here are ms from the first injection (the button).

The act is read from the injections: odd_exit and a takeover is branch A,
odd_exit alone branch B, hpc_loss the encore.

The window (phase8-W12). `window:` is a LEAST time: the request lasts at
least the window, and the checker charges it up to the DEADLINE (request on
+ window); the rung below is charged its route FROM the deadline, and that
route's first hop (mrm_handler/call_mrm) is where the late notice of the
deadline is charged (play_launch `window-expiry`). On the board that hop is
206 ms = the serial link in 57 + the tick 118 (100 + jitter) + in-tick work
31 (phase8-W30; 110 ms, the tick + a 10 ms call, until then; the derivation
is in the island contract at `call_mrm`). So branch B is cut at the deadline, a derived
instant (the request-on edge plus the declared, parameter-bound window),
never at the request-off edge, which lies inside the route below; the
verdict -> velocity limit row needs no derived instant at all.

Clocks (phase8-W30). The detect, host and `windows + route, host` rows are
host clock only; the dwell, route and exit rows are island clock only. The
takeover route, `windows` and `windows + route` compare an island edge with
the gate's host stamp, through merge.py's offset, the smallest
publish->receipt pair: a receipt is never before its publish, so that offset
never puts an island edge EARLIER than it happened, and those rows are
over-stated by the smallest out-link delay, never under-stated. They say so
in their note.
"""
import re

import yaml

import tlcommon as tl

# The tick share of mrm_handler/call_mrm on the board: the 100 ms period of
# update_rate 10 plus 18 ms of jitter (ticks up to 114.84 ms apart on the
# S32K344; island contract, phase8-W30). The encore's detect row adds it back
# (below). rlm has no key for the share, so it is stated here.
TICK_MS = 118.0
CROSS = "island vs host clock"  # the note on a cross-clock row (module doc)
HPC_TIMEOUT_MS = 500.0  # mrm_handler timeout_operation_mode_availability: hpc_loss
# What checks a row's declared value besides this trace check (phase10-B8):
# the checker's fault-reaction sum (a term of a total held to the FTTI), the
# island's runtime monitor (a deadline or max_age compiled into the image),
# or nothing but the trace.
SUM, MON, TRACE = "checker sum, trace", "runtime monitor, trace", "trace"


def settle_profiles(explain):
    """(hazard, rung) -> (a, j, v0) from the checker's settle-derived lines."""
    out = {}
    for m in re.finditer(r"hazard '(\w+)', rung '(\w+)': settle from .*?a = \|\w+\| = ([0-9.]+) m/s\^2, "
                         r"j = \|\w+\| = ([0-9.]+) m/s\^3, v0 = entry_speed ([0-9.]+) m/s", explain):
        out[(m.group(1), m.group(2))] = (float(m.group(3)), float(m.group(4)), float(m.group(5)))
    return out


def settle_responses(explain, contract=None):
    """(hazard, rung) -> the settle's declared response delay in ms (phase10-B2).

    The response is the time from the safe command to the vehicle's first
    braking, stated beside the braking profile (`settle: { decel, jerk,
    response }`); the settle is then profile + response. Read from the
    settle-derived line when the checker prints it there, else from the
    contract sidecar's `settle:` of the node the line names (the contract
    as it is now, not as the run had it; `contract=False` reads none).
    Absent when neither states one."""
    out = {}
    c = None if contract is not False else {}
    for m in re.finditer(r"^.*hazard '(\w+)', rung '(\w+)': settle from (\S+)'s braking profile.*$", explain, re.M):
        key, line = (m.group(1), m.group(2)), m.group(0)
        r = re.search(r"response\D{0,24}?([0-9.]+)\s*ms", line)
        if r:
            out[key] = float(r.group(1))
            continue
        if c is None:
            try:
                with open(contract or tl.LAUNCH.replace(".launch.xml", ".contract.yaml")) as f:
                    c = yaml.load(f, Loader=tl.YamlLoader) or {}
            except OSError:
                c = {}
        node = ((c.get("nodes") or {}).get(m.group(3).strip("/")) or {})
        for path in (node.get("paths") or {}).values():
            st = ((path or {}).get("safe_state") or {}).get("settle")
            if isinstance(st, dict) and st.get("response") is not None:
                out[key] = tl.duration_ms(st["response"])
    return out


def declared_transports(explain, contract=None):
    """topic -> (max_transport ms, charged) for each declared per-subscriber
    `max_transport` (phase10-B8). From the run's own `--explain` first: a
    route's `link X ms (max_transport into '<topic>'` (charged by the
    checker's sum) and `info[declared-not-charged]` (stated, not charged);
    then any other the contract sidecar declares now (charged unknown, None)."""
    out = {}
    for m in re.finditer(r"link ([0-9.]+)ms \(max_transport into '([^']+)'", explain):
        out[m.group(2)] = (float(m.group(1)), True)
    for m in re.finditer(r"`nodes\.\w+\.sub\.\w+\.max_transport: ([0-9.]+\s*\w+)` on '([^']+)' is not charged",
                         explain):
        out.setdefault(m.group(2), (tl.duration_ms(m.group(1)), False))
    try:
        with open(contract or tl.LAUNCH.replace(".launch.xml", ".contract.yaml")) as f:
            c = yaml.load(f, Loader=tl.YamlLoader) or {}
    except OSError:
        c = {}
    for node, nd in (c.get("nodes") or {}).items():
        for sub, v in ((nd or {}).get("sub") or {}).items():
            if isinstance(v, dict) and v.get("max_transport") is not None:
                out.setdefault(f"/{node}/{sub}", (tl.duration_ms(v["max_transport"]), None))
    return out


def _host_edges_availability(ev):
    """The gate's publishes of a new `autonomous` value: (host ns, island arg)."""
    return [(e["t_mono_ns"], 1 if e["value"]["autonomous"] else 0) for e in ev
            if e["source"] == "gate" and e["kind"] == "publish"]


def _host_edges_control_mode(ev):
    """The probe's receipts of a new control mode: (host ns, island arg).
    A receipt, not the publish: the publisher -> probe delay is not in it."""
    return [(e["t_mono_ns"], e["value"]["mode"]) for e in ev
            if e["source"] == "probe" and e.get("marker") == "control_mode" and e["kind"] == "sample"]


# The edges whose host side the run records: topic -> (island take marker,
# host edges, what the host stamp is, how far after it a take is looked for).
LINK_EDGES = {
    "/mrm_handler/operation_mode_availability": ("TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY",
                                                 _host_edges_availability, "gate publish", 500_000_000),
    "/mrm_handler/control_mode": ("TAKE_MRM_HANDLER_CONTROL_MODE", _host_edges_control_mode,
                                  "probe receipt", 1_000_000_000),
}


def link_hops(ev, marker, host_edges, horizon_ns):
    """Host stamp -> the island's take of the same value, ms, per host edge
    (terms.py's `link`): the first take of the new value whose previous take
    differs, from 50 ms before the host stamp (alignment error) and within
    `horizon_ns`. Cross-clock, over-stated by the smallest out-link delay
    (the module doc)."""
    takes = [e for e in ev if e["source"] == "island" and e.get("marker") == marker]
    out = []
    for t, want in host_edges:
        prev = None
        for e in takes:
            if e["t_mono_ns"] >= t - 50_000_000 and e["value"] == want and (prev is None or prev["value"] != want):
                if e["t_mono_ns"] - t < horizon_ns:
                    out.append((e["t_mono_ns"] - t) / 1e6)
                break
            prev = e
    return out


def _first(ev, pred, after=None, before=None):
    for e in ev:
        t = e["t_mono_ns"]
        if after is not None and t < after:
            continue
        if before is not None and t > before:
            return None
        if pred(e):
            return e
    return None


def _last(ev, pred, before):
    out = None
    for e in ev:
        if e["t_mono_ns"] > before:
            break
        if pred(e):
            out = e
    return out


def isl(name, arg=None):
    return lambda e: e["source"] == "island" and e.get("marker") == name and (arg is None or arg(e["value"]))


def probe(marker, pred=lambda v: True):
    return lambda e: e["source"] == "probe" and e.get("marker") == marker and pred(e["value"])


def act_of(ev):
    inj = [e["marker"] for e in ev if e["source"] == "scenario" and e["kind"] == "inject"]
    if "hpc_loss" in inj:
        return "encore"
    if "odd_exit" in inj:
        return "a" if "takeover" in inj else "b"
    return None


def velocity_at(ev, t):
    e = _last(ev, lambda e: e["source"] == "probe" and e["kind"] == "velocity", before=t)
    return e["value"] if e else None


def standstill(ev, after):
    """First velocity sample below mrm_handler's 0.001 m/s after `after`."""
    e = _first(ev, lambda e: e["source"] == "probe" and e["kind"] == "velocity" and e["value"] < tl.STOPPED_MPS,
               after=after)
    return e["t_mono_ns"] if e else None


# The serial link whose hop bounds the host-side window dwell's slack.
DWELL_LINK_TOPIC = "/mrm_handler/operation_mode_availability"


def analyze(ev, rows, explain="", windows=None, entry_speed=None):
    """Everything the plots and tables need, or None before the first injection."""
    act = act_of(ev)
    injects = [e for e in ev if e["source"] == "scenario" and e["kind"] == "inject"]
    if not act:
        return None
    hazard = "hpc_loss" if act == "encore" else "odd_exit"
    press = next(e for e in injects if e["marker"] == ("hpc_loss" if act == "encore" else "odd_exit"))
    t0 = press["t_mono_ns"]
    ms = lambda t: None if t is None else (t - t0) / 1e6  # noqa: E731
    d = lambda a, b: None if a is None or b is None else (b - a) / 1e6  # noqa: E731
    E, obs, notes = {"press": t0}, {}, []
    prof = settle_profiles(explain)
    windows = windows or {}
    entry_speed = entry_speed or {}
    win_ms = (windows.get("takeover_request") or {}).get("duration_ms", 10000.0)
    have_island = any(e["source"] == "island" and e["kind"] == "marker" for e in ev)
    align = next((e["value"] for e in ev if e["source"] == "island" and e["kind"] == "align"), None)

    def t_of(e):
        return e["t_mono_ns"] if e else None

    if act in ("a", "b"):
        E["fault_on_wire"] = t_of(_first(ev, lambda e: e["source"] == "gate" and e["kind"] == "publish"
                                          and e["value"]["autonomous"] is False, after=t0))
        E["island_take"] = t_of(_first(ev, isl("TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY", lambda a: a == 0),
                                       after=t0 - 50_000_000))
        E["host_take"] = t_of(_first(ev, probe("availability", lambda v: v["autonomous"] is False), after=t0))
        E["tor_on"] = t_of(_first(ev, isl("PUB_MRM_HANDLER_TAKEOVER_REQUEST_STATE", lambda a: a == 2),
                                  after=t0 - 50_000_000)) if have_island else \
            t_of(_first(ev, probe("takeover_request_state", lambda v: v == "OPERATING"), after=t0))
        after_on = E["tor_on"] or t0
        E["tor_off"] = t_of(_first(ev, isl("PUB_MRM_HANDLER_TAKEOVER_REQUEST_STATE", lambda a: a != 2),
                                   after=after_on + 1)) if have_island else \
            t_of(_first(ev, probe("takeover_request_state", lambda v: v != "OPERATING"), after=after_on + 1))
        E["hazard_lights_on"] = t_of(_first(ev, probe("vehicle_hazard_lights", lambda v: v == "ENABLE"), after=t0))
        E["island_hazard_cmd_on"] = t_of(_first(ev, probe("island_hazard_lights_cmd", lambda v: v == "ENABLE"),
                                                after=t0))
        # Host-side receipts of the request, beside the island's own edges.
        E["tor_on_host"] = t_of(_first(ev, probe("takeover_request_state", lambda v: v == "OPERATING"), after=t0))
        E["tor_off_host"] = t_of(_first(ev, probe("takeover_request_state", lambda v: v != "OPERATING"),
                                        after=(E["tor_on_host"] or t0) + 1))
        obs["detect"] = d(t0, E["fault_on_wire"])
        obs["tor_route"] = d(E["fault_on_wire"], E["tor_on"])
        obs["dwell"] = d(E["tor_on"], E["tor_off"])
        obs["dwell_host"] = d(E["tor_on_host"], E["tor_off_host"])
        if act == "a":
            E["takeover_press"] = t_of(_first(ev, lambda e: e["source"] == "scenario" and e.get("marker") == "takeover"
                                              and e["kind"] == "inject", after=t0))
            E["manual_host"] = t_of(_first(ev, probe("control_mode", lambda v: v["name"] == "MANUAL"), after=t0))
            E["manual_take"] = t_of(_first(ev, isl("TAKE_MRM_HANDLER_CONTROL_MODE", lambda a: a == 4), after=t0))
            E["driver_exit"] = t_of(_first(ev, isl("PATH_MRM_HANDLER_DRIVER_EXIT_ENTRY"), after=t0))
            E["mrm_operating"] = t_of(_first(ev, probe("mrm_state", lambda v: v["state"] == "MRM_OPERATING"),
                                             after=t0))
            obs["response"] = d(E["tor_on"], E["manual_host"])
            obs["exit_route"] = d(E["manual_take"], E["tor_off"])
            obs["press_to_manual"] = d(E["takeover_press"], E["manual_host"])
            rung = "takeover_request"
        else:
            E["call"] = t_of(_first(ev, isl("CALL_MRM_HANDLER_COMFORTABLE_STOP_OPERATE", lambda a: a == 1),
                                    after=after_on))
            E["safe_cmd"] = t_of(_first(ev, isl("PUB_MRM_COMFORTABLE_STOP_OPERATOR_MAX_VELOCITY_CANDIDATES"),
                                        after=after_on)) or \
                t_of(_first(ev, probe("velocity_limit", lambda v: v["max_velocity"] == 0.0), after=after_on))
            E["host_limit"] = t_of(_first(ev, probe("velocity_limit", lambda v: v["max_velocity"] == 0.0),
                                          after=after_on))
            E["mrm_operating"] = t_of(_first(ev, probe("mrm_state", lambda v: v["state"] == "MRM_OPERATING"),
                                             after=t0))
            E["first_decel"] = t_of(_first(ev, probe("control_cmd", lambda v: v["acc"] < -0.05),
                                           after=E["safe_cmd"] or after_on))
            E["standstill"] = standstill(ev, E["safe_cmd"] or after_on)
            E["mrm_succeeded"] = t_of(_first(ev, probe("mrm_state", lambda v: v["state"] == "MRM_SUCCEEDED"),
                                             after=t0))
            # The deadline: request on + the window (derived, see the module doc).
            wn = int(round(win_ms * 1e6))
            E["deadline"] = E["tor_on"] + wn if E["tor_on"] is not None else None
            E["deadline_host"] = E["tor_on_host"] + wn if E["tor_on_host"] is not None else None
            obs["windows"] = d(E["fault_on_wire"], E["deadline"])
            obs["route"] = d(E["deadline"], E["safe_cmd"])
            obs["windows_route"] = d(E["fault_on_wire"], E["safe_cmd"])
            obs["route_host"] = d(E["deadline_host"], E["host_limit"])
            obs["windows_route_host"] = d(E["fault_on_wire"], E["host_limit"])
            obs["planner_hop"] = d(E["safe_cmd"], E["first_decel"])
            obs["settle"] = d(E["safe_cmd"], E["standstill"])
            obs["total"] = d(t0, E["standstill"])
            rung = "comfortable_stop"
    else:
        E["sigstop"] = t0
        gl = _first(ev, lambda e: e["source"] == "gate" and e["kind"] == "last", after=t0 - 2_000_000_000)
        E["gate_last"] = t_of(gl)
        takes = [e for e in ev if e["source"] == "island" and e.get("marker") ==
                 "TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY" and e["t_mono_ns"] <= t0 + 300_000_000]
        E["island_take"] = takes[-1]["t_mono_ns"] if takes else None
        E["host_take"] = t_of(_last(ev, probe("availability"), before=t0))
        base = E["island_take"] or E["host_take"]
        E["detect_tick"] = t_of(_first(ev, isl("CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE", lambda a: a == 1),
                                       after=base))
        E["safe_cmd"] = t_of(_first(ev, isl("PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD",
                                            lambda a: a == 2), after=E["detect_tick"] or base))
        if not have_island:
            E["detect_tick"] = t_of(_first(ev, probe("mrm_state", lambda v: v["state"] == "MRM_OPERATING"),
                                           after=t0))
            E["safe_cmd"] = t_of(_first(ev, probe("island_emergency_control_cmd", lambda v: v["acc"] < 0),
                                        after=E["detect_tick"] or t0))
        E["mrm_operating"] = t_of(_first(ev, probe("mrm_state", lambda v: v["state"] == "MRM_OPERATING"), after=t0))
        E["hazard_lights_on"] = t_of(_first(ev, probe("vehicle_hazard_lights", lambda v: v == "ENABLE"), after=t0))
        E["standstill"] = standstill(ev, E["safe_cmd"] or t0)
        E["mrm_succeeded"] = t_of(_first(ev, probe("mrm_state", lambda v: v["state"] == "MRM_SUCCEEDED"), after=t0))
        obs["sigstop_after_last_sample"] = d(base, t0)
        obs["detect"] = d(base, E["detect_tick"])
        obs["route"] = d(E["detect_tick"], E["safe_cmd"])
        obs["settle"] = d(E["safe_cmd"], E["standstill"])
        obs["total"] = d(base, E["standstill"])
        obs["total_from_sigstop"] = d(t0, E["standstill"])
        # phase11-S4/S7: the supervised deadline of the hpc_loss reaction
        # (island_supervisor.c). The handler arms it at every take: due =
        # take + max_age + call_mrm, so from the last take before the loss.
        # A fault-tick overrun (SUPERVISOR_INJECT) makes call_mrm late; the
        # supervisor's verdict and the safe-state output are its fallback.
        E["sup_inject"] = t_of(_first(ev, isl("SUPERVISOR_INJECT"), after=base))
        dle = _first(ev, isl("SUPERVISOR_DEADLINE"), after=base)
        E["sup_verdict"] = t_of(dle)
        sse = _first(ev, isl("SUPERVISOR_SAFE_STATE"), after=base)
        E["sup_safe_state"] = t_of(sse)
        sup_offset = None
        if have_island and E["island_take"] is not None:
            max_age = tl.sub_max_age_ms("mrm_handler", "operation_mode_availability")
            call_mrm = tl.path_latency_ms("mrm_handler", "call_mrm")
            if max_age is not None and call_mrm is not None:
                sup_offset = max_age + call_mrm
                E["sup_due"] = E["island_take"] + int(round(sup_offset * 1e6))
        # The verdict names the due it judged (arg: route << 28 | the due's
        # uptime ms, low 28 bits); on the board the trace clock is the uptime,
        # so that due is placed exactly, on the host clock through the
        # marker's own offset. The take-based one above, from the take's
        # trace stamp, is up to 1 ms later (the handler reads the uptime in
        # whole ms).
        if dle is not None and dle.get("island_ns") is not None:
            due_low = (dle["value"] & 0x0FFFFFFF) * 1_000_000
            span = (1 << 28) * 1_000_000
            k = (dle["island_ns"] - due_low + span // 2) // span
            due_isl = due_low + k * span
            E["sup_due_take"] = E.get("sup_due")
            E["sup_due"] = dle["t_mono_ns"] - dle["island_ns"] + due_isl
        if E.get("sup_due") is not None and (E["sup_inject"] or E["sup_verdict"] or E["sup_safe_state"]):
            obs["sup_due_to_verdict"] = d(E["sup_due"], E["sup_verdict"])
            obs["sup_due_to_safe"] = d(E["sup_due"], E["sup_safe_state"])
            obs["sup_safe_to_standstill"] = d(E["sup_safe_state"], E["standstill"])
            obs["sup_base_to_safe"] = d(base, E["sup_safe_state"])
            obs["sup_cause"] = sse["value"] if sse else None
            inj = _first(ev, isl("SUPERVISOR_INJECT"), after=base)
            obs["sup_inject_ms"] = inj["value"] if inj else None
        obs["sup_offset"] = sup_offset
        rung = "emergency_stop"
    # the entry speed and the settle it implies
    t_cmd = E.get("safe_cmd")
    v_entry = velocity_at(ev, t_cmd) if t_cmd else None
    decl_rows = {r["rung"]: r for r in rows if r["hazard"] == hazard}
    p = prof.get((hazard, rung))
    decl_settle_at_obs = tl.settle_s(v_entry, -p[0], -p[1]) * 1000 if p and v_entry else None
    bound = entry_speed.get(hazard)
    # phase10-B8: every declared max_transport edge the trace observes
    links = []
    transports = declared_transports(explain)
    for topic, (decl, charged) in transports.items():
        if topic not in LINK_EDGES or not have_island:
            continue
        marker, host, what, horizon = LINK_EDGES[topic]
        hops = link_hops(ev, marker, host(ev), horizon)
        if hops:
            links.append(dict(topic=topic, declared=decl, charged=charged, host=what, hops=hops))
    res = dict(act=act, hazard=hazard, rung=rung, t0=t0, edges={k: ms(v) for k, v in E.items()},
               edges_ns=E, observed=obs, declared=decl_rows, window_ms=win_ms,
               window_end_ms=(decl_rows.get("takeover_request") or {}).get("window_end"), profile=p,
               entry_speed_declared=bound, entry_speed_observed=v_entry,
               entry_speed_exceeded=(v_entry is not None and bound is not None and v_entry > bound),
               settle_at_observed_speed_ms=decl_settle_at_obs,
               settle_response_ms=settle_responses(explain).get((hazard, rung)), links=links,
               dwell_link=transports.get(DWELL_LINK_TOPIC),
               align=align, have_island=have_island, notes=notes)
    # The rung the run ENDED on: the behavior of MRM_SUCCEEDED (or the last
    # one operated). A comfortable stop that the island escalates part way
    # (its rung requires hpc_alive) ends on EMERGENCY_STOP, and says so.
    seq = []
    for e in ev:
        if e["t_mono_ns"] >= t0 and e["source"] == "probe" and e.get("marker") == "mrm_state" \
                and e["value"]["state"] in ("MRM_OPERATING", "MRM_SUCCEEDED"):
            b = e["value"]["behavior"]
            if not seq or seq[-1][1] != b:
                seq.append((ms(e["t_mono_ns"]), b))
    res["behaviors"] = seq
    res["behavior"] = seq[-1][1] if seq else None
    if len(seq) > 1:
        notes.append("escalated: " + " -> ".join(f"{b} at {t:.0f} ms" for t, b in seq))
    # The host side of the precondition every rung above the floor needs
    # (hpc_alive): the longest silence of /system/operation_mode/availability
    # the probe saw from the button to the end of the act. Longer than the
    # handler's 500 ms and the island (rightly) raises hpc_loss.
    t_end = E.get("standstill") or E.get("mrm_succeeded")
    if act == "a":
        t_end = _first(ev, lambda e: e["source"] == "scenario" and e.get("marker") == "odd_enter", after=t0)
        t_end = t_end["t_mono_ns"] if t_end else None
    # phase11-S7: from the island's own takes when the trace has them (the
    # handler's view, which is what raises hpc_loss); the host probe stalls
    # with the host under load (phase10-B3: b3-b1/b2), so it is the fallback.
    def avail_gaps(pred):
        gaps, prev, last = [], None, None
        for e in ev:
            if not pred(e):
                continue
            t = e["t_mono_ns"]
            if t_end is not None and t > t_end:
                break
            if prev is not None and t >= t0:
                gaps.append(((t - prev) / 1e6, ms(prev)))
            prev = last = t
        return gaps, last
    res["avail_gap_src"] = None
    gaps = []
    if act != "encore":
        if have_island:
            gaps, last = avail_gaps(isl("TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY"))
            if gaps:
                res["avail_gap_src"] = "island"
                last_any = max((e["t_mono_ns"] for e in ev if e["source"] == "island" and e["kind"] == "marker"),
                               default=None)
                if t_end is not None and last_any is not None and last_any < t_end:
                    notes.append(f"HPC alive: the island trace ends {ms(last_any):.0f} ms after the fault, "
                                 f"before the act's end ({ms(t_end):.0f} ms)")
                    res["avail_gap_trace_end"] = ms(last_any)
        if not gaps:
            gaps, _ = avail_gaps(lambda e: e["source"] == "probe" and e.get("marker") == "availability"
                                 and e["kind"] == "sample")
            res["avail_gap_src"] = "host" if gaps else None
    res["avail_gap_max"] = max(gaps) if gaps else None
    res["verdicts"] = verdicts(res)
    return res


def verdicts(r):
    out = []
    o, dr = r["observed"], r["declared"]
    w = r["window_ms"]

    def add(term, obs, decl, note="", by=SUM):
        ok = None if obs is None or decl is None else obs <= decl
        out.append(dict(term=term, observed=obs, declared=decl, ok=ok, note=note, by=by))
    if r["act"] in ("a", "b"):
        tr = dr.get("takeover_request", {})
        add("detect (button -> verdict on the wire)", o.get("detect"), tr.get("detect"))
        add("takeover route (verdict -> request on)", o.get("tor_route"), tr.get("route"), CROSS)
        if r["act"] == "a":
            add("driver answered inside the window", o.get("response"), w, "response time")
            add("exit route (MANUAL taken -> request off)", o.get("exit_route"),
                tl.path_latency_ms("mrm_handler", "driver_exit"), "driver_exit max_latency", by=MON)
            ok_nomrm = r["edges"].get("mrm_operating") is None
            out.append(dict(term="no MRM", observed="none" if ok_nomrm else "MRM_OPERATING",
                            declared="none", ok=ok_nomrm, note="", by=TRACE))
        else:
            # The window is a least time, bounded above by the checker's
            # `ends within` (window + the first hop of the route below).
            end = tr.get("window_end")
            # The host row times two receipts, each one out-link hop after
            # its island edge. Each hop lies in [0, link] (the serial link's
            # max_transport: the same UART and gateway as the guard's in-link),
            # so the received window is the island's window +- at most one
            # link: on 9,993.00-9,999.87 ms in c8-b2/b4, c8f-b1/b2 with the
            # island's own dwell >= 10,000 (phase9-C9). The island-clock row
            # is the check of the window itself.
            # The link the run declared (its own --explain), not the contract
            # as it is now: a run sized at link 81 is read against 81 even
            # after the contract moves to 56.
            dl = r.get("dwell_link")
            if dl is not None:
                link, src = dl[0], ("the run's --explain" if dl[1] is not None else "the contract now")
            else:
                link, src = tl.sub_transport_ms("mrm_handler", "operation_mode_availability") or 0.0, \
                    "the contract now"
            for term, key, slack in (("window dwell, island clock (request on -> off)", "dwell", 0.0),
                                     ("window dwell, host (request on -> off as received)", "dwell_host", link)):
                dw = o.get(key)
                lo, hi = w - slack, (None if end is None else end + slack)
                out.append(dict(term=term, observed=dw,
                                declared=f"[{lo:.2f}, {hi:.2f}]" if hi is not None else f">= {lo:.2f}",
                                ok=None if dw is None else (lo <= dw and (hi is None or dw <= hi)),
                                note="at least the window; ends within the checker's `ends within`"
                                     + (f"; +- the link {link:.0f} ms ({src}), two receipts" if slack else ""),
                                by="checker (window-expiry), trace"))
            cs = dr.get("comfortable_stop", {})
            add("windows (verdict -> deadline = request on + window)", o.get("windows"), cs.get("windows"),
                CROSS)
            add("route, island clock (deadline -> velocity limit)", o.get("route"), cs.get("route"))
            add("route, host (deadline -> velocity limit received)", o.get("route_host"), cs.get("route"))
            wr = None if cs.get("windows") is None or cs.get("route") is None else cs["windows"] + cs["route"]
            add("windows + route (verdict -> velocity limit)", o.get("windows_route"), wr,
                "no derived instant; " + CROSS)
            add("windows + route, host (verdict -> velocity limit received)", o.get("windows_route_host"), wr,
                "no derived instant")
            add("settle (velocity limit -> standstill)", o.get("settle"), cs.get("settle"),
                "includes the planner hop, not declared here")
            ph = o.get("planner_hop")
            settle_at_speed(add, r, "velocity limit",
                            "includes the planner hop" + ("" if ph is None else f" {ph:.2f} ms"))
            add("total (button -> standstill)", o.get("total"), cs.get("total"))
            add("within the FTTI", o.get("total"), cs.get("ftti"))
    else:
        fl = dr.get("emergency_stop", {})
        inj = o.get("sup_inject_ms")
        if inj is None:
            add("detect (last sample -> reaction tick)", o.get("detect"), (fl.get("detect") or 0) + TICK_MS,
                "500 + the tick the route's call_mrm already holds")
            add("route (reaction tick -> braking command)", o.get("route"), fl.get("route"))
            dr_ = None if o.get("detect") is None or o.get("route") is None else o["detect"] + o["route"]
            dd_ = None if fl.get("detect") is None else fl["detect"] + fl["route"]
            add("detect + route (last sample -> braking command)", dr_, dd_)
            add("settle (braking command -> standstill)", o.get("settle"), fl.get("settle"))
            settle_at_speed(add, r, "braking command")
            add("total (last sample -> standstill)", o.get("total"), fl.get("total"))
            add("within the FTTI", o.get("total"), fl.get("ftti"))
        else:
            # phase11-S7: the fault tick overran on purpose, so the unsupervised
            # rows are over by construction; they are shown without a verdict
            # and the supervised rows below judge the run.
            what = "a stall that never ends" if inj == 0xFFFFFFFF else f"{inj} ms"
            nv = f"the fault tick overran ({what}, injected): judged by the supervised rows"
            for term, key in (("detect (last sample -> reaction tick)", "detect"),
                              ("route (reaction tick -> braking command)", "route"),
                              ("settle (braking command -> standstill)", "settle")):
                out.append(dict(term=term, observed=o.get(key), declared=None, ok=None, note=nv, by=TRACE))
        supervised_rows(add, out, r, fl)
    exp = {"b": "COMFORTABLE_STOP", "encore": "EMERGENCY_STOP"}.get(r["act"])
    if exp and o.get("sup_inject_ms") == 0xFFFFFFFF:
        out.append(dict(term="rung reached", observed=r.get("behavior") or "none", declared=exp, ok=None,
                        note="the stall never ends: the island's ladder cannot run; its safe state is the "
                        "supervisor's output (the supervised rows)", by=TRACE))
    elif exp:
        got = r.get("behavior")
        seq = r.get("behaviors") or []
        note = "escalated from " + ", ".join(b for _, b in seq[:-1]) if len(seq) > 1 else ""
        out.append(dict(term="rung reached", observed=got or "none", declared=exp, ok=got == exp, note=note,
                        by=TRACE))
    g = r.get("avail_gap_max")
    if g is not None:
        src = r.get("avail_gap_src") or "host"
        where = "island takes" if src == "island" else "host"
        note = f"at {g[1]:.0f} ms; over 500 ms the island raises hpc_loss"
        if src == "island" and r.get("avail_gap_trace_end") is not None:
            note += f"; the island trace ends at {r['avail_gap_trace_end']:.0f} ms"
        out.append(dict(term=f"HPC alive: longest availability gap ({where})", observed=g[0],
                        declared=HPC_TIMEOUT_MS, ok=g[0] <= HPC_TIMEOUT_MS, note=note, by=MON))
    if r["entry_speed_observed"] is not None and r["entry_speed_declared"] is not None:
        out.append(dict(term="entry speed (m/s)", observed=r["entry_speed_observed"],
                        declared=r["entry_speed_declared"], ok=not r["entry_speed_exceeded"], note="",
                        by="checker (settle v0), trace"))
    # phase10-B8: each declared max_transport edge the trace observes, so a
    # stated hop is compared with its observations, not only inside a route
    for lk in r.get("links") or []:
        h = lk["hops"]
        how = {True: "charged on its reaction route", False: "not charged by the fault arithmetic",
               None: "from the contract now, not the run's --explain"}[lk["charged"]]
        note = (f"max_transport, {how}; {min(h):.2f}-{max(h):.2f} ms over {len(h)} edge(s); "
                f"{CROSS}, over-stated by the smallest out-link delay")
        if lk["host"] != "gate publish":
            note += f"; the host stamp is the {lk['host']}, not the publish"
        add(f"link into {lk['topic']} ({lk['host']} -> island take)", max(h), lk["declared"], note,
            by=SUM if lk["charged"] else TRACE)
    return out


def supervised_rows(add, out, r, fl):
    """phase11-S4/S7: the hpc_loss reaction's supervised deadline
    (island_supervisor.c), on a run where the supervisor acted or an overrun
    was injected. The due is the last take + max_age + call_mrm, as the
    handler arms it; the detection delay is the platform's tick + switch
    (tlcommon.supervision_ms). Rows: the verdict and the fallback's start
    (the safe-state output) within the detection delay of the due; the
    fallback's start -> standstill within the emergency settle; last sample
    -> standstill within the overrun case's total (the rung total + the
    detection delay) and the FTTI; last sample -> the safe-state output
    within the FTTI."""
    o = r["observed"]
    if "sup_due_to_safe" not in o:
        return
    tick, switch, src = tl.supervision_ms()
    det = tick + switch
    by = "supervisor (timer), trace"
    cause = {1: "route deadline", 2: "SWT0 first timeout", 3: "the executor's reaction hook"}.get(o.get("sup_cause"), o.get("sup_cause"))
    note = (f"due = last take + {o['sup_offset']:.0f} (max_age + call_mrm); detection delay = tick {tick:g} + "
            f"switch {switch:g} ({src})")
    add("supervised: due -> deadline verdict", o.get("sup_due_to_verdict"), det, note, by=by)
    add("supervised: due -> fallback start (safe-state output)", o.get("sup_due_to_safe"), det,
        note + (f"; cause {cause}" if cause else ""), by=by)
    stall = o.get("sup_inject_ms") == 0xFFFFFFFF
    if stall:
        # the island's emergency stop never runs and the safe-state output (an
        # LED) is wired to no brake: a standstill the probe sees is the host's
        # own doing (p11-st1: the speed steps from 4.17 to 0.0 m/s ~1.1 s after
        # the fault, no island output), so no verdict on it
        nb = ("the stall never ends: the island's emergency stop never runs, and the safe-state output "
              "(an LED) is wired to no brake in the simulator; a standstill seen is not the island's")
        out.append(dict(term="supervised: fallback start -> standstill", observed=o.get("sup_safe_to_standstill"),
                        declared=fl.get("settle"), ok=None, note=nb, by=by))
        out.append(dict(term="supervised: total (last sample -> standstill)", observed=o.get("total"),
                        declared=None if fl.get("total") is None else fl["total"] + det, ok=None, note=nb, by=by))
    else:
        add("supervised: fallback start -> standstill", o.get("sup_safe_to_standstill"), fl.get("settle"),
            "the emergency settle; the vehicle brakes on the late reaction, the safe-state output being an LED",
            by=by)
    tot = None if fl.get("total") is None else fl["total"] + det
    if not stall:
        add("supervised: total (last sample -> standstill)", o.get("total"), tot,
            "the overrun case: the rung's total + the detection delay", by=by)
        add("supervised: within the FTTI", o.get("total"), fl.get("ftti"), by=by)
    add("supervised: last sample -> safe-state output, within the FTTI", o.get("sup_base_to_safe"),
        fl.get("ftti"), by=by)


def settle_at_speed(add, r, start, extra=""):
    """phase10-B2: the braking profile at the OBSERVED entry speed against
    the observed settle. Their difference is the measured response delay
    (the vehicle's, plus `extra`); once the contract states a `response`,
    the row's bound is profile + response and it gets a verdict."""
    prof = r.get("settle_at_observed_speed_ms")
    if prof is None:
        return
    obs, resp, v0 = r["observed"].get("settle"), r.get("settle_response_ms"), r["entry_speed_observed"]
    diff = None if obs is None else obs - prof
    note = (f"profile {prof:.2f} at v0 {v0:.2f} m/s; response delay (observed - profile) "
            + ("-" if diff is None else f"{diff:.2f}") + " ms"
            + (f" {extra}" if extra else "")
            + ("; no `response` declared, so no verdict" if resp is None else f"; declared response {resp:.2f} ms"))
    decl = None if resp is None else prof + resp
    add(f"settle at the observed entry speed ({start} -> standstill)", obs, decl, note,
        by=TRACE if resp is None else "trace (contract response)")


def selftest_rows(check):
    """The phase10-B8 link rows and the phase10-B2 settle row on synthetic
    events (tlcommon.py selftest): the explain parsing, the hop matching and
    each row's declared value, verdict and source."""
    ex = ("  hpc_loss/emergency_stop: route = link 81.00ms (max_transport into "
          "'/mrm_handler/operation_mode_availability', sub-level) + path 188.33ms\n"
          "  info[declared-not-charged]: x.yaml:1: `nodes.mrm_handler.sub.control_mode.max_transport: 143ms` "
          "on '/mrm_handler/control_mode' is not charged by the fault-reaction arithmetic\n")
    dt = declared_transports(ex, contract="/nonexistent")
    check(f"declared_transports: {dt}", dt == {"/mrm_handler/operation_mode_availability": (81.0, True),
                                               "/mrm_handler/control_mode": (143.0, False)})
    M = 1_000_000
    take = lambda t, v, m="TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY": dict(  # noqa: E731
        t_mono_ns=t * M, source="island", kind="marker", marker=m, value=v)
    ev = [take(0, 1), take(100, 1), take(1030, 0), take(1100, 0), take(2045, 1)]
    hops = link_hops(ev, "TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY", [(1000 * M, 0), (2000 * M, 1),
                                                                           (5000 * M, 0)], 500 * M)
    check(f"link_hops: one hop per host edge with a take of the new value in reach {hops}",
          [round(h, 2) for h in hops] == [30.0, 45.0])
    ev_cm = [dict(t_mono_ns=10 * M, source="probe", kind="sample", marker="control_mode",
                  value=dict(mode=4, name="MANUAL")), take(42, 4, "TAKE_MRM_HANDLER_CONTROL_MODE")]
    h2 = link_hops(ev_cm, "TAKE_MRM_HANDLER_CONTROL_MODE", _host_edges_control_mode(ev_cm), 1000 * M)
    check(f"link_hops: control mode, probe receipt -> take {h2}", [round(h, 2) for h in h2] == [32.0])
    base = dict(act="encore", observed=dict(settle=3000.0), declared={}, window_ms=10000.0, behaviors=[],
                behavior="EMERGENCY_STOP", avail_gap_max=None, entry_speed_observed=4.19,
                entry_speed_declared=8.33, entry_speed_exceeded=False, settle_at_observed_speed_ms=2510.69,
                settle_response_ms=None, edges={},
                links=[dict(topic="/mrm_handler/operation_mode_availability", declared=81.0, charged=True,
                            host="gate publish", hops=[18.5, 21.0]),
                       dict(topic="/mrm_handler/control_mode", declared=143.0, charged=False,
                            host="probe receipt", hops=[150.0])])
    by = {v["term"].split(" (")[0]: v for v in verdicts(base)}
    lk = by.get("link into /mrm_handler/operation_mode_availability")
    cm = by.get("link into /mrm_handler/control_mode")
    check("link row: max of the hops against max_transport, PASS, checker sum",
          lk is not None and lk["observed"] == 21.0 and lk["declared"] == 81.0 and lk["ok"] is True
          and lk["by"] == SUM and "18.50-21.00 ms over 2 edge(s)" in lk["note"])
    check("link row: an uncharged hop over its max_transport FAILs, checked by the trace only",
          cm is not None and cm["ok"] is False and cm["by"] == TRACE and "probe receipt" in cm["note"])
    st = by.get("settle at the observed entry speed")
    check("settle row without a response: no verdict, the difference stated",
          st is not None and st["ok"] is None and st["declared"] is None and "489.31 ms" in st["note"])
    base["settle_response_ms"] = 600.0
    st = {v["term"].split(" (")[0]: v for v in verdicts(base)}.get("settle at the observed entry speed")
    check("settle row with a response: profile + response, PASS",
          st is not None and abs(st["declared"] - 3110.69) < 1e-6 and st["ok"] is True)
    resp = settle_responses("  info[settle-derived]: c.yaml:1: hazard 'hpc_loss', rung 'emergency_stop': settle "
                            "from /mrm_emergency_stop_operator's braking profile, a = 2.5, response 250ms, "
                            "v0 = entry_speed 8.33 m/s: t = 4165.33ms", contract=False)
    check(f"settle_responses from the settle-derived line {resp}", resp == {("hpc_loss", "emergency_stop"): 250.0})
    # The host dwell's slack is the link the run declared, not the contract's now.
    b = dict(base, act="b", observed=dict(dwell=10000.5, dwell_host=9925.0),
             declared=dict(takeover_request=dict(window_end=10081.0)), dwell_link=(81.0, True))
    dh = {v["term"].split(" (")[0]: v for v in verdicts(b)}.get("window dwell, host")
    check("window dwell, host: slack from the run's --explain link (81), PASS",
          dh is not None and dh["declared"] == "[9919.00, 10162.00]" and dh["ok"] is True
          and "the run's --explain" in dh["note"])
    dh = {v["term"].split(" (")[0]: v for v in verdicts(dict(b, dwell_link=(40.0, True)))}.get("window dwell, host")
    check("window dwell, host: a run that declared link 40 FAILs a 75 ms short dwell",
          dh is not None and dh["declared"] == "[9960.00, 10121.00]" and dh["ok"] is False)


def selftest_supervised(check):
    """phase11-S7: the supervised rows of an encore with a fault-tick overrun,
    and the HPC alive row taken from the island's takes, on synthetic events."""
    M = 1_000_000
    isl_ev = lambda t, m, v=0: dict(t_mono_ns=int(t * M), source="island", kind="marker", marker=m,  # noqa: E731
                                    value=v)
    vel = lambda t, v: dict(t_mono_ns=int(t * M), source="probe", kind="velocity", value=v)  # noqa: E731
    take = "TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY"
    ev = [isl_ev(800, take, 1), isl_ev(900, take, 1), vel(950, 4.2),
          dict(t_mono_ns=1000 * M, source="scenario", kind="inject", marker="hpc_loss", value=None),
          isl_ev(1450, "PATH_MRM_HANDLER_CALL_MRM_ENTRY", 1), isl_ev(1450.1, "SUPERVISOR_INJECT", 300),
          isl_ev(1549.4, "SUPERVISOR_DEADLINE", 0), isl_ev(1549.5, "SUPERVISOR_SAFE_STATE", 1),
          isl_ev(1750.2, "CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE", 1),
          isl_ev(1760, "PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD", 2),
          vel(1800, 4.0), vel(4500, 0.0)]
    rows = [dict(hazard="hpc_loss", rung="emergency_stop", role="floor", detect=500.0, windows=0.0,
                 route=205.0, settle=4421.33, total=5165.67, ftti=10000.0)]
    r = analyze(sorted(ev, key=lambda e: e["t_mono_ns"]), rows)
    o = r["observed"]
    check(f"supervised: due = last take 900 + 649 -> due->verdict {o.get('sup_due_to_verdict')}, "
          f"due->safe {o.get('sup_due_to_safe')}",
          o.get("sup_due_to_verdict") is not None and abs(o["sup_due_to_verdict"] - 0.4) < 1e-6
          and abs(o["sup_due_to_safe"] - 0.5) < 1e-6)
    by = {v["term"]: v for v in r["verdicts"]}
    ds = by.get("supervised: due -> fallback start (safe-state output)")
    check("supervised: due -> fallback start PASS within tick + switch, cause named",
          ds is not None and ds["ok"] is True and ds["declared"] == 2.0 and "route deadline" in ds["note"])
    st = by.get("supervised: fallback start -> standstill")
    check(f"supervised: fallback start -> standstill {st and st['observed']} against the settle",
          st is not None and abs(st["observed"] - 2950.5) < 1e-6 and st["ok"] is True)
    tot = by.get("supervised: total (last sample -> standstill)")
    check("supervised: the overrun case's total = rung total + detection delay, PASS",
          tot is not None and abs(tot["declared"] - 5167.67) < 1e-6 and tot["ok"] is True)
    dt = by.get("detect (last sample -> reaction tick)")
    check("an injected overrun leaves the unsupervised detect row without a verdict",
          dt is not None and dt["ok"] is None and "injected" in dt["note"])
    # the verdict's own due (arg low 28 bits, uptime ms) on a trace whose
    # clock is the uptime, the host offset 5 s: the arg says 1548, not the take-based 1549 -> verdict +1.4 ms
    off = 5000 * M
    ev3 = [dict(e, t_mono_ns=e["t_mono_ns"] + off, island_ns=e["t_mono_ns"]) if e["source"] == "island"
           else dict(e, t_mono_ns=e["t_mono_ns"] + off) for e in ev]
    ev3 = [dict(e, value=1548) if e.get("marker") == "SUPERVISOR_DEADLINE" else e for e in ev3]
    o3 = analyze(sorted(ev3, key=lambda e: e["t_mono_ns"]), rows)["observed"]
    check(f"supervised: the due from the verdict's arg -> due->verdict {o3.get('sup_due_to_verdict')}",
          o3.get("sup_due_to_verdict") is not None and abs(o3["sup_due_to_verdict"] - 1.4) < 1e-6)
    # a stall: no standstill, the safe-state output still within the FTTI
    ev2 = [e for e in ev if e["kind"] != "velocity" or e["t_mono_ns"] < 1000 * M]
    ev2 = [dict(e, value=0xFFFFFFFF) if e.get("marker") == "SUPERVISOR_INJECT" else e for e in ev2
           if e.get("marker") not in ("CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE",
                                      "PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD")]
    r2 = analyze(ev2, rows)
    by2 = {v["term"]: v for v in r2["verdicts"]}
    s2 = by2.get("supervised: fallback start -> standstill")
    f2 = by2.get("supervised: last sample -> safe-state output, within the FTTI")
    check("stall: no standstill row verdict (no brake line), safe-state output within the FTTI PASS",
          s2 is not None and s2["ok"] is None and "never ends" in s2["note"]
          and f2 is not None and f2["ok"] is True and abs(f2["observed"] - 649.5) < 1e-6)
    # HPC alive from the island's takes, not the host probe
    evb = [dict(t_mono_ns=0, source="scenario", kind="inject", marker="odd_exit", value=None)]
    evb += [isl_ev(t, take, 0) for t in (100, 200, 300, 950, 1050)]
    evb += [dict(t_mono_ns=int(t * M), source="probe", kind="sample", marker="availability",
                 value=dict(autonomous=False)) for t in (100, 1500)]
    rb = analyze(evb, [])
    g = [v for v in rb["verdicts"] if v["term"].startswith("HPC alive")]
    check(f"HPC alive from the island takes: {g and (g[0]['term'], g[0]['observed'])}",
          len(g) == 1 and "island takes" in g[0]["term"] and abs(g[0]["observed"] - 650.0) < 1e-6
          and g[0]["ok"] is False)


def fmt(v, nd=2):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)
