# Emulation ladder: where the island runs before silicon

phase7-W2, 2026-09-25. This covers the four emulation rungs nano-ros offers,
whether each one runs the island, and what each one can and cannot tell us.
Recipes are in `just/emulation.just`. The QEMU entry is `src/qemu_entry/`.
Captures are under `build/emulation/`, which is not tracked. The verbatim
excerpts below come from those captures.

## The table

| rung | what it measures | what it cannot | cost to run | status 2026-09-25 |
| --- | --- | --- | --- | --- |
| native_sim (`just zephyr-build`, existing) | The island's logic and its ROS graph against real Autoware, over Cyclone DDS. | The zenoh image. The RTOS network stack (NSOS uses host sockets). 32-bit pointers. The board's pools. Any duration: they are host durations. | The demo's own build. No emulator. | Runs. The demo and phase7-W3 use it. |
| QEMU `mps2/an385`, Cortex-M3 (`just qemu-build`, `just qemu-run`) | The island's zenoh image on a 32-bit Cortex-M. Zephyr 4.4 in-kernel IP stack over the emulated LAN9118. Entity registration against the pools the contract derives, which are the same pools the board derives. The boot report read out of RAM, as a debugger reads it on the board. The graph as a host `ros2` sees it. | The M7: no FPU, caches or TCM, and a different ISA subset (ARMv7-M, not ARMv7E-M). The S32K344 memory limits: this part has 4 MiB, so the region report shows use, not fit. The S32K344 peripherals. The board's serial transport (blocked by a gap, finding F5). Time: icount is off, so the guest clock runs at host pace. With icount on, time would be instruction count, which is still not cycles. | Cold build about 11 min. Incremental build 7 min. A run takes the bound, 40 s by default. QEMU 11.0.0 comes from the nros store; nothing is downloaded. | Boots to its boot report. Stops at stage 4 (RegisteringEntities): `stop_mode_operator` create_publisher returns -100 (F1). phase7-W8: reaches stage 6 FirstSpin with four nodes in the host graph. That needs a heap and a main stack above the board's values (`docs/boot-through.md`). |
| Renode 1.16.0, `nxp-s32k388` plus an S32K344 delta (`just renode-run`) | The unmodified S32K344 board ELF, the one that would be flashed. That includes the DTCM `.bss` and the ITCM copy of the MRM node code, which no silicon has executed yet (docs/tcm-relocation.md). It also includes the island-serial zenoh link on LPUART2, over a host PTY to a real `rmw_zenohd`, and the boot report. | Cycle timing: Renode is instruction-level and its time is virtual. The FS26 PMIC and watchdog: LPSPI3 has no device ("No device is connected to LPSPI_PCS[0]"). The GMAC path, which was not tried. Anywhere the S32K388 model differs from the S32K344 beyond the TCM sizes and clock patched here. | 76 MB portable download, once (`just renode-setup`), into `build/emulation`. About 10 s to start, then the bound. | Runs the board image. It stops at the same stage 4 failure as QEMU (F1), with heap peak 57,024 B of 94,720. |
| Arm FVP (`just fvp-check`) | Nothing yet for this island. | nano-ros drives only `FVP_BaseR_AEMv8R` (phase-217). That model is an AArch64 Armv8-R envelope and cannot execute a Thumb Cortex-M7 image. FVPs are programmer's-view models, not cycle-accurate. | BaseR: 68 MB via `nros setup --tool arm-fvp`. An M-profile FVP is not provisioned by nano-ros. | Not run. The verdict and its reasons are below. |

The ordering is QEMU, then Renode, then silicon. QEMU is cheapest and shows
whether the island's own software registers against its derived pools. Renode
is the rung that runs the board's actual binary, with its TCM placement and
serial transport. Both reach the same failure (F1). The board would therefore
hit it too, since the board image derives the same pool size
(`build-board`: `MAX_TL_PUBLISHERS = 2`, `ZPICO_MAX_QUERYABLES=26`).

## Rung 1: QEMU mps2/an385

### Commands

    just qemu-build          # west build -b mps2/an385 -S nros-zenoh -S qemu-ethernet -d build-qemu src/qemu_entry
    just qemu-run            # 40 s bound; console, router log, graph and boot report to build/emulation/

