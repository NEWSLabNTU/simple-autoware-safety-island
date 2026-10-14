# Phase 10 - the contract's budgets: where they come from and what checks them

**Goal:** every number in the island's contract says where it comes from
(a requirement, a measurement, or a derivation), every stated budget is
checked by something, and the derived settling covers the vehicle's
response, not only the braking profile.

**Status (2026-10-15): plan.** B4, B5 and B6's runs are in progress; nothing
else is implemented.

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

### B6. Runs at the declared entry speed (this repo) - in progress

- What: run the encore and act b three times each on the planning simulator
  with Autoware's velocity cap at the declared entry speed (8.33 m/s), so
  the settling budgets are exercised where they are computed. Record per run
  the entry speed, the observed settle, the profile at that speed and the
  difference.
- Gate: six runs with tables; their response delay feeds B2. A settle row
  that exceeds its term is a finding for B2, not a reason to raise the
  budget silently.

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

## Not in this phase

- Deriving thread priorities and timer periods from the contract. They
  stay hand-set; B1 only makes the period agree with its parameter.
- Analysed (not measured) route bounds for the serial link and the
  executor. B7 makes the difference visible; the analysis is later work.
