# Phase 1 — Autoware Safety Island example: port plan

**Status (2026-07-24): P0-P4 DONE (P4 = native_sim; QEMU board = follow-up); P5 staged** — all three operators ported +
validated e2e on native/cyclonedds/domain 2. P1: emergency stop (OperateMrm
round-trip, decel ramp v=5→0 @ a=-2.5). P2: comfortable stop (latched
VelocityLimit w/ constraints + sender, clear command, OPERATING transition)
and stop_mode (continuous stop-hold a=-1.5, turn/hazard DISABLE, auto-parking
PARK=22 after 1 s continuous standstill + route ARRIVED — ContinuousCondition
port exercised). nano-ros fixes so far: struct-member msg constants,
multi-interface-pkg FFI dedupe (#253), rclcpp-shape `QoS(depth)` ctor.
P3: mrm_handler full chain (heartbeat loss → cancel comfortable → call
emergency → ramp + hazards). P4: the same 4-node chain in ONE Zephyr
native_sim image (cyclone, domain 2 baked, minimal libcpp) — identical e2e
result; host tooling needs the `just host-env` unicast-discovery URI.
nano-ros fixes: struct-member constants, FFI dedupe (#253), QoS(depth),
descriptor-registry cap, zephyr placement-new + NO_FFI_CRATE parity.
19 porting notes. Next: P5 co-sim run + zephyr QEMU board bring-up.

Port the Autoware 1.5.0 MRM node chain to nano-ros as a copy-out example
workspace, preserving the upstream C++/CMake/launch shape, and demonstrate it as
a safety island co-working with an unmodified Autoware stack. Every rclcpp →
nano-ros friction point gets logged in `docs/porting-notes.md` and filed as a
nano-ros issue — the friction log is a first-class deliverable.

Sources:
- Upstream nodes: `~/repos/autoware/1.5.0-ws/src/universe/autoware_universe/{system,control}/`
- Node-chain blueprint + topic behavior: `~/repos/autoware_sentinel` (Rust re-implementation)
- Bridge/demo topology: `~/repos/autoware-safety-island` (ASI fork; two-domain
  `ros2 domain_bridge` pattern, `demo/` compose, `bridge-config.yaml`)
- nano-ros surface: `rclcpp_compat.hpp`, `nano_ros_add_node/_executable`,
  `nros_generate_interfaces`, `[safety]` feature (RFC-0028), tiers (RFC-0002/0052)

## Decisions (locked)

| Decision | Choice | Rationale |
| --- | --- | --- |
| Repo name | `autoware-safety-island-example` | user-approved |
| Porting shape | rclcpp-compat, verbatim-first | the migration story IS the product |
| RMW | cyclonedds + `ros2 domain_bridge`, two domains | ASI-proven; Autoware default RMW |
| Zephyr target | `native_sim/native/64` first, QEMU board after | fastest loop; QEMU bring-up is its own work item |

## Work items

### P0 — scaffold — DONE
Repo skeleton: README, justfile, workspace CMakeLists (subdirs commented until
ports land), bringup pkg (system.toml + launch XML), native_entry stub, docs
(topic contract, porting-notes template, this doc), demo/ stub with
bridge-config.yaml.

### P1 — first port: `autoware_mrm_emergency_stop_operator`
- Vendor msg subset: `autoware_common_msgs` (ResponseStatus),
  `autoware_control_msgs` (Control/Lateral/Longitudinal), `tier4_system_msgs`
  (OperateMrm.srv, MrmBehaviorStatus.msg) — verbatim rosidl pkgs.
- Copy the upstream package (156 LOC), keep file layout; adapt only where
  compat forces it. Known suspects: `add_on_set_parameters_callback`,
  parameter declaration API shape.
- Wire into workspace CMake + system.toml + launch XML; `just setup && just
  build && just run` boots it on native.
- **Acceptance:** service-call `OperateMrm{operate:true}` with a fake
  `control_cmd` publisher → decel ramp visible on
  `~/output/mrm/emergency_stop/control_cmd`; status topic reports OPERATING.
  Verified with host ROS 2 tools over cyclonedds.

### P2 — operator trio
- Port `autoware_mrm_comfortable_stop_operator` (+`autoware_internal_planning_msgs`;
  needs `transient_local` latched pubs via compat QoS) and
  `autoware_stop_mode_operator` (+`autoware_vehicle_msgs`,
  `autoware_adapi_v1_msgs` subset).
- Launch XML mirrors upstream remaps (`stop_mode_operator.launch.xml` feeds the
  gate "stop" source names).
- **Acceptance:** all three operators boot from one launch; each exercisable
  individually from host tools.

### P3 — the brain: `autoware_mrm_handler`
- Port the ~600 LOC state machine. Known suspects: service *clients* through
  compat, `autoware_utils::polling_subscriber` (vendor a minimal shim or add
  compat), `diagnostic_msgs` sub.
- **Acceptance:** full-chain native e2e — publish heartbeat-style
  `OperationModeAvailability` + odometry; drop availability → handler calls
  the emergency-stop operator's OperateMrm → ramped stop commands out;
  `/system/fail_safe/mrm_state` transitions MRM_OPERATING. Scripted as a test
  (`just test-e2e`).

### P4 — Zephyr
- `src/zephyr_entry` + west workflow; build the island for
  `native_sim/native/64`; enable `[safety]` feature (E2E CRC) and a 2-tier
  split (ctrl tier: handler+operators timer loop; telem tier: status pubs).
- Then QEMU board bring-up as its own item (candidate `qemu_cortex_a53`;
  networking + cyclonedds on Zephyr QEMU is the unproven part — expect nano-ros
  fixes; FVP AEMv8-R via the ASI board crate is the fallback).
- **Acceptance:** P3 e2e scenario passes against the Zephyr image (native_sim
  minimum; QEMU board stretch).

### P5 — Autoware co-sim demo
- `demo/docker-compose.yaml`: Autoware planning_simulator image +
  `ros2 domain_bridge` with `demo/bridge/bridge-config.yaml`; launch overrides
  disabling stock MRM nodes (`mrm_handler`, both stop operators) in domain 1.
- Scenario script: engage autonomous driving in the sim → kill heartbeat →
  island MRM stops the vehicle. Record the run (bag + gif) for the README.
- **Acceptance:** vehicle visibly stops in planning_simulator with the island
  providing the only MRM path; `just demo-up && just demo-kill-heartbeat`
  reproduces it.

### Stretch (post-P5)
- `autoware_control_command_gate` port (2.2k LOC — full command MUX on-island).
- zenoh RMW variant of the bridge topology.
- S32Z / FVP hardware-class target alignment with the ASI fork.

## Friction-log protocol (applies to every phase)

1. Hit a compat gap → minimal repro + entry in `docs/porting-notes.md`
   (what upstream code expected, what nano-ros does, workaround used).
2. File a nano-ros issue (`docs/issues/` series there) referencing the entry.
3. Fix lands in nano-ros mainline → drop the local workaround, note the
   resolving commit.
