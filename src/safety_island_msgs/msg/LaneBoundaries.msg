# Island-internal (RFC section 6.2, not a section 8 signal): the forward
# camera's lane boundaries. Producer: N14 si_vision_guard, 10-20 Hz, on
# /si/sensing/lane_boundaries; a certified smart camera's lane output on
# /si/sensing/camera has the same form. Consumers: N5, N16, N19.

builtin_interfaces/Time stamp
# False when N14 (with N17's debounce) holds the camera or its lane lines
# invalid: the sensing-blackout condition, a B4 trigger.
bool valid
geometry_msgs/Point[<=32] left_boundary
geometry_msgs/Point[<=32] right_boundary
# Road edge or kerb beyond the outer lane line, and the drivable lateral
# space between them [m] (the evidence for an island-detected refuge).
geometry_msgs/Point[<=32] road_edge
float32 drivable_lateral_space
