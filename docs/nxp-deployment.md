# The safety island on NXP S32K344, via nano-ros

What the MR-CANHUBK344 image actually contains: which nodes run, where every
byte of RAM goes, and which parts of the launch contract reach the operating
system.

The hardware is in section 0; the software provenance is:

| | |
| --- | --- |
| Zephyr board string | `mr_canhubk3/s32k344` |
| Zephyr | 4.4.0, SDK 1.0.1 (`arm-zephyr-eabi` 14.3.0) |
| RMW | zenoh (`-S nros-zenoh`), serial link (`-S island-serial`) |
| nano-ros pin | `f8655e9b7` |
| Island commits | `07ffdb7`, `20bc6d9`, `368b766` |
| Status | configures, compiles and links; **over RAM budget by 61,608 B with the parameter server on** |

The same four nodes and the same contract also build for `native_sim` over
CycloneDDS, and that image is verified end to end:
`VERDICT: PASS -- island stopped the vehicle (4.24 -> 0.00 m/s), MRM recovered,
vehicle resumed (1.43 m/s)`, with `MrmState` reaching `state=2 behavior=2`
(EMERGENCY_STOP) and returning to NORMAL. Nothing below has run on silicon; the
board is blocked on the MCU-Link probe, so every board number here is from the
linker and the map file, not from a running target.

---

## 0. The hardware

NXP **S32K344**, Cortex-M7 r1p2, ARMv7E-M, **160 MHz**, on an
**MR-CANHUBK344** board. DAP IDCODE `0x6ba02477`. Everything in this section was
measured on the board in this repo except where marked; several things "known"
from documentation turned out to have exceptions only the silicon showed.

### Memory

Read from the device with `pyocd cmd -c "show map"`:

| region | start | end | size | access | sector |
| --- | --- | --- | ---: | --- | --- |
| `itcm` | `0x00000000` | `0x0000ffff` | 64 KiB | rwx | -- |
| `pflash` | `0x00400000` | `0x007fffff` | **4 MiB** | rx | 8 KiB |
| `dflash` | `0x10000000` | `0x1001ffff` | 128 KiB | rx | 8 KiB |
| `dtcm` | `0x20000000` | `0x2001ffff` | 128 KiB | rwx | -- |
| `sram` | `0x20400000` | `0x2044ffff` | **320 KiB** | rwx | -- |

**320 KiB of SRAM is the binding constraint for everything on this board.** The
4 MiB of flash is barely touched -- this image uses 14% of it. Both TCMs are
zero-wait-state and private to the CPU, which is what makes them useful for
determinism and useless for DMA.

Two flash caveats worth carrying: the top 48 KiB of pflash
(`0x007F4000`-`0x007FFFFF`) faults on read, bisected to 8 KiB granularity, so a
flash backup taken from this board does not contain it; and a single 4 MiB
`savemem` fails even across the readable range, so dumps must be chunked at
512 KiB or less.

### CPU

```
CPU core #0: Cortex-M7 r1p2, v7.0-M architecture
  Extensions: [DSP, FPU, FPU_V5, MPU]
```

| feature | present |
| --- | --- |
| ARMv7E-M DSP / 32-bit SIMD | yes -- `uadd8`, `smlad`, `qadd16` all emit |
| FPU FPv5, single and double | yes -- `vfma.f32` and `vfma.f64` emit |
| I-cache and D-cache | yes, both enabled, 32 B lines |
| NEON | **no** |
| Helium / MVE | **no** (Cortex-M55/M85 only) |
| GPU, VPU, ISP, camera interface | **no** |

The DSP extension is real but **32 bits wide** -- 4 x 8-bit or 2 x 16-bit lanes
per instruction, against NEON's 16 bytes. It suits control-loop filtering, CRC
and small FFTs. It does not make this part a vision processor: a decoded 1080p
frame is 6.2 MB against 320 KiB of SRAM, **19x short**, and even a compressed
1080p JPEG exceeds total SRAM.

### Connectivity

Six CAN interfaces, confirmed on the running factory image. Ethernet is
**100 Mbit** for two independent reasons: the PHY is a TJA1103 (100BASE-T1,
single-pair automotive), and `FEATURE_GMAC_RGMII_EN = 0` for the S32K344 in the
NXP HAL, so the MAC-to-PHY bus is MII/RMII and caps at 100 Mbit regardless of
the PHY.

