# Phase 13 - thread priorities derived from the contract

**Goal:** the island's thread priorities come from its contract through
nano-ros's priority allocation (nano-ros RFC-0079), not from numbers written
in Kconfig and C. The build prints and records the derived plan, and a check
holds the built image, and the running board, to it.

**Status (2026-10-16): done.** D1-D5 merged (nano-ros #2303, #2304, #2312;
the island pins d4bf898409), D6 on the board: every act PASS on the pinned
image e156e51d, and on the two images measured before the merge (tables
below).

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
- **Supervised deadlines above the transport** (nano-ros #2312, RFC-0079
  section 6 in part): a node with a `supervise:`d path is allocated above the
  reserved transport band, keeping its relative rank, with one more priority
  above it reserved for the supervisor. The contract's `supervise:` is the
  statement that names the crossing; a contract without one keeps every tier
  below the transport. Since nano-ros #1967 (rlm v0.1.67, #2414) only the
  supervisor's priority crosses on `supervise:`; a tier crosses the band only
  when its `[tiers.*]` table says `above = "transport"`. The island's does not
  (see "The mrm tier above or below the transport" below), so the tier runs
  at 5 in `pool.app`, below the transport's 4, and the supervisor at 3.
- **The tier** (`src/safety_island_bringup/system.toml`): `[tiers.mrm]` with
  no platform sub-table, `group_tiers = { main = "mrm" }` on the three
  components (issue 1426 rule 2: an authored, unplaced tier is ALLOCATED).
  `spin_period = "10ms"` is the park timeout `run_components` used, so the
  spin loop is unchanged. nano-ros derives a spin period from the tier's
  fastest release (33,333 us, the 30 Hz operator; #1968, #2399); the
  authored 10 ms is kept as an override and the build notes it.
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

Pinned image e156e51d: RAM 280,672 B (main 280,632; +40), DTCM 117,584 B
(+280 B: the record's thread table), FLASH 575,884 B (+8,160 B: the tier
runner and the six nano-ros commits since the old pin).

Runs on two images of this branch, the nano-ros changes applied to the pin
b285c0b654 before they merged: **derived 5** (#2303 and #2304 only: the tier
in `pool.app`, below the transport; the "before" of the supervised rule) and
**derived 3** (with #2312, then open as #2306: above the transport, supervisor 2). Run
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

The pinned image (e156e51d: nano-ros d4bf898409, derived 3), one run of
each act, run directories p13-f-*; every act PASS, `priorities: AGREE with
the plan` (spin thread 3, reaction thread 2, zenoh-pico's tasks 4):

| act | entry m/s | key terms (ms) | total / bound (ms) | spin gap max (ms) |
|---|---|---|---|---|
| encore | 4.14 | detect 569.60, route 15.56, settle 2696.01 | 3281.16 / 5228.67 | 12.54 |
| b (comfortable working) | 8.30 | route 101.63, dwell 10100.72, settle 10802.55 | 21046.07 / 21393.67 | 13.16 |
| encore, 300 ms overrun | 4.15 | 0.03 / 0.04 / 0.57, command -> standstill 2773.24, handover 225.43 / 223.05 | 3421.89 / 5379.67 | 308.38 |
| encore, stall | 4.16 | 0.03 / 0.04 / 0.58, 2805.00 | 3453.91 / 5379.67 | 12.51 |
| b, comfortable inert | 8.30 | 0.03 / - / 0.58, call -> due 11074.10 of 11076, 4395.57, handover 26.64 / 56.55 | 25574.76 / 26204.33 | 12.25 |

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
- Act b's `route` and `dwell` are bimodal: 1-2 ms or ~99 ms after the
  window's deadline, the handler's next 10 Hz tick. Closed after the
  phase: a coin flip of the 1 ms kernel tick, the same on both runners,
  and budgeted. See "The window's tick phase" below.
- The overrun's handover (the executor taking the emergency back after the
  300 ms stall) is 227-255 ms on derived 3 against 166-194 on derived 5 and
  56b81ad6's family; it is information, not a term (the direct path holds
  the emergency until then), and with n = 2 not separated from the
  overrun's own phase.

### The window's tick phase (after the phase)

The handler stamps the request inside the tick that turns it on (tick k)
and expires it on the first tick with `now - stamp >= 10 s`. With a
100 ms timer the deadline falls exactly on tick k+100, so the expiry tick
is k+100 when that tick runs at least as late after its due time as tick
k did, and k+101 otherwise. Read from the island traces (handler tick =
`PATH_MRM_HANDLER_CALL_MRM_ENTRY` / `ON_TIMER_ENTRY`; dE = tick k+100's
entry - tick k's entry - 10000 ms; the stamp is 0.22-0.38 ms after the
entry on every run):

| image | runs | dE (ms) when expiry is k+100 | dE (ms) when expiry is k+101 | late (k+101) |
|---|---|---|---|---|
| phase 11 (run_components): s6-b8-*, s7k-b8, s7k-in*, s6-in*, s6-g8i* | 22 | +0.005 .. +1.62 | -1.50 .. -0.004 | 10 of 22 |
| phase 13 (tier runner): p13-b8*, p13-d3-b8*, p13-f-b8, p13-*in8* | 10 | +0.002 .. +1.00 | -1.53 .. -0.14 | 6 of 10 |

The sign of dE decides every one of the 32 windows. dE is the difference
of two tick latencies, and those are quantized by the 1 ms kernel tick
(`SYS_CLOCK_TICKS_PER_SEC=1000`): the handler's tick runs at a fixed phase
or 1 ms after it. 10 of 22 against 6 of 10 is no difference (Fisher two-
sided p = 0.70); phase 13's "4 of 5 against 0 of 1" compared one old run
(s7k-b8, which drew dE = +0.67) with five new ones.

The timer does not drift on either runner. nano-ros's repeating timer
carries the overshoot (`elapsed_ms -= period_ms` in `Timer::fire`), so it
is phase-locked to its first release, whatever loop calls `spin_once`.
Fitted over every handler tick in the act (260-313 ticks, 30-32 s), the
period is 99.9995-100.0023 ms and the on-time phase moves -0.53 .. +0.14 ms
end to end on the phase 11 runs, 99.9995-100.0015 ms and -0.08 .. +0.06 ms
on the phase 13 runs. The tier runner's spin loop (the 10 ms park, the gap
step) does not shift it.

