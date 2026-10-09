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
| lifecycle | `MRM_HANDLER_INIT_DONE` / `_INIT_TIMEOUT` | not the contract: `LIFECYCLE` in gen_markers.py (phase8-W27) |
| nano-ros violation | `NROS_VIOLATION`, `_FQN`, `_MEASURED`, `_DECLARED` (ids 277-280) | not the contract: the executor's contract monitors, forwarded (phase9-W4, section 9) |

Ids run from 1, in that group order and sorted inside each group. The
lifecycle group comes last so no contract id moves; rlm has no element for a
node's start-up. Exactly one of its two markers fires per boot: INIT_DONE
(arg: ms from construction to the tick that found every required input
established) or INIT_TIMEOUT (arg: bits 0-3 the inputs never heard, bits
8-11 those heard but not yet established (phase8-W28); bit 0 availability,
1 operation mode state, 2 comfortable-stop status, 3 emergency-stop status,
and bit 8 + n the same order), so start-up is
told apart from a fault. INIT_TIMEOUT is excused in `unreachable.yaml` as a
fault-path marker (`fault:`), which does not lapse. The output
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

### The marker table (31 markers + 7 forwarded from nano-ros, table sha256 `f796abf8dd6b...`)

Paths are relative to `src/autoware_mrm_*/src/mrm_*/` (comfortable,
emergency, handler) and `src/autoware_stop_mode_operator/src/` (stop_mode).
Line numbers are from `just trace-gen` at this revision (phase9-W4; the
table above this revision was older than the contract: W7's contract
change had not been regenerated); `python3
src/safety_island_tracing/gen_markers.py sites` prints the current ones.

