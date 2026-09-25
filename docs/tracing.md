# Tracing the island

phase7-W1, 2026-09-25. What is traced, how the marker ids are made, how to
get a trace out of `native_sim` and off the board, what the tracing costs,
and what it cannot tell you.

Short version: synchronous Zephyr CTF into a RAM buffer, on both images. Only
application markers and thread switches are kept. The marker ids are
generated from the island contract. A heartbeat carries a sequence counter,
and a provenance record at boot names the marker table and the knob values.
On the native_sim demo every reachable marker fires and the sequence is
contiguous. The board image links, with 7,776 B of RAM left.

## 1. Design and why

The design was decided on 2026-09-01 and first landed here:
`CONFIG_TRACING_CTF` + `CONFIG_TRACING_SYNC` + `CONFIG_TRACING_BACKEND_RAM`,
with a cut event set, a stated buffer size, a heartbeat carrying a monotonic
sequence counter, and provenance in the buffer.

**Why sync + RAM and nothing else.** `TRACING_LOCK()` is `irq_lock()`
(`subsys/tracing/include/tracing_core.h:17`), and it wraps the whole backend
write (`tracing_format_raw_data`, `tracing_format_sync.c`). A synchronous
event therefore costs whatever the backend costs, paid with interrupts
masked. That rules out three backends:

- **UART**, the Kconfig default, is a byte-at-a-time `uart_poll_out` loop. At
  115200 baud a 14-byte event is about 1.2 ms with interrupts off.
- **Semihost** traps (`bkpt 0xab`) and halts the core until a probe answers.
  With no probe attached it faults, so the image cannot run on its own.
- **Async** drops whole events into `tracing_packet_drop_num`, a counter
  nothing in the tree reads. Loss is invisible and the stream still looks
  well-formed.

RAM is a bounds check and a `memcpy` (`tracing_backend_ram.c`), so it is the
only backend whose interrupts-off cost is small. That cost is estimated in
section 5 from the board image's code, not assumed, and is to be measured in
phase7-W6. The POSIX file backend exists on native_sim but is not used: it is
a host `fwrite` under the lock, a code path the board never runs.

**RAM is one-shot, not a ring.** `ram_tracing[]` fills from boot. On the
first write that would overflow it, the backend sets `buffer_full` and drops
every later event. The fill position `pos` is static. So the native_sim dump
trims trailing zeros (no event id is 0), and the board read takes the whole
array.

**Cut event set.** Only markers and thread switches are wanted, and Kconfig
cannot give exactly that:

- `CONFIG_TRACING_THREAD` is the only symbol that carries `switched_in` and
  `switched_out`. On 3.7 it also brings thread create, name_set and info. On
  4.4 it also brings sleep, yield, sched_lock and join, and no Kconfig
  separates those from the switches.
- On the 3.7 line (native_sim), `isr_enter`, `isr_exit` and `idle` are emitted
  by the native_sim board and the POSIX arch unconditionally. 3.7 has no
  `TRACING_IDLE`, and the native_sim IRQ handler ignores `TRACING_ISR`. They
  are 5 bytes each and are counted below.
- On 4.4 (board), ISR and idle events are gated and are off.
- Every other category is set to `n` in both conf blocks.

**Markers ride the CTF stream.** A marker is written with the same
`tracing_format_raw_data` call that `CTF_EVENT` ends in, laid out as a CTF
event:

    u32 timestamp_ns | event id | u16 marker | u32 arg

The event id is 0xE0 on Zephyr 3.x (u8 CTF ids; that tree uses up to 0x5B)
and 0x1E0 on 4.x (u16 ids; that tree uses up to 0xFF). The decoder refuses
to start if either value collides with the TSDL.

`sys_trace_named_event` was not used. 3.7 has no named or user event in CTF
at all. 4.4 has one, but it carries a 20-byte name string, which makes a
marker 32 bytes instead of 12.

Two more record types come from the runtime in `island_trace.h`:

- **HEARTBEAT** every 100 ms, from a `k_timer`:
  `u32 ts | id+1 | u32 seq | u32 uptime_ms`. `seq` counts from 0. A gap in it
  is a lost record.
- **PROVENANCE** once at boot (`SYS_INIT`, APPLICATION 90, after
  `tracing_init`): an ASCII key=value string. It carries the Zephyr version,
  the board, the contract sha256, the marker count and marker-table sha256,
  the entity counts, the heartbeat period, and the value the build actually
  delivered (from `autoconf.h`) for every integer knob stated in the entry
  confs and board conf.

