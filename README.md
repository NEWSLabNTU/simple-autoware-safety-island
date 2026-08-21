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
| `autoware_stop_mode_operator` | ~110 | continuous safe-command emitter |
| `autoware_mrm_handler` | ~600 | MRM state machine — the island brain |

Message dependencies are vendored verbatim (subset of files) under `src/`:
`autoware_control_msgs`, `autoware_vehicle_msgs`, `autoware_adapi_v1_msgs`,
`autoware_common_msgs`, `autoware_internal_planning_msgs`, `tier4_system_msgs`.
nano-ros consumes stock `rosidl_generate_interfaces()` + `package.xml` unchanged.

## Topology

```
┌───────────────────────────────┐      ┌──────────────────────────────────┐
│ Autoware (host install,       │      │ Safety island (Zephyr / native)  │
│ planning_simulator, domain 1, │◄────►│ domain 1: mrm_handler +          │
│ stock MRM nodes DISABLED)     │direct│ 3 stop operators                 │
└───────────────────────────────┘ DDS  └──────────────────────────────────┘
   one shared domain — the island's mrm_state / emergency commands reach
   the gate (and RViz) with no domain_bridge or relay in the middle
```

The island joins Autoware's own DDS domain directly. Discovery contract:
the native_sim island is multicast-less (NSOS), so every host participant
runs the shared `demo/cyclonedds.xml` (lo-pinned, auto participant index,
range 120) that the island's unicast peer scan can find; the island's own
profile is compile-time (`CONFIG_NROS_CYCLONE_CONFIG_XML`, nano-ros issue
0367).

- Topic contract: [docs/topic-contract.md](docs/topic-contract.md) (SSoT).
- Safety contracts: nano-ros `[safety]` feature (E2E CRC-32 + sequence, EN 50159
  black-channel model, nano-ros RFC-0028) + execution tiers for the control loop.
- Demo scenario: kill the Autoware heartbeat → island detects loss → MRM engages →
  vehicle stops in the planning simulator.

## Layout

```
CMakeLists.txt              nano-ros 3-role workspace root
src/
  <vendored msg pkgs>/      verbatim rosidl packages (subset)
  autoware_mrm_*/           ported node pkgs (upstream file layout preserved)
  safety_island_bringup/    system.toml + launch XML + params + resolved model
  native_entry/             native demo entry (fast dev loop)
  zephyr_entry/             Zephyr entry (added in phase 4)
demo/                       Autoware planning_simulator recipes + shared cyclone config
docs/
  roadmap/                  phase doc — plan + acceptance
  topic-contract.md         island⇄Autoware topic contract (SSoT)
  porting-notes.md          rclcpp→nano-ros friction log (deliverable!)
  demo-runbook.md           fresh-machine bring-up + what is still open
```

## Prerequisites

- ROS 2 Humble (`.msg` parsing by the codegen, and the host-side demo tools).
- Autoware 1.5.0 host install (`/opt/autoware/1.5.0`) for the demo.
- nano-ros — pinned as the `third-party/nano-ros` submodule
  (`git submodule update --init third-party/nano-ros`, then `nros setup`
  inside it). A sibling `../nano-ros` developer checkout, or an explicit
  `$NANO_ROS_ROOT`, takes precedence over the pin (resolution order in
  `.envrc`). Provides the `nros` CLI and the cmake package.
- `just` (task runner), `direnv` (optional but assumed by `.envrc`).
- play_launch — **installed by `just setup`**, not a manual prerequisite. It
  runs Autoware for the demo; >= 0.8.2 is required. To install from a source
  checkout instead of the package index: `PLAY_LAUNCH_REPO=<path> just setup`.

`direnv allow` sources ROS 2, Autoware, the demo overlay and nano-ros, and
reports anything missing; `just doctor` gives the same verdict on demand.

## Quick start (native island)

```sh
export NANO_ROS_ROOT=~/repos/nano-ros     # or let direnv/justfile default it
just setup        # install play_launch, demo overlay, resolve the system model
just build        # cmake configure + build (native)
just run          # boot the island against the native board
```

