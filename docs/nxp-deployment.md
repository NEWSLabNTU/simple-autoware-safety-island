# The safety island on NXP S32K344, via nano-ros

What the MR-CANHUBK344 image actually contains: which nodes run, where every
byte of RAM goes, and which parts of the launch contract reach the operating
system.

| | |
| --- | --- |
| Board | MR-CANHUBK344, NXP S32K344, Cortex-M7 r1p2, v7.0-M |
| Zephyr board string | `mr_canhubk3/s32k344` |
| Zephyr | 4.4.0, SDK 1.0.1 (`arm-zephyr-eabi` 14.3.0) |
| RMW | zenoh (`-S nros-zenoh`), serial link (`-S island-serial`) |
| nano-ros pin | `f8655e9b7` |
| Island commits | `07ffdb7`, `20bc6d9`, `368b766` |
| Status | configures, compiles and links; **over RAM budget with the parameter server on** |

The same four nodes and the same contract also build for `native_sim` over
CycloneDDS, and that image is verified end to end:
`VERDICT: PASS -- island stopped the vehicle (4.24 -> 0.00 m/s), MRM recovered,
vehicle resumed (1.43 m/s)`, with `MrmState` reaching `state=2 behavior=2`
(EMERGENCY_STOP) and returning to NORMAL. Nothing below has run on silicon; the
board is blocked on the MCU-Link probe, so every board number here is from the
linker and the map file, not from a running target.

---

## 1. The nodes

Four nodes, all four on the island image. `src/safety_island_bringup/system.toml`
names them as components; `safety_island.contract.yaml` declares their
endpoints; `src/zephyr_entry/CMakeLists.txt:102-105` builds them and
`:166-169` relocates all four into ITCM.

### mrm_handler -- the arbiter

Watches operation-mode availability, odometry, control mode and both operators'
statuses, decides which MRM behaviour to run, calls that operator over
`OperateMrm`, and publishes the resulting MRM state plus emergency gear, hazard
and turn-indicator commands.

- Timer 10 Hz. Publishes, in order: `mrm_state`, `turn_indicators_cmd`,
  `hazard_lights_cmd`, `gear_cmd_out`, `emergency_holding`.
- 7 subscriptions, all 10 Hz depth 1: `operation_mode_availability`,
  `kinematic_state`, `control_mode`, `comfortable_stop_status`,
  `emergency_stop_status`, `gear_cmd_in`, `operation_mode_state`.
- 5 publishers, all 10 Hz. 0 service servers, **2 service clients**
  (`comfortable_stop_operate`, `emergency_stop_operate`).
- 11 declared parameters.

### mrm_emergency_stop_operator

Passes the latest control command through while idle; once operated, ramps
longitudinal acceleration and jerk down to `target_acceleration` /
`target_jerk` each tick.

- Timer 30 Hz, outputs `emergency_control_cmd` and `status`.
- 1 subscription (`control_cmd`, 30 Hz depth 1), 2 publishers (30 Hz).
- 1 service server: `/system/mrm/emergency_stop/operate`.
- 3 parameters.

### mrm_comfortable_stop_operator

On an `operate` call publishes a `VelocityLimit` built from
`min_acceleration` / `max_jerk` / `min_jerk` so the planner decelerates
comfortably, and a clear command on cancel.

- Timer 10 Hz, output `status` only.
- 0 subscriptions, 3 publishers, 1 service server
  (`/system/mrm/comfortable_stop/operate`).
- 4 parameters.
- Note: `max_velocity_candidates` and `clear_velocity_limit` carry
  `min_rate_hz: 10` but are **event-driven**, not timer-driven -- they fire on a
  service transition. The contract's timer output list deliberately excludes
  them. Anyone sizing from `min_rate_hz` should know this.

### stop_mode_operator

Emits a continuous hold-still command set at 30 Hz: zero-velocity control at
`stop_hold_acceleration` with current steering, gear (PARK once stopped and the
route is UNSET/ARRIVED if `enable_auto_parking`), indicators DISABLE.

