cmake_minimum_required(VERSION 3.20)
project(autoware_vehicle_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
    msg/ControlModeReport.msg
    msg/GearCommand.msg
    msg/HazardLightsCommand.msg
    msg/SteeringReport.msg
    msg/TurnIndicatorsCommand.msg
    msg/VelocityReport.msg
    DEPENDENCIES builtin_interfaces std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
