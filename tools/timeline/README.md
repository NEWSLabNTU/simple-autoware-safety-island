# tools/timeline - the live timeline (phase 8, unit W7)

One JSON Lines event stream (`t_mono_ns`, `source`, `kind`, `hazard`,
`rung`, `marker`, `value`) fed by the contract-generated probe and logger,
the availability gate and scenario controller, and the island's trace
markers (a play_launch observer log dropped into the run directory is read
too; the W7 runs used none); a pyqtgraph live drawer and a matplotlib
renderer that draw the same files. Declared bars come from the checker's
arithmetic (`play_launch check --explain`); observed edges from events.
Design: `docs/roadmap/phase-8-rtss-work-demo.md`, D7. Results:
`docs/takeover-trace.md`.

## The pieces

| file | what it is |
|---|---|
| `tlcommon.py` | the event schema (module doc), the JSONL writer and tailer, the declared side (resolved SystemModel, the contract sidecar's `when:`/`window:`/`exit:`/`entry_speed`, the `--explain` table parser), the braking-profile arithmetic; `selftest` for CI |
| `probe.py` | the probe and logger: subscribes to every topic named in a `when:` (types from the resolved model), writes a `predicate` event on each change of truth, plus the samples the lanes and the alignment need |
| `scenario.py` | `gate`: execs the availability gate, `demo/host_ws/src/availability_gate` (C++, phase8-W16; Autoware's availability on `.../availability_raw` republished at 10 Hz on `/system/operation_mode/availability` with `autonomous &= !odd_exit`); `press <button>` / `buttons` (a window): odd-exit, odd-enter, takeover (MANUAL via `/control/control_mode_request`), hpc-loss (SIGSTOP the gate), hpc-restore; `run a\|b\|encore`: the whole act, scripted, one VERDICT |
| `merge.py` | island trace markers onto host CLOCK_MONOTONIC: coarse offset from anchor 1, refined on every publish/receipt pair, checked by anchor 2 (the W3 method, docs/reaction-trace.md) |
| `analysis.py` | declared against observed for one run: the edges, the observed terms, one verdict per declared bar, the rung the run ended on, the longest availability gap (the `hpc_alive` precondition) |
| `render.py` | the static PNG of a run for the slides, and `--table` (markdown) |
| `timeline.py` | the booth view: pyqtgraph, tails the run directory at 20 Hz; a rung turns red when its dwell passes the checker's `ends within` (window + the first hop of the route below, phase8-W12); the entry-speed flag |
| `run-native.sh` | one traced native_sim run with Autoware, everything above, into `build/timeline/<id>/` |
| `run-board.sh` | one traced act with the island off the host (phase8-W17): `--target board` flashes the ELF with pyocd, starts the gateway on the UART (`just l3-peer`), resets, waits for the island, starts Autoware in the container, the gate, the probe and the act, reads the trace over SWD, and merges and analyses into `build/timeline/<id>/` as `run-native.sh` does; `--target qemu` does the same against the QEMU island behind the same gateway config (island face on a unix socket) and reads over the QEMU monitor; `--dry-run` prints the steps. The board steps ran on the S32K344 in phase8-W8 (docs/takeover-trace.md section 9; `just l3-traced-act`) |
| `readout.py` | the island's RAM trace buffer and counters off a running target, every address from the ELF: pyocd over SWD on the board (phase8-W8), the QEMU monitor on QEMU; wraps the buffer in the native_sim dump's header |
| `testdata/explain.txt` | the checker's settle-derived lines and budget table for the live contract (play_launch phase 84, phase8-W12), for `tlcommon.py selftest` |

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
tools/timeline/run-native.sh a|b|encore <id>      # -> build/timeline/<id>/
python3 tools/timeline/render.py build/timeline/<id> --table
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
- `tlcommon.PLAY_LAUNCH_W6` is a local fallback path to a source-built
  play_launch; set `PLAY_LAUNCH_CHECK` elsewhere.