- Timer 30 Hz, 3 subscriptions (30 Hz depth 1), 4 publishers (30 Hz).
- No services either direction. 3 parameters.

### Totals

| Entity | Count |
| --- | ---: |
| Publishers | 14 |
| Subscriptions | 11 |
| Service servers | 2 |
| Service clients | 2 |
| Timers | 4 (one per node) |
| **Entities** | **33** |
| Declared parameters | 21 |

Two topics are fully internal to the island
(`/system/mrm/{comfortable,emergency}_stop/status`); 9 are inbound from
Autoware and 12 outbound to it. Both services are internal.

---

## 2. Contract counts become static pools

Every static pool in the image is derived from a count in the contract. Nothing
in the list below is a hand-tuned number, and each one is reported at configure
time as `DERIVED from this image's entity inventory`.

| Contract fact | Derived knob | Value |
| --- | --- | ---: |
| 14 publishers | `NROS_MAX_PUBLISHERS` | 14 |
| 11 subscriptions | `NROS_MAX_SUBSCRIBERS` | 11 |
| 11 subscriptions | `NROS_RMW_SUBSCRIBER_SLOTS` | 11 |
| 11 subs + 4 timers + 2 SS + 2 SC | `NROS_EXECUTOR_MAX_CBS` | 19 |
| 4 nodes | `NROS_EXECUTOR_MAX_NODES` | 4 |
| 6 param services x 4 nodes + 2 SS | `NROS_MAX_QUERYABLES` | 26 |
| 21 params + one `use_sim_time` per node | `NROS_MAX_PARAMETERS` | 25 |
| longest declared parameter name | `NROS_MAX_PARAM_NAME_LEN` | 35 |
| largest message bound | `NROS_SUBSCRIPTION_BUFFER_SIZE` | 1496 |
| no string/array parameters declared | `MAX_STRING_VALUE_LEN`, `MAX_ARRAY_LEN`, `MAX_BYTE_ARRAY_LEN` | 0 |

`33 entities declared, 19 of them claim a callback slot` is the configure-time
line that ties the first block together.

---

## 3. Memory layout

### Regions

| region | start | end | size | notes |
| --- | --- | --- | ---: | --- |
| `itcm` | `0x00000000` | `0x0000ffff` | 64 KiB | zero-wait, CPU only, no DMA |
| `pflash` | `0x00400000` | `0x007fffff` | 4 MiB | top 48 KiB faults on read |
| `dflash` | `0x10000000` | `0x1001ffff` | 128 KiB | unused by this image |
| `dtcm` | `0x20000000` | `0x2001ffff` | 128 KiB | zero-wait, CPU only, no DMA |
| `sram` | `0x20400000` | `0x2044ffff` | **320 KiB** | the binding constraint |

320 KiB of SRAM is what everything competes for. The 4 MiB of flash is barely
touched (14% used).

### What is relocated, and why

`src/zephyr_entry/CMakeLists.txt`:

```
zephyr_code_relocate(LIBRARY app                            LOCATION DTCM_BSS)
zephyr_code_relocate(LIBRARY mrm_handler_lib                   LOCATION ITCM_TEXT)
zephyr_code_relocate(LIBRARY stop_mode_operator_lib            LOCATION ITCM_TEXT)
zephyr_code_relocate(LIBRARY mrm_emergency_stop_operator_lib   LOCATION ITCM_TEXT)
zephyr_code_relocate(LIBRARY mrm_comfortable_stop_operator_lib LOCATION ITCM_TEXT)
```

DTCM takes the entry's `.bss` -- executor storage plus the four per-node
component buffers. ITCM takes the four MRM node bodies. The constraint that
decides what may move is **DMA reachability**: neither TCM is reachable by the
DMA masters, so Ethernet descriptors and the `net_pkt` / `net_buf` pools must
stay in SRAM. The relocation must not be extended to the net stack.

