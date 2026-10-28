# experiments/spin-latency - the spin-latency diagnostic

How the executor's late spins on the S32K344 were measured (phase-9 roadmap,
section 6; nano-ros phase-474 I10-I16) and how to measure them again. None
of this is in the normal image: the diagnostic needs two patches that are
not for merge, applied only for the length of one build.

## The pieces

| file | what it is |
|---|---|
| `nano-ros-diag.patch` | nano-ros: spin-phase events (event 40, `phase \| value << 8`) and the zenoh mutex-wait hook the diag reads |
| `zenoh-pico-diag.patch` | zenoh-pico: the serial ISR's time inside the longest callback, from zenoh-pico's own counters |
| `build-diag.sh` | `just board-build-diag`: applies both patches, builds into `build-board-diag/` with `CONFIG_ISLAND_SPIN_DIAG=y` and `CONFIG_NROS_ZENOH_SERIAL_ISR_STATS=y` (as `-D`, through board-build's `ISLAND_BOARD_KCONFIG`; the tracked board conf is not edited), reverts both patches from an EXIT trap |
| `late_records.py` | one line per late interval of a decode (the ring of intervals at least 2 ms late): segments, lock waits, longest callback, other threads |
| `swd_where.py` | one SWD halt: PC, LR, SP, xPSR, the fault status registers, and whether the heartbeat moves after resume |
| `swd_stackwalk.py` | halt, read 8 KiB above SP, name every word that looks like a Thumb return address (found the C4 assert recursion) |
| `../../tools/board/spin_diag.py` | reads and decodes `island_spin_diag` over SWD (attach, no halt) |
| `../../tools/eval/run-diag.sh` | `just diag-run`: one board act (default encore) with `spin_diag.py read` just before and just after the act |
| `../../tools/eval/actseg.py` | `just diag-actseg`: late spins inside the act only (act read minus pre read) |
| `../../scripts/ienv.sh` | runs a command in the checkout under `env -i` plus scripts/env.sh |

## Use

```
just board-build-diag                         # -> build-board-diag/zephyr/zephyr.elf
just diag-run sl-x1                           # flashes the diag ELF, one encore -> build/timeline/sl-x1/
just diag-actseg sl-x1 --survival             # the act segment, and the per-ms curve
just board-flash                              # the normal image back on the board
```

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
segment is the act read minus the pre read.

## The B2 numbers, regenerated

The deck's spin-latency figure (per-byte interrupt against the FIFO
watermark) plots these two runs; from this tree:

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
