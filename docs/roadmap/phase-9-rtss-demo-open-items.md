# Phase 9 - after the RTSS@Work 2026 proposal: what the demo left open

**Goal:** close what phase 8 left open, so that the booth runs the three
acts on the S32K344 the way the proposal describes them (a visitor
triggers each act and reads the trace against the contract) and every
number the demo shows is one the contract states and the board can report.

**Status (2026-10-01): plan. Nothing here is implemented.** The RTSS@Work
2026 demo proposal was submitted on 2026-09-30. Phase 8
(`docs/roadmap/phase-8-rtss-work-demo.md`) ended with the three acts
passing on silicon: 13 of 13 runs in W8 and 9 of 9 fresh runs in W31
against the board-derived budgets (`docs/takeover-trace.md` sections
9-11). Every item below is an "Open:" note of a phase-8 unit or a
follow-up (F1-F5) of section 10, and cites it. Nothing new was measured
for this document.

---

## 1. Where phase 8 stopped

| item | value | source |
|---|---|---|
| board image | main `71743c3`, ELF sha256 `664592d4...`, RAM 290,728 of 327,680 B (88.72 %) | takeover-trace.md section 11 |
| heap on the board | FirstSpin peak 77,160 of 102,912 B, 25,752 spare | sections 9, 11 |
| fresh runs | 9/9 VERDICT PASS, trace-check PASS, every row PASS | section 11 |
| `call_mrm` | 206 ms = link 57 + tick 118 + work 31 | section 10 |
| `driver_exit` | 149 ms = tick 118 + work 31 | section 10 |
| link, fresh | 8.93-67.02 ms (r01 60.64 and 67.02) against `max_transport` 57 | section 11 |
| encore, fresh | detect 579.60 / 618, total 3,505.54 / 4,904.67 ms | section 11 |
| violation ring at bring-up | full, 8 of 8 start-up entries | section 11 |

## 2. Units

Protocol as phase 8: `phase9-Wk`, disjoint files, real output only, ASCII,
one git writer per repository, the other projects through their own
phases, this repository by fast-forward push.

### Design

- **W1 - the booth UI.** One button per act (ODD exit, take over, HPC
  loss) and the trace plot drawn after each act. The proposal promises
  that visitors trigger each act; today an act is a
  `tools/timeline/run-board.sh` invocation by the presenter, and the plot
  is rendered from the run directory afterwards (phase 8 D7, W9). Design:
  which process owns the buttons (the scenario controller already logs
  button presses as events), how the next act waits for the island to be
  re-armed (W2), and what the visitor sees while the board resets.
  Gate: the design names the process, the event each button writes, and
  the per-act reset sequence.
- **W2 - re-arming the trace trigger.** The trigger fires once per boot,
  and a pre-act availability flap can fire it early (phase8-W17, "Open:").
  At a booth the acts follow each other without a reflash, so the second
  act's window would start at the first act's trigger. Design: re-arm on
  an explicit command or on the return to NORMAL; ignore a flap before the
  act starts (a guard on the scenario's own start event, or a minimum
  dwell). Gate: the design states the re-arm condition and how a flap is
  told apart from an act.
- **W3 - the board's time source.** Two problems with one cause, the
  board stamps from boot (no SNTP over serial):
  - hazard lights never reach the simulator from the board: the island's
    hazard command carries a boot-relative stamp; the island's own ENABLE
    is in every trace (section 9, "Not seen on the board"; phase8-W8
    "Open:"). On native_sim, with SNTP, ENABLE reaches `vehicle_cmd_gate`
    and the simulator 38-167 ms later (phase8-W26);
  - the island -> host clock merge: the two anchors disagree 13.05-47.62 ms
    over serial (section 9; under 1 ms on native_sim). Section 10 showed
    that in the A and B runs the disagreement is the in-link hop itself
    (matching the link edge to 0.13-0.62 ms), and that the merge places
    events by the smallest publish -> receipt pair, so a cross-clock row,
    the link term included, is over-stated by the smallest out-link delay
    and never under-stated. The measured hops are therefore upper bounds.
  Design: a time source the board can use over the serial link (a time
  sync exchange through the gateway, or SNTP routed to the board), and
  what the merge does once island stamps are on the host's epoch.
  Gate: the design states the source, its expected error, and which rows
  stop being cross-clock.
- **W4 - violations shown on the board's report.** In W31 no runtime
  violation could have been seen: the console (lpuart0) is unwired, and
  nothing drains the executor's violation ring, which keeps the first 8
  since boot and was full of start-up entries by bring-up (section 11,
  "Runtime contract violations"). The nano-ros phase in flight adds a
  violation channel; this unit designs the island's side: where the
  board's report (boot record, trace, or the link) carries each violation,
  and how the timeline draws it against the act. Gate: the design names
  the channel it consumes and the row or marker each violation becomes.

### Implementation

- **W5 - the contract budgets after F1.** Once play_launch charges
  `max_transport` on the reaction walk (its F1), take the 57 ms link out
  of `call_mrm`: 206 -> 149 ms, and the takeover window ends within
  10,149 ms instead of 10,206 (section 10, F1; the island contract's
  comment at `call_mrm` says where). Then re-size `max_transport` on
  `mrm_handler/operation_mode_availability` from 57 to about 81 ms (+20 %
  over the 67.02 ms seen in W31 r01) once more board runs exist (W14;
  phase8-W31 "Open:"). Gate: `play_launch check` clean, the variants
  still fail only their comfortable-stop rung, CI script green, the
  timeline's testdata/explain.txt regenerated, and the fresh board runs of
  W14 pass against the new numbers.