The P6 "DCD-LZ" JST-GH connector carries **SWD and the console UART combined** --
the MCU-Link probe and the console cable both live there, and the probe is
single-access, so a second pyocd command during a dump gets
`Unable to claim interface`.

This deployment links over serial (`-S island-serial`), not Ethernet.

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

## 3. Exactly-sized buffers: one derivation, many backends

Two questions get asked of the message types, and they have different answers.
Confusing them is worth tens of kilobytes here.

| basis | knob | this island | what it means |
| --- | --- | ---: | --- |
| `closure` | `NROS_SUBSCRIPTION_BUFFER_SIZE` | **1496** | every type the image LINKS |
| `subscribed` | `NROS_SUBSCRIBER_BUFFER_SIZE` | **880** | every type the image RECEIVES |

The closure basis is not over-caution: that number becomes the default receive
*and* transmit buffer for raw subscriptions, service servers and clients, and
action cores. A type this image only publishes still has to fit.

The subscribed basis sizes the executor arena and the zenoh payload class,
where paying for types you never receive is pure waste. On this island the gap
is the dominant term, not a rounding error -- one `std_msgs/Float64MultiArray`,
linked and never received, sets the closure number for the whole image.

### The layering rule

A knob is RMW-agnostic if it states a fact about the image; it is
backend-specific if it states how a backend spells that fact. The derivation
happens once, then lowers:

```
NROS_MAX_SUBSCRIBERS  ->  ZPICO_MAX_SUBSCRIBERS, NROS_XRCE_MAX_SUBSCRIBERS
NROS_MAX_QUERYABLES   ->  ZPICO_MAX_QUERYABLES,  NROS_XRCE_MAX_SERVICE_SERVERS
NROS_MAX_LIVELINESS   ->  ZPICO_MAX_LIVELINESS
```

The rule is stated where it bites, in backend-agnostic core code: a crate that
is not a backend **may not read a backend-prefixed name**. `nros-node` used to
read `ZPICO_SUBSCRIBER_BUFFER_SIZE`; the fix was to rename the knob rather than
let the core crate keep reading a zenoh name, and the old spelling is recorded
as dead.

Floors, unlike derivations, are per-consumer and deliberately so: the same
derived number reaches the XRCE knobs where a zero is a meaningful answer worth
tens of kilobytes of heap, and reaches zenoh where it is not. **One derivation,
two consumers, two different legal minima.**

### QoS depth is a multiplier, not a size

The contract's `qos: { depth: 1 }` never enters a buffer size. It multiplies the
arena:

```
buffered_region(depth, bound) = (depth + 1) * bound + (depth + 1) * 8
```

Measured on this island across ten subscriptions: **86,108 bytes at the ROS
default depth 10, 24,516 at depth 1.** Every one of the island's eleven
subscriptions declares depth 1, which is why the arena is affordable at all.

A subscription that declares no depth is not an error -- it is an image that has
not opted in, and the arena then *refuses* to derive rather than guessing. Ten
inflates tenfold and one under-sizes, so neither is a safe default.

The declared depth is also checked against the code: codegen emits the contract
QoS into a generated header and the subscribe macro static-asserts against it,
so a contract that disagrees with the source is a build error naming the topic
and both numbers.

### The precedence ladder

Every derivable knob resolves through one function, against a `-1` sentinel
that means "the image chose nothing" -- distinct from `0`, which for some knobs
is a meaningful claim:

```
1. an explicit environment value         -- a person, right now
2. a Kconfig / board .conf value         -- a person, in the tree
3. the value derived from the inventory  -- the build
4. the crate's own default               -- nobody; the knob stays unset
```

**A derived value is a DEFAULT, never an override.** Rung 4 is a deliberate
no-op: the knob is not resolved at all, so the cargo environment never carries
it and the reading `build.rs` falls through to its own literal, which is the one
place that literal is written.

Gates keep the road honest. One checks each knob is resolved exactly once;
another maps every derived fact to every resolved name it must reach, in both
directions, because "a derived 880 delivered as 1496 for four consecutive island
builds and nothing said so -- over-sized, therefore silent."

That failure is not hypothetical here. A three-configure chain that ninja ran
twice left this island linking at 1496 where 880 was correct, shipping a
70,296-byte arena where 46,272 was right -- 24 KB on a 320 KB part. The island's
own justfile now refuses to flash when the delivery check fails.

---

## 4. Message size bounds

A bound is a pair of byte counts for one type, plus an honest third state:

```rust
enum BoundState {
    Bounded { tx, rx },          // bytes, encapsulation header included
    Unbounded { reason },        // no bound EXISTS
    Unresolved { reason },       // the bound was not COMPUTED
}
```

