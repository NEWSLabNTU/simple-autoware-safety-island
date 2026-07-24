cmake_minimum_required(VERSION 3.20)
project(autoware_internal_planning_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
    msg/VelocityLimit.msg
    msg/VelocityLimitConstraints.msg
    msg/VelocityLimitClearCommand.msg
    DEPENDENCIES builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