The buffer cannot hold the image's own SHA: an image cannot contain a hash of
itself. The recipes therefore write `<trace>.meta` beside every capture, with
the image's sha256 and the source revision. The provenance ties the trace to
the contract and marker table; the `.meta` file ties it to the binary.

## 2. Markers, generated from the contract

`src/safety_island_tracing/gen_markers.py` reads the resolved model that
`just sync` writes (`build/nros/models/safety_island_bringup/system_model.yaml`).
It refuses to run if the model is stale against the contract. It emits one
marker per executing contract element:

| group | markers | from |
| --- | --- | --- |
| node path | `PATH_<node>_<path>_ENTRY` / `_EXIT` | every `paths:` entry (timer and reaction) |
| trigger input | `TAKE_<node>_<endpoint>` | every input that triggers a path |
| service call | `CALL_<node>_<endpoint>` | every `cli:` |
| service callback | `SERVE_<node>_<endpoint>_ENTRY` / `_EXIT` | every `srv:` |
| publish | `PUB_<node>_<endpoint>` | every contracted `pub:` |

Ids run from 1, in that group order and sorted inside each group. The output
is `include/island_trace_markers.h` (ids, contract digest, table digest, knob
macros) plus `markers.json` (the same table with trigger, rate and
`max_latency_ms` for the phase7-W3/W4 analysis). Both are generated and
committed; `just trace-gen-check` fails if either is stale or a marker has
no call site.

The four components use one macro, `ISLAND_TRACE(ISLAND_MK_<marker>, arg)`,
from `include/island_trace.h`. It compiles to nothing, and `arg` is not
evaluated, unless the image is a Zephyr build with `CONFIG_TRACING_CTF` and
`CONFIG_TRACING_BACKEND_RAM`. The host `native_entry` build is untouched.
Deleting the tracing block from a conf turns tracing off for that image; the
source edits are marker lines and three include lines, plus the
`ISLAND_TRACE_DEFINE_RUNTIME` define in `mrm_handler_core.cpp`, which is the
one translation unit that carries the runtime.

`call_mrm` is the same callback body as the handler's `on_timer`, a fact the
contract states. Its ENTRY and EXIT markers fire on a tick where
`is_operation_mode_availability_timeout` is set: ENTRY before
`updateMrmState()`, EXIT after `publishMrmState()`, matching the path's
`output: [mrm_state, emergency_stop_operate]`.

### The marker table (31 markers, table sha256 `bd6e59bbd17e...`)

Paths are relative to `src/autoware_mrm_*/src/mrm_*/` (comfortable,
emergency, handler) and `src/autoware_stop_mode_operator/src/` (stop_mode).
Line numbers are from `just trace-gen` at this revision; `python3
src/safety_island_tracing/gen_markers.py sites` prints the current ones.

