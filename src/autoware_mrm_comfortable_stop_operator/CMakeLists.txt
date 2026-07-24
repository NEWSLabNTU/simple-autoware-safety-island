cmake_minimum_required(VERSION 3.22)
# nano-ros port — same shape as autoware_mrm_emergency_stop_operator.
project(autoware_mrm_comfortable_stop_operator VERSION 0.48.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)
find_package(autoware_internal_planning_msgs REQUIRED)
find_package(tier4_system_msgs REQUIRED)

nano_ros_add_node(mrm_comfortable_stop_operator
    CLASS  autoware_mrm_comfortable_stop_operator::MrmComfortableStopOperator
    HEADER autoware/mrm_comfortable_stop_operator/mrm_comfortable_stop_operator_core.hpp
    SHAPE  rclcpp
    SOURCES src/mrm_comfortable_stop_operator/mrm_comfortable_stop_operator_core.cpp)

target_include_directories(autoware_mrm_comfortable_stop_operator_mrm_comfortable_stop_operator_component
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

# Topo-last superset interface lib only (porting-notes 08 / nano-ros #253).
if(TARGET tier4_system_msgs__nano_ros_cpp)
    target_link_libraries(autoware_mrm_comfortable_stop_operator_mrm_comfortable_stop_operator_component
        PUBLIC tier4_system_msgs__nano_ros_cpp)
endif()
