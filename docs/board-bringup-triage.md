# Board bring-up triage — MR-CANHUBK344 (S32K344)

For the serial console at 2am. Symptom on the left, the knob and its file on the
right.

**Read this first:** the image fits 320 KiB because a dozen pools were cut to
measured need. Every one of those cuts is a hypothesis that has never executed on
silicon. When the board misbehaves, the cause is far more likely to be one of
these values than a logic bug in a node that already ran green on native and
native_sim.

**Second thing:** one failure mode below is still **silent** — it does not crash,
log, or return an error you will see. Two others used to be and are now fixed
upstream, but only if your submodule is new enough. Section 3 has all three;
read it before you conclude something "works".

---

> Hardware reference — memory map, CPU features, connectors, sizing traps:
> [board-facts.md](board-facts.md).

## 0. Before power

| | |
| --- | --- |
| **Power order** | MCU-Link **first**, then the board. It can back-power otherwise. |
| **Probe** | pyocd, `--target=s32k344`. `just board-doctor` reports whether one is connected. |
| **Host link** | 100BASE-T1 needs a media converter (RDDRONE-T1ADAPT or similar). Not in the kit — Z1 and Z4 are blocked without it. |
| **Board IP** | `192.168.10.20/24`, gw `192.168.10.1`. Host side must match. |

Run `just board-doctor` before anything. It checks the workspace, the SDK venv,
pyocd, the probe, and — importantly — that `patches/zephyr/0001` is still applied.

---

## 1. Go in stages. Do not skip Z0.

| stage | command | what it proves |
| --- | --- | --- |
| **Z0** | `just board-hello` | IVT header, FS26 watchdog, flash chain, console. **Zero nano-ros** — a failure here is board or probe, never our stack. |
| **Z1** | `just board-build && just board-flash` | boots, IP comes up, ping across T1 |
| **Z3** | console + `ros2 node list` from the host | zenoh session joins, the graph is visible |
| **Z4** | the phase-2 demo | 3.90 → 0.00 m/s with the island on real silicon |

If Z0 fails, nothing below applies. Fix the board or the probe first.

---

## 2. Symptom → cause, most likely first

### Nothing on the console

Console is `CONFIG_UART_CONSOLE`. If Z0 printed and the island does not, the
image died before console init — suspect the relocation or the boot config, not
a node.

### Boots, then hard-faults or resets early

| suspect | current | where | note |
| --- | ---: | --- | --- |
| `CONFIG_MAIN_STACK_SIZE` | 8192 | `justfile` `board-build` | the nros-zenoh snippet asks 16384. **Raise this first.** |
| `CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE` | 4096 | `justfile` `board-build` | |
| `NROS_ZEPHYR_TIER_STACK_SIZE` | 4096 | entry `CMakeLists.txt` | only if something spawns a tier; nothing should |

The watchdog is enabled (`CONFIG_WATCHDOG=y`, FS26 SBC). A reset loop with no
fault message may be the watchdog, not a crash.

**If the fault is at the very first instructions, TCM ECC is worth one check —
but it is normally fine.** The image relocates `.bss` to DTCM and the MRM node
code to ITCM, and S32K3 TCM must be written by a 64-bit master after a
*destructive* reset before anything else touches it. Zephyr does that in
`soc_early_reset_hook`, and `mr_canhubk3_common.dtsi` chooses both TCMs, so the
loops are compiled in by default. Confirm only if something has changed the
devicetree:

```
arm-none-eabi-objdump -d zephyr.elf --disassemble=soc_early_reset_hook \
  | grep -cE 'ITCM_LOOP|DTCM_LOOP'      # expect 2
```

A functional reset retains SRAM in hardware and will not show this; only a
destructive one will (`MC_RGM_DES`). → [tcm-relocation.md](tcm-relocation.md)

### Faults with a garbage PC — suspect the STACK, not the pointer