| id | marker | contract element | source site |
| ---: | --- | --- | --- |
| 1 | `PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER_ENTRY` | `/mrm_comfortable_stop_operator/on_timer` (path_entry) | comfortable/mrm_comfortable_stop_operator_core.cpp:149 (onTimer) |
| 2 | `PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER_EXIT` | `/mrm_comfortable_stop_operator/on_timer` (path_exit) | comfortable/mrm_comfortable_stop_operator_core.cpp:151 (onTimer) |
| 3 | `PATH_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE_ENTRY` | `/mrm_comfortable_stop_operator/operate` (path_entry) | comfortable/mrm_comfortable_stop_operator_core.cpp:96 (operateComfortableStop) |
| 4 | `PATH_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE_EXIT` | `/mrm_comfortable_stop_operator/operate` (path_exit) | comfortable/mrm_comfortable_stop_operator_core.cpp:100 (operateComfortableStop) |
| 5 | `PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER_ENTRY` | `/mrm_emergency_stop_operator/on_timer` (path_entry) | emergency/mrm_emergency_stop_operator_core.cpp:143 (onTimer) |
| 6 | `PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER_EXIT` | `/mrm_emergency_stop_operator/on_timer` (path_exit) | emergency/mrm_emergency_stop_operator_core.cpp:152 (onTimer) |
| 7 | `PATH_MRM_HANDLER_CALL_MRM_ENTRY` | `/mrm_handler/call_mrm` (path_entry) | handler/mrm_handler_core.cpp:634 (onTimer) |
| 8 | `PATH_MRM_HANDLER_CALL_MRM_EXIT` | `/mrm_handler/call_mrm` (path_exit) | handler/mrm_handler_core.cpp:653 (onTimer) |
| 9 | `PATH_MRM_HANDLER_DRIVER_EXIT_ENTRY` | `/mrm_handler/driver_exit` (path_entry) | handler/mrm_handler_core.cpp:644 (onTimer) |
| 10 | `PATH_MRM_HANDLER_DRIVER_EXIT_EXIT` | `/mrm_handler/driver_exit` (path_exit) | handler/mrm_handler_core.cpp:650 (onTimer) |
| 11 | `PATH_MRM_HANDLER_ON_TIMER_ENTRY` | `/mrm_handler/on_timer` (path_entry) | handler/mrm_handler_core.cpp:620 (onTimer) |
| 12 | `PATH_MRM_HANDLER_ON_TIMER_EXIT` | `/mrm_handler/on_timer` (path_exit) | handler/mrm_handler_core.cpp:624 (onTimer)<br>handler/mrm_handler_core.cpp:666 (onTimer) |
| 13 | `TAKE_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE` | `/mrm_comfortable_stop_operator/operate` (take) | comfortable/mrm_comfortable_stop_operator_core.cpp:94 (operateComfortableStop) |
| 14 | `TAKE_MRM_HANDLER_CONTROL_MODE` | `/mrm_handler/control_mode` (take) | handler/mrm_handler_core.cpp:267 (onControlMode) |
| 15 | `TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY` | `/mrm_handler/operation_mode_availability` (take) | handler/mrm_handler_core.cpp:233 (onOperationModeAvailability) |
| 16 | `CALL_MRM_HANDLER_COMFORTABLE_STOP_OPERATE` | `/mrm_handler/comfortable_stop_operate` (service_call) | handler/mrm_handler_core.cpp:421 (requestMrmBehavior) |
| 17 | `CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE` | `/mrm_handler/emergency_stop_operate` (service_call) | handler/mrm_handler_core.cpp:425 (requestMrmBehavior) |
| 18 | `SERVE_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE_ENTRY` | `/mrm_comfortable_stop_operator/operate` (service_serve_entry) | comfortable/mrm_comfortable_stop_operator_core.cpp:90 (operateComfortableStop) |
| 19 | `SERVE_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE_EXIT` | `/mrm_comfortable_stop_operator/operate` (service_serve_exit) | comfortable/mrm_comfortable_stop_operator_core.cpp:106 (operateComfortableStop) |
| 20 | `SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_ENTRY` | `/mrm_emergency_stop_operator/operate` (service_serve_entry) | emergency/mrm_emergency_stop_operator_core.cpp:115 (operateEmergencyStop) |
| 21 | `SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_EXIT` | `/mrm_emergency_stop_operator/operate` (service_serve_exit) | emergency/mrm_emergency_stop_operator_core.cpp:123 (operateEmergencyStop) |
| 22 | `PUB_MRM_COMFORTABLE_STOP_OPERATOR_CLEAR_VELOCITY_LIMIT` | `/mrm_comfortable_stop_operator/clear_velocity_limit` (publish) | comfortable/mrm_comfortable_stop_operator_core.cpp:143 (publishVelocityLimitClearCommand) |
| 23 | `PUB_MRM_COMFORTABLE_STOP_OPERATOR_MAX_VELOCITY_CANDIDATES` | `/mrm_comfortable_stop_operator/max_velocity_candidates` (publish) | comfortable/mrm_comfortable_stop_operator_core.cpp:131 (publishVelocityLimit) |
| 24 | `PUB_MRM_COMFORTABLE_STOP_OPERATOR_STATUS` | `/mrm_comfortable_stop_operator/status` (publish) | comfortable/mrm_comfortable_stop_operator_core.cpp:114 (publishStatus) |
| 25 | `PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD` | `/mrm_emergency_stop_operator/emergency_control_cmd` (publish) | emergency/mrm_emergency_stop_operator_core.cpp:137 (publishControlCommand) |
| 26 | `PUB_MRM_EMERGENCY_STOP_OPERATOR_STATUS` | `/mrm_emergency_stop_operator/status` (publish) | emergency/mrm_emergency_stop_operator_core.cpp:131 (publishStatus) |
| 27 | `PUB_MRM_HANDLER_HAZARD_LIGHTS_CMD` | `/mrm_handler/hazard_lights_cmd` (publish) | handler/mrm_handler_core.cpp:314 (publishHazardCmd) |
| 28 | `PUB_MRM_HANDLER_MRM_STATE` | `/mrm_handler/mrm_state` (publish) | handler/mrm_handler_core.cpp:321 (publishMrmState) |
| 29 | `PUB_MRM_HANDLER_TAKEOVER_REQUEST_STATE` | `/mrm_handler/takeover_request_state` (publish) | handler/mrm_handler_core.cpp:335 (publishTakeoverRequestState) |
| 30 | `MRM_HANDLER_INIT_DONE` | `/mrm_handler/init` (lifecycle_done) | handler/mrm_handler_core.cpp:563 (updatePhase) |
| 31 | `MRM_HANDLER_INIT_TIMEOUT` | `/mrm_handler/init` (lifecycle_timeout) | handler/mrm_handler_core.cpp:575 (updatePhase) |

**Forwarded from nano-ros (phase9-W4, section 9).** Not contract elements
and not call sites in the island: the executor emits them, and the sink in
`include/island_trace.h` writes them at island id = 256 + nano-ros id.