`tx` is XCDR1 exact, because this stack writes XCDR1. `rx` is
`max(XCDR1, XCDR2)` rounded up to 4, because a buffer has to accept whatever
arrives -- `rx >= tx` always. The two failure states are kept apart because "we
looked and no bound exists" and "we could not look" license different fixes; the
second is usually a search-path problem, not a property of the message.

### Where bounds come from -- not the contract

The `.msg` / `.idl` is authoritative and cannot be overridden: a bounded shape
like `string<=64` has its own path and never consults configuration. A config
cap can neither widen nor narrow it.

Unbounded fields get their capacity from `nros-codegen.toml`, not from the
contract, and that is deliberate. The island's own contract says why:
capacities for a string or array would be **a board fact, never stated here**.
This island sets blanket defaults:

```toml
[defaults]
string   = { cap = 64, mode = "inline" }
sequence = { cap = 16, element_cap = 64, mode = "inline" }
```

Only `inline` yields a bound. `heap` treats the cap as a hint and `view` aliases
the receive buffer with no length check, so neither bounds anything.

### An unbounded type refuses the build, loudly

It does not warn and it does not silently pick a default. Codegen poisons the
type's size constants with a token naming the type and the offending member, so
the compiler says which field costs the bound rather than emitting "undeclared
identifier". The C++ pack does it with a dependent static assert inside the
size-bound template, so the error fires only when a size is actually asked for.

The diagnostic names the fix: bound the field in the `.msg`, give it an inline
cap, or pass an explicit byte count to size that one subscription by hand.

Every offender is named in one build, not the first one found -- otherwise
bounding a package costs one cap and one full codegen run per member.

The image-wide derivation refuses the same way: **if any type in the closure is
unbounded or unresolved, no class size is derived at all.** Deriving over the
bounded subset would publish a maximum a real sample can exceed, which is the
silent dropped-message this whole mechanism exists to prevent.

### Why the walk cannot be a sum

Padding is a function of where a field starts, so summing per-field maxima is
wrong the moment a variable-length field shifts what follows. The walk threads
the current alignment through and returns the size from there, which also makes
nested structs compose with no special case.

XCDR2 caps alignment at 4 and reserves a 4-byte header for every struct
including nested ones, so **a message containing an `int64` has two different
bounds** and one constant would be silently wrong for one encoding. The rules
are read off the writer, not the spec, and the bounds are unit-tested against
bytes the writer actually emitted.

### Where 1496 comes from

`std_msgs/msg/Float64MultiArray`, tied with the Int64 and UInt64 MultiArrays --
all three linked, none subscribed:

```
MultiArrayDimension  4 encap + string(4+64+1 -> pad 76) + 2 x u32   =   84  tx
                     + XCDR2 DHEADER                                     88  rx
MultiArrayLayout     4 + (4 seq-len + 16 x 80) + 4 data_offset      = 1292  tx
                                                                      1360  rx
Float64MultiArray    4 + 1288 + 4 seq-len + pad + 16 x float64      = 1428  tx
                                                                      1496  rx
```

That is the island's own `sequence.cap = 16` and `string.cap = 64` doing the
work. The island's config calls these caps what they are: **a deployment
assertion, not a measurement -- nothing here is subscribed, so nothing checks
them at runtime.**

The subscribed answer, 880, is `nav_msgs/msg/Odometry`: 8 stamp + 344 pose and
covariance + 336 twist and covariance + two length-prefixed strings. Its two
strings are the only fields this island caps *by name* rather than by blanket
default.

### What the bound is used for

Implemented: the take buffer and its transmit alias; the executor arena via the
subscribed size; the zenoh small and large payload classes, including how many
subscribed types exceed the 2048 split (**zero**, on this island, which is why
the large-payload pool is zero bytes).

Not derived, and worth knowing: `NROS_FRAG_MAX_SIZE` is a plain Kconfig default
of 2048 with no sentinel and no derivation, and **nothing compares it against
the derived 1496** even though the tuning guide describes it as the limit on the
largest message a node can receive. Zero-copy eligibility is computed as a
`plain` flag on every bound and has no consumer -- that wave has not landed.

---

## 5. Memory layout

The regions are in section 0. What matters here is that of the five, this image
uses three: SRAM for everything by default, DTCM and ITCM for what is moved
into them deliberately, and `dflash` not at all.

### The image's memory map

Laid out by address, from the map file of the real derived configuration:

