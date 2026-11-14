# HPC -> island pull-over refuge (RFC section 8.1, /si/in/refuge; the refuge
# contract of section 6.3). Producer: H8 hpc_refuge_publisher, 2 Hz, age
# limit 2 s, SI-E2E/A. Also the form in which N18 si_pull_over_manager hands
# the selected refuge (nominated or island-detected) to the MRM planner.

uint8 SIDE_LEFT = 0
uint8 SIDE_RIGHT = 1

uint8 SURFACE_UNKNOWN = 0
uint8 SURFACE_PAVED = 1
uint8 SURFACE_GRAVEL = 2

uint8 LEGALITY_PROHIBITED = 0
uint8 LEGALITY_LEGAL_STOP = 1
uint8 LEGALITY_EMERGENCY_ONLY = 2

uint8 FALLBACK_IN_LANE_STOP = 0

builtin_interfaces/Time stamp
# False is the explicit "no refuge available" declaration the HPC must make
# when it cannot honour the coverage guarantee; the other fields are then
# unused.
bool available
uint8 side
# Longitudinal window along the buffered trajectory, as arc length [m].
float32 entry_s
float32 exit_s
# Target lateral displacement from the lane centre [m].
float32 lateral_offset
# Usable width, for clearance checking [m].
float32 refuge_width
uint8 surface_class
uint8 legality
# How far ahead this refuge remains valid [m].
float32 validity_distance
# What to do if the refuge proves unusable.
uint8 fallback_behavior