- **W6 - the demo compositions model the gate as it runs.** The three
  `demo/l3/contracts/l3_takeover*.contract.yaml` still state the
  availability gate as input-triggered (`trigger: { input:
  [availability_raw] }`, 20 ms, "declared, not measured"; phase8-W24
  "Open:"), and `l3_takeover.launch.xml` still names `takeover_demo`'s
  `availability_gate`. The container itself already starts W16's C++ gate
  through `gate-rt` (phase8-W24: `takeover.launch.xml`, W3's rclpy gate
  deleted), so phase8-W16's "the L3 container still launches W3's Python
  gate" is closed; what remains is the composition. Model the gate as the
  10 Hz timer it is, under its own package. Gate: the compositions'
  verdicts printed and explained, CI script green.
- **W7 - on-demand topics.** The contract's 10 Hz `min_rate_hz` on the
  comfortable-stop operator's `clear_velocity_limit` and
  `max_velocity_candidates` tripped `rate-hierarchy-runtime` at start-up
  (2 of the 8 ring entries in W31). Both are published on demand. Either
  drop the rate claim in the contract or adopt the on-demand key the
  play_launch phase adds. Gate: a bring-up whose violation readout has no
  `rate-hierarchy-runtime` entry for these two topics.
- **W8 - run-board.sh fails fast on a bad start.** In W31 one act-A
  attempt came up with 66 of 68 composables (`"ok":false`); run-board.sh
  still saw "Startup complete" and the act ran until "FATAL: the vehicle
  did not reach 1.0 m/s" (section 11). Abort, or restart the container,
  when the start record says `"ok":false`. Gate: a forced bad start is
  refused before the act.
- **W9 - hazard lights reach the simulator from the board.** After W3:
  the board's hazard command carries a stamp the host accepts. Gate: on
  the board, the simulator's hazard-lights status shows ENABLE in act B and
  the encore (the `hazard_lights_on` row is no longer `-`).
- **W10 - the Orin container.** The booth machine is an Orin, in
  Yokohama, after submission (branch `orin-arm64`): the
  `sai-l3-autoware` image built for arm64, with the same start checks
  (`nodes 31/31, containers 13/13, composable 68/68`). Gate: the three acts
  pass with the container on the Orin and the island on the board.
- **W11 - the booth UI, built.** W1's design, implemented over W2's re-arm.
  Gate: the three acts triggered from the buttons, back to back without a
  reflash, each followed by its plot, every row PASS.

### Test / check

- **W12 - the late-join EMERGENCY_STOP, re-checked.** In the encore of
  phase8-W26 a late-joining island ran a 150 ms EMERGENCY_STOP 80 ms after
  INIT -> RUN, 32 s before the act (seen in act A before W27 too). Main
  `88a336f` (W28: INIT ends only when every input is established, not
  merely heard) may have fixed it. Re-check on the current image with the
  island joining after Autoware is up. Gate: repeated late joins with no
  MRM before the act, or the cause if one recurs.
- **W13 - F4 and F5: the unmeasured hops and the handler's in-tick
  work.** F4: the link hop of `kinematic_state`, `operation_mode_state`
  and `control_cmd` (the trace keeps no per-sample take for them), and the
  emergency operator's 30 Hz tick jitter (its ticks are kept one in ten);
  both need trace markers from the nano-ros phase. F5: profile what the
  handler does for 5.4-9.7 ms before its first publish and 11-18 ms before
  the `operate` call (section 10). Gate: each hop with a measured range;
  the in-tick time split by function.
- **W14 - more board runs to size the link.** W31's 12 edges reached
  67.02 ms against W8's 47.43 (18 edges). Run more acts on the board
  until the link term's maximum is stable, then feed it to W5. Gate: the
  run count, the edge count and the maximum, with the cross-clock caveat
  of W3.
- **W15 - the host under load.** The host gate's gaps at load 30
  (phase8-W14 "Open:"), and the planner's rate under load (phase8-W16
  "Open:": the one W16 FAIL was Autoware's `comfortable_stop`
  availability dropping when `/planning/trajectory` exceeded its 1 s topic
  timeout). Gate: a soak at the stated load with the largest gate gap and
  the planner's rate reported.
- **W16 - bad frames on the serial link.** In-run bad frames with no UART
  error and no ring overflow, about one per 80 min of soak at contract
  rates (3 in 250 min), cause open (docs/serial-link.md). Investigate with
  the frame capture image. Gate: the cause, or a capture of enough frames
  to rule causes out.
- **W17 - hygiene, in the background.**
  - Stale out-of-source build trees in the island repository (19 `build-*`
    directories today; 85 at the 2026-09-12 peak) and old worktrees under
    `/mnt/mx500/aeon/worktrees` (179 entries today).
  - The superseded paper repository `~/repos/rtss-work-2026-paper`; the
    paper now lives in the lab SVN.
  - Caches and worktrees off `/home`.
  - Drop the rmw_zenoh testing apt source and the rclcpp executor patch
    once ROS apt ships the fixes (phase8-W11 "Open:").
  Gate: each item done or stated as kept, with the reason.

## 3. Depends on

- **The play_launch phase:** F1 (transport charged on the reaction walk;
  W5), F2 (a timer release-jitter key), F3 (service-edge queueing), and
  the on-demand key (W7).
- **The nano-ros phase:** the violation channel (W4), monitor arming (so
  start-up does not fill the ring before the act), trace markers for the
  F4 hops (W13), and the heap.

## 4. Order

Violation visibility (W4) and F1 (W5) first; the booth UI (W1, W2, W11)
next; the late-join re-check (W12); hygiene (W17) in the background.
