# Island-internal (RFC section 6.2): the radar's native track output over CAN
# FD, on /si/sensing/radar_tracks, 20 Hz. Consumer: N6 si_radar_guard.

builtin_interfaces/Time stamp
safety_island_msgs/RadarTrack[<=32] tracks
