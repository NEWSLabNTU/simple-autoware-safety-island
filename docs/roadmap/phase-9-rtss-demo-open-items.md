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

2026-10-05: W18-W23 added from the DX and UX survey (next section); the
units already tracked carry a "DX:" line naming the gaps they close.

## DX and UX gaps, 2026-10-05

A read-only survey of the launch-contract toolchain (rlm, play_launch,
nano-ros and this island), by journey stage from writing a contract to
running the booth, made on 2026-10-03: `docs/dx-ux-gaps-2026-10.md`
(copied from the deck directory, `~/Downloads/contract-e2e-slides/`, which
is outside this repository). Every gap there has its evidence as file:line,
a severity, an owner repository and where it is tracked. "DX n.m" below is
a section of that file.

Gaps owned by this repository, or shared with it, that no unit tracked are
W18-W23; the cheap ones (under a day each) are grouped as W22, to be done in
one sitting. Gaps already tracked carry a one-line "DX:" reference under
their unit. Gaps owned by play_launch go to its phase 85
(`docs/roadmap/phase-85-what-the-island-left-open.md` in play_launch), those
owned by nano-ros to its phase 474 (merged;
`docs/roadmap/phase-474-safety-island-board-findings.md`); where a gap is
in neither, the row says so.

The top 10 (DX section 8, ranked by severity times how often it is hit):

| # | gap | DX | owner | here | play_launch / nano-ros |
|---|---|---|---|---|---|
| 1 | runtime violations invisible on the board; the ring keeps the first 8 and fills at start-up | 5.1, 5.2 | NR, SAI | W4 | NR474 D1, D2, I1, I2, T4 |
| 2 | play_launch version skew; the error never names a version | 2.1-2.3 | SAI, PL, RLM | W22 (doctor minimum), W19 | `--version` naming the grammar: not in PL85, handed over by W19 |
| 3 | declared endpoints never cross-checked against the code | 1.6 | NR, PL | - (W18 lists it) | not in PL85 or NR474 |
| 4 | booth: no visitor UI, a reflash and an Autoware restart per act, the trigger fires once per boot | 6.1, 6.2, 5.5 | SAI | W1, W2, W11 | - |
| 5 | wrong-checkout and per-worktree environment traps | 3.1, 3.2 | NR | the island side done (scripts/env.sh: the submodule wins); runbook line in W22 | NR issues 1253, 1254, 1234, 1596, 1373; not in NR474 |
| 6 | budgets with no keys: composite `call_mrm`, `max_transport` not charged, budget = deadline = monitor | 1.2-1.4, 5.3 | RLM, PL, NR | W5 | PL85 D1, D2, D4, I1; NR474 D3, D4 |
| 7 | no board time source: hazard lights, the clock merge | 5.4, 6.8 | SAI, NR | W3, W9 | NR issue 0758 |
| 8 | CI negative tests compare exit codes only | 2.4 | SAI | W22 | - |
| 9 | hand-set heap; stated knobs beat the derivation; derived counts without arithmetic | 3.4-3.6 | NR | W22 (the liveliness inventory) | NR474 I5; NR issues 1424, 1490 |
| 10 | host-side flakiness read as island faults: start flake, gate stall, load | 6.5, 6.6, 5.8 | UP, SAI | W15, W17, W21 (rtprio setup) | - |

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
  DX: see DX-UX-GAPS 6.1, 6.2, 6.3 (the six-terminal manual path), 6.8.
- **W2 - re-arming the trace trigger.** The trigger fires once per boot,
  and a pre-act availability flap can fire it early (phase8-W17, "Open:").
  At a booth the acts follow each other without a reflash, so the second
  act's window would start at the first act's trigger. Design: re-arm on
  an explicit command or on the return to NORMAL; ignore a flap before the
  act starts (a guard on the scenario's own start event, or a minimum
  dwell). Gate: the design states the re-arm condition and how a flap is
  told apart from an act.
  DX: see DX-UX-GAPS 5.5, 6.2.
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
  DX: see DX-UX-GAPS 5.4.
