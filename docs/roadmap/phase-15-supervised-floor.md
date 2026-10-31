# Phase 15 - the emergency-stop floor is supervised

**Goal:** the island checks that its last rung, the emergency stop, actually
brings the vehicle to standstill, and reacts when it does not. Today nothing
watches it: `mrm_handler` calls `/system/mrm/emergency_stop/operate` async
with no timeout, and phase 11's table records the floor's reaction as "none
on the island (it is the floor)". play_launch 0.21.0 (rlm v0.2.6, phase 95)
reports this as `warning[call-unbounded-floor]` on `hazards.hpc_loss` and
`hazards.odd_exit`. This phase closes the gap rather than acknowledging it.

**Status (2026-10-31): done (S1-S6).** Decided: supervise the floor
(option 1), not acknowledge it. S4 proved it on the board with the
floor's three failures injected; S6 closed the gap S4 left open (the
operator stalling after the handover) and stopped route 3 from calling a
vehicle-side fault before the island's own braking command had run a
settle.

- S1: `play_launch check` (0.21.0, rlm v0.2.6) on the island contract went
  from 0 errors / 12 warnings (2 `call-unbounded-floor`) to 0 errors / 9
  warnings, no `call-unbounded-floor`; the emergency response (319) is now
  supervised, so its `measured-unsupervised` is gone too. The reaction is
  `island.floor_override` (trigger `/control/command/control_cmd`, output
  `/system/emergency/control_cmd`): the walk reaches the operator's
  `on_timer` safe state through its state input and charges its tick
  (33.33 + 6), which the direct path does not wait for. A scope path with
  its own `safe_state` and the trigger `/localization/kinematic_state` was
  refused (`supervised-fit`: "reaches none of the hazard's safe states").
  The overrun rows:

  | hazard | before | settle | observe | detect | route | settle | total | FTTI | slack |
  |---|---|---|---|---|---|---|---|---|---|
  | hpc_loss | 744.33 | 4484.33 | 136 | 2 | 39.33 | 4484.33 | 9890.33 | 10000 | 109.67 |
  | odd_exit | 10493.33 | 4484.33 | 136 | 2 | 39.33 | 4484.33 | 19639.33 | 30000 | 10360.67 |

  Two faults on odd_exit (S4, resolved). Composed naively, a comfortable
  stop that overruns AND a floor that then overruns is 26204.33 + 136 + 2
  + 39.33 + 4484.33 = 30866.00 ms, over odd_exit's 30 s. That chain does
  not exist on the island: route 2's miss latches the output and the
  direct path brakes from that due (its settle is inside the comfortable
  overrun row, 26204.33). The handler, reading the latch, calls the
  emergency stop, which arms route 3 AFTER the latch, so route 3's due
  finds the output latched and a miss is `island_judge_floor`'s
  VEHICLE_FAULT: no second latch, no re-arm, no second direct-path settle
  (host test `two_faults`, tests/supervisor/test_judge.c). A common-cause
  stall of the mrm tier (both operators on one executor thread) ends the
  same way: the direct path runs on the supervisor's thread. The worst
  odd_exit chain is 26204.33 of 30000 ms (slack 3795.67); past it is a
  vehicle that does not decelerate under a braking command, which no
  island action fixes (the vehicle-side fault). An operator stalling
  after it took the command over is answered by the direct path's resume
  (S6), charged once: hpc_loss 9890.33 + 100 = 9990.33 of 10000 ms,
  odd_exit 19739.33, the two-fault chain 26304.33 of 30000.
- S2: route 3 (`island_supervisor.c`, `CONFIG_ISLAND_SUPERVISOR_
  EMERGENCY_MS` 4485), armed in `requestMrmBehavior` before the send.
  Missed before any latch: latch, the direct path, re-armed once for the
  direct path's settle. Missed with the output latched: the vehicle-side
  fault (`vehicle_fault` in the record, `SUPERVISOR_VEHICLE_FAULT` in the
  trace), the command kept. mrm_state is not set to MRM_FAILED: how
  Autoware's gate treats MRM_FAILED is not checked, and the braking
  command has to keep reaching the vehicle. The emergency operator,
  latched and not OPERATING, stops its pass-through publish so the direct
  path is the only command on the topic. The early response check is not
  built: `supervise:` covers the whole settle only, so the checker cannot
  model a deceleration check at the response bound (follow-up, rlm).
