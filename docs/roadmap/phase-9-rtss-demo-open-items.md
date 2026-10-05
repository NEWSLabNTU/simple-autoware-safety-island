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
- **W7 - on-demand topics.** The contract's 10 Hz `min_rate_hz` on the
  comfortable-stop operator's `clear_velocity_limit` and
  `max_velocity_candidates` tripped `rate-hierarchy-runtime` at start-up
  (2 of the 8 ring entries in W31). Both are published on demand. Either
  drop the rate claim in the contract or adopt the on-demand key the
  play_launch phase adds. Gate: a bring-up whose violation readout has no
  `rate-hierarchy-runtime` entry for these two topics.
  DX: see DX-UX-GAPS 1.5; dropping the claim is cheap and fits W22's sitting.
- **W8 - run-board.sh fails fast on a bad start.** In W31 one act-A
  attempt came up with 66 of 68 composables (`"ok":false`); run-board.sh
  still saw "Startup complete" and the act ran until "FATAL: the vehicle
  did not reach 1.0 m/s" (section 11). Abort, or restart the container,
  when the start record says `"ok":false`. Gate: a forced bad start is
  refused before the act.
  DX: see DX-UX-GAPS 6.4; cheap, fits W22's sitting.
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
  - [ ] DX 2.4, CI negative tests by exit code only.
    .github/check-contracts.sh expects exit 1 for six contracts that must
    each fail one rule ("each must fail its comfortable-stop rung and
    nothing else", :28-29) but compares only `$got = $want` (:49); a
    `manifest-parse` failure also exits 1, so a play_launch too old to parse
    the variants reports them "ok". Put the rule id in each EXPECT row (the
    comments at :24-34 already name it) and require `error[<rule>]` in the
    output, or read `--format json`; a parse failure is a FAIL.
  - [ ] DX 6.7, the demo lock. tools/timeline/run-board.sh never takes the
    lock; its comment tells the operator to run under "flock
    /tmp/claude-1000005/sai-demo.lock" (run-board.sh:38-39), a path that
    exists only in this machine's agent sandbox (also
    docs/takeover-trace.md:432, 565, 958). Take the lock in the script at
    `${XDG_RUNTIME_DIR:-/tmp}/sai-demo.lock` (or a repo-relative path) and
    drop the sandbox path from the comment and the trace doc.
  - [ ] DX 4.6, four stale documents:
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
  - [ ] DX 3.12, `nros-sdk.lock`. Decision: commit it. nano-ros design 0014
    says the lock is "committed per workspace" and records the resolved
    tool, version, sha256 and provenance
    (third-party/nano-ros/docs/design/0014-nros-setup-toolchain-management.md:283-284),
    and `nros store gc` reads locks back
    (third-party/nano-ros/changelog.d/1262.fix.md). This one pins
    zephyr-sdk 0.16.8, prebuilt, by sha256, the SDK every board image since
    2026-09-10 was built with; untracked it pins nothing for the next clone
    (the Orin, W10), and ignoring it would hide the one record of which SDK
    built the measured images.
  - [ ] DX 3.6, the derived liveliness count. The current image's
    `NROS_MAX_LIVELINESS` is recorded as a bare 25
    (docs/boot-through.md:607); the only formula written down, "1 session +
    4 names + 14 pubs + 11 subs + 2 servers + 2 clients + 24 parameter
    services = 58" (mr_canhubk3_s32k344.conf:561-562), is the earlier
    four-node image's with parameter services. Record the current image's
    token inventory beside the 25 and replace the conf comment's formula;
    printing the formula beside each derived knob is nano-ros's (section
    3).
  - [ ] DX 7.3, a regression check for `just demo-down`: it must spare a
    process that carries `CYCLONEDDS_URI` but not this checkout's
    `SAI_DEMO_RUN` (the fix of eb82dcf, justfile:918-942, has no test).
  - [ ] DX 6.10, `just doctor` checks that an X server listens on the
    display it prints (docs/demo-runbook.md:153-155).
  - Same sitting, their own units: W7 (drop the two `min_rate_hz` claims)
    and W8 (refuse `"ok":false`).
  Gate: every box ticked with its commit, or moved to a unit with the
  reason.

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
