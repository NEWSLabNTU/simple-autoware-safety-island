# Board bring-up triage — MR-CANHUBK344 (S32K344)

For the serial console at 2am. Symptom on the left, the knob and its file on the
right.

**Read this first:** the image fits 320 KiB because a dozen pools were cut to
measured need. Every one of those cuts is a hypothesis that has never executed on
silicon. When the board misbehaves, the cause is far more likely to be one of
these values than a logic bug in a node that already ran green on native and
native_sim.

**Second thing:** four of the failure modes below are **silent**. They do not
crash, log, or return an error you will see. Section 3 lists them; read it before
you conclude something "works".

---

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
| `CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE` | 4096 | board conf | |
| `NROS_ZEPHYR_TIER_STACK_SIZE` | 4096 | entry `CMakeLists.txt` | only if something spawns a tier; nothing should |

The watchdog is enabled (`CONFIG_WATCHDOG=y`, FS26 SBC). A reset loop with no
fault message may be the watchdog, not a crash.

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
| 5th node will not attach | `NROS_EXECUTOR_MAX_NODES` | 4 | **4 — no headroom** |

`MAX_NODES` is the one limit sized to exact need. If a node is ever added, this
fails first.

### Networking never comes up

`CONFIG_NET_CONFIG_INIT_TIMEOUT=30`. Check the PHY link first (`net iface` in the
shell — see §4), then the media converter, then:

| | current | snippet default |
| --- | ---: | ---: |
| `CONFIG_NET_MAX_CONN` | 4 | 8 |
| `CONFIG_NET_MAX_CONTEXTS` | 8 | 32 |
| `CONFIG_NET_PKT_{RX,TX}_COUNT` | 16 / 16 | 32 / 32 |
| `CONFIG_NET_BUF_{RX,TX}_COUNT` | 32 / 32 | 64 / 64 |

All in `justfile` `board-build` — **not** the board conf, see §5.

---

## 3. The silent failures — read this before declaring success

These produce no error. Everything looks like it is working.

**1. A subscription that never fires.**
`CONFIG_NROS_SUBSCRIPTION_BUFFER_SIZE=1024` (board conf). A serialized sample
larger than this is dropped at `try_recv` with `BUFFER_TOO_SMALL`, and the C++
arena dispatch path swallows the drop. The callback simply never runs.

Measured: `nav_msgs/Odometry` is the largest subscribed type at **~718 B** on the
wire with Autoware's `map` / `base_link` frame ids. A 255-char frame id would
cost 1208 B and break it. If one topic is dead while others work, check the
publisher's frame ids first.

Raising it also means recomputing `NROS_EXECUTOR_ARENA_SIZE`:
`max_cbs * (3 * rx_buf + 512) + 2048`. The two move together.

**2. Entities missing from `ros2 node list`.**
`CONFIG_NROS_MAX_LIVELINESS=32` against 29 tokens — one per node, per publisher
*and* per subscriber (4 + 14 + 11). On exhaustion `zpico_declare_liveliness`
returns `ZPICO_ERR_FULL` and the shim discards it with `.ok()`. The entity
publishes and subscribes perfectly and is invisible to every ROS 2 tool.

If the graph looks short but data flows, this is why — not a discovery problem.

**3. A rebuild that quietly changes the image.**
Only knobs with a `_nros_resolve_knob` row are baked into `build.ninja`. These
five are **not**, and reach `build.rs` only from the environment of the shell
running ninja:

```
NROS_EXECUTOR_ARENA_SIZE   NROS_RMW_SUBSCRIBER_SLOTS
ZPICO_SUBSCRIBER_RING_DEPTH   ZPICO_MAX_LARGE_SUBSCRIBERS   ZPICO_SUBSCRIBER_LARGE_SIZE
```

`cd build-board && ninja`, or `west build -d build-board` from a plain shell,
rebuilds them at crate defaults. Most of that overflows RAM and fails loudly —
but `NROS_RMW_SUBSCRIBER_SLOTS` drops 12 → 8 silently and re-breaks the 9th
subscription.

**Always build with `just board-build`.**

**4. A relocation that relocated nothing.**
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
| `justfile`, `board-build` | anything the **nros-zenoh snippet also sets**, and every `ZPICO_*` / `NROS_EXECUTOR_*` env knob |
| `src/zephyr_entry/boards/mr_canhubk3_s32k344.conf` | board-only Kconfig the snippet does not touch |
| `src/zephyr_entry/CMakeLists.txt` | compile definitions (`NROS_COMPONENT_*`, `NROS_ZEPHYR_*`) and the DTCM relocation |

**Why:** Zephyr merges `CONF_FILE` (prj.conf, board conf) *before*
`EXTRA_CONF_FILE`, and the nros-zenoh snippet rides in the latter. So
`MAIN_STACK_SIZE`, `HEAP_MEM_POOL_SIZE` and the four `NET_PKT`/`NET_BUF` counts
written into the board conf are **overwritten without warning**. They are passed
as `-DCONFIG_*` from the recipe, which lands in
`misc/generated/extra_kconfig_options.conf` — the one hook that merges last.

If a Kconfig change appears to do nothing, check the resolved value first:

```sh
grep '^CONFIG_<NAME>' build-board/zephyr/.config
```

---

## 6. Current footprint

```
FLASH:  600,236 / 4,144,896   14.48%
RAM:    273,072 /   320 KB    83.33%     53 KiB free
DTCM:    98,264 /   128 KB    74.97%
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