| id | marker | contract element | source site |
| ---: | --- | --- | --- |
| 1 | `PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER_ENTRY` | `/mrm_comfortable_stop_operator/on_timer` (path_entry) | comfortable/mrm_comfortable_stop_operator_core.cpp:134 (onTimer) |
| 2 | `PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER_EXIT` | `/mrm_comfortable_stop_operator/on_timer` (path_exit) | comfortable/mrm_comfortable_stop_operator_core.cpp:136 (onTimer) |
| 3 | `PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER_ENTRY` | `/mrm_emergency_stop_operator/on_timer` (path_entry) | emergency/mrm_emergency_stop_operator_core.cpp:134 (onTimer) |
| 4 | `PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER_EXIT` | `/mrm_emergency_stop_operator/on_timer` (path_exit) | emergency/mrm_emergency_stop_operator_core.cpp:143 (onTimer) |
| 5 | `PATH_MRM_HANDLER_CALL_MRM_ENTRY` | `/mrm_handler/call_mrm` (path_entry) | handler/mrm_handler_core.cpp:438 (onTimer) |
| 6 | `PATH_MRM_HANDLER_CALL_MRM_EXIT` | `/mrm_handler/call_mrm` (path_exit) | handler/mrm_handler_core.cpp:445 (onTimer) |
| 7 | `PATH_MRM_HANDLER_ON_TIMER_ENTRY` | `/mrm_handler/on_timer` (path_entry) | handler/mrm_handler_core.cpp:426 (onTimer) |
| 8 | `PATH_MRM_HANDLER_ON_TIMER_EXIT` | `/mrm_handler/on_timer` (path_exit) | handler/mrm_handler_core.cpp:430 (onTimer)<br>src/autoware_mrm_handler/src/mrm_handler/mrm_handler_core.cpp:451 (onTimer) |
| 9 | `PATH_STOP_MODE_OPERATOR_ON_TIMER_ENTRY` | `/stop_mode_operator/on_timer` (path_entry) | stop_mode/stop_mode_operator.cpp:95 (on_timer) |
| 10 | `PATH_STOP_MODE_OPERATOR_ON_TIMER_EXIT` | `/stop_mode_operator/on_timer` (path_exit) | stop_mode/stop_mode_operator.cpp:102 (on_timer) |
| 11 | `TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY` | `/mrm_handler/operation_mode_availability` (take) | handler/mrm_handler_core.cpp:148 (onOperationModeAvailability) |
| 12 | `CALL_MRM_HANDLER_COMFORTABLE_STOP_OPERATE` | `/mrm_handler/comfortable_stop_operate` (service_call) | handler/mrm_handler_core.cpp:356 (requestMrmBehavior) |
| 13 | `CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE` | `/mrm_handler/emergency_stop_operate` (service_call) | handler/mrm_handler_core.cpp:360 (requestMrmBehavior) |
| 14 | `SERVE_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE_ENTRY` | `/mrm_comfortable_stop_operator/operate` (service_serve_entry) | comfortable/mrm_comfortable_stop_operator_core.cpp:81 (operateComfortableStop) |
| 15 | `SERVE_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE_EXIT` | `/mrm_comfortable_stop_operator/operate` (service_serve_exit) | comfortable/mrm_comfortable_stop_operator_core.cpp:91 (operateComfortableStop) |
| 16 | `SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_ENTRY` | `/mrm_emergency_stop_operator/operate` (service_serve_entry) | emergency/mrm_emergency_stop_operator_core.cpp:106 (operateEmergencyStop) |
| 17 | `SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_EXIT` | `/mrm_emergency_stop_operator/operate` (service_serve_exit) | emergency/mrm_emergency_stop_operator_core.cpp:114 (operateEmergencyStop) |
| 18 | `PUB_MRM_COMFORTABLE_STOP_OPERATOR_CLEAR_VELOCITY_LIMIT` | `/mrm_comfortable_stop_operator/clear_velocity_limit` (publish) | comfortable/mrm_comfortable_stop_operator_core.cpp:128 (publishVelocityLimitClearCommand) |
| 19 | `PUB_MRM_COMFORTABLE_STOP_OPERATOR_MAX_VELOCITY_CANDIDATES` | `/mrm_comfortable_stop_operator/max_velocity_candidates` (publish) | comfortable/mrm_comfortable_stop_operator_core.cpp:116 (publishVelocityLimit) |
| 20 | `PUB_MRM_COMFORTABLE_STOP_OPERATOR_STATUS` | `/mrm_comfortable_stop_operator/status` (publish) | comfortable/mrm_comfortable_stop_operator_core.cpp:99 (publishStatus) |
| 21 | `PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD` | `/mrm_emergency_stop_operator/emergency_control_cmd` (publish) | emergency/mrm_emergency_stop_operator_core.cpp:128 (publishControlCommand) |
| 22 | `PUB_MRM_EMERGENCY_STOP_OPERATOR_STATUS` | `/mrm_emergency_stop_operator/status` (publish) | emergency/mrm_emergency_stop_operator_core.cpp:122 (publishStatus) |
| 23 | `PUB_MRM_HANDLER_EMERGENCY_HOLDING` | `/mrm_handler/emergency_holding` (publish) | handler/mrm_handler_core.cpp:270 (publishEmergencyHolding) |
| 24 | `PUB_MRM_HANDLER_GEAR_CMD_OUT` | `/mrm_handler/gear_cmd_out` (publish) | handler/mrm_handler_core.cpp:254 (publishGearCmd) |
| 25 | `PUB_MRM_HANDLER_HAZARD_LIGHTS_CMD` | `/mrm_handler/hazard_lights_cmd` (publish) | handler/mrm_handler_core.cpp:236 (publishHazardCmd) |
| 26 | `PUB_MRM_HANDLER_MRM_STATE` | `/mrm_handler/mrm_state` (publish) | handler/mrm_handler_core.cpp:261 (publishMrmState) |
| 27 | `PUB_MRM_HANDLER_TURN_INDICATORS_CMD` | `/mrm_handler/turn_indicators_cmd` (publish) | handler/mrm_handler_core.cpp:220 (publishTurnIndicatorCmd) |
| 28 | `PUB_STOP_MODE_OPERATOR_CONTROL` | `/stop_mode_operator/control` (publish) | stop_mode/stop_mode_operator.cpp:114 (publish_control_command) |
| 29 | `PUB_STOP_MODE_OPERATOR_GEAR` | `/stop_mode_operator/gear` (publish) | stop_mode/stop_mode_operator.cpp:132 (publish_gear_command) |
| 30 | `PUB_STOP_MODE_OPERATOR_HAZARD_LIGHTS` | `/stop_mode_operator/hazard_lights` (publish) | stop_mode/stop_mode_operator.cpp:150 (publish_hazard_lights_command) |
| 31 | `PUB_STOP_MODE_OPERATOR_TURN_INDICATORS` | `/stop_mode_operator/turn_indicators` (publish) | stop_mode/stop_mode_operator.cpp:141 (publish_turn_indicators_command) |