| id | marker | nano-ros id | arg |
| ---: | --- | ---: | --- |
| 274 | `NROS_TIMER_START` | 18 | timer slot; the bound timer only (phase9-W4 rerun) |
| 275 | `NROS_TIMER_END` | 19 | timer slot; the bound timer only |
| 277 | `NROS_VIOLATION` | 21 | seq << 8 | rule code (RULE_IDS index + 1) |
| 278 | `NROS_VIOLATION_FQN` | 22 | FNV-1a 32 of the endpoint ref |
| 279 | `NROS_VIOLATION_MEASURED` | 23 | measured |
| 280 | `NROS_VIOLATION_DECLARED` | 24 | declared |
| 281 | `NROS_TAKE` | 25 | input index << 24 \| take seq (phase9-W4 rerun; nano-ros: slot << 24 \| seq) |
| 282 | `NROS_TAKE_STAMP_SEC` | 26 | the sample's source stamp sec, only when it changed for that input |
| 283 | `NROS_TAKE_STAMP_NSEC` | 27 | the sample's source stamp nanosec |

The takes (nano-ros phase-474 I3) are forwarded only for the inputs in
`markers.json` `nros.take_inputs`: 0 `/mrm_handler/kinematic_state`, 1
`/mrm_handler/operation_mode_state`, 2
`/mrm_emergency_stop_operator/control_cmd` (one in three). The sink learns
each input's slot from the take it saw just before the input's callback
(`ISLAND_TRACE_TAKE_BIND`, `include/island_trace.h`; a C/C++ subscription
registers as `sub#N`), turns on the stamp at offset 4
(`nros_trace_set_take`), and puts the input's index where nano-ros had the
slot. `island_trace.py takes` lists them; `merge.py` writes `take` events.

The dispatch events 18/19 (callback start, end) are dropped for every slot
but one: the timer bound by `ISLAND_TRACE_TIMER_BIND` (the emergency
operator's 30 Hz timer, sampled every tick by
`nros_trace_set_timer_every(slot, 1)`) is forwarded at 274/275, so the trace
holds that timer's tick-to-tick spacing, with
`CONFIG_ISLAND_TRACE_TIMER_TICKS=y` (off in the board and QEMU confs) (phase9-W4 rerun: the 29773/30000
mHz rate readout on its two topics). `island_trace.py ticks` prints the
start-to-start spacing (count, mean, min, max, histogram at 1 ms bins, every
gap of 1.5 means or more) and the callback duration; `check` reports the
count and mean. Cost: two 12-byte records per tick, 720 B/s at 30 Hz, about
as much again as the rest of the window (section 8): in run `w4r-ticks`
the 40 KiB buffer filled ~34 s after the trigger and `check` failed
`complete`, hence off by default. merge.py and render.py do not read them.

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
| `just trace-board [out] [elf]` | phase8-W17: `tools/timeline/readout.py --target board`: halt, read `ram_tracing` and the heartbeat and window counters over SWD (pyocd, attach mode), resume; every address from the ELF's symbol table; the buffer wrapped in the native_sim dump's header; then `trace-check` |
| `just trace-window-native-build` | phase8-W17: the native_sim island with the trace window (`src/native_sim_entry/trace-window.conf`), into build-zephyr |
| `just trace-qemu-build` | phase8-W17: the QEMU island with the board's tracing block and window (`src/qemu_entry/trace.conf`), into build-qemu-trace |

**`trace-board` has not been exercised against a board** (phase8-W17 did not
touch it; W10 held it). The same readout code, with the QEMU monitor in place
of pyocd, has read the QEMU island (section 8).

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

## 8. The trace window (phase8-W17)

