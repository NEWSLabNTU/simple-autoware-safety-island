cmake_minimum_required(VERSION 3.20)
project(tier4_system_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(autoware_common_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
    msg/MrmBehaviorStatus.msg
    srv/OperateMrm.srv
    DEPENDENCIES builtin_interfaces autoware_common_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