`qemu-run` does the following:

1. Starts its own `rmw_zenohd` on port 7449. The image dials 10.0.2.100:7447,
   and a QEMU `guestfwd` rule maps that address to this router and nothing
   else.
2. Boots `qemu-system-arm -machine mps2-an385 -nic user,model=lan9118,...`.
3. Half-way through the bound, lists the domain-10 graph from the host.
4. Three seconds before the bound, dumps the boot report through the QEMU
   monitor (`pmemsave` at the address `read-boot-report.py --addr-only`
   names).
5. Decodes the report with nano-ros's `scripts/read-boot-report.py`.

### The entry

`src/qemu_entry/` is the third entry package. It has the same bringup,
contract and components as the other two. It is a separate package because
nano-ros resolves an image per entry package and checks the image's `rmw`
against Kconfig, which is the same reason `native_sim_entry` split from
`zephyr_entry`. Board-only policy stays out of it: an385 has no TCM, so there
is no `zephyr_code_relocate`, and it has no LPUARTs.

`boards/mps2_an385.conf` holds only two kinds of setting:

- **The guest clock.** `CONFIG_QEMU_ICOUNT=n`, as nano-ros's own an385 lane
  sets it.
- **The S32K344 board facts, value for value.** These are the heap (94,208),
  the main stack (16,384), task slots and stack (5 x 8,192), the pthread
  mutex pool (64), the graph cache (4,096), `HEAP_MEM_POOL_SIZE=0`,
  `COMMON_LIBC_MALLOC_ARENA_SIZE=0`, the boot report and `REQUIRES_FULL_LIBCPP`.
  A board-sized pool that is too small therefore fails here first.

Three settings deliberately differ from the board, and the conf explains each:

- **`CONFIG_HW_STACK_PROTECTION=y`.** nano-ros issue 0552 found that a main
  stack overflow on this board reads as an all-zero usage fault unless the
  guard is on.
- **No shell.**
- **`CONFIG_ASSERT=n`.** Finding F4.

The transport is a snippet, as it is on the board entry:

- `snippets/qemu-ethernet` is the default: the LAN9118 over SLIRP.
- `snippets/qemu-serial` is the board's island-serial transport on the CMSDK
  UART1. It builds, but it cannot open a session (F5).

Nothing the contract determines is stated in the conf. Every NROS count is
derived by the same resolver the board build runs. `check-knob-delivery`
names 23 resolver pairs over 21 facts, and one line is red:
`NROS_DERIVED_SUBSCRIBED_TYPE_BOUNDS`, the known upstream phase-412 W4 line.
The board image has the same red line. `qemu-build` tolerates that line by
name and refuses any other.

### Region report and derived knobs, against the board

| image | FLASH | RAM (region) | notes |
| --- | --- | --- | --- |
| QEMU, qemu-ethernet (`build-qemu`) | 603,096 B of 4 MB | 435,124 B of 4 MB | IP stack, LAN9118 driver and packet pools included |
| QEMU, qemu-serial (built, 2026-09-25) | 529,068 B of 4 MB | 381,308 B of 4 MB | no IP stack, as the board |
| Board, island-serial (`build-board`, pre-tracing, the image Renode ran) | 4 MB part | SRAM 302,608 B of 327,680, DTCM 84,528 B of 131,072, ITCM text 12,812 B | from its ELF program headers |

The QEMU RAM number is a single region: nothing is relocated to TCM. It should
not be compared with the board's SRAM line alone.

The Ethernet image carries the following RAM that the board does not:

| symbol | bytes |
| --- | --- |
| `tcp_conns_slab` | 21,760 |
| `net_buf` data, RX and TX | 2 x 4,096 |
| net `contexts` | 5,504 |
| `work_q_stack` | 4,160 |
| `fdtable` | 1,776 |

The board, in turn, carries its shell and FS26 driver state.

The derived knobs are identical on both images, because they come from the
same contract. From the boot report:

    NROS_EXECUTOR_ARENA_SIZE      50640
    NROS_EXECUTOR_MAX_CBS         19
    NROS_EXECUTOR_MAX_SC          5
    NROS_EXECUTOR_MAX_NODES       4
    NROS_SUBSCRIPTION_BUFFER_SIZE 1496