Gap G9 of docs/roadmap/phase-8-rtss-work-demo.md: the board's RAM buffer
filled from boot and held seconds, but act B lasts 20-30 s and the encore
about 10 s. The fix is in `include/island_trace.h`, switched on by
`CONFIG_ISLAND_TRACE_WINDOW` (`src/safety_island_tracing/Kconfig.island_trace`,
sourced by each entry's `Kconfig`). It is on in the board conf and in
`src/qemu_entry/trace.conf`; native_sim keeps the phase-7 stream by default
and takes the window from `src/native_sim_entry/trace-window.conf`.

### Design

Three parts, all in the one translation unit that carries the runtime:

- **A pre-trigger ring.** Until the trigger, nothing but the provenance
  enters the stream. Markers and heartbeats go, already in their stream
  form, into a 2 KiB ring of two halves (`CONFIG_ISLAND_TRACE_PRE_BYTES`),
  each filled linearly with whole records; when one half is full the other
  is cleared and becomes current. At the trigger the older half and the
  current one are walked by timestamp only, and the records of the last
  `CONFIG_ISLAND_TRACE_PRE_MS` (1500 ms) go into the stream in **two**
  `tracing_format_raw_data` calls, a memcpy each in the RAM backend.
  Writing them one by one would have held `irq_lock` for one backend call
  per record, some 50-70 of them, at the moment the island reacts.
- **The trigger**, generated from the contract (`gen_markers.py`): the ENTRY
  of the detector path, the input-triggered path whose input is a topic in
  some hazard's `guards:` (`/mrm_handler/call_mrm`, id 7), once the ARM
  marker, the take of that guarded input (`TAKE_..._OPERATION_MODE_AVAILABILITY`,
  id 15), has carried a non-zero arg: once the HPC has said "autonomous
  available". Without the arm the boot-time `call_mrm` ticks (availability
  not yet autonomous, or stale before Autoware is up) fire it; in the W8a
  and W14 native_sim traces they do, from 0.0 s to 4.2 s after boot. Both
  hazards reach the detector path: `odd_exit` on the tick after the first
  `autonomous: false`, `hpc_loss` 500 ms plus a tick after the last sample.
  One TRIGGER record follows the history:
  `u32 ts | id+3 | u16 marker | u16 pre_ms | u16 pre_kept | u16 spin_keep |
  u32 pre_lost | u32 filtered` (22 B on the board).
