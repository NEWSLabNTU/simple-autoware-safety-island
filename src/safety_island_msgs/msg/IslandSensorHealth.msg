# Island -> HPC sensor health (RFC section 8.2, /si/out/sensor_health).
# Producer: N17 si_sensor_health, 5 Hz. One item per D8-ranked sensor;
# `fitted` says which ranks this island carries (its sensor rung).

builtin_interfaces/Time stamp
safety_island_msgs/SensorHealth[<=8] sensors
