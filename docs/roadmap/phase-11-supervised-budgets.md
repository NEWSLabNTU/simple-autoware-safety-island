# Phase 11 - supervised budgets: a measured number is met, or its miss is caught in time

**Goal:** every budget in a contract is either a bound (analysed) or a
supervised expectation: the runtime catches an overrun and starts a
fallback, and the checker shows that the overrun case still fits the
hazard's FTTI. A budget that is neither is reported as such, as a warning
or an error by project policy. A timer's period gets a feasible range from
the same arithmetic.

**Status (2026-10-16): in progress.** S4 is done on the board. S6 and S7
are done on branch `phase11-s6` (the five S6 decisions below; S7's
overrun, stall and comfortable-escalation acts PASS on the board), and
reach main with the CI move to play_launch 0.18.0, which carries S1, S2
and S5 (rlm v0.1.61). S3 is merged in nano-ros (#2264, #2266, #2267,
#2271, and #2279: a late completion of a supervised route is a deadline
miss) and pinned at 7874373b01. Open: the comfortable settle cannot be
`supervise:`d in 0.18.0 (S6). The emergency response is re-sized to 319 ms
from 16 stops at 8.30 m/s (S6, gap 2), and the overrun's ~220 ms slower
stop was the timeline's clock alignment, not the handback (S7, gap 3). The plan below was grounded in a read of rlm (main,
v0.1.60), play_launch (main, 0.17.0), nano-ros (the island's pin,
79583587cf) and this repository; file:line references are at those
revisions.

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
| emergency settle `response` | 319 (265.34, n 16; was 256 from 213.11, n 3) | hpc_loss, odd_exit floor | none on the island (it is the floor) | observable; no rung below it |

