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
┌───────────────────────────────┐     ┌──────────────────────────────────┐
│ Autoware (docker,             │     │ Safety island (Zephyr / native)  │
│ planning_simulator, domain 1, │◄───►│ domain 2: mrm_handler +          │
│ stock MRM nodes DISABLED)     │bridge│ 3 stop operators                 │
└───────────────────────────────┘     └──────────────────────────────────┘
        ros2 domain_bridge forwards exactly the contract topic set
```

- Topic contract: [docs/topic-contract.md](docs/topic-contract.md) (SSoT) +
  [demo/bridge/bridge-config.yaml](demo/bridge/bridge-config.yaml) (machine artifact).
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
demo/                       Autoware planning_simulator + domain_bridge compose
docs/
  roadmap/                  phase doc — plan + acceptance
  topic-contract.md         bridged-topic SSoT
  porting-notes.md          rclcpp→nano-ros friction log (deliverable!)
```

## Prerequisites

- A nano-ros checkout, activated (`source <nano-ros>/activate.sh`) — provides the
  `nros` CLI and `play_launch`.
- ROS 2 Humble (for `.msg` parsing by the codegen and the host-side demo tools).
- `just` (task runner). Docker + `ros2 domain_bridge` for the co-sim demo (phase 5).

## Quick start (native)

```sh
export NANO_ROS_ROOT=~/repos/nano-ros     # or let direnv/justfile default it
just setup        # resolve deps + generate interfaces + resolve the system model
just build        # cmake configure + build (native)
just run          # boot the island against the native board
```

See the [phase doc](docs/roadmap/phase-1-safety-island-port.md) for the current
status and what each phase delivers.

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
