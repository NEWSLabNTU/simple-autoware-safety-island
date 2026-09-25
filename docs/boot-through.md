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
