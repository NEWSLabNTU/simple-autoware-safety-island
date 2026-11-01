# Phase 16 - the floor's response check

**Goal:** a floor whose braking command never took effect is caught at the
response bound, not at the end of the whole settle. Phase 15 supervised the
emergency stop to standstill (route 3, call + 4485 + 136 ms): the only
question it asks is "stopped by the settle's end?", so a lost operate
request, a stalled operator or a vehicle that does not decelerate was seen
4621 ms after the call, and a vehicle-side fault 9242 ms after it. Phase 15
S2 left the earlier check open because `supervise:` covered the whole
settle only and the checker could not model a check at the response bound.
This phase is that follow-up (named phase 16 rather than phase 15 S8: the
evaluation repo used "S8" for an image bump).

**Status (2026-11-02): done.** The contract language, the checker, the
supervisor and the board acts.

## The contract form (rlm v0.3.1, play_launch 0.22.0)

A supervised settle takes a response check beside its reaction, mechanism
and observation:

```yaml
settle:
  decel: $(param target_acceleration) m/s^2
  jerk: $(param target_jerk) m/s^3
  response: { duration: 319ms, source: { measured: { max: 265.34ms, n: 16, margin: 0.2 } } }
  supervise:
    reaction: island.floor_override
    mechanism: timer
    observes: mrm_handler/kinematic_state
    early: { within: 1319ms, drop: 0.25 m/s }
```

- Semantics: the platform arms a second, earlier due over the same settle,
  command + `within` + the observation (the same `observes` delay as the
  settle's own due, 136 ms here), and judges it against the speed it saw
  when it armed. Met when the vehicle has shed at least `drop` or is at
  standstill; a miss starts the same reaction as the settle's miss. It is
  the settle's question asked weaker and earlier, so it lives inside the
  settle's `supervise:` and names no reaction of its own.
- `early:` is refused on any budget but a settle's (`early` names the
  settle's response); `within` and `drop` are required, with units.
- The checker (`supervised-early`): an error when `within` lies inside the
  settle's `response` (the plant is not required to slow yet, so a nominal
  stop would be a miss) or at or past the settle's end (it detects nothing
  earlier); an error when `drop` exceeds the speed the nominal profile sheds
  by `within`. That speed is the settle's extension's own derivation,
  `derive settle.speed_lost` (new rlx derive target, a Velocity, with the
  core input `elapsed`), which the bundled `vehicle.braking` 1.1.0 states
  from the same profile as `settle.duration`: nothing during the response,
  then the jerk ramp, then the held deceleration. A written settle derives
  no shed speed: `drop` is unchecked (a warning).
- The FTTI rows: the response check gets its own overrun row,
  `<rung> (<settle>.supervise.early)`: the time before the settle +
  `within` + the observation + the detection + the reaction's route and
  settle. The settle's own row stays: a vehicle that slows and then fails
  to stop is still seen only at the settle's end.