Zephyr variant: `just zephyr-build && just zephyr-run` (host tooling needs
`just host-env`). Phase docs: [phase-1](docs/roadmap/phase-1-safety-island-port.md)
(ports), [phase-2](docs/roadmap/phase-2-simple-demo-host-autoware.md) (the demo),
[phase-3](docs/roadmap/phase-3-canhubk344-real-silicon.md) (NXP MR-CANHUBK344 —
S32K344 under Zephyr; the image builds and links, no hardware run yet),
[phase-4](docs/roadmap/phase-4-link-security.md) (what protects the island's
link — open question, gates any non-bench deployment).

## The demo (validated: PASS, 3.90 → 0.00 m/s)

Host Autoware 1.5.0 (`/opt/autoware/1.5.0`) + the island; stock MRM nodes are
shadowed out, so the island is the ONLY MRM path.

Three parts, one terminal each — every recipe **blocks** on its services and
tears its whole process tree down when it exits or is Ctrl-C'd (no detached
-up/-down pairs, no orphans). RViz renders on the VNC display
(`$VNC_DISPLAY`, default `:1`; start one with `vncserver :1`):

```sh
just setup          # once: install play_launch, build the demo overlay
                    #       (MRM-shadowed tier4_system_launch), resolve the model

just autoware       # 1. Autoware planning_simulator, stock MRM OFF
                    #    (blocks; prints "Startup complete" when ready)
just island         # 2. the island, directly on domain 1 (blocks)
just demo           # 3. waits for the sim, then drive -> heartbeat fault ->
                    #    island MRM stop -> revive -> resume -> VERDICT

just demo-all       # all three in one command -> VERDICT (exit 0 = PASS)
just demo-down      # crash cleanup only (recorded groups + orphan sweep)
```

Every multi-process recipe is a foreground **GNU parallel** supervisor:
each service is its own process-group leader, and recipe exit — the
scenario finishing, a service dying, or Ctrl-C — tears the whole group
down (`--termseq` TERM→KILL). Normal teardown is simply Ctrl-C;
`just demo-down` exists for crashed supervisors.

Variants: `just demo-all native` / `just island native` (native island
instead of the Zephyr native_sim image). Autoware is launched with
play_launch (>= 0.8.2 — older versions stall on the composable
containers); `just doctor` checks the environment.

### Demo sequence & timeline

| t | step | visible in RViz |
| --- | --- | --- |
| 0 s | wait for the sim stack (ADAPI routing up) | map |
| ~1 s | `/initialpose` published | vehicle appears |
| ~6 s | goal published → route SET | route ribbon |
| ~10 s | `change_to_autonomous` | mode AUTONOMOUS |
| T₀ | velocity > 0 | **vehicle drives (~4 m/s)** |
| T₀+15 s | availability publisher SIGSTOPped — heartbeat cut | — |
| **T₀+15.5 s** | island heartbeat timeout (0.5 s) → `MRM_OPERATING / EMERGENCY_STOP` | **hard decel starts; MRM State panel goes red (live — direct domain)** |
| T₀+~18 s | jerk-limited ramp (a = −2.5 m/s²) done | **vehicle stopped, hazards on** |
| T₀+25 s | publisher SIGCONTed — heartbeat revives | — |
| T₀+~27 s | island MRM back to `NORMAL` | MRM State Inactive |
| T₀+~35 s | trajectory follower resumes on its own | **vehicle drives again** |
| +~40 s | `VERDICT: PASS/FAIL` printed | — |

The recovery leg is part of the verdict: PASS requires the MRM stop, the
island returning to `NORMAL` after the heartbeat revives, AND the vehicle
moving again. `ARRIVE_SECS=300 just demo-all` additionally waits for the
route to reach `ARRIVED` (off by default — the sample route's intersection
stop lines can hold the planner for minutes, which is Autoware behavior,
not the island's). Drive longer before the fault: `DRIVE_SECS=30`.
The 0.5 s reaction time is the ported handler's upstream
`timeout_operation_mode_availability` default.

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
