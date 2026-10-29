# Demo runbook - the island and the board on a fresh machine

**Validated 2026-10-13 (phase9-W21)**, on the demo host, from a fresh
worktree to a board image that then passed three acts (encore, a, b) on the
MR-CANHUBK344. The RTSS demo runs the island on the board, its zenoh session
over the serial link to a gateway router on the host, and Autoware 1.5.0 on
rmw_zenoh_cpp in a container. This file sets up and builds the island side:
the nano-ros tools, play_launch, the Zephyr 4.4 toolchain, the model and the
board image (sections 0-6). The host side (the Autoware image, the host
overlay, the real-time limits, the acts, the host traps and the validation
record of the acts) is in NEWSLabNTU/rtss-work-2026-demo, which holds this
repo as its submodule `third-party/safety-island`:
rtss-work-2026-demo:docs/demo-runbook.md (section 7 below). A path written
`rtss-work-2026-demo:<path>` is in that repo. The earlier Cyclone/native_sim
demo (phases 2-7) is retired (phase 14); its recipes are gone.

## 0. The one rule: a clean shell

This host's login shell is not a clean one. `.envrc` (through
`scripts/env.sh`) exports the Cyclone RMW, and a shell that ever sourced a
built copy of an Autoware overlay carries it ahead of `/opt/autoware/1.5.0`.

- Run every step below through `scripts/ienv.sh '<command>'`: `env -i` with a
  minimal PATH, then `scripts/env.sh` for this checkout only, so an inherited
  `NANO_ROS_ROOT`, another worktree's direnv or a sibling nano-ros cannot
  reach the build. From a rtss-work-2026-demo checkout the same script is
  `third-party/safety-island/scripts/ienv.sh`; it `cd`s into the island
  checkout first.
- The Autoware checks of the host side run under `env -i` too
  (rtss-work-2026-demo:docs/demo-runbook.md section 0).

## 1. Prerequisites (machine level)

| Thing | Where / check | Notes |
| --- | --- | --- |
| Ubuntu 22.04 + ROS 2 Humble | `/opt/ros/humble` | |
| Autoware 1.5.0 | `/opt/autoware/1.5.0` | `just doctor` checks it; `just sync` resolves the island's launch against it |
| `just`, `git`, `uv` | `command -v` | uv makes the Zephyr 4.4 py3.12 venv |
| GNU parallel | `command -v parallel` | `just doctor` fails without it |
| pyocd 0.44 | `pyocd --version` (`pip install --user pyocd`) | flash, reset and the SWD readout |
| MCU-Link probe on the board's SWD | `pyocd list` shows it | never `pyocd erase --chip` (justfile `board-flash`) |
| disk | `~/.nros` (shared nros store) | Zephyr 4.4 workspace, its venv, SDK 1.0.1, hal_nxp (~1.3 GB) |

The host side's own prerequisites (rmw_zenoh_cpp 0.1.10, Docker, pyserial,
the serial adapter, an X display) are in
rtss-work-2026-demo:docs/demo-runbook.md section 1.

## 2. Clone and submodules

```sh
git clone https://github.com/NEWSLabNTU/simple-autoware-safety-island.git
cd simple-autoware-safety-island
git submodule update --init third-party/nano-ros
git -C third-party/nano-ros submodule update --init \
    packages/cli/third-party/play_launch packages/rmw/zenoh/zpico-sys/zenoh-pico
```

Not `--recursive`: that also clones nano-ros's PX4, NuttX, Cyclone, XRCE and
QEMU trees, none of which this build reads. The nano-ros clone is large (it
took over 20 min from GitHub here; `--reference <an existing nano-ros
clone>` makes it seconds).

## 3. The nano-ros tools

```sh
scripts/ienv.sh '(cd third-party/nano-ros && just setup-cli)'
scripts/ienv.sh '(cd third-party/nano-ros && just setup-launch-resolve)'
```

About a minute with a warm sccache. Re-run both after any change of the
nano-ros pin or of its play_launch submodule; `just doctor` says which.

- After `setup-launch-resolve` the doctor warns that play_launch has a
  modified `src/ros-launch-resolve/parser/Cargo.lock`. Harmless at this pin
  (nano-ros issue 1863, fixed after it); `git -C
  third-party/nano-ros/packages/cli/third-party/play_launch checkout
  src/ros-launch-resolve/parser/Cargo.lock` clears it.
