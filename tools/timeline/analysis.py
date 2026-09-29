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

import tlcommon as tl

# The tick share of mrm_handler/call_mrm on the board: the 100 ms period of
# update_rate 10 plus 18 ms of jitter (ticks up to 114.84 ms apart on the
# S32K344; island contract, phase8-W30). The encore's detect row adds it back
# (below). rlm has no key for the share, so it is stated here.
TICK_MS = 118.0
CROSS = "island vs host clock"  # the note on a cross-clock row (module doc)
HPC_TIMEOUT_MS = 500.0  # mrm_handler timeout_operation_mode_availability: hpc_loss


def settle_profiles(explain):
    """(hazard, rung) -> (a, j, v0) from the checker's settle-derived lines."""
    out = {}
    for m in re.finditer(r"hazard '(\w+)', rung '(\w+)': settle from .*?a = \|\w+\| = ([0-9.]+) m/s\^2, "
                         r"j = \|\w+\| = ([0-9.]+) m/s\^3, v0 = entry_speed ([0-9.]+) m/s", explain):
        out[(m.group(1), m.group(2))] = (float(m.group(3)), float(m.group(4)), float(m.group(5)))
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
        rung = "emergency_stop"
    # the entry speed and the settle it implies
    t_cmd = E.get("safe_cmd")
    v_entry = velocity_at(ev, t_cmd) if t_cmd else None
    decl_rows = {r["rung"]: r for r in rows if r["hazard"] == hazard}
    p = prof.get((hazard, rung))
    decl_settle_at_obs = tl.settle_s(v_entry, -p[0], -p[1]) * 1000 if p and v_entry else None
    bound = entry_speed.get(hazard)
    res = dict(act=act, hazard=hazard, rung=rung, t0=t0, edges={k: ms(v) for k, v in E.items()},
               edges_ns=E, observed=obs, declared=decl_rows, window_ms=win_ms,
               window_end_ms=(decl_rows.get("takeover_request") or {}).get("window_end"), profile=p,
               entry_speed_declared=bound, entry_speed_observed=v_entry,
               entry_speed_exceeded=(v_entry is not None and bound is not None and v_entry > bound),
               settle_at_observed_speed_ms=decl_settle_at_obs, align=align, have_island=have_island,
               notes=notes)
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
    gaps, prev = [], None
    if act != "encore":
        for e in ev:
            if e["source"] != "probe" or e.get("marker") != "availability" or e["kind"] != "sample":
                continue
            t = e["t_mono_ns"]
            if t_end is not None and t > t_end:
                break
            if prev is not None and t >= t0:
                gaps.append(((t - prev) / 1e6, ms(prev)))
            prev = t
    res["avail_gap_max"] = max(gaps) if gaps else None
    res["verdicts"] = verdicts(res)
    return res


def verdicts(r):
    out = []
    o, dr = r["observed"], r["declared"]
    w = r["window_ms"]

    def add(term, obs, decl, note=""):
        ok = None if obs is None or decl is None else obs <= decl
        out.append(dict(term=term, observed=obs, declared=decl, ok=ok, note=note))
    if r["act"] in ("a", "b"):
        tr = dr.get("takeover_request", {})
        add("detect (button -> verdict on the wire)", o.get("detect"), tr.get("detect"))
        add("takeover route (verdict -> request on)", o.get("tor_route"), tr.get("route"), CROSS)
        if r["act"] == "a":
            add("driver answered inside the window", o.get("response"), w, "response time")
            add("exit route (MANUAL taken -> request off)", o.get("exit_route"),
                tl.path_latency_ms("mrm_handler", "driver_exit"), "driver_exit max_latency")
            ok_nomrm = r["edges"].get("mrm_operating") is None
            out.append(dict(term="no MRM", observed="none" if ok_nomrm else "MRM_OPERATING",
                            declared="none", ok=ok_nomrm, note=""))
        else:
            # The window is a least time, bounded above by the checker's
            # `ends within` (window + the first hop of the route below).
            end = tr.get("window_end")
            for term, key in (("window dwell, island clock (request on -> off)", "dwell"),
                              ("window dwell, host (request on -> off as received)", "dwell_host")):
                dw = o.get(key)
                out.append(dict(term=term, observed=dw,
                                declared=f"[{w:.2f}, {end:.2f}]" if end is not None else f">= {w:.2f}",
                                ok=None if dw is None else (w <= dw and (end is None or dw <= end)),
                                note="at least the window; ends within the checker's `ends within`"))
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
            add("total (button -> standstill)", o.get("total"), cs.get("total"))
            add("within the FTTI", o.get("total"), cs.get("ftti"))
    else:
        fl = dr.get("emergency_stop", {})
        add("detect (last sample -> reaction tick)", o.get("detect"), (fl.get("detect") or 0) + TICK_MS,
            "500 + the tick the route's call_mrm already holds")
        add("route (reaction tick -> braking command)", o.get("route"), fl.get("route"))
        dr_ = None if o.get("detect") is None or o.get("route") is None else o["detect"] + o["route"]
        dd_ = None if fl.get("detect") is None else fl["detect"] + fl["route"]
        add("detect + route (last sample -> braking command)", dr_, dd_)
        add("settle (braking command -> standstill)", o.get("settle"), fl.get("settle"))
        add("total (last sample -> standstill)", o.get("total"), fl.get("total"))
        add("within the FTTI", o.get("total"), fl.get("ftti"))
    exp = {"b": "COMFORTABLE_STOP", "encore": "EMERGENCY_STOP"}.get(r["act"])
    if exp:
        got = r.get("behavior")
        seq = r.get("behaviors") or []
        note = "escalated from " + ", ".join(b for _, b in seq[:-1]) if len(seq) > 1 else ""
        out.append(dict(term="rung reached", observed=got or "none", declared=exp, ok=got == exp, note=note))
    g = r.get("avail_gap_max")
    if g is not None:
        out.append(dict(term="HPC alive: longest availability gap (host)", observed=g[0],
                        declared=HPC_TIMEOUT_MS, ok=g[0] <= HPC_TIMEOUT_MS,
                        note=f"at {g[1]:.0f} ms; over 500 ms the island raises hpc_loss"))
    if r["entry_speed_observed"] is not None and r["entry_speed_declared"] is not None:
        out.append(dict(term="entry speed (m/s)", observed=r["entry_speed_observed"],
                        declared=r["entry_speed_declared"], ok=not r["entry_speed_exceeded"], note=""))
    return out


def fmt(v, nd=2):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)
