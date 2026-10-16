# Phase 13 - thread priorities derived from the contract

**Goal:** the island's thread priorities come from its contract through
nano-ros's priority allocation (nano-ros RFC-0079), not from numbers written
in Kconfig and C. The build prints and records the derived plan, and a check
holds the built image, and the running board, to it.

**Status (2026-10-16): in progress.** D1-D5 implemented (nano-ros #2303,
#2304, #2306, auto-merge armed; the island on branch `phase13-derived-prio`
until the pin can move to a merged nano-ros). D6: both derivations measured
on the board, every act PASS (tables below); the final run on the pinned
image follows the merge.

## Before and after

| thread | before (main 12fd995) | derived now | from |
|---|---|---|---|
| main thread, registration | 5, `CONFIG_MAIN_THREAD_PRIORITY` | 5, unchanged | Kconfig (below the read task while the island registers, phase8-W10) |
| executor (tier `mrm`: mrm_handler, both operators) | 3, `CONFIG_ISLAND_SPIN_THREAD_PRIORITY` set by `spin_priority.c` | **3** | allocated by nano-ros: the tier takes its most urgent member, `mrm_handler` (rank 5 in `pool.app`: 10 Hz, deadline 100 ms); its contract supervises `call_mrm` (`supervise:`), so the rank is allocated above the transport band, adjacent to it |
| supervisor reaction thread | 2, `CONFIG_ISLAND_SUPERVISOR_THREAD_PRIORITY` | **2** | `NROS_PRIORITY_PLAN_SUPERVISOR_PRIORITY`: the priority the plan reserves above the supervised tier |
| zenoh-pico read, lease, tx flush | 4 | 4, unchanged | `CONFIG_NROS_ZENOH_{READ,LEASE}_PRIORITY` 200 on the 0..255 band; the reserved transport band `[4, 4]` the plan is resolved around |

The other ranks the contract gives (recorded, not run: one tier is one
thread): `mrm_emergency_stop_operator` 7 (30 Hz, no deadline),
`mrm_comfortable_stop_operator` 8 (10 Hz, no deadline). The build reports the
split the single tier loses as a degradation.

## How it is derived

