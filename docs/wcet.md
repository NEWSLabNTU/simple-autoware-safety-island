# Execution times per callback

phase-7 W4 (the `[wcet]` profile) and W5 (the derivation) own this file. The
section below is W7's: what silicon has given so far. Section 6 of the phase-7
plan applies to every number here: a trace is one run, and a maximum over N
runs is a lower bound on the worst case.

## Silicon (W7)

2026-09-25, MR-CANHUBK344 (S32K344, Cortex-M7 at 160 MHz), the island image
with the phase7-W1 tracing, a host `rmw_zenohd` on the board's only wired UART
(`just board-peer`, `just/board-peer.just`). Raw reads, router logs and CSVs
are in `experiments/serial-interop/w7/`.

### Result: no callback ran, so there are no durations yet

The serial session opens on every boot (6 of 6), but the executor never
starts. Entity registration fails in the third node's constructor and the
image tears every entity down again, about 0.6 s after the session opens.
No timer ran, so no marker fired and no marker pair exists. The table below is
therefore the table the contract asks for, with its measured columns empty.
No number from native_sim or QEMU is put in them (docs/tracing.md section 7).

| pair (ENTRY -> EXIT) | declared | N | min | median | max |
| --- | --- | ---: | ---: | ---: | ---: |
| PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER | period 33.33 ms | 0 | - | - | - |
| PATH_STOP_MODE_OPERATOR_ON_TIMER | period 33.33 ms | 0 | - | - | - |
| PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER | period 100 ms | 0 | - | - | - |
| PATH_MRM_HANDLER_ON_TIMER | max_latency 100 ms, period 100 ms | 0 | - | - | - |
| PATH_MRM_HANDLER_CALL_MRM | max_latency 110 ms | 0 | - | - | - |
| SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE | - | 0 | - | - | - |
| tracing's own cost, `island_trace_marker` (DWT CYCCNT) | 2-5 us estimated | 0 | - | - | - |

Provenance of the empty rows: the flashed image `build-board/zephyr/zephyr.hex`
sha256 `828ea599...0bcef74` (ELF `4dbf4163...d1d094`), run 3, trace
`experiments/serial-interop/w7/board-peer-3.bin`: 1,115 records, 1,114
heartbeats, 0 markers.

### Why the executor never starts

The trace and the router log together show what happens. Nothing here was
read off a console: the board's console UART is not wired.

1. **The session opens.** Each of the 6 boots with the router up (runs 1-3,
   and three resets in run 4) opened a serial transport at once, for
   example `New transport opened between 2b703d7a... and 233d9924...` at
   09:18:29.416Z, under 1 s after the flash reset.
2. **Registration runs.** Over the next 0.4 s the router logs the board
   declaring `mrm_emergency_stop_operator` and `mrm_comfortable_stop_operator`
   in full. That includes the comfortable operator's two TRANSIENT_LOCAL
   publishers, whose history caches appear as queryables
   `.../max_velocity_candidates/.../@adv/pub/<zid>/0/_` and
   `.../clear_velocity_limit/.../@adv/pub/<zid>/1/_`. Then
   `stop_mode_operator` and its `control` publisher.
3. **The third TRANSIENT_LOCAL publisher fails.** `stop_mode_operator`'s
   `gear` (`QoS(1).transient_local()`) declares its publisher interest and
   undeclares it in the same batch: `Declare interest 32
   (10/system/stop_mode/gear/...)` then `Undeclare interest 32`, with no
   cache queryable and no token. The retention-slot counter
   `transient_local::NEXT_ADV_EID` stops at 2. The failed component object,
   read over SWD from `__nros_comp_buf_2`, holds
   `error_what = "create_publisher_in"` and `error_code = -100`
   (`nros::ErrorCode::TransportError`). The image was built with nano-ros's
   retention pool at its default, `MAX_TL_PUBLISHERS = 2`. The contract
   states no durability, so nothing derived a larger pool, and the code has
   five TRANSIENT_LOCAL publishers. W2 found the same failure on QEMU and
   Renode, where the console prints it: `[nros] FATAL: node
   "stop_mode_operator" failed to construct at create_publisher_in
   (code=-100)`.
4. **Teardown.** Within 0.25 s every token, subscriber and queryable is
   undeclared. The board then sends nothing, and the router closes the link
   10 s later (`RX task failed: serial//dev/ttyUSB0 => ...: expired after
   10000 milliseconds`).

Ruled out on the board in run 4, by polling RAM over SWD every 40 ms or so
while the image registered, on two of its three resets
(`experiments/serial-interop/w7/poll-zpico-tables.py` and `poll-posix-pools.py`):

- zenoh-pico's tables were not full: at most 6 of 14 publishers, 4 of 31
  queryables and 15 of 58 liveliness tokens;
- the POSIX pools were not full: at most 22 of 64 mutexes and 10 of 16
  condition variables;
- the platform heap was not full: peak 57,024 B of 94,720 in the boot
  report.

The boot report reads `stage 4 RegisteringEntities` with no error recorded
(`experiments/serial-interop/w7/boot-report-run3.bin`). It does not capture a
constructor failure.

