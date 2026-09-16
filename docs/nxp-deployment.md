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

## 2. The contract sizes the image

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

## 4. The contract does not reach the scheduler

This is the part most likely to be assumed rather than checked, so it is worth
stating plainly: **the contract's rates size the image, they do not schedule
it.**

`rate_hz: 10` and `min_rate_hz: 30` in the contract feed buffer sizing,
callback counts and liveliness. They do not become thread priorities, periods
or deadlines. Nothing in the contract maps a callback to an OS thread.

Scheduling is a separate declaration, in `system.toml`, and this island makes
none. The mechanism exists and is written out in that file as commented
examples:

```toml
# group_tiers = { control = "ctrl" }
#
# [tiers.ctrl]
# spin_period_us = 33_333            # 30 Hz, matches upstream update_rate
# [tiers.telem]
# spin_period_us = 100_000
```

A `[tiers.*]` block plus a `group_tiers` mapping on a component is what would
spawn a dedicated Zephyr thread per tier, via `nros_zephyr_tier_task_create`
out of a static pool. With none declared, all **19 callbacks run on one
executor**, and the MRM control loop is not isolated from telemetry.

The tier pool itself costs nothing here. Two sources disagree about its size --
`src/zephyr_entry/CMakeLists.txt:74-77` compiles in `NROS_ZEPHYR_MAX_TIERS=1`,
`TIER_STACK_SIZE=4096`, while Kconfig carries 4 and 16384, and the build warns
`"NROS_ZEPHYR_MAX_TIERS" redefined` -- but the argument is moot: no
`nros_tier_stacks` symbol appears in the map at all. Nothing spawns a tier, so
`-Wl,--gc-sections` drops the pool entirely. **0 bytes.**

### What threads do exist

| thread | stack | source |
| --- | ---: | --- |
| Zephyr `main` | 16,384 | `CONFIG_MAIN_STACK_SIZE` |
| system work queue | 4,096 | `CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE` |
| nano-ros task slots x5 | 8,192 each | `CONFIG_NROS_ZEPHYR_TASK_SLOTS` x `TASK_STACK_SIZE` |
| interrupt stacks | 2,048 | Zephyr |

The five nano-ros slots cover the zenoh read task, the lease task and the
tx-flush task, plus the spin thread. The slot index only ever rises:
`nros_zephyr_task_create` bounds-checks and returns -1 when slots run out, and
nothing releases a slot when a task ends, so a workload that reconnects
consumes them permanently. That is a latent bring-up risk on a link that drops.

---

## 5. The parameter server, on and off

The parameter server is a **bringup capability**, not a Kconfig knob:

```toml
# src/safety_island_bringup/system.toml
features = ["param_services"]
```

With it on, every node gets the six ROS 2 parameter services, so the 4 nodes
contribute 24 of the image's 26 queryables. Each queryable gets the same inbox:
a ring of 4 slots of `SERVICE_BUFFER_SIZE` (1024) bytes, 4,428 bytes all in.

| | param server ON | param server OFF |
| --- | ---: | ---: |
| Queryables | 26 | 2 |
| Service inbox table | 115,128 B | *(pending)* |
| RAM | **overflows by 61,608 B** | *(pending)* |
| Links? | **no** | *(pending)* |

A control build forcing `MAX_QUERYABLES=2` -- a proxy that shrinks the table
without removing the parameter machinery -- came out at RAM 281,192 B / 320 KiB
(85.81%), ITCM 13,052 B (19.92%), DTCM 83,216 B (63.49%), FLASH 582,020 B
(14.04%). The real `features = []` numbers replace that row when the build
lands.

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

## 6. Where this leaves the board

TCM relocation cannot close the gap on its own: DTCM has 47,856 B free against
a 61,608 B overflow, 13,752 B short even if everything movable went there. The
overflow moves when the parameter-service inbox sizing changes, or when the
parameter server is turned off for this deployment.

Open:

- nano-ros #1043 / issue 1352 -- parameter service inbox sizing.
- The board has never executed this image; the MCU-Link probe is the blocker.
  The boot-time `z_data_copy()` that populates ITCM is exactly the thing a
  linker cannot check.