- **The image's plan** (RFC-0079 section 4.1, issue 1508): `nros codegen
  entry --dotconfig` resolves the transport band from the image's `.config`,
  on the board `transport [4, 4]`, `pool.app [5, 14]`.
- **Ranks** from the contract (`chain_aware_rank` over rlm's derivation:
  timer rates, path deadlines, chains), realised into `pool.app`.
- **Supervised deadlines above the transport** (nano-ros #2306, RFC-0079
  section 6 in part): a node with a `supervise:`d path is allocated above the
  reserved transport band, keeping its relative rank, with one more priority
  above it reserved for the supervisor. The contract's `supervise:` is the
  statement that names the crossing; a contract without one keeps every tier
  below the transport. `above = "transport"` (the key the RFC sketches) is
  not implemented: `[tiers.*]` is rlm's `TierDef` (`deny_unknown_fields`), so
  it needs an rlm schema change and a resolver release.
- **The tier** (`src/safety_island_bringup/system.toml`): `[tiers.mrm]` with
  no platform sub-table, `group_tiers = { main = "mrm" }` on the three
  components (issue 1426 rule 2: an authored, unplaced tier is ALLOCATED).
  `spin_period = "10ms"` is the park timeout `run_components` used, so the
  spin loop is unchanged (nano-ros derives no spin period yet).
- **The runner.** `run_tiers` registers on the main thread at
  `CONFIG_MAIN_THREAD_PRIORITY` and adopts the tier's priority before the
  first spin: what `spin_priority.c` did by hand. It is now `spin_hook.c`,
  the SWT0 feed only.
- **The record** (nano-ros #2304): `build-board/nros_priority_plan.json` and
  `nros_priority_plan.h`; the supervisor includes the header and build-asserts
  its thread above the tier and the tier above the transport.

## Units

### D1. The tier runner keeps the application's trace sink (nano-ros #2303)

`run_tiers` replaced the island's trace sink (set from a `SYS_INIT` before
`main()`) with `nros_zephyr_trace_marker`, and that shim's strong reference
to the out-of-tree `sys_trace_app_marker` failed the island's first tier
build at link. Fixed: install-if-unset (`rclc_set_default_trace_sink`), a
weak reference. Every act's trace below decodes the island's markers.

### D2. The entry records the derived plan (nano-ros #2304)

The JSON record and C header beside the generated entry, a printed plan, and
`check-tier-priority-plan-image.py --derived-plan <json> <.config> [<TU>]`.

### D3. The island declares its tier (this repo)

As above. `CONFIG_ISLAND_SPIN_RAISE`, `CONFIG_ISLAND_SPIN_THREAD_PRIORITY`
and `CONFIG_ISLAND_SUPERVISOR_THREAD_PRIORITY` are gone.

### D4. The supervisor's thread from the same plan (this repo)

`ISLAND_SUPERVISOR_PRIORITY = NROS_PRIORITY_PLAN_SUPERVISOR_PRIORITY`; an
image whose plan reserves none does not build. The supervisor record carries
the plan and the priorities the kernel gave every thread at the first spin
(`k_thread_foreach`): `violations.py supervisor` and every act's
`supervisor.txt` judge them, and the act summary prints the verdict.

### D5. The check (this repo)

`just priority-check` (also at the end of `just board-build`): nano-ros's
`--derived-plan` check of the build, the plan and the ranks printed; with
`board=1` the running board's record.

### D6. The board

Image RAM 280,640 B (main 280,632), DTCM 117,584 B (+280 B: the record's
thread table), FLASH 574,236 B (+6,512 B: the tier runner).

Runs on two images of this branch, the nano-ros changes applied to the pin
b285c0b654 before they merged: **derived 5** (#2303 and #2304 only: the tier
in `pool.app`, below the transport; the "before" of the supervised rule) and
**derived 3** (with #2306: above the transport, supervisor 2). Run
directories /mnt/mx500/aeon/worktrees/p13-island/build/timeline/p13-* and
p13-d3-*. The encores at Autoware's default `max_vel`, act b at 8.3 m/s, on
the 315 m straight, as phase 11's S7. Every act PASS, and every act's
supervisor record reads the plan's priorities on the board (`priorities:
AGREE with the plan`: spin thread 5 / 3, reaction thread 3 / 2, zpico_read,
zpico_lease and zpico_flush 4).

| act | image | runs | entry m/s | key terms (ms) | total / bound (ms) | spin gap max (ms) |
|---|---|---|---|---|---|---|
| encore | 2b8a7985 (s6-e4-c, -d) | 2 | 4.14 | detect 517.83-523.22, route 4.71-33.09, settle 2670.41-2681.15 | 3198.33-3232.07 / 5165.67 | 12.68 |
| encore | derived 5 | 2 | 4.14 | detect 557.06-567.73, route 1.69-17.71, settle 2693.34-2696.91 | 3266.33-3268.11 / 5228.67 | 12.70-13.02 |
| encore | derived 3 | 2 | 4.13-4.14 | detect 575.84-596.04, route 1.78-23.64, settle 2691.30-2694.60 | 3290.78-3292.42 / 5228.67 | 12.35-12.67 |
| b (comfortable working) | 56b81ad6 (s7k-b8) | 1 | 8.30 | route 1.87, dwell 10001.13, settle 10756.09 | 20849.67 / 21393.67 | 13.27 |
| b | derived 5 | 2 | 8.31 | route 1.19-99.75, dwell 10000.43-10098.98, settle 10575.91-10754.38 | 20678.30-20975.64 / 21393.67 | 12.71-12.77 |
| b | derived 3 | 2 | 8.31 | route 99.18-99.75, dwell 10098.43-10098.99, settle 10808.26-10858.79 | 20949.63-21074.58 / 21393.67 | 12.31-12.70 |
| encore, 300 ms overrun | cc14139c (s7k-ov2) | 1 | 4.15 | due -> verdict / output / command 0.05 / 0.07 / 0.72, command -> standstill 2801.05, handover 168.17 / 165.67 | 3450.22 / 5379.67 | 303.50 |
| encore, 300 ms overrun | derived 5 | 2 | 4.15 | 0.03 / 0.04-0.05 / 0.57-0.66, 2786.22-2805.29, handover 166.75-194.11 / 163.84-191.44 | 3435.69-3454.08 / 5379.67 | 303.53-311.59 |
| encore, 300 ms overrun | derived 3 | 2 | 4.15 | 0.03 / 0.04 / 0.57, 2780.46-2787.09, handover 227.36-254.76 / 224.92-252.40 | 3429.06-3436.03 / 5379.67 | 307.70-309.17 |
| encore, stall | cc14139c (s7k-st2) | 1 | 4.16 | 0.03 / 0.05 / 0.71, 2782.91 | 3432.21 / 5379.67 | 12.74 |
| encore, stall | derived 5 | 2 | 4.16 | 0.03 / 0.05 / 0.57-0.70, 2782.44-2807.97 | 3431.19-3456.63 / 5379.67 | 12.61-13.11 |
| encore, stall | derived 3 | 2 | 4.16 | 0.03 / 0.04 / 0.57, 2782.57-2795.72 | 3431.36-3444.95 / 5379.67 | 12.80-12.83 |
| b, comfortable inert | 56b81ad6 (s7k-in4, -in5) | 2 | 8.30 | 0.03 / - / 0.57-0.70, call -> due 11074.11-11074.72 of 11076, 4391.47-4410.58, handover 25.04-26.58 / 25.01-57.42 | 25525.50-25675.51 / 26204.33 | 12.47-13.13 |
| b, comfortable inert | derived 5 | 2 | 8.30 | 0.03 / - / 0.57-0.61, 11073.91-11074.10, 4396.99-4401.92, handover 26.19-26.47 / 52.55-53.49 | 25650.59-25750.95 / 26204.33 | 12.43-13.32 |
| b, comfortable inert | derived 3 | 2 | 8.30 | 0.03 / - / 0.57, 11074.07-11074.69, 4400.25-4412.35, handover 25.40-25.50 / 25.38-54.53 | 25552.88-25725.36 / 26204.33 | 12.69-13.16 |

(2b8a7985 is the newest image with plain encores at 4 m/s; its bound was
5165.67 before the response was re-sized to 319 ms.)

What moved, and what did not:

- The supervised terms do not move: due -> verdict 0.03 ms, -> output
  0.04-0.05, -> the direct path's emergency command 0.57-0.70 ms on every
  image; command -> standstill within the same 2780-2808 ms (encores) and
  4391-4412 ms (escalations). The reaction thread is 2 on both 56b81ad6 and
  derived 3, and 3 on derived 5 (still above the spin thread).
- The longest spin gap is 12.3-13.3 ms on all three, overruns aside (300 ms
  + a tick by construction).
- The plain encore's detect is 557-596 ms on both derived images against
  518-523 on 2b8a7985 (n = 2 each). Detect is last sample -> the handler's
  reaction tick, 500 ms max_age + the 10 Hz tick's phase, so it moves by up
  to a tick with the phase; not attributed to the priority.
- Act b's `route` and `dwell` are bimodal on every image: 1-2 ms or ~99 ms
  after the window's deadline, the handler's next 10 Hz tick. s7k-in3
  (cc14139c, phase 11) read dwell 10100.10 the same way. Derived 3 drew the
  late tick in both b runs, which puts their totals at 20949.63 and
  21074.58 of 21393.67 (s7k-b8 20849.67 with the early tick); the settle
  itself (10808-10859 against 10756) is the vehicle's.
- The overrun's handover (the executor taking the emergency back after the
  300 ms stall) is 227-255 ms on derived 3 against 166-194 on derived 5 and
  56b81ad6's family; it is information, not a term (the direct path holds
  the emergency until then), and with n = 2 not separated from the
  overrun's own phase.


## Not in this phase

- Two tiers (the 30 Hz emergency operator on a thread of its own): each tier
  is another executor block (53,776 B on this image, in DTCM with 13,488 B
  free) and a stack; it does not fit without per-tier executor sizing in
  nano-ros.
- The derived spin period (RFC-0079's table): unset, the C tier runner spins
  with a 1 ms timeout, so the island states 10 ms.
- `above = "transport"` as an authored key (rlm schema + resolver release).
- The `nros sync` metadata probes fail on main as before this phase (exit 240
  and `ExecutorFull`); the build proceeds without them.
