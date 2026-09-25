# MR-CANHUBK344 — board facts

Everything here was **measured on the board in this repo** unless a line says
otherwise. Where a fact came from a datasheet, a devicetree, or a manual rather
than from the silicon, it is marked. That distinction has mattered: several
things "known" from documentation turned out to be wrong or to have exceptions
only the hardware showed.

Silicon: **NXP S32K344**, Cortex-M7 r1p2, ARMv7E-M, **160 MHz**.
DAP IDCODE `0x6ba02477`. Board: `mr_canhubk3/s32k344` under Zephyr 4.4.0.

---

## Memory map

Read from the device with `pyocd cmd -c "show map"`:

| region | start | end | size | access | sector |
| --- | --- | --- | ---: | --- | --- |
| `itcm` | `0x00000000` | `0x0000ffff` | 64 KiB | rwx | — |
| `pflash` | `0x00400000` | `0x007fffff` | **4 MiB** | rx | 8 KiB |
| `dflash` | `0x10000000` | `0x1001ffff` | 128 KiB | rx | 8 KiB |
| `dtcm` | `0x20000000` | `0x2001ffff` | 128 KiB | rwx | — |
| `sram` | `0x20400000` | `0x2044ffff` | **320 KiB** | rwx | — |

**320 KiB of SRAM is the binding constraint for everything on this board.** The
4 MiB of flash is barely touched by anything we build.

### The top 48 KiB of pflash cannot be read

`0x007F4000`–`0x007FFFFF` faults on read — bisected to 8 KiB granularity:
`0x007F2000` reads, `0x007F4000` onward returns `memory transfer fault`. Single
words fail there too, so it is not a size or timeout effect. Most likely UTEST /
reserved; `UM11965` would confirm. It is outside any image we place, but a flash
backup taken from this board **does not contain it**.

### Reading flash over the probe

A single 4 MiB `savemem` fails with `memory transfer failed` even across the
readable range. **Chunk at 512 KiB or less.** The probe is also single-access —
a second pyocd command while a dump runs gets `Unable to claim interface`.

---

## CPU features

Reported by pyocd from the core itself:

```
CPU core #0: Cortex-M7 r1p2, v7.0-M architecture
  Extensions: [DSP, FPU, FPU_V5, MPU]
```

Confirmed independently by compiling for the target:

| feature | present | evidence |
| --- | --- | --- |
| ARMv7E-M **DSP / 32-bit SIMD** | yes | `uadd8`, `usad8`, `smlad`, `smuad`, `qadd16`, `pkhbt` all assemble and emit |
| **FPU** FPv5, single *and* double | yes | `vfma.f32` and `vfma.f64` emitted |
| I-cache / D-cache | yes, **enabled** | `CONFIG_ICACHE=y`, `CONFIG_DCACHE=y`; line size 32 B |
| **NEON** | **no** | `Error: selected FPU does not support instruction` |
| **Helium / MVE** | **no** | same rejection; Cortex-M55/M85 only |
| GPU / VPU / ISP / JPEG codec | **no** | none in the SoC devicetree |
| camera interface (CSI/DCMI) | **no** | none in the SoC devicetree |

The DSP extension is real but **32 bits wide** — 4×8-bit or 2×16-bit lanes per
instruction, against NEON's and Helium's 16 bytes. It suits control-loop
filtering, CRC and small FFTs. It does not make this part a vision processor:
a decoded 1080p frame is 6.2 MB against 320 KiB of SRAM, **19× short**, and even
a compressed 1080p JPEG (~350–790 KB measured) exceeds total SRAM.

---

## Peripherals

From the SoC devicetree (`nxp_s32k344_m7.dtsi`) — an automotive body/safety MCU:

`flexcan-fd`, `s32-gmac` + `gmac-mdio`, `lpuart`, `lpspi`, `lpi2c`,
`s32-adc-sar`, `s32-emios` (+PWM), `flexio` (+PWM), `mcux-edma`, `s32-qspi`,
`c40-flash` (+controller), `siul2-gpio`, `siul2-eirq`, `s32-swt`, `s32-wkpu`,
`s32-trgmux`, `s32-lcu`, `s32k3-pmc`, `s32-mc-me`, `s32-mc-rgm`, `s32-sys-timer`.

