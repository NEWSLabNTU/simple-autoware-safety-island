cmake_minimum_required(VERSION 3.20)
project(autoware_adapi_v1_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
    msg/MrmState.msg
    msg/OperationModeState.msg
    DEPENDENCIES builtin_interfaces
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