Slack on main (link 56): hpc_loss 5,228.67 of 10,000 ms (5,165.67 with the
256 ms response); odd_exit 21,393.67 of 30,000 ms. By hand, with d the detection delay: `call_mrm`
overrunning in hpc_loss gives 5,165.67 + d; the comfortable stop failing
at its response gives 100 + 56 + 149 + 10,000 + 149 + 943 + d + the
emergency route 39.33 + the emergency settle 4,484.33 = 15,920.66 + d. Both
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
- Status (2026-10-16): done on the board, with the handler arming the route
  itself (below); the nano-ros hook is wired but has no row to fire yet.
  `CONFIG_ISLAND_SUPERVISOR` (on in the board conf),
  `src/zephyr_entry/src/island_supervisor.c`: a `k_timer` re-armed to the
  earliest due of two routes; its expiry gives a semaphore to a reaction
  thread at priority 2 (the spin thread runs at 3; a build assert keeps it
  above) that records `SUPERVISOR_DEADLINE` (arg route << 28 | the due's
  uptime ms) and drives CAN LED1 (PTE5, node `can_led1` of the board DTS,
  the brake line's stand-in) with a raw port write, then
  `SUPERVISOR_SAFE_STATE` (arg the cause: 1 route, 2 SWT0, 3 the
  executor's hook). It touches neither the executor nor the session. The
  output latches until reset. SWT0 (`wdt_nxp_s32`) is installed and started
  at the first spin, fed at the start of every spin, timeout 300 ms
  (`CONFIG_ISLAND_SUPERVISOR_SWT_MS`), paused while a debugger halts the
  core; its first-timeout callback wakes the same thread. Once the output
  is latched the reaction thread feeds SWT0 itself, so the second timeout
  (the MCU reset, which would also release the output) is left for a
  reaction thread that cannot run. Everything is in
  `island_supervisor_record` (SWD; `violations.py supervisor`, and
  `supervisor.txt` in every act's readout).
  - Route 0, armed by the handler until nano-ros arms deadlines from the
    model: every availability take sets due = take + max_age 500 + call_mrm
    149 (`CONFIG_ISLAND_SUPERVISOR_CALL_MRM_MS`), once the monitors are
    armed; the call_mrm EXIT of a tick that saw the loss clears it. That is
    the hpc_loss reaction's deadline, an omission: no take is pending at
    the fault tick, so a completion-based route monitor (S3's, or B3's
    `route-latency-runtime`) has nothing to judge there. p11-ov1 shows it:
    a 300 ms overrun of the fault tick stored three `max-latency-runtime`
    verdicts (301 ms) and no route verdict.
  - Route 1, nano-ros phase-503 (S3; pinned at 573490978d since #2271,
    whose play_launch (68aa242d, rlm 33577ff) resolves `supervise:`; before
    it b7e63a5b44: #2264, the model read of #2266, and #2267, a monitor row
    of 72 B on a 32-bit target, without which nros-cpp did not build for
    the board):
    `nros_app_reaction_hook` wakes the thread (cause 3) and, after every
    spin, `nros_cpp_executor_route_next_due_us` re-arms route 1. The
    generated entry installs the hook only when a monitor row is
    supervised. Main's contract states no `supervise:`, so on main route 1
    is idle; the S6 draft's image has the rows (S6 status).
  - Board images: 5fa405ff (`just board-build` at 08c8296, pin
    79583587cf; FLASH 563,060 B, RAM 277,432 B, DTCM 117,120 B) and, at the
    pin b7e63a5b44 with the hook wired, 71e81adc (FLASH 564,584 B, RAM
    277,400 B, DTCM 117,192 B of 131,072).
    - Flashing: three first flashes after an act failed with `Memory
      transfer fault (FAULT ACK)` in the flash algorithm's RAM (p11-e1,
      p11-e2, p11-s6-ov1). The reset with the core halted that
      `run-board.sh` now does first did not prevent the third, and SWT0
      reads disabled after that reset (SWT_CR 0xff00010a), so the cause is
      not known. An interrupted flash then left a sector whose read faults
      on every retry (`@ 0x0041f000` while erasing); `pyocd erase -t
      s32k344 --sector 0x41f000` (one sector, never `--chip`) cleared it,
      and run-board.sh's failure message says so.
    - p11-swt1, SWT0 with no route pending (the encore with the act
      replaced by `violations.py spin-stall`, `island_debug_spin_stall`,
      `CONFIG_ISLAND_DEBUG_SPIN_STALL`): the spin stalls at uptime
      92,947.11 ms (`SUPERVISOR_INJECT`), SWT0's first timeout calls back
      at 93,235.86 ms (288.75 ms later: 300 ms nominal on the 32 kHz SIRC,
      counted from the last feed) and the output is driven 0.027 ms after
      the callback, cause SWT0. No reset followed. Before the stall the
      longest feed-to-feed gap over 20,846 spins was 10.63 ms, so the
      300 ms timeout is 28 times the longest spin seen.
    - p11-ov2..4, p11-st1..2 (S7 below): the route's verdict 0.024-0.03 ms
      after its due and the output 0.036-0.05 ms after it, against the
      1 ms tick + 1 ms switch the S6 draft states.
    - A plain encore leaves it dark: p11-e1 (pin 16ee271442 with #2267
      applied) and p11-e2 (71e81adc) read `supervisor not driven`, route 0
      armed 333-334 times and met once (the fault tick's EXIT 562-575 ms
      after the last sample, inside the 649 ms due), longest spin 10.66 ms.
      Both read FAIL on one phase-10 row only, `settle at the observed entry
      speed`: response 463.80 and 441.41 ms at 4.21 m/s against the 256 ms
      sized at 8.3 m/s (phase10-B2; the fr round at this speed measured
      352.54-488.91), not on anything this phase changed.

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
- Decisions (2026-10-16), each with its reason:
  1. `call_mrm` is supervised with `mechanism: timer` for both chains,
     `supervise: { enters: emergency_stop, mechanism: timer }`; nothing in
     the contract uses `executor`. One `supervise:` per budget, and the
     executor's check cannot see one long callback that overruns before it
     returns (p11-s6-b1).
  2. The reaction commands the emergency stop itself, not only CAN LED1, so
     `enters: emergency_stop` holds: the timer rung's thread publishes
     mrm_state MRM_OPERATING / EMERGENCY_STOP, the hazard lights and the
     emergency operator's braking command directly (the direct path below),
     because the callback that is stuck may own the handler's state.
  3. One `supervision: { tick: 1ms, switch: 1ms }` for the contract; it
     holds because only the timer mechanism is used. The contract states
     that an executor detection would be tick = spin period + the longest
     callback, and that none is used.
  4. The comfortable stop is supervised to standstill (option C): not at
     standstill by the comfortable call + settle 9996.67 + response 943 (at
     8.33 m/s) + 156 for the island to see it, the emergency stop is
     commanded, timer mechanism. The deceleration onset is not the test:
     the speed first falls 940-990 ms after the request at 8.3 m/s, past
     the response term.
  5. A settle is judged as one sum at the entry speed bound (option A): the
     whole settle, safe command to standstill, against settle + response at
     8.33 m/s; the lag at the observed speed is information. The lag
     depends on the speed, the sum is what the FTTI arithmetic uses.
- Status (2026-10-16): on branch `phase11-s6`, rebased onto main at
  4a56aac, nano-ros pinned at 7874373b01 (#2279: a supervised route that
  completes after its due records `route-deadline-runtime` and calls the
  hook). Board image 2b8a7985 (`just board-build`; FLASH 567,552 B, RAM
  280,632 B, DTCM 117,304 B). Checks clean with play_launch main 9af9c631
  (0.18.0's release commit plus a CI fix; rlm v0.1.61), built locally,
  16/16 contracts as expected; 0.17.0 refuses the keys, so main takes it
  with the CI bump to 0.18.0.
  - The contract: `supervision:` with its comment (decision 3);
    `call_mrm`'s `supervise:` as drafted, its comment naming routes 0 and
    1 and the direct path. The comfortable `response` is not
    `supervise:`d: 0.18.0 lowers only a node path's `max_latency` to a
    monitor (`supervised-unlowered`, an error, on a settle's response), and
    its overrun row would charge the response alone (before it 10454 +
    budget 943 + detection 2 + route 188.33 + settle 4421.33 = 16008.67),
    not the settle the response ends. The contract states the island's
    supervision and its overrun case in a comment: 21393.67 + 156 + 2 +
    188.33 + 4421.33 = 26161.33 ms of 30,000 (26224.33 with the 319 ms
    response, gap 2 below). The variants follow.
  - `--explain` overrun rows (`supervised-fit`): hpc_loss 556 + 149 + 2
    (tick 1 + switch 1) + island.emergency_stop 188.33 + settle 4421.33 =
    5316.67 of 10,000 ms; odd_exit (comfortable and emergency rungs)
    10305 + 149 + 2 + 188.33 + 4421.33 = 15065.67 of 30,000. With the
    319 ms response (gap 2): 5379.67 and 15128.67.
  - The direct path (`island_supervisor.c`, `island_supervisor_set_direct`,
    `_handover`, `_latched`). Once the output latches, the reaction thread
    calls each component's direct function at once and every 33 ms until
    that component's own tick publishes the emergency: slot 0, mrm_handler,
    mrm_state and the hazard lights; slot 1, the emergency operator, its
    braking command, the operator's ramp in closed form from the last
    control command it saw. Safe against the spin thread because each
    function uses only publishers built at construction and messages it
    owns, never the executor, a take or a service; zenoh-pico is built
    multi-threaded (its tx mutex serialises writers, with priority
    inheritance). The handler reads the latch every tick (`isInputLost`),
    so a spin thread that resumes enters and holds the emergency stop
    through its own path and hands over (`SUPERVISOR_HANDOVER`); the
    operator continues the direct ramp from its last command. The three
    publishers are `tx_express`: batched, the direct path's samples waited
    for a flush that the flush thread, below a stalled spin thread, never
    ran (s6-st3: bursts of six every ~200 ms, and the host's own heartbeat
    timeout stopped the vehicle first). Reaction thread stack 4096.
  - Route 2, the comfortable standstill: armed at the comfortable call,
    due = call + 10940 + 156 (`CONFIG_ISLAND_SUPERVISOR_COMFORTABLE_MS`,
    `_STANDSTILL_OBSERVE_MS`). At the due the thread judges the speed the
    handler last noted from `kinematic_state` (fresh within 300 ms, below
    1 mm/s is standstill); not at standstill, it latches and the direct
    path commands the emergency stop. The 156 ms (one 10 Hz period + the
    link 56) came from s6-b8-1: a stop met on the host 52 ms before a due
    of call + 10940 was not yet seen on the island and was escalated.
    `kinematic_state` already reaches the island (mrm_handler's
    `isStopped()` input); no new input was needed.
  - `analysis.py`: the settle rows per decision 5; supervised rows on the
    direct path (due -> first braking command, command -> standstill, the
    handovers as information; a stall is now judged, the island brakes);
    act b's escalation rows (call -> due, due -> verdict and command,
    command -> standstill, the total against the overrun case);
    `parse_explain` reads 0.18.0's overrun rows. `run-board.sh RB_INERT=1`
    (act b, `violations.py comfortable-inert`).
  - Speed sweep (decision 5), image 2b8a7985, the 315 m straight,
    `max_vel` 2.0 / 4.17 (stock) / 6.0 / 8.3 m/s; every act PASS:

    | run | act | entry m/s | settle (ms) | bound (ms) | profile at v | lag (info) | total / of |
    |---|---|---|---|---|---|---|---|
    | s6-e2-c | encore | 2.04 | 1850.60 | 4421.33 | 1647.71 | 202.89 | 2472.10 / 5165.67 |
    | s6-e2-d | encore | 2.04 | 1861.66 | 4421.33 | 1647.59 | 214.07 | 2418.75 / 5165.67 |
    | s6-e4-c | encore | 4.14 | 2670.41 | 4421.33 | 2488.24 | 182.17 | 3198.33 / 5165.67 |
    | s6-e4-d | encore | 4.14 | 2681.15 | 4421.33 | 2487.59 | 193.56 | 3232.07 / 5165.67 |
    | s6-e6-c | encore | 5.96 | 3512.82 | 4421.33 | 3217.87 | 294.96 | 4055.43 / 5165.67 |
    | s6-e6-d | encore | 5.96 | 3532.13 | 4421.33 | 3216.86 | 315.27 | 4063.05 / 5165.67 |
    | s6-e8-c | encore | 8.30 | 4334.64 | 4421.33 | 4153.49 | 181.15 | 4883.11 / 5165.67 |
    | s6-e8-d | encore | 8.30 | 4351.46 | 4421.33 | 4153.69 | 197.77 | 4955.85 / 5165.67 |
    | s6-b2-c | b | 2.00 | 3832.61 | 10939.67 | 3665.18 | 167.44 | 13974.71 / 21393.67 |
    | s6-b2-d | b | 2.00 | 3932.18 | 10939.67 | 3665.45 | 266.74 | 14050.00 / 21393.67 |
    | s6-b4-c | b | 4.17 | 6620.46 | 10939.67 | 5837.13 | 783.33 | 16773.30 / 21393.67 |
    | s6-b4-d | b | 4.17 | 6645.45 | 10939.67 | 5838.98 | 806.48 | 16717.66 / 21393.67 |
    | s6-b6-c | b | 6.00 | 8457.54 | 10939.67 | 7664.36 | 793.18 | 18546.54 / 21393.67 |
    | s6-b6-d | b | 6.00 | 8420.24 | 10939.67 | 7664.37 | 755.88 | 18474.67 / 21393.67 |
    | s6-b8-c | b | 8.30 | 10536.75 | 10939.67 | 9971.07 | 565.69 | 20699.84 / 21393.67 |
    | s6-b8-d | b | 8.30 | 10662.85 | 10939.67 | 9970.92 | 691.94 | 20774.52 / 21393.67 |

    settle(v) + lag(v) stays under settle + response at 8.33 m/s at every
    speed: emergency 1850.60-4351.46 of 4421.33, comfortable
    3832.61-10662.85 of 10939.67 (the comfortable lag includes the planner
    hop). The emergency lag at 4.14 m/s is now 182-194 ms (441-464 on the
    image before the publishers were express: part of that lag was the tx
    batch).
  - Gap 2, the emergency response at 8.3 m/s (done, island main 8316e32).
    s6-in4 read 4422.87 of 4421.33 with the clocks aligned on the wrong
    publish (S7, gap 3); re-merged it reads 4416.64. The response was
    re-sized from the final image's stops at 8.30 m/s anyway: it was 256 =
    213.11 x 1.2 from 3 runs before the direct path's publishers were
    express. 16 stops on image 2b8a7985, merged with 5aa6226 (lag = settle -
    profile at the speed at the first emergency command; 2b8a7985 and
    74451cc2 differ only in the contract hash string):

    | run | path | entry m/s | settle (ms) | profile at v | lag | handover handler / operator (ms) |
    |---|---|---|---|---|---|---|
    | s6-e8-c | direct (hpc_loss) | 8.30 | 4334.64 | 4153.49 | 181.15 | - |
    | s6-e8-d | direct (hpc_loss) | 8.30 | 4351.46 | 4153.69 | 197.77 | - |
    | s6-g8e1 | direct (hpc_loss) | 8.30 | 4337.27 | 4153.20 | 184.07 | - |
    | s6-g8e2 | direct (hpc_loss) | 8.30 | 4340.76 | 4153.69 | 187.07 | - |
    | s6-g8e3 | direct (hpc_loss) | 8.30 | 4340.77 | 4153.30 | 187.47 | - |
    | s6-g8e4 | direct (hpc_loss) | 8.30 | 4352.98 | 4153.52 | 199.46 | - |
    | s6-g8e5 | direct (hpc_loss) | 8.30 | 4350.13 | 4154.09 | 196.04 | - |
    | s6-in3 | escalation (odd_exit, comfortable inert) | 8.30 | 4400.38 | 4153.43 | 246.95 | 6.11 / 35.53 |
    | s6-in4 | escalation | 8.30 | 4416.64 | 4153.44 | 263.20 | 6.99 / 36.04 |
    | s6-in5 | escalation | 8.30 | 4403.56 | 4153.46 | 250.10 | 6.00 / 35.53 |
    | s6-in6 | escalation | 8.30 | 4400.16 | 4153.45 | 246.71 | 5.83 / 35.54 |
    | s6-g8i1 | escalation | 8.30 | 4413.40 | 4153.48 | 259.92 | 4.87 / 34.54 |
    | s6-g8i2 | escalation | 8.30 | 4395.02 | 4153.46 | 241.56 | 6.35 / 35.56 |
    | s6-g8i3 | escalation | 8.30 | 4393.71 | 4153.44 | 240.27 | 6.63 / 36.50 |
    | s6-g8i4 | escalation | 8.30 | 4407.46 | 4153.45 | 254.01 | 5.40 / 31.52 |
    | s6-g8i5 | escalation | 8.30 | 4418.77 | 4153.43 | 265.34 | 7.34 / 33.99 |

    Direct 181.15-199.46 ms (n 7), escalation 240.27-265.34 ms (n 9). By
    the contract's rule, 265.34 x 1.2 = 318.41 -> 319: settle 4484.33,
    hpc_loss 5228.67 of 10,000 (overrun row 5379.67), the route-2 overrun
    case 26224.33 of 30,000. Every run's settle is under 4484.33. The
    direct encores' totals (last sample -> standstill) 4900.28-4958.21.
    Excluded: s6-e8-1 and s6-e8-a (lag 206.16, 208.06; image 6eb8371f) and
    s6-in1, s6-in2 (267.84, 268.60; 489fdf39, before the express
    publishers).

    The escalation is not a different command. Its first command seeds from
    the last control command (acceleration -0.03 against -0.066 in the
    encore; the inert comfortable stop leaves the host's command at 8.3
    m/s, nothing of the comfortable state in it), and the ramps match: the
    host receives acceleration -2.5 at 1647-1660 ms and velocity 0 at
    4158-4172 ms after the first command on both paths, no step back in
    either. The gate forwards the first decelerating command 7-30 ms
    (direct) and 34-43 ms (escalation) after it, and the speed first drops
    326-335 ms against 350-366 ms. The rest is the vehicle: the encore
    brakes ~63 m along the 315 m straight, the escalation ~251 m (11 s more
    at 8.3 m/s; distance from the integrated speed). The mean deceleration
    1.8-3.8 s after the command is 2.506-2.512 m/s2 in the encores and
    2.436-2.467 in the escalations, against the 2.5 commanded. The likely
    cause is the road: the planning simulator has
    `enable_road_slope_simulation: true`, and the lanelet map's elevation
    (node `ele`, averaged per 20 m along the straight) is flat around 63 m
    and falls about 0.2 m over the 80 m before 280 m (~0.25 %, ~0.025 m/s2;
    same sign, a little under the 0.04-0.07 seen). Not isolated: no run
    braked at both places on one path. The response is the vehicle's,
    wherever on the route it brakes, so the escalations' sample sizes it.
  - Before this unit's decisions, the draft's image (d2b696c, pin
    573490978d) showed the timer route catching the overrun of one long
    callback (p11-s6-b1: route 1 fired at its due +0.033 ms; the executor
    recorded only `route-latency-runtime` 327 of 149 ms, the hook was not
    called) and route 0 catching the encore's (p11-s6-ov1).

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
- Status (2026-10-16): done on branch `phase11-s6` with S6's direct
  emergency path: hpc_loss overrun and stall, and odd_exit with a
  comfortable stop that does not decelerate, each in its safe state within
  the FTTI, every act PASS. Image 2b8a7985 (pin 7874373b01); run
  directories /mnt/mx500/aeon/worktrees/p11-s6/build/timeline/s6-*.
  Detection delay from the contract, tick 1 + switch 1:

  | run | act, injected | entry m/s | due -> verdict / output / emergency command (ms) | command -> standstill / settle (ms) | total / overrun case (ms) | handover handler / operator (ms) | SUMMARY |
  |---|---|---|---|---|---|---|---|
  | s6-ov4 | encore, 300 ms | 4.15 | 0.03 / 0.05 / 0.70 | 2789.04 / 4421.33 | 3438.64 / 5316.67 | 235.23 / 232.70 | PASS, supervised 7/7 |
  | s6-ov5 | encore, 300 ms | 4.15 | 0.03 / 0.04 / 0.57 | 2775.74 / 4421.33 | 3424.52 / 5316.67 | 238.82 / 235.84 | PASS, supervised 7/7 |
  | s6-st4 | encore, stall | 4.16 | 0.03 / 0.04 / 0.57 | 2777.27 / 4421.33 | 3426.19 / 5316.67 | - / - | PASS, supervised 7/7 |
  | s6-st5 | encore, stall | 4.16 | 0.03 / 0.04 / 0.57 | 2795.07 / 4421.33 | 3444.64 / 5316.67 | - / - | PASS, supervised 7/7 |
  | s6-ov6 | encore, 300 ms | 4.15 | 0.03 / 0.05 / 0.58 | 2776.24 / 4484.33 | 3425.37 / 5379.67 | 230.60 / 227.88 | PASS, supervised 7/7 |
  | s6-ov7 | encore, 300 ms | 4.15 | 0.03 / 0.04 / 0.57 | 2786.55 / 4484.33 | 3435.84 / 5379.67 | 224.47 / 221.64 | PASS, supervised 7/7 |
  | s6-st6 | encore, stall | 4.16 | 0.03 / 0.05 / 0.70 | 2787.00 / 4484.33 | 3436.70 / 5379.67 | - / - | PASS, supervised 7/7 |
  | s6-st7 | encore, stall | 4.16 | 0.03 / 0.04 / 0.57 | 2801.28 / 4484.33 | 3450.57 / 5379.67 | - / - | PASS, supervised 7/7 |
  | s6-in3 | b, comfortable inert | 8.30 | 0.03 / - / 0.57 (served -> due 11094.11 of 11096) | 4400.38 / 4421.33 | 25698.03 / 26161.33 | 6.11 / 35.53 | PASS, supervised 6/6 |
  | s6-in4 | b, comfortable inert | 8.30 | 0.03 / - / 0.56 (served -> due 11093.91 of 11096) | 4416.64 / 4421.33 | 25701.46 / 26161.33 | 6.99 / 36.04 | PASS, supervised 6/6 |
  | s6-in5 | b, comfortable inert | 8.30 | 0.03 / - / 0.57 (served -> due 11094.13 of 11096) | 4403.56 / 4421.33 | 25674.78 / 26161.33 | 6.00 / 35.53 | PASS, supervised 6/6 |
  | s6-in6 | b, comfortable inert | 8.30 | 0.03 / - / 0.57 (served -> due 11094.91 of 11096) | 4400.16 / 4421.33 | 25624.63 / 26161.33 | 5.83 / 35.54 | PASS, supervised 6/6 |

  The total is from the last sample (encore) or the ODD exit (b). In the
  stall the handler never runs again: mrm_state stays MRM_OPERATING /
  EMERGENCY_STOP from the direct path, which the encore act accepts at
  standstill (nothing on the island can report MRM_SUCCEEDED), and the
  vehicle stops on the island's command, which the host now receives at
  30 Hz (the earlier stall runs stopped on the host's own heartbeat
  timeout). The overrun case hands over once the spin thread resumes.

  Gap 3 (done, island main 5aa6226): the overrun's command -> standstill
  read ~220 ms longer than the stall's (3010-3015 against 2790-2800) because
  `merge.py` aligned the two clocks on the wrong publish. The host's first
  MRM_OPERATING after an overrun is the direct path's (slot 0, published
  from the reaction thread with no `PUB_MRM_HANDLER_MRM_STATE` marker); the
  handler publishes its own only when the spin thread resumes, ~231 ms
  later. Anchor 1 paired the host's receipt with the handler's marker, and
  as the smallest publish/receipt pair it set the offset: s6-ov4/ov5 were
  aligned 220.78 / 223.69 ms off (anchor 2 disagreed by exactly that), so
  the host's standstill landed that much later against the island's
  command. A stall publishes no handler mrm_state and aligned on anchor 2.
  The handback itself is clean, from the host's own samples (no
  alignment): command -> standstill 2685.33 / 2671.46 ms (overrun) against
  2681.82 / 2692.86 (stall); the operator's first own command follows the
  direct path's last 16 ms later, one step further down the same ramp
  (-0.289 -> -0.304 m/s2, the jerk unchanged), with no gap, repeat or
  restart. The fix counts the direct path's slot-0 calls as mrm_state
  publishes in anchor 1 and the refinement (selftest in `tlcommon.py`);
  every run's anchors now disagree by 4.6-23 ms. The escalations moved by
  the handler's ~6 ms handover (s6-in4 4422.87 -> 4416.64), which also
  closes S6's 1.54 ms overrun. Rows above: s6-ov4/5, st4/5 and in3-6
  re-merged from their traces (copies in
  /mnt/mx500/aeon/worktrees/p11-gap-re; the run directories keep the
  original merge); s6-ov6/7, st6/7 new on image 74451cc2 (2b8a7985
  with the contract hash of 8316e32), judged against the 319 ms response.
  Route 2's due
  is timed from the operator's operate path, where the settle starts: the
  handler arms it after sending the request, up to ~1.4 ms after its call
  marker (s6-in6 read 11096.42 from the call). The output
  latched 648.26-649.04 ms after the last sample in the encores, within
  the FTTI. The tools and the first runs (images 5fa405ff, 71e81adc), the
  output an LED only: `island_debug_fault_overrun_ms`
  (`CONFIG_ISLAND_DEBUG_OVERRUN`): the next tick that runs call_mrm
  busy-waits N ms right after its ENTRY, before the reaction, or forever
  (0xffffffff). `RB_OVERRUN=<ms>|stall` on the encore: once the vehicle
  drives the act re-arms the trace window (`readout.py --rearm-only`) and
  writes the hook (`violations.py fault-overrun`), then the HPC loss;
  p11-ov1's window, opened at boot, was full before the act. Markers
  `SUPERVISOR_DEADLINE`, `_SAFE_STATE`, `_INJECT`, appended (no id moves).
  `analysis.py` rows on an encore where the supervisor acted: due ->
  verdict and due -> output within tick + switch (`supervision:` of the
  contract, else 1 + 1 ms); output -> standstill within the emergency
  settle; last sample -> standstill within the rung's total + the
  detection delay and the FTTI; last sample -> output within the FTTI. The
  due is the verdict's own (its arg; the trace clock is the uptime), the
  take-based one kept beside it. The unsupervised rows of an injected act
  carry no verdict, a stall's standstill, total and rung neither;
  `run_summary.py` counts them apart and prints `supervised k/n` and the
  supervisor record. The `HPC alive` row is taken from the island's takes
  (`island takes`), the host probe only without a trace. `merge.py` aligns
  a stalled island (no take after the loss) on its last take. Selftests in
  `tlcommon.py selftest`.
  Runs (the planning simulator at Autoware's default `max_vel`, 4.17-4.25
  m/s; run directories
  /mnt/mx500/aeon/worktrees/p11-island/build/timeline/p11-*; images as in
  S4's status: 5fa405ff for ov1, ov2, st1; the pin b7e63a5b44's code for
  ov3 (built with #2267 applied before it merged), ov4, st2 (71e81adc)):

  | run | injected | due -> verdict / output (ms) | output cause | last sample -> output (ms) | output -> standstill / settle (ms) | total / overrun total (ms) | SUMMARY |
  |---|---|---|---|---|---|---|---|
  | p11-ov2 | 300 ms | 0.03 / 0.04 | route | 648.47 | 2940.86 / 4421.33 | 3589.34 / 5167.67 | PASS, supervised 6/6 |
  | p11-ov3 | 300 ms | 0.03 / 0.04 | route | 648.59 | 2925.69 / 4421.33 | 3574.28 / 5167.67 | PASS, supervised 6/6 |
  | p11-ov4 | 300 ms | 0.03 / 0.04 | route | 648.95 | 2895.30 / 4421.33 | 3544.26 / 5167.67 | PASS, supervised 6/6 |
  | p11-st1 | stall | 0.03 / 0.04 | route | 648.25 | - (no island braking) | - | FAIL (act), supervised 3/3 |
  | p11-st2 | stall | 0.03 / 0.05 | route | 648.27 | - (no island braking) | - | FAIL (act), supervised 3/3 |
  | p11-ov1 | 300 ms | 0.024 / 0.036 (record) | route | - | - | - | trace full before the act |

  The overrun total is the rung's total plus the detection delay (5165.67
  + 2); the checker's overrun row on the S6 draft reads 5316.67, because it
  also charges the island.emergency_stop route as the fallback's.

  p11-ov2: the reaction tick came 850.86 ms after the last sample (the
  300 ms overrun), the emergency operator braked 1.86 ms later, standstill
  3589.34 ms after the last sample, inside 10,000. p11-st1: the island's
  ladder never ran (MRM state stays NORMAL, no emergency command); the
  output was driven 648.25 ms after the last sample and is the island's
  safe state here, which the simulator does not see: the act reads FAIL.
  The simulated speed stepped from 4.17 to 0.0 m/s about 1.1 s after the
  fault with no island output, the host's own doing, not judged. In both
  stall cases SWT0 did not fire: the route latched first and the reaction
  thread fed SWT0 from then on (p11-swt1 is SWT0's own check).

## Order

S1 first (the keys). S2 and S3 in parallel after it. S5 any time after S1.
S4 after S3 (it shares the due time). S6 after the rlm and play_launch
releases carrying S1, S2 and S5, and the nano-ros pin carrying S3. S7 last,
on the board. One agent owns the board.

## Follow-ups

- Derive an executor supervision's tick from its spin period in the
  checker (S6 decision 3, option B): `supervision.tick` is one term per
  contract, right for the timer mechanism only; an `executor` supervision
  should be charged the spin period plus the longest callback on that
  executor, read from the contract, not stated by hand.
- Lower a supervised settle in the checker: a `supervise:` on a settle (or
  its response) that the platform checks to standstill, with the overrun
  row charging the whole settle (profile + response), not the response
  alone. Until then the island's route 2 is stated in a contract comment.

## Not in this phase

- Analysed bounds for execution time and transport. `source: analysed`
  takes them when a user has them; a platform package (play_launch phase
  91's profiles) is where a link's or a processor's numbers would live.
- A runtime check of a host-to-island hop: needs a shared clock (phase 10).
- The vehicle-side safe input below the emergency stop.
- Thread priorities from the contract: the island has one spin thread;
  S4's reaction thread is set above it by construction.
