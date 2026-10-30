# Phase 15 - the emergency-stop floor is supervised

**Goal:** the island checks that its last rung, the emergency stop, actually
brings the vehicle to standstill, and reacts when it does not. Today nothing
watches it: `mrm_handler` calls `/system/mrm/emergency_stop/operate` async
with no timeout, and phase 11's table records the floor's reaction as "none
on the island (it is the floor)". play_launch 0.21.0 (rlm v0.2.6, phase 95)
reports this as `warning[call-unbounded-floor]` on `hazards.hpc_loss` and
`hazards.odd_exit`. This phase closes the gap rather than acknowledging it.

**Status (2026-10-31): planned.** Decided: supervise the floor (option 1),
not acknowledge it.

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

- S1. Contract: the floor's `safe_state.settle` gets its `supervise:` in the
  form rlm v0.2.6 accepts; bump the CI pin to play_launch 0.21.0 (and the
  nano-ros play_launch/rlm pins if the island's sync reads them); `check`
  shows no `call-unbounded-floor` finding and the FTTI sums still pass.
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
