# Island -> HPC ODD verdict and switch demand (RFC section 8.2,
# /si/out/odd_verdict; section 6.4). Producer: N19 si_odd_monitor, 2-5 Hz.
# The island measures, the HPC declares (OddStatus), the island verifies.

uint8 DIMENSION_NONE = 0
uint8 DIMENSION_VISIBILITY = 1
uint8 DIMENSION_PRECIPITATION = 2
uint8 DIMENSION_FRICTION = 3
uint8 DIMENSION_AMBIENT_LIGHT = 4
uint8 DIMENSION_SENSING = 5

uint8 PRECIPITATION_NONE = 0
uint8 PRECIPITATION_LIGHT = 1
uint8 PRECIPITATION_HEAVY = 2

builtin_interfaces/Time stamp
# Measured envelope.
float32 visibility_range
uint8 precipitation_class
float32 friction_estimate
float32 ambient_light
# Speed the measured envelope allows [m/s], and the ODD margin (0..1).
float32 v_max
float32 odd_margin
# False demands an ODD switch (the B1 trigger).
bool odd_satisfiable
uint8 failed_dimension
# Remaining T_odd budget [s]; 0 when no switch is demanded.
float32 t_odd_remaining
# The B1 acceptance test: true once the island has accepted a domain the
# HPC declared, which is then `accepted_odd`.
bool accepted
safety_island_msgs/ActiveOdd accepted_odd
