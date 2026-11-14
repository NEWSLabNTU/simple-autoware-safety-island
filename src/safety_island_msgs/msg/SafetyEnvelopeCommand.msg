# Island -> HPC constraint / veto vector (RFC section 8.2,
# /si/out/constraints). Producer: N10 si_envelope_monitor, 50 Hz. Graded
# reaction steps 1 and 2: the island constrains the HPC rather than seizing
# control, and escalates only when the HPC does not comply in time.

uint8 MODE_ALLOW = 0
uint8 MODE_CONSTRAIN = 1
uint8 MODE_MRM = 2

builtin_interfaces/Time stamp
uint8 mode
# Limits the HPC must keep while mode is CONSTRAIN.
float32 accel_limit
float32 curvature_limit
float32 speed_limit
