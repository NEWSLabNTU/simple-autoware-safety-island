cmake_minimum_required(VERSION 3.22)
# nano-ros port — same shape as the operator pkgs.
project(autoware_mrm_handler VERSION 0.48.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17) # upstream Autoware standard — nested namespaces port verbatim (RFC-0057)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)
find_package(autoware_adapi_v1_msgs REQUIRED)
find_package(autoware_vehicle_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(tier4_system_msgs REQUIRED)

nano_ros_auto_add_library(mrm_handler_lib STATIC src/mrm_handler/mrm_handler_core.cpp)

nros_components_register_node(mrm_handler_lib
    PLUGIN autoware::mrm_handler::MrmHandler
    EXECUTABLE mrm_handler
    HEADER autoware/mrm_handler/mrm_handler_core.hpp
    # phase-403 W9. Enumerated from THIS component's sources, not from the
    # topic contract, which was one subscription short. Every callback slot
    # NROS_EXECUTOR_MAX_CBS must cover is listed; publishers claim no slot,
    # and are declared because the payload classes price what is RECEIVED
    # and a reader should not have to know which half matters.
    ENTITIES
        sub:tier4_system_msgs/msg/OperationModeAvailability:/system/operation_mode/availability
        sub:nav_msgs/msg/Odometry:/localization/kinematic_state
        sub:autoware_vehicle_msgs/msg/ControlModeReport:/vehicle/status/control_mode
        sub:tier4_system_msgs/msg/MrmBehaviorStatus:/system/mrm/comfortable_stop/status
        sub:tier4_system_msgs/msg/MrmBehaviorStatus:/system/mrm/emergency_stop/status
        sub:autoware_vehicle_msgs/msg/GearCommand:/control/command/gear_cmd
        pub:autoware_adapi_v1_msgs/msg/MrmState
        pub:autoware_vehicle_msgs/msg/GearCommand
        pub:autoware_vehicle_msgs/msg/HazardLightsCommand
        pub:autoware_vehicle_msgs/msg/TurnIndicatorsCommand
        pub:tier4_system_msgs/msg/EmergencyHoldingState
        timer
)

# Any interface target carries the workspace superset archive (island_interfaces).