`SUBSCRIPTION_BUFFER_SIZE 1496` is the linked-closure bound. The board conf
records 880 as the correct subscribed-set value. 1496 is what compiles in when
`SUBSCRIBED_TYPE_BOUNDS` does not arrive, and it arrives on neither image.

The transport-sized pools differ between the images:

- The zenoh-pico queryable table and the transient-local pool are the same:
  26 and 2.
- The heap demand differs. Registration up to the failure peaked at 55,792 B
  on the Ethernet image. The same stage on the board image under Renode peaked
  at 57,024 B.
- With F1 worked around (below), the Ethernet image exhausted the board's
  94,720 B heap in `mrm_handler`: "nros: HEAP EXHAUSTED: request 194 bytes,
  arena 94720 bytes". The serial board image never got that far, so whether
  94,208 B holds on the board is still open.

### The gate run, verbatim

`just qemu-run`, 2026-09-25 17:23, `build/emulation/qemu-20260925T172310.*`. An identical earlier run is `qemu-20260925T171541`.
The console:

    *** Booting Zephyr OS build v4.4.0 ***
    [ERROR] .../nros-cpp/include/nros/node.hpp:324 node "stop_mode_operator": FAILED at create_publisher_in (code=-100)
    [nros] FATAL: node "stop_mode_operator" failed to construct at create_publisher_in (code=-100)
    [ERROR] .../nros-cpp/include/nros/node.hpp:324 node "stop_mode_operator": FAILED at create_publisher_in (code=-100)
    [nros] FATAL: node "stop_mode_operator" failed to construct at create_publisher_in (code=-100)
    qemu-system-arm: terminating on signal 2 from pid 3073043 (timeout)

The boot report, read from RAM at 0x2003c248 (92 B):

    stage      4  RegisteringEntities -- an entity claimed arena; registration in flight
    arena capacity                50640
    arena used                    9800   (19.4%)
    arena allocations             9
    platform heap PEAK            55792 bytes   (58.9% of the heap)
    platform heap capacity        94720 bytes   (NROS_ZEPHYR_HEAP_SIZE)
    HEAP HEADROOM: ok -- 38928 bytes spare (peak 55792 of 94720, floor 24576).
    Halted DURING REGISTRATION: 9 allocation(s) succeeded, ... the arena is not the cause

No node reached the host graph: `ros2 node list` on domain 10 was empty.
The two nodes constructed before the failure are never announced, because the
executor never reaches its first spin.

This run is the gate: the image boots, installs, reaches its boot report, and
says why it stops. It is not the demo's island half, and F1 decides whether it
can become that.

## Rung 2: Renode

### Verdict

The rung works. It runs the board's own ELF.

nano-ros does not use Renode. `git grep -i renode` in nano-ros finds two
files: a word list in `scripts/check-board-name-reach.py:99` and vendored
mermaid. There is no recipe, no `.resc` and no SDK index entry, and Renode
was not installed on this host (`command -v renode` exits 1).

Upstream Renode 1.16.0 does ship `platforms/cpus/nxp-s32k388.repl`. That is an
S32K3 with four Cortex-M7 cores, and its LPUART, STM, SIUL2, MC_ME and GMAC
sit at the S32K344's addresses (LPUART2 is 0x40330000, which is the island's
serial locator). Two things in that model differ from the S32K344 in ways that
matter to this image:

- **The TCM sizes.** The model has 32 KiB ITCM and 64 KiB DTCM per core. The
  S32K344 has 64 KiB and 128 KiB, and this image puts 84,528 B of `.bss` in
  DTCM.
- **The core clock.** The model runs at 320 MHz. The S32K344 runs at 160 MHz.

`renode-run` generates a four-entry delta (`build/emulation/s32k344.repl`):

    using "platforms/cpus/nxp-s32k388.repl"
    itcm0:
        size: 0x10000
    dtcm0:
        size: 0x20000
    nvic0:
        systickFrequency: 160000000
    dwt:
        frequency: 160000000

The first smoke test was the board's Zephyr `hello_world`
(`build-hello/zephyr/zephyr.elf`, built for `mr_canhubk3/s32k344`), with no
delta at all. It printed:

    *** Booting Zephyr OS build v4.4.0 ***
    Hello World! mr_canhubk3/s32k344

