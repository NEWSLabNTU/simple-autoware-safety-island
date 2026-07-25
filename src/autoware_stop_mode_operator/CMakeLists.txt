cmake_minimum_required(VERSION 3.22)
# nano-ros port — upstream keeps sources under src/ with no include/ tree;
# layout preserved.
project(autoware_stop_mode_operator VERSION 0.48.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17) # upstream Autoware standard — nested namespaces port verbatim (RFC-0057)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)
find_package(autoware_control_msgs REQUIRED)
find_package(autoware_planning_msgs REQUIRED)
find_package(autoware_vehicle_msgs REQUIRED)

nano_ros_auto_add_library(stop_mode_operator_lib STATIC src/stop_mode_operator.cpp src/continuous_condition.cpp)

nros_components_register_node(stop_mode_operator_lib
    PLUGIN autoware::stop_mode_operator::StopModeOperator
    EXECUTABLE stop_mode_operator
    HEADER stop_mode_operator.hpp)

