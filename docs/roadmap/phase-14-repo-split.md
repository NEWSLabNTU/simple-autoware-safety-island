# Phase 14 - split the repo: the island here, the evaluation elsewhere

**Goal:** this repo holds the safety island and nothing else: the MRM chain
port, its bringup and contract, the board entries, the board tooling and the
board docs. The RTSS@Work 2026 evaluation (the L3 container, the CARLA booth
demo, the acts, the experiment runs, the figures) moves to a new private repo,
`NEWSLabNTU/rtss-work-2026-demo`, which consumes this one as a submodule.
Write-ups and slides leave with it. The legacy Cyclone demo is retired.

**Status (2026-10-29): planned.** Decisions taken:

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

**P0. Clean up in place**

- P0.1 Delete `record.json`, `demo/README.md`, `docs/topic-contract.md`;
  repoint their links.
- P0.2 Drop the hard-coded `/home/aeon` and `/mnt/evo` paths
  (`tools/timeline/tlcommon.py`, `just/carla.just`, `docs/demo-l4`).
- P0.3 `demo/map` becomes a pinned download (URL plus checksum, fetched by a
  recipe into an ignored directory) instead of tracked bytes.

**P1. Re-layout in this repo**

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

**P2. Extract the evaluation**

- P2.1 Create `NEWSLabNTU/rtss-work-2026-demo` (private).
- P2.2 `git filter-repo` a fresh clone down to the evaluation paths (with
  their history), add this repo as `third-party/safety-island` pinned like
  nano-ros, and give it its own CI (L3 contract, the evaluation selftest).
- P2.3 Delete the moved paths here in one commit, retire the legacy Cyclone
  demo (its recipes, `demo/cyclonedds.xml`, its README section), and fix the
  links (README, runbook, the phase docs that point at moved files).
- P2.4 The board acts run from the new repo against the pinned island; one
  act passes there before P2.3 lands.

**P3. Write-ups leave**

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
