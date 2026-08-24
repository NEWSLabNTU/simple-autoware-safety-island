# TCM relocation on MR-CANHUBK344 — how it works, and the two traps

The image relocates data to DTCM and the MRM node code to ITCM. Both TCMs are
zero-wait-state memory private to the CPU. This note records where the machinery
lives, which parts are automatic, and the two failure modes a build cannot catch.

Status: **links and places correctly; never executed on silicon.** The board is
blocked on the MCU-Link probe. Everything below about boot behaviour is derived
from the sources, not observed.

## What is where

Four layers. Only the last three are ours.

| layer | file | role |
| --- | --- | --- |
| Zephyr SoC | `dts/arm/nxp/s32/nxp_s32k344_m7.dtsi` | declares the regions exist — `itcm: memory@0`, 64 KiB; `dtcm: memory@20000000`, 128 KiB |
| Zephyr SoC | `soc/nxp/s32/s32k3/s32k3xx_startup.S` | the ECC init loop — **`#if`'d on `DT_CHOSEN(zephyr_itcm)` / `(zephyr_dtcm)`** |
| Zephyr | `cmake/modules/extensions.cmake`, `scripts/build/gen_relocate_app.py`, `z_data_copy()` | front end, linker fragment, boot-time copy |
| **ours** | `src/zephyr_entry/boards/mr_canhubk3_s32k344.overlay` | the `chosen` nodes — *enables* the above |
| **ours** | `src/zephyr_entry/boards/mr_canhubk3_s32k344.conf` | `CONFIG_CODE_DATA_RELOCATION=y` |
| **ours** | `src/zephyr_entry/CMakeLists.txt` | *policy* — which libraries move where |
| **ours** | `patches/zephyr/0001-gen_relocate_app-fix-source-to-object-matching.patch` | see trap 2 |

Nothing about relocation lives in `third-party/nano-ros`, and nothing about this
project's node names lives there either (audited 2026-08-24: every hit is a
comment or a `#[test]` fixture). Keep it that way — the policy half is
inherently per-project.

## Trap 1: the board package does not choose the TCMs, so the ECC init is dead code

S32K3 TCM is ECC-protected. The reference manual requires the region be written
by a **64-bit master** after a destructive reset before any 32-bit master reads
or writes it. Zephyr does this in `soc_early_reset_hook` — but the ITCM and DTCM
loops are compiled out unless the `chosen` nodes exist, and `mr_canhubk3.dts`
chooses only `zephyr,code-partition` and `zephyr,flash`:

```dts
chosen {
    zephyr,code-partition = &code_partition;
    zephyr,flash = &flash0;
};
```

The SoC says "these regions exist". The board says nothing about using them. So
on a stock `mr_canhubk3`, **both TCMs stay ECC-uninitialised**, and the SRAM loop
above them runs unconditionally while the TCM loops do not.

This bit us silently: we relocated `.bss` to DTCM during the memory-fit work with
that loop compiled out. Zeroing relocated `.bss` from C is a *32-bit* store —
the access the manual says must come **after** the 64-bit initialisation, not
instead of it.

The fix is the overlay. Verify it took by disassembling, not by building:

```
$ arm-none-eabi-objdump -d zephyr.elf --disassemble=soc_early_reset_hook
0040c74c <SRAM_LOOP_END>:
  40c74c:  mov.w  r1, #0            <- ITCM base
  40c750:  mov.w  r2, #65536        <- 64 KiB
0040c756 <ITCM_LOOP>:
  40c756:  stmia  r1!, {r0, r3}     <- 64-bit store pair
```

If `ITCM_LOOP` / `DTCM_LOOP` are absent, the overlay is not being applied.

**This is a board-package gap, not a project one.** Anyone relocating anything
on this board has to rediscover it. Upstreaming `zephyr,itcm` / `zephyr,dtcm`
into `mr_canhubk3.dts` is the real fix; the overlay is our local compensation.

## Trap 2: relocation fails silently and the build still goes green

On a source-to-object mismatch, `gen_relocate_app.py` writes an **empty**
fragment, prints nothing, and exits 0. The link succeeds and nothing moves.

Our patch fixes the specific matcher bug we hit (a source generated into the
build root, where the object tree does not mirror the source tree), but the
general shape — no match, empty output, success — is still there.

So: **verify by the region report, never by the build succeeding.**

```
ITCM:       12816 B        64 KB     19.56%
DTCM:      100680 B       128 KB     76.81%
```

A `0 B` line where you expected content means it relocated nothing.

## Automatic vs. manual

Automatic:

- region discovery from the devicetree
- linker fragment generation, and the boot-time flash→ITCM copy
- **overflow protection** — over-filling a region is a hard link error
  (`region ITCM overflowed by N bytes`), not silent corruption

Manual, and not reasonably automatable:

- **which libraries to move.** A policy call about what is latency-critical. No
  tool knows the MRM decision path matters more than the shell does.
- **whether the candidate is DMA-safe.** TCM is not reachable by the DMA
  masters. Moving the net buffers there would link cleanly and fail at runtime.
  This is why `DTCM_BSS` takes the app library and not the net stack.
- **the `chosen` nodes**, per trap 1.
- **verification**, per trap 2.

## Granularity

`zephyr_code_relocate(LIBRARY ...)` moves the whole library, so each node's
constructor rides into ITCM despite running once. A `FILTER` argument exists but
takes a regex over *mangled* C++ names: it stops matching on any rename and then
relocates nothing while still linking green — trap 2 again. With 51 KiB of ITCM
free, a few KiB of one-shot code is the cheaper problem.

## What ITCM actually buys here

`CONFIG_ICACHE=y` is already set, so this is **not** a throughput win — a hot
loop already runs near zero-wait out of cache. It is a determinism change. The
M7's I-cache is small against 421 KiB of text, so the MRM decision path competes
for lines with the net stack, the shell and the Rust executor, and a decision
taken after an idle period pays flash wait states on every miss. ITCM is
zero-wait always, with no miss to jitter the response, and it returns those
cache lines to the rest of the image.

For a safety island the worst case is the number that matters. Do not expect a
measurable average-throughput change; if someone measures one, suspect the
measurement.