ITCM is not a throughput win -- the I-cache is already on. It buys
**determinism**: code in ITCM is zero-wait always, with no miss to jitter an
MRM decision that follows an idle period, and it stops competing for cache
lines with the net stack and the Rust executor. For a safety island the worst
case is the number that matters.

Both relocations depend on `patches/zephyr/0001-gen_relocate_app-fix-source-to-object-matching`.
Stock Zephyr 4.4 cannot relocate a source generated into the build root: on no
match it writes an empty fragment, prints nothing, and exits 0. Without the
patch these lines link fine and relocate nothing. **Verify by the region
report, never by the build succeeding.**

### Where the RAM goes

Largest consumers, from `zephyr_pre0.map` of the real derived configuration:

| bytes | symbol | what it is |
| ---: | --- | --- |
| 115,128 | `nros_rmw_zenoh::shim::service::SE...` | service inbox table, 26 x 4,428 |
| 95,928 | `nros_platform::zephyr_heap::HEAP` | nano-ros heap |
| 40,960 | `nros_thread_stacks` | task stacks (noinit) |
| 38,720 | `nros_rmw_zenoh::shim::subscriber...` | subscriber slots, 11 x 3,520 |
| 24,992 | `g_sessions` | zenoh-pico session pool |
| 16,384 | `z_main_stack` | Zephyr main (noinit) |
| 11,264 | `nros_rmw_cffi::rust_adapter::st...` | cffi adapter state |
| 8,268 | `kheap__system_heap` | Zephyr system heap (noinit) |

Every one of those traces to a stated knob:

```
nros_thread_stacks  40,960 = TASK_SLOTS 5 x TASK_STACK_SIZE 8192   exact
z_main_stack        16,384 = CONFIG_MAIN_STACK_SIZE                exact
system_work_q        4,096 = CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE    exact
kheap__system_heap   8,268 = CONFIG_HEAP_MEM_POOL_SIZE 8192 + 76
zephyr_heap HEAP    95,928 = CONFIG_NROS_ZEPHYR_HEAP_SIZE 94208 + 1720
service table      115,128 = MAX_QUERYABLES 26 x (4 x 1024 + 332)  exact
subscriber table    38,720 = MAX_SUBSCRIBERS 11 x 3,520            exact
```

---

## 4. The contract sizes the image; it does not schedule it

Worth stating plainly because it is easy to assume otherwise: `rate_hz` and
`min_rate_hz` feed buffer sizing, callback counts and liveliness. On this image
they produce **no thread, no priority and no deadline**.

That is not because the machinery is missing. The derivation chain is complete
and is real code -- it is gated shut one link from the end.

### The chain, and where it stops

```
contract  paths.on_timer.trigger.timer.rate_hz
   |      (resolver drops it -- see below)
   v
nros-orchestration-ir  mapper_input.rs:70-80   EffectiveTrigger::Timer
   v
derive.rs:52  derive_tiers_from_contracts -> chain_aware_rank -> realize_rtos
   v
[tiers.derived-<node>]  ->  entry_tiers.rs  ->  nros_zephyr_tier_task_create
```

`derive.rs:97-101` is the gate:

```rust
let Some(groups) = callback_groups.get(&node).filter(|g| !g.is_empty()) else {
    out.groupless_notes.push(n.name.clone());
    continue;
};
```

`build-board/nros-metadata.json` carries `"callback_groups": []` for all four
components. All four land in `groupless_notes`, the derived schedule comes out
empty, and the generated entry
(`build-board/zephyr_entry_nros_main_generated.cpp:182`) ends at
`run_components(...)` -- **not `run_tiers`**. No tier is spawned.

Four independent confirmations: empty `callback_groups` in the metadata, no
`execution:` key in the resolved model, `run_components` in the generated
entry, and the discarded tier sections in the map.

### The trigger rate is dead data

The resolver flattens `on_timer` into `contracts.node_paths` with an empty
`input` and **no rate** (`build/nros/models/safety_island_bringup/system_model.yaml:343-360`
carries `output:` only). The rate is then reconstructed downstream from
`contracts.pub_endpoints[*].min_rate_hz` of the first output endpoint
(`mapper_input.rs:46-52`).