A `USAGE FAULT` reporting **"Illegal use of the EPSR"** with `pc = 0x00000000`
(or any address in RAM) is almost always a stack overflow, not a corrupt
function pointer. The overflow wrecks the exception frame, so the CPU unstacks
garbage and the fault it reports is a consequence rather than the cause. Chasing
the apparent NULL call wastes hours — this cost several rounds during the serial
bring-up.

Turn the guard on and it names itself:

```
CONFIG_MPU_STACK_GUARD=y
```
```
***** MPU FAULT *****  Stacking error
>>> ZEPHYR FATAL ERROR 2: Stack overflow on CPU 0
```

Use it as a diagnostic and switch it back off — its per-stack reservation is
substantial and may not fit. Fix the size instead. `CONFIG_MAIN_STACK_SIZE=4096`
overflows in zenoh's declare path (`_z_declare_resource` alone reserves 340 B);
8192 is the smallest that has held.

### Reading a board whose only UART is taken

When a transport owns the wired UART, the console has nowhere to go. Move it to
an unwired LPUART in an overlay so its bytes cannot corrupt the transport's
framing, and read the log over RTT on the existing SWD link:

```
pyocd rtt -t s32k344 -a $(arm-none-eabi-nm zephyr.elf | awk '$3=="_SEGGER_RTT"{print "0x"$1}')
```

Four things this needs, none of which any error message mentions:

| | |
| --- | --- |
| the SEGGER module is not in this workspace | clone `zephyrproject-rtos/segger` into `modules/debug/segger` |
| west will not register it | `-DZEPHYR_EXTRA_MODULES=<path>` |
| `pyocd rtt` needs a TTY | run it under `script -qec "..." /dev/null` |
| it will not find the control block | pass `-a <addr of _SEGGER_RTT>` |

The default 1 KiB up-buffer also wraps before a post-hoc reader attaches, so a
failing run reads back empty: `CONFIG_SEGGER_RTT_BUFFER_SIZE_UP=16384`.

### zenoh-pico is sized by the KERNEL heap, not the libc arena

`z_malloc` on Zephyr is `k_malloc` (zenoh-pico `src/system/zephyr/system.c`), so
every zenoh buffer comes from `CONFIG_HEAP_MEM_POOL_SIZE`.
`CONFIG_COMMON_LIBC_MALLOC_ARENA_SIZE` — which sizes the Rust/picolibc allocator
— has no effect on it. Serial send and receive each take 1507+1516 B and can be
live at once, so a serial image needs ~8 KiB of kernel heap before it does
anything. Enlarging the arena while shrinking the kernel heap makes every send
fail from boot, which reads as a transport bug.

### Boots, then HANGS with no fault and no further output

Distinct from a hard-fault: no panic, no message, output simply stops. nano-ros
**#0756** was exactly this — `Box::new(ParamState{..})` has no placement-new, so
the parameter store was built on the caller's stack: 2,244,628 B measured on
thumbv7em at `NROS_MAX_PARAMETERS=256`, against a 512 KiB main stack. Fixed
(`dd79d3125`); the temporary is now 68 B.

So that specific cause is gone. The *shape* still matters here, and more than
upstream: this image runs `CONFIG_MAIN_STACK_SIZE=8192`, half what the snippet
asks. A silent hang on the boot path is stack exhaustion until proven
otherwise — it walks off the end of a stack with no guard below it, which is
why it hangs instead of faulting.

Order: raise `MAIN_STACK_SIZE` to 16384 in the recipe, reflash. If it boots, get
the real number from `kernel thread stacks` (§4) rather than leaving it doubled.

### `pthread_create` fails / a thread never starts

`NROS_ZEPHYR_MAX_THREADS=4` (entry `CMakeLists.txt`). Covers zenoh's read and
lease tasks plus the spin thread. The 5th `pthread_create` fails. Raise to 6 and
retest before suspecting anything else.

### Allocation abort, `k_malloc` returns NULL, or zenoh fails to start

| suspect | current | snippet default | where |
| --- | ---: | ---: | --- |
| `CONFIG_HEAP_MEM_POOL_SIZE` | 16384 | 65536 | `justfile` |
| `CONFIG_COMMON_LIBC_MALLOC_ARENA_SIZE` | 24576 | — | board conf |