- **A record policy per marker**, generated from the contract into
  `ISLAND_TRACE_POLICY_TABLE`, applied before and after the trigger:
  `every` for non-timer paths, service calls and callbacks, and the take of
  a hazard-guarded input (its gaps are the detection measurement); `change`
  for every other take and every publish (recorded when the arg differs
  from the last recorded one of that marker); `spin` for timer-path
  ENTRY/EXIT (recorded when the ENTRY arg changed, or on every tenth tick,
  `CONFIG_ISLAND_TRACE_SPIN_KEEP`; the EXIT follows its ENTRY's decision).
  At the trigger the `change` and `spin` state is cleared, so the first of
  each after the fault is always kept: "the first X after the fault", which
  is what `analysis.py` and `merge.py` read, never depends on the history.
  Every edge they use survives: the guarded take at full rate (the encore's
  last sample and anchor 2), the changes of the takeover-request state and
  `mrm_state` (anchor 1 and the pair refinement), the first velocity limit,
  the first braking command, the first MANUAL, every service call and
  callback, `call_mrm` and `driver_exit`.

Two smaller changes ride with it. The island's stamp now comes from the
64-bit cycle count where the timer has one (the board does, at 160 MHz):
from the 32-bit count the u32 ns value stepped back by 2^30 ns every 2^32
cycles, 26.8 s at 160 MHz, which no modular unwrap can absorb and which an
act crosses. And the provenance is written as two raw writes under one lock
instead of from a 776 B static staging copy (section 6).

The decoder (`island_trace.py`) reads the TRIGGER record, starts a new
segment after a windowed provenance (the gap to the first flushed record is
unknown) and anchors it on the first heartbeat's `uptime_ms`; `check` then
asks for the trigger instead of every marker, heartbeats contiguous from
the first one kept, and reports the window: history, record rate after the
trigger in this trace's bytes and in the board's, and how long 16, 24 and
32 KiB hold at that rate. `wrap` puts a raw target read into the native_sim
dump's header with the heartbeat counter read beside it, so the `complete`
check works off the host too.

### Sizing, from the measured rate

Replayed first over the W8a and W14 native_sim traces (window off, every
marker from boot; the policy applied offline to the recorded stream), in the
board's record format (12 B a marker, 14 B a heartbeat):

| policy | after the trigger | seconds of act per KiB | 1.5 s of history |
| --- | ---: | ---: | ---: |
| every marker (phase 7) | 3.2-3.4 KB/s | 0.30 | about 2.2 KB |
| window, `spin_keep` 1 (only CHANGE applied) | 1.65-1.69 KB/s | 0.61-0.62 | about 2.2 KB |
| window, `spin_keep` 10 (the board's) | 576-606 B/s | 1.69-1.78 | 486-582 B |

over w8a-a, w8a-b, w8a-e, w14-b3 and w14-e. The largest remaining shares
after the trigger are `call_mrm` (ENTRY and EXIT on every handler tick while
a fault holds, 8.5 Hz), the guarded take (10 Hz) and the heartbeat (10 Hz,
23 % of the bytes).

The board's buffer is therefore set to **32 KiB**: at 606 B/s, less the
provenance (about 1 KB), the history and the trigger record, it holds about
51 s after the trigger. Act B, the longest act, ran 20-30 s from the button
to standstill and odd-enter (W7 b5-b8, W8a, W17 below).

The board image with the window and the 32 KiB buffer links (`just
board-build` on `ed2e193`, W17, not flashed): RAM 287,320 of 327,680 B
(87.68 %), **40,360 B free**; FLASH 609,100 B; ITCM 11,516 B; DTCM 61,528 B.
The tracing objects in RAM total 35,170 B: `ram_tracing` 32,768, the ring
`island_trace_pre` 2,048, and 354 B of state, counters and the heartbeat
timer; the provenance string (950 B) and the policy table (30 B) are in
flash. (`board-size`'s ram_report failed on the host: the 4.4 venv lacks
the `anytree` module; the region table is the linker's.)

### Verification: full acts on native_sim and QEMU

All on the tree rebased onto `ed2e193` (nano-ros `da272e419`, the C++ gate),
under the demo lock. The table's "after the trigger" figures are
`island_trace.py check`'s, in the board's record format; `merge.py` and
`analysis.py` (through `render.py --table`) read every trace.

| run | target | act | VERDICT | history kept | after the trigger | board bytes | rate | analysis |
| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| w17-nb4 | native_sim | B | PASS | 44 records, 1474 ms | 959 records, 19.73 s | 11,902 | 603 B/s | 15 of 15 rows PASS |
| w17-ne3 | native_sim | encore | PASS | 41 records, 1477 ms | 191 records, 4.13 s | 2,374 | 575 B/s | 8 of 8 PASS |
| w17-qb5 | QEMU (run-board.sh) | B | PASS | 42 records, 1459 ms | 1065 records, 21.74 s | 13,214 | 608 B/s | 10 of 15 PASS, see below |
| w17-qe1 | QEMU (run-board.sh) | encore | PASS | 41 records, 1440 ms | 206 records, 4.47 s | 2,562 | 573 B/s | 8 of 8 PASS |

Every trace: `trace-check: PASS` (clean decode, the provenance's table,
heartbeats contiguous from the first one kept, the last heartbeat recorded
is the last emitted, one TRIGGER). Fixed cost on the board's format: the
provenance (about 1,075 B), the history (522-558 B) and the trigger (22 B).
With them, act B took 13,554-14,845 B of the board's 32 KiB, and the
measured rates put 32 KiB at 51-54 s after the trigger.

The island's edges the analysis reads all came from the window: in w17-nb4
`island_take` 88.24 ms (the guarded take, in the history), `tor_on` 162.21,
`tor_off` 10163.22, `call` 10163.21, `safe_cmd` 10163.22 ms from the button;
in w17-ne3 the last sample before the silence (-29.79 ms, from the history,
anchor 2), `detect_tick` 544.18 and `safe_cmd` 574.18 ms.

QEMU's five FAIL rows in w17-qb5 are timing, not the trace: the takeover
route, 111.79 ms against 110, and the windows row that contains it (10111.79
against 10110), and three `host` rows 49-61 ms over, with a publish/receipt
pair spread of 140.5 ms (native_sim: 1.9 ms). The QEMU
guest runs on TCG without `icount` and its clock is not the host's; the
same rows on the island clock pass. The encore's rows all pass on QEMU.

Two faults of the first version, both found by these runs and fixed:

- **The history's age in u32.** The first native encore (`w17-ne1`) kept
  records 5.3 s old and dropped the 1 s after them: `now - ts` in u32 wraps
  every 4.29 s and a ring half lasts about 3 s at the pre-trigger rate, so a
  5.3 s-old record looked 1.0 s old. `island_trace_fire` now sums the u32
  differences of consecutive records (a heartbeat enters the ring every
  100 ms, so each is small) into a 64-bit age. `w17-ne2` onward: contiguous.
- **More than one onset.** In `w17-nb2` the availability flapped to
  `autonomous: false` for single samples before and after the act; each flap
  is a real takeover-request tick and the first one after the arm triggers
  the window (37 s before the button in that run; it still held the act).
  `merge.py` took the LAST onset as anchor 1, a flap, and put the offset
  34 s off. It now takes the onset whose offset explains the most
  publish/receipt pairs (`best_onset`); the W8a and W14 runs merge to the
  same offsets as before.

A negative control: the windowed native_sim island alone for 15 s (`just
trace-native 15`, no Autoware) never triggers; the dump holds the provenance
and `check` says `FAIL window: ... no TRIGGER record`.

### The QEMU island, and what differs from the board

`src/qemu_entry/trace.conf` is the board's tracing block with one
difference, the buffer: 1 MiB instead of 32 KiB. The QEMU island's link is
Ethernet, and Zephyr 4.4's IP core emits `net_send_data`/`net_recv_data`
CTF events through `SYS_PORT_TRACING_FUNC`, which no Kconfig masks
(`CONFIG_TRACING_NETWORKING=n` does not; the type masks act on the `OBJ_`
macros only). They enter the stream from boot, 22 B each: 32 KiB filled in
14.5 s with no Autoware attached, before any trigger (w17 smoke run). The
board's link is the UART with no IP stack (`CONFIG_NETWORKING` is unset in
the board image), so it has none of them. The island's own bytes after the
trigger, which is what 32 KiB must hold, are reported separately by `check`.

The QEMU runs also used a 1 MiB heap
(`CONFIG_NROS_ZEPHYR_HEAP_SIZE=1048576 just --set QEMU_BUILD_DIR
build-qemu-trace qemu-build` with `EXTRA_CONF_FILE`, W3's precedent): at
102,400 B the QEMU island died 7.3-8.0 s after boot, when Autoware joined,
with `HEAP EXHAUSTED` in `_z_slice_init` from `zpico_read`, both straight
into the stock router and behind the gateway (runs w17-qb1, w17-qb2). Over
TCP nothing paces Autoware's traffic the way the board's UART does.

`tools/timeline/run-board.sh --target qemu` puts the QEMU island behind the
gateway router exactly as the board is: `demo/l3/router/island-gateway.json5`
with its island face moved from `serial` to `unixsock-stream` (so the
no-graph rule and the downsampling apply to it), and QEMU's `guestfwd` piped
into that socket by `socat`. The trace is read over QEMU's monitor
(`readout.py --target qemu`: `stop`, `xp`, `pmemsave`, `cont`), from the same
ELF symbols the board read uses.

### What is not verified

- W17 did not touch the board. phase8-W8 has since run the board steps
  (docs/takeover-trace.md section 9): the flash (`pyocd flash`), the
  gateway on the UART and the reset, and the SWD read (`readout.py
  --target board`) worked unchanged in 13 acts and one bring-up run.
  Every trace gave `trace-check: PASS`. After the trigger the board wrote
  534-607 B/s, and each read halted the core for 0.18-0.23 s.
- The interrupts-off cost of the flush at the trigger is not measured. It is
  two `tracing_format_raw_data` calls (memcpy of at most 2 KiB) after a walk
  of at most about 170 records that reads timestamps, all under the marker's
  `irq_lock`; the board's DWT bracket (`island_trace_cost_*`) will include it
  in its maximum.
- The trigger fires once per boot. A second act needs a reset, as
  `run-board.sh` does (it flashes and resets for every act).

### One traced act off the host: `tools/timeline/run-board.sh`

```
just board-build                                   # the image with the window
flock <demo lock> tools/timeline/run-board.sh b <id>          # the board (phase8-W8)
flock <demo lock> tools/timeline/run-board.sh --dry-run b <id> # print the steps, resolve the addresses
just trace-qemu-build
flock <demo lock> tools/timeline/run-board.sh --target qemu b <id>   # the rehearsal
just l3-traced-act b <id> [target] [elf] [flags]   # the same, as a recipe
```

It flashes (board), starts the stock router, the island's link (the gateway
on the UART and a reset; for QEMU the same gateway config on a unix socket),
waits for the island's first operator status sample, starts Autoware in the
container (one restart if it sits at "still constructing"), the gate, the
probe and the act, reads the trace out, tears down only what it started, and
writes `build/timeline/<id>/` as `run-native.sh` does: `island.trace` (+
`.raw`, `.meta`, `.readout.json`, `.check.txt`), the JSONL files,
`island.jsonl`, `explain.txt`, `table.md`, `timeline.png`. The QEMU runs above
are its output.

Also changed with the window: the component libraries of the two 4.4 entries
are ordered after Zephyr's generated headers (a parallel build compiled a
component, which includes `<zephyr/kernel.h>` once tracing is on, before
`zephyr/heap_constants.h` existed); and `experiments/reaction-trace/stop-island.sh`
signals the island that writes this run's trace instead of the first
`build-zephyr/zephyr/zephyr.exe` on the host (run w17-nb3 signalled another
process and lost its dump).

## 9. Contract violations in the trace (phase9-W4)

nano-ros's executor judges the contract's runtime rules (rate, age,
silence, latency, timer overrun, release jitter) every spin, and from
phase-474 I1 (pin `5b3ac4567`, PR #1729) it emits every STORED violation, at
detection, as four trace events through the callback trace sink
(`nros_set_trace_sink`, `CONFIG_NROS_TRACE_CALLBACKS`):

| nano-ros id | arg |
| ---: | --- |
| 21 | `seq << 8 \| rule code` (rule code = `monitor::RULE_IDS` index + 1) |
| 22 | FNV-1a 32 of the endpoint ref (`/mrm_handler/mrm_state`; `timer`, `spin` for the rules with no endpoint) |
| 23 | measured (per rule: mHz, ms, dropped activations, us) |
| 24 | declared, same unit |

**The id collision, and how it is resolved.** nano-ros numbers its events
16-24 (16-20 are the per-dispatch register/start/end/name events); the
island's markers are generated from the contract as 1..N (N = 31 today).
Both cannot share one id space. The island ids do not move: every recorded
trace, `markers.json`, `merge.py`, `analysis.py` and the experiments key on
them. Instead the island installs its own sink (`island_trace_nros_sink`,
`include/island_trace.h`, at `SYS_INIT` before any entity registers) that
keeps only 21-24 and writes each at island id `ISLAND_TRACE_NROS_BASE` (256)
+ nano-ros id, so 277-280, through the same `ISLAND_TRACE` path as every
marker (the trace window, the record policy, the self-cost bracket). The
dispatch events 16-20 are dropped at the id test: a record per callback
would fill the board's buffer, and the paths the island measures carry
their own ENTRY/EXIT. `gen_markers.py` reads the four ids and `RULE_IDS`
from the pinned `monitor.rs` and hashes the contract's endpoint refs into
`markers.json` (`nros`: `base`, `markers`, `rule_ids`, `endpoint_hashes`), all
inside the table digest; it refuses a contract that reaches id 256. The
policy table gives every id above the island's count the `every` policy.

**A violation opens the trace window.** A stored violation is a second
trigger beside the detector path's ENTRY: whichever comes first flushes the
pre-trigger history (the callbacks before the verdict) and starts the
stream, and the TRIGGER record names `NROS_VIOLATION` (id 277). An act that
follows is still recorded whole: in run `w4-encore` the window opened at the
first post-arming verdict (6.8 s after boot), the act came 31 s later, and
the 32 KiB buffer held 17,062 B of it with every row of the analysis
present (docs/takeover-trace.md section 12).

**Decoding.** `island_trace.py` joins each run of 277-280 into one
violation and names it: the rule from `rule_ids`, the endpoint from
`endpoint_hashes` (a hash not in the table prints as `fqn#xxxxxxxx`).
`island_trace.py violations <trace>` lists them with the island time;
`check` reports them (`info violations: N ...`) without failing, since a
violation is a finding of the run, not a fault of the trace; `decode
--timeline` prints the decoded verdict beside its marker. `merge.py` writes
each as an `island` `violation` event on the host clock, and `render.py`
draws it as a dashed vertical line labelled with rule, endpoint and
measured/declared.

**The SWD record beside it.** The same verdicts go, at detection, into
nano-ros's `NROS_VIOLATION_RECORD` (`CONFIG_NROS_BOOT_REPORT`), read by
symbol by `tools/timeline/violations.py` and, inside its halted read, by
`readout.py`, which writes `violations.txt` into every run directory. The
record keeps the latest `CONFIG_NROS_EXECUTOR_MAX_VIOLATIONS` (8) and the
counts (total, dropped, suppressed_before_arm, armed); the trace keeps
every verdict after the window opened, which is how runs with more than 8
can be read whole (`w4-bringup2`: 17 in the trace, 8 in the record).