**Six CAN interfaces** — confirmed on the running factory image, which exposed
`can0`–`can5`.

### Ethernet is 100 Mbit, for two independent reasons

- the PHY is a **TJA1103 — 100BASE-T1** (single-pair automotive), and
- `FEATURE_GMAC_RGMII_EN = (0U)` for the S32K344 in the NXP HAL, so the MAC↔PHY
  bus is MII/RMII, which caps at 100 Mbit **regardless of the PHY**.

Both would have to change, which means different silicon. 100BASE-T1 needs a
media converter to reach ordinary RJ45 gear; matched speeds on both sides of
that converter, or it becomes a store-and-forward switch (which also breaks
gPTP transparency, since a bridge will not forward `01-80-C2-00-00-0E`).

Practical throughput is well under the line rate: a 160 MHz M7 running Zephyr's
IP stack with 320 KiB of RAM is realistically **10–30 Mbit/s**, not 97.5. That
figure is an estimate and has not been measured on this board.

---

## Connectors (from UG10154, the hardware manual)

| connector | purpose |
| --- | --- |
| **P6 "DCD-LZ"** | JST-GH, **SWD + console UART combined** — MCU-Link and the console cable both live here |
| P26 | ARM 10-pin JTAG/SWD, standard pinout |
| P2 / P5 | UART0 / UART1, DroneCode 6-pin (pin 1 supplies limited 5 V) |
| P12–P23 | CAN |
| P27 | power |
| P8B | I/O headers |

### The console UART, verified electrically

Zephyr's console is `lpuart2` at `0x40330000`, muxed to **PTA9 (TX) / PTA8 (RX)**
(`PTA9` MSCR reads `0x00200002` — SSS=2, OBE set), reaching **P6 → FTDI →
`/dev/ttyUSB0` at 115200**.

Proven by writing bytes straight into `LPUART2` `DATA` (`0x4033001c`) over SWD
and watching them arrive on the host. That test is worth remembering: it
separates "the UART works" from "the firmware is printing", and it is what
settled a long dead-end where a build looked bricked and was merely silent.

`LPUART2 FIFO` reads `0x00c00099` — **RX and TX FIFOs enabled**, `WATER` 0. The
**RX FIFO is only 4 bytes deep**, which is shorter than a zenoh serial frame.

---

## Watchdogs

- `fs26_wdt` — **DISABLED**. The board reports at boot:
  `<err> wdt_nxp_fs26: In DEBUG mode, watchdog is disabled`.
  So the FS26 SBC watchdog is *not* a reset-loop suspect in this configuration,
  which retires a standing guess in the bring-up triage sheet.
- `swt0` — READY.

---

## TCM ECC — handled, but only because the board opts in

S32K3 TCM is ECC-protected. The reference manual (via Zephyr's
`s32k3xx_startup.S`) requires the region be written by a **64-bit master** after
a *destructive* reset before any 32-bit master reads or writes it. Zephyr does
this in `soc_early_reset_hook`, gated on the TCMs appearing in `chosen`.

`mr_canhubk3_common.dtsi` **does** choose both (`zephyr,itcm`, `zephyr,dtcm`), so
the ECC init is compiled in with no action from us. Confirmed by disassembly:
`SRAM_LOOP`, `ITCM_LOOP` and `DTCM_LOOP` are all present.

Worth knowing because the opposite is easy to conclude: the `chosen` block in
`mr_canhubk3.dts` lists only `zephyr,code-partition` and `zephyr,flash`, so
reading that file alone suggests the TCMs are unchosen and the ECC loops dead.
The board `.dts` files *add* to the common `chosen` block rather than replacing
it. **Check `mr_canhubk3_common.dtsi`, and prefer the disassembly to either.**

A functional reset retains SRAM in hardware and will not show ECC problems; only
a destructive one will (`MC_RGM_DES`).

---

## Factory firmware (backed up before first flash)

```
NuttX 11.0.0  dbac7e12ff  Mar 3 2023  arm  mr-canhubk3
eth0  10.0.0.2/24  gw 10.0.0.1  MAC 66:55:44:33:22:11
can0..can5  DOWN
Umem 383,504 total / 368,480 free
```

