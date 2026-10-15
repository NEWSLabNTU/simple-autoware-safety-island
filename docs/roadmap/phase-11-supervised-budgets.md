# Phase 11 - supervised budgets: a measured number is met, or its miss is caught in time

**Goal:** every budget in a contract is either a bound (analysed) or a
supervised expectation: the runtime catches an overrun and starts a
fallback, and the checker shows that the overrun case still fits the
hazard's FTTI. A budget that is neither is reported as such, as a warning
or an error by project policy. A timer's period gets a feasible range from
the same arithmetic.

**Status (2026-10-16): plan. Nothing here is implemented.** Grounded in a
read of rlm (main, v0.1.60), play_launch (main, 0.17.0), nano-ros (the
island's pin, 79583587cf) and this repository; file:line references are at
those revisions.

## Why

Phase 10 made every budget say where it comes from. Most of the island's
are `source: measured`: a maximum over board runs plus 20 %. A measurement
is not a bound (the serial hop was set to 57 ms from a 47.43 ms maximum and
later reached 67.02 ms), and `--explain` marks every hazard's total
"measured, not a bound". Two ways out:

- **Analyse the terms.** Execution time needs a WCET tool that holds only
  under its processor model (static analysis is used by few teams);
  transport needs a model of the serial link, the network or the
  middleware. Neither is knowledge a ROS user should have to write into a
  launch contract.
- **Supervise them.** The user states what they expect; the runtime
  checks it while the system runs and starts a fallback when it is broken;
  the checker proves that "budget + detection + fallback" fits the FTTI.
  This is deadline supervision as in the AUTOSAR watchdog manager, and it
  needs no timing-analysis tool. The safety claim becomes: every budget is
  met, or its violation is detected and handled within the FTTI.

This phase takes the second. The split of responsibility:

| who | owns |
|---|---|
| the user | the expectation: a budget, its source (`measured: { max, n, margin }`), and which fallback a miss starts |
| the toolchain (rlm, play_launch, nano-ros) | the supervision: a deadline monitor per supervised budget, its detection delay, the overrun-case arithmetic, the level of each budget |
| a platform package | transport and hardware knowledge (a link's bound, a watchdog), stated once and referenced by name; a later phase (play_launch phase 91's profiles), not this one |

`source: analysed` stays, as an upgrade for those who have an analysis; it
is never required.

## What exists today

- **Grammar (rlm).** A budget's map form is `{ duration, source, param? }`
  (rlm `types/src/bound.rs`, `parse.rs:227`); the source goes to
  `Manifest.budget_sources` (`types.rs:90`, `SourceKind` `:110`).
  `on_violation { on, mechanism, reaction, within }` attaches only to a
  subscriber (`types.rs:589`, `:857`); `FaultKind` is omission | late |
  loss | reported (`types.rs:558`), none of which is "the computation
  overran". A path cannot carry `on_violation`; the nearest key is `miss:
  { tolerate, consecutive, action }` (`types.rs:1394`), a weakly-hard
  policy with no reaction and no detection time.
- **Checker (play_launch).** `check_fault_reaction`
  (`ros/manifest_loader.rs:2597`) builds one row per ladder rung: detection,
  windows, the route walked by `walk_reaction` (`:1993`), settle
  (`settle_of`, `:2976`), total against the FTTI. `walk_terms` (`:382`)
  collects the stated keys on a row, as keys without their order or
  values. `--explain`'s CHECKED BY column (`ros/budget_book.rs:220`) says
  "runtime monitor (...)" from the key's shape (`:249`, `:298`, `:341`):
  nothing checks that a monitor exists or that it reacts.
- **Runtime (nano-ros).** `route-latency-runtime` (`monitor.rs:1093`
  stamps the take at the trigger's dispatch start, `:1112` judges at the
  end of the dispatch that publishes) is completion-based: an output that
  never comes leaves the route pending forever, with no verdict. Every
  monitor records only (`monitor.rs:41`). The island's one reacting
  detection, the availability silence, is the application's own:
  mrm_handler polls `isInputLost()` on its 10 Hz tick
  (`mrm_handler_core.cpp:616-625`), independently of nano-ros's
  `max_age` verdict. The tier `DeadlineAction::Fault` calls a fault hook
  that panics when none is set (`spin.rs:3394`), Rust-only.
- **Executor.** One spin thread; timers fire on the first spin at or after
  their due time; the park ends at the earliest of the timers and the
  registered wake sources (`spin.rs:3452`, `:3510-3548`); 1 ms ticks
  (`src/zephyr_entry/prj.conf:19`). A check inside the executor cannot
  fire while a callback is stuck.
- **Watchdog.** Zephyr's `wdt_nxp_s32` drives the S32K344's SWT0
  (`status = "okay"`, left disabled at boot; first timeout calls the
  installed callback, the second resets). The FS26 SBC watchdog is off in
  DEBUG mode. The island sets `CONFIG_WATCHDOG=y` and uses neither.

## The measured budgets of the island contract

`src/safety_island_bringup/launch/safety_island.contract.yaml` (C):

| budget | value (max seen) | in | fallback if it overruns | supervisable on the island |
|---|---|---|---|---|
| `call_mrm.max_latency` | 149 (tick 118 + work 31) | hpc_loss once, odd_exit twice | hpc_loss: brake now; odd_exit: skip the request, start the comfortable stop | yes; no rung below it when the executor itself is stuck (S4) |
| handler timer jitter | 18 (14.84) | inside tick 118 | as `call_mrm` | through `call_mrm`'s route |
| operator timer jitter | 6 (4.34) | hpc_loss sampling | none below the emergency operator | through the operator's route (S4) |
| `driver_exit.max_latency` | 149 | no hazard | none needed (the window still expires) | yes, level only |
| availability `max_transport` | 56 (46.42, n 12) | both hazards | - | no: host stamp, island take, no shared clock. Total loss is caught by `max_age` 500 |
| `control_mode.max_transport` | 143 (118.78, n 5) | no hazard | - | no (deferred to an Ethernet link, phase 10) |
| comfortable settle `response` | 943 (785.43, n 3) | odd_exit | escalate to the emergency stop | yes: no deceleration in `kinematic_state` by take + 943 |
| emergency settle `response` | 256 (213.11, n 3) | hpc_loss, odd_exit floor | none on the island (it is the floor) | observable; no rung below it |

Slack on main (link 56): hpc_loss 5,165.67 of 10,000 ms; odd_exit
21,393.67 of 30,000 ms. By hand, with d the detection delay: `call_mrm`
overrunning in hpc_loss gives 5,165.67 + d; the comfortable stop failing
at its response gives 100 + 56 + 149 + 10,000 + 149 + 943 + d + the
emergency route 39.33 + the emergency settle 4,421.33 = 15,857.66 + d. Both
fit with seconds to spare, so the arithmetic is not the hard part; the
monitor that fires on time, and the rung it can still start, are.

## Units

### S1. The supervision keys (rlm)

- What: a `supervise:` sibling of `source:` in every budget's map form, so
  every budget key takes it at once:

  ```yaml
  max_latency:
    duration: 149ms
    source: { measured: { terms: { tick: { period: 100ms, max: 14.84ms }, work: { max: 25.04ms } }, margin: 0.2 } }
    supervise: { reaction: brake_now, mechanism: timer }
  ```

  `reaction` resolves as `on_violation`'s does (a path of the same node),
  and also takes a scope path or `enters: <mode>`. `mechanism`:
  `executor` (checked in the spin loop: catches slowness, not a stuck
  callback) or `timer` (an independent timer and thread: catches both,
  needs S4). A new `FaultKind` `overrun` for traces and verdicts.
  A top-level `policy: { unsupervised_measured: warn | error }` (default
  warn). `SourceKind::Allocated` for a value chosen inside a range the
  checker derives (S5). The level of a budget is derived, never written:
  analysed -> bound; measured + supervise -> supervised; measured alone ->
  unsupervised. All core: they add a checker rule and runtime behaviour,
  which the extension system (play_launch phase 91) must not.
- Gate: rlm round-trips the keys; field rows with SINCE; format reference
  regenerated; no migrate rewrite (additive).
- Size: ~150 LOC plus tests.

### S2. The overrun case in the checker (play_launch)

- What: `walk_terms` keeps each term's order and value
  (`Vec<(TermKey, f64)>`). For each supervised term on a row, a new
  `RungRole::Overrun` row: the terms before it + its budget + the
  detection delay + the reaction's route (`walk_reaction`) + its settle,
  against the hazard's FTTI; rule `supervised-fit`. Detection delay by
  mechanism:
  - `executor`: 1 tick + the longest callback on that executor (its stated
    `max_latency` work term, else unknown -> error) + the check;
  - `timer`: 1 tick + the interrupt and thread switch (a stated platform
    term).
  A reaction that runs on the same executor as the route it supervises,
  under `mechanism: executor`, is reported "covers slowness, not a hang".
  The CHECKED BY column reads the lowering (a supervised budget lowered to
  a monitor row with a reaction), not the key's shape. A LEVEL column
  replaces the "measured, not a bound" note; rule `measured-unsupervised`
  at the policy's severity.
- Gate: the island contract's overrun rows printed with their arithmetic;
  a fixture where the overrun case exceeds the FTTI is refused; a
  supervised budget with no lowered monitor is refused.
- Size: ~700-900 LOC with tests.

### S3. A deadline-armed route monitor (nano-ros, PR)

- What: `route_take` also stores `due = take + budget`; the executor offers
  the earliest due as a wake source; `run_contract_monitors` adds
  `route_overdue`: pending and `now >= due` -> `Violation{
  "route-deadline-runtime" }`, the reaction hook called, the route marked
  violated. The hook generalises `set_fault_handler` to a function plus
  context with the reaction's id, exported through nros-cpp
  (`nros_cpp_executor_set_reaction_hook`); codegen carries the reaction id
  per route row (`contract_monitors.rs`, `entry.cpp.jinja`). The
  completion verdict `route-latency-runtime` stays.
- Gate: a unit test where the output never comes fires at due + 1 tick; a
  QEMU test calls the hook; the existing route tests unchanged.
- Size: ~120 LOC plus ~150 test. PR with auto-merge, then the island pin.

### S4. The rung that does not need the executor (this repo)

- What: `mechanism: timer` on the island. A `k_timer` re-armed to the
  earliest due route; its expiry (ISR) wakes a reaction thread above the
  spin thread's priority. That thread must not touch the executor or the
  zenoh session (neither is thread-safe), so its action is direct: a
  safe-state output that bypasses the stack. On this board a GPIO (an LED
  stands in for the brake line); on a vehicle, the actuator's own safe
  input, out of scope here. SWT0 fed once per spin, its timeout above the
  longest spin, its first-timeout callback the same action: a hung
  executor is caught even with no route pending.
- Gate: on the board, a stall that never ends inside the handler's tick
  drives the safe-state output within budget + 1 tick + the switch; SWT0
  catches a stuck spin and the output follows.
- Size: ~150 LOC C, Kconfig, the contract's platform term for the switch.

### S5. A feasible range for each timer's period (play_launch)

- What: every rung row records how many times each timer's period enters
  it (sampling hops, reported detection, a measured `tick: { period }`
  term, the window owner's notice). Upper bound: the current period plus
  the smallest slack / count over the rows, cross-checked by re-running the
  walk with that period. Lower bound: sum of work / period per executor
  <= 1, from measured `work` terms or a platform file's `budget_us`;
  "unknown" when a timer on the executor has no work stated. A table in
  `--explain`; with `source: allocated` on `rate_hz` the checker refuses a
  period outside the range.
- Gate: the island's 10 Hz handler gets a printed range with its limits
  named. Expected: the FTTI does not bind it below seconds; what binds it
  from above is `max_age`'s detection (500 + one period) and the
  emergency-stop requirement, which the range must show.
- Size: ~400-600 LOC.

### S6. The island contract, supervised (this repo)

- What: `supervise:` on `call_mrm` (hpc_loss: `timer`, the S4 output;
  odd_exit: `executor`, the comfortable stop), on the comfortable settle's
  response (`executor`, escalate to the emergency stop on no deceleration
  in `kinematic_state`; needs a check in mrm_handler or a monitor on that
  input), and on `driver_exit` (level only). Left unsupervised with a
  reason in the contract: the availability hop (no shared clock; total
  loss is `max_age`), `control_mode` (phase 10), the emergency response
  (the floor; the vehicle's own). The variants in `docs/island-variants/`
  follow.
- Gate: `play_launch check --explain` lists every budget with its level;
  the unsupervised ones carry their reason; CI on the next play_launch
  release.

### S7. The board check of a supervised overrun (this repo)

- What: the overrun hook (`island_debug_overrun_ms`,
  `mrm_handler_core.cpp:682-690`) armed for the fault tick, and a
  never-ending stall. An act (`RB_ACT=overrun`) that injects the hazard and
  the overrun together. Trace markers for the deadline verdict and the
  fallback's start. New rows in `analysis.py`: deadline -> fallback start
  <= detection delay; fallback -> standstill <= its settle; total <= FTTI.
  The `HPC alive` row taken from the island's takes, not the host probe
  (phase 10: the probe stalls under load).
- Gate: hpc_loss with an overrun and with a stall, and odd_exit with a
  comfortable stop that does not decelerate: each lands in its safe state
  within the FTTI, the overrun row PASS.

## Order

S1 first (the keys). S2 and S3 in parallel after it. S5 any time after S1.
S4 after S3 (it shares the due time). S6 after the rlm and play_launch
releases carrying S1, S2 and S5, and the nano-ros pin carrying S3. S7 last,
on the board. One agent owns the board.

## Not in this phase

- Analysed bounds for execution time and transport. `source: analysed`
  takes them when a user has them; a platform package (play_launch phase
  91's profiles) is where a link's or a processor's numbers would live.
- A runtime check of a host-to-island hop: needs a shared clock (phase 10).
- The vehicle-side safe input below the emergency stop.
- Thread priorities from the contract: the island has one spin thread;
  S4's reaction thread is set above it by construction.