- **W4 - violations shown on the board's report.** In W31 no runtime
  violation could have been seen: the console (lpuart0) is unwired, and
  nothing drains the executor's violation ring, which keeps the first 8
  since boot and was full of start-up entries by bring-up (section 11,
  "Runtime contract violations"). The nano-ros phase in flight adds a
  violation channel; this unit designs the island's side: where the
  board's report (boot record, trace, or the link) carries each violation,
  and how the timeline draws it against the act. Gate: the design names
  the channel it consumes and the row or marker each violation becomes.
  DX: see DX-UX-GAPS 5.1, 5.2 (top-10 row 1).
  Status (2026-10-10): the board gate PASSES at nano-ros `319715968`
  (PR #1825's merge commit, with PR #1764's merge `2b8153621`): runs
  `w4-gate-ab` and `w4-gate-encore`, branch `phase9-w4-rerun`, below the
  rehearsal. History: status (2026-10-06): implemented; the board gate
  is NOT passed as written, for reasons that are nano-ros's (below). Branch `phase9-w4`,
  not merged to main. The runs were built at nano-ros `5b3ac4567`, the head
  of PR #1729 (`feat/violation-ring-and-arming`, phase-474 I1/I2); the PR was
  then rebased and the pin moved to its new head `810c73341` (two non-code
  files differ). PR #1729 merged on 2026-10-06 as nano-ros main
  `99f03da7f`, and the pin now points there (the same tree as `810c73341`
  rebased onto main; not rebuilt, the three readouts above are from
  `5b3ac4567`).
  - [x] Pin, `just setup-cli`, `just doctor` OK (play_launch 0.13.1, the SDK
    lock's two zephyr-sdk tables). The pin's issue-1498 floor asked for 19
    pthread conds (board and QEMU confs, 17 -> 19).
  - [x] Island config (board, native_sim, QEMU):
    `CONFIG_NROS_MONITOR_ARM_ON_CALL=y`, no grace;
    `CONFIG_NROS_EXECUTOR_MAX_VIOLATIONS=8` (the default; with arming the
    ring takes no start-up entries, and the trace keeps every verdict);
    `CONFIG_NROS_VIOLATION_DRAIN_REPORT` off on the board (its log goes to
    the unwired lpuart0), on in native_sim; `CONFIG_NROS_TRACE_CALLBACKS=y`.
    The handler arms on the first tick with every input established
    (INIT_DONE, or an init failure clearing), NOT at INIT_TIMEOUT: on the
    board INIT always times out before Autoware starts, and arming there
    would store the availability's silence for the whole wait.
  - [x] Trace markers: the island ids stay 1-31; nano-ros's violation
    events 21-24 are forwarded by an island sink at 256 + id = 277-280, and
    a stored violation also opens the trace window. gen_markers.py reads
    the ids and RULE_IDS from the pinned monitor.rs and hashes the
    contract's endpoint refs; island_trace.py, merge.py and render.py name
    and draw each verdict (docs/tracing.md section 9). native_sim, QEMU and
    board images build; `.github/check-contracts.sh` 14/14 as expected (the
    contract is untouched).
  - [x] SWD readout: tools/timeline/violations.py reads
    `NROS_VIOLATION_RECORD` by symbol through the pinned
    read-violation-record.py; readout.py reads it in its halt, so every
    run directory gets `violations.txt` (vscan.py retired).
  - [x] Found on the way, fixed here: the first stored violation halted the
    board (K_ERR_ARM_USAGE_ILLEGAL_EPSR) because the pin's `/diagnostics`
    reporter (issue 1635) overflowed the 16 KiB main stack into the idle
    thread's; bisected on the bench, main stack 24576 (high-water 18,780 B).
  - [ ] Gate (a), bring-up (`w4-bringup2`). Before Autoware:

      violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
        total=0 dropped=0 suppressed_before_arm=5 armed=0
        handler armed the monitors: not armed
        read at uptime ~3500 ms (last trace heartbeat)
        EMPTY: no violation stored since boot

    After RUN, nothing commanded (45 s):

      violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
        total=10 dropped=2 suppressed_before_arm=8 armed=1
        handler armed the monitors: init failure cleared at uptime 6974 ms
        read at uptime ~52000 ms (last trace heartbeat)
        #10: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=29990 declared=30000
        #9: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=29990 declared=30000
        #8: release-jitter-runtime spin measured=88585 declared=10000
        #7: timer-overrun-runtime timer measured=1 declared=0
        #6: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9984 declared=10000
        #5: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9984 declared=10000
        #4: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9984 declared=10000
        #3: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9984 declared=10000

    `armed` 0 -> 1 (via the init-failure recovery, 6,974 ms), start-up in
    `suppressed_before_arm` (8), no rate verdict on the two on-demand
    topics (W7). NOT empty: the availability's silence at arming (the board
    has no epoch, so nano-ros never counts its takes; W3), the rate rule's
    first window after arming at 9984/10000 and 29990/30000 mHz, and the
    `/diagnostics` reporter's own cost (15-20 ms of spin per verdict over
    serial: release jitter 88.6 ms, one timer overrun).
  - [ ] Gate (b), a 250 ms commanded overrun of the handler's tick (same
    boot; `violations.py overrun 250`):

      violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
        total=17 dropped=9 suppressed_before_arm=8 armed=1
        handler armed the monitors: init failure cleared at uptime 6974 ms
        read at uptime ~57900 ms (last trace heartbeat)
        #17: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=28788 declared=30000
        #16: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=28788 declared=30000
        #15: timer-overrun-runtime timer measured=1 declared=0
        #14: release-jitter-runtime spin measured=246918 declared=10000
        #13: timer-overrun-runtime timer measured=1 declared=0
        #12: timer-overrun-runtime timer measured=1 declared=0
        #11: timer-overrun-runtime timer measured=7 declared=0
        #10: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=29990 declared=30000

    In the trace the tick runs 250.65 ms and the verdicts follow it as
    VIOLATION markers; but no `max-latency-runtime`: the rule did not see
    the timer's dispatch (likely the unmeasured timer sweep in nano-ros
    spin.rs), so the contract's 206 ms rows are not judged on this image.
  - [x] Gate (c), encore (`w4-encore`): VERDICT PASS, every table row PASS;
    no verdict stored during the act (all 8 are 27-32 s before it, the set
    of (a)):

      violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
        total=8 dropped=0 suppressed_before_arm=8 armed=1
        handler armed the monitors: init failure cleared at uptime 6274 ms
        read at uptime ~43500 ms (last trace heartbeat)
        #8: release-jitter-runtime spin measured=86278 declared=10000
        #7: timer-overrun-runtime timer measured=1 declared=0
        #6: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9990 declared=10000
        #5: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9990 declared=10000
        #4: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9990 declared=10000
        #3: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9990 declared=10000
        #2: release-jitter-runtime spin measured=15428 declared=10000
        #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500

  The three readouts in full, with the trace, are docs/takeover-trace.md
  section 12. Handed to nano-ros (phase 474): max-latency blind to
  sweep-fired timers; the reporter on the spin thread (cost, stack); the
  rate rule's first window after arming; and (with W3) silence without an
  epoch. Open here: the boot record's heap headroom reads REFUSED on this
  pin (peak 79,712 of 102,912 B), not resized.
  Rerun (2026-10-09, branch `phase9-w4-rerun`): NOT run as the gate. The
  gate waits for nano-ros PR #1764 (feat/474-rest: I7 scheduling half, I5,
  I3, I4, T4) to merge; it was still OPEN after the 60 min poll (head
  `6cc3790a0`). #1750 (I6, I8, I7 stack half) and #1749 are on nano-ros
  main. The branch pins #1764's head and carries the island-side changes;
  the three readouts below are a REHEARSAL at that head, not the gate.
  Re-pin to the merge commit, `just setup-cli`, rebuild, and run the gate.
  - [x] Pin `6cc3790a0` (PR head), `just setup-cli`, `just doctor` OK. In a
    shell carrying the main checkout's .envrc, configure picked up the main
    checkout's nros (ABI 9 vs runtime 2..=8): builds here ran under `env -i`
    with scripts/env.sh. Old build trees (W4 pin) failed on a removed
    `_NrosFindRosMsgPackage.cmake` stub: native_sim, QEMU and board were
    built pristine.
  - [x] Sizing (board; QEMU board conf alike): `CONFIG_MAIN_STACK_SIZE`
    16384 (paint over SWD: high-water 12,136 B after bring-up + overrun,
    12,200 B after an encore; 4,184 B spare, so 16384 stays);
    `CONFIG_NROS_ZEPHYR_HEAP_SIZE` 106496, not #1764's 104448: at 104448 the
    boot record after an encore read `HEAP HEADROOM: REFUSED -- 24056 bytes,
    floor is 24576.` (peak 80,904 of 104,960); at 106496 `HEAP HEADROOM: ok
    -- 26104 bytes spare (peak 80904 of 107008, floor 24576).` No "stated
    below its derivation" warning: this pin derives no heap, so the
    configure compares nothing. `CONFIG_RAM_TRACING_BUFFER_SIZE` 40960. RAM
    305,056 of 327,680 B.
  - [x] T3: `CONFIG_MAIN_THREAD_PRIORITY=5`, RX ring 4096 kept; the
    configure's priority warning (nros_rmw_zenoh.cmake, issue 1534) did not
    fire.
  - [x] I3 (F4 enabler): `CONFIG_NROS_TRACE_TAKES=y`,
    `CONFIG_NROS_TRACE_TIMER_EVERY=10`; the island binds each input's slot
    from the take seen just before its callback (C/C++ subscriptions
    register as `sub#N`), sets its stamp offset 4 and forwards takes at
    281-283 (docs/tracing.md section 9); the emergency operator's 30 Hz
    timer keeps every tick (`nros_trace_set_timer_every(slot, 1)`; the
    island sink does not forward 18/19). Bound slots: control_cmd 0,
    kinematic_state 6, operation_mode_state 10, operator timer 2.
  - [x] I4: caps at `<repo>/nros-codegen.toml`. Package scope: mrm_handler
    and stop_mode_operator probes fail to build (frame_id). Root: all four
    build and run, then stop at `declare_parameter (code=-16)`; "no
    producer" is NOT gone (the parameter-store gap phase-474 I4 names).
  - [x] native_sim, QEMU (trace) and board images build;
    `.github/check-contracts.sh` 14/14 (its play_launch check of the
    island contract: clean, 2 warnings, as before).
  - Rehearsal (a), `w4r-pre-ab` (encore with the act replaced by
    readouts; superseded by the gate below). Before Autoware:

      violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
        total=0 dropped=0 suppressed_before_arm=5 armed=0
        handler armed the monitors: not armed
        read at uptime ~4900 ms (last trace heartbeat)
        EMPTY: no violation stored since boot

    After RUN, nothing commanded (40 s):

      violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
        total=10 dropped=2 suppressed_before_arm=9 armed=1
        handler armed the monitors: init failure cleared at uptime 11265 ms
        read at uptime ~66300 ms (last trace heartbeat)
        #10: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=29773 declared=30000
        #9: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=29773 declared=30000
        #8: release-jitter-runtime spin measured=68369 declared=10000
        #7: timer-overrun-runtime timer measured=2 declared=0
        #6: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9999 declared=10000
        #5: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9999 declared=10000
        #4: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9999 declared=10000
        #3: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9999 declared=10000

    Rehearsal result, FAIL as written: the first rate window after arming read
    9999/10000 and 29773/30000 mHz (I8 re-anchors the window but the rule
    has no tolerance), and the verdicts are still 15-17 ms apart in the
    trace with a timer overrun and 68 ms of release jitter right after
    them (I7's scheduling half does not show on the board at this head).
    #1 (silence on the availability, W3) is in the trace at 11,820 ms.
  - Rehearsal (b), same boot, `violations.py overrun 250`: I6 works, three
    `max-latency-runtime` verdicts (one per monitored publisher of the
    tick, not one), then the overrun's own timer-overrun and jitter:

      #11: max-latency-runtime /mrm_handler/hazard_lights_cmd measured=250 declared=100
      #12: max-latency-runtime /mrm_handler/mrm_state measured=250 declared=206
      #13: max-latency-runtime /mrm_handler/takeover_request_state measured=250 declared=206
      #14: timer-overrun-runtime timer measured=9 declared=0
      #15: timer-overrun-runtime timer measured=2 declared=0
      #16: timer-overrun-runtime timer measured=2 declared=0
      #17: release-jitter-runtime spin measured=242934 declared=10000
      #18: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=28583 declared=30000
      #19: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=28583 declared=30000

    (trace, `island_trace.py violations`; the record keeps #12-#19). #15
    and #16 come 15 ms apart after #14, the reporter's spacing.
    Gate (b) wording: one `max-latency-runtime` verdict PER MONITORED
    PUBLISHER of the overrunning tick (three on the handler: each
    publisher's own budget was broken), not one for the tick.
  - [x] Found from the pin's monitor.rs (2026-10-09), two causes, neither
    the reporter:
    - The 15-17 ms spacing, and the timer-overrun and release-jitter
      verdicts after each stored one, are the LOG FLOOR: `record()` logs
      every verdict at detection (`log_violation`) unless the drain hook
      reports, and this board has `CONFIG_LOG_MODE_IMMEDIATE=y` with the
      console on the unwired lpuart0 at 115200 baud, so each ~170-character
      warn line is shifted out on the spin thread, ~15 ms. The I7 reporter
      was already off the judged tick. Fix here: `CONFIG_LOG_DEFAULT_LEVEL=1`
      on the board (errors only; nothing reads lpuart0). Expect: the three
      max-latency verdicts of (b) within one tick, no overrun or jitter
      verdict after them, and after RUN no timer-overrun or jitter verdict.
    - The 9999/10000 mHz rate verdicts are the rule's arithmetic, not the
      window's phase: `check_rate` floors `published * 1e9 / window_us`, and
      the window closes at the first tick after the interval, so a stream
      at exactly its declared rate reads one mHz short in EVERY window
      (reported once, `violated_last_window`). nano-ros branch
      `fix/474-rate-floor` (phase-474 I9) judges the count against
      floor(min_rate * window) instead. The 29773/30000 on the emergency
      operator's two topics was a real shortfall (149 samples in 5.004 s),
      but not a timer cadence or clock defect: see the next item.
    - The emergency operator's 29773/30000 mHz (found 2026-10-09, run
      `w4r-ticks`): the operator's timer runs at 33.000 ms (`1000 /
      update_rate` = 33 ms, mrm_emergency_stop_operator_core.cpp:90, so
      30.30 Hz, 1 % over the declared 30 Hz), and the executor carries
      every remainder (spin.rs:9614-9623 accumulates `now - last_spin_end`;
      arena.rs:2836-2875). It lost two ACTIVATIONS in that window: the log
      floor above stalled the spin for ~100 ms (verdicts #3-#8 at
      16383-16481 ms, ~16 ms each), and the timer's default overrun policy
      `Skip` (arena.rs:2866-2873, rclcpp's behaviour) fires once after a
      stall and drops the missed periods, counted: that is verdict #7,
      `timer-overrun-runtime timer measured=2`. 151.6 - 2 = 149.6 ticks in
      the 5.004 s window that opened at 16332 ms -> 149. The handler's
      100 ms timer loses nothing to a 100 ms stall (it would need >= 200
      ms), hence 9999 there, the floor defect only. Evidence:
      - Old traces (the operator's own ON_TIMER_ENTRY, one tick in ten,
        `spin_keep` 10): 10-tick spans of 329-331 ms throughout (33.0 ms a
        tick); `w4r-pre-ab` has ONE span of 396 ms (= 12 periods) starting
        at 16115 ms, across the stall, and one of 627 ms (19 periods) across
        the commanded 250 ms overrun of gate (b) (28583 mHz, 9 dropped).
        `w4r-pre-encore2`: one 361 ms span at 11098 ms (1 dropped,
        `timer measured=1`, 29972 mHz).
      - `w4r-ticks` (image of cbf2ad5 plus the bound timer's nano-ros
        18/19 forwarded at 274/275, `CONFIG_ISLAND_TRACE_TIMER_TICKS`; the
        act replaced by `sleep 45`): 1073 ticks over 35.375 s,
        start-to-start mean 32.999 ms (30304 mHz), min 28.856, max 37.336;
        histogram at 1 ms bins: 28: 1, 29: 2, 30: 16, 31: 60, 32: 463,
        33: 456, 34: 50, 35: 21, 36: 2, 37: 1; no gap of 1.5 periods or
        more. Callback 0.552 ms mean, 3.196 ms max. The four 9998 verdicts
        were stored 90 us apart (13270.363-13270.637 ms), not 16 ms: no
        timer-overrun, no release-jitter and no operator rate verdict in
        the record (total=5). The buffer filled 25 s before the readout
        with the forwarding on, so it is off by default
        (src/safety_island_tracing/Kconfig.island_trace).
      Fix: `CONFIG_LOG_DEFAULT_LEVEL=1` (cbf2ad5), already on this branch;
      no nano-ros change. Still open: (1) any spin stall of two periods
      (66 ms) drops an operator activation by design and reads as a rate
      verdict in the next window, so `min_rate_hz` equal to the producer's
      own rate leaves no margin (contract question, as above); (2) the
      period is 33 ms by integer division, not 33.333 ms: 30.30 Hz on the
      wire, which is the only margin the rule had.
  - Rehearsal (c), `w4r-pre-encore2` (final image): VERDICT PASS,
    every table row PASS; 11 verdicts stored, all 6.1-16.2 s after boot,
    the act at ~38 s: none during it. HEAP HEADROOM ok (above). Takes in
    the trace: 437 (kinematic_state 225, control_cmd 201, of them 199
    stamped, operation_mode_state 11); render's take - stamp estimate
    36.8 ms median for control_cmd, 44.8 ms for kinematic_state (on the
    host REALTIME - MONOTONIC offset read at merge; a first estimate, not
    F4). Some early control_cmd samples carry a stamp ~island uptime, not
    host time (counted apart by render.py).
  Handed back to nano-ros (#1764 / phase 474): on the board the reporter
  still costs 15-17 ms per verdict on the spin and breeds timer-overrun and
  release-jitter verdicts; the rate rule's first window after arming still
  judges 9999/10000; I6 stores one verdict per monitored publisher.
  Gate (2026-10-10, branch `phase9-w4-rerun`): nano-ros pinned at
  `319715968` (nano-ros main: PR #1764 merged as `2b8153621`, PR #1825,
  phase-474 I9, merged as `319715968`). PASSED, all three readouts.
  - [x] Re-pin `319715968`, `just setup-cli`, `just doctor` OK (under
    `env -i` with scripts/env.sh, as every build and run below).
  - [x] native_sim (build-zephyr), QEMU trace (build-qemu-trace) and board
    (build-board) built pristine (trees removed first);
    `.github/check-contracts.sh` 14/14. No "stated below its derivation"
    warning: the configure derives no heap at this pin either, so
    `CONFIG_NROS_ZEPHYR_HEAP_SIZE` stays 106496. Board ELF sha256
    `39dd64334ce8ca7108a8c58418315f8c24ece519c17005fa5bd800da5703bd25`,
    RAM 305,056 of 327,680 B; `LOG_DEFAULT_LEVEL=1`, main stack 16384,
    trace buffer 40960 (the trace provenance names them).
  - [x] Gate (a), bring-up (`w4-gate-ab`, encore with the act replaced by
    readouts). Before Autoware:

      violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
        total=0 dropped=0 suppressed_before_arm=3 armed=0
        handler armed the monitors: not armed
        read at uptime ~1900 ms (last trace heartbeat)
        EMPTY: no violation stored since boot

    After RUN, nothing commanded (40 s):

      violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
        total=1 dropped=0 suppressed_before_arm=4 armed=1
        handler armed the monitors: init failure cleared at uptime 6074 ms
        read at uptime ~61100 ms (last trace heartbeat)
        #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500

    PASS: no rate-hierarchy, timer-overrun or release-jitter verdict after
    arming; the one stored is the availability's silence (W3, no epoch), in
    the trace at 6599.790 ms. The 9999/10000 and 29773/30000 mHz verdicts of
    the rehearsal are gone (I9 and the log floor, cbf2ad5).
  - [x] Gate (b), same boot, `violations.py overrun 250`. The record 5 s
    later (it keeps the latest 8):

      violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
        total=14 dropped=6 suppressed_before_arm=4 armed=1
        handler armed the monitors: init failure cleared at uptime 6074 ms
        read at uptime ~66900 ms (last trace heartbeat)
        #14: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9787 declared=10000
        #13: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9787 declared=10000
        #12: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9787 declared=10000
        #11: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9787 declared=10000
        #10: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=28921 declared=30000
        #9: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=28921 declared=30000
        #8: release-jitter-runtime spin measured=242922 declared=10000
        #7: timer-overrun-runtime timer measured=1 declared=0

    and the trace (`island_trace.py violations`):

      trace violations: 14 (trace window opened by NROS_VIOLATION)
            6599.790 ms  #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500
           61825.694 ms  #2: max-latency-runtime /mrm_handler/hazard_lights_cmd measured=250 declared=100
           61825.782 ms  #3: max-latency-runtime /mrm_handler/mrm_state measured=250 declared=206
           61825.871 ms  #4: max-latency-runtime /mrm_handler/takeover_request_state measured=250 declared=206
           61827.614 ms  #5: timer-overrun-runtime timer measured=7 declared=0
           61827.700 ms  #6: timer-overrun-runtime timer measured=1 declared=0
           61827.785 ms  #7: timer-overrun-runtime timer measured=1 declared=0
           61827.872 ms  #8: release-jitter-runtime spin measured=242922 declared=10000
           66163.167 ms  #9: rate-hierarchy-runtime /mrm_emergency_stop_operator/emergency_control_cmd measured=28921 declared=30000
           66163.475 ms  #10: rate-hierarchy-runtime /mrm_emergency_stop_operator/status measured=28921 declared=30000
           66232.772 ms  #11: rate-hierarchy-runtime /mrm_comfortable_stop_operator/status measured=9787 declared=10000
           66232.868 ms  #12: rate-hierarchy-runtime /mrm_handler/hazard_lights_cmd measured=9787 declared=10000
           66232.958 ms  #13: rate-hierarchy-runtime /mrm_handler/mrm_state measured=9787 declared=10000
           66233.052 ms  #14: rate-hierarchy-runtime /mrm_handler/takeover_request_state measured=9787 declared=10000

    PASS: the three `max-latency-runtime` verdicts (100, 206, 206) stored
    within 0.18 ms of each other (61825.694-61825.871), one tick. What
    follows is the overrun's own: the spin was held from the last take at
    61548.834 ms to 61825.694 ms; the next handler tick ran
    61826.869-61827.525, and then, within 0.26 ms, the three timers' Skip
    counts (the 30 Hz operator 7 periods, the two 10 Hz timers 1 each) and
    the spin's release jitter of 242.9 ms. 5 s later the rate windows that
    held the stall close short by exactly those activations: 30 Hz at
    28921 mHz, 10 Hz at 9787 mHz (49 in the window). No verdict is spaced
    15 ms apart and no overrun or jitter verdict follows a stored verdict.
  - [x] Gate (c), encore (`w4-gate-encore`, a normal `run-board.sh
    encore`): VERDICT PASS, every table row PASS (detect 602.00 of 618,
    route 8.41 of 239.33, detect + route 610.41 of 739.33, settle 2865.15
    of 4165.33, total 3475.57 of 4904.67, EMERGENCY_STOP reached, entry
    speed 4.25 of 8.33 m/s). The readout at its end:

      violation record (NROS_VIOLATION_RECORD, layout v1, capacity 8):
        total=5 dropped=0 suppressed_before_arm=4 armed=1
        handler armed the monitors: init failure cleared at uptime 5965 ms
        read at uptime ~43500 ms (last trace heartbeat)
        #5: release-jitter-runtime spin measured=17888 declared=10000
        #4: release-jitter-runtime spin measured=14905 declared=10000
        #3: release-jitter-runtime spin measured=13794 declared=10000
        #2: release-jitter-runtime spin measured=13625 declared=10000
        #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500

      trace violations: 5 (trace window opened by NROS_VIOLATION)
            6494.773 ms  #1: silence-runtime /mrm_handler/operation_mode_availability measured=0 declared=500
           21121.524 ms  #2: release-jitter-runtime spin measured=13625 declared=10000
           22121.692 ms  #3: release-jitter-runtime spin measured=13794 declared=10000
           32318.925 ms  #4: release-jitter-runtime spin measured=14905 declared=10000
           33230.385 ms  #5: release-jitter-runtime spin measured=17888 declared=10000

    No verdict stored during the act: the last availability sample before
    the HPC loss is at island 38,470 ms and MRM_OPERATING at 39,079 ms (the
    merge's anchors); the last verdict is 5.2 s before. Boot record (SWD,
    after the run): `HEAP HEADROOM: ok -- 35088 bytes spare (peak 71920 of
    107008, floor 24576).` Main stack paint over SWD: high-water 11,640 B
    of 16,384 (4,744 B spare; the same after (b)). Takes in the trace
    (281-283): 431, kinematic_state 224, control_cmd 196, operation_mode_state
    11, all stamped. Trace buffer: 28,135 of 40,960 B (26,038 B after the
    trigger, 37.07 s); `w4-gate-ab` used 25,959 B. Not in (a)'s shape and
    new against the rehearsal: #2-#5, four single release-jitter verdicts
    of 13.6-17.9 ms against 10 ms, 0.9-10 s apart, while the scenario set
    the pose, the goal and engaged (21-33 s); each sits on a
    `kinematic_state` take or an operator tick and none is followed by
    another verdict, so they are not the log floor or the reporter. Not
    explained here; they did not occur in (a), where nothing published
    `kinematic_state`. The spin's 10 ms jitter bound is the contract's; a
    question for the contract (as the rate rule's margin above), not a gate
    failure (c) as written.
  Closed at this pin: the reporter's per-verdict cost (with the log floor),
  the rate rule's floored quotient (I9), max-latency on sweep-fired
  timers (I6). Still open: silence without an epoch (W3).
  - [x] Margin on the island's own rate floors (2026-10-10, decided: option
    "lower the floor"). Gate (b) showed what a `min_rate_hz` equal to the
    producer's own timer rate buys: the overrun's two dropped ticks came
    back a window later as rate verdicts (9787/10000, 28921/30000) beside
    the overrun's own verdict. The island's streams now promise 9 and 27
    (one period of slack per 5 s window), the handler requires 9 of the
    operators' status, and the host's floors (kinematic_state,
    control_mode, control_cmd, the detector) stay. rlm reads a topic's
    `rate_hz` as the floor its publisher must sustain (`rate-hierarchy`:
    "rate_hz (10) > publisher min_rate_hz (9)"), so the island topics'
    `rate_hz` rows went too: play_launch 0.14.0 derives them from the
    timers (`derivable-rate` said so), and the budget table is unchanged
    (hpc_loss 4961.67, odd_exit 20565.67 under 0.14.0, which charges the
    link; W5). The three L3 compositions carry the same floors. Takes
    effect in the image at the next build (the gate above ran at 10/30);
    expected: no rate verdict after a commanded overrun. Open in rlm: a
    nominal rate and a floor are one key (DX gap 1.4; play_launch phase
    85).
  Spin release latency (2026-10-10, branch `phase9-spin-latency` on
  `9727131`; nano-ros phase-474 I10, draft PR #1857). The four 13.6-17.9 ms
  release-jitter verdicts above were the serial reader: the read task
  (k_thread 4, above main at 5) and the RX ISR held the CPU for each
  frame's wire time (11.5 ms per 1 KB kinematic_state) because the reader
  woke once per byte. Measured with a diagnostic build
  (`CONFIG_ISLAND_SPIN_DIAG`, off; needs `experiments/spin-latency/*.patch`
  on nano-ros; `tools/timeline/spin_diag.py` reads it over SWD).
  - [x] before, `sl-diag-before` (pin `319715968` + diag), act only: 3589
    spin intervals, 74 at 10 ms or more late (max 19 ms), 199 at 5 ms or
    more, p99 in the 12-13 ms bin; 8 verdicts 10.0-18.8 ms; each 10 ms+
    interval had zpico_read 11.5-17.3 ms of CPU in the 10 ms park.
  - [x] after, `sl-diag-fix` (pin + zenoh-pico `199e611f` + diag), act
    only: 3997 intervals, 1 at 10 ms or more (14.5 ms), 13 at 5 ms or more,
    p99 in the 3-4 ms bin; zpico_read at most 1.5 ms per interval;
    rx_wakes 1548 for 1542 frames, no bad frame, no ring overflow.
  - [x] pinned clean image, nano-ros `9eed444b3`
    (`fix/spin-release-latency-319715968`: `319715968` + the same pin bump;
    the PR head on nano-ros main cannot be pinned, main's phase-483 W1
    moved the C++ API to `rclcpp::`), `sl-bp-encore`: VERDICT PASS, detect
    513.35, route 11.62, total 3460.51 ms; one verdict, release-jitter
    10.3 ms. RAM 305,056 B as before.
  - [ ] open, island side: the remaining verdict (and the 14.5 ms one) is
    the handler's own `std::printf` on the 115,200 baud console in the
    reaction tick, two lines of about 56 characters, 4.9 ms each (ENTRY to
    CALL 4.93 ms in the trace); route carries it.
  - [x] grid release, nano-ros `1551851d6` (`fix/spin-cadence-319715968`:
    `9eed444b3` + phase-474 I11, draft PR #1896 on main): a `spin_once(10)`
    loop parks to the next point of an absolute 10 ms grid instead of 10 ms
    from its own entry, skips (counts) only whole missed periods, and the
    jitter rule judges release minus grid point; Zephyr's ms wait no longer
    adds a tick. Run `sl-cadence-diag` (pin + diag, on `9e20a42`, console
    prints off), act only: 5810 spin intervals (more than 3997: a spin woken
    early by data is now its own interval), 61 at 1 ms or more late (before,
    `sl-diag-fix`: 603), 2 at 5 ms or more (13), 0 at 10 ms or more (1),
    max 5.9 ms (14.5), p99 in the 1-2 ms bin (3-4). The diag measures entry
    to entry, so a long dispatch still reads late here though the release
    after it is on the grid: the 5.9 ms interval is a 5.5 ms callback
    (2.8 ms waiting for the link in a send). Encore VERDICT PASS, detect
    561.48, route 32.04, total 3506.54 ms; no `release-jitter-runtime`
    verdict stored (the record holds only the known
    `silence-runtime operation_mode_availability`). Diag image RAM
    314,672 B; the clean image at this pin was not built.
- **W18 - the contract's head comment, sorted by where each explanation
  belongs.** The island contract opens with a 102-line comment before
  `version: 1` (src/safety_island_bringup/launch/safety_island.contract.yaml,
  CON below, CON:1-103), and 546 of its 804 lines are comments (DX 1.1): a
  second author inherits an essay, not a model. The comment is a symptom;
  each block explains what the grammar or the checker cannot say. The
  inventory, and where each explanation should live:
  - CON:15-21, why no scheduling platform file is needed: history; move it
    to the island's docs and delete it here.
  - CON:23-28, why the contract replaced the hand-kept CMake `ENTITIES`
    lists (the 2026-09-04 seventh subscription that "cost several days"):
    the island's docs; the rule it stands for, that the declared endpoints
    equal what the code creates, is a code-vs-contract cross-check
    (nano-ros, play_launch; DX 1.6).
  - CON:32-35, endpoint keys are local names and an absolute path "produces
    a malformed `/node//abs/path` endpoint that matches no topic": a checker
    refusal (rlm: refuse a `/` in an endpoint key; DX 1.7).
  - CON:42-44 and CON:156-241, where each number comes from: a per-number
    provenance (`source:`) field in rlm (DX 1.1), or a parameter binding
    like `window-param` for the FDTI and the timer rates (DX 1.8). Until
    then docs/takeover-trace.md section 10 holds the arithmetic, and the
    comment can point there instead of repeating it.
  - CON:76-80, services must be declared or MAX_QUERYABLES under-derives: a
    checker or image-derivation message (nano-ros, play_launch; DX 1.6).
  - CON:242-256, why the intervals are 10 s and 30 s: a judgement this
    repository owns; it stays, shorter.
  - CON:307-318, the two `reaction-unguarded` warnings that are true and
    kept: an in-file acknowledgement the checker reads (play_launch, rlm;
    DX 2.9).
  The rlm and checker rows go to play_launch phase 85 by reference to this
  list; DX 1.1, 1.7, 1.8 and 2.9 are not units there. Gate: every block
  marked stay, move or hand over, with its destination; each moved one
  cited at its new place; the head comment's remaining length stated.

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
  DX: see DX-UX-GAPS 1.2.
  Status (2026-10-10): done on play_launch 0.14.0 (released the same day),
  but for the board round. Island contract and the three L3 compositions:
  `call_mrm` 206 -> 149 (tick 118 + work 31), `within` 149, the link
  `max_transport` 57 -> 81 on the guard subscriber (67.02 x 1.2, phase8-W31
  r01; W14 re-sizes it), `jitter: 18ms` on the handler's `on_timer` (W30's
  ticks up to 14.84 ms late x 1.2) and `jitter: 6ms` on the emergency
  operator's 30 Hz timer (w4r-ticks: 37.34 - 33.00 = 4.34 x 1.2). The
  checker charges the link once on the reaction route and the jitter at
  the sampling hop and the window's notice, so the island topics' totals
  are now: hpc_loss 4934.67 (was 4904.67: 81 + 149 + 33.33 + 6 = 269.33
  on the route), odd_exit comfortable_stop 20475.67 (was 20508.67; WINDOWS
  10230, route 149), odd_exit floor 14683.67; the request ends within
  10,149 ms. The variants still fail only their comfortable-stop rung
  (30795.67 and 30525.67; demo/l3/contracts/README.md). 14/14 CI checks
  as expected; tools/timeline/testdata/explain.txt regenerated and the
  selftest passes (tlcommon now runs the play_launch on PATH; the W6
  source build is 0.12.0, DX gap 2.2). Open: the fresh board round of
  W14 against the new numbers (the board is on the spin-latency
  investigation, W4's open finding), and the paper's camera-ready
  figures (4,904.67 and 20,508.67 in v3) follow this change.
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
  DX: see DX-UX-GAPS 6.6 (the compositions; the rtprio host setup is W21).
  Status (2026-10-11): done on play_launch 0.15.1 (0.14.0 gives the same
  output). The three compositions name package `availability_gate`, exec
  `gate-rt`, `odd_timeout_s` 1.0, and model it as takeover.contract.yaml
  does: `on_timer`, `timer: { rate_hz: 10, jitter: 6ms }`, the raw sample
  and the ODD verdict read-latest (`state: true`, `max_age: 1s`). The 6 ms
  is measured: the gate's largest publish gap under SCHED_FIFO 20, 104.53
  ms (docs/takeover-trace.md section 7, s3; the container's idle 600 s in
  phase8-W24 reached 101.67), 4.53 x 1.2 rounded up. The tick's path keeps
  the 20 ms declared since phase8-W6 (not measured), so odd_exit's
  detection stays 120 ms and no explain row moves: hpc_loss 4934.67,
  odd_exit comfortable_stop 20795.67, floor 14703.67; the variants still
  fail only their comfortable-stop rung (30795.67, 30525.67). The
  `warning[scope-budget]` play_launch 0.14.0 printed on all three
  (island.tor 226 against 250) was stale since W5: the link moved into
  `max_transport`, which 0.14.0 counts in a path's latency. island.tor is
  re-derived to 356 ms (gate sampling 100 + jitter 6 + path 20 + link 81 +
  `call_mrm` 149; the checker's critical path is 350, it adds no jitter to
  a sampling cost) and the warning is gone. Checker gap: a reported fault's
  detection charges the publisher's period and path, not its timer's
  jitter (6 ms short here; no verdict is that close). The island contract
  changed in one comment only (its path-exclusion note is printed again
  since W5, naming `on_timer`); tools/timeline/testdata/explain.txt
  regenerated (line numbers only), selftest OK. CI: main's run of W5
  failed, the 0.13.1 pin refusing `trigger.timer.jitter`
  (`manifest-parse`) on four contracts; the pin and the doctor's minimum
  are now 0.15.1, and `.github/check-contracts.sh` gives 14/14 as
  expected on 0.15.1 and 0.14.0. demo/l3/contracts/README.md's verbatim
  outputs, scratch variants and smallest breaks (19.20 s, 63.1 km/h)
  refreshed.
  Status (2026-10-12, the gate's liveliness): the contracts now state the
  QoS the code runs. The three compositions declared the gate's publisher
  `liveliness: manual_by_topic, lease_duration: 500ms`; the gate
  (availability_gate.cpp:261) publishes `KeepLast(1).reliable()
  .durability_volatile()` with rclcpp's default AUTOMATIC liveliness, and
  takeover.contract.yaml already said `{ depth: 1, durability: volatile }`.
  The compositions now say the same. The handler's subscriber (island
  contract and compositions) also lost its lease: the handler subscribes
  with `nros::QoS(1)` (no liveliness) and checks the 500 ms itself, which
  `max_age: 500ms` + `mechanism: application` already state, and a
  MANUAL_BY_TOPIC request against an AUTOMATIC offer is RxO-incompatible
  under DDS. The lease was not read where the old comment said: nano-ros
  takes only depth/reliability/durability/history from a contract's qos
  (qos_agreement.rs, "the contract has no key for" liveliness); play_launch's
  model did turn it into two `qos_overrides./system/operation_mode/
  availability.subscription.liveliness*` parameters on mrm_handler, but the
  C++ component entry bakes no override table from them, so the image never
  requested it. Checked by derivation, not a board build: `nros sync` +
  `nros ws entity-inventory` (cmake, json, entity and params headers) and
  `nros codegen entry --lang cpp --typed` on the island model before and
  after give identical outputs (NROS_DERIVED_MAX_LIVELINESS 27, MAX_CBS 14);
  the model differs only by the two derived parameters. This used
  island-dma's nano-ros (6ad29e721): the pinned 319715968 refuses the island
  contract (`trigger.timer.jitter` unknown, `nros sync` writes
  system_model.refused), so a board build from main's submodule needs the
  nano-ros bump first. `play_launch check --explain` (0.15.1): no verdict
  or total moves (hpc_loss 4934.67, odd_exit comfortable_stop 20795.67,
  floor 14703.67; island alone floor 14683.67; variants 30795.67 and
  30525.67), only line numbers; README's verbatim outputs and
  tools/timeline/testdata/explain.txt follow (selftest OK);
  `.github/check-contracts.sh` 14/14 as expected.
  Status (2026-10-12, the jitter gap): play_launch PR #18
  (NEWSLabNTU/play_launch, branch `fix/timer-jitter-detection`, not
  released) charges a timer's declared jitter in a reported fault's
  detection and in a scope path's critical path. These contracts are not
  re-pinned and not re-derived; this is what the PR build reads on them
  (the comments that say the checker adds no jitter stay, each with a note
  that points at the PR). L3 compositions: odd_exit detection 120 -> 126
  (`reports every 100.00ms + 6.00ms jitter + 20.00ms`), comfortable_stop
  20795.67 -> 20801.67, floor 14703.67 -> 14709.67; variants 30795.67 ->
  30801.67 and 30525.67 -> 30531.67, still failing only their
  comfortable-stop rung; hpc_loss 4934.67 unchanged. island.tor's critical
  path is 350 -> 356, which is the declared 356, so there is no warning (a
  probe at 300 ms printed 250 + 106 sampling). Island contract alone: its
  totals do not move (odd_exit's gate is external there, detection 100),
  but island.tor's critical path through the handler's tick becomes 218
  (100 + 18 jitter + 100), more than its declared 210: one new
  `warning[scope-budget]`, so the re-pin must re-derive island.tor (to at
  least 218). `.github/check-contracts.sh` with the PR build: 14/14 as
  expected. At the re-pin: README verbatim outputs, smallest breaks,
  tools/timeline/testdata/explain.txt (the island's own table does not
  move) and the paper's odd_exit figures.
- **W7 - on-demand topics.** The contract's 10 Hz `min_rate_hz` on the
  comfortable-stop operator's `clear_velocity_limit` and
  `max_velocity_candidates` tripped `rate-hierarchy-runtime` at start-up
  (2 of the 8 ring entries in W31). Both are published on demand. Either
  drop the rate claim in the contract or adopt the on-demand key the
  play_launch phase adds. Gate: a bring-up whose violation readout has no
  `rate-hierarchy-runtime` entry for these two topics.
  DX: see DX-UX-GAPS 1.5; dropping the claim is cheap and fits W22's sitting.
  Status (2026-10-05): the claim is dropped. `min_rate_hz: 10` left both
  publishers and `rate_hz: 10` left both topics in
  safety_island.contract.yaml, with a comment saying why; `play_launch
  check --explain` (0.13.0) prints byte-identical diagnostics before and
  after (0 errors, 5 warnings), and the CI script still reports every
  verdict as expected. The image's monitor table changes at the next
  board build; the gate (a bring-up readout with no
  `rate-hierarchy-runtime` entry for these two) waits for it.
- **W8 - run-board.sh fails fast on a bad start.** In W31 one act-A
  attempt came up with 66 of 68 composables (`"ok":false`); run-board.sh
  still saw "Startup complete" and the act ran until "FATAL: the vehicle
  did not reach 1.0 m/s" (section 11). Abort, or restart the container,
  when the start record says `"ok":false`. Gate: a forced bad start is
  refused before the act.
  DX: see DX-UX-GAPS 6.4; cheap, fits W22's sitting.
  Status (2026-10-05): implemented in W22's sitting. Step 5 refuses a start
  whose log says "Startup complete with failures" or `"ok":false` and takes
  the existing retry (stop, wait, start again; a second short start ends
  the run before the act). Replayed on the two real logs: w31-r07-aw6668
  "REFUSED: a short start, composable 66/68 loaded", w31-r07 accepted. Gate
  still open: no forced bad start has been run live.
- **W9 - hazard lights reach the simulator from the board.** After W3:
  the board's hazard command carries a stamp the host accepts. Gate: on
  the board, the simulator's hazard-lights status shows ENABLE in act B and
  the encore (the `hazard_lights_on` row is no longer `-`).
  DX: see DX-UX-GAPS 5.4, 6.8.
- **W10 - the Orin container.** The booth machine is an Orin, in
  Yokohama, after submission (branch `orin-arm64`): the
  `sai-l3-autoware` image built for arm64, with the same start checks
  (`nodes 31/31, containers 13/13, composable 68/68`). Gate: the three acts
  pass with the container on the Orin and the island on the board.
  DX: see DX-UX-GAPS 6.9.
- **W11 - the booth UI, built.** W1's design, implemented over W2's re-arm.
  Gate: the three acts triggered from the buttons, back to back without a
  reflash, each followed by its plot, every row PASS.
  DX: see DX-UX-GAPS 6.1, 6.8.
- **W19 - one play_launch version for the doctor, CI and the vendored
  copy.** Three surfaces move independently (DX 2.3): the binary on PATH
  (0.12.0 on this host), the CI pin (`PLAY_LAUNCH_VERSION: "0.13.0"`,
  .github/workflows/check.yml:21) and the copy vendored inside nano-ros
  (`packages/cli/third-party/play_launch`, moved by nano-ros PRs: "nano-ros
  PR 1394 moves the vendored pin to play_launch 92043c82 / rlm v0.1.46",
  P8:368-369). `just l3-check` already reads the pin from check.yml
  (just/l3-demo.just:188); the doctor (justfile:73, .envrc:14,
  scripts/env.sh:21) does not. Make the doctor read the same pin, print the
  three versions, and say which one `just l3-check`, the demo and the image
  build each use. Two binaries that both call themselves 0.12.0 disagree on
  the island contract (DX 2.2; demo/l3/README.md:515-520, trap 10); a
  `--version` that names the grammar is play_launch's, handed to its phase
  85 by reference. W22 raises the minimum by hand first. Gate: a fresh
  shell with the 0.12.0 wheel on PATH gets a doctor line naming the
  required version before any check runs.
- **W20 - reading the board's log without a console.** lpuart0 (the
  console) is unwired and lpuart2 carries the link (DX 4.1). RTT works, but
  needs "Four things this needs, none of which any error message
  mentions": the SEGGER module cloned by hand, `-DZEPHYR_EXTRA_MODULES`, `pyocd rtt` under
  `script` for a TTY, and the `_SEGGER_RTT` address; and the default 1 KiB
  up-buffer wraps before a post-hoc reader attaches
  (docs/board-bringup-triage.md:117-127). One recipe that does the four
  steps, with the 16 KiB buffer in the board conf. Violations are W4 (and
  NR474 D1); this unit is the log. Gate: on a fresh clone, one command
  prints a running board's log.
- **W21 - the runbook, re-validated for the zenoh path.**
  docs/demo-runbook.md:1-7 says the end-to-end run "has NOT been
  re-validated" since 2026-07-31; the path that ran 13 + 9 board acts is
  the `l3-*` recipes and run-board.sh, documented in demo/l3/README.md and
  memory notes. Rewrite the runbook for that path, with what a new machine
  (the Orin, W10) or a presenter needs and today learns by accident:
  - host_ws shadows stock Autoware in a login shell. From a login shell an
    Autoware check parses 163 scopes / 33 nodes / 2 manifests instead of
    169 / 34 / 4, and every MRM hazard reads `hazard-unguarded` (DX 2.8,
    7.4); `just l3-check` and run-board.sh already run under `env -i`
    (just/l3-demo.just:191-192; tools/timeline/run-board.sh:36-38). State
    the rule: run every Autoware check under `env -i`.
  - the host's real-time setup, undocumented today: `gate-rt` uses
    SCHED_FIFO only "when `ulimit -r` allows (0 for this user: needs a
    limits.d rtprio entry)" (P8:448-449), and the container needs
    `--cap-add SYS_NICE --ulimit rtprio=20 --ulimit memlock=-1`
    (P8:546-547; DX 6.6). Write the limits.d line and how to verify it.
  - the host traps: `:1` is a user's desktop, not the demo's VNC
    (demo/l3/README.md:523-524); `ros2 topic echo` without `--no-daemon`
    answers for the wrong RMW (:511-514); Autoware's own setup.bash exports
    the Cyclone RMW (:507-510); a shared DDS domain kills every host node
    with "rcl node's rmw handle is invalid" (docs/demo-runbook.md:156-167);
    a name-based `pkill -f play_launch` hits every project on the box
    (:168-173) (DX 6.10, 7.3).
  - the Cyclone-era `just autoware` / `island` / `demo` path beside the zenoh
    `l3-*` path (DX 6.3): say which is current, retire or label the other.
  Gate: the runbook followed from a clean shell to an act that passes, and
  the validation date in its header.
- **W22 - the cheap fixes.** Each under a day and one change in this
  repository (DX section 9, the SAI rows); one sitting, one commit each.
  - [x] DX 2.1, the doctor's play_launch minimum. `PLAY_LAUNCH_MIN :=
    "0.8.2"` (justfile:73), .envrc:14 (warns only for `0.[0-7].*`) and
    scripts/env.sh:21 (">= 0.8.2") accept the 0.12.0 on PATH, while CI pins
    0.13.0 (.github/workflows/check.yml:21). On the island contract that
    0.12.0 prints "at 'hazards.hpc_loss.entry_speed': unknown key in
    `hazards.<name>` ... Every contract in this file is now UNCHECKED" and
    exits 1, never naming a version. Raise all three to 0.13.0, and make the
    warning name the required version (W19 then reads it from the pin).
    Done: 0.13.0 in justfile, .envrc, scripts/env.sh and the runbook,
    compared with `sort -V`; with the PATH 0.12.0 the doctor prints
    "play_launch 0.12.0 is older than the required 0.13.0" and fails.
  - [x] DX 2.4, CI negative tests by exit code only.
    .github/check-contracts.sh expects exit 1 for six contracts that must
    each fail one rule ("each must fail its comfortable-stop rung and
    nothing else", :28-29) but compares only `$got = $want` (:49); a
    `manifest-parse` failure also exits 1, so a play_launch too old to parse
    the variants reports them "ok". Put the rule id in each EXPECT row (the
    comments at :24-34 already name it) and require `error[<rule>]` in the
    output, or read `--format json`; a parse failure is a FAIL.
    Done: each EXPECT row is `1:<rule>`; 0.13.0 passes 14/14, the PATH
    0.12.0 now FAILs the two variants on `error[manifest-parse]` (the old
    script called them "ok").
  - [x] DX 6.7, the demo lock. tools/timeline/run-board.sh never takes the
    lock; its comment tells the operator to run under "flock
    /tmp/claude-1000005/sai-demo.lock" (run-board.sh:38-39), a path that
    exists only in this machine's agent sandbox (also
    docs/takeover-trace.md:432, 565, 958). Take the lock in the script at
    `${XDG_RUNTIME_DIR:-/tmp}/sai-demo.lock` (or a repo-relative path) and
    drop the sandbox path from the comment and the trace doc.
    Done: run-board.sh takes it (`flock -n` on fd 9, refuses with the
    holder's pid and run id); the sandbox path is gone from the trace doc
    and demo/l3/README.md (:275, :329) too.
  - [x] DX 4.6, four stale documents:
    - docs/board-bringup-triage.md:339-341 "Nothing in this image has
      executed on silicon"; :183 heap `94208` (the board runs at 102,400
      configured); :245 `CONFIG_NROS_MAX_LIVELINESS=32` against 29 tokens
      (the knob derives now, mr_canhubk3_s32k344.conf:169-171);
    - docs/nxp-deployment.md section 10 (:1247-1252): "94208 was chosen
      without a measurement" and "Never executed on silicon. The board is
      blocked on the MCU-Link probe" (13 + 9 board acts have run since);
    - demo/l3/README.md:531-533 lists G5 under "Open" though W24 closed it
      (the entry itself says it brakes), and :60-64 says the host runs
      rmw_zenoh_cpp 0.1.9 beside the image's held 0.1.10: re-check and say
      which side runs which;
    - docs/demo-runbook.md:1-7 (unvalidated since 2026-07-31: until W21,
      say so with a pointer to demo/l3/README.md), :15 names `../nano-ros`
      as the default checkout (scripts/env.sh: the submodule wins), and
      :228-229 repeats G5 as open.
    Done: all four, plus the triage doc's section 5 and the board-build
    comment: gap 3.3 is fixed at nano-ros 3d52070ec (`configdefault`),
    inside the pin f03d9d190. rmw_zenoh_cpp: host and image both run
    0.1.10-1jammy.20260915.210859 (host held since 2026-09-29).
  - [x] DX 3.12, `nros-sdk.lock`. Decision: commit it. nano-ros design 0014
    says the lock is "committed per workspace" and records the resolved
    tool, version, sha256 and provenance
    (third-party/nano-ros/docs/design/0014-nros-setup-toolchain-management.md:283-284),
    and `nros store gc` reads locks back
    (third-party/nano-ros/changelog.d/1262.fix.md). This one pins
    zephyr-sdk 0.16.8, prebuilt, by sha256, the SDK every board image since
    2026-09-10 was built with; untracked it pins nothing for the next clone
    (the Orin, W10), and ignoring it would hide the one record of which SDK
    built the measured images.
    COMMITTED (2026-10-05), after one correction to the premise above: the
    0.16.8 table is not what built the board images, and it is not stale
    either. The 4.4 workspace (the board line) asks for SDK 1.0.1
    (zephyr/SDK_VERSION), which scripts/board-env.sh resolves through
    scripts/zephyr-sdk-tool.sh to the index entry `zephyr-sdk-1-0-1`; the
    W31 build log reads "Found toolchain: zephyr 1.0.1
    (~/.nros/sdk/zephyr-sdk-1-0-1/1.0.1/zephyr-sdk-1.0.1)". The 3.7
    workspace (the native_sim line) asks for 0.16.8, the table the lock
    already had. So the lock was incomplete, not wrong. Fixed with
    `third-party/nano-ros/packages/cli/target/release/nros setup --tool
    zephyr-sdk-1-0-1 --index third-party/nano-ros/nros-sdk-index.toml`
    from this repository's root, which completed the store's 1.0.1 (its
    setup.sh installed the host tools it had skipped) and wrote
    `[tool.zephyr-sdk-1-0-1] version 1.0.1, prebuilt, sha256 ca9bc0ff...`
    (the index's own sha) beside the 0.16.8 table. Two findings for other
    units: (1) the pinned CLI refused to run ("stale CLI: source stamp
    023f6f8f7b1bd676 != d6d84900edf245c5"; it was built 2026-09-29 14:55,
    before the pin moved to f03d9d190), so the lock write ran under
    NROS_SKIP_STALE_CHECK=1; `just setup-cli` is due before the next build
    (DX 3.1, nano-ros phase 478 D1); (2) ~/.nros/workspaces/zephyr/{3.7,4.4}/
    env.sh still name in-checkout SDK paths that do not exist
    (board-env.sh never sources them, nano-ros issue 1254); nano-ros
    scripts/zephyr/setup.sh regenerates them and that is not on the
    board-build path.
  - [x] DX 3.6, the derived liveliness count. The current image's
    `NROS_MAX_LIVELINESS` is recorded as a bare 25
    (docs/boot-through.md:607); the only formula written down, "1 session +
    4 names + 14 pubs + 11 subs + 2 servers + 2 clients + 24 parameter
    services = 58" (mr_canhubk3_s32k344.conf:561-562), is the earlier
    four-node image's with parameter services. Record the current image's
    token inventory beside the 25 and replace the conf comment's formula;
    printing the formula beside each derived knob is nano-ros's (section
    3).
    Done: 1 session + 3 names + 8 pubs + 7 subs + 4 queryables (2 servers
    + 2 TL caches) + 2 clients = 25, from the W31 build's
    entity_inventory.cmake pools (the sum reconstructed; nano-ros prints
    only the 25, phase 478 D3), in boot-through.md and the board conf.
  - [x] DX 7.3, a regression check for `just demo-down`: it must spare a
    process that carries `CYCLONEDDS_URI` but not this checkout's
    `SAI_DEMO_RUN` (the fix of eb82dcf, justfile:918-942, has no test).
    Done: scripts/test-demo-down-spares-bystanders.sh over a new
    `just _sweep-orphans dry`; PASS in 2.7 s, and FAIL when the sweep is
    put back on the CYCLONEDDS_URI key.
  - [x] DX 6.10, `just doctor` checks that an X server listens on the
    display it prints (docs/demo-runbook.md:153-155).
    Done: `xset q`, else the socket; on `:1` "X server: :1 answers", on
    `:57` a WARNING naming the display, doctor still OK.
  - Same sitting, their own units: W7 (drop the two `min_rate_hz` claims)
    and W8 (refuse `"ok":false`).
  Gate: every box ticked with its commit, or moved to a unit with the
  reason.
  Status (2026-10-05): 7 of 8 ticked, one commit each: a239c23 (doctor
  minimum 0.13.0), 78ac685 (CI rule ids, parse failure fails), dc7adf8
  (run-board.sh demo lock), 60dc775 (four stale docs, gap 3.3 fixed at
  nano-ros 3d52070ec), 0bfde92 (liveliness 25 by term), 28b9cb6
  (demo-down bystander test), c07d196 (doctor X server check). Open: DX
  3.12, `nros-sdk.lock` stays untracked because it pins zephyr-sdk 0.16.8
  while the board images were built with the store's 1.0.1 (c45ebf9 has
  the finding and the re-bind command). W8 implemented in the same sitting
  (14146a0), its live gate open; W7 not taken.

### Test / check

- **W12 - the late-join EMERGENCY_STOP, re-checked.** In the encore of
  phase8-W26 a late-joining island ran a 150 ms EMERGENCY_STOP 80 ms after
  INIT -> RUN, 32 s before the act (seen in act A before W27 too). Main
  `88a336f` (W28: INIT ends only when every input is established, not
  merely heard) may have fixed it. Re-check on the current image with the
  island joining after Autoware is up. Gate: repeated late joins with no
  MRM before the act, or the cause if one recurs.
  DX: see DX-UX-GAPS 4.4 (the late join; the ACL re-measurement is W23).
- **W13 - F4 and F5: the unmeasured hops and the handler's in-tick
  work.** F4: the link hop of `kinematic_state`, `operation_mode_state`
  and `control_cmd` (the trace keeps no per-sample take for them), and the
  emergency operator's 30 Hz tick jitter (its ticks are kept one in ten);
  both need trace markers from the nano-ros phase. F5: profile what the
  handler does for 5.4-9.7 ms before its first publish and 11-18 ms before
  the `operate` call (section 10). Gate: each hop with a measured range;
  the in-tick time split by function.
  DX: see DX-UX-GAPS 5.6.
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
  DX: see DX-UX-GAPS 5.8, 6.6.
- **W16 - bad frames on the serial link.** In-run bad frames with no UART
  error and no ring overflow, about one per 80 min of soak at contract
  rates (3 in 250 min), cause open (docs/serial-link.md). Investigate with
  the frame capture image. Gate: the cause, or a capture of enough frames
  to rule causes out.
  DX: see DX-UX-GAPS 5.9.
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
  DX: see DX-UX-GAPS 3.11, 6.5, 7.1, 7.2 (the 19 `build-*` directories and
  179 worktree entries above are 7.2's counts).
- **W23 - the gateway's liveliness ACL, re-measured on the board.** Graph
  discovery is derived off on serial images, but "the link has not been
  re-measured without the ACL on the board" (docs/serial-link.md:463-471);
  phase8-W10 "Open:" ("re-measure the serial link without the gateway ACL
  on the board", P8:509-510). Without it, the island's survival of a full
  Autoware graph rests on the ACL (DX 4.4). Run a tap on the serial link,
  `ros2 node list` and an Autoware restart without the ACL. Gate: the ACL
  retired, or kept with the measurement that requires it.

## 3. Depends on

- **The play_launch phase:** F1 (transport charged on the reaction walk;
  W5), F2 (a timer release-jitter key), F3 (service-edge queueing), and
  the on-demand key (W7). Handed over by reference, not yet units there:
  W18's checker and grammar rows (DX 1.1, 1.7, 1.8, 2.9) and a `--version`
  that names the grammar (W19, DX 2.2).
- **The nano-ros phase:** the violation channel (W4), monitor arming (so
  start-up does not fill the ring before the act), trace markers for the
  F4 hops (W13), and the heap. Asked of its next phase: the formula
  printed beside each derived knob (W22, DX 3.6) and the code-vs-contract
  endpoint cross-check (W18, DX 1.6).

## 4. Order

Violation visibility (W4) and F1 (W5) first; the booth UI (W1, W2, W11)
next; the late-join re-check (W12); hygiene (W17) in the background. The
cheap fixes (W22) any time, in one sitting, the doctor's minimum first: it
fails every fresh shell today. The runbook (W21) before the Orin (W10).

## 5. nano-ros main and the rclcpp:: API (2026-10-11)

Branch `phase9-rclcpp-api` pins nano-ros main `23f8336d9` (was
`319715968`). It carries #1857 (the serial reader, `4332d00275`). #1896
(the spin release grid) was still in the merge queue, so it is NOT in
this pin; re-pin at or after its merge commit.

- **The API (nano-ros phase-483 W1, #1835).** The C++ API left `nros::`
  for `rclcpp::` with no alias. The island's port is a namespace rename
  only: `::nros::X` -> `::rclcpp::X` for `NodeWithTimers`, `NodeHandle`,
  `Publisher`, `QoS`, `Result`, `ErrorCode`, `detail::node_param_*`,
  `bind_service`, `create_service_client_raw`, `ServiceClientStorage`,
  `Clock`, `arm_monitors` and `board::NativeBoard`. The macros
  (`NROS_COMPONENT`, `NROS_SUBSCRIBE`, `NROS_CREATE_WALL_TIMER`,
  `NROS_MAIN`) and the `<nros/...>` header paths are unchanged. `QoS(1)`
  now goes through upstream's implicit `QoS(size_t)`; same profile. W2-W4
  are Rust only. No Kconfig symbol changed between the two pins.
- **The root variable (nano-ros phase-484 W1, RFC-0103 D6).** nano-ros's
  cmake package now refuses to configure while `NANO_ROS_ROOT` is set in
  the ENVIRONMENT; `NROS_REPO_DIR` is the one name. The justfile's
  variable is now `NROS_ROOT`, recipes unexport `NANO_ROS_ROOT` and export
  `NROS_REPO_DIR`, and `scripts/env.sh` stops exporting the old name. A
  direnv shell from before this change still exports it: re-enter the
  directory (direnv reloads on env.sh) before a build.
- **Measured, on `0f59543` + the branch diff.** The branch head's
  contract (`c5d49aa`, `jitter:` on two timers) cannot be resolved by
  `nros sync` at EITHER pin: nano-ros vendors play_launch `bbf9c04`
  (pre-0.13), whose resolver refuses `jitter` ("unknown key in
  `trigger.timer`"). So the images were built from `0f59543` (the commit
  before) with the branch's code, against a baseline of `0f59543` at the
  old pin. Same Kconfig on both board images.

  | image | old pin (`319715968`) | main (`23f8336d9`) |
  | --- | --- | --- |
  | S32K344 FLASH | 649,324 B | 572,016 B |
  | S32K344 RAM | 305,056 B (93.10%) | 305,056 B (93.10%) |
  | S32K344 DTCM / ITCM | 62,496 / 13,136 B | 62,504 / 13,204 B |
  | QEMU trace FLASH / RAM | 627,264 / 2,361,780 B | 549,700 / 2,361,780 B |

  The 77 KB of flash is rodata: the `__NROS_SIZE_*` size-probe arrays
  nano-ros #1765 (`488bfc3b9`) keeps out of linked images. native_sim
  standalone, 30 s: the same markers on both (handler `on_timer` 298,
  `call_mrm` 268, emergency operator ticks 904 / 902, INIT timeout 1).
  QEMU, 40 s with a router: the same host topic list, heap peak 65,960 B
  (66,152 at the old pin). `play_launch check` 14/14, `tlcommon`
  selftest OK, demo-down bystander test PASS.
- **Open, at both pins (not the port).** (1) The contract above needs a
  nano-ros whose play_launch is >= 0.14.0 before any image builds from
  `main`. (2) The native_sim island dies of HEAP EXHAUSTED in
  `ddsrt_malloc` (Cyclone, `dq.builtins`) when it joins a running
  Autoware: 1 MiB and 4 MiB both exhaust, at either pin, so the demo
  cannot run on native_sim. (3) The host `just build` fails to link
  (`nros_cpp_declare_param` undefined: nros-cpp built without
  `param-store`). (4) `nros sync`'s source-metadata probe finds no
  producer for the four nodes.

## 6. Spin latency after the TX fixes (2026-10-12)

The board image on nano-ros `4f91dfd7b` (#1944 play_launch 0.15.1, #1946
the non-blocking serial TX, phase-474 I12), TX ring 4096, encore with the
spin diag (`CONFIG_ISLAND_SPIN_DIAG` + `experiments/spin-latency/*.patch`;
runs kept in `build/timeline/` and `/mnt/mx500/aeon/worktrees/spinlat-logs/`).

| run | spins | >= 2 ms late per 10k | >= 1 ms per 10k | worst |
| --- | ---: | ---: | ---: | ---: |
| `sl-cadence-diag` (I10 + I11, before #1946) | 10,968 | 26.4 | 68.4 | 5.9 ms |
| `sl-rclcpp-diag` (#1946, ring 4096) | 10,121 | 33.6 | 51.4 | 5.1 ms |
| `sl-rclcpp-prio` (+ executor at 3, `e93e258`) | 127,823 | 6.4 | 21.9 | 4.0 ms |

- [x] #1946 on the board: `frames_waited` 0, TX `waits` 0, lock waits at
  link.c:253 / tx.c:660 down to 2-10 us. The late spins stayed.
- [x] Thread priorities (`e93e258`): zenoh-pico's read, flush and lease
  tasks (k_thread 4) ran ahead of a due release with the executor at 5
  (1.7 ms median of a late interval). Registration still runs at 5, below
  the read task (phase8-W10); `src/zephyr_entry/src/spin_priority.c`
  raises the spin thread to 3 on its first spin
  (`CONFIG_ISLAND_SPIN_RAISE`). RX ring high water 1006 of 4096 B, no
  overflow; gate table PASS (total 3573.62 of 4934.67 ms).
- [x] The rest was the per-byte serial ISRs (about 505k calls per act,
  6 us each). nano-ros phase-474 I13-I16, PR #1987 (branch
  `fix/serial-isr-cost`); spin-diag encores, the act segment only (the
  rates of whole runs mislead: `sl-rclcpp-prio` idled 10 min before its
  act, and the same image varies 11-77 late spins per 10k run to run):

  | run | image | act: >= 1 ms late | worst | overruns / bad | ISR CPU |
  | --- | --- | ---: | ---: | --- | ---: |
  | `sl-i13`, `-b` | I13: ISR trim, network.c in ITCM/DTCM | 61, 61 | 6-7 ms | 0 / 0 | 4.46 s |
  | `sl-i14` | I14: LPUART FIFO watermark, RXWATER 2 | 0 | 0.76 ms | 4 / 4 | 0.66 s |
  | `sl-i14w1` | I14, RXWATER 1 | 0 | 0.94 ms | 0 / 0 | 0.85 s |
  | `sl-i16b` | I16: async UART on eDMA | 0 | 0.57 ms | 0 / 0 | 0.04 s |

  Gate PASS in all. I13 alone changed nothing (6.2 us a call with TCM, 6.0
  without; it frees 12.9 KiB of SRAM). I16 first asserted at boot: Zephyr
  4.4.0's TCM linker sections `SUBALIGN(4)` broke the eDMA TCD pool's
  32-byte alignment once I13 moved DTCM; nano-ros backports the upstream
  `ALIGN(4)` fix (`just setup zephyr` applies it).
- [x] The island takes I14 at RXWATER 1 with TCM
  (`CONFIG_NROS_ZENOH_SERIAL_TCM`, `CONFIG_NROS_ZENOH_SERIAL_FIFO_WATERMARK`),
  nano-ros pinned at the #1987 merge `9a0e7ec0f` (zenoh-pico `17b14961`).
  Plain encore `sl-i14-final`: VERDICT PASS, total 3508.51 of 4934.67 ms,
  trace-check PASS. Serial counters read over SWD after the run: 423,204
  bytes and 1447 frames in, 1 overrun, 1 bad frame (CRC, dropped and
  recovered), ring high water 1212 of 4096 B, no ring overflow. `sl-i14w1`
  had 0 / 0; at RXWATER 1 the 4-deep FIFO leaves two characters (about
  170 us) for the ISR to be entered, and one stretch with interrupts masked
  went past it. Not pursued: one frame in an encore costs nothing the gate
  sees. If it recurs, RXWATER 0 (interrupt on the first byte, still a FIFO
  drain per interrupt) or the I16 DMA mode are the next steps.
  `experiments/spin-latency/*.patch` and the spin diag now read zenoh-pico's
  own ISR counters (`CONFIG_NROS_ZENOH_SERIAL_ISR_STATS`, diag builds only).

## 7. A board round on the I14 image (2026-10-12)

Ten acts with `tools/timeline/run-board.sh` on the plain board image of this
branch at `3329eac` (ELF sha256 `924c7abd9bb2c511...`, nano-ros `9a0e7ec0f`,
FIFO watermark and serial TCM on, no spin diag; the 149 / 81 budgets),
under `env -i` + scripts/env.sh, `L3_IMAGE=sai-l3-autoware:1.5.0-w24`. Run
ids `build/timeline/d12-*`; the serial counters (`_z_zephyr_serial_stats`)
were read over SWD after each run's teardown.

| run | act | VERDICT | total (ms) | stored verdicts | overruns / bad |
| --- | --- | --- | ---: | --- | --- |
| `d12-e1` | encore | PASS | 3472.95 of 4934.67 | silence only | 1 / 1 |
| `d12-a1` | a | PASS | (exit route 60.68 of 149) | silence only | 1 / 1 |
| `d12-b1` | b | PASS | 18049.64 of 20475.67 | silence only | 1 / 1 |
| `d12-e2` | encore | PASS | 3291.07 | silence only | 1 / 1 |
| `d12-a2` | a | PASS | (exit route 91.80) | silence only | 1 / 1 |
| `d12-b2` | b | PASS | 14698.75 | silence only | 3 / 3 |
| `d12-e3r` | encore | PASS | 3537.84 | silence only | 1 / 1 |
| `d12-a3r` | a | PASS | (exit route 61.08) | silence only | 1 / 1 |
| `d12-b3s` | b | PASS | 15849.78 | silence only | 1 / 1 |
| `d12-b3r` | b | FAIL | 12997.38 (EMERGENCY_STOP) | silence only | 2 / 2 |

- [x] Nine of ten PASS every row. "silence only" = the record holds the one
  known `silence-runtime /mrm_handler/operation_mode_availability` (W3):
  no release-jitter or timer-overrun verdict in any act run (the 14.4 /
  W4 (c) finding does not recur on this image).
- [x] `d12-b3r` FAIL is host-side: load average 189 at its start
  (unrelated builds); detect 186.06 of 100 (the host gate), and Autoware's
  availability carried `comfortable_stop: false` for one sample 1.8 s into
  the comfortable stop, so the island escalated to EMERGENCY_STOP as the
  ladder says (W15/W16). `d12-e3`, `-a3`, `-b3` never reached the act (the
  gateway step timed out: `fuser` on the tty took over 60 s while a stray
  filesystem scan held the host's /proc busy); rerun as `-e3r`, `-a3r`,
  `-b3r`, and b once more as `-b3s`.
- [x] Terms (`/mnt/mx500/aeon/worktrees/w30-reanalysis/terms.py` over the
  nine, `build/timeline/d12-terms.txt`): `max: link 38.13, wait 88.16,
  spacing 101.50, work 1.04, tor_on 0.27, call 0.04, tor_off 0.68,
  operate 0.49, exit 91.80`; link 19.19-38.13 over 13 edges (W14), tick
  spacing 98.87-101.50 over 1053 ticks, work 0.40-1.04. All inside the
  81 / 118 / 31 terms; nothing re-derived.
- [x] `d12-ab` (encore with the act replaced by readouts, gate (a)/(b)
  shape): 40 s after RUN only the silence; `violations.py overrun 250`:
  `max-latency-runtime` hazard_lights_cmd 250 / 100, mrm_state 250 / 149,
  takeover_request_state 250 / 149, then timer-overrun 7, 1, 1 and
  release-jitter 242715 us; no rate verdict 6 s later (the 9 / 27 floors).
  Serial counters 0 / 0 at the act's start, at 40 s and after the overrun,
  1 / 1 only after teardown: the one bad frame per run is the teardown.
- Open: trace-check FAILs on 7 of the 9 PASS runs on completeness only
  (the 40,960 B buffer fills before the readout: the window opens at the
  arming-time silence verdict, about 9 s after boot); every table edge was
  inside the window. Whether `d12-b2`'s 3 / 3 and `d12-b3r`'s 2 / 2 were in
  the act is not known.

## 8. Correctness and UX first (2026-10-12)

The order for the next sitting: what makes a stated claim wrong or
unverifiable first, then the frictions that cost time on every run. The
booth units (W1, W2, W11, W9, W10) wait until this section is done. Each
unit names its gate; a unit is done when the gate passes on the board
image of main.

### Correctness

- [x] **C1 - charge the timer jitter (play_launch PR #18).** Release
  play_launch with the PR, re-pin CI and the doctor's minimum (W19's
  three surfaces together), raise the island contract's `island.tor` from
  210 to at least 218 ms (its critical path through the handler tick is
  100 + 18 + 100 with the PR), regenerate `tools/timeline/testdata/explain.txt`
  and the README's verbatim outputs. Expected: odd_exit detection 120 ->
  126 ms, comfortable_stop 20,795.67 -> 20,801.67, floor 14,703.67 ->
  14,709.67, the variants 30,801.67 and 30,531.67 (still refused at the
  comfortable rung only), hpc_loss unchanged. Gate:
  `.github/check-contracts.sh` 14/14 with no `warning[scope-budget]`,
  selftest OK; the deck's totals follow.
  Status (2026-10-12): done on play_launch 0.16.0 (PR #18 released as
  828a271f, tag v0.16.0, wheels on the GitHub release and the package
  index). The CI pin, the doctor's `PLAY_LAUNCH_MIN`, .envrc, scripts/env.sh
  and the runbook say 0.16.0; nano-ros PR 2031 moves the vendored copy to
  the same tag (rlm v0.1.56), queued. island.tor is 218 ms: the checker's
  critical path is `/mrm_handler = 218.00ms (100.00ms event-segment +
  118.00ms sampling_cost)`, the period 100 plus the handler timer's 18 ms
  jitter, and 217 draws `warning[scope-budget]`. With 0.16.0 from the
  package index under `env -i`: odd_exit detection 126 (`reports every
  100.00ms + 6.00ms jitter + 20.00ms`), comfortable stop 20,801.67, floor
  14,709.67, the variants 30,801.67 and 30,531.67 (refused at the
  comfortable rung only; floors 24,709.67 and 18,601.67), hpc_loss 4,934.67
  unchanged; the island contract's own totals do not move (its gate is
  external, period only). `.github/check-contracts.sh` 14/14; no contract
  of the island or the demo prints `warning[scope-budget]` (the
  docs/demo-l4 fixture stage2-rungBudget prints its own on
  `island.b1_degrade_ads`, as on 0.15.1). selftest OK on the regenerated
  testdata/explain.txt; demo/l3/contracts/README.md's verbatim outputs and
  scratch variants are 0.16.0's.
- [x] **C2 - trace completeness on every act.** trace-check fails on 7 of
  9 passing runs because the 40,960 B RAM buffer fills before the
  readout. DTCM has about 52 KiB free on the I14 image (75,400 of 128 KiB
  used): move the trace buffer there and size it from the act's marker
  volume, or read it out mid-act; drop or decimate the per-tick markers
  that no table reads. Gate: trace-check PASS on every act of a round
  (encore, a, b) with the same table rows.
  Status (2026-10-12, branch `phase9-c2-trace`): done. Measured over the
  section 7 traces (`d12-*`, `u1-e1`, `u1-e2`, board format): the window
  opens at the arming verdict and spends 29-35 s idle at 579-633 B/s
  (16.9-20.5 KB) before the act, the act runs at 1,140-1,318 B/s
  (5.5-18.3 KB), the tail to the readout at 916-1,312 B/s; extrapolated to
  each readout the window needed encore 28.0-28.9 KB, a 41.6-60.3 KB, b
  44.3-64.4 KB (`d12-e2` 112.9 KB, a readout 92 s after its act). The
  forwarded F4 takes were 40-46 % of the bytes. DTCM alone (55,672 B free)
  cannot hold 64 KB; opening at the act gives up the violation trigger.
  Done: `ram_tracing` relocated to DTCM (`zephyr_code_relocate(FILES
  tracing_backend_ram.c LOCATION DTCM_BSS)`, at 0x20003250) and sized
  53,248 B, and the F4 takes thinned to one in 4 / 1 / 12 (2.5 Hz each;
  provenance `take_keep=4,1,12`); replayed, the worst b needs 45.4 KB.
  `check` is unchanged (`complete` = the last heartbeat emitted is in the
  buffer). Regions, I14 image -> C2 image: RAM 300,624 (91.74 %) ->
  259,656 (79.24 %), DTCM 75,400 (57.53 %) -> 128,656 (98.16 %), ITCM
  14,548 both, FLASH 572,496 -> 572,544. Board round (ELF sha256
  `8d6b39a65ec1a90b...`):
  `SUMMARY c2-encore1 encore: PASS; table 8/8 PASS, total 3465.08 of 4934.67 ms; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66640 of 107008 B`
  (buffer 20,782 of 53,248 B);
  `SUMMARY c2-a1 a: PASS; table 6/6 PASS; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66416 of 107008 B`
  (30,439 B);
  `SUMMARY c2-b2 b: PASS; table 15/15 PASS, total 15950.07 of 20475.67 ms; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66688 of 107008 B`
  (32,907 B, 61.8 % of the buffer). The first b, `c2-b1`, was trace-check
  PASS (32,146 B) with table 14/15: the host-clock dwell row read 9,996.56
  against [10,000, 10,149] because the request-on reached the host 18.4 ms
  after its publish and the request-off 14.1 ms after (island clock
  10,000.91, PASS); not the trace, and `c2-b2` passed every row. Same row
  counts as the d12 round (8, 6, 15). docs/tracing.md section 8, "The
  buffer in DTCM". DTCM is now 2,416 B from full.
- [ ] **C3 - serial errors inside the act.** Every run ends with about one
  overrun and one bad frame; in `d12-ab` they came at teardown, the
  others are unattributed. Snapshot `_z_zephyr_serial_stats` at the act's
  start and end (C6's readout) so a run says which errors fell in the
  act. If any do: RXWATER 0 (an interrupt on the first byte, still a FIFO
  drain), else the I16 eDMA mode (needs `just setup zephyr`'s TCM
  backport). Gate: a round with 0 overruns and 0 bad frames inside every
  act. Supersedes W16.
- [x] **C4 - an assert must not fault the fault report.** The board conf
  has `CONFIG_ASSERT=y` with immediate logging to the shell backend, so an
  assert recurses into a usage fault and the reason is lost (the first
  I16 image, `EDMA_TcdSetTransferConfig`). Make the assert path print once
  (deferred log mode, or `CONFIG_ASSERT_NO_MSG_INFO` with the file and
  line kept) and land in the fatal handler. Gate: a forced assert on the
  board leaves its file and line readable over SWD or the console.
  Status (2026-10-13, branch `phase9-c4-u2`): done. Cause, read off the
  board with the I16 ELF flashed again (stack walk over SWD, the core in
  the UsageFault handler, IPSR 6): in immediate mode `assert_print` ->
  `z_log_vprintk` -> the shell log backend -> `z_shell_lock`, a
  `k_sem_take(K_FOREVER)` on the shell's lock. The assert fired under
  `irq_lock` (dma_mcux_edma.c) with that lock held, so the take had to
  pend, `z_swap_irqlock`'s `CONFIG_SPIN_VALIDATE` assert ("Context
  switching while holding lock!", kswap.h:217) fired, its own message took
  the same path, and the recursion ran the stack out into a usage fault;
  no message reached the console and the fatal handler printed nothing
  useful. A forced assert under the same condition
  (`CONFIG_ISLAND_DEBUG_FORCE_ASSERT_LOCKED`: the shell's lock taken, then
  `irq_lock`, then `__ASSERT`) reproduced it exactly (the same recursing
  frames, a usage fault frame under the fatal handler, no record); without the shell's lock held
  (plain thread, `irq_lock` only, or a timer ISR) the immediate image
  landed in the fatal handler cleanly, which is why it bit only at boot.
  Fix: `CONFIG_LOG_MODE_DEFERRED=y` in the board conf (the caller only
  enqueues; the fatal handler's `LOG_PANIC()` puts the shell in polled
  panic mode and flushes), plus `CONFIG_ISLAND_ASSERT_RECORD`
  (src/zephyr_entry/src/assert_record.c, default y with `CONFIG_ASSERT`):
  an `assert_post_action()` override writes the first assert's file,
  line, uptime and context into `island_assert_record` and then
  `k_panic()`s as Zephyr's does; a second assert while handling it is
  recorded as `nested` and halts there. readout.py reads the record in
  every act's halted read (assert.bin; assert.txt only when set) and
  `--assert-only` reads it alone; run_summary.py appends `; ASSERT
  <file>:<line>` when assert.txt is there. Board, the same forced assert
  on the deferred image: `readout: ASSERT
  CMAKE_SOURCE_DIR/src/assert_record.c:86 at uptime 3001 ms (thread
  context); failing asserts seen: 1` (line 86 is the `__ASSERT`), the core
  in `arch_system_halt` from `k_sys_fatal_error_handler` via the SVC
  (IPSR 11), CFSR 0. Cost against the C2 image: RAM 259,656 -> 263,176
  (+3,520: the log thread's 2,048 B stack and the 1,024 B log buffer),
  DTCM 128,656 -> 128,688 (+32, the record; 2,384 B left), FLASH
  572,544 -> 576,728 (+4,184). The normal image (ELF sha256
  `9475bca518b14817...`), flashed back:
  `SUMMARY c4-encore1 encore: PASS; table 8/8 PASS, total 3440.93 of 4934.67 ms; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66640 of 107008 B`.
- [x] **C5 - contract QoS reaches the image.** play_launch lowers contract
  QoS into `qos_overrides.*` parameters, but nano-ros's C++ component
  entry bakes no override table from them (the generated main has no
  `set_qos_overrides`), so a contract QoS that differs from the code's is
  silently not applied. File it in nano-ros and fix it there, with a
  test that a contract-only QoS change changes the baked table. Gate: an
  island build whose entry carries the contract's overrides, verified in
  the generated source.
  Status (2026-10-13, branch `phase9-c5-qos`): done. The gap as found: the
  C++ pack rendered the override table only for a `configure`-shape node,
  and the island's three components are `rclcpp`-shape, so they got a
  3-argument `NodeHandle` with no table (nano-ros issue 1854). Fixed in
  nano-ros PR #2068: an rclcpp-shape component's table rides on its
  `NodeHandle` and is installed before the constructor creates its
  entities, with a test that a contract-only liveliness line changes the
  baked table. Re-pinning to it broke the board link: DTCM overflowed by
  22,608 B. Measured, not guessed: the whole growth is one symbol,
  `rclcpp::Node::GlobalStorageHolder<0>::storage` (52,056 -> 77,048 B),
  and `-Zprint-type-sizes` on the island's own nros-cpp build puts 24,744
  B of the 24,992 B in nano-ros 1812's carved parameter-service home
  (4 x 3,596 B of empty service sets, 2 x 4,444 B of request/reply
  buffers, 596 B of event publisher, the rest of the state). The island
  holds a 22-slot store (its contract declares parameters) and serves no
  parameter services (`CONFIG_NROS_CAPABILITY_PARAM_SERVICES` off), and
  1812 reserved the services whenever a store is carved. Fixed in nano-ros
  PR #2077 (issue 1856): a build that states the services off carves the
  store's state alone, `ParamHome` 24,744 -> 1,472 B; an image with the
  services keeps 1812's full home. The same PR fixes issue 1855: the
  resolver writes a contract's `deadline:` / `lease_duration:` overrides
  in nanoseconds (rclcpp's unit) and the lowering read milliseconds, so a
  500 ms lease would have baked as 500,000,000 ms; the lowering now reads
  nanoseconds and bakes milliseconds (tests: a 500 ms lease and a 4.3 s
  deadline, end to end through the resolver). Pinned to nano-ros
  `43fc1c2f7` (#2077's merge, which contains #2068); the phase-492 C API
  renames and the three board knobs moved into
  `src/zephyr_entry/system.toml` `[image.zephyr] env` came with the pin.
  The island's generated entry carries no override table, and that is the
  right answer: its contract states no deadline, liveliness or lease
  (`system_model.yaml` has no `qos_overrides.*` parameter) and its
  capacity QoS agrees with the code (check-contracts 14/14), so the gate
  is held by nano-ros's tests rather than by an island row. Image against
  C4: FLASH 576,728 -> 581,688 (+4,960), RAM 263,176 (unchanged), DTCM
  128,688 -> 130,408 of 131,072 (+1,720: the store's state, now carved
  instead of on the heap; 664 B left), ITCM 14,760. Explain totals
  unchanged (hpc_loss 4934.67, odd_exit comfortable_stop 20801.67, floor
  14709.67, variants 30801.67 / 30531.67); selftest OK. Board, this image
  (ELF sha256 `df1bf38a1090bb46...`):
  `SUMMARY c5-encore1 encore: PASS; load 24.44 at act; table 8/8 PASS, total 3504.30 of 4934.67 ms; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66184 of 107008 B`.
- [x] **C6 - the host under load (was W15).** The tenth run of section 7
  (`d12-b3r`, load 189 from unrelated builds) escalated because
  Autoware withdrew comfortable-stop availability for one sample.
  run-board.sh takes the demo lock but not a load ceiling: refuse to start
  an act above a stated 1-min load (or wait for it), print the load in
  the run record, and keep the island's correct escalation as the
  expected outcome under overload. Gate: a round run with the ceiling,
  no host-side escalation; a forced overload refused before the act.
  Status (2026-10-13, branch `phase9-c6-u5`): done. run-board.sh reads the
  1-min load in its preflight (before flashing) and again right before the
  act (after the settle); above `RB_LOAD_MAX` it waits up to
  `RB_LOAD_WAIT` s (default 180) and then refuses with one line and exit 3
  (at the act: torn down first). Default ceiling 35: the load the
  section-9/10 rounds of docs/takeover-trace.md kept by hand on this
  20-thread host; the C2 and C4 runs started at 13-19, section 7's
  passing acts at 15-45 (and `d12-a2` / `d12-b2` at 245 / 78, the latter
  with 3 / 3 serial errors), `d12-b3r` escalated at 189. island.trace.meta
  keeps `loadavg_start`, `loadavg_act` (new) and `loadavg_end`;
  run_summary.py prints `load <1-min> at act` after the verdict. The
  escalation is not masked: a run under the ceiling that escalates still
  reads FAIL. Forced, before flashing (`RB_LOAD_MAX=0.1 RB_LOAD_WAIT=5`,
  `u5-load`): `run-board: REFUSED host load: 1-min load 15.46 above
  RB_LOAD_MAX=0.1 before flashing, still after 5 s (RB_LOAD_WAIT);
  busiest: anydesk 106.2%,xrdp 100.0%,xrdp 100.0%`, exit 3. Forced at the act (`c6-overload`,
  `RB_LOAD_MAX=25 RB_LOAD_WAIT=10`, 60 niced busy loops started once the
  board was flashed and joined): `1-min load 41.90 above 25 at the act;
  waiting (up to 10 s)`, then `run-board: REFUSED host load: 1-min load
  48.64 above RB_LOAD_MAX=25 at the act, still after 10 s (RB_LOAD_WAIT);
  busiest: rustc 505.3%,xrdp 94.7%,anydesk 89.5%`, torn down, exit 3, no
  act. A real wait: `u5-void` started at 44.31 and flashed after the load
  fell to 34.12. On the C4 image (ELF sha256 `9475bca518b14817...`, no
  firmware change since):
  `SUMMARY c6-encore2 encore: PASS; load 24.65 at act; table 8/8 PASS, total 3518.56 of 4934.67 ms; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0 (overruns/bad frames); heap peak 66640 of 107008 B`
  (and `c6-encore1`, before the pre-act probe check: PASS, load 14.31 at
  act, total 3482.34). Not run here: a and b with the ceiling; the final
  board round (section 8, Order) runs them.
- [ ] **C7 - the budgets from the current image (was W14).** tick 118 and
  work 31 ms were set from the pre-I14 image; the I14 runs read tick
  spacing 98.87-101.50 and work 0.40-1.04 ms. Re-derive with max + 20 %
  over a full round of the current image, keep the margin rule, and state
  which image each term came from. Gate: the contract's numbers cite the
  current image's runs; check-contracts 14/14.

### UX frictions

- [x] **U1 - every run records its own evidence.** The serial counters,
  the boot record (heap and arena at FirstSpin and at the dump) and the
  violation ring are read by hand today. tools/timeline/readout.py
  reads all three in its halted read at the end of each act, into
  `serial.txt` and `bootrec.txt` beside `violations.txt`, and
  run-board.sh prints one summary line (verdict, total, stored verdicts,
  overruns / bad frames, heap peak). Enables C3.
  Status (2026-10-12): readout.py reads `_z_zephyr_serial_stats` and
  `NROS_BOOT_REPORT` in its halted read (serial.txt, bootrec.txt decoded by
  the pinned read-boot-report.py); `--serial-only` snapshots the counters
  without a halt just before the act (run-board.sh step 7), so serial.txt
  says how many overruns and bad frames fell inside the act;
  tools/timeline/run_summary.py prints one SUMMARY line per run (also
  summary.txt). On the board, encore `u1-e2` (image rebuilt at 190890d):
  `SUMMARY u1-e2 encore: PASS; table 8/8 PASS, total 3529.61 of 4934.67
  ms; trace-check PASS; stored 1 (silence-runtime x1); serial in act 0/0
  (overruns/bad frames); heap peak 66640 of 107008 B`. Found on the way:
  `u1-e1` ran with the probe refused ("the model is STALE ... run `just
  sync`") and still printed VERDICT PASS with an empty table; U5 refuses
  that.
- [x] **U2 - `just board-build` exits 0 on a good image.** It exits 1 from
  the post-link `ram_report` (`size_report` fails), so every caller has to
  know the ELF is fine. Fix the report or make `board-size` advisory, and
  keep a real link failure fatal. Gate: a clean build exits 0; a forced
  link error exits non-zero.
  Status (2026-10-13, branch `phase9-c4-u2`): done. Two causes, neither
  the ELF. (1) The exit 1 was ours: board-i14-final.log ends in `failed
  printing to stdout: Broken pipe` from the nros CLI, inside board-size's
  `source scripts/board-env.sh`. scripts/zephyr-sdk-tool.sh piped `nros
  setup --list` into an awk that exited on the first match; under
  pipefail, when awk was gone before nros wrote its last 15 lines, nros
  panicked on EPIPE, set -e exited 1 and board-env.sh returned 1 with
  nothing printed. 2 failures in 200 runs of the script before, 0 in 400
  after: it now reads the whole list, then matches; board-env.sh names the
  failure if it ever recurs. (2) `size_report` fails on every build with
  `ModuleNotFoundError: No module named 'anytree'` (the Zephyr workspace
  venv lacks it; requirements-base.txt lists it, the nros provisioning
  installs a subset); `| tail -20` without pipefail hid it, so it never
  set the exit status, only scrolled a traceback (the "FAILED" in
  board-u1.log and board-c2.log). board-size now links the image first,
  fatally, then runs rom_report and ram_report as advisory: a failure
  prints one line (`board-size: ram_report failed (advisory, the image is
  fine): ModuleNotFoundError: ...`) and the log path. Gate: a clean
  `just board-build` exits 0 (all nine clean builds on this branch); with
  a temporary call to an undefined `island_u2_forced_undefined()` inside
  `assert_post_action` the link stops (`undefined reference to
  'island_u2_forced_undefined'`) and `just board-build` exits 1. (The same
  call in an unreferenced function linked: `--gc-sections` drops it.)
  Not done here: adding `anytree` to the venv, a nano-ros provisioning
  matter.
- [x] **U3 - the spin-latency tools in the tree.** `build-diag.sh`,
  `actseg.py`, `run-encore-rclcpp.sh` and the `ienv.sh` pattern live in a
  scratch directory. Move them under `tools/timeline/` (or `experiments/
  spin-latency/`) with a `just` recipe for a diag build and an act-segment
  count, so the B2 figure is reproducible from the repo. Gate: the B2
  numbers regenerate from a clean checkout.
  Status (2026-10-13, branch `phase9-u3-u4`): done. The act-segment count
  is tools/timeline/actseg.py (`just diag-actseg <run>...`, run dirs or ids
  under build/timeline; `--survival` prints the per-ms curve the figure
  plots), the driver tools/timeline/run-diag.sh (`just diag-run [a|b|encore]
  <id>`: run-board.sh's own default act inside RB_ACT, `spin_diag.py read`
  just before and just after it, the diag ELF by default), the build
  experiments/spin-latency/build-diag.sh (`just board-build-diag
  [CONFIG_X=v ...]`: both patches applied, built into build-board-diag with
  `CONFIG_ISLAND_SPIN_DIAG` and `CONFIG_NROS_ZENOH_SERIAL_ISR_STATS` as -D
  through board-build's new `ISLAND_BOARD_KCONFIG`, the board conf not
  edited; an EXIT trap reverts both patches; a tree that still carries one
  is refused with the `git apply -R` to run). Beside the patches:
  late_records.py, swd_where.py, swd_stackwalk.py (addr2line from the SDK,
  no host path: spin_diag.py's lookup), and scripts/ienv.sh for the
  `env -i` runner; experiments/spin-latency/README.md documents them.
  Gate, over the island-rclcpp run dirs (read only): `sl-i13` 61 spins
  >= 1 ms late of 5,779 act spins (35 >= 2 ms, 105.6 / 60.6 per 10k, worst
  bin 6 ms, ISR 6.21 us a call, 4.46 s), `sl-i14w1` 0 of 6,019 (worst bin
  0, 2.94 us, 0.85 s): the scratch actseg.py's numbers and section 6's.
  `just board-build-diag` built on the first pass (FLASH 578,888, RAM
  273,184, DTCM 128,696, ITCM 16,452 B; `island_spin_diag` and
  `_z_zephyr_serial_isr_cycles` in the ELF; build-board untouched) and left
  both submodules clean; with a stub `just`, a failed build and a SIGINT to the
  process group mid-build each reverted both patches. Found on the way: the
  scratch build-diag.sh took nano-ros from an inherited `NROS_REPO_DIR`, so
  run from a shell whose direnv names another checkout it patched THAT
  checkout; the tree's script uses its own submodule unless the recipe
  passes the justfile's root. Not run here: a diag encore on the board.
- [x] **U4 - a stale nros CLI is refused, not used.** Main moved its
  nano-ros pin; a worktree whose `packages/cli/target/release/nros` was
  built from another commit still runs it (DX 3.1). The doctor compares
  the CLI's build commit with the pinned submodule and says which
  `just setup-cli` to run. Gate: a deliberately stale CLI fails the
  doctor with that line.
  Status (2026-10-13, branch `phase9-u3-u4`): done.
  scripts/check-nros-fresh.sh, run by `just doctor`: (1) third-party/nano-ros
  at the island's pin; (2) nano-ros's play_launch and zenoh-pico submodules
  at the commits nano-ros records (a non-recursive `git submodule update`
  leaves them behind, the 2026-10-12 `--locked` failure); (3) the CLI the
  recipes resolve is `<root>/packages/cli/target/release/nros`, also after
  sourcing activate.sh as `just sync` does, and `nros source-stamp` says it
  was built from the sources now checked out (nros reports no build commit,
  `nros --version` is `nros 0.5.0`; the stamp is nano-ros's content hash of
  the CLI sources and the play_launch pin, embedded at build time, issue
  0363); (4) nros-launch-resolve through nano-ros's own
  check-launch-resolve-fresh.sh. Each finding names its command (`git
  submodule update third-party/nano-ros`, `git -C third-party/nano-ros
  submodule update --init packages/cli/third-party/play_launch
  packages/rmw/zenoh/zpico-sys/zenoh-pico`, `(cd third-party/nano-ros &&
  just setup-cli)`, `... just setup-launch-resolve`); not `--recursive`,
  which would clone PX4, NuttX and QEMU. A PATH `nros` that is not the
  checkout's and modified tracked files in those trees (a leftover diag
  patch is named) are warnings. Gate, in the worktree, each forced and
  restored: zenoh-pico at HEAD~1 -> `STALE: .../zenoh-pico is at
  e308088583f2, nano-ros pins 17b1496171b4 -- run: ...`; play_launch at
  HEAD~1 -> that line plus the CLI (`built from b5505cd9bf7afb77, sources
  are now dc5efe80e691c3ae`) and the resolver (`built from play_launch
  d23720c7...`, tree at `bb16802e...`); a comment appended to a CLI source
  -> `STALE: nros CLI was built from other sources ...`; one in a resolver
  source -> the resolver line; nano-ros at HEAD~1 -> `STALE:
  third-party/nano-ros is at cdbb9a85b7c1, this commit pins 9a0e7ec0f824 --
  run: git submodule update third-party/nano-ros`. Restored, `doctor: OK`.
  Found on the way: nano-ros's resolver stamp sorts its file list in the
  caller's locale, so a stamp written under C.UTF-8 reads STALE under
  en_US.UTF-8; the check accepts a match under the caller's locale or C
  (collation only reorders the same files; an edit misses under every
  locale). main's own checkout, read only: `STALE: nros CLI was built from
  other sources than third-party/nano-ros now holds` (built from
  514def1aa07b45b9, the pin's sources are b5505cd9bf7afb77), the DX 3.1
  case.
- [x] **U5 - a run that cannot start says why, fast.** The gateway step
  timed out at 60 s when `fuser` crawled under a stray filesystem walk;
  the run left an empty directory. Preflight in run-board.sh: probe held,
  container state, load (C6), and a bounded `fuser`; on failure, a reason
  in `run.log` and a non-zero exit before flashing. Also refuse to call a
  run PASS when the probe or the gate did not start (`u1-e1`: the probe
  refused a stale model, the table was empty, the scenario still printed
  VERDICT PASS), and run the model's staleness check before flashing.
  Gate: each preflight failure, forced once, produces its reason.
  Status (2026-10-13, branch `phase9-c6-u5`): done. run-board.sh writes
  its own `run.log` (unless the caller already redirects into it) and runs
  a preflight after the demo lock and before flashing; each failure is one
  `run-board: REFUSED <reason>` line (also `refused.txt`), a `SUMMARY <id>
  <act>: REFUSED <reason>` line, exit 3. Forced once each (encore, the
  board idle):
  stale model (a comment appended to the contract, restored), `u5-stale`:
  `REFUSED timeline: the model is STALE against
  launch/safety_island.contract.yaml -- run \`just sync\`` (the check is
  tlcommon.load_model, the probe's own);
  a second container (`docker run --name sai-l3-u5fake ... sleep`),
  `u5-container`: `REFUSED container(s) running: sai-l3-u5fake -- another
  act or a leftover; \`docker stop sai-l3-u5fake\` if nothing uses it`;
  a held probe (`pyocd gdbserver -t s32k344` in the background),
  `u5-probe`: `REFUSED the probe is in use by another process: 409350
  timeout 60 pyocd gdbserver -t s32k344 --port 3399 (+1 more)` (the
  run's own ancestors are excluded, so a shell whose command line names
  pyocd does not refuse itself);
  a slow fuser (`FUSER_TIMEOUT=0.001`), `u5-fuser`: `REFUSED fuser on
  /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0 took over
  0.001 s (host /proc busy: a filesystem walk?)`; just l3-peer and
  board-peer bound their own fuser the same way (`l3-peer: fuser on ...
  took over 0.001 s ... -- not starting`, exit 1), and run-board.sh stops
  waiting for the gateway as soon as l3-peer exits, with its last line;
  a missing overlay (`RB_HOST_WS=/nonexistent/l3-host-ws/install`),
  `u5-overlay`: `REFUSED no host overlay:
  /nonexistent/l3-host-ws/install/setup.bash missing -- run \`just
  l3-host-ws\``;
  the load ceiling: C6 above.
  After the board is up: a probe that exits before the act (a stand-in
  RB_PROBE printing the u1-e1 STALE line), `u5-noprobe`: `REFUSED the
  probe exited before the act: timeline: the model is STALE against ...`,
  torn down, no act, exit 3. A probe that dies 5 s into the act
  (`u5-void2`): the scenario's own act output still says `VERDICT: PASS`,
  but run-board.sh prints `VERDICT: VOID the probe exited before the act
  ended; probe.jsonl missing or empty; timeline: the model is STALE
  against ... (the scenario's own verdict is not evidence without them)`,
  `(the scenario said PASS)`, keeps `void.txt`, exits 4, and
  `SUMMARY u5-void2 encore: VOID (the probe exited before the act ended;
  probe.jsonl missing or empty; timeline: ...); load 18.98 at act; table
  0/7 PASS, total - of 4934.67 ms; ...`. The same holds for the gate
  (gate.jsonl, gate.stdout). The encore: C6's `c6-encore2`. Not forced:
  `pyocd list` without a probe (the MCU-Link stayed plugged in).
- [ ] **U6 - one priority story.** `CONFIG_ISLAND_SPIN_RAISE` showed no
  clear gain over the act (section 6); the I14 watermark removed the late
  spins. Measure one round without it on the I14 image; keep it only if
  the round shows a difference, otherwise remove it and its comment.

### Order

C1 (small, unblocks the deck), U1 (makes C3 and C2 measurable), C3, C2,
C4, U2, U3, C6 with U5, U4, C5 (cross-repo), C7 and U6 on the last board
round. One board round at the end re-runs encore, a and b on main's
image and feeds C3, C2, C7 and U6 together.
