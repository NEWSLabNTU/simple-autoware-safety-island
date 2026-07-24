cmake_minimum_required(VERSION 3.22)
# nano-ros port — upstream keeps sources under src/ with no include/ tree;
# layout preserved.
project(autoware_stop_mode_operator VERSION 0.48.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)
find_package(autoware_control_msgs REQUIRED)
find_package(autoware_planning_msgs REQUIRED)
find_package(autoware_vehicle_msgs REQUIRED)

nano_ros_add_node(stop_mode_operator
    CLASS  autoware_stop_mode_operator::StopModeOperator
    HEADER stop_mode_operator.hpp
    SHAPE  rclcpp
    SOURCES src/stop_mode_operator.cpp src/continuous_condition.cpp)

target_include_directories(autoware_stop_mode_operator_stop_mode_operator_component
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)

# Any interface target carries the workspace superset archive (island_interfaces
# resolves the union closure first — nano-ros #253).
if(TARGET autoware_vehicle_msgs__nano_ros_cpp)
    target_link_libraries(autoware_stop_mode_operator_stop_mode_operator_component
        PUBLIC autoware_vehicle_msgs__nano_ros_cpp)
endif()
