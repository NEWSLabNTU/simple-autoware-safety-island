# Phase 10 - the contract's budgets: where they come from and what checks them

**Goal:** every number in the island's contract says where it comes from
(a requirement, a measurement, or a derivation), every stated budget is
checked by something, and the derived settling covers the vehicle's
response, not only the braking profile.

**Status (2026-10-15): B4, B5, B6 done; the timeline side of B2 and B8
done;** the rest is planned.

## Why

A read of the contract against the board runs turned up gaps in how its
budgets are written, derived and checked. They are below as units, each
with its evidence. Two were confirmed by experiment on 2026-10-15:

- A timer's period is not tied to the parameter that sets it. With the
  contract's mrm_handler timer changed to `rate_hz: 20` while
  `mrm_handler.param.yaml` keeps `update_rate: 10`, `play_launch check`
  (0.16.0) reports the contract clean. The takeover window, by contrast, is
  bound (`window: { param: mrm_handler.takeover_request_timeout }`), and a
  disagreement there fails with `error[window-param]`.
- The derived settling does not cover the vehicle's response. In the last
  full round of the gate image (runs fr-e1..3, fr-b1..3,
  ELF sha256 df1bf38a...), the vehicle took longer to stop than the
  braking profile allows at the speed it actually had:

  | rung | entry speed (m/s) | settle observed (ms) | profile at that speed (ms) | difference (ms) |
  |---|---|---|---|---|
  | emergency stop | 4.19-4.25 | 2887-3000 | 2511-2535 | 362-476 |
  | comfortable stop | 3.03-3.07 | 5306-6534 | 4697-4737 | 609-1797 |

  The budget is computed at the declared entry speed (8.33 m/s), so it was
  never exercised: Autoware's default `max_vel` (4.17 m/s) kept every run
  below half of it.

## Units

### B1. Bind each timer to its parameter (rlm, play_launch)

- What: a timer trigger names the parameter that sets its period, as the
  window does: `timer: { rate_hz: 10, param: update_rate }` (or `period`).
  The checker resolves the parameter from the launch file's parameter files
  and fails on a disagreement (`timer-param`), the same way `window-param`
  does. Same for `max_age` against the handler's
  `timeout_operation_mode_availability` if it is not bound yet (check first).
- Gate: the `rate_hz: 20` / `update_rate: 10` case above fails; the island
  contract states `param:` on every timer and checks clean; a contract
  fixture for each case in rlm and play_launch tests.
- Owner: rlm (schema), play_launch (rule), this repo (contract keys).

### B2. The vehicle's response in the settling (rlm, play_launch, this repo)