### Commands

    just renode-setup                                  # 76 MB, once
    just renode-run                                    # build-board/zephyr/zephyr.elf, 40 s
    just renode-run <elf> <secs>

`renode-run` does the following:

1. Snapshots the ELF.
2. Connects LPUART2 to a host PTY through
   `emulation CreateUartPtyTerminal` and `connector Connect`.
3. Starts `rmw_zenohd` listening on that PTY, with
   `experiments/serial-interop/router-serial.json5` and the same invocation
   the bench uses.
4. Starts the machine through the Renode monitor port.
5. After the bound, reads the boot report with `sysbus ReadBytes` and decodes
   it.

### The run, verbatim

This was the board image as of 04:08 (sha256 5e5c42196a13...). That image
predates phase7-W1's tracing and is the W8b-era image.
`build/emulation/renode-20260925T164802.*`. The console on LPUART0:

    uart:~$ [ERROR] .../nros-cpp/include/nros/node.hpp:324 node "stop_mode_operator": FAILED at create_publisher_in (code=-100)
    [nros] FATAL: node "stop_mode_operator" failed to construct at create_publisher_in (code=-100)

The boot report, read from RAM at 0x204258a4:

    stage      4  RegisteringEntities -- an entity claimed arena; registration in flight
    arena used                    9800   (19.4%)
    platform heap PEAK            57024 bytes   (60.2% of the heap)
    platform heap capacity        94720 bytes   (NROS_ZEPHYR_HEAP_SIZE)

This run shows several things about the board image:

- The boot-time ITCM copy works. `stop_mode_operator`'s constructor is in
  ITCM-relocated code, and it ran.
- The DTCM `.bss` works.
- The zenoh session opens over the serial link to a host router.
- Registration proceeds to the same entity as on QEMU.

Without a router on LPUART2, the image stops at stage 2 (BootConfigResolved).

## Rung 3: Arm FVP

### Verdict

Not run. The mismatch is the finding. The 20-minute limit was kept, and
nothing was installed.

- **nano-ros's FVP runtime cannot take the island's image.** nano-ros
  phase-217 and its `fvp-aemv8r-smp` board drive `FVP_BaseR_AEMv8R` with
  Zephyr `fvp_baser_aemv8r/fvp_aemv8r_aarch64/smp` (4 CPUs, Cyclone DDS, SMSC
  91C111 Ethernet). That model is the AArch64 Armv8-R architecture envelope,
  which is the L4 spec's FSI class. The island is a Thumb-2 Cortex-M7 image
  and cannot execute on it. Using this rung would need a new port of the
  island to an R-profile AArch64 board, not a new entry.
- **The M-profile FVPs do exist.** Zephyr's `boards/arm/mps2/board.cmake`
  names `FVP_MPS2_Cortex-M3` for `mps2/an385`, which is this QEMU entry's
  board, and `FVP_MPS2_Cortex-M7` for `mps2/an500`, a Cortex-M7 on the same
  MPS2 memory map. So an FVP rung for this island would be `mps2/an500` on
  `FVP_MPS2_Cortex-M7`. nano-ros does not provision it (its SDK index has only
  `[tool.arm-fvp]` = BaseR, 68 MB), and that was not downloaded here.
- **FVP durations are not silicon durations.** FVPs are programmer's-view
  models, not cycle-accurate. nano-ros itself runs BaseR with
  `cache_state_modelled=0` for speed, and its issue 0232 calls the resulting
  timestamps "fast-sim timestamp clustering". An FVP rung would give an
  instruction-accurate M7 (FPU, and the cache programming model), but not a
  WCET.

### Command

    just fvp-check
    fvp-check: no FVP model on PATH or in ~/.nros/sdk/arm-fvp

## Findings

**F1: the board image cannot register its entities; it will not boot on
silicon as built.**

The failure: stop_mode_operator's create_publisher returns -100 on QEMU (the
QEMU entry) and on Renode (the board ELF).

The cause, traced with gdb on QEMU: the island declares five TRANSIENT_LOCAL
publishers:

- `mrm_comfortable_stop_operator`: `max_velocity_candidates` and
  `clear_velocity_limit`