So the number that would reach a scheduler is the `min_rate_hz` under `pub:`,
not the one under `trigger.timer`. For this island they agree (10 and 30), so
the divergence is invisible here -- but only by coincidence.

### What the rates would buy, if callback groups existed

Tier assignment is rate-monotonic and **per node, not per callback**. Budget is
the period; the sort is ascending milliseconds
(`chain_aware_mapper.rs:350-360`); the dense rank becomes the Zephyr priority
verbatim, because Zephyr's caps are `low_number_is_high: true`
(`rtos_realizer.rs:165-175`).

| node | period | rank | Zephyr priority |
| --- | ---: | ---: | ---: |
| mrm_emergency_stop_operator | 33.33 ms | 0 | 0 |
| stop_mode_operator | 33.33 ms | 0 | 0 |
| mrm_comfortable_stop_operator | 100 ms | 1 | 1 |
| mrm_handler | 100 ms | 1 | 1 |

That is a projection of the code above, not a measurement -- the derivation
never fires. No code anywhere assigns an individual subscription callback to a
tier by its own rate; a callback reaches a tier only through the group its
author declared.

### The threads that do exist

Not `k_thread_create`. nano-ros creates **POSIX pthreads with a caller-supplied
stack** -- `pthread_attr_setstack(&attr, &nros_thread_stacks[slot], ...)` then
`pthread_create` (`nros_platform_zephyr_shims.c:531-541`). `k_thread_create`
appears only on the tier path, which is discarded here.

| thread | stack | priority |
| --- | ---: | --- |
| Zephyr `main` (runs every callback) | 16,384 | 0 |
| zenoh read | 8,192 | SCHED_RR, Zephyr 4 |
| zenoh lease | 8,192 | SCHED_RR, Zephyr 4 |
| zenoh tx-flush | 8,192 | SCHED_RR |
| system work queue | 4,096 | Zephyr default |

**1 main thread + 3 zenoh pthreads. Two of the five stack slots are spare, and
zero tier threads exist.** All 19 callbacks run on `main`, so the 30 Hz MRM
control path is not isolated from 10 Hz telemetry.

Priority 4 is derived, not written: `CONFIG_NROS_ZENOH_READ_PRIORITY=200` on a
normalised 0-255 band, mapped by `platform.c:487-510` as
`lo + (200 * (hi - lo)) / 255` against `CONFIG_NUM_PREEMPT_PRIORITIES=15`.
Policy is SCHED_RR; SCHED_FIFO on Zephyr would select the cooperative band.

The slot index only ever rises. `nros_zephyr_task_create` bounds-checks and
returns -1 when slots run out, and nothing releases a slot when a task ends, so
a workload that reconnects consumes them permanently -- a latent bring-up risk
on a link that drops.

### The tier pool costs nothing, and the comment about it is wrong

Two sources emit the same three tokens onto the command line, and last-wins
does not go the way the island's comment claims:

| token | island sets | nano-ros sets | effective |
| --- | ---: | ---: | ---: |
| `NROS_ZEPHYR_MAX_THREADS` | 4 | 5 | **5** |
| `NROS_ZEPHYR_MAX_TIERS` | 1 | 4 | **4** |
| `NROS_ZEPHYR_TIER_STACK_SIZE` | 4096 | 16384 | **4096** |

`src/zephyr_entry/CMakeLists.txt:70-73` says it keeps "one minimal slot". It
gets four, at the island's 4096 each -- the map shows
`.bss.nros_tier_threads` = `0x440` = 4 x `sizeof(struct k_thread)` and a
`0x4000` tier stack array.

Both are moot: the map places them under **Discarded input sections** at
address `0x0`. Nothing spawns a tier, so `-Wl,--gc-sections` drops the pool.
**0 bytes.** The comment should be corrected, not the build.