Both were cut to fit. There is 53 KiB of SRAM free — raising either is cheap.

### Node creation fails at boot

| symptom | knob | current | need |
| --- | --- | ---: | ---: |
| `SubscriberCreationFailed`, opaque | `NROS_RMW_SUBSCRIBER_SLOTS` | 12 | 11 |
| `declare_parameter` → `ErrorCode::Full (-5)` | `NROS_COMPONENT_MAX_PARAMS` | 16 | 11 |
| 7th node will not attach | `NROS_EXECUTOR_MAX_NODES` | 6 | 4 |

`MAX_NODES` was the one limit sized to exact need (4 against 4 nodes). Now 6.
The two spare slots cost 2,416 B of **DTCM** and zero SRAM, because the executor
storage was already relocated there — see §5.

### A callback never fires / one topic looks dead

Since nano-ros **#0757** this reports itself. Look for this on the console —
first occurrence, then every 64th:

```
subscription take DROPPED (...); buffer is N bytes. The sample was received and
ACKed, then discarded — raise the subscription buffer knob if this is
BufferTooSmall. Dropped N so far (issue 0757)
```

It also increments `subscription_errors` in the executor's spin result, so the
count stops lying.

If it says `BufferTooSmall`, raise `CONFIG_NROS_SUBSCRIPTION_BUFFER_SIZE` (board
conf) — and recompute `CONFIG_NROS_EXECUTOR_ARENA_SIZE` with it, the two move
together (`max_cbs * (3 * rx_buf + 512) + 2048`). On zenoh the relevant knob may
instead be `CONFIG_NROS_SUBSCRIBER_BUFFER_SIZE` or
`CONFIG_NROS_SUBSCRIBER_LARGE_SIZE`.

### Networking never comes up

`CONFIG_NET_CONFIG_INIT_TIMEOUT=30`. Check the PHY link first (`net iface` in the
shell — see §4), then the media converter, then:

| | current | stock | where |
| --- | ---: | ---: | --- |
| `CONFIG_NET_MAX_CONN` | 4 | 8 | board conf |
| `CONFIG_NET_MAX_CONTEXTS` | 8 | 32 | board conf |
| `CONFIG_NET_PKT_{RX,TX}_COUNT` | 16 / 16 | 32 / 32 | `justfile` — snippet-contested |
| `CONFIG_NET_BUF_{RX,TX}_COUNT` | 32 / 32 | 64 / 64 | `justfile` — snippet-contested |

The split is not arbitrary; see §5.

---

## 3. Failures that do not announce themselves

**1. Entities missing from `ros2 node list`. STILL SILENT.**
`CONFIG_NROS_MAX_LIVELINESS=32` against 29 tokens — one per node, per publisher
*and* per subscriber (4 + 14 + 11). On exhaustion `zpico_declare_liveliness`
returns `ZPICO_ERR_FULL` and the shim discards it with `.ok()`. The entity
publishes and subscribes perfectly and is invisible to every ROS 2 tool.

If the graph looks short but data flows, this is why — not a discovery problem.
It is the one failure in this document that gives you nothing to grep for.

**2. A rebuild that quietly changed the image — FIXED, but check your submodule.**
Knobs reach `build.rs` only if they have a `_nros_resolve_knob` row; without one
they came from the environment of whatever shell ran ninja, so `cd build-board &&
ninja` rebuilt at crate defaults — and `NROS_RMW_SUBSCRIBER_SLOTS` reverted 12 → 8
silently, re-breaking the 9th subscription.

Fixed upstream in nano-ros **#0752** (`61684d09`), which gave the last five knobs
Kconfig rows. All sizing now lives in the board conf and bakes into
`build.ninja`. To confirm on any tree:

```sh
grep -o 'NROS_RMW_SUBSCRIBER_SLOTS=[0-9]*' build-board/build.ninja
```

Empty means you are on a nano-ros older than #0752 — build only through
`just board-build` until you bump.