Why the late tick stays: the window is a LEAST time (the contract's
`window` comment, phase8-W12). Expiring on tick k+100 regardless (the due
time instead of the run time, or a tolerance of a tick) would end the
request up to 1.5 ms before 10 000 ms on the island clock in the runs
with dE < 0, and the dwell term's lower bound would fail. The contract
already charges the late tick: `call_mrm`'s 149 ms holds the 100 ms tick
plus the timer's 18 ms jitter, the dwell is checked in [10 000, 10 149] ms,
and the total's bound 21 393.67 ms is summed with it. With the late tick
the working-comfortable act b totals are 20 949.63-21 149.03 ms (s6-b8-a
on phase 11's image the highest), 244.64 ms or more under the bound; route
99.18-101.63 ms of 149. Removing the coin flip needs a deadline that is not on the tick (a one-shot at stamp + 10 s,
another timer entity on the handler), worth ~100 ms in about half the runs;
not done.


### The mrm tier above or below the transport (after the phase)

nano-ros #2398 (#1967) ended the implicit lift: a tier crosses the
transport band only when its `[tiers.*]` table says `above =
"transport"`, and the supervisor's priority stays above the transport
either way. Two gate images, the planning simulator, one fresh boot per
act:

- **A**, mrm above the transport: nano-ros 628675932 (the lift still
  implicit; the same plan an authored key gives): transport 4, mrm 3,
  supervisor 2.
- **B**, mrm below the transport: 628675932 with #2398 applied: transport
  4, mrm 5 in pool.app, supervisor 3.

Serial is the island's UART counters (`_z_zephyr_serial_stats`): UART
overruns / bad frames in the act (boot to the act's start was 0/0 in
every run, so the boot-to-end count is the same), the RX ring's overflows
in the act and its high water (the ring is 4,096 B).

| act | image | runs | serial in act | ring overflows | ring high water (B) | key terms (ms) | total / bound (ms) | spin gap max (ms) |
|---|---|---|---|---|---|---|---|---|
| encore | A | 3 (pl-pe, A-e2, A-e3) | 0/0 x3 | 0 | 1006-1111 | detect 538.54-559.23, route 1.75-4.53 | 3449.45-3506.94 / 5228.67 | 12.24-13.24 |
| encore | B | 3 (B-e1..3) | 0/0 x3 | 0 | 1006-1106 | detect 521.63-568.83, route 1.71-1.99 | 3475.54-3503.50 / 5228.67 | 12.70-12.89 |
| a | A | 1 (pl-pa) | 0/0 | 0 | 1006 | | 8/8 PASS | 12.33 |
| a | B | 1 (B-a1) | 0/0 | 0 | 1045 | | 8/8 PASS | 13.21 |
| b | A | 1 (pl-pb) | 0/0 | 0 | 1106 | route 102.21 | 16150.76 / 21393.67 | 12.25 |
| b | B | 1 (B-b1) | 0/0 | 0 | 1105 | route 2.01 | 15399.67 / 21393.67 | 12.89 |
| encore, 300 ms overrun | A | 3 (A-ov1..3) | 1/2, 1/2, 0/1 | 1163, 962, 1615 | 4096 (full) x3 | due -> verdict / output / command 0.03 / 0.04 / 0.57-0.58, command -> standstill 2713.51-2728.16 | 3362.28-3377.33 / 5379.67 | 309.78-311.65 |
| encore, 300 ms overrun | B | 3 (B-ov1..3) | 0/0, 0/0, 1/1 | 0 | 1006-1212 | 0.03-0.04 / 0.05 / 0.57-0.71, 2714.17-2729.51 | 3363.11-3378.32 / 5379.67 | 303.02-311.91 |

Every act PASS. The supervisor is not driven in any plain act; in every
overrun act it latches on the route deadline, the case the act injects,
and its supervised rows PASS. On the board the kernel ran each image's
plan: A spin 3 / reaction 2, B spin 5 / reaction 3, zpico_read,
zpico_lease and zpico_flush 4 on both. (The B runs printed `priorities:
DISAGREE` only under violations.py's former rule that the spin thread
must be above the transport; the rule went with #1967, see below.)

What it shows:

- **Mrm above the transport starves the RX drain while a spin overruns.**
  In every A overrun act the 4,096 B RX ring fills and overflows
  962-1,615 times, costing one or two bad frames (and in two of the three
  a UART overrun): for 300 ms the tier at 3 holds the CPU and zpico_read at 4
  never drains. In B the same 300 ms busy-wait runs at 5, below
  zpico_read; the ring peaks at 1,212 B and never overflows. B-ov3's one
  UART overrun (one bad frame) came with no ring overflow, so it is the
  hardware FIFO, not the drain; fn-ca on the final pin shows the same in
  a plain CARLA act. This is the mechanism behind rg-ov2's serial 2/3.
- **The supervised terms do not move.** The supervisor is above the
  transport on both images (2 or 3), and due -> verdict / output /
  command is 0.03 / 0.04-0.05 / 0.57-0.71 ms on both; command ->
  standstill and the totals are within 16 ms of each other.
- **Plain acts do not separate.** No overflow on either image, detect
  521-569 ms and route 1.7-4.5 ms on both. Act b's route is the known
  1-2 ms or ~100 ms coin flip of the window's tick phase (above), not the
  priority. The longest plain spin gap is 12.2-13.2 ms on both.

Recommendation: **B**, mrm below the transport, the plan nano-ros now
derives without the key. It keeps the link draining through a spin
overrun at no cost to the supervised path, and the supervisor, not the
tier, is what has to preempt the transport. The island takes it on pin
54a1146d67 (island_supervisor.c no longer asserts the tier above the
transport, and violations.py no longer requires it); that round, all
PASS with priorities spin 5 / reaction 3 AGREE, is in
docs/design/carla-island-demo.md, plus one overrun encore on the final
image (fn-ov1: serial 0/0, no ring overflow, high water 1,212 B,
supervised 0.03 / 0.04 / 0.57 ms). Run directories:
/mnt/mx500/aeon/worktrees/pin-latest/build/timeline/{pl-*,A-*,B-*,fn-*}.

## Not in this phase

- Two tiers (the 30 Hz emergency operator on a thread of its own, tier
  `estop` at 7): measured, not adopted. With per-tier executor sizing
  (nano-ros #2404) and RFC-0107 steps 1-3 (#2421 arena floor only for
  unknown demand, #2423 launch remaps in flash, #2424 extra sessions sized
  from the backend count) the split builds at DTCM 110,320 B against
  103,224 B for one tier, 20,752 B free, inside the 8 KiB guard. The second
  tier costs 7,096 B: the two backings 11,112 + 28,176 B against 35,384 B,
  one more executor value (5,360 against 2,680 B), the tier thread (272 B)
  and its monitor rows (240 B). Its 16 KiB stack is in RAM.
- The derived spin period: nano-ros derives one (#1968, #2399), 33,333 us
  for the mrm tier (its fastest release); the island keeps `spin_period =
  "10ms"` as an authored override, and the build notes it.
- `above = "transport"`: nano-ros reads the key (#2398, rlm v0.1.67 in
  #2414); the island does not set it (recommendation B above), so the plan
  stays transport 4, mrm 5, supervisor 3.
