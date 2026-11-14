# Island -> HPC fallback availability (RFC section 8.2,
# /si/out/fallback_availability; section 6.3). Producer: N18
# si_pull_over_manager, 2 Hz, evaluated continuously (also during B2).

uint8 REASON_NONE = 0
uint8 REASON_NO_REFUGE_OFFERED = 1
uint8 REASON_REFUGE_OCCUPIED = 2
uint8 REASON_REFUGE_OUT_OF_RANGE = 3
uint8 REASON_CAMERA_INVALID = 4

uint8 SOURCE_NONE = 0
uint8 SOURCE_HPC_NOMINATED = 1
uint8 SOURCE_ISLAND_DETECTED = 2

builtin_interfaces/Time stamp
# True if either source currently offers a refuge the island can verify.
bool pull_over_available
uint8 reason
# Distance to the next refuge [m].
float32 distance_to_refuge
uint8 refuge_source
