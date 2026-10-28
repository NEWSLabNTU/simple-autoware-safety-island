# tools/eval - the evaluation: the live timeline and the acts (phase 8, unit W7)

One JSON Lines event stream (`t_mono_ns`, `source`, `kind`, `hazard`,
`rung`, `marker`, `value`) fed by the contract-generated probe and logger,
the availability gate and scenario controller, and the island's trace
markers (a play_launch observer log dropped into the run directory is read
too; the W7 runs used none); a pyqtgraph live drawer and a matplotlib
renderer that draw the same files. Declared bars come from the checker's
arithmetic (`play_launch check --explain`); observed edges from events.
Design: `docs/roadmap/phase-8-rtss-work-demo.md`, D7. Results:
`docs/takeover-trace.md`.

The board half (the event schema and the declared side in `tlcommon.py`,
the SWD readers, the probe) is `tools/board/` (its README); everything here
imports `tlcommon` from there. This half leaves with the evaluation
(phase 14, P2). `python3 tools/eval/selftest.py` runs both halves'
selftests (CI).

## The pieces

| file | what it is |
|---|---|
| `scenario.py` | `gate`: execs the availability gate, `demo/host_ws/src/availability_gate` (C++, phase8-W16; Autoware's availability on `.../availability_raw` republished at 10 Hz on `/system/operation_mode/availability` with `autonomous &= !odd_exit`); `press <button>` / `buttons` (a window): odd-exit, odd-enter, takeover (MANUAL via `/control/control_mode_request`), hpc-loss (SIGSTOP the gate), hpc-restore; `run a\|b\|encore`: the whole act, scripted, one VERDICT |
| `merge.py` | island trace markers onto host CLOCK_MONOTONIC: coarse offset from anchor 1, refined on every publish/receipt pair, checked by anchor 2 (the W3 method, docs/reaction-trace.md) |
| `analysis.py` | declared against observed for one run: the edges, the observed terms, one verdict per declared bar, the rung the run ended on, the longest availability gap (the `hpc_alive` precondition); a row per declared `max_transport` edge the trace observes (phase10-B8); the settle at the observed entry speed, its difference from the profile as the measured response delay, and profile + `response` once declared (phase10-B2); each row's `checked by` (checker sum, runtime monitor, trace) |
| `render.py` | the static PNG of a run for the slides, and `--table` (markdown) |
| `timeline.py` | the booth view: pyqtgraph, tails the run directory at 20 Hz; a rung turns red when its dwell passes the checker's `ends within` (window + the first hop of the route below, phase8-W12); the entry-speed flag |
| `run-native.sh` | one traced native_sim run with Autoware, everything above, into `build/timeline/<id>/` |
| `run-board.sh` | one traced act with the island off the host (phase8-W17): `--target board` flashes the ELF with pyocd, starts the gateway on the UART (`just l3-peer`), resets, waits for the island, starts Autoware in the container, the gate, the probe and the act, reads the trace over SWD, and merges and analyses into `build/timeline/<id>/` as `run-native.sh` does; `--target qemu` does the same against the QEMU island behind the same gateway config (island face on a unix socket) and reads over the QEMU monitor; `--dry-run` prints the steps. A preflight before flashing (phase9-U5, C6: host overlay, model freshness, no `sai-l3*` container, the probe free, the tty free with a bounded `fuser`, the 1-min load under `RB_LOAD_MAX`) refuses with one `REFUSED <reason>` line and exit 3; the load is checked again at the act; a run without its probe or gate reads `VERDICT: VOID` (exit 4); docs/tracing.md has the table. The board steps ran on the S32K344 in phase8-W8 (docs/takeover-trace.md section 9; `just l3-traced-act`) |
| `run-diag.sh`, `actseg.py` | DIAG (spin latency, phase9-U3; the SWD reader `spin_diag.py` is in tools/board): one act on the diag image (`just board-build-diag`) with the diag read before and after the act (`just diag-run`); the late spins of the act segment (`just diag-actseg`). experiments/spin-latency/README.md |

## Dependencies

Python 3.10, PyYAML, matplotlib and numpy (Ubuntu 22.04 packages:
`python3-yaml python3-matplotlib python3-numpy`), pyqtgraph with PyQt5 for
the live view (`python3-pyqt5`, and `pip install --user --no-deps
"pyqtgraph<0.14"`: 0.14 pulls numpy 2, which breaks the system matplotlib
built against numpy 1.21). The probe, the gate and the scenario need ROS 2
Humble and the Autoware 1.5.0 messages sourced (`scripts/env.sh`); merge.py
needs `src/safety_island_tracing/island_trace.py`. The declared side needs a
play_launch that parses rlm v0.1.46 (92043c82 or later: nano-ros's vendored
pin after PR 1394, or `PLAY_LAUNCH_CHECK=<path>`), and `just sync` for the
resolved model.

## Use

One run, scripted (Autoware, the traced native_sim island, gate, probe, act):

```
tools/eval/run-native.sh a|b|encore <id>      # -> build/timeline/<id>/
python3 tools/eval/render.py build/timeline/<id> --table
```

By hand, one terminal each, into one run directory (default
`build/timeline/live`); Autoware must be launched with
`operation_mode_availability_topic:=/system/operation_mode/availability_raw`:

```
just l3-scenario gate       # the availability gate
just l3-probe               # the probe and logger
just l3-timeline            # the live view; `just l3-timeline <dir> <file.png>` renders instead
just l3-scenario buttons    # ODD exit / driver takes over / HPC loss
```

A run directory holds `probe.jsonl`, `gate.jsonl`, `scenario.jsonl`,
`island.jsonl` (merged markers), `explain.txt`, `island.trace` (+ `.meta`,
`.log`, `.check.txt`), `timeline.png` and `table.md`.

## Caveats

- On native_sim island durations are simulated time; a callback takes zero
  time (docs/takeover-trace.md, the first paragraph).
- The gate is the C++ node `availability_gate` (phase8-W16), built by
  `just demo-host-ws` and started through its `gate-rt` wrapper (SCHED_FIFO
  when `ulimit -r` allows; it is 0 for this user, so SCHED_OTHER). W7's
  rclpy gate went silent for 250-1134 ms on a loaded host because its
  executor thread blocked in file writes (docs/takeover-trace.md, section
  7); the C++ gate does no file I/O on that thread and held its largest
  publish gap under 150 ms for 10 min at load 100-130. It still logs
  `stall` events (timer or raw stream more than GATE_STALL_MS late) and a
  `stats` event with its largest publish gap at exit.
- `PLAY_LAUNCH_CHECK` names the play_launch the checker reads run under
  (default: `play_launch` on PATH).