```
RAM   0x20400000  datas       3,448   initialised data, copied from flash at boot
      0x20400ef0  bss       310,811   zero-filled at boot
      0x2044cd10  noinit     74,648   stacks and heaps, not touched at boot
      0x2045f0a8  end
                          ---------
                            389,288   needed
                            327,680   available        OVER BY 61,608

DTCM  0x20000000  .dtcm_bss_reloc   83,216 of 131,072    63.5%
ITCM  0x00000000  .itcm_text_reloc  13,052 of  65,536    19.9%
FLASH 0x00400100  text + rodata    582,020 of 4,144,896  14.0%
```

Seventeen symbols account for 97% of that RAM. Grouped by what owns them:

| owner | bytes | what |
| --- | ---: | --- |
| **RMW (zenoh)** | **196,112** | |
| | 115,128 | service inbox table -- 26 queryables x 4,428 |
| | 38,720 | subscriber slots -- 11 x 3,520 |
| | 24,992 | zenoh-pico session pool |
| | 11,264 | cffi subscription-handle registry |
| | 3,584 | message info table |
| | 2,424 | subscriber auxiliary state |
| **Heap** | **95,928** | 94,208 arena + 1,720 TLSF metadata and slab |
| **Stacks** | **63,488** | |
| | 40,960 | nano-ros task stacks -- 5 slots x 8,192 |
| | 16,384 | Zephyr `main` |
| | 4,096 | system work queue |
| | 2,048 | interrupt stacks |
| **Kernel heap** | **8,268** | `CONFIG_HEAP_MEM_POOL_SIZE`, still present -- see section 6 |
| **Other** | **12,168** | POSIX thread pool 5,120; three action stashes 4,488; shell 2,560 |

The remaining ~11.6 KiB is spread across many small symbols, plus section
alignment.

### What is NOT in the map

**The executor arena.** It is the largest single allocation in the image and it
never appears as a symbol, because it is carved out of the TLSF heap at runtime
rather than reserved in `.bss`. `CONFIG_NROS_EXECUTOR_ARENA_SIZE=0` means
derive, and the derivation sizes it from the *subscribed* bound and the declared
depths:

```
buffered_region(depth=1, bound=880)  =  3 x 880          (triple buffer)
pubsub_entry                          =  region + 1024
```

At the delivered `NROS_SUBSCRIBER_BUFFER_SIZE=880` that lands near 46 KiB; at
the stale 1496 it was 70,296, and this tree has shipped the latter by accident.
Because the arena comes out of the heap, cmake gates the two against each other
at configure time -- `arena + 24576 <= NROS_ZEPHYR_HEAP_SIZE` -- which at
94,208 leaves roughly 23 KiB of margin over the current arena.

That relationship is the one to hold onto: **the heap number is not free space,
it is mostly the arena.** Raising a buffer bound raises the arena, which eats
heap, which the gate then refuses rather than letting it fail at first
allocation.

**The parameter store.** Sized by `NROS_MAX_PARAMETERS=25` and owned by the
executor, not embedded per node. It does not appear as a large symbol, and the
A/B in section 8 shows varying its sizing moves the image by 0 bytes -- the
parameter cost is entirely in the 24 service queryables above, not in the store.

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

### Every figure traces to a stated knob



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

## 6. The unified TLSF heap

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

---

## 7. The contract sizes the image; it does not schedule it

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

## 8. The parameter server, on and off

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

## 9. What this campaign did

The board did not build at all when this started, and the Zephyr image did not
join the DDS graph. Both now do, and three defects were found and filed upstream
by the act of getting there.

**Island, on `contract-params`:**

| commit | what |
| --- | --- |
| `07ffdb7` | move the nano-ros pin to main, drop a local `component.hpp` patch that had landed upstream |
| `20bc6d9` | two lines of the native_sim NSOS profile the island's hand-copy had missed |
| `368b766` | wire `hal_nxp` into `board-setup` and `board-build` |

`20bc6d9` is why the demo passes. The island copies nano-ros's native_sim
profile by hand, because it passes `CONF_FILE` explicitly and so does not get
the file applied automatically -- and it had copied three of the four lines.
`CONFIG_ETH_NATIVE_POSIX=n` was the missing one, so the TAP driver stayed
compiled in and failed on `/dev/net/tun`, which needs root. Cyclone's receive
thread then spun on `select failed` forever. A second line,
`CONFIG_NET_SOCKETS_POLL_MAX=16`, was needed because Zephyr's default poll set
of 3 is smaller than the descriptor set Cyclone's waitset selects on:

```
zeth errors            1 -> 0
select failed  7,758,842 -> 0
tmp_island.log    8.8 GB -> 4 KB
engage          8 failures -> attempt 1: True
```

`368b766` is why the board builds. nano-ros omits `hal_nxp` from its Zephyr 4.4
allowlist on purpose and names this tree as the downstream that re-enables it;
no such wiring existed, so devicetree preprocessing could not find the S32K344
pin-control header even on a machine where the file was already on disk.
Fetched and registered as a Zephyr module are different things.

**nano-ros:**

| | |
| --- | --- |
| PR #992, issue 1337 | `package.xml` walk descended into build trees. Merged. |
| PR #1043, issue 1352 | `set_parameters` does not fit its own service inbox. Open. |

Issue 1337 was found by this migration and is worth recording: two hand-copied
`package.xml` walks pruned `build` and `target-*` but not `build-*`, while the
CLI's other two walkers did. One `nros image-facts` opened **362,782
directories, 98.7% of every open it made, to read a single file** -- 242 MB of
physical reads for 27 KB of answers. After the fix and a cleanup of 82 stale
build trees, the same command runs in 0.95 s.

**Measurements taken, not assumed:**

- `native_sim` demo to VERDICT PASS, twice, with the MRM chain exercised end to
  end.
- The board image linked, and its region report recorded.
- An A/B proving the parameter *store* sizing costs 0 bytes, byte-identical
  across both configurations.
- A control proving the parameter *services* cost 108,096 bytes.
- The `set_parameters` overflow computed from the `rcl_interfaces` definitions
  at this image's capacities, and cross-checked against the map: the model
  predicts 4,428 bytes per service slot and the map measures 4,428.

---

## 10. Future work

Nothing below is blocked on a decision; each is work that was scoped and not
done.

**The board does not fit, by 61,608 bytes.**

The cause is isolated: the parameter services, 108,096 bytes measured. nano-ros
#1043 is the fix, and it needs both halves -- per-type inbox sizing *and* a ring
depth for the parameter family separate from the action path's. Per type at
depth 1 the same four nodes need 43,344 B instead of 106,272 B; per type at the
current depth 4 would be worse than today. TCM relocation cannot substitute:
DTCM has 47,856 B free, 13,752 B short of the overflow.

**Reclaimable without waiting for upstream:**

- `CONFIG_HEAP_MEM_POOL_SIZE=8192` is still set, so this image carries both the
  Zephyr kernel heap and the 94 KiB unified arena. Setting it to 0 frees
  8,268 B and doubles as the link test that no enabled Zephyr subsystem still
  calls `k_malloc`.
- `CONFIG_NROS_ZEPHYR_HEAP_SIZE=94208` was chosen without a measurement.
  `nros_zephyr_heap_peak()` now exists to replace it with a number.

**Never executed on silicon.** The board is blocked on the MCU-Link probe.
Everything here is from the linker and the map. The boot-time copy that
populates ITCM is exactly what a linker cannot check, and the `set_parameters`
drop is exactly what a linker cannot see.

**Scheduling is available and unused.** The tier derivation is complete and
gated only on components declaring callback groups. Declaring them would put the
two 30 Hz nodes at Zephyr priority 0 and the two 10 Hz nodes at priority 1,
instead of all 19 callbacks sharing `main`. Whether a safety island wants its
MRM loop isolated from telemetry is a design question this deployment has not
answered.

**Gaps in the derivation, upstream:**

- `NROS_FRAG_MAX_SIZE` is a hand-set 2048 that nothing compares against the
  derived 1496, though it bounds the largest receivable message.
- Zero-copy eligibility is computed on every bound and consumed by nothing.
- No external fragmentation bound is computed or asserted for the TLSF arena;
  only the 6.25% internal bound exists. A safety argument needing the former
  will not find it.

**Stale statements to correct in this tree:**

- `src/zephyr_entry/CMakeLists.txt:70-73` claims one minimal tier slot; the
  build gets four.
- `docs/board-facts.md` still describes `z_malloc -> k_malloc ->
  CONFIG_HEAP_MEM_POOL_SIZE`, which phase-391 W3 replaced.
- The contract header's liveliness excerpt shows one service client; there are
  two.

**Not captured by the contract at all:** QoS durability. Several publishers and
one subscription are transient-local in code, and no publisher entry in the
contract carries a `qos` block. The contract records depth only.