### Unreachable by configuration

Five markers cannot fire in this image as configured, and
`src/safety_island_tracing/unreachable.yaml` says why:

- ids 12, 14 and 15: the comfortable-stop client call and the operator's
  `operate` callback;
- ids 18 and 19: the two velocity publishers that callback drives.

`mrm_handler.param.yaml` sets `use_comfortable_stop: false`. This is the
contract's "WHY THERE IS NO comfortable_stop RUNG".

Each exemption names the parameter. `trace-check` reads its value from the
resolved model, and if the value changes the exemption lapses and the marker
is required again. No marker is exempted by name alone.

## 3. Recipes (`just/tracing.just`)

| recipe | what it does |
| --- | --- |
| `just trace-gen` | regenerate the header and table from the model; check every marker has a call site |
| `just trace-gen-check` | fail if the committed header or table is stale, or a marker has no call site |
| `just trace-native [secs] [out]` | run the native_sim island for `secs` host seconds (`--stop_at`) on the demo domain. The image writes the buffer to `out` at exit (`--trace-out=`, an `ON_EXIT` native task). Default `build/trace/island.trace` |
| `just trace-demo [out]` | Autoware, a traced island and the demo sequence (as `demo-all`). Prints the VERDICT, then runs `trace-check` on the dump |
| `just trace-decode <file> [zephyr]` | event counts and bytes, the provenance, the first 60 marker/heartbeat records, and `<file>.perfetto.json` for ui.perfetto.dev |
| `just trace-check <file> [zephyr]` | PASS only if: the decode is clean; the provenance names `markers.json`'s table; every marker is seen or exempted by a confirmed parameter; heartbeats are contiguous from 0; and (native_sim) the last recorded heartbeat is the last one emitted, i.e. the buffer did not fill early |
| `just trace-board [out]` | read `ram_tracing` over SWD with `pyocd cmd -t s32k344 -c "savemem <addr> <len> <out>"`, taking the address and length from the ELF symbol, and read `island_trace_hb_seq`. Then `trace-check --zephyr 4.4` |

**`trace-board` has not been exercised.** No image with the tracing block has
been flashed; W6's board runs the W8b image, which has none. The recipe is
written against the ELF built here: `ram_tracing` @ `0x2042fcb3`, 0x4000 B;
`island_trace_hb_seq` @ `0x20425900`. It has never read a board.

**Decoder.** The task named nano-ros's Tonbandgeraet as the decoder. It
cannot decode this trace: it reads only its own COBS-framed binary format,
and has no CTF input. Its checkout in the pin is also empty: only the `.git`
file is present, and the working tree is not checked out. So
`src/safety_island_tracing/island_trace.py` decodes the CTF itself. It takes
every Zephyr event layout from the pinned tree's TSDL
(`subsys/tracing/ctf/tsdl/metadata` for 3.7 or 4.4) and stops on any id it
cannot place rather than resynchronising. For viewing, it writes
Chrome/Perfetto trace-event JSON, which is what Tonbandgeraet's converter
would have produced.

## 4. The gate, native_sim demo

`just trace-demo`: host Autoware 1.5.0 planning_simulator, the traced
native_sim island on domain 10, `demo/scenario_driver.py`.

