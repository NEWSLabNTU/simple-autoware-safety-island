# HPC -> island drivable corridor (RFC section 8.1, /si/in/corridor).
# Producer: H3 hpc_corridor_publisher, 10 Hz, age limit 300 ms, SI-E2E/A.
# The Lanelet2 map reduced to a fixed-capacity strip around the current
# trajectory: left and right boundary polylines in the vehicle's map frame.

builtin_interfaces/Time stamp
geometry_msgs/Point[<=32] left_boundary
geometry_msgs/Point[<=32] right_boundary
