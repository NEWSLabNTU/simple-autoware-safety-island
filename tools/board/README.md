# tools/board - the board tooling

What the island repo needs to read and drive the board and to check its
contract: the event schema and the declared side (`tlcommon.py`), the SWD
readers (pyocd, attach without halting unless a tool says otherwise), the
contract probe, and the console stamp. The evaluation (the timeline, the
acts, the analysis, the run scripts) is `rtss-work-2026-demo:tools/eval/` and imports
`tlcommon` from here.

| file | what it is |
|---|---|
| `tlcommon.py` | the event schema (module doc), the JSONL writer and tailer, the declared side (resolved SystemModel, the contract sidecar's `when:`/`window:`/`exit:`/`entry_speed`, the `--explain` table parser), the braking-profile arithmetic; `selftest` for CI |
| `probe.py` | the probe and logger: subscribes to every topic named in a `when:` (types from the resolved model), writes a `predicate` event on each change of truth, plus the samples the lanes and the alignment need |
| `terms.py` | the board budget terms over a round of runs (link, tick spacing, in-tick work, the velocity limit on the expiry tick, ...; phase8-W30, moved here from the W30 re-analysis directory); `--propose` applies the measurement rule and prints each budget: max x 1.2 rounded up to the next ms, the timer period without margin (tick = period + lateness x 1.2), call_mrm = tick + work (phase10-B4) |
| `readout.py` | the island's RAM trace buffer and counters off a running target, every address from the ELF: pyocd over SWD on the board (phase8-W8), the QEMU monitor on QEMU; wraps the buffer in the native_sim dump's header |
| `testdata/explain.txt` | the checker's settle-derived lines and budget table for the live contract (play_launch phase 84, phase8-W12), for `tlcommon.py selftest` |
| `violations.py` | the island's runtime contract violations and the supervisor's record over SWD (phase9-W4; route 3, the floor, and the vehicle-side fault since phase15-S2); `just priority-check` reads the derived priorities through it; the overrun, spin-stall and (phase15-S4, the island-floor-inject image only) floor-inject debug hooks; `selftest` decodes a synthetic record and, with `--elf`, checks the record's size against its layout |
| `board_buttons.py` | SW1/SW2 over SWD (CONFIG_ISLAND_BUTTONS): `watch` (`just board-buttons`) and `inject` |
| `led_readout.py` | the island's LED state and its last transitions over SWD (CONFIG_ISLAND_LED) |
| `lock_probe.py` | read and decode island_lock_probe_record (CONFIG_ISLAND_LOCK_PROBE, nano-ros RFC-0108) |
| `spin_diag.py` | DIAG (spin latency, phase9-U3): read and decode `island_spin_diag` over SWD |
| `stamp.py` | host CLOCK_MONOTONIC stamps on the island's console lines (phase8-W29) |

## Selftest

`python3 tools/board/tlcommon.py selftest` (CI): the `--explain` table
parser and the braking-profile arithmetic against
`testdata/explain.txt`, every row's terms summing to its total.

## Dependencies

Python 3.10 and PyYAML; pyocd and pyelftools for the SWD readers; ROS 2
Humble and the Autoware 1.5.0 messages for `probe.py`. The declared side
needs a play_launch that parses the contract (`PLAY_LAUNCH_CHECK=<path>`
to choose one) and `just sync` for the resolved model.