The gate run is `just trace-demo build/trace/demo3.trace`, on the final
image (with the single-read timestamp fix). Output verbatim:

    VERDICT: PASS -- island stopped the vehicle (4.26 -> 0.00 m/s), MRM recovered, vehicle resumed (1.52 m/s)
    island_trace: 11451659 of 67108864 buffer bytes, 524 heartbeats -> .../build/trace/demo3.trace
    ok   decode: 548808 records, 11451659 bytes, no unknown event id
    ok   provenance: marker table bd6e59bbd17e, contract 3879cbf4e701, zephyr 3.7.0, board native_sim
    ok   markers: 26 of 31 seen at least once; 5 unreachable under the configured parameters
    ok   heartbeat: seq 0..523 contiguous (524 records)
    ok   complete: last heartbeat recorded is the last emitted (524); buffer 11451659 of 67108864 B
    trace-check: PASS

(The scenario prints an em dash after `PASS`; it is written `--` here to keep
this file ASCII.)

Per-marker counts from the earlier passing run, `demo2.trace`: the handler
paths and publishes fired 507 times, the 30 Hz operators 1,536 times,
`call_mrm` 108 times, and `TAKE` 391 times. The emergency-stop client call
and the operator's callback fired 4 times: call at 0.8 s, cancel at 1.0 s
(boot, before the first sample), call at 38.0 s (the fault), cancel at
48.6 s (recovery). In that run the availability samples stop at 37.46 s;
the handler's first `call_mrm` tick is 38.0 s, the 500 ms staleness bound
plus tick phase. These are native_sim times: order and waits only (section 7).

**Three traced runs, two verdicts.**

- `demo.trace`, the first run, **failed the demo** with
  `VERDICT: FAIL (stop=True v 4.26 -> 0.0, mrm=2/2, recover=False, ...)`.
  Its trace passed `trace-check`, and it shows why: after the SIGCONT, the
  island never received another `/system/operation_mode/availability`
  sample. `TAKE` stops at 38.9 s and the run ends at 150.1 s. So the handler
  correctly stayed in MRM, and every timer kept running throughout
  (heartbeats 0..1500 contiguous). That is a DDS rediscovery failure after
  the 10 s SIGSTOP, on the path between the resumed publisher and the island,
  not the island stalling. It is not one of the two flakes in
  `docs/demo-runbook.md`.
- `demo2.trace` passed with the same image.
- `demo3.trace`, the gate above, passed with the final image.

One failure in three runs is not enough to tell a flake from a tracing
effect. It needs a tracing-off baseline of several runs, which this unit did
not build.

**Negative control.** `just trace-native 20` with no Autoware produces a
clean decode and contiguous heartbeats, and `trace-check` reports FAIL with
11 markers missing. Those are the handler's paths, its publishes and the
service pair: the handler never becomes data-ready without Autoware. The
check is not vacuous.

## 5. What the tracing costs

### Bytes per event (from the format, confirmed by the decode)

| record | 3.7 / native_sim | 4.4 / board |
| --- | ---: | ---: |
| marker | 11 B | 12 B |
| heartbeat | 13 B | 14 B |
| thread_switched_in / _out | 29 B each | 30 B each |
| isr_enter / isr_exit / idle | 5 B each (not gated on 3.7) | off |
| provenance, once | 890 B | ~800 B (string 768 B in the board ELF) |

Measured on the gate run, `demo3.trace` (52.5 s of island time, 548,808
records, 11,451,659 B, which is 218 KB/s):

- thread switches are 90.4% of the bytes (357,162 events, 10,357,698 B);
- ISR and idle are 7.4% (169,397 events);
- markers are 2.1% (21,709 events, 238,799 B);
- heartbeats are 0.06%.

With no Autoware attached the island writes 28 KB/s: 565,648 B in 20 s,
30,415 records.

This is why the board buffer is small in time. At a native_sim-like switch
rate, 16 KiB lasts well under a second. Markers alone would be about 4.5 KB/s,
so about 3.6 s. On the board that makes the buffer a boot-and-first-seconds
window unless `TRACING_THREAD` is also cut. That decision belongs to W3/W6,
with a measured board switch rate.

### Interrupts-off time per RAM write (board): an estimate, not a measurement

native_sim cannot measure this. Its CPU runs in zero simulated time: every
marker in one callback carries the same timestamp (for example five markers
at 213.000 ms in the smoke trace), so no duration inside a callback is
observable there.

The estimate below reads the locked path straight out of the board ELF built
here (`arm-zephyr-eabi-objdump`, `build-board/zephyr/zephyr.elf`). A marker
masks interrupts (`BASEPRI` = 16) from `irq_lock()` in `island_trace_marker`
(in ITCM, 0x74 B) to its `irq_unlock`. In between:

