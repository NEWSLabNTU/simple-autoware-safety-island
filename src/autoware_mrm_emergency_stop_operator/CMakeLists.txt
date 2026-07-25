cmake_minimum_required(VERSION 3.22)
# nano-ros port — upstream builds this with ament_cmake_auto +
# rclcpp_components; here the same sources become a nano-ros Node pkg
# (no main(), the Entry pkg owns boot). RFC-0057: upstream namespaces +
# rclcpp_components-parity registration — near-verbatim CMake too.
project(autoware_mrm_emergency_stop_operator VERSION 0.48.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17) # upstream Autoware standard — nested namespaces port verbatim (RFC-0057)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)
find_package(autoware_control_msgs REQUIRED)
find_package(tier4_system_msgs REQUIRED)

nano_ros_auto_add_library(mrm_emergency_stop_operator_lib STATIC src/mrm_emergency_stop_operator/mrm_emergency_stop_operator_core.cpp)

nros_components_register_node(mrm_emergency_stop_operator_lib
    PLUGIN autoware::mrm_emergency_stop_operator::MrmEmergencyStopOperator
    EXECUTABLE mrm_emergency_stop_operator
    HEADER autoware/mrm_emergency_stop_operator/mrm_emergency_stop_operator_core.hpp)

