# The operating domain the HPC declares as active (RFC section 8.1, carried
# in OddStatus.active_odd; section 3.1 B1). These are the domain's DECLARED
# limits, which the island verifies against its own measured envelope, not
# the vehicle's current state.

uint8 ROAD_CLASS_UNKNOWN = 0
uint8 ROAD_CLASS_CITY = 1
uint8 ROAD_CLASS_HIGHWAY = 2

uint8 road_class
# Speed ceiling of the domain [m/s].
float32 speed_ceiling
# Sensing range the domain requires [m].
float32 required_sensing_range
# Friction coefficient the domain assumes.
float32 assumed_friction
