# Topic contract — Autoware ↔ safety island

Ground truth for what crosses the domain bridge. `demo/bridge/bridge-config.yaml`
is the machine artifact and MUST stay in sync with this table.

Autoware runs on **domain 1**, the island on **domain 2**. The bridge forwards
exactly this set — nothing else leaves either domain.

## Autoware → island (1 → 2)

| Topic | Type | Consumer |
| --- | --- | --- |
| `/system/operation_mode/availability` | `tier4_system_msgs/msg/OperationModeAvailability` | mrm_handler |
| `/localization/kinematic_state` | `nav_msgs/msg/Odometry` | mrm_handler |
| `/vehicle/status/control_mode` | `autoware_vehicle_msgs/msg/ControlModeReport` | mrm_handler |
| `/api/operation_mode/state` | `autoware_adapi_v1_msgs/msg/OperationModeState` | mrm_handler |
| `/control/command/control_cmd` | `autoware_control_msgs/msg/Control` | emergency_stop_operator (ramp seed) |
| `/vehicle/status/steering_status` | `autoware_vehicle_msgs/msg/SteeringReport` | stop_mode_operator |
| `/vehicle/status/velocity_status` | `autoware_vehicle_msgs/msg/VelocityReport` | stop_mode_operator |
| `/planning/route_state` | `autoware_adapi_v1_msgs/msg/RouteState` | stop_mode_operator |

## Island → Autoware (2 → 1)

| Topic | Type | Producer |
| --- | --- | --- |
| `/system/emergency/control_cmd` | `autoware_control_msgs/msg/Control` | emergency_stop_operator |
| `/system/emergency/gear_cmd` | `autoware_vehicle_msgs/msg/GearCommand` | mrm_handler |
| `/system/emergency/turn_indicators_cmd` | `autoware_vehicle_msgs/msg/TurnIndicatorsCommand` | mrm_handler |
| `/system/emergency/hazard_lights_cmd` | `autoware_vehicle_msgs/msg/HazardLightsCommand` | mrm_handler |
| `/system/fail_safe/mrm_state` | `autoware_adapi_v1_msgs/msg/MrmState` | mrm_handler |
| `/planning/scenario_planning/max_velocity_candidates` | `autoware_internal_planning_msgs/msg/VelocityLimit` | comfortable_stop_operator |
| `/planning/scenario_planning/clear_velocity_limit` | `autoware_internal_planning_msgs/msg/VelocityLimitClearCommand` | comfortable_stop_operator |

## Island-internal (domain 2 only, not bridged)

| Topic / service | Type | Wire |
| --- | --- | --- |
| `/system/mrm/emergency_stop/operate` | `tier4_system_msgs/srv/OperateMrm` | handler → operator |
| `/system/mrm/comfortable_stop/operate` | `tier4_system_msgs/srv/OperateMrm` | handler → operator |
| `/system/mrm/emergency_stop/status` | `tier4_system_msgs/msg/MrmBehaviorStatus` | operator → handler |
| `/system/mrm/comfortable_stop/status` | `tier4_system_msgs/msg/MrmBehaviorStatus` | operator → handler |

Timing contract (bringup params, upstream defaults): operators tick at
`update_rate: 30` Hz; emergency profile `target_acceleration: -2.5 m/s²`,
`target_jerk: -1.5 m/s³`.

> NOTE: exact remap names get finalized in P1/P3 against
> `mrm_handler.launch.xml` from upstream 1.5.0 — treat the current names as
> draft until the launch files land.