- S3: `just supervisor-test` (host verdicts: met, missed, stale sample,
  the floor's sequences; the record decoder against its layout, and with
  `--elf` against the image: 756 B; 760 B since S4's `floor_unseen`); native, native_sim and board builds
  pass; `priority-check` agrees.
- S5: phase 11's table row, the contract comments, the readout
  (`violations.py supervisor`: route 3, `floor_*`, `vehicle_fault`,
  `stale_at_due`) and the marker table.

## What can fail on the floor, and what the island can do

| Failure | Seen today? | Island reaction after this phase |
|---|---|---|
| The operate request is lost or never answered (link, service, operator not up) | no | route 3 misses its due; the direct path brakes |
| The operator latched OPERATING but its timer does not run (its executor level starved or stalled) | no | same: the direct path publishes the braking command itself |
| The operator took the command over from the direct path, then its tick stops (S6) | no | the direct path resumes the slot after 3 of its periods (99 ms) and keeps it; route 3 judges the resumed command a whole settle from the resume |
| The operator runs, the vehicle does not decelerate (vehicle-side, actuator) | no | the island cannot brake harder than its command; it latches a persistent fault, keeps commanding, hazard lights, and reports it (readout, status) |

The direct path exists since phase 11 (island_supervisor.c, decision 2): once
the output is latched the reaction thread calls each registered direct
function, which publishes the emergency command at the operator's rate until
that component's executor path reports the emergency running. Route 3 reuses
it; nothing below the floor is invented.

## Design

- **Route 3, the floor's standstill.** Armed when the handler calls the
  emergency stop (the call site in mrm_handler_core.cpp, as route 2 is armed
  at the comfortable call). Due = the floor's settle at the entry speed
  (profile + response: 4484.33 ms at 8.33 m/s) + the standstill observation
  (CONFIG_ISLAND_SUPERVISOR_STANDSTILL_OBSERVE_MS, 136). At the due the thread
  judges standstill the way route 2 does (fresh kinematic_state, below
  1 mm/s). Met: disarm. Missed: latch, direct path, fault record.
- **An early check at the response bound (optional, decided in S2).** No
  deceleration in kinematic_state by call + route + response (319) +
  observation means the command never took effect; reacting there instead of
  at the full settle saves about 4 s. Phase 11 lists the same observable for
  the comfortable rung.
- **No SWT0 reset as the reaction.** A reset while braking drops the
  island's commands for its boot and INIT time (3 s); the watchdog stays the
  answer to a stalled island, not to a vehicle that does not stop.
- **The contract** states the floor's settle as supervised; the exact rlm
  form for a rung with no lower rung to enter is S1. The checker's overrun
  sum (supervised-fit) must still fit the 30 s FTTI with the floor's
  observation and detection added.

## Units

- S1. Contract (form confirmed with play_launch, rlm
  `docs/format-reference.md`, rows `<settle>.supervise`):
  - `supervise:` takes exactly one of `reaction:` / `enters:`, plus
    `mechanism:`; `observes:` is settle-only. The floor has no rung to
    enter, so it names a `reaction:`: a scope path of the manifest for the
    supervisor's direct path, e.g. `sys.floor_override` (trigger: what route
    3's due fires on; output: the braking command it publishes).
  - The checker walks that reaction and requires it to reach one of the
    hazard's safe states. The direct path publishes `emergency_control_cmd`,
    which the operator's `on_timer` safe state emits; if the walk does not
    accept that, the scope path gets its own `safe_state: { emits, settle }`.
    The latch and the hazard lights are outside the arithmetic.
  - One supervised settle clears both `call-unbounded-floor` findings: both
    hazards' floors end at the operator's `on_timer` safe state.
  - The checker adds an `overrun` row per hazard (`supervised-fit`): before
    the floor + its settle deadline (settle + the `kinematic_state` period
    + its `max_transport`) + detection (`supervision.switch`) + the
    reaction's route + its settle, against each hazard's FTTI; an error if
    it exceeds. **Risk:** odd_exit reaches the floor only after the
    comfortable rung's overrun (26204.33 ms of 30 s today); adding the
    floor's settle deadline (~4620 ms) and a second settle (~4484 ms) is
    likely over 30 s. Run `check --explain` first. If it does not fit, the
    choices are a direct path that brakes harder (its own, shorter settle),
    an earlier floor check that the checker can model, or a recorded
    finding for the odd_exit row with the reason.
  - Bump the CI pin to play_launch 0.21.0 (and the nano-ros play_launch /
    rlm pins if the island's sync reads them). Done when `check` shows no
    `call-unbounded-floor` and both overrun rows fit.
- S2. Supervisor: route 3 (Kconfig `ISLAND_SUPERVISOR_EMERGENCY_MS`, derived
  like route 2's), the arm call in the handler, the fault record readable by
  name over SWD (`tools/board/violations.py supervisor`), selftests. Decide
  the early response check.
- S3. Native and Zephyr builds; the supervisor's host tests cover met,
  missed and stale-sample cases.
- S4. Board, from `rtss-work-2026-demo` against the pinned island:
  fault injection for each row of the table above (drop the operate
  request; stall the operator's level; hold the vehicle model's speed), each
  ending in a direct-path stop or a latched vehicle-side fault, and the
  normal encore acts still PASS. **Done (2026-10-31).**
  - Hooks: `CONFIG_ISLAND_DEBUG_FLOOR_INJECT`, set only by the snippet
    `island-floor-inject` (`just board-build-floor-inject`,
    build-board-floor-inject). The gate image has none of the words (nm:
    0 `island_debug_floor_*`). Words, written over SWD by
    `violations.py floor-inject drop|stall|stall-after|hold [mm/s]`:
    `island_debug_floor_drop` (the next emergency operate request is not
    sent, route 3 still armed), `island_debug_floor_stall` (1: from its
    next OPERATING tick the operator's timer does nothing, the level still
    spins, so SWT0 stays fed and route 3 is what sees it; 2: only after the
    handover), `island_debug_floor_hold_mm_s` (the speed the handler sees,
    its isStopped() and route 3's sample). `SUPERVISOR_INJECT` 0xfffffffc /
    fb / f9 / fa.
  - Acts (rtss-work-2026-demo `tools/eval/run-board.sh floor-drop|
    floor-stall|floor-hold`: the encore with the word written once the
    vehicle drives; judged by `tools/eval/floor_check.py` from the SWD
    record and by analysis.py's `floor:` rows from the trace). Planning
    simulator, entry speed 4.05-4.18 m/s (the contract's bound is 8.33).
    Each run below PASS on record and trace:

    | fault | n | call -> due | due -> verdict | due -> direct command | direct command -> standstill | last sample -> standstill (row 9890.33, FTTI 10000) |
    |---|---|---|---|---|---|---|
    | drop | 4 | 4620.87 | 0.03 | 0.58-0.60 | 2640.50-2671.63 | 7790.97-7867.45 |
    | stall | 4 | 4620.86-4620.87 | 0.03-0.04 | 0.59-0.71 | 2639.40-2662.80 | 7800.40-7873.60 |

    hold, n 4: route 3's verdict 0.03-0.04 ms after its due (call + 4620.34-
    4620.87), the direct path at +0.59-0.73, the direct path's own due
    4620.96-4620.97 after that verdict, its verdict and
    `SUPERVISOR_VEHICLE_FAULT` 0.04 ms after it at the held 1000 mm/s
    (`vehicle_fault` 1, `vehicle_fault_speed_mm_s` 1000); the emergency
    command kept (30 samples in the second after the fault) and the
    island's hazard lights command ENABLE. The operator itself stopped the
    vehicle 2724-2755 ms after the call, unseen by the island. Every run:
    latched by a route deadline, SWT0 0 fires, `floor_latches` 1,
    `stale_at_due` 0; drop and stall one route-3 verdict, no vehicle
    fault. All times ms. Runs s4f-fd1..3, s4f-fs1..3, s4f-fh1/3/4 (island
    529bfa7) and s4z-fd1, s4z-fs1, s4z-fh1 (6c07dad); s4f-fh2 is void (the
    act restored the HPC before route 3's due; fixed in scenario.py).
  - Regression, the gate image: encore x3, a, b PASS on 529bfa7 (s4g-*)
    and on 6c07dad (s4z-*): encore totals 3504.46-3532.75 (529bfa7) and 3463.12-3509.67 (6c07dad) of 5228.67 ms, every table 8/8; b 15926.82 and 15550.71 of 21393.67, 16/16; a 8/8; supervisor not driven, SWT0 0 fires, priorities AGREE.
  - Found on the board and fixed (529bfa7): at boot the handler's INIT
    failure raises an emergency stop, which armed route 3 before any
    kinematic_state (the planning simulator publishes none until its
    initial pose); when the stack took longer than the span to clear the
    fault, route 3 latched on a vehicle it had never seen and the act could
    not drive (s4-fh1). A due met before any kinematic_state since boot is
    now re-armed for another span (`floor_unseen`, the record's last word,
    760 B).
  - After the handover (found here, closed in S6): once the operator
    had taken the command over from the direct path
    (`island_supervisor_handover`), the direct path never resumed, so an
    operator that stalled after that left no braking command on the wire,
    and route 3, if armed, called it a vehicle-side fault. The S4
    `floor-stall-after` act (act b, comfortable stop inert) was
    inconclusive: the vehicle reached its goal before route 2's due
    (s4z-fsa1, s4z-fsa2).
- S5. Docs: phase 11's table row for the floor, the contract notes,
  tracing/readout names.
- S6. The direct path resumes after a handover; no vehicle-side fault
  before the island's braking command ran a settle. **Done (2026-10-31).**
  - Resume. After a slot's executor path took the emergency over, it
    reports every tick that publishes it (`island_supervisor_handover(slot,
    period_ms)`, now every tick, with the tick's period). Silent for
    `CONFIG_ISLAND_SUPERVISOR_RESUME_PERIODS` (3) of its periods, 99 ms for
    the emergency operator (33 ms) and 300 ms for the handler (100 ms), the
    direct path resumes the slot at once (`resumed[]`,
    `resume_uptime_ms[]`, `resume_silent_ms[]`, `SUPERVISOR_RESUME`). The
    reaction thread's latched wait is the earliest of the direct path's
    next publish, each watched slot's resume deadline and SWT0's feed, so
    the resume lands within the ms tick of the deadline. 3, not 2: one late
    tick (the executor's jitter, 6 ms measured on the operator's timer) is
    not a stall; above 3 the gap outgrows hpc_loss's slack.
  - No re-take. Once resumed, the direct path keeps the slot until the
    latch clears (reset). The executor path's later reports are counted
    (`alive_after_resume[]`) and answered 0 (handover's return,
    `island_supervisor_resumed`), and the component then publishes nothing
    on the slot's topics: the operator no command, the handler no mrm_state
    or hazard lights. A tick that missed three periods is not trusted with
    the next ones, two ramps on one topic would interleave, and the direct
    path publishes the same command (the operator's ramp in closed form
    from the latch), so nothing is lost by keeping it. The thread-safety
    argument holds: after the handover the spin thread writes only its
    slot's report (a 32-bit store) and reads `resumed`, written once by the
    reaction thread; a resume decided between a component's check and its
    publish costs one extra braking command from the same ramp, never a
    missing one.
  - Route 3 judges the island's own braking command. `brake_since` is the
    latch (the direct path's start; an operator continuing that ramp after
    a handover keeps it) or the operator slot's resume. At a route-3 due
    with the output latched and the vehicle moving, a vehicle-side fault
    needs the command to have run the span (4485 + 136 ms) from
    `brake_since`; younger, the due re-arms at `brake_since` + span
    (`floor_waits`, `SUPERVISOR_FLOOR_WAIT`), no latch, no fault. That is
    the stall of the mrm tier that SWT0 latches ~300 ms in, just before
    route 3's operator due, and the resume after a stall. A resume also
    arms route 3 for the resumed direct path's settle if nothing has it
    armed. `island_judge_floor(standstill, latched, braked_ms, span_ms)`
    replaces the stage argument; `island_judge_resume` is new. The
    two-fault chain is unchanged: route 3 is armed after the latch, so its
    due is at least a span after `brake_since`.
  - Host tests (`just supervisor-test`): latched but young -> WAIT, one ms
    short still WAIT, the re-armed due met or a fault; full settle and
    moving -> fault; the resume threshold for 33 and 100 ms periods and the
    ms wrap; the operator stalling after its handover -> resume, the old
    route-3 due deferred, the re-armed due met or a fault. The record grew
    760 -> 804 B (appended; `violations.py selftest --elf` against both
    images). Markers 38 `SUPERVISOR_RESUME` (slot << 28 | silent ms) and 39
    `SUPERVISOR_FLOOR_WAIT` (the new due), appended.
  - FTTI. The resume leaves a gap of at most 100 ms (99 + the 1 ms tick)
    in the braking command, once per latch; charged in full to the direct
    path's settle (the vehicle in fact keeps the last command):
    hpc_loss 9890.33 + 100 = 9990.33 of 10000 (slack 9.67), odd_exit
    19639.33 + 100 = 19739.33, the two-fault chain 26204.33 + 100 =
    26304.33 of 30000. The deferred route-3 verdict only dates the
    vehicle-side fault; it latches nothing and moves no safe state. The
    checker's rows are unchanged (the gap is outside its model; the
    contract comment carries the sum); `play_launch check` (0.21.0) still
    0 errors.
  - Board (rtss-work-2026-demo, island 169d126). `floor-stall-after` is now
    the encore with the handler's fault tick overrun 300 ms
    (`RB_FLOOR_OVERRUN_MS`): route 0 latches, the direct path brakes, the
    operator takes over on its first OPERATING tick and stalls on the next;
    judged PASS/FAIL by floor_check.py (record and trace). Planning
    simulator, entry speed 4.16-4.18 m/s; all times ms:

    | act | n | verdict | resume | standstill | vehicle_fault |
    |---|---|---|---|---|---|
    | stall-after | 4 | route 0 +0.027-0.029 after its due | 99 silent (record, every run), 65.87-65.95 after the stall marker; longest gap in the braking command at the host 93.94-101.67 | 2212.84-2416.79 after the resume; last sample -> standstill 3206.97-3376.30 (row 9890.33) | 0; route 3 no verdict |
    | stall | 4 | route 3 +0.03-0.04 | none (the operator never took over) | direct command -> standstill 2633.45-2660.83; last sample -> standstill 7755.35-7880.27 | 0 |
    | drop | 4 | route 3 +0.03-0.04 | none | direct command -> standstill 2645.97-2668.12; last sample -> standstill 7798.12-7851.90 | 0 |
    | hold | 4 | route 3 +0.03-0.04; the direct path's due 4620.96-4620.97 later, verdict +0.03-0.04 | none (the operator alive after its takeover) | the operator stopped the vehicle 2729.71-2759.05 after the call, unseen | 1 at the held 1000 mm/s |

    Every run PASS on record and trace, SWT0 0 fires, `floor_waits` 0
    (no due found the braking command young on these acts; the deferred
    verdict is covered by the host tests), `stale_at_due` 0. Runs s6-fsa1..4,
    s6-fs1..4, s6-fd1..4, s6-fh1..4 (floor-inject image).
  - Regression, the gate image (nm: 0 `island_debug_floor_*`): encore x3,
    a, b PASS (s6g-e1..3, s6g-a1, s6g-b1): encore totals 3489.21-3557.45
    of 5228.67 ms, every table 8/8; b 15300.63 of 21393.67, 16/16; a 8/8;
    supervisor not driven, SWT0 0 fires, priorities AGREE.

## Acceptance

- `play_launch check` (0.21.0): 0 errors, no `call-unbounded-floor`.
- On the board, each injected floor failure is detected by its due and
  answered as the table says; the existing acts PASS unchanged.
- S6: an operator stalling after its takeover is answered by the resume,
  ending at standstill with no vehicle-side fault (floor-stall-after PASS).
