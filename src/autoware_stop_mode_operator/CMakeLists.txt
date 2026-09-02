cmake_minimum_required(VERSION 3.22)
# nano-ros port — upstream keeps sources under src/ with no include/ tree;
# layout preserved.
project(autoware_stop_mode_operator VERSION 0.48.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17) # upstream Autoware standard — nested namespaces port verbatim (RFC-0057)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)
find_package(autoware_control_msgs REQUIRED)
find_package(autoware_planning_msgs REQUIRED)
find_package(autoware_vehicle_msgs REQUIRED)

nano_ros_auto_add_library(stop_mode_operator_lib STATIC src/stop_mode_operator.cpp src/continuous_condition.cpp)

nros_components_register_node(stop_mode_operator_lib
    PLUGIN autoware::stop_mode_operator::StopModeOperator
    EXECUTABLE stop_mode_operator
    HEADER stop_mode_operator.hpp
    # phase-403 W9. Enumerated from THIS component's sources, not from the
    # topic contract, which was one subscription short. Every callback slot
    # NROS_EXECUTOR_MAX_CBS must cover is listed; publishers claim no slot,
    # and are declared because the payload classes price what is RECEIVED
    # and a reader should not have to know which half matters.
    ENTITIES
        sub:autoware_vehicle_msgs/msg/SteeringReport:/vehicle/status/steering_status
        sub:autoware_vehicle_msgs/msg/VelocityReport:/vehicle/status/velocity_status
        sub:autoware_planning_msgs/msg/RouteState:/planning/route_state
        pub:autoware_control_msgs/msg/Control
        pub:autoware_vehicle_msgs/msg/GearCommand
        pub:autoware_vehicle_msgs/msg/HazardLightsCommand
        pub:autoware_vehicle_msgs/msg/TurnIndicatorsCommand
        timer
)