1. `sys_clock_cycle_get_32`, called twice (see the finding below). The image
   has `CONFIG_ASSERT` and `CONFIG_SPIN_VALIDATE`, so each call nests its own
   BASEPRI lock around `z_spin_lock_valid`, `z_spin_lock_set_owner`,
   `elapsed()` (a SysTick read) and `z_spin_unlock_valid`: about 60-80
   instructions each.
2. The ns conversion: 160 MHz does not divide 1e9, so it is two `udiv`, an
   `mls`, a `umull`, and `__aeabi_uldivmod` into Rust's `compiler_builtins`
   `u64_div_rem`. That weak symbol wins the link; so does its `memcpy`.
3. Packing: about 10 instructions.
4. `tracing_format_raw_data`: `is_tracing_enabled` (two `dmb`), a nested
   BASEPRI lock, `tracing_buffer_handle`, an indirect call to
   `tracing_backend_ram_output` (bounds check, a 12-byte `memcpy`, a `pos`
   store). The backend itself is about 70 instructions.

**Estimate: 300-450 instructions, which is 2-5 us per marker at 160 MHz**,
with the range covering flash wait states on the non-ITCM callees. Most of it
is the two validated cycle-counter reads and the 64-bit division, not the RAM
write.

A thread switch pays the same timestamp cost plus a 20-byte name copy and a
30-byte `memcpy`, twice per context switch. **Estimate: 5-12 us of extra
masked time per context switch.**

This is to be measured in phase7-W6 by bracketing `island_trace_marker` with
DWT `CYCCNT` on silicon. Until then these numbers are estimates and are
quoted as such.

## 6. Region delta, board image with tracing on

`just board-build`, one build (the knob-convergence second pass relinked
nothing), against the phase-6 baseline in `docs/nxp-deployment.md`:

| region | baseline | with tracing | delta |
| --- | ---: | ---: | ---: |
| FLASH | 623,728 B | 632,852 B | +9,124 B |
| RAM | 302,608 B | 319,904 B (97.63%) | **+17,296 B** |
| ITCM | 12,812 B | 13,788 B | +976 B |
| DTCM | 84,528 B | 84,528 B | 0 |

RAM left: 327,680 - 319,904 = **7,776 B** (it was 25,072 B).

Where the RAM went (`nm -S`):

- `ram_tracing` 16,384 B;
- `island_trace_start()::pkt` 776 B, a static staging copy of the provenance
  record. It could be written in three `tracing_format_raw_data` calls under
  the one lock instead; that has not been done;
- `island_trace_hb_timer` 56 B;
- `tracing_buffer` 33 B and `tracing_ring_buf` 20 B;
- about 30 B of scalars.

ITCM grew because the component code is TCM-relocated and the four inlined
`island_trace_marker` copies came with it. Flash is the CTF thread hooks,
`sys_trace_gpio_*` (compiled although `TRACING_GPIO=n`), the provenance
string and the marker call sites.

## 7. Limits and findings

- **native_sim time is simulated time.** `NATIVE_SIM_SLOWDOWN_TO_REAL_TIME`
  keeps it near wall time between events, but code executes in zero time. A
  native_sim trace gives order and waits (tick phases, the 500 ms detection),
  never execution time. phase7-W4 cannot take a WCET from it.
- **CTF timestamps are u32 nanoseconds**, wrapping every 4.29 s. The decoder
  unwraps by signed modular difference, which is valid because records are
  never 2.1 s apart (the heartbeat is 100 ms). On the board, the 32-bit cycle
  counter at 160 MHz also wraps every 26.8 s. The heartbeat's `uptime_ms`
  exists to re-anchor across that; the decoder does not yet use it.
- **Double counter read.** `k_cyc_to_ns_floor64()` expands its argument
  twice, so `CTF_EVENT`'s `k_cyc_to_ns_floor64(k_cycle_get_32())` reads the
  counter twice. On the board, the seconds come from one read and the
  remainder from the other, so a pair that straddles a second boundary is
  about 1 s off. `island_trace.h` now reads once. Zephyr's own thread-switch
  events still read twice. The board ELF measured above predates the fix,
  which changes only `island_trace_ts`; the native_sim image was rebuilt with
  it (an incremental `ninja` in `build-zephyr`) and re-run (section 4).
- **The board build refuses its own image** on
  `NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS` ("DERIVED but ... never reached the
  resolver"), on both passes. The image links, and the region numbers above
  are from it. The knob is a message-bound fact the tracing block does not
  touch, but no tracing-off build was run to prove the refusal is
  independent of it.