The island's numbers. The emergency profile is target_acceleration -2.5,
target_jerk -1.5, response 319: 1 s into the jerk ramp (`within` 1319) the
nominal stop has shed 0.75 m/s (`supervised-early`: "fits: the nominal
profile sheds 0.7500 m/s by then (vehicle.braking 1.1.0), 0.5000 m/s above
`drop`"). `drop` is a third of that: the other 0.5 m/s cover a vehicle still
accelerating at up to 1 m/s^2 through the response (0.32 m/s) and a
reference sample one observation (136 ms) old. A check at the response
bound itself (`within` 319) would be refused: the profile sheds nothing by
then.

## The FTTI rows (`play_launch check --explain`, 0.22.0)

`check`: 0 errors, 6 warnings, 2 acknowledged, before and after. The rows
of the floor, before (phase 15) and after:

| hazard | row | before | settle/check | observe | detect | route | settle | total | FTTI | slack |
|---|---|---|---|---|---|---|---|---|---|---|
| hpc_loss | the settle (phase 15, unchanged) | 744.33 | 4484.33 | 136 | 2 | 39.33 | 4484.33 | 9890.33 | 10000 | 109.67 |
| hpc_loss | the response check (new) | 744.33 | 1319 | 136 | 2 | 39.33 | 4484.33 | 6725.00 | 10000 | 3275.00 |
| odd_exit | the settle (unchanged) | 10493.33 | 4484.33 | 136 | 2 | 39.33 | 4484.33 | 19639.33 | 30000 | 10360.67 |
| odd_exit | the response check (new) | 10493.33 | 1319 | 136 | 2 | 39.33 | 4484.33 | 16474.00 | 30000 | 13526.00 |

With S6's resume gap charged once (outside the checker, as before):
hpc_loss 9990.33 (unchanged, the worst row) and 6825.00 for a vehicle that
does not respond; the two-fault odd_exit chain 26304.33 (unchanged: route 4
judges the island's own braking command from the latch, as route 3 does).
No row grew, so no row exceeds its FTTI: the response check only adds a
shorter path to the same reaction. The rows that a vehicle which never
decelerates now ends on are the response check's: 6725.00 instead of
9890.33 on hpc_loss.

## The supervisor (route 4)

- Route 4 (`island_supervisor.c`, `ISLAND_SUPERVISOR_ROUTE_EMERGENCY_RESPONSE`)
  is armed by the supervisor itself whenever route 3 starts a settle: the
  handler's emergency call (`island_supervisor_arm(route 3)`), route 3's or
  route 4's latch (the direct path's settle) and the direct path's resume
  (S6). Due = start + `CONFIG_ISLAND_SUPERVISOR_EMERGENCY_RESPONSE_MS` (1319)
  + `CONFIG_ISLAND_SUPERVISOR_STANDSTILL_OBSERVE_MS` (136), against the |v|
  noted then. A start with no fresh kinematic_state (at boot, a link gap)
  leaves route 4 unarmed (`response_unref`): there is nothing to judge a drop
  against, and route 3 alone judges. The handler never arms or clears it;
  route 3's done clears it.
- The verdict (`island_supervisor_judge.h`): `island_judge_responded`
  (standstill now, or a fresh sample that has shed
  `CONFIG_ISLAND_SUPERVISOR_EMERGENCY_DROP_MM_S` (250) from the reference)
  feeds route 3's own `island_judge_floor` with the response span (1455) in
  place of the settle's: met; not latched -> LATCH; latched and the island's
  own braking command older than the span -> VEHICLE_FAULT; younger ->
  WAIT (re-armed at `brake_since` + the span against the |v| noted at
  `brake_since`).
- The reaction to an early "not responding" verdict is route 3's, earlier:
  - nothing latched yet: the command never took effect on the island's
    side (the operate request lost, the operator's tick not running), so
    the output latches and the direct path brakes (`response_latches`);
    route 3 is re-armed for the direct path's settle and route 4 for its
    response check, as route 3's own miss does;
  - latched, the island's braking command has run the response span and
    the vehicle still has not slowed: the vehicle-side fault, the same
    latched fault as route 3's (`vehicle_fault`, now with
    `vehicle_fault_route` 3 or 4), which the handler reports as MRM_FAILED /
    EMERGENCY_STOP (phase 15 S7) with the braking command and the hazard
    lights kept. Route 3 is disarmed then: the fault is final.
  Why the same path: the early verdict answers the same question with less
  evidence, and both answers the island has are already the right ones. A
  floor that never took effect is what the direct path is for; a vehicle
  that does not slow under the island's own command is past anything the
  island can do but report it, and reporting it 2.9 s after the call
  instead of 9.2 s is the gain. A second reaction (an SWT0 reset, a
  harder command) would be wrong for the reasons phase 15 gives.
- Why `drop` and not a deceleration: kinematic_state carries the twist,
  not an acceleration; the island differentiates nothing. A shed speed
  against a reference taken at the start needs one fresh sample at each
  end.
- Record (868 B, appended after `brake_since_ms`, offsets hold):
  `route_response` (a route's seven words), `response_within_ms`,
  `response_drop_mm_s`, `response_ref_mm_s`, `response_met`,
  `response_latches`, `response_waits`, `response_unref`,
  `response_last_shed_mm_s`, `vehicle_fault_route`.
  `violations.py supervisor` reports them; `selftest --elf` checks the
  layout against both images.
- Trace: marker 40 `SUPERVISOR_RESPONSE` (appended), arg verdict << 28 |
  the speed shed (mm/s), at every route-4 verdict; a miss also writes
  `SUPERVISOR_DEADLINE` with route 4 in its top bits.
- Kconfig: `ISLAND_SUPERVISOR_EMERGENCY_RESPONSE_MS` (default 1319, 0
  turns route 4 off, must be below `ISLAND_SUPERVISOR_EMERGENCY_MS`:
  BUILD_ASSERT) and `ISLAND_SUPERVISOR_EMERGENCY_DROP_MM_S` (default 250).
- Host tests (`just supervisor-test`, CI): `response_route` (the drop, one
  mm/s short, a faster vehicle, a stale sample, standstill at any
  reference) and `response_sequences` (the operator brakes: met; the
  request lost: the direct path at the response bound, then its own check
  met; a held speed: the vehicle-side fault at the second check; SWT0
  latched just before the due: wait, then judged from the latch; a stale
  sample: a miss).

## Board

Planning simulator, rtss-work-2026-demo `tools/eval/run-board.sh`.
`floor_check.py` and analysis.py's floor rows judge route 4 as the first
floor verdict (record and trace). The runs below were on nano-ros
8ff6a38df4, the rlm v0.3.1 bump's PR head (NEWSLabNTU/nano-ros#2987); the
pin is its merge, b40cd0ec49, five commits later (the nano-ros CLI, the
mps2-an385 board and its serial crate, and a zpico.c branch the island's
threaded session does not compile). On the pinned image, built from this
tree: floor-hold, floor-drop, floor-stall, encore and b PASS (p16f-fh1,
p16f-fd1, p16f-fs1, p16f-e1, p16f-b1), with the numbers inside the ranges
below except the encore's shed 632 mm/s and drop's call -> due 1454.03.
All times ms.

Floor-inject image (`just board-build-floor-inject`), entry speed 3.13-4.17
m/s (the |v| route 4 armed against). Every run PASS on record and trace:

| fault | n | call -> route 4 due | due -> verdict | due -> direct command | then | standstill | vehicle_fault |
|---|---|---|---|---|---|---|---|
| drop | 3 | 1454.83-1454.86 | 0.04 (record +0.036-0.041) | 0.60-0.73 | the direct path's response check met, 987-1143 mm/s shed against 250 | direct command -> standstill 2362.27-2714.39; last sample -> standstill 4402.50-4732.08 (the response check's row 6725.00; phase 15: 7790.97-7867.45 against 9890.33) | 0 |
| stall | 3 | 1454.22-1454.86 | 0.04 (+0.036-0.040) | 0.59-0.60 | met, 1059-1146 mm/s shed | 2697.60-2711.66; last sample -> standstill 4711.29-4755.91 | 0 |
| hold | 3 | 1454.82-1454.86 | 0.04 (+0.036-0.037) | 0.60-0.67 | route 4's second due 1454.96 after the first verdict, the vehicle-side fault 0.05-0.06 after it (`vehicle_fault_route` 4, at the held 1000 mm/s, 0 shed); MRM_FAILED / EMERGENCY_STOP on the wire 90.8-97.8 later; 30 braking commands in the second after; hazard lights ENABLE | the operator stopped the vehicle 3391.78-3424.49 after the call, unseen | 1 |

- On drop and stall route 3 never missed (`floor_latches` 0, its verdicts
  0) and ended at standstill (the handler cleared it when it saw the
  standstill); one route-4 verdict, `response_latches` 1, `response_met`
  1. On hold, route 4 found the vehicle-side fault 2909.9 ms after the
  emergency call (1454.86 + 0.04 + 1454.96 + 0.06); phase 15's route 3
  found it 9242 ms after the call (two whole spans).
- floor-stall-after, n 2: PASS (resume 99 ms silent, 65.82-65.96 ms after
  the stall marker; resume -> standstill 2424.27-2456.13; longest command
  gap 84.37-90.66), no route-3 or route-4 miss, no vehicle-side fault.
  Route 4 was not armed on this act (`response_unref` 2): the handler's
  300 ms overrun leaves its last kinematic_state older than the 300 ms
  freshness bound when it calls the emergency stop, so there is no
  reference to judge a drop against, and route 3 alone judges, as in
  phase 15. Arming against a stale reference was rejected: a reference
  older than the command can understate the speed (a vehicle that was
  still accelerating) and turn a nominal stop into a miss.
- Every run: latched by a route deadline (none on stall-after but route
  0's), SWT0 0 fires, `stale_at_due` 0, priorities AGREE. Runs p16-fd1..3,
  p16-fs1..3, p16-fh1..3, p16-fsa1..2 (fd1 and fs1 were judged by the
  first draft of floor_check.py, which required route 3 to be met by the
  supervisor; the handler clears it at standstill first, so the check now
  accepts either, and both runs pass it re-judged from their records).

Regression, the gate image (nm: 0 `island_debug_floor_*`): encore x3, a, b
PASS (p16g-e1..3, p16g-a1, p16g-b1): encore totals 3446.56-3476.05 of
5228.67 ms, every table 8/8; b 15863.55 of 21393.67, 16/16; a 8/8;
supervisor not driven, SWT0 0 fires, priorities AGREE. On each encore
route 4 was armed at the emergency call against 4155-4185 mm/s and met,
the vehicle having shed 632-761 mm/s by its due (p16f-e1 included) (the nominal profile's
750 at 1319 ms; `drop` 250): no false early verdict on a nominal stop. a
and b never call the emergency stop; route 4 is not armed there. Every
run also counts one `response_unref`: the emergency stop the handler
raises at boot, before any kinematic_state (route 3's `floor_unseen`
case).

## Acceptance

- `play_launch check` (0.22.0): 0 errors; `supervised-early` fits on both
  hazards; the response check's overrun rows 6725.00 (hpc_loss) and
  16474.00 (odd_exit); no row above its FTTI.
- floor-hold: route 4's verdict at the response bound latches the direct
  path, and its second verdict, one response span later, is the
  vehicle-side fault reported as MRM_FAILED.
- floor-drop, floor-stall: route 4 latches the direct path at the response
  bound; the direct path's own response check is met (no false early
  verdict); no vehicle-side fault.
- floor-stall-after, encore, a, b: no route-4 miss.
