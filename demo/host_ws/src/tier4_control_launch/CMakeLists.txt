cmake_minimum_required(VERSION 3.14)
# phase9-W9: overlay-shadow of the installed tier4_control_launch: identical
# except vehicle_cmd_gate's emergency hazard input (launch/control.launch.xml,
# argument emergency_hazard_lights_cmd).
project(tier4_control_launch)
find_package(ament_cmake REQUIRED)
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
ament_package()