The NXP demo: `nsh` with `candump`, `cansend`, `ping`, `telnetd`, `buttons`.
Real content **159,020 bytes**; the rest of pflash and all of dflash are erased.
Backup and checksums: `~/Downloads/NXP-CANHUBK344/firmware-backup-20260825/`.

Note the factory IP is `10.0.0.2/24` — **not** the `192.168.10.20/24` this
project's board conf uses.

---

## Deployment notes

### Probe and flashing

- `s32k344` is a **builtin** pyocd target; no pack install needed.
- The probe needs a udev rule or it is invisible (`No available debug probes`).
  VID `1fc9`; `udevadm control --reload-rules && udevadm trigger` is enough —
  **no replug required**, contrary to the usual advice.
- **Reset with `-M halt -c "reset halt" -c "go"`.** A plain `pyocd reset` leaves
  the core in **Lockup** on this board; that is an artefact of the reset
  sequence, not a firmware fault.
- Flash writes run ~45–65 kB/s.
- pyocd **breakpoints are unreliable here** — breakpoints at `main`, `z_cstart`
  and others were set successfully and silently never hit, while PC sampling
  proved those functions execute. **Trust PC sampling; do not trust breakpoints.**

### Reading a board whose only UART is taken

When a transport owns the wired UART, move the console to an unwired LPUART in
an overlay (so its bytes cannot corrupt the transport's framing) and read the log
over **RTT** on the existing SWD link. Four things this needs, none of which any
error message mentions:

| | |
| --- | --- |
| the SEGGER module is absent from this workspace | clone `zephyrproject-rtos/segger` into `modules/debug/segger` |
| west will not register it | `-DZEPHYR_EXTRA_MODULES=<path>` |
| `pyocd rtt` needs a TTY | run under `script -qec "..." /dev/null` |
| it will not find the control block | pass `-a <addr of _SEGGER_RTT>` |

The default 1 KiB up-buffer wraps before a post-hoc reader attaches, so a failing
run reads back empty: `CONFIG_SEGGER_RTT_BUFFER_SIZE_UP=16384`.

### Sizing traps, all found the hard way

- **The application heap is `CONFIG_NROS_ZEPHYR_HEAP_SIZE`, not
  `CONFIG_HEAP_MEM_POOL_SIZE`.** This entry used to read "`z_malloc` is
  `k_malloc`, so zenoh's buffers come from `CONFIG_HEAP_MEM_POOL_SIZE`". That
  stopped being true at nano-ros phase-391 W3. `z_malloc` and Rust's
  `__rust_alloc` both funnel through `nros_platform_alloc`
  (`third-party/nano-ros/packages/platform/nros-platform-zephyr/src/platform.c:182`)
  into one rlsf arena in `nros-platform/src/zephyr_heap.rs`, sized by
  `CONFIG_NROS_ZEPHYR_HEAP_SIZE`. nano-ros says it flatly in
  `third-party/nano-ros/zephyr/Kconfig:1372-1373`: "CONFIG_HEAP_MEM_POOL_SIZE
  does NOT govern application allocation any more; this does." So:
  - Raising `CONFIG_HEAP_MEM_POOL_SIZE` to cure an allocation failure under
    zenoh does nothing. Raise `CONFIG_NROS_ZEPHYR_HEAP_SIZE`.
  - Exhausting the arena does `printk("nros: HEAP EXHAUSTED: request %zu bytes,
    arena %zu bytes, caller %p")` with the return address (platform.c:212).
    On this board that console is not wired, so in practice the image just
    stops. Size the arena from the boot report's `platform heap PEAK` instead.
  - `CONFIG_COMMON_LIBC_MALLOC_ARENA_SIZE` (the picolibc allocator) is
    unrelated to both and is 0 in the board conf, because nothing calls
    `malloc`.
  The kernel heap does not go away: it still backs the k_malloc callers that
  remain (nano-ros's timer bridge, Zephyr's POSIX `semaphore.c` and `key.c`),
  and Zephyr floors it at the sum of the enabled
  `CONFIG_HEAP_MEM_POOL_ADD_SIZE_*` entries. See
  `src/zephyr_entry/boards/mr_canhubk3_s32k344.conf`, "The Zephyr KERNEL heap".
- **`CONFIG_MAIN_STACK_SIZE=4096` overflows** in zenoh's declare path
  (`_z_declare_resource` alone reserves 340 B). 8192 is the smallest that has
  held. It presents as a `USAGE FAULT` — *"Illegal use of the EPSR"* with a
  garbage `pc` — which looks like a NULL function pointer and is not.
  `CONFIG_MPU_STACK_GUARD=y` renames it to `ZEPHYR FATAL ERROR 2: Stack overflow`
  instantly. Use it to diagnose, then switch it off: its per-stack reservation
  does not fit this image.
- **`NROS_MAX_LARGE_SUBSCRIBERS=0`** is worth ~60 KiB on a single-topic image.
- RMW snippet sizing is host-scale by default (Cyclone asks for a 16 MiB malloc
  arena). nano-ros now supplies it as `configdefault` so a board conf wins; before
  that the only override was `-D` on the command line.

### Current image footprints

Safety island, four MRM nodes, zenoh over Ethernet:

```
FLASH    604,228 / 4,144,896   14.58%
RAM      273,072 /   327,680   83.33%
DTCM     100,744 /   131,072   76.86%   (app .bss relocated)
ITCM      12,816 /    65,536   19.56%   (MRM node code relocated)
```

CycloneDDS builds for the same board at **RAM 174,364 (53.21%)** — static
footprint only, at a 24 KiB malloc arena; it has never been run.

**TCM is not DMA-reachable.** Ethernet descriptors and the `net_pkt`/`net_buf`
pools must stay in SRAM; only CPU-only data may be relocated.

---

## Image memory layout

Measured from the ELF of the zenoh-over-serial talker example
(`examples/zephyr/c/talker`), which is the smallest thing here that does real
ROS 2 work. Addresses are where sections actually land:

```
FLASH  0x00400000 ─────────────────────────────────────────
       0x00400100  rom_start              1,788 B   IVT + vector table
       0x00400800  text                 277,300 B   77% of the flash image
       0x00444428  initlevel/device/isr  ~2,700 B
       0x00444fb0  rodata                76,996 B
       0x00457c74  (LMA of .datas)                  copied to RAM at boot

SRAM   0x20400000 ─────────────────────────────────────────
       0x20400000  _RTT_SECTION_NAME     16,568 B   debug only
       0x204040e0  datas                  3,368 B   LMA 0x00457c74
       0x20404eb0  bss                  132,020 B
       0x20425268  noinit               121,240 B
                                        ─────────
                              total RAM  273,360 B   83% of 320 KiB
```

`.datas` is the **only** section with a split VMA/LMA — loaded from flash, run
from RAM. Everything else runs where it loads. (An image using
`zephyr_code_relocate` adds `.dtcm_bss_reloc` and `.itcm_text_reloc`; the ITCM
one is also a copy, flash LMA to ITCM VMA. See
[tcm-relocation.md](tcm-relocation.md).)

### Where the RAM actually goes

Largest objects, from the symbol table:

| bytes | object |
| ---: | --- |
| 65,536 | `nros_rmw_zenoh::shim::subscriber::LARGE_PAYLOADS` |
| 65,536 | `nros_thread_stacks` |
| 32,852 | `kheap__system_heap` |
| 16,384 | `…subscriber::SMALL_PAYLOADS` |
| 16,384 | `_acUpBuffer` (RTT) |
| 8,856 | `…service::SERVICE_BUFFERS` |
| 8,192 | `z_main_stack`, `static_subscriber_storage::SLOTS`, `malloc_arena` |
| 4,736 | `posix_thread_pool` |

Three things worth reading off that table:

- **Two objects are half the RAM.** `LARGE_PAYLOADS` at 64 KiB is the
  subscriber's large-message pool; `CONFIG_NROS_MAX_LARGE_SUBSCRIBERS=0` removes
  it, which is where the ~60 KiB saving quoted earlier comes from. A talker with
  one publisher does not need it at all.
- **`kheap__system_heap` (32,852 B) is a pre-phase-391 figure and does not
  describe a current image.** When this table was taken, `z_malloc` did route to
  `k_malloc` and that heap was the application's. It no longer is (see the
  sizing trap above), so a current image's application allocation shows up as
  the rlsf arena `CONFIG_NROS_ZEPHYR_HEAP_SIZE` reserves, not here. The island
  board conf now sets `CONFIG_HEAP_MEM_POOL_SIZE=0`, which Zephyr floors at 512
  and which measured 572 B of `.noinit` against 8,268 B before. Reading the
  symbol table is still the cheapest way to check you sized the right heap; just
  read the arena, not this symbol.