- What: the settling term gains a written response delay, stated beside the
  braking profile (`settle: { decel, jerk, response: <ms> }` or similar),
  measured on the target like a route term (B7's rule) and added to the
  derived `a/j + (v0 - v_r)/a`. `settle-derived` prints both parts.
- Evidence: the table above; B6 sizes it at the declared entry speed.
- Gate: the island contract states `response` for both operators; the
  checker's totals include it; B6's runs fit the new settling terms; the
  timeline table's settle row shows `profile + response` and the observed
  difference.
- Status (2026-10-15): the timeline side is done; the key, the checker and
  the contract's values are open. `analysis.py` adds the row "settle at the
  observed entry speed": the profile at the observed entry speed, the
  observed settle, and their difference as the measured response delay.
  With no `response` declared the row has no verdict (`run_summary.py`
  counts it apart, `+1 n/a`). Once the settle-derived line or the
  contract's `settle:` carries `response`, the row's bound is profile +
  response and it gets a verdict; the selftest adds the response to the
  profile when the checker prints it. fr round (observed - profile, ms):
  e1 362.18, e2 488.91, e3 352.54 (braking command -> standstill); b1
  608.65, b2 1796.30, b3 1781.04 (velocity limit -> standstill, so the
  planner hop is included: 629.49 in b2).

### B3. A runtime check of the route, not only of the callback (nano-ros)

- What: the island's `max-latency-runtime` monitor bounds one dispatch
  (the longest was 24.93 ms), while a route budget such as `call_mrm`
  149 ms is a wait for the next tick plus the work, measured from the
  input's take. A route made of a full tick wait and a slow dispatch can
  exceed its budget while every callback passes. Route budgets are today
  checked only after the run, from the trace (`tools/timeline/analysis.py`).
- Fix: nano-ros stamps the take of a path's trigger and checks
  take-to-last-output against the path's `max_latency` at the output,
  recording a `route-latency-runtime` violation (record only; no fallback).
- Gate: a fixture with a delayed tick records the violation on qemu and on
  the board; the island's acts record none; violation-record layout and
  readout updated. nano-ros PR, then the pin.
- Also in this repo (`docs/dx-ux-gaps-2026-10.md` section 5.3).

### B4. The tool applies the measurement rule (this repo) - done

- What: the rule for a measured term is its observed maximum plus 20 %,
  rounded up to the next ms; a timer period takes no margin (tick = period
  + lateness x 1.2). Today the terms tool prints maxima and the rule is
  applied by hand. It prints the proposed budget per term.
- Gate: on the W8 runs it reproduces tick 118 and work 31; on the W31 runs,
  link 81 from a 67.02 ms maximum.
- Status (2026-10-15): done. `tools/timeline/terms.py --propose`. W8
  (13 runs): tick 118 (lateness 14.84), work 31 (25.04, tick to the
  velocity limit), call_mrm 149. W31 (9 runs): link 81 (67.02). fr
  (9 runs): link 56 (46.42), tick 102, work 2, call_mrm 104.

### B5. Variants of the island contract in CI (this repo) - done

- What: the rejected variants (a 20 s window; a 65 km/h entry speed) exist
  only for the demo's composed contract, whose detection (126 ms) and
  comfortable-stop route (449 ms, with a 300 ms placeholder for the
  planner's hop) differ from the island contract's (100 ms, 149 ms). Their
  totals cannot be compared with the island's. Add both variants of the
  island contract itself, each expected to fail with
  `ladder-rung-budget` only (the 20 s variant raises the handler's
  `takeover_request_timeout` with it, so `window-param` stays quiet).
- Gate: `just l3-check` lists both with the expected verdicts.
- Status (2026-10-15): done. `docs/island-variants/`, expected
  `ladder-rung-budget` as the only error (check-contracts `!`). Totals on
  main's contract (link 56): 30450.67 (20 s) and 30180.67 (65 km/h); with
  the link at 81: 30475.67 and 30205.67. `just l3-check` 16/16.

### B6. Runs at the declared entry speed (this repo) - done

- What: run the encore and act b three times each on the planning simulator
  with Autoware's velocity cap at the declared entry speed (8.33 m/s), so
  the settling budgets are exercised where they are computed. Record per run
  the entry speed, the observed settle, the profile at that speed and the
  difference.
- Gate: six runs with tables; their response delay feeds B2. A settle row
  that exceeds its term is a finding for B2, not a reason to raise the
  budget silently.
- Status (2026-10-15): done. Six runs (b6-e1..3, b6-b1..3; image
  df1bf38a, the fr round's explain.txt via `RB_EXPLAIN`; `max_vel` 8.3 via
  `L3_PLANNING_COMMON=demo/l3/config/common-30kmh.param.yaml`; a 315 m
  straight, `INIT` 3916.96 73771.77, `GOAL` 3649.19 73632.10), all acts
  PASS at 8.30 m/s. Every settle row exceeds its term: the difference to
  the profile at the entry speed is 204-213 ms (emergency) and 587-785 ms
  (comfortable); totals 4890-4957 of 4934.67 and 20751-20948 of 20475.67.

### B7. Say where each budget comes from (rlm, play_launch)

- What: a measured budget is not an upper bound. The serial hop was set to
  57 ms from a 47.43 ms maximum and later reached 67.02 ms on a rebuilt
  image. Today a measured term and an analysed one look the same in the
  contract and in `--explain`. Add a provenance key per budget
  (`source: requirement | measured | derived | analysed`, with `measured`
  carrying the maximum, the sample count and the margin), and have
  `--explain` mark a total that contains a measured term as "measured, not a
  bound".
- Gate: the island contract states the source of every budget; `--explain`
  prints it per row; a contract whose measured term's stated maximum and
  margin do not reproduce the budget fails (`budget-rule`).

### B8. Every stated budget is checked by something (this repo, play_launch)

- What: some stated values are not charged by the fault-reaction arithmetic
  (`info[declared-not-charged]`, e.g. `control_mode.max_transport: 143ms`),
  and the per-edge serial hop is checked only inside a route row. The
  post-run trace check adds a row per declared `max_transport` edge that
  the trace observes, so a stated hop is always compared with its
  observations; `--explain` lists, per stated budget, what checks it
  (checker sum, runtime monitor, trace check, or nothing).
- Gate: the act tables carry the link rows; no stated budget is listed as
  checked by nothing without a note.
- Status (2026-10-15): the timeline side is done; `--explain`'s list is
  open (play_launch). `analysis.py` adds a row per declared
  `max_transport` edge the trace observes: the declared value from the
  run's own `--explain` (the route's `link`, or `declared-not-charged`),
  the observed hop as the maximum over the run's edges (host stamp ->
  island take on the host clock, as terms.py's `link`; over-stated by the
  smallest out-link delay). Edges with a recorded host side: the guard
  subscriber (gate publish) and `control_mode` (the probe's receipt, not
  the publish). Every table row gets a `checked by` column: checker sum,
  runtime monitor, or the trace only. fr round, against the 81 / 143 the
  runs declared: link into operation_mode_availability a1 38.73, a2 33.66,
  a3 46.42, b1 29.05, b2 20.97, b3 20.77 (PASS); control_mode a1 32.11,
  a2 49.09, a3 95.63 (PASS, checked by the trace only). The encore runs
  have no row: the gate is stopped, so no host edge.

## Not in this phase

- Deriving thread priorities and timer periods from the contract. They
  stay hand-set; B1 only makes the period agree with its parameter.
- Analysed (not measured) route bounds for the serial link and the
  executor. B7 makes the difference visible; the analysis is later work.
