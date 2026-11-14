# Island -> HPC safety world state (RFC section 8.2, /si/out/safety_world).
# Producer: N16 si_safety_world_model, 20 Hz. Advisory in this direction:
# the HPC may cross-validate against it and must never depend on it.

builtin_interfaces/Time stamp
# True when no source is valid: the explicit no-valid-source condition, so a
# blackout is distinguishable from an empty road.
bool no_valid_source
# Nearest in-path obstacle [m], its range rate [m/s] and time to collision
# [s]; has_obstacle false when none is perceived.
bool has_obstacle
float32 obstacle_range
float32 obstacle_range_rate
float32 time_to_collision
# Free-space distance ahead [m].
float32 free_space_distance
# Perceived corridor (camera-anchored), left and right boundaries.
geometry_msgs/Point[<=32] corridor_left
geometry_msgs/Point[<=32] corridor_right
# Validity per source.
bool camera_valid
bool radar_valid
bool ultrasonic_valid
bool lidar_valid
