# Island-internal: one monitor's verdict on its sensing input, from N5
# si_corridor_monitor (/si/internal/corridor_state) and N6 si_radar_guard
# (/si/internal/radar_state) to N8, N16 and N19.

builtin_interfaces/Time stamp
# False once the input is lost (silent past its age limit) or reported
# invalid.
bool valid
# Fault code for N8's table (0 = none).
uint32 fault_code
