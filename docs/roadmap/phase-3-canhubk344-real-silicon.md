# Phase 3 — the island on real silicon: NXP MR-CANHUBK344 under Zephyr

**Goal:** the same four-node MRM chain that phases 1–2 ran on native and Zephyr
native_sim, running on an S32K344 on real hardware, joining Autoware's DDS
domain over 100BASE-T1 — and stopping the vehicle when the heartbeat dies.

**Status (2026-08-21): the image builds, links and fits. No hardware has run
it.** The 320 KiB question of section 4 is answered — measured, not estimated —
and section 4b records how. What remains is Z0: nothing here has executed a
single instruction on silicon, because the MCU-Link probe has not arrived. The
host RTOS decision was made twice and the second answer overturned the first —
see [Appendix A](#appendix-a--why-not-freertos--s32ds).

**Platform:** Zephyr **v4.4.0**, the rolling line (`NROS_ZEPHYR_VERSION=4.4`,
`west-4.4.yml`), board `mr_canhubk3/s32k344`. Not the 3.7 LTS: 4.5 is expected
to become the next LTS, so 4.4 carries us into it.

---

## 1. The shape of it

nano-ros is a library, not a board (nano-ros RFC-0064) — and Zephyr is the
`rtos-owned` case that model exists for.

```
Zephyr (mr_canhubk3/s32k344)  ── boot, IVT header, FS26 watchdog,
                                  GMAC + MDIO + TJA1103, IP stack, west flash
        +
nano-ros (a west module)      ── RMW, executor, the 4 ported nodes, entry
        =
  west build -b mr_canhubk3/s32k344 -S nros-<rmw> src/zephyr_entry
  west flash            (pyocd --target=s32k344, via MCU-Link)
```

We contribute **no board port and no new package**. The hardware delta is one
Kconfig fragment.

## 2. Upstream already solves the hard parts

Verified against Zephyr v4.4.0 (and cross-checked on v3.7.0).

| Problem | Where Zephyr solves it |
| --- | --- |
| S32K3 IVT boot header — without it an image flashes and never runs | `soc/nxp/s32/s32k3/sections.ld` emits `.ivt_header` into an `IVT_HEADER` region at `CONFIG_FLASH_BASE_ADDRESS + CONFIG_IVT_HEADER_OFFSET` |
| FS26 PMIC challenger watchdog resets the MCU every 256 ms unless serviced | An **FS26 SBC watchdog driver**, enabled by the board config. Board doc: *"This board configuration enables the FS26 watchdog driver that handles this initialization."* |
| Ethernet MAC | `drivers/ethernet/eth_nxp_s32_gmac.c` |
| MDIO | `drivers/ethernet/mdio/mdio_nxp_s32_gmac.c` (on 3.7 it was `drivers/mdio/` — **path moved, symbol did not**) |
| TJA1103 100BASE-T1 PHY | `drivers/ethernet/phy/phy_tja1103.c`; board DTS wires `ethernet-phy@12`, `master-slave = "auto"` on 4.4 |
| Flashing | `board.cmake`: `board_runner_args(pyocd "--target=s32k344")`, plus jlink and trace32 |
| TCP/IP stack | Zephyr's own. No lwIP, no vendor RTD, no entitlement |

Memory map matches what we measured independently from the vendor project and
from pyocd: `flash@400000`, `sram0_1@20400000` **320K**, ITCM 64K, DTCM 128K.

Board `supported:` on 4.4 — `adc can counter display dma flash gpio i2c`
**`netif:eth`** `pwm spi uart watchdog`.

> `netif:eth` is a *declared* twister capability. It means the board builds
> networking, not that anyone has run DDS over it. Treat Z1 as the proof.

## 3. Project organisation

Both conventions were consulted, and they agree.

**Zephyr:** an application keeps per-board configuration in
`<app>/boards/<board>.conf` (and `.overlay`), auto-selected from the board
target with `/` normalised to `_`. Proof already in nano-ros:
`examples/zephyr/cpp/talker/boards/native_sim_native_64.conf` beside
`talker-aemv8r/boards/fvp_baser_aemv8r_fvp_aemv8r_aarch64_smp.conf` — one
application, two unrelated boards, differing by one file.

**nano-ros:** RFC-0066, quoted in its CLAUDE.md — *"a FEATURE is a node package,
a CONFIGURATION is a fixture axis — **never a new directory**."* A board is a
configuration. Entries name their INPUT (`BRINGUP`); SystemModels are build
artifacts and are gated against being committed.

### Consequence: no new entry package

An earlier revision of this doc planned `src/canhubk344_entry`. That was the
FreeRTOS-shaped answer, where the entry had to carry a `main()` handoff and a
board-specific link. On Zephyr both conventions independently reject it.

```
src/
  <vendored msg pkgs>/            unchanged
  island_interfaces/              unchanged
  autoware_mrm_*/ …               unchanged — the four ported node pkgs
  safety_island_bringup/          system.toml + launch — the entry's INPUT
  zephyr_entry/
    CMakeLists.txt                unchanged except MODEL -> BRINGUP
    package.xml
    prj.conf                      board-agnostic base
    prj-cyclonedds.conf           LTS/CONF_FILE path — native_sim scale, KEPT AS IS
    boards/
      mr_canhubk3_s32k344.conf    ← the entire hardware delta
      mr_canhubk3_s32k344.overlay ← only if the stock DTS needs changing
```

Board target `mr_canhubk3/s32k344` → `boards/mr_canhubk3_s32k344.conf`. The
`/mcuboot` variant would be `boards/mr_canhubk3_s32k344_mcuboot.conf`; not used.

### Kconfig fragment order — the thing to get right

Zephyr applies `CONF_FILE` (default `prj.conf`), then `boards/<board>.conf`,
then `EXTRA_CONF_FILE`. **Snippets append to `EXTRA_CONF_FILE`**, so
`-S nros-cyclonedds` lands *after* our board file and wins any conflict.

That matters because the snippet carries host-scale sizing (see §4). Two
consequences:

* Never rely on `boards/*.conf` to shrink a value the snippet sets. Verify with
  `west build -t menuconfig` or the generated `.config`, not by reading files.
* The legacy `-DCONF_FILE="prj.conf;prj-<rmw>.conf"` form **suppresses the
  automatic board file entirely** — `prj-cyclonedds.conf` says so in its own
  comment ("board overlay not auto-applied under explicit CONF_FILE"). Hardware
  builds must therefore use the snippet form, not CONF_FILE.

### Reference symbols, never driver paths

`drivers/mdio/` exists on 3.7 and not on 4.4. Kconfig symbol names are the
stable surface; paths are not. This applies to docs, Kconfig fragments and any
CI grep.

## 4. The real risk: 320 KB

This is now the hard part of the phase, and it replaces "write a MAC driver".

`zephyr/snippets/nros-cyclonedds/cyclonedds.conf` asks for, on any board:

| Symbol | Snippet value | S32K344 has |
| --- | --- | --- |
| `CONFIG_MAIN_STACK_SIZE` | 524288 (512 KiB) | |
| `CONFIG_HEAP_MEM_POOL_SIZE` | 4194304 (4 MiB) | **320 KiB SRAM, total** |
| `CONFIG_COMMON_LIBC_MALLOC_ARENA_SIZE` | 16777216 (16 MiB) | |
| `CONFIG_NET_PKT_{RX,TX}_COUNT` | 64 / 64 | |
| `CONFIG_NET_BUF_{RX,TX}_COUNT` | 128 / 128 | |

Our own `prj-cyclonedds.conf` goes further still — a 256 MiB malloc arena —
with the comment *"native_sim can afford RAM."* The board cannot.

Cyclone DDS on 320 KB is unproven and may simply not fit. **zenoh-pico is the
realistic first target**, and it is what every FreeRTOS fixture upstream uses.
Against that, our host side is Cyclone, which is why this is a decision (Z4) and
not an assumption. Bring up on zenoh; revisit Cyclone with measurements.

Also unchanged from the earlier plan: 100BASE-T1 needs a media converter
(RDDRONE-T1ADAPT or similar) for host interop. Not in the kit.

## 4b. It fits (2026-08-21)

zenoh was the right call. The first link attempt overflowed RAM by **651,448
bytes**; the image now sits inside the part with room to spare:

```
FLASH:  600,036 / 4,144,896   14.48%
RAM:    268,336 /   320 KB    81.89%
DTCM:    98,264 /   128 KB    74.97%
ITCM:         0 /    64 KB     0.00%
```

Every figure below came from `zephyr_pre0.map` and `nm` against built objects.
The dominant cost was not what this section predicted:

| | reclaimed | what it was |
| --- | ---: | --- |
| `NROS_COMPONENT_MAX_PARAMS` 256 → 16 | 206 KiB | `ComponentNode` embeds `ParameterServer<256,…>` BY VALUE — 55,328 B of `.bss` per node, against 11 declared parameters on the busiest one |
| DTCM relocation | 98 KiB | executor storage + the four component buffers moved off SRAM |
| `MAIN_STACK_SIZE` / `HEAP_MEM_POOL` | 123 KiB | `MAIN_STACK_SIZE` is charged twice — main thread, and again as the 8-slot pthread pool |
| zenoh payload classes | 105 KiB | `LARGE_PAYLOADS` defaulted to 2 × 4 × 16 KiB for image-scale messages; the largest subscribed type is `nav_msgs/Odometry` at ~800 B |
| net stack right-sizing | 34 KiB | host-scale defaults: 8 TCP connections, 32 socket contexts, for the one link zenoh opens |

Three findings worth carrying forward:

1. **A snippet beats the board file.** `CONFIG_MAIN_STACK_SIZE`,
   `CONFIG_HEAP_MEM_POOL_SIZE` and the four `NET_PKT`/`NET_BUF` counts are set by
   `snippets/nros-zenoh/zenoh.conf`, which rides in `EXTRA_CONF_FILE` and merges
   *after* `CONF_FILE`. Values written into `boards/mr_canhubk3_s32k344.conf`
   were silently ignored. They are passed as `-DCONFIG_*` from `board-build`
   now, which is the one hook that merges later.
2. **The entity limits were wrong, not just large.** `CONFIG_NROS_MAX_SUBSCRIBERS`
   and `_MAX_PUBLISHERS` were both 8 against a measured 11 and 14. That would
   have failed at runtime past the eighth publisher, independent of memory.
3. **DTCM needed a Zephyr fix.** `zephyr_code_relocate()` could not resolve the
   generated entry TU to its object, and on no match it writes an empty fragment
   and exits 0 — relocating nothing, silently. See `patches/zephyr/0001`.

Cyclone DDS on this part remains unproven and untried; zenoh fits, so the
question is deferred rather than answered.

## 4c. The link is serial, not Ethernet (2026-08-31)

T1 was the plan and it is not available: 100BASE-T1 needs a media converter to
reach anything with an RJ45, and we have none. Rather than block, the island
runs zenoh-pico over the DCD-LZ serial adapter on `lpuart2` at 115200, framed
by z-serial (COBS + crc32). That is the same console UART the board already
exposes, so it costs no extra hardware.

What this bought, beyond unblocking:

* **The IP stack comes out entirely.** `CONFIG_NETWORKING` is off, and with it
  the GMAC driver, TCP, and the socket layer. Measured against the Ethernet
  build: **49 KB of RAM and 136 KB of flash** reclaimed. On a part where the
  first link attempt overflowed by 651 KB, that is not a rounding error.
* **A zenoh-pico bug, found and fixed.** `_z_serial_rx_bind` returned early for
  an already-bound device and so skipped `uart_irq_rx_enable`, while
  `_z_open_serial_from_dev` calls `uart_configure()` before it on every open --
  which clears exactly that enable. Second and later opens came up deaf. The fix
  re-arms on every open and resets the ring buffer and semaphore. Upstream as
  zenoh-pico PR #1301; carried in our pin meanwhile.
* **Polled RX beats interrupt RX here.** Measured on the same harness, ten goal
  attempts per row:

  | pin | RX | goals | router errors |
  | --- | --- | ---: | ---: |
  | 1.7.2 (ships) | polled | 8/10 | 0 |
  | 1.7.2 | ISR + rebind fix | 6/10 | 0 |
  | 1.10 | polled | 8/10 | 0 |
  | 1.10 | ISR + rebind fix | 0/7 | 3 |
  | 1.10 | ISR, no fix | 0/10 | 80 |

  The ISR does not earn its place, so it stays off. The 0/x rows appear only on
  1.10, which isolates a second defect to that branch rather than to the ISR
  itself -- recorded, not chased, since the pin stays at 1.7.2.

Ethernet is not abandoned. The static IPv4 and GMAC/TJA1103 configuration stays
in the tree, and `snippets/island-ethernet` selects it, so a converter arriving
is a rebuild rather than a port.

### The heap gate earns its keep (2026-08-31)

Rebuilding the entry against a newer nano-ros failed to configure, and the
failure was worth more than the build:

```
nros: the executor arena cannot fit in the platform heap.
  NROS_EXECUTOR_ARENA_SIZE = 52224
  NROS_ZEPHYR_HEAP_SIZE    = 65536
  needed (arena + ~24576 overhead) = 76800
```

The board file set the arena and never the heap, so the heap sat at its 65536
default, 11264 B short. The arena is one allocation out of that heap, so the
image would have linked clean, flashed clean, and then stopped mid-boot on a
NULL with no fault and no log. The board file now sets
`CONFIG_NROS_ZEPHYR_HEAP_SIZE=81920`.

Worth stating plainly: **this was latent in the image before the check existed.**
Every earlier sizing pass in this document measured what the image consumed, and
none of them would have caught a heap too small for a single allocation out of
it. The check is upstream's, and it found our bug.

## 4d. Z4 on silicon: what it took (2026-08-31)

**Z4 is MET.** The four MRM components run on the board:

```
/mrm_comfortable_stop_operator   /mrm_handler
/mrm_emergency_stop_operator     /stop_mode_operator
```

with all 22 island topics visible from a stock Humble graph over zenoh-pico on
serial. Final image: RAM 99.16%, DTCM 71.52%, FLASH 9.82%.

Every failure between the first flash and that verdict was a sizing defect, and
each one hid the next -- which is why the section below reads as a sequence
rather than a list. Two were nano-ros defects rather than configuration, and
both are fixed upstream (NEWSLabNTU/nano-ros#139).

| | defect | fix |
| --- | --- | --- |
| 1 | `board-build` selected no link, so Ethernet silently returned -- 44968 B over | `BOARD_LINK` |
| 2 | `MAIN_STACK_SIZE` multiplied into four zenoh task stacks | `NROS_ZEPHYR_TASK_STACK_SIZE` |
| 3 | `MAX_CBS` caps CALLBACK SLOTS: the image demands 19, and 14 was set | 36 |
| 4 | the arena budgeted every slot at ActionClient size | `ACTION_CLIENTS=0` |
| 5 | every slot charged the largest type's receive buffer | phase-403 W3/W5 |
| 6 | QoS depth 10 multiplies the type's bound | depth 1 |
| 7 | `Executor` was a 16 KiB value moved twice on the stack | phase-409 |
| 8 | zenoh needs a fifth task slot | `TASK_SLOTS=5` |

Number 8 was invisible until 7 stopped crashing the boot, and 5 was invisible
until 3 and 4 let the image get far enough to allocate.

### The original 4d analysis, and where it was wrong

What follows was written when Z4 looked structurally blocked. The diagnosis of
the MECHANISM was right and the NUMBERS were wrong, because they came from the
C++ pack's estimated sizes rather than derived bounds -- `Control` was read as
2052 and serializes to 114. Kept because the mechanism is the reusable part, and
because the way the numbers misled is itself the finding (nano-ros #0964).


The island was flashed and run. Boot gets through all four nodes' entity
creation and then the image is out of memory in both regions at once: SRAM
98.58%, DTCM 98.33%. That is not a tuning gap, so the number that matters is
not "how much over" but "why".

**The executor arena charges every handle a receive buffer.** It is derived as
`max_cbs * (3 * NROS_SUBSCRIPTION_BUFFER_SIZE + 512) + 2048`. The island has 33
handles, of which only 13 ever receive anything:

| node | pub | sub | svc | tmr |
| --- | ---: | ---: | ---: | ---: |
| mrm_handler | 5 | 7 | 2 | 1 |
| stop_mode_operator | 4 | 3 | 0 | 1 |
| mrm_comfortable_stop_operator | 3 | 0 | 0 | 2 |
| mrm_emergency_stop_operator | 2 | 1 | 0 | 2 |
| **total** | **14** | **11** | **2** | **6** |

14 publishers and 6 timers are each charged 3 KiB of receive buffer they can
never use. That is ~61 KiB of DTCM spent on entities that do not receive.

**Which makes the configuration unsatisfiable.** DTCM leaves 77968 B for the
arena. The largest subscribed type is `nav_msgs/Odometry` at ~718 B, so the
buffer must be at least 768:

| buffer | 33 slots | 36 slots |
| ---: | ---: | ---: |
| 512 | 69632 (fits, but drops Odometry) | 75776 (same) |
| 768 | 94976 (over by 17008) | 103424 (over by 25456) |
| 1024 | 120320 (over by 42352) | 131072 (over by 53104) |

The largest buffer that fits at 36 slots is 532 B, below the 718 B Odometry
needs. There is no valid setting. A booting image is reachable only by
undersizing the buffer, and the upstream help is explicit that an oversized
sample is then dropped SILENTLY on the C++ arena dispatch path -- a subscription
that never fires rather than an error. That is a worse outcome than not booting,
so the board file keeps 1024 and does not link.

**The fix is upstream, and it is already open.** This island is a data point for
work that exists rather than a new finding:

* **nano-ros phase-403, "the type's bound sizes every receive buffer"** (design,
  nothing landed as of 2026-08-30). It states this exact problem: buffer 1 is one
  global size for every subscription in the image, so "a 68-byte type and a
  1000-byte type get the same small block". Our 14 publishers and 6 timers paying
  Odometry's price is the same defect seen from the arena side. It is not a
  parameter change because `RX_BUF` is a const generic and the C path is
  type-erased by design (RFC-0043 components subscribe raw with the type name as
  a string), so there is no `M` to monomorphise on.
* **nano-ros issue 0900**, "every executor arena slot is budgeted at the
  ActionClient worst case". `NROS_EXECUTOR_ACTION_CLIENTS=0` is its mitigation and
  is set above; it is what took the arena from the ActionClient figure down to
  `3 * rx_buf + 512` per slot.
* **phase-402** landed the plumbing for a per-type receive hint. phase-403 exists
  because that hint reaches the backend and sizes nothing yet.

With per-type sizing only the 11 subscriptions carry a buffer, and only
Odometry's needs to be large. The 14 publishers and 6 timers stop paying for
receive buffers they cannot use.

**Correction on the strength of the claim.** "No valid setting exists" holds only
with every other pool fixed. At the minimum viable 33 slots x 768 B the arena
wants 94976 B against 77968 free, so DTCM is short about 17008 B; trimming the
heap, main's stack and the RTT buffer could recover on the order of 12 KiB of
that. So this is a shortfall of roughly 5-17 KiB, not an impossibility by
construction -- close enough that a landed phase-403 clears it outright, and
close enough that nobody should try to close it by undersizing the buffer.

### What the bring-up did establish

Everything up to the arena is proven on hardware:

* The flash chain, boot, and all four MRM component factories linked.
* zenoh-pico opening the serial link and framing COBS on `lpuart2`.
* RTT over SWD as a console while zenoh owns the only wired UART. Without it
  none of the failures below were visible: the shipping image has no console at
  all, and a boot halt is indistinguishable from a healthy idle over SWD (both
  sit in `arch_cpu_idle` once halted).
* Every entity creating successfully once `MAX_CBS` was right.

### Sizing values this corrected, all of which were wrong on silicon

| knob | was | is | why the old value was wrong |
| --- | ---: | ---: | --- |
| `NROS_EXECUTOR_MAX_CBS` | 14 | 36 | caps CALLBACK SLOTS; the demand is 19, not the 33 entity count (see below) |
| `NROS_EXECUTOR_ACTION_CLIENTS` | 4 | 0 | island instantiates no action entity |
| `NROS_ZEPHYR_TASK_STACK_SIZE` | inherit | 8192 | inherits MAIN_STACK_SIZE, multiplying it into 4 zenoh task stacks |
| `MAIN_STACK_SIZE` | 8192 | 32768 | overflowed in `Executor::open_in`; 16384 also overflowed |
| `NROS_ZEPHYR_HEAP_SIZE` | 65536 | 98304 | build gate caught the arena not fitting; runtime then reported HEAP EXHAUSTED at 82432 |
| `EXECUTOR_ARENA_SIZE` | 52224 hardcoded | derived | hand-derived from the wrong handle count |

**Count entities with both spellings.** Most subscriptions are the
`NROS_SUBSCRIBE` macro and timers are `NROS_CREATE_TIMER`; grepping for
`create_subscription` finds 1 of 11 and none of the 6 timers. That mistake put
the handle count at 17 instead of 33 and cost two silicon round-trips. The
original board file's "11 subs + 2 service servers" was arithmetically CORRECT
-- it was counting callbacks for a knob that caps handles.

### Correction: MAX_CBS counts callback slots, not entities (2026-08-31)

This document said `MAX_CBS` "caps total HANDLES, not callbacks; publishers and
timers count". **Publishers do not count.** Verified against nano-ros: every
registration that claims a slot calls `Executor::next_entry_slot()`, and
`create_publisher` is not among them -- the C++ path writes an `RmwPublisher`
into caller-owned storage and the C API has no `add_publisher` to increment
`handle_count`.

So for this island:

| | count |
| --- | ---: |
| entities created | 33 |
| **callback slots demanded** | **19** |
| hand-set `MAX_CBS` | 36 |

Subscriptions, timers, services, service clients, action entities and guard
conditions claim a slot; publishers do not. `ParamState` lives outside the arena
by design, and the lifecycle servers go through `create_lc_srv` directly, so
neither is a hidden term.

What the original diagnosis got RIGHT: 14 was too small and raising it fixed the
boot halt. What it got WRONG was the reason -- the shortfall was 19 against 14,
not 33 against 14, and the fix was over-provisioned by 17 slots as a result.

The per-node table in 4d is also mis-attributed: it reads 6 timers and 2
services where the source has 4 timers, 2 service servers and 2 service clients.
The TOTAL came out right by coincidence, which is why nothing caught it.

Tracked upstream as nano-ros #0965's first consumer, which derives 19 from a
declared entity inventory rather than from anyone's count.

## 5. Waves

| | What | State |
| --- | --- | --- |
| **Z0** | Stock Zephyr `hello_world` on the board: `west build -b mr_canhubk3/s32k344`, flash with MCU-Link + pyocd, see console. **Zero nano-ros.** Exercises IVT, FS26 and the flash chain so a failure is unambiguously board-or-probe | done (2026-08-27), by a stronger test than the one planned: the nano-ros talker itself runs on the board, over the same IVT / FS26 / pyocd path. `hello_world` was never needed |
| **Z1** | Board conf + networking. Get an IP up and ping across the T1 link | superseded, not done. T1 needs a 100BASE-T1 to 100BASE-TX media converter we do not have, so nothing can sit at the other end of the link. The transport is serial instead (4c); `CONFIG_NETWORKING` is off in the board conf. The static IPv4 + GMAC/TJA1103 config stays in tree, unexercised, against a converter arriving |
| **Z2** | Entry: point `src/zephyr_entry` at the board. **No CMakeLists change needed to build** — checked 2026-08-16: `nano_ros_entry` accepts both `MODEL` and `BRINGUP` and emits no deprecation, so the board build works with the entry as-is. The `MODEL` → `BRINGUP` migration is hygiene (models are build artifacts upstream; `check-no-tracked-models` gates nano-ros's own tree, not a consumer's) and is separable from the bring-up | done — the entry builds for the board |
| **Z3** | RMW + sizing. zenoh first; measure; decide about Cyclone | done for zenoh — see 4b. Cyclone deferred, not evaluated |
| **Z4** | The demo on hardware — phase-2's verdict reproduced with the island on real silicon | **MET (2026-08-31).** All four MRM components run on the board and appear in a stock ROS 2 Humble graph with 22 island topics, over zenoh-pico on serial. Final image RAM 99.16%, DTCM 71.52%, FLASH 9.82%. It took two upstream fixes and six configuration corrections; see 4d |

Z0 needed no decisions and no nano-ros, but it was overtaken: bringing the
talker up on the board proved the same chain and more, so Z0 is closed by
evidence rather than by running the sample.

## 6. Hardware notes that are easy to get wrong

* **FS26 watchdog.** Zephyr's driver services it, so the JP1 jumper should not
  be needed. If the board resets in a loop anyway, the bench workaround is
  UG10154 §2.3: JP1 off → **exactly 12.0 V** on P27/P28 → JP1 on → LED **D24
  dark**.
* **The 10-pin ARM SWD header is the 2×5 immediately right of P6.** UG10154
  §3.9.2 calls it "P26"; P26 is the 2×17 Pixhawk IMU connector. Go by Figure 13.
* **Never mass-erase.** pyocd's `pflash` region spans `0x00400000`–`0x007FFFFF`,
  which includes the 176 KB reserved for sBAF and HSE firmware. `pyocd flash`
  sector-erases only what it writes; `pyocd erase --chip` can brick the part.
* **Power MCU-Link first, then the board** — it can be back-powered otherwise.
* Console is the DCD-LZ adapter's 6-pin FTDI header. The board DTS puts
  `zephyr,console` on `lpuart2`.
* 100BASE-T1 is master/slave and the ends must disagree. 4.4's DTS uses
  `master-slave = "auto"`; 3.7 hard-pinned `"slave"`. First thing to check if
  the link will not come up.

## 7. Toolchain facts

* **Workspace:** 4.4 uses a sibling `../nano-ros-workspace-4.4`; the 3.7 LTS
  keeps nano-ros's in-tree `zephyr-workspace/`. They coexist, so native_sim on
  3.7 keeps working while the board runs 4.4.
* **Python 3.12 required.** 4.4's `find_package(Python3)` demands ≥ 3.12; this
  host is Ubuntu 22.04 (3.10). nano-ros provisions a venv at
  `<workspace>/.venv312/bin` and prepends it, so `west` must be invoked through
  that PATH. No sudo.
* **The support window is "current LTS + at most one rolling."** When the next
  LTS is declared, nano-ros drops 4.4 and we move with it. That is the point of
  choosing it.
* nano-ros's `docs/development/zephyr-version-support.md` names this repo:
  *"Downstream integrators (e.g. autoware-safety-island) must be on ≥ 3.7."*
  It also notes the per-version churn is isolated to the native_sim/NSOS shims —
  which is why the rolling line is cheap on hardware and expensive on
  native_sim.


## 7b. Setup preconditions found the hard way (2026-08-16)

Running `just board-setup` for the first time surfaced three things the recipe
now handles, recorded because none is obvious from the Zephyr side:

* **`nros setup --source` runs INSIDE `just zephyr setup`.** It resolves the CLI
  from `$NROS_CLI` / `PATH` / `~/.nros`, so a checkout whose CLI has never been
  built cannot run the Zephyr setup at all. `board-setup` builds it first and
  exports `NROS_CLI`.
* **The stale `~/.nros/bin/nros` is gone** (deleted 2026-08-16; it was from May
  and shadowed the in-tree CLI, which `packages/cli/CLAUDE.md` explicitly
  forbids). Nothing should reintroduce it — but note the fallback chain above
  means an absent CLI is now a hard failure rather than a silent stale one.
* **The XRCE agent is skipped** (`NROS_ZEPHYR_SKIP_XRCE_AGENT=1`). `just zephyr
  setup` otherwise builds the Micro XRCE-DDS Agent, a Fast-DDS superbuild
  needed only for XRCE *runtime* tests. The island uses zenoh or Cyclone.

**`NANO_ROS_ROOT` points at the sibling `~/repos/nano-ros`, not the submodule.**
`.envrc` resolves env → sibling → submodule, and the env var is set. The two
have diverged: the sibling is at `234eb9ad1` and does NOT carry the phase-351
work, which lives uncommitted in `third-party/nano-ros` at `205a834`. For phase
3 that is harmless — the Zephyr path does not touch the FreeRTOS shell — but
anything that needs phase-351 must use the submodule or land it on the sibling.


## 7c. Z0 attempt 1 — an upstream SDK bug, found and fixed (2026-08-16)

`just board-hello` failed. Not on the probe, and not on anything in this repo.
Everything up to the toolchain worked:

```
Found Python3: .../.venv312/bin/python (3.12.11, minimum required is "3.12")
Zephyr version: 4.4.0
Found west (1.5.0)
Board: mr_canhubk3, qualifiers: s32k344      <- the board target resolves
ZEPHYR_TOOLCHAIN_VARIANT not set, trying to locate Zephyr SDK
CMake Error ... FindZephyr-sdk.cmake:160 (find_package)
```

**The bug.** `scripts/zephyr/setup.sh` hardcoded `ZEPHYR_SDK_VERSION="0.16.8"`
with no env override and no per-line dispatch, while Zephyr 4.4's own
`zephyr/SDK_VERSION` demands **1.0.1**. The manifest (`west-4.4.yml`) and the
patch set (`scripts/zephyr/patches/4.4.sh`) were both line-dispatched; the SDK
was the one axis that was not. So `NROS_ZEPHYR_VERSION=4.4 just zephyr setup`
exited **0** and produced a workspace that could not build anything.

Same class as the phase-351 defects: the step succeeds, prints nothing wrong,
and the failure lands somewhere that names neither the cause nor the step that
chose it.

**Why Z0 being `hello_world` paid for itself immediately.** A stock upstream
sample with zero nano-ros failed, so the fault was unambiguously toolchain
provisioning. Had this started with `board-build`, the identical error would
have arrived inside our own build and read as our problem.

**Fixed upstream** (in `~/repos/nano-ros`, uncommitted):

* `scripts/zephyr/setup.sh` — SDK version/tarball/sha256 dispatched on
  `$MANIFEST`. Note the tarball NAME is not a pure function of the version:
  0.16.x is one fat tarball, 1.0.x is `_minimal` plus per-toolchain fetches.
* `just/zephyr-setup.just` — `just zephyr doctor` now compares the registered
  SDKs against the line's `zephyr/SDK_VERSION` and fails loudly, printing what
  is registered instead. Verified: it reproduces this exact failure at
  diagnosis time.
* `docs/development/zephyr-version-support.md` — "pin the SDK for the line" is
  now step 5 of the add-a-line checklist, with the reason it exists.

**Installed locally:** SDK 1.0.1 (minimal + `arm-zephyr-eabi` +
`x86_64-zephyr-elf`, ~0.3 GB rather than the 2.13 GB full GNU bundle) beside
the existing 0.16.8, at nano-ros's own `scripts/zephyr/sdk/`. Both stay
registered in `~/.cmake/packages/Zephyr-sdk`; Zephyr picks by the version its
tree demands, so the 3.7 line is undisturbed.
sha256 `ca9bc0ff66fafca1dac9d592a36d953cf16d096a9d09b1c0357f021cf9f6a7eb`.


### Z0 attempt 2 — it builds (2026-08-16)

Second upstream bug, same class as the SDK one: `west-4.4.yml`'s
`name-allowlist` named only `cmsis`, but **Zephyr 4.x moved the Cortex-M core
headers to a separate `cmsis_6` module** (`CMSIS_6` upstream,
`modules/hal/cmsis_6`; both appear in Zephyr 4.4's own west.yml). Symptom:
`fatal error: cmsis_core.h: No such file or directory` at
`arch/arm/core/offsets/offsets.c` — i.e. **every Cortex-M board on the 4.4 line
was unbuildable**, not just this one. Invisible because 4.4 had only ever been
built for native_sim, which is x86 and needs no CMSIS. Fixed by allowlisting
`cmsis_6`; `west update` pulls it.

With that, stock `hello_world` links for `mr_canhubk3/s32k344`:

```
Memory region     Used Size   Region Size   %age Used
   IVT_HEADER:       256 B         256 B     100.00%
        FLASH:     50584 B     4144896 B       1.22%
          RAM:      6624 B       320 KB        2.02%
         ITCM:         0 B        64 KB        0.00%
         DTCM:         0 B       128 KB        0.00%
```

`IVT_HEADER 256 B / 100 %` is the S32K3 boot header, emitted automatically —
the artefact that would have been hand-written assembly on the FreeRTOS path.

**RAM baseline: 6.6 KiB of 320 KiB for a minimal image.** That is the number
every later sizing decision is measured against; the island's budget is what is
left of the remaining ~313 KiB after the RMW, the executor and the net buffers.

Flash then failed on `JLinkExe not found`: the board's `board.cmake` lists the
jlink runner first, so `west flash` defaults to it. We use an MCU-Link
(CMSIS-DAP), so both flash recipes now pass `-r pyocd` explicitly.


### Z1 attempt 1 — three environment faults, then the real one (2026-08-16)

`just board-build` needed three fixes before it produced a genuine finding.
Each moved the build further, which is the useful part: configure -> codegen ->
every FFI archive -> the RMW.

| Fault | Cause | Fix |
| --- | --- | --- |
| `west: unknown command "build"` | the recipe set PATH but never `ZEPHYR_BASE`; `west build` must run inside a workspace | recipes source the workspace `env.sh` |
| `nros (codegen tool) not found` | no `nros` on PATH — the stale `~/.nros/bin` copy was deliberately deleted | recipe adds the checkout's `packages/cli/target/release` |
| `failed to install component: 'rust-std-thumbv7em-none-eabihf', detected conflict` | rustup fetching a different stable than the unpacked files (`liballoc-e2a964ee…` wanted vs `87f42bbe…` present) — a partial-upgrade state | `rustup target remove/add thumbv7em-none-eabihf` |

Also worth recording as a process note: the first run reported "exit code 0"
because the command was piped to `tail`, so the pipeline's status masked the
recipe's. Same trap as the `scripts/bin/cargo` shim swallowing test output
earlier in this session. **Do not read an exit status through a pipe.**

### The actual blocker

```
error: no global memory allocator found but one is required; link to std or
       add `#[global_allocator]` to a static item that implements GlobalAlloc
error: `#[panic_handler]` function required, but not found
       compiling nros-rmw-zenoh-staticlib
```

NOT an unregistered architecture: `modules/lang/rust/CMakeLists.txt:23` maps
Cortex-M with hard float to `thumbv7em-none-eabihf`, our target. The staticlib
is being compiled without whatever supplies `#[global_allocator]` and
`#[panic_handler]` on Zephyr.

This is a nano-ros ↔ zephyr-lang-rust wiring gap on a real ARM board, and it
matches the caveat already recorded in nano-ros's `board-support.toml`: Zephyr
is tier 1 but *"only ever built for native_sim/native/64. No real Zephyr
hardware board is built by anything."* phase-346's real-board proof was
`mps2_an385` — Cortex-M3, SOFT float, `thumbv7m-none-eabi`. A different target
row from ours, and the RMW there is zenoh too, so the comparison is direct.

Open, not guessed at. The next step is to diff how the zenoh staticlib is
configured for `mps2_an385` against `mr_canhubk3`, rather than adding an
allocator and hoping.

**Resolved (2026-08-27).** The entry builds and runs on the board. The gap was
in the wiring, as suspected, not in the target mapping; the record above stays
because the diagnosis path is the reusable part.

## 8. Open questions

* Does Cyclone fit in 320 KB at all, or is zenoh-pico the only viable RMW here?
  (Z3. Our host side is Cyclone, so this has consequences beyond the island.)
* nano-ros's `board-support.toml` caveats that Zephyr is tier 1 but *"only ever
  built for native_sim/native/64 — no real Zephyr hardware board is built by
  anything."* phase-346 landed Rust on a real Zephyr board (`mps2_an385`), so
  the seam is exercised — and now on S32K3 too: the entry builds and runs here.
  The caveat is stale as written; upstream has not been told.
* Media converter for T1 ↔ 100BASE-TX — still absent, and no longer blocking:
  the link is serial (4c). It gates T1 specifically, not the island.
* Does the FS26 driver need board-specific Kconfig beyond the board default, or
  is `CONFIG_WATCHDOG=y` (already in `mr_canhubk3_defconfig`) sufficient?
* ~~`src/safety_island_bringup/config/system_model.yaml` is COMMITTED.~~
  CLOSED 2026-09-05 by the `BRINGUP` migration. The debt was not only a
  convention one: the committed model had been resolved BEFORE the contract
  sidecar existed, so it carried `topics: 0` and every pool derived from it
  was sized for a system with no wiring. Both entries now say `BRINGUP
  <pkg>`, `nros sync` writes the model under `build/nros/models/`, and the
  resolved artifact records each input's sha256 in `meta.inputs` — the
  contract included, which is what makes a stale model detectable at all.

---

## Appendix A — why not FreeRTOS + S32DS

The original plan targeted the board's shipped S32 Design Studio FreeRTOS
project. That work is retained because it is what proved the vendor path
unviable, and because it produced real upstream fixes.

**What killed it: the vendor SDK is Windows-only.**

* NXP's **RTD** (Real-Time Drivers) publishes exactly one OS fragment per
  update site — `com.nxp.RTD.S32K3.win32.win32.x86_64`, *"S32K3 SDK Binary for
  Windows OS"*. Zero occurrences of `linux` in the p2 metadata across four
  sites checked, all RTD 3.0.0. NXP states it: *"the RTD is not developed to
  ensure full Linux compatibility."*
* The catalogue entry is named **"S32 Design Studio S32K3 SDK"** — it never says
  "RTD", which is why it is unfindable by name.
* The 3.6 RTD catalogue (`APSW/RTD/S32DS_3.6`) is **published and empty** —
  `<children size="0"/>`, stamped 2024-10-29.
* The **SW32K3 TCP/IP stack** (NXP's lwIP port) is not in the Eclipse catalogue
  at all, installs *on top of* RTD via the same mechanism, into the IDE tree,
  and is *"licensed together with S32 RTD under the same license model."* No RTD
  on Linux ⇒ no TCP/IP stack on Linux.
* Even on Windows it is a migration, not a drop-in: the stack wants S32DS 3.5,
  RTD 3.0.0 and **FreeRTOS 10.5.1**, where the reference project ships FreeRTOS
  **10.4.6**. Adopting it means changing the RTOS kernel under the vendor's own
  validated application.

**What was salvaged.** Two things, both verified locally rather than inherited:

1. The `integrations/s32ds` **probe works and needs no S32DS at all** — the zip
   ships every CDT `.args` file, so the probe derives the ABI from the shipped
   project directly. Confirmed: `-mcpu=cortex-m7 -mthumb -mlittle-endian
   -mfloat-abi=hard -mfpu=fpv5-sp-d16 -specs=rdimon.specs`,
   `FREERTOS_PORT=GCC/ARM_CM7/r0p1`. Exactly matching nano-ros's
   `[arch.cortex-m7]` profile.
2. nano-ros **phase-351** fixed real upstream defects found on this path — the
   board-less family-glue drop, the `_nra_board_active` inversion (a board NAME
   was the precondition for being a board, so any shell-integrated entry
   silently got no glue), and the entry archive shape for foreign linkers.
   Those stand on their own for ESP-IDF and PlatformIO too.

**When to revisit.** If Zephyr's S32K3 support proves insufficient, or if a
Windows machine with the NXP entitlement becomes available, the FreeRTOS path is
documented and its blocker is understood. The old plan is preserved in git
history at the revision before this rewrite.
