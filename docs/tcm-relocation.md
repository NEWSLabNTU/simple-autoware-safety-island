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
| Zephyr SoC | `soc/nxp/s32/s32k3/s32k3xx_startup.S` | the ECC init loop, gated on the `chosen` TCM nodes |
| Zephyr board | `boards/nxp/mr_canhubk3/mr_canhubk3_common.dtsi` | **chooses both TCMs** — so the ECC loops are compiled in |
| Zephyr | `cmake/modules/extensions.cmake`, `scripts/build/gen_relocate_app.py`, `z_data_copy()` | front end, linker fragment, boot-time copy |
| **ours** | `src/zephyr_entry/boards/mr_canhubk3_s32k344.conf` | `CONFIG_CODE_DATA_RELOCATION=y` |
| **ours** | `src/zephyr_entry/CMakeLists.txt` | *policy* — which libraries move where |
| **ours** | `patches/zephyr/0001-gen_relocate_app-fix-source-to-object-matching.patch` | the silent-failure fix |

Nothing about relocation lives in `third-party/nano-ros`, and nothing about this
project's node names lives there either (audited 2026-08-24: every hit is a
comment or a `#[test]` fixture). Keep it that way — the policy half is
inherently per-project.

## TCM ECC — handled by the board, not by us

S32K3 TCM is ECC-protected. The reference manual requires the region be written
by a **64-bit master** after a destructive reset before any 32-bit master reads
or writes it. Zephyr does this in `soc_early_reset_hook`
(`soc/nxp/s32/s32k3/s32k3xx_startup.S`), gated on the TCMs being named in
`chosen`.

**`mr_canhubk3` names them**, in `mr_canhubk3_common.dtsi` — which both
`mr_canhubk3.dts` and `mr_canhubk3_s32k344_mcuboot.dts` include:

```dts
chosen {
    zephyr,sram = &sram0_1;
    zephyr,itcm = &itcm;
    zephyr,dtcm = &dtcm;
    ...
};
```

So the ECC initialisation is compiled in with no action from us, and has been
for the DTCM relocation all along. Verified by building with no overlay of our
own and disassembling:

```
$ arm-none-eabi-objdump -d zephyr.elf --disassemble=soc_early_reset_hook
0040da8e <SRAM_LOOP>:
0040da9e <ITCM_LOOP>:
0040daae <DTCM_LOOP>:
```

This is recorded because the opposite is easy to conclude and was concluded here
first: the `chosen` block in `mr_canhubk3.dts` lists only `zephyr,code-partition`
and `zephyr,flash`, so reading that file alone suggests the TCMs are unchosen and
the ECC loops dead. They are not — the board `.dts` files *add* to the common
`chosen` block rather than replacing it. **Check `mr_canhubk3_common.dtsi`, and
prefer the disassembly to either.**

There is consequently nothing to fix upstream here, and no overlay is needed.

## The one real trap: relocation fails silently and the build still goes green

On a source-to-object mismatch, `gen_relocate_app.py` writes an **empty**
fragment, prints nothing, and exits 0. The link succeeds and nothing moves.

Our patch fixes the specific matcher bug we hit (a source generated into the
build root, where the object tree does not mirror the source tree), but the
general shape — no match, empty output, success — is still there. This is the
only Zephyr change this project actually needs.

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
- **verification** — see above.

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
