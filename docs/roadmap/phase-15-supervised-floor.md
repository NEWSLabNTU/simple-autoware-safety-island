# Phase 15 - the emergency-stop floor is supervised

**Goal:** the island checks that its last rung, the emergency stop, actually
brings the vehicle to standstill, and reacts when it does not. Today nothing
watches it: `mrm_handler` calls `/system/mrm/emergency_stop/operate` async
with no timeout, and phase 11's table records the floor's reaction as "none
on the island (it is the floor)". play_launch 0.21.0 (rlm v0.2.6, phase 95)
reports this as `warning[call-unbounded-floor]` on `hazards.hpc_loss` and
`hazards.odd_exit`. This phase closes the gap rather than acknowledging it.

**Status (2026-10-31): S1-S3 and S5 done; S4 (board) open.** Decided:
supervise the floor (option 1), not acknowledge it.

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

  The checker takes one overrun at a time. A comfortable stop that
  overruns AND an emergency stop that then overruns (two faults) is
  26204.33 + 136 + 2 + 39.33 + 4484.33 = 30866.00 ms, over odd_exit's 30 s;
  it is not a row of the checker.
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
  `--elf` against the image: 756 B); native, native_sim and board builds
  pass; `priority-check` agrees.
- S5: phase 11's table row, the contract comments, the readout
  (`violations.py supervisor`: route 3, `floor_*`, `vehicle_fault`,
  `stale_at_due`) and the marker table.

## What can fail on the floor, and what the island can do

| Failure | Seen today? | Island reaction after this phase |
|---|---|---|
| The operate request is lost or never answered (link, service, operator not up) | no | route 3 misses its due; the direct path brakes |
| The operator latched OPERATING but its timer does not run (its executor level starved or stalled) | no | same: the direct path publishes the braking command itself |
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
  normal encore acts still PASS.
- S5. Docs: phase 11's table row for the floor, the contract notes,
  tracing/readout names.

## Acceptance

- `play_launch check` (0.21.0): 0 errors, no `call-unbounded-floor`.
- On the board, each injected floor failure is detected by its due and
  answered as the table says; the existing acts PASS unchanged.
