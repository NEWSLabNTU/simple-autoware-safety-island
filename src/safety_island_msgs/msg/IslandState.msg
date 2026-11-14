# Island -> HPC safety state (RFC section 8.2, /si/out/state). Producer: N3
# si_state_machine (published outward through N1), 50 Hz. Consumer on the
# HPC: H6 hpc_island_state_client. Inside the island, the B2/B3 planner
# (N7) and the envelope monitor (N10) read it too.

# Island mode (N3's states, section 6.1).
uint8 MODE_BOOT = 0
uint8 MODE_SELF_TEST = 1
uint8 MODE_STANDBY = 2
uint8 MODE_ADS_ACTIVE = 3
uint8 MODE_DEGRADED = 4
uint8 MODE_LANE_KEEP_HOLD = 5
uint8 MODE_MRM_PREPARE = 6
uint8 MODE_MRM_EXECUTE = 7
uint8 MODE_MRM_COMPLETE = 8
uint8 MODE_EMERGENCY_STOP = 9
uint8 MODE_SAFE_STOP = 10

# Who holds lateral and longitudinal authority.
uint8 AUTHORITY_HPC = 0
uint8 AUTHORITY_ISLAND = 1

# Corridor source N5 uses.
uint8 CORRIDOR_NONE = 0
uint8 CORRIDOR_MAP = 1
uint8 CORRIDOR_CAMERA = 2

builtin_interfaces/Time stamp
uint8 mode
# The fault code of the verdict that set the mode (N8's table; 0 = none).
uint32 fault_code
uint8 authority
uint8 corridor_source
# True when no corridor source is valid (sensing blackout, a B4 trigger).
bool blackout
# Lateral deviation from the corridor centre [m].
float32 lateral_deviation
# Remaining B2 hold budget T_hold [s]; 0 outside LANE_KEEP_HOLD.
float32 hold_budget_remaining
# The ODD class latched at B2 entry and its speed v_odd [m/s].
uint8 latched_road_class
float32 v_odd
# The current hold speed and the entry speed the ramp is aimed at [m/s].
float32 v_hold
float32 v_entry
