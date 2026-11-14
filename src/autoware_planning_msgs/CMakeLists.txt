cmake_minimum_required(VERSION 3.20)
project(autoware_planning_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
    msg/RouteState.msg
    # Autoware 2.0.0 (1.13.0): the trajectory the L4 island receives from the
    # HPC (RFC section 8.1) and its MRM planner produces.
    msg/Trajectory.msg
    msg/TrajectoryPoint.msg
    DEPENDENCIES builtin_interfaces geometry_msgs std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