- `stop_mode_operator`: `gear`, `turn_indicators` and `hazard_lights`

nano-ros sizes the retention pool from the durability the contract states
(`nros-cli-core/src/sizing_descriptor.rs`, `transient_local_publishers*`).
`safety_island.contract.yaml` states no durability anywhere, so the pool falls
to `TL_PUBLISHERS_DEFAULT = 2` (`nros-rmw-zenoh/build.rs:776`). The queryable
table is sized without them as well (26 = 24 parameter services + 2 app
services).

The gdb trace, in order:

1. `transient_local::claim` #1, then its cache queryable.
2. Claim #2, then its queryable.
3. Claim #3 (the first `stop_mode` TL publisher) finds no slot, and
   `declare_retention` returns Backend(...), which reaches C++ as -100.

The log line nano-ros writes for this case ("TRANSIENT_LOCAL retention pool
exhausted ... raise ZPICO_MAX_TL_PUBLISHERS") never appeared on the console.

The fix belongs in the contract, which W2 does not own: state the five
publishers' durability, so that the pool and the queryable table derive 5 and
31. The diagnostic build `build-qemu-tl` (env `ZPICO_MAX_TL_PUBLISHERS=5`,
`ZPICO_MAX_QUERYABLES=31`) gets past `stop_mode_operator`. See F2 and F3 for
what comes next.

Resolution (phase7-W8, `docs/boot-through.md` iterations 1-2). There were two
gaps, and both are fixed.
- The contract now states `durability` on all fourteen publishers. nano-ros
  refuses to count while any publisher states none.
- The Zephyr road now delivers the count to the retention pool (nano-ros PR
  #1311, issue 1498), and the slot size derives from the latched types:
  105 B, not 1,024 B.

On QEMU the pool derives 5 and the queryable table 31, and all three of
`stop_mode_operator`'s latched publishers register.

**F2: after F1, mrm_handler's subscriptions fail in zenoh-pico.** The
diagnostic build is `build-qemu-tl`. It was built with
`ZPICO_MAX_TL_PUBLISHERS=5 ZPICO_MAX_QUERYABLES=31` and, for diagnosis only,
`CONFIG_NROS_ZEPHYR_HEAP_SIZE=196608` and `CONFIG_MAX_PTHREAD_MUTEX_COUNT=128`,
through `qemu-build`'s env lever. It was run against its own router on port
7449, in `build/emulation/qemu-20260925T172402.*`.

With those overrides, all three `stop_mode_operator` TL publishers register.
Then `mrm_handler` fails:

    zpico: z_declare_subscriber (ring) failed: -1 for '10/system/mrm/comfortable_stop/status/tier4_system_msgs::msg::dds_::MrmBehaviorStatus_/*'
    [nros] FATAL: node "mrm_handler" failed to construct at create_subscription_in (code=-100)

The boot report shows 13 arena allocations, heap peak 93,960 B, and
`LAST ERROR Transport ConnectionFailed`.

Neither the heap nor the mutex pool is the cause, since both were doubled.
Which zenoh-pico table refuses the declaration is not yet identified. Two
more observations:

- At the board's heap (94,720), an earlier run with only the TL override
  exhausted the heap at this same node ("nros: HEAP EXHAUSTED: request 194
  bytes, arena 94720 bytes", peak 88,408 B). On the Ethernet image,
  therefore, 94,208 B is not enough for four nodes. That run is
  `build/emulation/qemu-20260925T163203.*`.
- The serial board image never reached this node, so the heap question for
  the board is open.

Resolution (phase7-W8, iterations 3 and 5). The failing table was not
zenoh-pico's. It was Zephyr's static POSIX COND pool, at 16 of 16. Every
declared subscriber and queryable takes one cond and one mutex for its sync
group. The mutex pool, which W2 doubled, is the next to fill: with 31
queryables it needs 70.

nano-ros now floors both pools for a derived table and refuses the configure
below the floor (issue 1498). Both confs state 70/48. The heap question is
answered in `docs/boot-through.md`: a 190,216 B peak at FirstSpin, which the
board cannot hold while `param_services` is on.

**F3: mrm_handler subscribes TRANSIENT_LOCAL, which the zenoh backend refuses
for subscriptions.** The subscription is `/api/operation_mode/state`,
`mrm_handler_core.cpp:109`. The refusal is in `nros-rmw-zenoh/src/shim/qos.rs`,
`admit`: "the shim serves publisher-side retention only". The cyclone
native_sim image does not hit this. It is predicted by code reading, and was
not yet reached at runtime, because F2 stops registration first.

Resolution (phase7-W8). nano-ros's rule is deliberate (phase-455 W5, issue
1341). The island drops `.transient_local()` on that one subscription
(`mrm_handler_core.cpp:104-118`). The contract declares it at
`min_rate_hz: 10`, so latching buys nothing.

**F4: `zpico.c:894` calls `k_cycle_get_64()` unguarded.** On a SysTick at or
below 60 MHz (an385 runs at 25 MHz) with `CONFIG_ASSERT=y`, boot panics:

    ASSERTION FAIL [0] @ WEST_TOPDIR/zephyr/include/zephyr/kernel.h:2237
        64-bit cycle counter not enabled on this platform. See CONFIG_TIMER_HAS_64BIT_CYCLE_COUNTER
    >>> ZEPHYR FATAL ERROR 4: Kernel panic on CPU 0

nano-ros guards the same call in `nros-platform-zephyr/src/platform.c:52-58`
(issue #531) but not here. The board, at 160 MHz, is unaffected. The QEMU conf
turns asserts off until this is guarded upstream.

**F5: zenoh-pico's Zephyr serial link requires `uart_configure()`.** See
`zenoh-pico/src/system/zephyr/network.c:1055`. Zephyr's CMSDK APB UART driver,
which every MPS2 board uses, does not implement `configure`, so the call
returns an error and the session fails at stage 2 (ConnectionFailed). nano-ros
has no an385 serial runtime lane: `cmake/zephyr/mps2-an385-serial.conf` is a
size probe (phase-392 W4). So QEMU cannot exercise the board's serial
transport, and the QEMU rung runs Ethernet.

**F6: `system.toml`'s `domain_id = 10` does not reach the image.** The key
prefix comes from `CONFIG_NROS_DOMAIN_ID` (Kconfig default 0), and the first
QEMU boot declared `@ros2_lv/0/...`. The board gets 10 only because
`island-serial/serial.conf` states it. `island-ethernet/ethernet.conf` does
not, so the board's Ethernet image would join domain 0.

Resolution (phase7-W8): recorded, not changed. nano-ros's rule is
deliberate: Kconfig is what the image bakes (RFC-0049). The check that
refuses a disagreement with `system.toml` (phase-460 W4) runs only in
`nros_system_generate`, not on the `nano_ros_add_executable` road these
entries use. So the snippets state the domain and nothing checks them. See
`docs/boot-through.md`, F6.

**F7: the nano-ros log facade printed nothing on the Zephyr C++ entry.** Its
refusal lines (F1's pool message, qos refusals) never reached the console. The
zpico C `printk` lines did.

Status (phase7-W8): unchanged. Every refusal W8 met reached the console
through zpico's `printk`, and was read with gdb.

## What the phase doc got wrong

- **"No Ethernet" on `mps2/an385`.** It has one: the LAN9118 (`smsc,lan9220`
  in `mps2_base.dtsi`). nano-ros's own an385 witness runs zenoh over it and
  QEMU SLIRP (`cmake/zephyr/mps2-an385.conf`, phase-441 W1). The serial
  transport is the one that does not work there (F5).
- **"An emulation ladder in nano-ros, all rungs present ... Renode".** nano-ros
  has no Renode support; the "171 hits" are two files. The Renode rung here is
  upstream Renode's S32K388 model plus a four-line delta.
- **"only FVP or silicon durations go on a slide without a qualifier".** FVP
  durations need the same qualifier as QEMU's: the models are not
  cycle-accurate, and nano-ros runs them with cache state unmodelled. The
  nano-ros FVP is not even the island's ISA.
- **Section 1: "the board has never executed".** The board conf records
  silicon measurements. The pthread mutex pool note says "MEASURED on silicon:
  32 -> ExecutorReady ... 64 -> FirstSpin". That run predates the pin that
  sized the TL pool, and on this pin the image has not run on silicon.
