# tools/diag - the spin-latency diagnostic

How the executor's late spins on the S32K344 were measured (phase-9 roadmap,
section 6; nano-ros phase-474 I10-I16) and how to measure them again. None
of this is in the normal image: the diagnostic needs two patches that are
not for merge, applied only for the length of one build.

## The pieces

| file | what it is |
|---|---|
| `nano-ros-diag.patch` | nano-ros: spin-phase events (event 40, `phase \| value << 8`) and the zenoh mutex-wait hook the diag reads |
| `zenoh-pico-diag.patch` | zenoh-pico `src/link/transport/serial/uart_zephyr.c`: the serial TX-wait hook (the sender's sleep for ring room, one site for both the interrupt-driven and the `UART_ASYNC` DMA path) and the TX-lock wait hook, both reported through `island_diag_lock_wait` |
| `build-diag.sh` | `just board-build-diag`: applies both patches, builds into `build-board-diag/` with `CONFIG_ISLAND_SPIN_DIAG=y` and `CONFIG_NROS_ZENOH_SERIAL_ISR_STATS=y` (as `-D`, through board-build's `ISLAND_BOARD_KCONFIG`; the tracked board conf is not edited), reverts both patches from an EXIT trap |
| `late_records.py` | one line per late interval of a decode (the shared ring of intervals at least 2 ms past their park bound, and each level's worst): level, segments, lock waits, longest callback, other threads |
| `swd_where.py` | one SWD halt: PC, LR, SP, xPSR, the fault status registers, and whether the heartbeat moves after resume |
| `swd_stackwalk.py` | halt, read 8 KiB above SP, name every word that looks like a Thumb return address (found the C4 assert recursion) |
| `../board/spin_diag.py` | reads and decodes `island_spin_diag` over SWD (attach, no halt); `segment <run dir>` prints the act segment per level; `selftest` checks it against the blob of `tests/spin_diag` |
| `../../tests/spin_diag/` | the recorder (`island_spin_diag.h`) on the host against a fake clock and threads, two levels interleaved (`just supervisor-test`, CI) |
| `../eval/run-diag.sh` | `just diag-run`: one board act (default encore) with `spin_diag.py read` just before and just after the act |
| `../eval/actseg.py` | `just diag-actseg`: late spins inside the act only (act read minus pre read) |
| `../../scripts/ienv.sh` | runs a command in the checkout under `env -i` plus scripts/env.sh |

## Where the hooks are (nano-ros pin 27d1c571da)

The five phases, emitted from `Executor::pass`, its preludes and its two
band returns in `packages/core/nros-node/src/executor/spin.rs` (one pass is
one `spin_once`, `spin_once_shared` or, phase-509, `spin_band_once`: the
image's mrm_handler and emergency operator levels are band workers on
their own threads over the one executor, the comfortable operator's level
is the executor's own worker on `main`):

| phase | value | where |
|---|---|---|
| 0 | 0 | `pass` entry, before `reap_deferred_releases` (every pass: owned, shared, band) |
| 1 | the park bound, us | owner: `owned_prelude`, after `park_can_be_woken`, before the handle park and the park primitive. Band: `band_prelude`, before the waiter's park; the band's bound (its next timer, at most the timeout), 0 when it does not park (an arrival is pending); a band with no waiter polls and emits no phase 1 |
| 2 | 0 | owner: `owned_prelude`, after the primary and the extra sessions' drive. Band: `band_prelude`, after the park, before the level's check-in |
| 3 | 1 = idle, 0 = dispatched | owner: idle return, before `flush_violation_reports`; dispatch path, before `check_timer_overruns`. Band: both band returns, before `tick_components` |
| 4 | 1 = idle, 0 = dispatched | owner: idle return, before `return`; dispatch path, after `tick_components`, before `result`. Band: both band returns, after `tick_components` |

A yielded park (phase-521 W8, `park_yielded`) returns between phase 2 and 3
and closes no interval cleanly; the island's levels are k_threads and do not
yield.

**Which zenoh-pico tree.** nano-ros resolves zenoh-pico at configure time
(`nros locate zenoh-pico --why`): a clean submodule at its pin loses to the
shared store copy `~/.nros/sources/zenoh-pico/<pin>`, which is what a normal
build-board compiles, and a dirty submodule (the local-edit rung) outranks
the store. `build-diag.sh` patches the checkout's submodule, so the store,
shared by every checkout, is never edited; west reconfigures on every
board-build, so the ladder is asked again with the patch applied, and the
script fails the build unless `build-board-diag/compile_commands.json`
names the submodule's `uart_zephyr.c` (and nano-ros's
`zephyr/nros_zenoh_zephyr_system.c`).

## What is measured (island #14)

**Every executor level, apart.** The image runs one executor per derived
sched task (mrm_handler 100 ms, the emergency operator 33.3 ms, the
comfortable operator 100 ms, `build-board/nros_priority_plan.json`), each
on its own thread: the first two are phase-509 band workers
(`derived-mrm_handler`, `derived-mrm_emergency_stop_operator`), the third
is the executor's own worker on `main`. Every thread that emits phase 0 becomes a level, in the
order the levels first spin, up to `SD_LEVELS` (4; a thread past that is
counted in `lev_dropped` and not followed). Each level keeps its own spin count,
lateness histogram (1 ms bins, 40), late count, worst lateness, park bound
range, segment maxima and worst record; the ring of the latest 48 late
records is shared and every record names its level. Callback, take and
lock-wait events are charged to the level of the thread that emits them;
a lock wait of a thread that is not a level goes to every level's interval
under way ("other lock waits").

**Lateness against the interval's own park bound.** An interval is one
`spin_once` entry (phase 0) to the next of the same thread; phase 1 carries
the bound the pass parked on (`park_achieved_us`: the time to its next wake,
the release grid point, a timer or a session deadline). Then

    late = interval - park_bound      (0 if the interval ran shorter)

the time the interval ran past the wake it planned: the prelude before the
park, the overshoot of the park itself, the dispatch, the rules and the
caller's loop. An idle interval of a 100 ms level that parks 85 ms and
returns 1 ms after its wake reads 1 ms late, as a 10 ms executor's idle
spin did against 10 ms in B2. An interval woken early by an arrival runs
shorter than its bound and reads 0. An interval with no phase 1 (a pass that
returned before the park) has no bound: counted as `nobound`, not judged,
not in the histogram. "Late" is still at least 2 ms (`SD_LATE_US`); the
histogram, `>=1ms` included, is over the judged intervals. The 1 ms bin is
expected to be full: the park rounds up to whole ms and a Zephyr timeout
of N ticks (1000 Hz here) wakes on the tick after N, so an interval that
ran no work past its wake still reads 0-1 ms (about half of every level's
intervals in d14-e2 below); at least 2 ms is time the level lost past
that.

**Cost.** `island_spin_diag` is 11,124 B (9,412 B with one thread) and
the per-level working state `sd_lv` 4 x 488 B plus a 128 B scratch (one
~600 B set before), all in SRAM .bss (0x2042xxxx, outside the DTCM
relocation): the diag image's RAM is 276,184 of 327,680 B, about +3.2 KiB
over the SDG1 recorder, and its DTCM line is the normal image's, 117,984 B
(13,088 B free, the 8 KiB guard of linker/dtcm-headroom.ld untouched).
Shared state (the thread table and the ring) is filed under
`k_sched_lock`, so a level preempted while it files an interval cannot
have its record torn by another level.

**The readout.** `spin_diag.py decode` prints first the sum over the
levels (the `spins=` and `lateness histogram` lines,
`rtss-work-2026-demo:tools/eval/actseg.py` reads them, so its counts are
all levels together), then one block per level:

```
level 1 derived-mrm_eme(p5): spins=... judged=... nobound=... late(>=2ms)=... max_late_us=... park_bound_us=min..max interval_max_us=...
level 1 lateness (ms bin: count): 0:... 1:...
level 1 segment max wall us: ...
```

then every level's `WORST` and the ring, each record tagged `lvl=<thread
name>` (Zephyr keeps 15 characters of it). `spin_diag.py segment <run dir>`
is the act segment per level (act read minus pre read: spins, judged,
`>=1ms`, `>=2ms`, worst lateness inside the act, the bound range, the act's
histogram). An SDG1 blob (before #14) is refused with the island commit that
decodes it.

**First numbers (d14-e2).** Planning-sim encore, PASS, the
diag image of this tree, `spin_diag.py segment <run dir>`:

```
level                               spins judged  >=1ms  >=2ms   worst late park bound us (boot)  lateness ms bins (act)
derived-mrm_eme(p7)                  1328   1328    697     25       3336us             0..33000  0:631 1:672 2:24 3:1
main(p8)                              462    462    258     11       3470us          1000..86000  0:204 1:247 2:10 3:1
derived-mrm_han(p5)                  1951   1951    229      8       2422us            0..100000  0:1722 1:221 2:8
```

(`main` is the comfortable operator's level.) The late intervals are the
park overshooting while a higher level or zpico_exec runs (`S1` charged to
other threads), and the emergency operator's 2.9 ms dispatch of slot 4.

## Use

```
just board-build-diag                         # -> build-board-diag/zephyr/zephyr.elf
just diag-run sl-x1                           # flashes the diag ELF, one encore -> build/timeline/sl-x1/
just diag-actseg sl-x1 --survival             # the act segment, all levels summed, and the per-ms curve
python3 tools/board/spin_diag.py segment build/timeline/sl-x1   # the act segment per level (from the demo checkout)
just board-build && just board-flash         # the normal image back on the board
```

`board-build` before `board-flash`: the diag build patched and reverted
the shared nano-ros sources, so `board-flash`'s own west rebuild of
build-board runs, outside the recipe's arguments, and fails its DTCM link
(seen: "region `DTCM' overflowed by 18336 bytes").

`board-build-diag` takes extra Kconfig lines (`just board-build-diag
CONFIG_NROS_ZENOH_SERIAL_FIFO_WATERMARK=1`) and the build dir from
`BOARD_DIAG_BUILD_DIR`. It refuses a tree that already carries a patch
(a run killed by SIGKILL is the only way to leave one; `just doctor` warns
about it too) and prints the `git apply -R` that reverts it. Do not run a
normal `just board-build` in the same checkout while it builds.

`diag-run` passes everything to run-board.sh except the act and `--elf`
(default the diag ELF); the act is run-board.sh's own default `RB_ACT`
(`scenario.py run <act> --log <dir>/scenario.jsonl`) with the two reads
around it, and its exit status is the act's. Check `docker ps` and
`pgrep -af run-board` first; run-board.sh takes the demo lock itself.

## Why the act segment

The whole-run counts mislead: the diagnostic counts from boot, a run idles
for minutes before its act (`sl-rclcpp-prio` idled 10 min), and the same
image varies 11-77 late spins per 10k run to run over whole runs. The act
segment is the act read minus the pre read (`spin_diag.py segment`, per
level).

## The B2 numbers, regenerated

The spin-latency comparison (per-byte interrupt against the FIFO
watermark) is these two runs, taken with the SDG1 recorder (one executor
at a 10 ms spin, lateness against 10 ms); from this tree:

```
$ just diag-actseg <runs>/sl-i13 <runs>/sl-i14w1 --survival
run              act spins  >=1ms  >=2ms  /10k>=1  /10k>=2 worst bin isr us/call isr cpu s
sl-i13                5779     61     35    105.6     60.6       6ms        6.21      4.46
sl-i14w1              6019      0      0      0.0      0.0       0ms        2.94      0.85
survival sl-i13: 1:61(105.6) 2:35(60.6) 3:13(22.5) 4:6(10.4) 5:2(3.5) 6:1(1.7)
survival sl-i14w1: none late
```

(`<runs>` = the island-rclcpp worktree's build/timeline, where the runs
were taken.) `isr us/call` and `isr cpu s` are cumulative from boot at the
act read, 160 MHz core.