- Build and check the resolver in the same locale. At this pin its
  freshness stamp sorts in the caller's locale, so a resolver built under
  `C.UTF-8` (what `scripts/ienv.sh` sets) reads STALE to
  `check-launch-resolve-fresh.sh` under `en_US.UTF-8` (nano-ros issue 1869,
  fixed after this pin). `just doctor` accepts either.

## 4. play_launch and the doctor

```sh
scripts/ienv.sh 'just setup-play-launch'     # play_launch >= 0.16.0 into ~/.local/bin
scripts/ienv.sh 'just doctor'
```

The minimum is the CI pin (`PLAY_LAUNCH_VERSION`, .github/workflows/check.yml),
0.16.0: 0.14.x and older reject the demo contracts' timer `jitter` key, 0.15.x
does not charge it, and 0.12.0 rejects the island contract without naming a
version. A source build instead of the package index:
`PLAY_LAUNCH_REPO=<checkout> just setup-play-launch force`.

`just doctor` ends in `doctor: OK (...)`. Its findings each name their
command, in order: the nano-ros pin, the nested submodules, `setup-cli`,
`setup-launch-resolve`, play_launch, cmake, GNU parallel, ROS, Autoware. Two
warnings do not fail it: no X server, and the real-time limit of the host gate
(rtss-work-2026-demo:docs/demo-runbook.md section 4).

## 5. The Zephyr 4.4 toolchain

```sh
scripts/ienv.sh 'just board-setup'
scripts/ienv.sh 'just board-doctor'
```

`board-setup` provisions into the shared nros store (`~/.nros`): the Zephyr
4.4 west workspace and its py3.12 venv (`.venv312`, made with uv), the
Zephyr SDK 1.0.1 and its installer, hal_nxp at the revision Zephyr's
`west.yml` names, and this repo's `patches/zephyr/0001` (DTCM relocation).
Idempotent: on a provisioned host it takes seconds; re-run it after any
`west update`. `board-doctor` should end with `[OK] one ROS domain
everywhere: 10` and show the probe.

Then the one package the store's venv lacks at this pin (nano-ros issue
1870, fixed after it): Zephyr's size reports import `anytree`, so without it
`just board-build` prints `board-size: rom_report failed (advisory, the
image is fine): ModuleNotFoundError` for both reports.

```sh
uv pip install --python ~/.nros/workspaces/zephyr/4.4/.venv312/bin/python anytree
```

## 6. The model and the board image

```sh
scripts/ienv.sh 'just sync'          # the SystemModel, build/nros/models/...
scripts/ienv.sh 'just board-build'   # build-board/zephyr/zephyr.elf (runs sync too)
```

- `just sync` prints `no producer for <node> (metadata probe run failed ...
  declare_parameter (code=-16))` for the island's nodes and then `sync:
  done.`: known and harmless at this pin (rtss-work-2026-demo:docs/roadmap/phase-9-rtss-demo-open-items.md,
  section 5, item 4).
- `just board-build` exits 0 and ends with the rom and ram reports; the
  linker's own table is the footprint of record. Validated build: FLASH
  581,676 B, RAM 276,040 B (84.24 %), ITCM 12,800 B, DTCM 117,536 B (89.67 %,
  the 8 KiB headroom guard of phase9-C10 passes).
- `board-build: REFUSING this image -- a resolved knob did not reach the
  compile` on a first build: run it again, the second pass converges (the
  recipe says so).

## 7. The host side and the acts

In a rtss-work-2026-demo checkout, its submodule at this repo's commit
(`git -C third-party/safety-island log -1`), the island built there by
sections 2-6 (`just island::<recipe>` runs this repo's recipes from it):
rtss-work-2026-demo:docs/demo-runbook.md has the Autoware image, the host
overlay, the evaluation contract check, the real-time limits of the host
gate, the acts (`tools/eval/run-board.sh`, one act or several on one boot),
the host traps and the validation record of the acts.

The board image of the validation (2026-10-13, phase9-W21, a fresh worktree
of `main` at `13ff8e5`, nano-ros `43fc1c2f7`, every step above through
`scripts/ienv.sh`, the submodule clone with `--reference` to a local
nano-ros clone): `just board-build` exit 0, ELF sha256
`0ebd641254a98cf0...`, the region table of section 6.
