# safety_island_msgs

Messages of the L4 safety island's HPC interface, from
RFC_L4_SafetyIslandDesign V1.0 (`docs/L4SafetyIsland_SoftwareDesign_GitHub.md`,
commit f529052), section 8, plus the island-internal messages the L4 contract
(`l4/l4_island_bringup`) names. One set of `.msg` sources serves both domains:

- ROS 2: `rosidl_generate_interfaces()` in `CMakeLists.txt`, built by
  `scripts/build-host-msgs.sh` (`just host-msgs`, and CI).
- nano-ros: resolved from `package.xml` through the workspace's
  `NROS_INTERFACE_SEARCH_PATH` (`src/`), like the vendored Autoware subsets
  beside it. `just l4-msgs` generates the Rust, C and C++ bindings and checks
  that every type has a derived size bound. No image carries these messages
  yet: no L4 node is built.

The RFC proposes the name `autoware_safety_island_msgs` for an upstream
package (open decision 5); this repository uses `safety_island_msgs` until
that is decided.

## Messages

| Message | RFC | Topic | Producer -> consumer |
|---|---|---|---|
| `HpcHeartbeat` | 8.1 | `/si/in/heartbeat` | H7 -> N2 |
| `HpcCapability` | 8.1 | `/si/in/capability` | H2 -> island |
| `OddStatus` (+ `ActiveOdd`) | 8.1 | `/si/in/odd_status` | H4 -> N19 |
| `SafetyCorridor` | 8.1 | `/si/in/corridor` | H3 -> N5 |
| `PullOverRefuge` | 8.1, 6.3 | `/si/in/refuge` | H8 -> N18 |
| `IslandState` | 8.2 | `/si/out/state` | N3 -> H6 (and N7, N10) |
| `SafetyWorldState` | 8.2 | `/si/out/safety_world` | N16 -> HPC (advisory) |
| `IslandSensorHealth` (+ `SensorHealth`) | 8.2 | `/si/out/sensor_health` | N17 -> HPC |
| `OddVerdict` | 8.2, 6.4 | `/si/out/odd_verdict` | N19 -> N3, N10, HPC |
| `FallbackAvailability` | 8.2, 6.3 | `/si/out/fallback_availability` | N18 -> N3, HPC |
| `SafetyEnvelopeCommand` | 8.2 | `/si/out/constraints` | N10 -> HPC |
| `LaneBoundaries` | 6.2 | `/si/sensing/lane_boundaries` | N14 -> N5, N16, N19 |
| `RadarTracks` (+ `RadarTrack`) | 6.2 | `/si/sensing/radar_tracks` | radar -> N6 |
| `SensorState` | 6.1 | `/si/internal/{corridor,radar}_state` | N5, N6 -> N8, N3 |
| `SafetyEvent` | 8.4 | `/si/internal/e2e_event` | N1 -> N8 |
| `FaultVerdict` | 6.1 | `/si/internal/fault_verdict` | N8 -> N3 |

The RFC names the section 8 messages and lists their content in prose; the
field names, types and enum values here are this repository's reading of it.
Every array is bounded (`[<=N]`), so nano-ros derives a size bound for every
type without a codegen cap.

What the messages leave out on purpose: the SI-E2E protection (Data ID,
sequence counter, CRC, length, timestamp; section 8.4) is the link layer's
(H1 on the HPC, N1 on the island), not a payload field. `HpcHeartbeat` keeps
its own `sequence`, which N2 uses to tell a stuck sender from a live one.

## Autoware messages the L4 island uses

The other types the L4 contracts name come from the vendored Autoware
subsets under `src/` (verbatim `.msg` files):

- Autoware 2.0.0 (`tier4_system_msgs` 0.53.0): the command mode set of
  `command_mode_decider`, `command_mode_switcher` and
  `control_command_gate` (`CommandModeAvailability`, `CommandModeRequest`,
  `CommandModeStatus` and their items, `CommandSourceStatus`,
  `srv/SelectCommandSource`) and `InLaneStopTrigger`;
- Autoware 2.0.0 (`autoware_planning_msgs` 1.13.0): `Trajectory`,
  `TrajectoryPoint` (identical in 1.5.0);
- already vendored and identical in 2.0.0: `autoware_control_msgs/Control`,
  `autoware_vehicle_msgs/VelocityReport`, `tier4_system_msgs/OperationModeAvailability`.

They are vendored rather than taken from an installed Autoware because the
nano-ros build resolves interfaces from `src/` (the island's image has no
Autoware install), and CI checks the contracts without one.