### The scheduling file was deleted, and reinstating it would change nothing

`safety_island.system.posix.yaml` existed and was removed in commit `2535dd7`
("ENTITIES is gone; the contract states the whole image"). It carried three
facts -- `target: posix`, `mapper: rate_monotonic`, and an RT priority band --
and its own comments already admitted the island "runs its four components on
ONE Zephyr thread through the nano-ros executor, so no POSIX priority derived
here is applied to anything today".

Reinstating it as written would still change nothing, for two reasons:
`target: posix` does not match this image (tier caps are looked up by exact
key, and the board's key is `zephyr`, with different caps), and the derivation
is gated on callback groups, not on the platform file.

The one contract field that *would* be scheduling is `max_latency_ms` on a
path. No path in this model carries one, so `deadline_us`, `budget_us`,
`period_us` and the EDF path (`k_thread_deadline_set`) are all unreachable here.

---

## 5. The unified TLSF heap

One static `.bss` arena behind one allocation funnel, serving both the vendored
C RMW (zenoh-pico's `z_malloc`) and Rust's `#[global_allocator]`. The funnel is
`nros_platform_alloc`; nano-ros phase-391 W3 repointed its Zephyr body off
Zephyr's `k_malloc` / `sys_heap` onto an rlsf (Rust TLSF) arena.

The phase states its own thesis as *"replace what sits behind the funnel, and
make the property checkable"*.

### Why TLSF: a worst-case bound, not a fragmentation one

The predecessor was a first-fit, address-ordered free list. Its fragmentation
behaviour was already good -- Robson (1977) showed first-fit is near-optimal --
but it is **O(n)**, so it has no worst-case execution bound. That is the
property a safety island needs and did not have.

TLSF is O(1) for both allocate and free regardless of heap state, via two-level
segregated free lists plus bitmaps and a `CLZ`, which is a single instruction on
Cortex-M7. Internal fragmentation is bounded at `1/SLLEN`; with `SLLEN = 16`
that is **6.25%**.

The O(1) property is also load-bearing for a second reason: Zephyr is
multi-threaded and the old free list was single-threaded by contract, so the C
funnel wraps every call in a `k_spinlock`. O(1) is what keeps that critical
section short and bounded.

`o1heap` was rejected despite MISRA C:2012 conformance and a published
worst-case formula, because it is single-level -- one bin per power of two, so
worst-case internal fragmentation approaches 100%. UPV's tlsf was rejected on
licence, mattconte's as unmaintained.

### What "unified" merged

| what was separate | merged by |
| --- | --- |
| zenoh-pico's C `z_malloc` vs Rust's `#[global_allocator]` | phase-230 / RFC-0034 D6-D7 |
| a second `#[global_allocator]` in `nros-c`, letting a board bypass the funnel | phase-361 W8.c |
| Zephyr's kernel `sys_heap` behind `nros_platform_alloc` | phase-391 W3 |

There is no per-RMW pool in that list, and deliberately so -- see below.

### Where the 95,928 bytes go

The `.bss` symbol is `sizeof(FreeListHeap<94208, 18>)`, not just the arena:

```
arena    (CONFIG_NROS_ZEPHYR_HEAP_SIZE)          94,208
slab     8 slots x 64 B                             512
rlsf control  fl_bitmap 4 + [u16;18] 36
              + [[Option<NonNull>;16];18] 1,152    1,192
flags, stats counters, tail padding                   16
                                                 --------
                                                  95,928
```

That accounts for the 1,720 bytes over the stated knob exactly.

### Payload buffers deliberately stay static

This is the keystone, and it explains the shape of section 3's table. Robson's
bound scales with the ratio of largest to smallest block, so a heap holding both
20-byte key expressions and megabyte payloads has a punishing worst case. A heap
that holds only *infrastructure* -- sessions, key expressions, Rust `String` and
`Vec` churn -- has a narrow spread, and the bound is cheap to defend.

The consequence is visible in this image: the 115,128 B service inbox table and
the 38,720 B subscriber slots are static `.bss` symbols, and together they are
larger than the heap itself.

### What allocates, and when

The executor arena is the largest single allocation and comes out of this heap
in one piece, which is why cmake gates it at configure time:
`NROS_EXECUTOR_ARENA_SIZE + 24576 <= NROS_ZEPHYR_HEAP_SIZE`, fatal if violated.
The 24,576 is empirical, not derived -- treat it as a floor, not a formula.

Beyond that: zenoh-pico sessions and key expressions (42 C call sites), its read
and lease task structures, Rust `Box`/`Vec`/`String`, Zephyr sync primitives
(`k_mutex`, `k_condvar`), the node runtime's registries, and the parameter
services.

**There is no boot-time-only rule and no "no allocation after init" guarantee.**
Allocation is permitted at any time; what is guaranteed is that each one is
O(1). zenoh-pico's tasks allocate concurrently with the application by design.

Two tiers are defined and gated by `scripts/check-no-alloc-image.py`:
`heap-free` (no allocation symbol links at all) and `unified` (allocation
permitted, but only through the platform funnel). This image is `unified`.

### Failure mode, and two gaps on this board

Exhaustion is blunt: an application that outgrows the arena *stops*. Since
phase-8 there is a diagnostic -- `nros: HEAP EXHAUSTED: request N bytes, arena N
bytes, caller 0x...` with an `addr2line` hint, printed with `printk` rather than
`LOG_*` because the logging subsystem may itself allocate and this is the path
that just failed to allocate.

Only **internal** fragmentation is bounded (the 6.25%). There is no external
fragmentation bound computed or asserted anywhere in the tree; the narrow-spread
argument is qualitative. A safety argument needing a defensible external bound
will not find one here.

Two things are unfinished on this island specifically:

1. **It still carries both arenas.** `mr_canhubk3_s32k344.conf` sets
   `CONFIG_HEAP_MEM_POOL_SIZE=8192`, so `kheap__system_heap` (8,268 B in
   section 3's table) is live alongside the 94 KiB unified arena. W3's endgame
   is to set that pool to 0, at which point `k_malloc` and `sys_heap_*`
   garbage-collect out of the link -- which is simultaneously the test that no
   enabled Zephyr subsystem still needs them. On a board 61,608 B over budget,
   this is 8 KiB sitting there untested.
2. **94,208 was chosen, not measured.** The high-water reporter now exists
   (`nros_zephyr_heap_peak()`, surfaced as `heap_peak`), so the path to a
   derived number is open and has not been walked.

`CONFIG_COMMON_LIBC_MALLOC_ARENA_SIZE=0` in the board conf belongs to the same
phase (W1b), and was added because of this board: denying the `malloc` *symbol*
is necessary and not sufficient, because the arena is reserved in `.bss`
whether or not any caller survives the linker. It was found reserved here twice,
at 24,576 B and later 8,192 B after a rebuild lost the setting. Dead code is
collected; dead reservations are not.

One caution for readers of the older notes: the causal chain in
`docs/board-facts.md` and in the board conf's own comment -- `z_malloc` ->
`k_malloc` -> `CONFIG_HEAP_MEM_POOL_SIZE` -- is the pre-phase-391 shape and is
no longer true for this image.

## 6. The parameter server, on and off

The parameter server is a **bringup capability**, not a Kconfig knob:

```toml
# src/safety_island_bringup/system.toml
features = ["param_services"]
```

With it on, every node gets the six ROS 2 parameter services, so the 4 nodes
contribute 24 of the image's 26 queryables. Each queryable gets the same inbox:
a ring of 4 slots of `SERVICE_BUFFER_SIZE` (1024) bytes, 4,428 bytes all in.

| | as shipped | queryables forced to 2 |
| --- | ---: | ---: |
| Queryables | 26 | 2 |
| Service inbox table | 115,128 B | 8,856 B |
| RAM | **overflows by 61,608 B** | 281,192 B of 320 KiB (85.81%) |
| ITCM | -- | 13,052 B (19.92%) |
| DTCM | -- | 83,216 B (63.49%) |
| FLASH | -- | 582,020 B (14.04%) |
| Links? | **no** | yes |

The right column is a control that forces `MAX_QUERYABLES=2`. It shrinks the
inbox table without removing the parameter machinery, so read it as an upper
bound on what the services cost, not as a supported configuration. Turning the
capability off properly (`features = []`) is a separate exercise: it collapses
every derived knob to its crate default, which is a different image again.

### The cost is the services, not the store

Measured, not inferred:

- Varying the parameter **store** knobs (`MAX_PARAMETERS` 25 -> 32,
  `MAX_PARAM_NAME_LEN` 35 -> 64, `PARAM_SERVICE_BUFFER_SIZE` derived -> 4096)
  changes the overflow by **0 bytes**, byte-identical at 61,608.
- Removing the service queryables changes it by **108,096 bytes**.

So phase-446's contract-declared parameter sizing is free. The services are
what the board cannot afford.

### And two of the six do not fit their own buffer

Computed from the `rcl_interfaces` definitions at this image's capacities
(`MAX_STRING_VALUE_LEN=0`, `MAX_ARRAY_LEN=0`, `MAX_BYTE_ARRAY_LEN=0` collapse
every `ParameterValue` arm to its empty-sequence header, giving
`ParameterValue` = 56 B and `Parameter` = 96 B):

| service | request bytes | fits 1024 |
| --- | ---: | --- |
| `get_parameters` | 1004 | yes |
| `get_parameter_types` | 1004 | yes |
| `describe_parameters` | 1004 | yes |
| `list_parameters` | 1016 | yes |
| `set_parameters` | **2408** | **no** |
| `set_parameters_atomically` | **2408** | **no** |

A `set_parameters` carrying the node's 25 declared parameters is 2.35x the slot
it must land in. The callback sets an overflow flag and drops the request: the
caller sees a node that answers `get_parameters` and silently ignores
`set_parameters`. Nothing fails at build time. The four that do fit are not
comfortable either -- 1004 of 1024 means one longer name, or a 26th parameter,
drops those too.

Filed upstream as nano-ros issue 1352. The fix wants per-type inbox sizing plus
a ring depth for the parameter family separate from the action path's: sized
per type at depth 1 the same four nodes need 43,344 B instead of 106,272 B,
which is more than the overflow, and `set_parameters` gets a slot it fits in.
Per type at depth 4 would be worse than today, so the depth is the half that
makes it pay.

---

## 7. Where this leaves the board

TCM relocation cannot close the gap on its own: DTCM has 47,856 B free against
a 61,608 B overflow, 13,752 B short even if everything movable went there. The
overflow moves when the parameter-service inbox sizing changes, or when the
parameter server is turned off for this deployment.

Open, roughly in order of how much they would buy:

- **nano-ros #1043 / issue 1352** -- parameter service inbox sizing. Worth
  106,272 B here, and it also fixes `set_parameters` being silently dropped.
- **Finish phase-391 W3 on this board** -- set `CONFIG_HEAP_MEM_POOL_SIZE=0` so
  the 8,268 B kernel heap garbage-collects out, which doubles as the test that
  no enabled Zephyr subsystem still calls `k_malloc`.
- **Measure the heap instead of guessing it.** 94,208 B was chosen without a
  measurement; `nros_zephyr_heap_peak()` now exists to replace it with a number.
- **Declare callback groups** if the MRM control loop should be isolated from
  telemetry. The tier derivation is complete and gated only on their absence.
- **Correct two stale comments**: the island's tier-slot comment
  (`src/zephyr_entry/CMakeLists.txt:70-73`) does not describe the build, and the
  `z_malloc -> k_malloc` chain in `docs/board-facts.md` predates phase-391.
- The board has never executed this image; the MCU-Link probe is the blocker.
  The boot-time `z_data_copy()` that populates ITCM is exactly the thing a
  linker cannot check.