**3. A relocation that relocated nothing — loud here, silent by design.**
If `patches/zephyr/0001` is missing (a `west update` resets the Zephyr tree),
`zephyr_code_relocate()` writes an empty fragment, prints nothing, and exits 0.
Here that overflows RAM by ~39 KiB so it fails loudly — but *verify DTCM in the
region report*, never the build succeeding. `just board-doctor` checks for it.

---

## 4. Instruments already in the image

Built in deliberately. Use them before guessing.

| tool | how | for |
| --- | --- | --- |
| Zephyr shell | over the console | everything below |
| `CONFIG_THREAD_ANALYZER` | `kernel thread stacks` | **actual stack high-water per thread** — settles every stack question in §2 with a number |
| `CONFIG_INIT_STACKS` | (enables the above) | stacks are pattern-filled so usage is measurable |
| `CONFIG_NET_SHELL` | `net iface`, `net conn`, `net stats` | PHY link, addresses, connection count vs `NET_MAX_CONN` |
| `CONFIG_LOG_MODE_IMMEDIATE` | — | logs are not buffered; the last line before a fault is real |
| `CONFIG_ASSERT_VERBOSE` | — | assertion messages carry file and line |
| `CONFIG_THREAD_NAME` | — | thread names in analyzer and fault output |

`kernel thread stacks` is the single highest-value command here. Do not raise a
stack by guessing when the board will tell you its high-water mark.

---

## 5. Where a value actually lives

Three files, and the distinction matters — writing a value in the wrong one is
silently ignored.

| file | holds |
| --- | --- |
| `justfile`, `board-build` | **only** what the nros-zenoh snippet also sets: `MAIN_STACK_SIZE`, `HEAP_MEM_POOL_SIZE`, `SYSTEM_WORKQUEUE_STACK_SIZE`, and the four `NET_PKT`/`NET_BUF` counts |
| `src/zephyr_entry/boards/mr_canhubk3_s32k344.conf` | everything else — entity limits, executor and zenoh pools, net conn/context caps, the subscription buffer |
| `src/zephyr_entry/CMakeLists.txt` | compile definitions (`NROS_COMPONENT_*`, `NROS_ZEPHYR_*`) and the DTCM relocation |

**Why:** Zephyr merges `CONF_FILE` (prj.conf, board conf) *before*
`EXTRA_CONF_FILE`, and the nros-zenoh snippet rides in the latter. So
`MAIN_STACK_SIZE`, `HEAP_MEM_POOL_SIZE` and the four `NET_PKT`/`NET_BUF` counts
written into the board conf are **overwritten without warning**. They are passed
as `-DCONFIG_*` from the recipe, which lands in
`misc/generated/extra_kconfig_options.conf` — the one hook that merges last.

Everything the snippet does *not* set belongs in the board conf, which is where
board sizing belongs. That became possible for the whole sizing class only with
nano-ros #0749 and #0752.

If a Kconfig change appears to do nothing, check the resolved value first:

```sh
grep '^CONFIG_<NAME>' build-board/zephyr/.config
```

---

## 6. Current footprint

```
FLASH:  603,388 / 4,144,896   14.56%
RAM:    273,072 /   320 KB    83.33%     53 KiB free
DTCM:   100,680 /   128 KB    76.81%
ITCM:         0 /    64 KB     0.00%     idle, available
```

There is room. Raising a pool to get past a bring-up failure is the right call —
tune back down afterwards with a measurement, not before.

## 7. What is known-unvalidated

- **Nothing in this image has executed on silicon.** It builds, links and fits.
- The RNG is `TEST_RANDOM_GENERATOR` — timer-seeded, not cryptographic. Bench
  networks only; see [phase-4](roadmap/phase-4-link-security.md).
- `SUBSCRIBER_RING_DEPTH=4` is the nano-ros default, but the receive queue has
  never seen real traffic. Sample loss under burst is the symptom.
- Cyclone DDS on this part is untried. zenoh fits; that is all we know.
