# Phase 5 - the island's units of the contract-chain program

**Goal:** the island runs on the S32K344 with its four nodes on derived
priorities, its entity counts reconciled against its own code, and every
number in `docs/nxp-deployment.md` traceable to a gate.

**Status (2026-09-21): planned, nothing started.** The program is nano-ros
phase-464 (`docs/roadmap/phase-464-contract-chain-program.md` there), which
sequences nano-ros phases 457, 459, 460, 461, 462, 463, play_launch phase 78
and ros-launch-manifest design issue #52 into milestones. This document holds
only the units that are edits to THIS repository, so that a session working
here can claim one without reading the upstream plans first.

---

## 1. Why the island has units at all

Every upstream wave ends in a number measured on this tree: the projection
that the two 30 Hz nodes rank above the two 10 Hz nodes, the census that
names the seventh subscription, the inbox table that makes the board link.
The upstream phase proves the mechanism on a fixture; the island unit is
where the mechanism meets an Autoware subsystem, a Zephyr board and a demo
with a verdict. They are separate units because they need a pin bump each,
and a pin bump is its own PR.

## 2. The protocol here

- A unit is `island-Wk`. The claim is a branch named `island-Wk` and a draft
  PR opened before the first substantive commit; nano-ros's `just claim`
  does not reach this repository.
- Each unit begins with a submodule bump (forward only, one commit, the
  range and the reason in the message) and ends with the demo verdict line
  and, where the board is involved, the region report, both pasted into
  `docs/nxp-deployment.md`.
- The status line under each unit is the only thing updated by hand:
  `Status: not started | claimed <date> | PR #N | landed <commit>`.

## 3. The units

### island-W1 - the island declares its callback groups, and the derivation places them

Depends on: nano-ros phase-459-W2 and phase-459-W4 (a cmake image reaches the
tier derivation; priorities allocated from the board's plan).

What it does: one `CALLBACK_GROUPS` keyword per component in the four
`nano_ros_add_node` calls (the registration already accepts it); no
`[tiers.*]` in `system.toml`, so the derivation runs; the two 30 Hz nodes
(`mrm_emergency_stop_operator`, `stop_mode_operator`) come out on one tier
above the two 10 Hz nodes (`mrm_handler`, `mrm_comfortable_stop_operator`),
at the priorities the board's plan allocates below the transport band
(projected 5 and 6 on the MR-CANHUBK344 Kconfig; the earlier projection of
0 and 1 predates the plan).

Gate: `just zephyr-build` shows `run_tiers` in the generated entry with two
derived tiers; `just demo-*` reaches `VERDICT: PASS`; the thread listing on
native_sim shows the two tiers as separate threads; `docs/nxp-deployment.md`
section 7 is rewritten from "the contract sizes the image; it does not
schedule it" to what is measured.

Owns: `src/autoware_*/CMakeLists.txt` (four files), `src/safety_island_bringup/system.toml`,
`docs/nxp-deployment.md` section 7, `third-party/nano-ros` (the pin).

Status: not started.

### island-W2 - the census is a configure gate

Depends on: nano-ros phase-463-W4 (the census runs at RTOS configure and goes
stale by content), phase-463-W6 (retire the max; flip the island).

What it does: `just sync` or `just build` produces the native census beside
the model; `just zephyr-build` and `just board-build` refuse a stale or
absent census; the contract and the code agree on every endpoint (the
seventh subscription of 2026-09-04 would now be a named verdict); the
`NROS_EXECUTOR_MAX_CBS=32` export the native build carries is deleted,
because the census makes the exact count safe.

Gate: an intentional omission in a scratch copy of the contract is refused
at configure with the endpoint named; the pristine tree configures.

Owns: `justfile` (the sync/build/zephyr-build/board-build recipes),
`src/native_sim_entry/CMakeLists.txt`, `src/zephyr_entry/CMakeLists.txt`,
`third-party/nano-ros` (the pin).

Status: not started.

### island-W3 - the board image links, and the map says why

Depends on: nano-ros phase-461-W5 (the parameter family's own inbox at depth
1; user services and actions keep theirs).

What it does: the pin bump alone should take the image from
`region 'RAM' overflowed by 56848 bytes` to a link; the projected figure is
298,552 of 327,680 B (91.1%), with the inbox tables at 32,088 B instead of
115,128. `docs/nxp-deployment.md` sections 5 and 8 are rewritten from the
new map. If the projection is wrong, the fallback is phase-461-W6: the
store-only parameter capability in `system.toml` (`features` without the
services), projected 273,496 B, with `ros2 param` stated as unavailable.

Gate: `just board-build` links; the region report and the seventeen largest
symbols pasted into the report; `just check-knob-delivery` green.

Owns: `src/zephyr_entry/boards/mr_canhubk3_s32k344.conf`,
`src/safety_island_bringup/system.toml` (only if the fallback is taken),
`docs/nxp-deployment.md` sections 5 and 8, `third-party/nano-ros` (the pin).

Status: not started.

### island-W4 - first execution on silicon

Depends on: island-W3; the MCU-Link probe (hardware; phase 3 records the
state of the probe).

What it does: flash, boot, join the zenoh router over serial, run the demo
against the board instead of native_sim, read `nros_zephyr_heap_peak()`
once at the end of a demo and once after an hour idle, and replace
`CONFIG_NROS_ZEPHYR_HEAP_SIZE=94208` with the measured figure plus the
stated margin (nano-ros phase-460-W5 gates the knob against it).

Gate: the verdict line from a run whose island half is the board; the
heap high-water figure in the board `.conf` with its provenance; the ITCM
boot copy verified by a symbol read on the running target, which is the
one thing the linker could not check.

Owns: `src/zephyr_entry/boards/mr_canhubk3_s32k344.conf`, `docs/board-facts.md`,
`docs/nxp-deployment.md` sections 6 and 10, `docs/demo-runbook.md`.

Status: not started.

## 4. Order

W3 has no dependency on W1 or W2 and is the only unit that unblocks
hardware, so it goes first when phase-461-W5 lands. W1 waits on the
scheduling half of the program (milestone M2 in phase-464) and W2 on the
census track (M1 track A); they are independent of each other. W4 last.

## 5. What this phase is not

It is not the place for the upstream design; each unit names the wave it
consumes and nothing more. It is not the deck (`~/Downloads/contract-e2e-slides`),
which is paused until the numbers here are measured rather than projected.
