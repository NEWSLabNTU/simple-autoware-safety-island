# Boot through registration: the iteration log

phase7-W8, 2026-09-25. W2 left the island image stopping at boot stage 4
(RegisteringEntities) on QEMU and on Renode (`docs/emulation.md`, F1). This
unit takes the QEMU image (`src/qemu_entry`, `mps2/an385`, zenoh over the
emulated LAN9118) through registration to the executor's first spin, fixing
each failure where its cause is, and then builds the S32K344 board image with
the same fixes into `build-board-w8` (not flashed; `build-board/` untouched).

Short version:

- The QEMU image reaches **stage 6, FirstSpin**, and a host `ros2 node list`
  on domain 10 lists all four nodes. Every pool the contract determines is
  derived. Two BOARD FACTS the QEMU conf copies from the S32K344 conf are too
  small for this image, and the boot-through needed both raised through
  `qemu-build`'s env lever, which is not written in any conf: the nano-ros
  heap (peak **190,216 B** at FirstSpin against the board's 94,720) and the
  main stack (**21,464 B** used against the board's 16,384).
- The board image with the same fixes **links**: RAM 323,112 of 327,680 B
  on the merged nano-ros pin.
  The fixes did not push it over, because the retention slot now derives
  from the latched types (105 B, not 1,024 B). But its heap and main stack
  are the same two board facts, and it has no room to raise the heap. It
  cannot reach FirstSpin while `param_services` is on (iteration 6).
- Six causes, fixed in this order:
  1. The contract left nine publishers' durability unstated, so nano-ros
     refused to count the transient-local ones (contract fix).
  2. The retention pool never received the count on the Zephyr road
     (nano-ros fix).
  3. The zenoh-pico cond pool had no floor.
  4. The mutex floor counted subscribers only.
  5. Heap and main stack (board facts, raised for the diagnosis only).
  6. The parameter services' heap at the first spin.

  Plus F3: a transient-local subscription the zenoh shim refuses (island
  fix). nano-ros changes: PR #1311 (issue 1498).

## The rung and the commands

The QEMU commands are as in `docs/emulation.md`. Until the nano-ros change
merged, the image was built against a clone of the pinned nano-ros
(d2671d5b5) with the change applied. The recipe takes it through its
external-root lever. `qemu-build` now names `nano_ros_DIR` too, so the cmake
package, the Zephyr module and the CLI come from one tree:

    NANO_ROS_ALLOW_EXTERNAL_ROOT=1 NANO_ROS_ROOT=/home/aeon/repos/nano-ros-w8pin \
        just QEMU_BUILD_DIR=build-qemu-w8 qemu-build
    NANO_ROS_ALLOW_EXTERNAL_ROOT=1 NANO_ROS_ROOT=/home/aeon/repos/nano-ros-w8pin \
        just QEMU_BUILD_DIR=build-qemu-w8 qemu-run 40

The diagnostic overrides go through the recipe's existing env lever. W8
added `CONFIG_MAX_PTHREAD_COND_COUNT` to that lever. The overrides are never
written in a conf, for example:

    CONFIG_MAIN_STACK_SIZE=32768 CONFIG_NROS_ZEPHYR_HEAP_SIZE=393216 just ... qemu-build

The pool counts below were read with gdb on the QEMU gdbstub (`-s -S`), using
the nros store's `arm-none-eabi-gdb`. That gdb needs `libncursesw.so.5`; a
symlink to `.so.6` on `LD_LIBRARY_PATH` satisfies it. The breakpoints were on
the zpico failure `printk` sites (`zpico.c:2599`, `:3191`) and on
`pthread_cond_init`. The Zephyr POSIX pools were read from
`_sys_bitarray_bundles_posix_{cond,mutex}_bitarray`.

## Iteration 1: the durability stated on five publishers is not enough

`just qemu-build` on HEAD (the contract states `durability: transient_local`
on the five latched publishers). The build was 22 s and relinked nothing, and
the derived table and pool did not move. From `build-qemu/`:

    nros/entity_inventory.cmake:60:set(NROS_DERIVED_MAX_QUERYABLES 26)
    nros/entity_inventory.cmake:62:set(NROS_ENTITY_APP_QUERYABLES 2)
    .../nros-rmw-zenoh-*/out/buffer_config.rs:68:pub const MAX_TL_PUBLISHERS: usize = 2;

**Cause.** nano-ros counts transient-local publishers with one rule,
`nros_sizing_descriptor::transient_local_publishers_over`. That rule
REFUSES the count when any publisher states no durability ("a count over the
rows that answered is not a bound on the row that did not"), and a refusal
contributes 0 to the queryable table. Five of the island's fourteen
publishers stated it. The rule is deliberate and right: an unstated
durability is not a volatile one.

**Fix (contract).** `durability: volatile` is now stated on the other nine
publishers (`safety_island.contract.yaml`, the `pub:` blocks at :262, :299-300,
:387-391 and :409). Each was checked against its source: the default profile,
or `QoS(5)` for `stop_mode/control`, both volatile. Re-running the inventory
by hand:

    set(NROS_DERIVED_MAX_QUERYABLES 31)
    set(NROS_ENTITY_APP_QUERYABLES 7)

## Iteration 2: the table is 31 and the pool is still 2

The queryable table now counts the five transient-local cache queryables, and
`nros-rmw-zenoh`'s retention pool is still `TL_PUBLISHERS_DEFAULT = 2`.

**Cause (nano-ros).** On a Zephyr west entry, `nros-rmw-zenoh/build.rs` sizes
the pool from the sizing descriptor only. A west build names no descriptor
to cargo (nano-ros issue 1393), and never receives the CMake road's
`NROS_DECLARED_TL_PUBLISHERS` either. The table and the pool derive from one
rule and reached the image on two roads, and only one road was wired.

**Fix (nano-ros PR #1311, issue 1498).**
- The entity inventory publishes `NROS_DERIVED_TL_PUBLISHERS`, only when the
  rule states a count.
- The Zephyr resolver forwards it on the derivable ladder as
  `NROS_DECLARED_TL_PUBLISHERS`.
- `nros-rmw-zenoh/build.rs` reads that carrier as the pool's demand when no
  descriptor is named.
- The retention SLOT now derives too. It was a flat 1,024 B, and is now the
  largest `_TX` bound over the transient-local types: `VelocityLimit`, 105 B.
  W7 measured that at 1,024 B a pool of 5 overflows the board.

The resulting build (`build-qemu-w8`):

    nros/entity_inventory.cmake:65:set(NROS_DERIVED_TL_PUBLISHERS 5)
    nros/message_bound_knobs.cmake:49:set(NROS_DERIVED_TL_RETAIN_BYTES 105)
    CMakeCache.txt: NROS_RESOLVED_NROS_DECLARED_TL_PUBLISHERS:INTERNAL=5
    CMakeCache.txt: NROS_RESOLVED_ZPICO_MAX_QUERYABLES:INTERNAL=31
    CMakeCache.txt: NROS_RESOLVED_ZPICO_TL_RETAIN_BYTES:INTERNAL=105
    buffer_config.rs: pub const MAX_TL_PUBLISHERS: usize = 5;
    buffer_config.rs: pub const TL_RETAIN_BYTES: usize = 105;
    check-knob-delivery: DERIVED_PAIRS names every one of the 25 resolver call site(s) over 23 fact(s).

F1 is gone: all three of `stop_mode_operator`'s latched publishers register.
Next is F2 (`build/emulation/qemu-20260925T182138.log`):

    zpico: z_declare_subscriber (ring) failed: -1 for '10/system/mrm/comfortable_stop/status/tier4_system_msgs::msg::dds_::MrmBehaviorStatus_/*'
    [ERROR] .../nros-cpp/include/nros/node.hpp:324 node "mrm_handler": FAILED at create_subscription_in (code=-100)
    [nros] FATAL: node "mrm_handler" failed to construct at create_subscription_in (code=-100)
    zpico: z_declare_subscriber (ring) failed: -1 for '10/system/mrm/emergency_stop/status/tier4_system_msgs::msg::dds_::MrmBehaviorStatus_/*'
    zpico: z_declare_subscriber (ring) failed: -1 for '10/api/operation_mode/state/autoware_adapi_v1_msgs::msg::dds_::OperationModeState_/*'
    zpico: z_declare_subscriber (ring) failed: -1 for '10/control/command/gear_cmd/autoware_vehicle_msgs::msg::dds_::GearCommand_/*'
    nros: HEAP EXHAUSTED: request 194 bytes, arena 94720 bytes, caller 0xec23

## F3, decided alongside: the transient-local subscription

`mrm_handler`'s `/api/operation_mode/state` subscription was
`QoS(1).transient_local()`. The zenoh shim refuses that for anything but a
publisher (`nros-rmw-zenoh/src/shim/qos.rs`, `admit`: "the shim serves
publisher-side retention only; a subscription cannot query a peer's cache on
match yet"). That is a documented design decision (phase-455 W5, issue 1341),
not an oversight: the subscriber half is "a real capability and is not built".

**Fix (island, `mrm_handler_core.cpp:104-118`).** The subscription is
`QoS(1)`, volatile. Latching buys nothing on this island, because the contract
declares `operation_mode_state: { min_rate_hz: 10 }` on this subscription:
the mode is republished every 100 ms, and a late joiner has it within one
period. The upstream comment's concern (a late joiner stuck in "emergency"
until the mode next changes) holds only if that rate claim is false, and the
new comment says so. A volatile reader is RxO-compatible with the latched
writer. The fix is unconditional, so the cyclone native_sim image runs the
same QoS. nano-ros's shim was not changed: nothing the island needs is
refused.

## Iteration 3: the cond pool, not the subscriber table (F2)

`z_declare_subscriber` returned -1 while `ZPICO_MAX_SUBSCRIBERS` (11) had
room. At the failure breakpoint:

    == ring declare failed ret=-1 key=10/system/mrm/comfortable_stop/status/tier4_system_msgs::msg::dds_::MrmBehaviorStatus_/*
    cond bundles  0000ffff
    mutex bundles 7fffffff 00000000

That is 16 of 16 conds in use and 31 of 64 mutexes. A breakpoint on
`pthread_cond_init` counted 20 calls:

- 1 from `zpico_open`;
- 19 from `_z_sync_group_state_create`: the session's own sync group, 7
  queryables and 7 subscribers that succeeded, and then the 8th subscriber
  retried as it failed.

**Cause.** zenoh-pico gives every declared subscriber AND queryable a
callback-drop sync group, and each takes one mutex and one cond from Zephyr's
static POSIX pools. nano-ros floors the mutex pool (subscribers + 22 + 4) and
not the cond pool, whose Kconfig default is 16. W2 doubled the mutex pool
and the heap, which is why F2 survived its diagnosis. The four subscriptions
W7 reported as getting no token are these four declarations.

**Fix (nano-ros, same PR).** For an image whose queryable table is DERIVED,
the resolver now floors the cond pool at subscribers + queryables + 2 + 4,
and refuses the configure below the floor, naming the number. This is a
floor and not a derivation, by nano-ros's stated rule for these pools
("DELIBERATELY NOT DERIVED ... A floor with a measured constant is honest
about being a bound rather than a model"). Kconfig cannot take a derived
default, so the island STATES the value the floor names, and the configure
checks it every time. See iteration 5 for the value.

With the cond pool at 64 (diagnostic), every subscriber registers.
`build/emulation/qemu-20260925T184224.log`:

    nros: HEAP EXHAUSTED: request 236 bytes, arena 94720 bytes, caller 0x296fb

`addr2line 0x296fb` gives `_z_slist_new`, which is zenoh-pico's session
lists, during `mrm_handler`'s registration. The heap peak is 88,312 B, and
the boot report says:

    HEAP HEADROOM: REFUSED -- 6408 bytes, floor is 24576.
    set CONFIG_NROS_ZEPHYR_HEAP_SIZE >= 112888

## Iteration 4: the main stack

The heap was raised to 196,608 B for the diagnosis. The console,
`qemu-gdb3.log`:

    [00:00:02.227,000] <err> os: ***** MPU FAULT *****
    [00:00:02.228,000] <err> os:   Data Access Violation
    [00:00:02.228,000] <err> os:   MMFAR Address: 0x200765c0
    [00:00:02.228,000] <err> os: >>> ZEPHYR FATAL ERROR 2: Stack overflow on CPU 0
    [00:00:02.229,000] <err> os: Current thread: 0x20021088 (main)

`MMFAR` is `z_main_stack`'s first byte. The faulting frame is
`nros_rmw_cffi::to_c_str` under `CffiSession::create_service`: `main`
constructs every node and its services on its own 16,384 B stack. `qemu-run`
reported only `stage 4 ... Halted DURING REGISTRATION ... the arena is not
the cause`. The fault lines are in the console log. They are not in the
recipe's tail.

## Iteration 5: the mutex pool, with the queryables counted

The main stack was raised to 32,768 B for the diagnosis. The four nodes
appeared in the host graph for the first time
(`qemu-20260925T184714.graph.txt`). Then:

    zpico: z_declare_queryable failed: -1 for '10/mrm_handler/describe_parameters/rcl_interfaces::srv::dds_::DescribeParameters_/TypeHashNotSupported'

At the breakpoint:

    == queryable failed ret=-1 key=10/mrm_handler/describe_parameters/...
    cond bundles  ffffffff 000007ff
    mutex bundles ffffffff ffffffff
    idx=29

That is 64 of 64 mutexes, with 11 subscribers and 29 queryables declared, so
zenoh-pico holds 24 others.

**Cause.** nano-ros's mutex floor (subscribers + 22 + 4 = 37 here) was
measured on an image with 2 queryables. The parameter services add six per
node.

**Fix (nano-ros, same PR).** For a derived table, the resolver takes the
mutex floor again with both terms: subscribers + queryables + 24 + 4 = 70.
The island states both pools in both confs:

    src/qemu_entry/boards/mps2_an385.conf:59     CONFIG_MAX_PTHREAD_MUTEX_COUNT=70
    src/qemu_entry/boards/mps2_an385.conf:60     CONFIG_MAX_PTHREAD_COND_COUNT=48
    src/zephyr_entry/boards/mr_canhubk3_s32k344.conf:457 CONFIG_MAX_PTHREAD_MUTEX_COUNT=70
    src/zephyr_entry/boards/mr_canhubk3_s32k344.conf:458 CONFIG_MAX_PTHREAD_COND_COUNT=48

The floor at work, from a configure with the mutex pool still at 64:

    CMake Error at /home/aeon/repos/nano-ros-w8pin/zephyr/cmake/nros_cargo_build.cmake:795 (message):
      CONFIG_MAX_PTHREAD_MUTEX_COUNT=64 is too small for 11 subscribers and 31
      queryables.
        need at least 70 = 11 subscribers + 31 queryables + 24 zenoh-pico fixed + 4 headroom

At FirstSpin (iteration 7) the pools held 45 conds (`ffffffff 00001fff`) and
66 mutexes (`ffffffff ffffffff 00000003`), against 48 and 70.

## Iteration 6: the parameter services at the first spin

With the pools at 70/48, `build/emulation/qemu-20260925T185334.log`:

    nros: HEAP EXHAUSTED: request 3548 bytes, arena 197120 bytes, caller 0x45e89

`0x45e89` is `Box::<ParameterServiceServers>::new` in
`Executor::reconcile_parameter_services` (`nros-node/src/executor/spin.rs:9307`).
The executor builds each node's six parameter services on its first spin. The
peak was 184,312 B before the failure.

## Iteration 7: FirstSpin

With the heap at 393,216 B and the main stack at 32,768 B (both diagnostic, on
the env lever), `build/emulation/qemu-20260925T185510.*`. The boot report:

    stage      6  FirstSpin -- registration complete and spinning
      arena capacity                50640
      arena used                    14248   (28.1%)
      arena allocations             17
      platform heap PEAK            190216 bytes   (48.3% of the heap)
      platform heap capacity        393728 bytes   (NROS_ZEPHYR_HEAP_SIZE)
    HEAP HEADROOM: ok -- 203512 bytes spare (peak 190216 of 393728, floor 24576).
      CONFIG_NROS_ZEPHYR_HEAP_SIZE could go as low as 214792 on this
      evidence.

The host graph, `ros2 node list` on domain 10 at t=+20 s, as `qemu-run` does it:

    /mrm_comfortable_stop_operator
    /mrm_emergency_stop_operator
    /mrm_handler
    /stop_mode_operator

All 23 island topics are in `ros2 topic list`, besides `/parameter_events` and `/rosout`. The main-stack high-water
mark, read with gdb as the first non-`0xaa` byte above the 64-byte guard, is
**21,464 B of 32,832**.

### The final runs, with the code as it stands

Both runs used the final island sources (F3 unconditional), in fresh build
directories against the patched pin.

**Conf values, no overrides** (`build-qemu-w8d`, `qemu-20260925T210548.*`).
The build converged in one `qemu-build`:

    Memory region         Used Size  Region Size  %age Used
               FLASH:      602636 B         4 MB     14.37%
                 RAM:      437812 B         4 MB     10.44%
    check-knob-delivery: DERIVED_PAIRS names every one of the 25 resolver call site(s) over 23 fact(s).
    qemu-build: tolerating the known upstream SUBSCRIBED_TYPE_BOUNDS line (phase-412 W4); nothing else is red.

The run stops where the board's heap stops:

    *** Booting Zephyr OS build v4.4.0 ***
    nros: HEAP EXHAUSTED: request 236 bytes, arena 94720 bytes, caller 0x296ff
    nros: PANIC platform heap exhausted (see the HEAP EXHAUSTED line above, and the boot report's failed_alloc_size)
    stage      4  RegisteringEntities -- an entity claimed arena; registration in flight
      platform heap PEAK            88312 bytes   (93.2% of the heap)

**Heap and main stack raised on the env lever** (`build-qemu-w8e`,
`qemu-20260925T211712.*`):

    qemu-build: env overrides -> -DCONFIG_NROS_ZEPHYR_HEAP_SIZE=393216 -DCONFIG_MAIN_STACK_SIZE=32768
               FLASH:      602660 B         4 MB     14.37%
                 RAM:      753204 B         4 MB     17.96%
    *** Booting Zephyr OS build v4.4.0 ***
    qemu-system-arm: terminating on signal 2 from pid 1502459 (timeout)
    stage      6  FirstSpin -- registration complete and spinning
      platform heap PEAK            190216 bytes   (48.3% of the heap)
    == ros2 node list (rmw_zenoh_cpp, domain 10), t=+20 s ==
    /mrm_comfortable_stop_operator
    /mrm_emergency_stop_operator
    /mrm_handler
    /stop_mode_operator

The console carries no error line at all.

**The merged pin** (nano-ros 91a9a1edc, `just qemu-build` in the default
`build-qemu`, `qemu-20260925T220524.*`) derives the same values and stops at
the same heap, now through the plain recipe with no external root:

    Memory region         Used Size  Region Size  %age Used
               FLASH:      603080 B         4 MB     14.38%
                 RAM:      438324 B         4 MB     10.45%
    check-knob-delivery: DERIVED_PAIRS names every one of the 25 resolver call site(s) over 23 fact(s).
    set(NROS_DERIVED_MAX_QUERYABLES 31)
    set(NROS_DERIVED_TL_PUBLISHERS 5)
    pub const MAX_TL_PUBLISHERS: usize = 5;
    pub const TL_RETAIN_BYTES: usize = 105;
    nros: HEAP EXHAUSTED: request 236 bytes, arena 94720 bytes, caller 0x296ff

## Where it stands, and the two numbers that are board facts

On the heap and the main stack, the QEMU conf follows its own rule: it copies
the S32K344's values "so that ... a board-sized pool that is too small fails
HERE first". That is what happened, so the conf keeps 94,208 and 16,384.
Raising them there would hide the board's problem, not solve it:

| | board conf states | this image needs (QEMU, FirstSpin) |
| --- | --- | --- |
| nano-ros heap | 94,208 (arena 94,720) | peak 190,216; with the 24,576 floor, 214,792 |
| main stack | 16,384 | 21,464 used |
| mutex / cond pools | 70 / 48 (W8) | 66 / 45 at FirstSpin |

The heap is the one that cannot be met on the board. The registration peak
alone is 111,904 B, and the parameter services add about 78 KB at the first
spin (190,216 - 111,904). The board image has 4,568 B of SRAM left and
46,544 B of DTCM, so even with the heap in DTCM its RAM is short by more
than 100 KB. `system.toml` already names the cause and the way out:
"The services cost 24 queryables and are the reason the S32K344 image does
not fit; a store-only capability (no queryables, no `ros2 param`) is planned
as nano-ros phase-461 W6". Phase-461 W6 is "not started" at nano-ros main
2d14dca82. With it, the 24 parameter queryables and the reconcile's
allocations go away. That is the board's next step, and a smaller main stack
is not a substitute for it.

These heap figures come from the Ethernet image, which is not the board's
transport. At stage 4, W2 found them close to the serial board image's
(55,792 vs 57,024 B). Whether that holds at FirstSpin is unmeasured.

## F6: the domain

nano-ros decided this one deliberately. Kconfig's `CONFIG_NROS_DOMAIN_ID` is
what the image bakes (RFC-0049), and `system.toml` "gains no authority over a
build-time knob". The agreement check that refuses a disagreement
(`nros_system_check_domain_agreement`, phase-460 W4, issue 1423) runs only in
`nros_system_generate`. The island's entries use `nano_ros_add_executable`
(`NanoRosEntry.cmake`), where it does not run. The configure prints the
system's value (`deployment from .../src/qemu_entry/system.toml ...
domain_id=10`) and compares it with nothing. So the domain cannot reach the
image from `system.toml`. The snippets state `CONFIG_NROS_DOMAIN_ID=10`
(`qemu-ethernet/ethernet.conf`, `island-serial/serial.conf`), and nothing
checks that they agree. The gap to file upstream: that check should also run
on the entry road.

## F7: the log facade

The pool refusals of iterations 3 and 5 reached the console through
zenoh-pico's C `printk` (`zpico: z_declare_* failed`). None of nano-ros's
Rust-side refusals did. The retention-pool message W2 looked for is one of
them. Not investigated further here: gdb on the `printk` sites and the boot
report answered every question this unit had.

## Region reports

QEMU (`mps2/an385`, qemu-ethernet), as `qemu-build` prints them:

| image | FLASH | RAM |
| --- | --- | --- |
| before (W2, `build-qemu`, pin d2671d5b, TL pool 2, queryables 26) | 603,096 B | 435,124 B |
| TL pool 5 at 105 B, queryables 31 (`build-qemu-w8`, iteration 2) | 602,628 B | 437,300 B |
| plus cond 64 (iteration 3) | 602,628 B | 437,876 B |
| FINAL, conf values: pools 70/48, heap 94,208, stack 16,384 (`build-qemu-w8d`, pin + patch) | 602,636 B | 437,812 B |
| the same on the merged pin 91a9a1edc (`build-qemu`, `just qemu-build`) | 603,080 B | 438,324 B |
| diagnostic, FirstSpin: heap 393,216, stack 32,768 (`build-qemu-w8e`) | 602,660 B | 753,204 B |

The S32K344 board image (`mr_canhubk3/s32k344`, island-serial, tracing on,
`CONFIG_TRACING_THREAD=n`):

| image | RAM (SRAM) | DTCM | ITCM | FLASH |
| --- | --- | --- | --- | --- |
| before, per W1 (with tracing, TL pool 2, 26 queryables) | 319,904 of 327,680 | | | |
| before, per W7: pool 5 at 1,024 B plus 31 queryables | overflowed by 3,352 B | | | |
| W8 on pin + patch (`build-board-w8`, first build): pool 5 at 105 B, 31 queryables, mutex 70, cond 48 | 322,600 of 327,680 (98.45%) | 84,528 of 131,072 | 14,108 of 65,536 | 627,920 |
| W8 on the merged pin 91a9a1edc (`just BOARD_BUILD_DIR=build-board-w8 board-build`, twice, fresh dir) | **323,112 of 327,680 (98.61%), 4,568 B left** | 84,528 of 131,072 | 14,108 of 65,536 | 628,376 |

The final board build, verbatim (the same table on both passes; the knob
check converged on the first):

    Memory region         Used Size  Region Size  %age Used
          IVT_HEADER:         256 B        256 B    100.00%
               FLASH:      628376 B    4144896 B     15.16%
                 RAM:      323112 B       320 KB     98.61%
                ITCM:       14108 B        64 KB     21.53%
                DTCM:       84528 B       128 KB     64.49%
            IDT_LIST:           0 B        32 KB      0.00%
    check-knob-delivery: DERIVED_PAIRS names every one of the 25 resolver call site(s) over 23 fact(s).
    board-build: tolerating the known upstream SUBSCRIBED_TYPE_BOUNDS line (phase-412 W4); nothing else is red.
    buffer_config.rs: pub const MAX_TL_PUBLISHERS: usize = 5;
    buffer_config.rs: pub const TL_RETAIN_BYTES: usize = 105;

`board-size`'s symbol reports (`rom_report` / `ram_report`) did not run.
The store venv has no `anytree` (`ModuleNotFoundError: No module named
'anytree'`), which is an environment gap and not this image's. The 512 B
between the two W8 rows is the 62 other nano-ros commits between d2671d5b5
and 91a9a1edc.

Nothing was cut. The derived retention slot (5 x 105 B, not 5 x 1,024 B) paid
for the three extra slots, the five extra queryables and the 6 + 32 extra
POSIX objects. The 776 B provenance staging packet and a smaller
`RAM_TRACING_BUFFER_SIZE` are still available, if the board ever needs them.

## Parameter store, minimal form

phase8-W1, 2026-09-29. `features = []` in
`src/safety_island_bringup/system.toml` (the parameter services off;
`src/qemu_entry/system.toml` declares no `features`). nano-ros PR #1384
(issue 1529, merged as cc1f5a93e) splits nros-cpp's feature: `param-store`
compiles the store entry points (launch seeds, node-scoped
declare/get/set) and every Zephyr C++ image gets it; `param-services` adds
only the six servers. The island's pin is cc1f5a93e with no local patch.

What the island keeps: the parameter STORE. The generated entry seeds the
launch file's `<param from>` values (21 `nros_cpp_declare_param` calls in
`build-qemu/qemu_entry_nros_main_generated.cpp`, no
`register_parameter_services`), and each component's `declare_parameter`
returns the seeded value, or its source default, instead of Unsupported
(-16). What it loses: `ros2 param get/set/list/describe/dump`, the
parameter services, and the `use_sim_time` runtime switch. From the host
during the FirstSpin run below:

    == ros2 service list ==
    /system/mrm/comfortable_stop/operate
    /system/mrm/emergency_stop/operate
    == ros2 param list ==
    (empty)

The seeds keep the yaml's values, so `use_comfortable_stop` boots **false**
(`mrm_handler.param.yaml:13`; the source default is true and the demo wants
true). That is a yaml edit, not a store question; it is left open here.

The derived tables (`build-qemu/nros/entity_inventory.cmake`):

    set(NROS_DERIVED_MAX_QUERYABLES 7)
    set(NROS_ENTITY_APP_QUERYABLES 7)
    set(NROS_DERIVED_MAX_PARAMETERS 25)
    NANO_ROS_FEATURES:STRING=

`just sync` still prints "no producer" for the four components' source
metadata. That is the host metadata probe, and it failed the same way
before this change: two probes build and then halt at `declare_parameter
(code=-16)` because capabilities are not lowered into the probe (issue
0543: the probe is per workspace), and two fail to build on the host's
unbounded `header.frame_id` (Odometry, VelocityReport). The image's tables
come from the launch model, not the probe.

**QEMU at the conf values** (heap 94,208, main stack 16,384; `just
qemu-build` in `build-qemu`, `qemu-20260929T060055.*`). It links:

    Memory region         Used Size  Region Size  %age Used
               FLASH:      603868 B         4 MB     14.40%
                 RAM:      403956 B         4 MB      9.63%
    check-knob-delivery: DERIVED_PAIRS names every one of the 25 resolver call site(s) over 23 fact(s).
    qemu-build: tolerating the known upstream SUBSCRIBED_TYPE_BOUNDS line (phase-412 W4); nothing else is red.

It stops at registration on the platform heap, not on the store:

    nros: HEAP EXHAUSTED: request 236 bytes, arena 94720 bytes, caller 0x297bb
    stage      4  RegisteringEntities -- an entity claimed arena; registration in flight
      arena used                    14196   (28.0%)
      platform heap PEAK            88312 bytes   (93.2% of the heap)
      platform heap capacity        94720 bytes   (NROS_ZEPHYR_HEAP_SIZE)

`0x297bb` is `_z_slist_new` (zenoh-pico `src/collections/list.c:263`). The
boot report also prints "ARENA EXHAUSTED ... 236 bytes"; the executor arena
is 14,196 of 50,640 used, so that line reads the heap failure's size as an
arena one.

**QEMU at the D4 heap, conf stack** (`CONFIG_NROS_ZEPHYR_HEAP_SIZE=122880`
on the env lever, main stack 16,384 from the conf, `build-qemu-w1d`,
`qemu-20260929T060339.*`):

               FLASH:      603868 B         4 MB     14.40%
                 RAM:      432628 B         4 MB     10.31%
    *** Booting Zephyr OS build v4.4.0 ***
    stage      6  FirstSpin -- registration complete and spinning
      arena used                    14248   (28.1%)
      platform heap PEAK            109376 bytes   (88.6% of the heap)
      platform heap capacity        123392 bytes   (NROS_ZEPHYR_HEAP_SIZE)
    HEAP HEADROOM: REFUSED -- 14016 bytes, floor is 24576.
      set CONFIG_NROS_ZEPHYR_HEAP_SIZE >= 133952

The console carries no error line, and `ros2 node list` on domain 10 lists
all four nodes. Two earlier FirstSpin runs of the same build on the
pre-merge commit peaked at 105,976 and 108,624 B. So the first spin needs
14,656 B more than the conf's arena (109,376 - 94,720), and the headroom
floor asks for 133,952 B, 39,744 B above the conf's 94,208. With the
services on, the peak was 190,216 B (iteration 7). The heap value is W8's
call (D4 allows 122,880 in the board conf); this unit did not change a
conf.

**The S32K344 board image** (`just BOARD_BUILD_DIR=build-board-w1
board-build`, twice, the same table on both passes, not flashed; queryables
7; heap 94,208 from the conf):

    Memory region         Used Size  Region Size  %age Used
          IVT_HEADER:         256 B        256 B    100.00%
               FLASH:      629160 B    4144896 B     15.18%
                 RAM:      288792 B       320 KB     88.13%
                ITCM:       14108 B        64 KB     21.53%
                DTCM:       84528 B       128 KB     64.49%
            IDT_LIST:           0 B        32 KB      0.00%
    check-knob-delivery: DERIVED_PAIRS names every one of the 25 resolver call site(s) over 23 fact(s).
    board-build: tolerating the known upstream SUBSCRIBED_TYPE_BOUNDS line (phase-412 W4); nothing else is red.

Against W8's 323,112 B with the services on, the board's SRAM drops by
34,320 B, leaving 38,888 B.

## The demo image

phase8-W8a, 2026-09-29. The island is sized for the RTSS@Work demo
(`docs/roadmap/phase-8-rtss-work-demo.md`: acts A, B and the encore, the
live timeline, and what the host's Autoware reads), not as a complete
safety island. Island pin bec9aecb8, `features = []` as in W1.

**What left the image, and the reader checked first** (Autoware 1.5.0
source under `~/repos/autoware/1.5.0-ws`, the demo's `demo/host_ws`
overlay, `tools/timeline`, `demo/l3/takeover_demo`):

| cut | reader in the demo | why it can go |
|---|---|---|
| `stop_mode_operator`, whole node (D4) | none: 1.5.0 launches it only with the control-command gate; the demo runs `vehicle_cmd_gate` | three 30 Hz inputs (steering, velocity, route state), four outputs (three latched), 6 of the old 38 trace markers and G9's 34 % of marker volume |
| `mrm_handler` `/system/emergency/gear_cmd` and its `/control/command/gear_cmd` pass-through input | `vehicle_cmd_gate` only, and only while `mrm_state` says `EMERGENCY_STOP` (`onMrmState`) | with no sample the gate keeps the gear it last sent (`getContinuousTopic` returns the previous command when the new stamp is older), which is DRIVE; the island sent DRIVE too (`use_parking_after_stopped: false`) |
| `mrm_handler` `/system/emergency/turn_indicators_cmd` | `vehicle_cmd_gate`, same condition | the gate keeps the planner's last indicator; nothing in the demo shows it |
| `mrm_handler` `/system/fail_safe/emergency_holding` | the host's `hazard_status_converter` (W3's remap, G10) | it reads a missing sample as `false` (`converter.cpp:122-124`), the only value the island could send with `use_emergency_holding: false` |

Kept, although the planning simulator never shows it (W7 finding 4):
`/system/emergency/hazard_lights_cmd`, read by the demo's `hazard_relay`
(branch B), by `vehicle_cmd_gate` in the encore, and by the timeline probe.
Kept: `clear_velocity_limit`, the only thing that lifts the comfortable
stop's latched limit when the fault clears. The handler still declares
`turning_indicator_on.emergency` and `use_parking_after_stopped`; nothing
reads them now (the parameter store is small; the declarations stay with
the upstream code).

The contract, the launch file, `system.toml`, the three entries' builds
(the `add_subdirectory` lines and the board's ITCM relocation), the bringup
`package.xml`, the demo composition contracts (`demo/l3/contracts/`, three
files) and `takeover_demo`'s island node list changed together.
`play_launch check` (92043c82, built from the nano-ros vendored copy) on
the island contract: `1 manifest(s) checked: 1 clean, 0 with errors (0
errors, 2 warnings)`, every budget row as W7's; the demo composition
20,636.67 / 14,538.67 / 4,808.67 ms as W6's, the two variants refused on
the comfortable rung only (30,636.67 and 30,366.67 ms). `just l3-check`
(the CI script, pinned wheel 0.12.0): `14 contract(s) checked; every
verdict as expected`. Trace markers regenerate from 38 to 29: stop_mode's 6 and
the handler's three dropped publishers.

**The derived tables** (`build-qemu-w8a/nros/entity_inventory.cmake`
against W1's):

| | W1 (4 nodes) | W8a (3 nodes) |
|---|---|---|
| entities (inventory) | 33 | 23 (22 in the image; see below) |
| publishers / subscriptions | 14 / 11 | 9 / 7 (8 / 7 in the image) |
| queryables | 7 derived | 2 derived, 4 stated (below) |
| `NROS_EXECUTOR_MAX_CBS` | 19 | 14 |
| executor arena | 50,640 | 35,920 |
| `NROS_MAX_LIVELINESS` | - | 25 |
| POSIX mutex / cond pools | 70 / 48 | 39 / 17 |

**A defect this surfaced: the external availability publisher.** W7 named
the demo's gate as the external publisher of
`/system/operation_mode/availability` (`pub: [/availability_gate/availability]`;
without it `odd_exit` is `hazard-unguarded`, re-checked here). nano-ros's
entity inventory composes that name into the image as a fourth component
(`availability_gate = 1 entities, 0 slots`) although the model marks the
topic `externals: pub`, and its row states no durability, so:

    # NROS_DERIVED_TL_PUBLISHERS is not derived: publisher /system/operation_mode/availability (tier4_system_msgs/msg/OperationModeAvailability) states no `durability`: nothing derived it. A count over the rows that answered is not a bound on the row that did not
    set(NROS_DERIVED_MAX_QUERYABLES 2)

and the image boots short of the two cache queryables the comfortable-stop
operator's latched publishers need (QEMU, heap 122,880, conf stack,
`qemu-20260929T083204.*`):

    [nros] FATAL: node "mrm_comfortable_stop_operator" failed to construct at create_publisher_in (code=-3)
    stage      4  RegisteringEntities -- an entity claimed arena; registration in flight

The contract cannot state that endpoint's QoS: a `nodes:` block for the
gate is refused (`node-identity-unknown`) or, keyed absolute, passes and
never reaches `contracts.pub_endpoints`; a topic-level `qos:` reaches the
subscriber's row only. So both confs STATE `CONFIG_NROS_MAX_QUERYABLES=4`
(2 services + 2 latched publishers; the retention pool's builtin of 2
covers the 2 latched publishers), and `qemu-build` tolerates that one
knob-delivery line by its exact values
(`NROS_DERIVED_MAX_QUERYABLES=2 but NROS_RESOLVED_NROS_MAX_QUERYABLES=4`),
and so does `board-build`. The right fix is nano-ros's: skip a publisher
the model lists under `externals`. The POSIX pools follow nano-ros's own
formula for 7 subscribers and 4 queryables: 7 + 4 + 24 + 4 = 39 mutexes,
7 + 4 + 2 + 4 = 17 conds (stated, because nano-ros re-takes that floor only
for a derived table).

**QEMU, heap on the lever, conf stack** (`CONFIG_NROS_ZEPHYR_HEAP_SIZE`
122,880 and 1,048,576, main stack 16,384; `build-qemu-w8a`,
`build-qemu-w8a-1m`):

               FLASH:      581764 B         4 MB     13.87%
                 RAM:      391156 B         4 MB      9.33%
    stage      6  FirstSpin -- registration complete and spinning
      arena used                    11680   (32.5%)
      platform heap PEAK            75760 bytes   (61.4% of the heap)
      platform heap capacity        123392 bytes   (NROS_ZEPHYR_HEAP_SIZE)
    HEAP HEADROOM: ok -- 47632 bytes spare (peak 75760 of 123392, floor 24576).
      CONFIG_NROS_ZEPHYR_HEAP_SIZE could go as low as 100336 on this

Four FirstSpin runs, peak 75,760 / 74,856 / 76,080 B at the 122,880 heap
(`qemu-20260929T092349`, `T092558`, `T092841`) and 75,736 B at 1 MiB
(`T101644`): the peak does not grow with the heap. Against W1's 109,376 B
at the same heap, the demo image needs 33,296 B less at the first spin (against the largest of the four).
The same image at 122,880 links 41,472 B smaller in RAM than W1's (391,156
against 432,628). The host saw the three nodes:

    == +15 s
    /mrm_comfortable_stop_operator
    /mrm_emergency_stop_operator
    /mrm_handler

**The heap value.** The headroom rule asks for peak + 24,576 floor; the
largest of the four asks for >= 100,656, and rounded up to 4 KiB that is
**102,400**, now the value in both confs (was 94,208).

**QEMU at the conf values** (heap 102,400, main stack 16,384;
`build-qemu-w8a`, `qemu-20260929T111152.*`):

               FLASH:      581764 B         4 MB     13.87%
                 RAM:      370676 B         4 MB      8.84%
    stage      6  FirstSpin -- registration complete and spinning
      arena used                    11680   (32.5%)
      platform heap PEAK            75720 bytes   (73.6% of the heap)
      platform heap capacity        102912 bytes   (NROS_ZEPHYR_HEAP_SIZE)
    HEAP HEADROOM: ok -- 27192 bytes spare (peak 75720 of 102912, floor 24576).

and `ros2 node list` on domain 10 at +15 s lists the three nodes.

**The S32K344 board image** (`just BOARD_BUILD_DIR=build-board-w8a
board-build`, island-serial, heap 102,400, trace buffer 16,384, not
flashed; twice, the same table: the first pass refused on the
MAX_QUERYABLES line, the second, with the tolerance, exits 0 and prints
`board-build: tolerating the known upstream SUBSCRIBED_TYPE_BOUNDS line
(phase-412 W4) and the stated MAX_QUERYABLES=4 (phase8-W8a); nothing else
is red.`):

    Memory region         Used Size  Region Size  %age Used
          IVT_HEADER:         256 B        256 B    100.00%
               FLASH:      606952 B    4144896 B     14.64%
                 RAM:      277208 B       320 KB     84.60%
                ITCM:       10996 B        64 KB     16.78%
                DTCM:       62872 B       128 KB     47.97%
            IDT_LIST:           0 B        32 KB      0.00%

Against W1's 288,792 B at the 94,208 heap: 11,584 B less SRAM with an
8,192 B larger heap, 50,472 B free. DTCM (the relocated executor storage)
drops 21,656 B and ITCM (the node bodies) 3,112 B.

**Before and after:**

| | W1 (HEAD 55a65a4) | W8a |
|---|---|---|
| nodes | 4 | 3 |
| entities (inventory) | 33, 14 publishers | 23, 9 publishers (22 and 8 in the image) |
| queryables | 7 | 4 |
| heap PEAK at FirstSpin (QEMU) | 109,376 | 74,856-76,080 (5 runs) |
| `CONFIG_NROS_ZEPHYR_HEAP_SIZE` | 94,208 (FirstSpin needs a lever) | 102,400 (headroom ok at the conf) |
| board SRAM | 288,792 (88.13 %) | 277,208 (84.60 %) |

**Not measured here: nano-ros W4** (graph discovery off, D9). Its pin has
not landed; it removes the liveliness subscriber and the graph cache
(`CONFIG_NROS_GRAPH_CACHE_SIZE=4096` of .bss), so it lowers both numbers
further. Re-measure the peak when it does.

**Open: the island leaves the graph when a host peer joins** (QEMU,
plain `rmw_zenohd`, no liveliness ACL). The three nodes are listed at
+15 s and gone at +30 s, +45 s, +60 s and +75 s, at the 122,880 heap and at
1 MiB alike, and with the old 70/48 POSIX pools too, so it is neither the
heap nor this unit's pools. The router's transport log names the moment
(`qemu-20260929T093106.router.log`, `RUST_LOG=zenoh_transport=debug`):
0.15 s after the host's `ros2 node list` peer opened its session, the
island sent a fresh `InitSyn` on its live transport and the router closed
it:

    01:31:32.300 New transport opened between 45dfebbe... and 47298e3e... - whatami: router
    01:31:32.453 Transport: 4b294cb1.... Message handling not implemented: TransportMessage { body: InitSyn(InitSyn { version: 9, whatami: Client, ...
    01:31:32.453 [47298e3e...] Closing transport with peer: 4b294cb1...

No console line, no heap exhaustion (fatal in this image), and the island
does not reconnect within the run. `qemu-run`'s own single query at half
the bound races the drop, which is why some runs list the nodes and some
do not. On the board the W2 gateway keeps liveliness away from the
island, and W4 turns discovery off; this was not run against HEAD.

**Regression, W7's acts on native_sim** (`tools/timeline/run-native.sh`,
one run each, sequential, under the demo lock, load 16-27 at the start;
the declared side from play_launch 92043c82):

    VERDICT: PASS a: v at the fault 3.90 m/s; TOR on True, TOR now 1, control mode 4, mrm (1, 1)
    VERDICT: PASS b: v at the fault 3.86 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v 0.000
    VERDICT: PASS encore: v at the fault 3.87 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)

In w8a-b the `windows` row reads 10,156.01 ms against the declared
10,110.00 (the window expires on the handler's tick; W7's open item, not
this change). The encore's last sample to braking command is 594.00 ms
against 643.33 (W7: 547-570). `trace-check` reports FAIL on each single
act, because it requires every marker in one trace and each act takes one
branch: A misses the 8 comfortable-stop markers, B only the 2 `driver_exit`
markers A records, so the three together see all 29. B publishes
`clear_velocity_limit` when its closing odd-enter cancels the stop, which
is the reason that publisher stays.

### phase8-W14: the pin that carries W4, W5 and issue 1567

nano-ros moved to `da272e419` (main): local queryable derived (issue 1549,
`bf2532c15`), the domain agreement check (issue 1550, `b6b763edb`), graph
discovery as a knob (phase-473 W1, `d04981fe1`), the transient-local
subscriber (phase-473 W2, `a259c7058`), play_launch `bbf9c044` / rlm v0.1.47,
and issue 1567 (`da272e419`: a publisher the contract names on an external
topic is no longer a component of the image). With 1567 the queryable table
derives to 4 again, so both confs drop the stated
`CONFIG_NROS_MAX_QUERYABLES=4` and both recipes drop its knob-delivery
tolerance (W13). The island's TCP snippets (`qemu-ethernet`,
`island-ethernet`) state `CONFIG_NROS_ZENOH_GRAPH_DISCOVERY=n` (a serial
image derives it off).
`mrm_handler` reads `/api/operation_mode/state` TRANSIENT_LOCAL again (W4).

**QEMU** (`build-qemu-w14`, heap 102,400, the configure lines):

    -- nros: NROS_MAX_QUERYABLES=4 DERIVED from this image's entity inventory (nothing in Kconfig or the environment states one)
    -- nros: NROS_RMW_LOCAL_QUERYABLE=1 DERIVED from this image's entity inventory (nothing in Kconfig or the environment states one)
    -- nros: ZPICO_GRAPH_DISCOVERY=0 from CONFIG_NROS_ZENOH_GRAPH_DISCOVERY, which OVERRIDES the value 1 derived from this image's zenoh links (tcp)
    qemu-build: tolerating the known upstream SUBSCRIBED_TYPE_BOUNDS line (phase-412 W4); nothing else is red.
               FLASH:      583056 B         4 MB     13.90%
                 RAM:      361524 B         4 MB      8.62%

RAM 9,152 B below W8a's 370,676 at the same conf. `just qemu-run 40`
(`qemu-20260929T171429.*`, the final tree):

    [00:00:02.323,000] <inf> nros: nros: [    2.323000] graph discovery is compiled out (ZPICO_GRAPH_DISCOVERY=0): no liveliness subscriber and no graph cache. ...
    stage      6  FirstSpin -- registration complete and spinning
      Z_FEATURE_LOCAL_QUERYABLE     1   (DERIVED from the image's entity inventory)
      platform heap PEAK            74016 bytes   (71.9% of the heap)
      platform heap capacity        102912 bytes   (NROS_ZEPHYR_HEAP_SIZE)
    HEAP HEADROOM: ok -- 28896 bytes spare (peak 74016 of 102912, floor 24576).
    == ros2 node list (rmw_zenoh_cpp, domain 10), t=+20 s ==
    /mrm_comfortable_stop_operator
    /mrm_emergency_stop_operator
    /mrm_handler

Four FirstSpin peaks on this pin: 74,016 B three times (`T154909`,
`T155115`, `T171429`) and 71,944 B once (`T160847`, an image with a 60 s
lease built for the W15 handoff below); W8a's were 74,856-76,080. The
largest asks for 74,016 + 24,576 = 98,592, which rounds up to 4 KiB as
**102,400**: the heap stays where W8a put it, in both confs.

**The board image** (`just BOARD_BUILD_DIR=build-board-w14 board-build`,
island-serial, not flashed):

    -- nros: ZPICO_GRAPH_DISCOVERY=0 DERIVED from this image's zenoh links (serial); nothing in Kconfig or the environment states otherwise
    -- nros: NROS_RMW_LOCAL_QUERYABLE=1 DERIVED from this image's entity inventory (nothing in Kconfig or the environment states one)
    board-build: tolerating the known upstream SUBSCRIBED_TYPE_BOUNDS line (phase-412 W4); nothing else is red.
    Memory region         Used Size  Region Size  %age Used
          IVT_HEADER:         256 B        256 B    100.00%
               FLASH:      608384 B    4144896 B     14.68%
                 RAM:      269416 B       320 KB     82.22%
                ITCM:       11000 B        64 KB     16.78%
                DTCM:       61528 B       128 KB     46.94%
            IDT_LIST:           0 B        32 KB      0.00%

SRAM 7,792 B below W8a's 277,208 (58,264 B free), DTCM 1,344 B below.
(`board-size`'s rom/ram reports fail in this environment on a missing
`anytree` module in the west venv; the linker table above is the build's
own.) `just board-doctor` with `ROS_DOMAIN_ID=10` and a pyocd stub on PATH
prints `[OK]      one ROS domain everywhere: 10` over system.toml, both
snippets, the built image and the shell.

**native_sim** (`just zephyr-build`, Cyclone). Issue 1550's configure check
refused this image first (`CONFIG_NROS_DOMAIN_ID = 0 (what the image bakes;
from the Kconfig default ...)` against system.toml's 10): its conf stated
only `CONFIG_NROS_CYCLONE_DOMAIN_ID=10`. prj-cyclonedds.conf now states
`CONFIG_NROS_DOMAIN_ID=10` as well. W7's acts on it
(`tools/timeline/run-native.sh`, under the demo lock, load 20-31 at the
start; the declared side from play_launch bbf9c044):

    VERDICT: FAIL a: v at the fault 3.92 m/s; TOR on True, TOR now 1, control mode 4, mrm (3, 2)
    VERDICT: FAIL b: v at the fault 3.88 m/s; TOR on True, mrm (3, 2) (3 = COMFORTABLE_STOP), v 0.000
    VERDICT: PASS encore: v at the fault 3.90 m/s; mrm (3, 2) (2 = EMERGENCY_STOP), v 0.000, after restore mrm (1, 1)

Both failures are the host gate going silent past the 500 ms `hpc_alive`
bound, after which the island escalated to the emergency stop as the
contract says it must (the same class as W7's b3/b4):

    w14-a | HPC alive: longest availability gap (host) | 500.00 | 1599.93 | FAIL | at 2303 ms; over 500 ms the island raises hpc_loss |
    w14-b | HPC alive: longest availability gap (host) | 500.00 | 1901.49 | FAIL | at 860 ms; over 500 ms the island raises hpc_loss |

Reruns: `VERDICT: PASS a: v at the fault 3.90 m/s; TOR on True, TOR now 1,
control mode 4, mrm (1, 1)` (w14-a2, largest gap 422.91 ms); w14-b2 PASS by
verdict but with a 6,825.68 ms host gap starting before the fault (the
island took the verdict 4.98 s late); w14-b3 clean, `VERDICT: PASS b: v at
the fault 3.93 m/s; TOR on True, mrm (3, 3) (3 = COMFORTABLE_STOP), v
0.000`, with W12's window rows:

    | window dwell, island clock (request on -> off) | [10000.00, 10110.00] | 10001.00 | PASS | at least the window; ends within the checker's `ends within` |
    | window dwell, host (request on -> off as received) | [10000.00, 10110.00] | 10002.27 | PASS | at least the window; ends within the checker's `ends within` |
    | windows (verdict -> deadline = request on + window) | 10110.00 | 10067.43 | PASS |  |
    | HPC alive: longest availability gap (host) | 500.00 | 154.46 | PASS | at 745 ms; over 500 ms the island raises hpc_loss |

The encore: last sample to braking command 606.95 ms against 643.33,
to standstill 3,519.15 ms (FTTI 10 s). W8a's runs had host gaps of at most
166 ms at load 16-27; these started at 20-31 with a nano-ros CI container
running on the same host, and w14-a's probe saw four availability gaps over
500 ms (570 to 1,600 ms).

**The plain-router drop** (W8a's open item) moved to phase8-W15 with W14's
measurements: /mnt/mx500/aeon/worktrees/w15-handoff.md (a TCP tap between
QEMU's guestfwd and a stock `rmw_zenohd`, the pin above). In short: with no
host peer at all the island closed its session with reason 5 (EXPIRED)
30.1 s after opening, twice; the stock router's `lease: 60000` /
`keep_alive: 2` sends one keepalive per 30 s, and the island tolerates 10 s
(`CONFIG_NROS_ZENOH_LEASE_MS` default). W15 owns the fix.

### phase8-W15: the plain-router drop is configuration, not version

**Mode.** The island is a zenoh CLIENT: nano-ros's only session mode on
Zephyr (no Kconfig selects peer; `SessionMode::Client` is the default), and
the router logs `New transport opened ... - whatami: client` and `InitSyn {
version: 9, whatami: Client ...}`. zenoh's own config says "instances in
client mode do not participate in gossip", and the tap saw no OAM message
toward the island in any run. Scouting and multicast are compiled out
(`Z_FEATURE_SCOUTING=0`, `Z_FEATURE_MULTICAST_TRANSPORT=0`); a client
opens one link, to the connect locator. The peer/gossip hypothesis is refuted.

**Versions.** Host router ros-humble-rmw-zenoh-cpp 0.1.9 (upgraded to 0.1.10
on 2026-09-29 18:36), container 0.1.10; both vendor zenoh-c 1.8.0 built from
zenoh commit 2687c51, and both ship `lease: 60000`, `keep_alive: 2`. The
island's zenoh-pico is jerry73204/zenoh-pico `nano-ros` 52f60b79 =
`1.8.0-74-g52f60b79` (same commit under nano-ros bec9aecb8 and da272e419):
the same release as the router, protocol version 9 on both sides. Key
expressions are rmw_zenoh humble's (`@ros2_lv/10/<zid>/<nid>/<eid>/NN|MP|MS|
SS|SC/...`, `.../TypeHashNotSupported`).

**Cause.** zenoh-pico (upstream 1.8.0, `transport.c` OpenAck handling)
measures router silence against min(router lease, own lease) = 10 s, and
closes after two silent periods; rmw_zenohd keepalives an idle link every
30 s. The CLOSE is decided at ~OPEN+20 s but reaches the wire only with the
next byte the router sends, 20-50 ms after it: the 30 s keepalive, or a host
peer's liveliness declarations forwarded to the island when graph discovery
is on -- which is why W8a saw it "0.15 s after `ros2 node list`". The same
thing is known upstream as ros2/rmw_zenoh#734 (closed: "Actually using any
`Z_TRANSPORT_LEASE` > `lease`/`keep_alive` works"), and nano-ros fixed it for
its cargo lane in issue 0906, but the Zephyr Kconfig default stayed 10000.

**One change at a time** (QEMU, `/mnt/mx500/aeon/worktrees/w15/tap/*`, the
tap is W14's zproxy on 7472 in front of a private rmw_zenohd on 7471):

| run | image | router | host peers at OPEN+ | result |
| --- | --- | --- | --- | --- |
| A | 10 s, discovery on | stock 0.1.9 | none | KEEPALIVE 49.652, CLOSE reason 5 49.676 (OPEN 19.463) |
| B | 10 s, discovery on | stock 0.1.9 | 24 s | peer's FRAMEs 28.401, CLOSE reason 5 28.451; list empty |
| E | 10 s, discovery on | keep_alive 6 only | 24, 40, 55 s | held 88 s, 3 of 3 lists name the 3 nodes |
| F | 10 s, discovery on | gossip `enabled: false` only | 24 s | KEEPALIVE 33.393, CLOSE reason 5 33.441 |
| H | 10 s, discovery on | 0.1.10 (container) | 24 s | FRAMEs 32.248, CLOSE reason 5 32.267 |
| I | 10 s, main f7c9369 | stock 0.1.10 | 24, 40 s | KEEPALIVE 34.409, CLOSE 34.410; +24 lists 3, +40 empty |
| D | 60 s, main + this change | stock 0.1.9 | 24, 40, 55, 70 s | held 77 s, 4 of 4 lists |
| J | 60 s, main + this change | stock 0.1.10 | 24, 40, 55, 70 s | held 97 s, keepalives +30/+60/+90, 4 of 4 lists |

Only the lease (or the router's keepalive cadence) moves the result; gossip
and router version do not. Fix: `CONFIG_NROS_ZENOH_LEASE_MS=60000` stated in
qemu-ethernet, island-ethernet and island-serial, and the Zephyr default
moved in nano-ros (issue 1574). On 0.1.10 the host `ros2 node list` did not
hang: 6 of 6 runs returned, each session open 0.8-2.9 s (run J).
