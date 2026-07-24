cmake_minimum_required(VERSION 3.22)
# nano-ros port — upstream builds this with ament_cmake_auto +
# rclcpp_components; here the same sources become a nano-ros Node pkg
# (no main(), the Entry pkg owns boot). Identity rule: CLASS prefix must
# equal the pkg name.
project(autoware_mrm_emergency_stop_operator VERSION 0.48.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)
find_package(autoware_control_msgs REQUIRED)
find_package(tier4_system_msgs REQUIRED)

nano_ros_add_node(mrm_emergency_stop_operator
    CLASS  autoware_mrm_emergency_stop_operator::MrmEmergencyStopOperator
    HEADER autoware/mrm_emergency_stop_operator/mrm_emergency_stop_operator_core.hpp
    SHAPE  rclcpp
    SOURCES src/mrm_emergency_stop_operator/mrm_emergency_stop_operator_core.cpp)

target_include_directories(autoware_mrm_emergency_stop_operator_mrm_emergency_stop_operator_component
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

# Link ONLY the topo-last interface lib: nano-ros emits each interface pkg's
# FFI staticlib as a SUPERSET of every preceding pkg in the resolve-deps topo
# order, so linking two of them duplicates the shared closure symbols
# (porting-notes 08 — nano-ros issue pending). tier4_system_msgs is last here
# and carries autoware_control_msgs + autoware_common_msgs + builtin_interfaces.
if(TARGET tier4_system_msgs__nano_ros_cpp)
    target_link_libraries(autoware_mrm_emergency_stop_operator_mrm_emergency_stop_operator_component
        PUBLIC tier4_system_msgs__nano_ros_cpp)
endif()
