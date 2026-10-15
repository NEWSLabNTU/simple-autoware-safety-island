# Phase 10 - the contract's budgets: where they come from and what checks them

**Goal:** every number in the island's contract says where it comes from
(a requirement, a measurement, or a derivation), every stated budget is
checked by something, and the derived settling covers the vehicle's
response, not only the braking profile.

**Status (2026-10-15): B4, B5, B6, B9 done; the timeline side of B2 and
B8 done; the checker side of B1, B2, B7 and B8 done and released in rlm
v0.1.58, on play_launch main (c0a6a2e6, pinning v0.1.58) and pinned
through nano-ros (f496a8b68a, this repo's pin). The island contract's keys
(branch `phase10-contract-keys-rebased`) wait for play_launch 0.17.0 on
PyPI, which CI installs by version;** B3 done in nano-ros, pinned and
checked on the board.

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
- Status (2026-10-15): the checker is done and released (rlm v0.1.58,
  play_launch main c0a6a2e6); the contract keys wait for play_launch 0.17.0
  on PyPI. rlm 6211471 (in v0.1.58): `trigger: { timer: { rate_hz, param } }` (a
  rate, Hz) or `period_param` (seconds), and `max_age: { duration, param }`
  (`max_age` was not bound before). play_launch 7576ec46: `timer-param` and `max-age-param`, resolved from the launch
  tree's parameter files like `window-param`. Reproduced first: the
  contract's handler timer at `rate_hz: 20` over `update_rate: 10` checks
  clean on 0.16.0; with `param: update_rate` the local build fails it with
  `error[timer-param]: ... /mrm_handler/on_timer ticks at 20 Hz, bound to
  `param: update_rate`, and 'update_rate' resolves to 10 Hz`. Fixture
  `tests/fixtures/contract_param_bind` in play_launch, parse tests in rlm.
  The island contract with `param:` on every timer and on `max_age` is on
  branch `phase10-contract-keys-rebased`: it checks clean on the local build and
  is refused (`manifest-parse`) by the pinned 0.16.0, so it waits.

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
- Status (2026-10-15): the timeline side, the key and the checker are done;
  the contract's values are on branch `phase10-contract-keys-rebased`,
  waiting for play_launch 0.17.0 (B1's status). rlm: `settle: { decel, jerk, response }`;
  play_launch 7e10a661: the settle is profile + response, `settle-derived`
  prints both parts ("... = 4165.33ms; + response 256.00ms (written) =
  settle 4421.33ms"), the totals include it and `--explain` notes
  `settle = profile + response` per row. Values from B6 at the declared
  entry speed, by the measurement rule: emergency 256 ms (213.11 x 1.2),
  comfortable 943 ms (785.43 x 1.2, the planner's hop included). With them
  the island's totals are hpc_loss 5165.67 (slack 4834.33), odd_exit
  comfortable_stop 21393.67 (slack 8606.33), odd_exit floor 14914.67. `analysis.py` adds the row "settle at the
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

### B3. A runtime check of the route, not only of the callback (nano-ros) - done

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
- Status (2026-10-15): done in nano-ros (PR #2221, merged as `67e29e9fa`), pinned
  here; checked on the board (below). The executor stamps the
  dispatch that takes a route's trigger input (the earliest take not yet
  answered) and, at the end of a dispatch that published one of the path's
  outputs, judges take to dispatch end against the path's `max_latency`:
  `route-latency-runtime`, rule code 10, record only, reported once until
  a route is within budget again. The violation record's layout is
  unchanged (v1: the rule is a code); `tools/timeline/violations.py` says
  which quantity each latency rule measured. The timer sweep judges it as
  the drains do (the sweep's blind spot for `max-latency-runtime` was
  closed by nano-ros phase-474 I6 before this). Codegen gives the route to
  the outputs of the tightest input-triggered path: on this image
  `mrm_state` and `takeover_request_state` carry `call_mrm`'s 149 ms from
  the take of `/system/operation_mode/availability` (hazard lights stays a
  100 ms callback-only row). Board image: RAM 276,152 B and DTCM 116,624 B
  unchanged (the row storage stays 6 x 64 B), FLASH +1,528 B, against
  the same tree on the PR's base; at the pin, with the other changes it
  brings, RAM 276,152 B, DTCM 116,632 B of 131,072, FLASH 559,108 B. Fixtures in
  nano-ros: a host executor test (three on-time routes record nothing; a
  take followed by a 260 ms late tick records one verdict while the tick's
  own dispatch stays inside its callback budget) and the violation-cpp
  image on native_sim (two late routes, `measured=250 declared=180`, none
  on time). The pin refuses a knob stated as an `env` row or a Kconfig
  line and the retired `NANO_ROS_*` cmake names (nano-ros phase-484 W8), so
  the board image's three knobs move to knob tables in
  `src/zephyr_entry/system.toml`, the native_sim image's ring depth to
  `src/native_sim_entry/system.toml`, and the posix workspace build says
  `nano_ros_ROOT` and `NROS_PLATFORM`. Built on this pin: the board image
  and the native_sim image. The QEMU image and the posix workspace build
  were fixed after (below, "Builds at the pin").
- Builds at the pin (2026-10-15, at nano-ros f496a8b68a; each checked
  against the previous pin 43fc1c2f first):
  - QEMU image: failed at 43fc1c2f as well (`NROS_ZEPHYR_HEAP_SIZE ... is
    assigned in a configuration file, but is not directly user-configurable`),
    so not new. The heap and graph cache (boards/mps2_an385.conf), the ring
    depth (trace.conf) and graph discovery off (snippets/qemu-ethernet) are
    knob tables in `src/qemu_entry/system.toml`, values unchanged; the
    board's `island-ethernet` snippet line moves to
    `src/zephyr_entry/system.toml` the same way (the serial gate image
    derives it off already). `qemu-build`'s heap lever passes
    `-DNROS_OVERRIDE_ZEPHYR_HEAP_SIZE` (a `-DCONFIG_` line for a knob is
    refused), so `trace-qemu-build` keeps its 1 MiB heap.
  - posix `just build`: two refusals new at this pin and one link failure
    already present at 43fc1c2f. New: `nros ws board-facts` asks which of
    the four system.toml files (the recipe now passes
    `-DNROS_BRINGUP_DIR=src/safety_island_bringup`, which declares no image,
    so nothing to carry as before), and board `native` is retired for
    `linux` (src/native_entry). Old: `nros_cpp_declare_param` undefined at
    link, because the posix nros-cpp had no parameter store while the
    generated entry seeds the launch parameters; the bringup now declares
    `features = ["params"]` (nano-ros phase-461 W6, the store without the
    services). Board RAM 276,152 B and DTCM 116,632 B unchanged by it.
  - Trace markers: `gen_markers.py` reads the integer knobs of the entries'
    system.toml knob tables (named through the pinned
    `NanoRosKnobRegistry.cmake`) beside the conf files, so the provenance
    list has `CONFIG_NROS_ZEPHYR_HEAP_SIZE` and
    `CONFIG_NROS_GRAPH_CACHE_SIZE` again; `just trace-gen-check` passes.
  - Gate: `just build`, `just qemu-build`, `just board-build` (FLASH
    559,164 B, RAM 276,152 B, DTCM 116,632 B), the native_sim image
    (`just trace-window-native-build`) and `just l3-check` (16 contracts,
    every verdict as expected) all pass.
- Board check (2026-10-15, done): image sha256 `3a41bdcf...` (`just
  board-build` at e55a63b), flashed by run-board.sh.
  - `b3-e2`, encore: `SUMMARY b3-e2 encore: PASS; load 31.35 at act; table
    8/8 PASS (+1 n/a), total 3484.19 of 4909.67 ms; trace-check PASS, trace
    18,588 of 53,248 B over 37.8 s; stored 1 (silence-runtime x1)`. The
    record and the trace's list hold only the arming `silence-runtime`: no
    `route-latency-runtime`.
  - `b3-ov2`, the phase9-W4 overrun gate (encore with the act replaced by
    `violations.py read`, `violations.py overrun 250`, 5 s, `read`): the
    trace lists, 0.5 ms apart, `route-latency-runtime
    /mrm_handler/mrm_state measured=332 declared=149` and the same on
    `/mrm_handler/takeover_request_state`, then the three
    `max-latency-runtime` verdicts (hazard lights 250/100, MRM state and TOR
    state 250/149), three `timer-overrun-runtime` and one
    `release-jitter-runtime` (241,845 us). The route is 332 ms because its
    take (34389.48 ms) waited 82 ms for the tick that then busy-waited 250
    ms (verdict at 34721.57 ms). The 8-slot record kept #3-#10 (`dropped=2`:
    the arming silence and the `mrm_state` route); the trace keeps all ten.
  - `b3-b1` and `b3-b2`, act b (the comfortable stop after the window's
    expiry): the record and the trace hold only the arming silence; no
    route verdict on the expiry path (route on the island clock 2.04 ms in
    b3-b1). Both read `FAIL` on one table row only, `HPC alive: longest
    availability gap (host)`, 1086.91 and 556.21 ms at load 30.6 and 25.5,
    while the gate's own largest publish gap was 106.54 and 102.87 ms and
    the island stored no silence. The stream did not stop: inside the
    probe's gap (1314.64 and 705.41 ms raw) the island took the
    availability 14 and 7 times, 79.9-107.5 ms apart, while the probe got
    only 3 and 2 samples of its OTHER topics too, so the probe process
    stalled, not the topic. The same row passes in fr-b1..3 (102.20-102.91
    ms, act load 7.1-9.0) and b6-b1..3 (107.02-111.09 ms, act load
    14.8-19.5); b3-b1/b2 ran at act load 30.6 and 25.5, under the
    RB_LOAD_MAX of 35 but with other builds on the host. Same symptom as runs b3 and b4 in
    section 3 of docs/takeover-trace.md: the host probe, not the stream,
    and not B3.

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
- Status (2026-10-15): the checker is done; the contract waits for the
  release (B1's status). rlm: every budget key takes the map form
  `{ duration, source }` (and a window takes `source`), `source:
  requirement | measured | derived | analysed`, and a measured one may
  state `{ measured: { max, n, margin } }` or several `terms` (a timer
  tick's `period` takes no margin). play_launch b31fbeb9: `budget-rule`
  (error), a SOURCES column per row, every total with a measured term
  noted "measured, not a bound", and a "Stated budgets" table with each
  budget's source and the rule's arithmetic. On branch
  `phase10-contract-keys-rebased` every budget of the island contract states its
  source, the measured ones with the maxima from its comments (link 56 =
  46.42 x 1.2; `call_mrm` and `driver_exit` 149 = tick 100 + 14.84 x 1.2
  -> 118 + work 25.04 x 1.2 -> 31; the timers' jitter 18 and 6; the
  `control_mode` link 143); every hazard's total is measured, not a bound.

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
  done in play_launch b31fbeb9 (released with B1): per stated budget, what
  checks it (the fault-reaction sum with the hazards, a rule such as
  `scope-budget`, `reaction-within`, `window-param`, `max-age-param`,
  `window-expiry`, a runtime monitor, or nothing), and
  `declared-not-charged` reads the same table, so it now says of
  `control_mode`'s 143 ms that nothing else in the checker checks it;
  the contract's comment notes that the trace check does. On the island
  contract that is the one budget listed as checked by nothing. `analysis.py` adds a row per declared
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

### B9. The run's verdict says when a budget row fails (this repo) - done

- What: `run_summary.py` printed the scenario's verdict, the safe state
  reached, as the act's: b6-e2 read `encore: PASS; table 6/8 PASS, total
  4957.25 of 4934.67 ms` with settle and total over budget and only
  "within the FTTI" passing.
- Gate: an act whose table has a FAIL row reads FAIL in its SUMMARY, with
  the rows named and an FTTI-only success visible; the fr round stays PASS.
- Status (2026-10-15): done. `run_summary.budget()`: a FAIL row turns PASS
  into `FAIL (the act PASS; <n> table row(s) FAIL: <terms>; within the
  FTTI PASS)` and is appended to a FAIL; VOID, INVALID and REFUSED are
  kept. Exit codes unchanged (run-board.sh: 0/1 the scenario's verdict, 3
  refused, 4 void; docs/tracing.md). Re-read offline: b6-e1 FAIL (settle),
  b6-e2, b6-e3, b6-b1..3 FAIL (settle, total), all within the FTTI; fr-a1..3,
  b1..3, e1..3 PASS. Open: whether run-board.sh's exit code should carry
  the budget verdict too (cast.sh and callers read it as the act's).

## Not in this phase

- Deriving thread priorities and timer periods from the contract. They
  stay hand-set; B1 only makes the period agree with its parameter.
- Analysed (not measured) route bounds for the serial link and the
  executor. B7 makes the difference visible; the analysis is later work.