- **`_acUpBuffer` + `_RTT_SECTION_NAME` ≈ 33 KiB is debug-only** and comes
  straight back out of a production build.

### The example is not smaller than the island

```
              text      data       bss
talker     359,528     3,536   269,876
island     597,928     6,768   367,566
```

The island carries ~66% more text (four MRM nodes, 14 publishers, 11
subscriptions, 2 service servers) and 36% more `.bss`, and still lands at the
**same 83% of SRAM** — because it relocates `.bss` into DTCM and MRM code into
ITCM, which the example does not. Neither has meaningful headroom; they are
differently placed, not differently sized.

---

## What is proven on this board, and what is not

**Z0, 2026-09-25 (phase-7 W6):** `samples/hello_world` built with hal_nxp
named on the command line (`-DZEPHYR_EXTRA_MODULES=$ISLAND_ZEPHYR_WS/modules/hal/nxp`,
now what `just board-hello` does), Zephyr 4.4.0, SDK 1.0.1: FLASH 50,584 B,
RAM 6,624 B; pyocd 0.44.0 over the MCU-LINK erased and programmed 57,344 B
(7 sectors) at 44.67 kB/s; after `pyocd reset` the console (`/dev/ttyUSB0`,
115200) printed, verbatim:

```
*** Booting Zephyr OS build v4.4.0 ***
Hello World! mr_canhubk3/s32k344
```

