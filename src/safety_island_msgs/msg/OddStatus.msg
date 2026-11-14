# HPC -> island ODD status and declared active domain (RFC section 8.1,
# /si/in/odd_status). Producer: H4 hpc_odd_reporter, 10 Hz, age limit 300 ms,
# SI-E2E/B. The HPC's half of the B1 exchange: the island demands an ODD
# switch, and this message answers within T_ack.

uint8 WEATHER_UNKNOWN = 0
uint8 WEATHER_CLEAR = 1
uint8 WEATHER_RAIN = 2
uint8 WEATHER_HEAVY_RAIN = 3
uint8 WEATHER_FOG = 4
uint8 WEATHER_SNOW = 5

uint8 ODD_SWITCH_STEADY = 0
uint8 ODD_SWITCH_SWITCHING = 1
uint8 ODD_SWITCH_EXHAUSTED = 2

builtin_interfaces/Time stamp
bool geofence_valid
uint8 weather_class
bool roadworks
bool unmapped_area
safety_island_msgs/ActiveOdd active_odd
uint8 odd_switch_state
