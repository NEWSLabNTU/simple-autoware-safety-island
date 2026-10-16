# Phase 13 - thread priorities derived from the contract

**Goal:** the island's thread priorities come from its contract through
nano-ros's priority allocation (nano-ros RFC-0079), not from numbers written
in Kconfig and C. The build prints and records the derived plan, and a check
holds the built image, and the running board, to it.

**Status (2026-10-16): in progress.** Plan below; units D1-D6.

## What the island does today

| thread | priority | set by |
|---|---|---|
| main thread, registration | 5 | `CONFIG_MAIN_THREAD_PRIORITY` (board conf), below the read task so it drains the serial ring while the island registers (phase8-W10) |
| executor (all three MRM nodes, one thread) | 3 after the first spin | `CONFIG_ISLAND_SPIN_THREAD_PRIORITY` (Kconfig default 3), `src/zephyr_entry/src/spin_priority.c` |
| supervisor reaction thread | 2 | `CONFIG_ISLAND_SUPERVISOR_THREAD_PRIORITY`, a build assert keeps it above 3 |
| zenoh-pico read, lease, tx flush | 4 | `CONFIG_NROS_ZENOH_{READ,LEASE}_PRIORITY` 200 on the 0..255 band, mapped by nano-ros to `k_thread` 4 on a 15-priority image; the flush task takes the read priority |

`src/safety_island_bringup/system.toml` declares no tier: the entry calls
`ZephyrBoard::run_components`, one executor on the main thread.

## What nano-ros derives today (pin b285c0b654, main fe7ad85b61)

- **The image's plan** (RFC-0079 section 4.1, issue 1508). `nros codegen
  entry --dotconfig` resolves the transport band from the image's `.config`:
  on the island `transport [4, 4]`, `pool.app [5, 14]`.
- **Ranks** from the contract (`chain_aware_rank` over rlm's derivation:
  timer rates, path deadlines, chains), realised into `pool.app` in the
  port's direction (issue 1427).
- **Placement rules** (issue 1426): a `[tiers.<name>]` with no platform
  sub-table, bound through `group_tiers`, gets an ALLOCATED priority, the most
  urgent of its members' ranks; one with a `zephyr` sub-table is authored and
  wins (and the build says what it beat); a group bound to no tier gets a
  `derived-<node>` tier of its own.
- **Runner.** `run_tiers` runs the first tier on the main thread: the setup
  (registration) at `CONFIG_MAIN_THREAD_PRIORITY`, then the thread adopts the
  tier's priority and spins. That is what `spin_priority.c` does by hand.
  Each further tier is a thread with its own executor storage.
- **Checks.** `check-tier-priority-plan-image.py` judges AUTHORED pins against
  an image's resolved band; nothing compares a derived table with the image,
  and nothing records the derivation beyond a stderr line.
- **Not implemented:** RFC-0079 section 6 (`above = "transport"`: a tier
  stated above the transport; the checker script reads the key, rlm's
  `TierDef` does not), the derived spin period (an unset `spin_period` makes
  the C runner spin with a 1 ms timeout), per-tier executor sizing.

Measured on the island (first build with a tier): the ranks are
`mrm_handler` 5, `mrm_emergency_stop_operator` 7 (the comfortable operator
between), so one tier takes 5, and the build reports the lost split as a
degradation.

## Units

### D1. The tier runner keeps the application's trace sink (nano-ros, PR)

- What: `run_tiers` installed `nros_zephyr_trace_marker` as the callback
  trace sink unconditionally, replacing the sink the island's tracing sets
  from a `SYS_INIT` before `main()` (`run_components` installs none). And the
  shim names `sys_trace_app_marker` strongly under `CONFIG_TRACING_CTF`, so
  an image with CTF tracing and without that out-of-tree patch fails to link
  once it takes the tier runner (the island's first tier build:
  `undefined reference to sys_trace_app_marker`). Fix: an install-if-unset
  (`rclc_set_default_trace_sink`), a weak reference in the shim.
- Gate: the island image links with a tier; a unit test of the
  install-if-unset; nano-ros CI.

### D2. The entry records the derived plan (nano-ros, PR)

- What: `nros codegen entry` writes beside the generated entry a JSON record
  (the image's plan: direction, range, reserved bands, `pool.app`, its
  source; each node's rank: priority, period, deadline; each tier: priority,
  whether authored, allocated or derived, its members; the degradations) and
  a C header with the plan's bands and each tier's priority, so code outside
  nano-ros (the island's supervisor) places its threads from the same plan.
  `check-tier-priority-plan-image.py --derived-plan <json> <.config>`
  re-resolves the band with the Python checker and holds the record to it:
  same bands, every allocated or derived tier inside `pool.app`, none on a
  reserved band, the record's tier priorities equal to the generated entry's.
- Gate: unit tests on the record; the selftest; the island's build prints
  the plan.

### D3. The island declares its tier (this repo)

- What: `[tiers.mrm]` with no platform sub-table, and `group_tiers = { main =
  "mrm" }` on the three components: one tier, its priority allocated. The
  executor runs at the derived priority; `CONFIG_ISLAND_SPIN_RAISE` and
  `CONFIG_ISLAND_SPIN_THREAD_PRIORITY` go; the `nros_cpp_spin_once` wrapper
  stays for SWT0's feed. `spin_period = "10ms"` is stated: it is the timeout
  `run_components` spun with, so the spin loop is unchanged and the one
  variable is the priority (the derived spin period is not implemented).
- Expected: 5, the most urgent priority of `pool.app`, below the transport
  (4). Today it runs at 3, above it. The phase-9 measurement put the raise's
  gain at 0 against 2-3 spins >= 1 ms late per encore (all under 2 ms); D6
  measures it again.
- RAM: one tier has one executor block and no spawned stack. Measured: RAM
  +8 B, FLASH +6,384 B (the tier runner).

### D4. The supervisor's thread from the same plan (this repo)

- What: the reaction thread's priority is no longer a Kconfig number: it is
  one above the most urgent of the transport band and the tiers, from D2's
  header (3 on this image), with build asserts that it is above every tier
  and the transport. The supervisor records, at the first spin and once the
  output latches, the priorities the kernel gave the spin thread, the
  reaction thread and zenoh-pico's tasks (`k_thread_foreach`, by name).
- Gate: the build's plan and the board's record agree (D5).

### D5. The check (this repo)

- What: `just priority-check`: D2's check over the board build, plus the
  record read over SWD from a running board against the plan. `run-board.sh`
  writes the record into every act's readout.
- Gate: PASS on the built image and on the board.

### D6. The board (this repo)

- What: rebuild, flash, re-run phase 11's acts: the encore (HPC loss), act b
  (ODD exit), the 300 ms overrun, the stall, the comfortable-inert
  escalation. Each against `play_launch check --explain`'s rows, compared
  with image 56b81ad6 (s7k-in4, -in5, -b8 and the cc14139c runs).
- Gate: every act PASS; route and detection terms no worse than 56b81ad6's,
  or the regression reported with its numbers.

## Not in this phase

- Two tiers (the 30 Hz emergency operator alone): each tier is an executor
  block (53,776 B on this image, in DTCM with 13,768 B free) and a thread
  stack; it does not fit without per-tier executor sizing in nano-ros.
- `above = "transport"` (RFC-0079 section 6), unless D6 shows the derived
  placement below the transport costs timing.