So the IVT header, the FS26 watchdog handling, the flash chain and the console
are all good on this kit; a later failure is ours.

**Z1a, 2026-09-25 (phase-7 W6), partial:** the island image itself
(`build-board/zephyr/zephyr.hex`, sha256 `be0a3afa...47ed6`, the phase-6 W8b
build with every pool derived) flashed with `pyocd flash -t s32k344`: 630,784 B
erased and programmed (77 sectors) at 61.34 kB/s. After `pyocd reset` the core
reads `Sleeping` (idle, not halted and not faulted) and the UART carries, in
35 s, 24 identical 9-byte COBS frames (`02 01 01 01 01 01 01 01 00`, decoding
to `01 00 00 00 00 00 00 00`): the zenoh serial link's open attempts, since
this image's locator is `serial/uart@40330000#baudrate=115200` and no peer
answers. This is the first time the island image has run on the board. What
it does NOT give: the boot report, because the only wired UART is the
transport's (see "Reading a board whose only UART is taken").

**Z1a, the trace read, same day, later:** the phase-7 W1 image with tracing
(sha256 `6122d68b...e0e35a`, FLASH 632,788 B, RAM 319,904 B of 327,680,
97.63%) flashed (565,248 B programmed, 9 pages unchanged) and, 6 s after
`pyocd reset`, `just trace-board` read `ram_tracing` (16 KiB) over SWD.
`island_trace.py decode --zephyr 4.4`, verbatim except the label:

```
event                            count       bytes  B/event
heartbeat                          223        3122     14.0
thread_switched_out                 76        2280     30.0
thread_switched_in                  76        2280     30.0
thread_sched_ready                  37        1110     30.0
provenance                           1         775    775.0
thread_sched_pend                   19         570     30.0
k_sleep_exit                        19         266     14.0
k_sleep_enter                       20         200     10.0
thread_sched_lock                    1           6      6.0
thread_sched_unlock                  1           6      6.0
total                              473       10615
provenance: island-trace/1;zephyr=4.4.0;board=mr_canhubk3;contract_sha256=3879cbf4...;markers=31;table_sha256=bd6e59bb...;entities=pub=14,sub=11,srv=2,cli=2,timer=4;heartbeat_ms=100;...;MAIN_STACK_SIZE=16384;NROS_ZEPHYR_HEAP_SIZE=94208;NROS_ZEPHYR_TASK_SLOTS=5;...;SYS_CLOCK_HW_CYCLES_PER_SEC=160000000;...
      99.496 ms  heartbeat seq=0 uptime=100 ms
     199.495 ms  heartbeat seq=1 uptime=200 ms
ok   heartbeat: seq 0..222 contiguous (223 records)
```

