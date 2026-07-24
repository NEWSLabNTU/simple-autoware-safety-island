cmake_minimum_required(VERSION 3.22)
# nano-ros port — same shape as the operator pkgs.
project(autoware_mrm_handler VERSION 0.48.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)
find_package(autoware_adapi_v1_msgs REQUIRED)
find_package(autoware_vehicle_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(tier4_system_msgs REQUIRED)

nano_ros_add_node(mrm_handler
    CLASS  autoware_mrm_handler::MrmHandler
    HEADER autoware/mrm_handler/mrm_handler_core.hpp
    SHAPE  rclcpp
    SOURCES src/mrm_handler/mrm_handler_core.cpp)

target_include_directories(autoware_mrm_handler_mrm_handler_component
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

# Any interface target carries the workspace superset archive (island_interfaces).
if(TARGET tier4_system_msgs__nano_ros_cpp)
    target_link_libraries(autoware_mrm_handler_mrm_handler_component
        PUBLIC tier4_system_msgs__nano_ros_cpp)
endif()
