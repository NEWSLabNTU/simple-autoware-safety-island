# Autoware Safety Island Example

Port real Autoware 1.5.0 C++ nodes onto [nano-ros](https://github.com/NEWSLabNTU/nano-ros)
and run them as a **safety island**: a small MRM (Minimum Risk Maneuver) node chain that
brings the vehicle to a controlled stop when the main compute fails — on an RTOS
(Zephyr), co-working with an unmodified Autoware stack.

The point of this repo is the **migration story**: the ported packages keep their
upstream file layout, `package.xml`, near-verbatim `.cpp` sources, ROS 2 launch XML,
and an ament-shaped CMake surface. A ROS user should recognize everything.

## What runs on the island

Ported from `autoware_universe` 1.5.0 (`src/universe/autoware_universe/{system,control}/`),
easiest → hardest:

| Package | LOC | Role |
| --- | --- | --- |
| `autoware_mrm_emergency_stop_operator` | ~156 | jerk-limited hard stop ramp |
| `autoware_mrm_comfortable_stop_operator` | ~131 | gentle stop via velocity limit |
| `autoware_stop_mode_operator` | ~110 | continuous safe-command emitter; ported, but out of the image since phase8-W8a (no reader in the demo) |
| `autoware_mrm_handler` | ~600 | MRM state machine — the island brain |

Message dependencies are vendored verbatim (subset of files) under `src/`:
`autoware_control_msgs`, `autoware_vehicle_msgs`, `autoware_adapi_v1_msgs`,
`autoware_common_msgs`, `autoware_internal_planning_msgs`, `tier4_system_msgs`.
nano-ros consumes stock `rosidl_generate_interfaces()` + `package.xml` unchanged.

## Topology

The island joins Autoware's own domain (10) directly, with no bridge or
relay in between: on the board (`zephyr_entry`) as a zenoh-pico client over
the serial link to a gateway router beside Autoware's rmw_zenoh router
(docs/serial-link.md); on the host (`native_entry`, `native_sim_entry`) on
Cyclone DDS, the native_sim island's profile compiled in
(`CONFIG_NROS_CYCLONE_CONFIG_XML`, nano-ros issue 0367). Autoware's stock
MRM nodes are disabled by the demo's overlay, so the island is the only MRM
path; the demo itself (the L3 container, the acts, the CARLA booth) is
NEWSLabNTU/rtss-work-2026-demo.

- Topic contract: the `topics:` section of
  [safety_island.contract.yaml](src/safety_island_bringup/launch/safety_island.contract.yaml) (SSoT).
- Safety contracts: nano-ros `[safety]` feature (E2E CRC-32 + sequence, EN 50159
  black-channel model, nano-ros RFC-0028) + execution tiers for the control loop.
- Reaction: Autoware's availability heartbeat stops → the island detects the
  loss → MRM engages → the vehicle stops.

## Layout

```
CMakeLists.txt              nano-ros 3-role workspace root
src/
  <vendored msg pkgs>/      verbatim rosidl packages (subset)
  autoware_mrm_*/           ported node pkgs (upstream file layout preserved)
  safety_island_bringup/    system.toml + launch XML + params + resolved model
  native_entry/             native entry (fast dev loop)
  native_sim_entry/         Zephyr native_sim entry, Cyclone
  zephyr_entry/             Zephyr board entry, zenoh (MR-CANHUBK344)
tools/board/                board tooling: SWD readout, violations, probe
tools/diag/                 the spin-latency diagnostic image
docs/
  roadmap/                  phase doc — plan + acceptance
  porting-notes.md          rclcpp→nano-ros friction log (deliverable!)
  demo-runbook.md           fresh-machine bring-up of the island and the board (start here)
  board-bringup-triage.md   MR-CANHUBK344 first-boot triage: symptom → knob
```

## Prerequisites

- ROS 2 Humble (`.msg` parsing by the codegen, and the host-side tools).
- Autoware 1.5.0 host install (`/opt/autoware/1.5.0`) (the doctor checks it).
- nano-ros -- pinned as the `third-party/nano-ros` submodule, which wins
  over a sibling checkout or an inherited `$NANO_ROS_ROOT` (resolution order
  in `scripts/env.sh`; an override needs `NANO_ROS_ALLOW_EXTERNAL_ROOT=1`).
  The submodule commands and the `setup-cli` / `setup-launch-resolve` steps
  are in [docs/demo-runbook.md](docs/demo-runbook.md), sections 2-3.
  Provides the `nros` CLI and the cmake package.
- `just` (task runner), `direnv` (optional but assumed by `.envrc`).
- play_launch — **installed by `just setup`**, not a manual prerequisite. It
  checks the island's contract; >= 0.21.0 (the CI pin) is required. To install from a source
  checkout instead of the package index: `PLAY_LAUNCH_REPO=<path> just setup`.

`direnv allow` sources ROS 2, Autoware and nano-ros, and
reports anything missing; `just doctor` gives the same verdict on demand.

## Quick start (native island)

The board demo (the RTSS path: the island on the MR-CANHUBK344, Autoware on
zenoh in a container): [docs/demo-runbook.md](docs/demo-runbook.md) sets up
and builds the island and the board image; the host side and the acts run from
NEWSLabNTU/rtss-work-2026-demo (its docs/demo-runbook.md).
The native island below is the fast development loop.

```sh
just setup        # install play_launch, resolve the system model
just build        # cmake configure + build (native)
just run          # boot the island against the native board
```

Zephyr variant: `just zephyr-build && just zephyr-run` (host tooling needs
`just host-env`). Phase docs: [phase-1](docs/roadmap/phase-1-safety-island-port.md)
(ports), [phase-2](docs/roadmap/phase-2-simple-demo-host-autoware.md) (the legacy Cyclone demo, retired),
[phase-3](docs/roadmap/phase-3-canhubk344-real-silicon.md) (NXP MR-CANHUBK344 —
S32K344 under Zephyr; the image builds and links, no hardware run yet),
[phase-4](docs/roadmap/phase-4-link-security.md) (what protects the island's
link — open question, gates any non-bench deployment),
[phase-14](docs/roadmap/phase-14-repo-split.md) (the evaluation leaves this
repo). The RTSS@Work 2026 takeover demo and its evaluation (the L3 container,
the CARLA booth demo, the acts, the experiment runs, phases 6-9) live in
[NEWSLabNTU/rtss-work-2026-demo](https://github.com/NEWSLabNTU/rtss-work-2026-demo),
which holds this repo as its submodule `third-party/safety-island`; this
repo's docs cite its files as `rtss-work-2026-demo:<path>`.

## Porting conventions

- **rclcpp-compat first**: ported sources keep `class X : public rclcpp::Node`
  via nano-ros's `<nros/rclcpp_compat.hpp>`. Fall back to the native
  `ComponentNode` shape only where a compat gap bites — and file the gap in
  [docs/porting-notes.md](docs/porting-notes.md) either way.
- **Upstream layout preserved**: `include/autoware/<pkg>/`, `src/`, `launch/`,
  `config/*.param.yaml` mirror the 1.5.0 package.
- Every friction point becomes a nano-ros issue; fixes land in nano-ros mainline,
  not as local workarounds.

## License

Apache-2.0. Ported sources are Copyright the Autoware Foundation /
TIER IV contributors, under their original Apache-2.0 terms.