So the provenance record, the contract's digest and the delivered knob
values are readable from silicon; the heartbeat ran 22.3 s at a measured
99.999 ms period from the 160 MHz cycle counter with no gap, which is the
boot report's job done by other means. And the finding: **no marker ever
fired**. The only threads that ran are `main`, `idle` and `shell_uart`, and
`main` slept 20 times in 22 s. The image sits in the zenoh serial session's
open-retry loop (the UART frames above, about one a second) and never
reaches the executor, so no node timer runs and the contracted paths are
never entered. `trace-check` says so: `FAIL markers: 26 of 31 never seen`.
On this kit, with no serial peer and no T1 link, the island boots and waits;
the reaction cannot be traced on silicon until a transport peer exists (a
host on the serial link, or the T1 media converter).

**Z1b over serial, 2026-09-25 (phase-7 W7): the session opens, but the
executor does not start.** A host `rmw_zenohd` listened on
`serial//dev/ttyUSB0#baudrate=115200` with `router-serial.json5`
(`just board-peer`, `just/board-peer.just`; it runs under `env -i` with ROS 2
sourced fresh, and on TCP port 7449, not 7447). The board then opened a zenoh
session on every boot, 6 of 6, each within a second of reset, and began
registering entities (the router log shows the island's liveliness tokens on
`@ros2_lv/10/...`). The "one run in three" flakiness recorded for the talker
in `experiments/serial-interop/README.md` did not appear with this image and
router. Registration then failed in `stop_mode_operator`'s `gear` publisher, the
image's third TRANSIENT_LOCAL publisher. nano-ros's retention pool is 2 when
the contract states no durability. The component object read over SWD holds
`create_publisher_in` / `-100` (TransportError). Every entity was undeclared
within 0.25 s, and the router expired the link 10 s later. So no node timer
ran and no marker fired. `ros2 node list` through the router
(`RMW_IMPLEMENTATION=rmw_zenoh_cpp`, `ROS_DOMAIN_ID=10`), run 1, verbatim. It
was taken after the board's session had already expired. The nodes exist for
about 0.6 s per boot, so a CLI query cannot catch them; the router log is the
record that they were declared.

```
== ros2 node list (rmw_zenoh_cpp, domain 10, router tcp/127.0.0.1:7447)
== ros2 topic list
/parameter_events
/rosout
```

Two trace reads, both in `experiments/serial-interop/w7/`:

- The W1 image (thread switches on) filled its 16 KiB buffer 31 ms after
  boot, before the first heartbeat. In that window `main` is woken once per
  received byte, and pend/ready repeats every 87 us, one byte at 115200 baud.
  That came to 173 switch pairs and 16,381 B.
- With `CONFIG_TRACING_THREAD=n` (the board conf since W7), the buffer held
  1,114 contiguous heartbeats (111 s) and 0 markers.

The boot report reads `stage 4 RegisteringEntities`, arena 9,800 of 50,640 B,
heap peak 57,024 of 94,720 B. It records no error, so on this board it does
not capture a constructor failure. Also seen: `pyocd reset -t s32k344` booted
the image every time (see the Lockup note under "Probe and flashing"). pyocd's
Python API reset only when connected in `halt` mode; in `attach` mode it left
the core running. Details and the numbers are in `docs/wcet.md` ("Silicon
(W7)").

**Proven:** flashing and boot; console; the ECC init path executes; ROS 2 interop
over serial end to end (`ros2 node list`, `topic echo` with real data); the
receive path (board logs `I heard:` from a host publisher); service registration.

**Not proven:** the safety island image itself has never run here — only
examples. Ethernet/T1 has never been exercised (no media converter). CycloneDDS
links but has never run. ITCM/DTCM relocation places correctly but its
boot-time copy has never been observed executing. TCM ECC has never seen a
destructive reset. And serial interop is **flaky** — roughly one run in three
establishes a link, cause still open.
