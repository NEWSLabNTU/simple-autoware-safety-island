# Phase 14 - split the repo: the island here, the evaluation elsewhere

**Goal:** this repo holds the safety island and nothing else: the MRM chain
port, its bringup and contract, the board entries, the board tooling and the
board docs. The RTSS@Work 2026 evaluation (the L3 container, the CARLA booth
demo, the acts, the experiment runs, the figures) moves to a new private repo,
`NEWSLabNTU/rtss-work-2026-demo`, which consumes this one as a submodule.
Write-ups and slides leave with it. The legacy Cyclone demo is retired.

**Status (2026-10-29): P0-P3 done; the P2.4 board act is open (below).** Decisions taken:

- **History is kept.** Paths leave the tree, not the history; nothing is
  rewritten or force-pushed.
- **New repo:** `NEWSLabNTU/rtss-work-2026-demo`, private. It carries the
  moved paths with their history (`git filter-repo` on a fresh clone).
- **The CARLA booth demo** goes with the evaluation.
- **The legacy Cyclone demo** (last validated 2026-07-31) is retired, not moved.
- **An `autoware-safety-island` contribution** (an MRM module in that repo's
  layout) is planned after this phase, as its own phase. Nothing here depends
  on it.

## What the repo holds today

| Strand | Paths | Fate |
|---|---|---|
| Island core | `src/*`, `patches/zephyr`, `scripts/`, `CMakeLists.txt`, `nros-*`, the build and board parts of `justfile` and `just/`, the board docs | stays |
| July port leftovers | `record.json`, `demo/README.md`, `docs/topic-contract.md`, `demo/cyclonedds.xml`, `demo/map` (29 MB, the same bytes as `autoware-safety-island`'s copy), the legacy demo recipes | deleted (P0, P2) |
| Evaluation | `demo/l3`, `demo/carla`, `demo/host_ws`, `demo/scenario_driver.py`, `experiments/*`, the evaluation half of `tools/timeline`, `just/l3-demo.just`, `just/carla.just`, `docs/demo-l4`, `docs/island-variants`, `docs/takeover-trace*`, `docs/design/carla-island-demo.md`, `docs/roadmap/phase-6..9` | moves (P2) |
| Write-ups | `slides/`, `docs/writeup/`, `docs/dx-ux-gaps-2026-10.md`, `docs/design/rtss-work-2026/` | moves (P3) |

## Couplings cut before the move

1. `tools/timeline` serves both sides: the board side (SWD readout,
   `violations.py` behind `just priority-check`, the CI selftest) and the
   evaluation (render, merge, analysis, `run-board.sh`).
2. Live config lives under `experiments/`: `serial-interop/router-serial.json5`
   (used by `just/board-peer.just` and `just/emulation.just`) and
   `spin-latency` (the diagnostic image and a doctor check).
3. `demo/scenario_driver.py`, `demo/host_ws` and `demo/map` are shared by the
   legacy demo, the L3 container and CARLA.
4. The CI table names paths of every strand (`demo/l3`, `docs/demo-l4`,
   `docs/island-variants`).
5. The root `justfile` imports every `just/*.just` unconditionally.
6. Docs link across strands (README, `demo-runbook.md`, phase docs).

## Units

**P0. Clean up in place** -- done (2026-10-29)

Status: `record.json`, `demo/README.md` and `docs/topic-contract.md` are
gone; the topic contract is the `topics:` section of
`safety_island.contract.yaml`. Live code names no `/home/aeon` or
`/mnt/evo` path (`CSB_DIR` defaults to a sibling checkout, `CAST_DIR` to
`build/casts`, `PLAY_LAUNCH_WHEELHOUSE` names a wheelhouse); captured tool
output and dated run logs keep theirs. `demo/map` is gitignored and fetched
by `demo/fetch-map.sh` (`just demo-map`, also run by `just setup`,
`_svc-sim`, `run-native.sh`, `l3-container` and the L3 host run) from
NEWSLabNTU/autoware-safety-island@6998300c with a sha256 per file; the
four files were byte-identical to that commit's.

- P0.1 Delete `record.json`, `demo/README.md`, `docs/topic-contract.md`;
  repoint their links.
- P0.2 Drop the hard-coded `/home/aeon` and `/mnt/evo` paths
  (`tools/timeline/tlcommon.py`, `just/carla.just`, `docs/demo-l4`).
- P0.3 `demo/map` becomes a pinned download (URL plus checksum, fetched by a
  recipe into an ignored directory) instead of tracked bytes.

**P1. Re-layout in this repo** -- done (2026-10-29)

Status: `tools/board/` holds tlcommon, readout, violations, board_buttons,
led_readout, lock_probe, probe, stamp, terms, spin_diag and
`testdata/`; `tools/eval/` holds analysis, render, merge, timeline,
scenario, scenario_driver, actseg, diaggraph, led_vs_trace, run_summary
and the `run-*.sh`. Eval modules put `tools/board` on `sys.path`; no
board module imports an eval one. Selftests: `tools/board/tlcommon.py
selftest` and `tools/eval/selftest.py` (runs the board one first); CI runs
both. `config/router-serial.json5`; `tools/diag/` holds build-diag.sh,
the two diag patches, the SWD scripts and late_records.py. The contract
table is `EXPECT_CORE` (src/) and `EXPECT_EVAL`, picked by
`CONTRACTS=core|evaluation|all`, two CI steps; `just contract-check` (was
`l3-check`, kept as an alias) runs it locally. `just/l3-demo.just` and
`just/carla.just` are `import?`; `diag-run` and `diag-actseg` moved into
`just/l3-demo.just`. Left for P2: the legacy recipes in the root justfile
(`_scenario`, `_svc-sim`, `demo-map`) still call into `demo/` and
`tools/eval/` and go with the legacy demo's retirement; tools/diag's README
names the eval act runners.

- P1.1 `tools/timeline` splits into `tools/board/` (readout, violations,
  buttons, LED, lock probe, probe, `tlcommon`, stamp, terms) and `tools/eval/`
  (render, merge, analysis, acts, `run-*.sh`, summaries). Each half has its
  own selftest; the board half's runs in this repo's CI.
- P1.2 `experiments/serial-interop/router-serial.json5` moves to `config/`;
  the spin-latency diagnostic (`build-diag.sh`, its patches, the SWD scripts)
  moves to `tools/diag/`.
- P1.3 `scenario_driver.py` moves out of `demo/` next to its users.
- P1.4 The CI table splits into a core list and an evaluation list.
- P1.5 The root `justfile` imports evaluation modules optionally
  (`import?`), so removing them leaves `just` working.

**P2. Extract the evaluation** -- done (2026-10-29), except the P2.4 act

Status: `NEWSLabNTU/rtss-work-2026-demo` (private) is a `git filter-repo`
of a fresh clone at a657ac3 down to the evaluation and write-up paths,
current and pre-move (`tools/timeline/<eval files>`,
`demo/scenario_driver.py`), 225 commits; layout unchanged (`demo/l3`,
`demo/carla`, `demo/host_ws`, `tools/eval`, `experiments/`, `just/`,
`docs/...`). It holds this repo as `third-party/safety-island`, and its
root justfile imports `just/l3-demo.just` and `just/carla.just` and loads
this repo's justfile as the optional module `island` (`just
island::board-build`). `tools/eval` reads `tools/board`, `scripts/`, `src/`
and the build trees from the submodule (`tl.ROOT` is the island; run
directories stay in the demo repo); the contract launch files take the
island's parameter files from it. Its CI (play_launch 0.20.2) runs the
evaluation contract check (the old `EXPECT_EVAL`, 15 contracts) and the
evaluation selftest. `run-native.sh` did not move: it ran on the legacy
demo's recipes. `demo/fetch-map.sh` moved (its users are the L3 recipes).
Here: the moved paths are deleted, `.github/check-contracts.sh` checks
`src/` only, the `import?` lines are gone, and docs and comments cite moved
files as `rtss-work-2026-demo:<path>`. The legacy Cyclone demo is retired:
its recipes (`autoware`, `island`, `demo`, `demo-all`, `demo-down`,
`topics`, `demo-host-ws`, `demo-map`, `trace-demo`), `demo/cyclonedds.xml`,
the overlay and `CYCLONEDDS_URI` in `scripts/env.sh`, the `SAI_DEMO_RUN`
marker and its test, the README and runbook sections. `src/` is untouched
(`native_entry` and `native_sim_entry` still build; `trace-native` keeps
the run guards). Open: P2.4, one board act from the demo repo against the
pinned island.

- P2.1 Create `NEWSLabNTU/rtss-work-2026-demo` (private).
- P2.2 `git filter-repo` a fresh clone down to the evaluation paths (with
  their history), add this repo as `third-party/safety-island` pinned like
  nano-ros, and give it its own CI (L3 contract, the evaluation selftest).
- P2.3 Delete the moved paths here in one commit, retire the legacy Cyclone
  demo (its recipes, `demo/cyclonedds.xml`, its README section), and fix the
  links (README, runbook, the phase docs that point at moved files).
- P2.4 The board acts run from the new repo against the pinned island; one
  act passes there before P2.3 lands.

**P3. Write-ups leave** -- done (2026-10-29)

Status: the write-ups went with the same filter-repo pass and are deleted
here. The docs that stay drop deck and slide references (the reaction
trace drawing, the spin-latency comparison, the phase-5 deck note, an
emulation claim's wording); measurements keep their method.

- P3.1 `slides/`, `docs/writeup/`, `docs/dx-ux-gaps-2026-10.md`,
  `docs/design/rtss-work-2026/` move to the new repo (same filter-repo pass
  or a second one).
- P3.2 The docs that stay state technical facts only (measurements with
  their method, no paper framing).

## Acceptance

- This repo's CI is green after every unit; `just build`, `just zephyr-build`
  and the board build work from a fresh clone with only the needed submodules.
- `rg -l 'demo/l3|demo/carla|experiments/|tools/timeline|slides/|writeup'`
  in this repo finds no live reference (history and the phase-14 doc aside).
- The new repo builds its L3 container and passes its CI; one board act
  passes there against the pinned island.
- No file in this repo's tree is larger than 1 MB except vendored sources.