A rebuild with the pool raised from the environment (`ZPICO_MAX_TL_PUBLISHERS=5`,
`ZPICO_MAX_QUERYABLES=31`) went through `just board-build`, but it never ran:
`just board-flash` is `west flash`, which rebuilt the image first in a shell
without those variables. The flashed ELF has `TL_SLOTS` of 2,680 B, which is
2 x 1,340 B (two 1,024 B slots). The rebuild's own ELF has 2,860 B, which is
5 x 572 B. So the silicon result above is the default pool, as W2's is. The
contract fix (durability stated, pool derived) was taken over by the session
on 2026-09-25, and this unit did not flash anything after that.

### What the fixed image is expected to hit next

These are expectations from W2's image and from the source. None of them is
a silicon observation.

- **RAM.** With a 5-slot pool at the default 1,024 B per sample and 31
  queryables, the board image did not link: `region 'RAM' overflowed by 3352
  bytes` (`build/trace/board-build-w7-1.log`). It linked with
  `ZPICO_TL_RETAIN_BYTES=256`: RAM 327,192 B of 327,680 (99.85%), 488 B left.
  Every retained message here is under 256 B.
- **mrm_handler.** W2's QEMU image with a 5-slot pool
  (`build-qemu-tl`, locator `tcp/10.0.2.100:7447`) reached this host's
  router on port 7447 while W7's router held that port (run 3, 09:17:10Z,
  face `a17a2875...`; see the port note in `just/board-peer.just`). It
  registered all of `stop_mode_operator` and then failed in `mrm_handler`.
  The handler's three subscriptions (availability, odometry, control_mode),
  five publishers and two clients were declared. The other four subscriptions
  never got a token: comfortable_stop/status, emergency_stop/status,
  `/api/operation_mode/state` and gear_cmd. Then everything was torn down. One
  cause is certain from the source: `/api/operation_mode/state` is subscribed
  `QoS(1).transient_local()` (`mrm_handler_core.cpp`), and nros-rmw-zenoh
  refuses TRANSIENT_LOCAL on every entity except a publisher (`shim/qos.rs`:
  "the shim serves publisher-side retention only"). Stating durability in the
  contract does not change that refusal. The handler will not construct on a
  zenoh image until that subscription asks for VOLATILE, or until the shim
  serves the subscriber half.
- **The reaction will not fire by itself.** Once the handler constructs,
  `onTimer` runs `isDataReady()` first, which returns false until one
  `/system/operation_mode/availability` sample has arrived
  (`has_operation_mode_availability_`). With no publisher anywhere, every
  tick is `PATH_MRM_HANDLER_ON_TIMER_ENTRY` followed by
  `PATH_MRM_HANDLER_ON_TIMER_EXIT` with arg 0, and that EXIT is the last
  handler marker. `call_mrm` needs availability to have arrived and then gone
  stale for 500 ms. To trace the reaction on silicon, the host has to publish
  availability for a while and then stop.

### Timebase, observed

`island_trace_ts()` is `k_cycle_get_32()` (160 MHz, wraps every 26.84 s)
converted to u32 nanoseconds. At each cycle-counter wrap the u32 ns stamp
steps back by 2^30 ns (1,073.742 ms). The reason: 2^32 cycles is 6.25 x 2^32
ns, and that is 0.25 x 2^32 ns modulo 2^32. Seen in run 3: consecutive
heartbeats 100 ms apart decode as `-973.742 ms` at uptime 26,900, 53,700,
80,600 and 107,400 ms. So the decoded span is 107.105 s against 111.3 s of
uptime. The other 1,108 heartbeat intervals measure 99.998 / 100.000 /
100.000 ms (min / median / max). A marker pair that straddles one of these
wraps would show a duration near -1.07 s. `w7_pairs.py` reports such a pair
rather than hiding it. The heartbeat's `uptime_ms` is what would re-anchor it
(docs/tracing.md section 7).

### The tracing's own cost: instrumented, not yet measured

`island_trace.h` now brackets `island_trace_marker` with DWT `CYCCNT` on the
Cortex-M7. The bracket runs from just before `irq_lock()` to just before
`irq_unlock()`, and it keeps `island_trace_cost_{n,min,max,sum}` plus a
one-time empty-bracket calibration, `island_trace_cost_empty`. On the board:
`CYCCNT` runs (`DWT_CTRL` = `0x40000001`), `island_trace_cost_empty` = 1
cycle, and `island_trace_cost_n` = 0 because no marker has run. The 2-5 us
per marker estimate from W1 still stands unmeasured. When markers fire, each
pair's duration includes one marker's cost: the ENTRY marker's write
completes before the EXIT stamp is taken.

### Reproduce (when a fixed image is flashed)

    just board-peer                       # terminal 1; router first
    pyocd reset -t s32k344                # terminal 2
    just board-peer-nodes                 # ros2 node list via the router (port 7449)
    just trace-board build/trace/board-peer-N.bin
    python3 experiments/serial-interop/w7_pairs.py build/trace/board-peer-N.bin \
        --csv-dir experiments/serial-interop/w7 --timeline 40

With `CONFIG_TRACING_THREAD=n` (the board conf since W7), the buffer holds
markers and heartbeats only. At the native_sim marker rate (about 4.5 KB/s,
docs/tracing.md section 5) 16 KiB covers the first 3-4 s after boot, which is
roughly 100 ticks of each 30 Hz timer.
