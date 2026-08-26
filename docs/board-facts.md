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

- **`z_malloc` is `k_malloc`** in zenoh-pico's Zephyr port, so zenoh's buffers
  come from `CONFIG_HEAP_MEM_POOL_SIZE` — the *kernel* heap.
  `CONFIG_COMMON_LIBC_MALLOC_ARENA_SIZE` (the Rust/picolibc allocator) has **no
  effect on it**. Enlarging the arena while shrinking the kernel heap makes every
  send fail from boot and reads as a transport bug.
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

## What is proven on this board, and what is not

**Proven:** flashing and boot; console; the ECC init path executes; ROS 2 interop
over serial end to end (`ros2 node list`, `topic echo` with real data); the
receive path (board logs `I heard:` from a host publisher); service registration.

**Not proven:** the safety island image itself has never run here — only
examples. Ethernet/T1 has never been exercised (no media converter). CycloneDDS
links but has never run. ITCM/DTCM relocation places correctly but its
boot-time copy has never been observed executing. TCM ECC has never seen a
destructive reset. And serial interop is **flaky** — roughly one run in three
establishes a link, cause still open.
