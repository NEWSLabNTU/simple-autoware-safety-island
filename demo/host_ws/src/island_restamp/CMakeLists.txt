cmake_minimum_required(VERSION 3.14)
# phase9-W9: the island's hazard-lights command, restamped on the host for
# vehicle_cmd_gate (include/island_restamp/restamp.hpp says why).
project(island_restamp CXX)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_components REQUIRED)
find_package(autoware_vehicle_msgs REQUIRED)

add_library(hazard_lights_restamp_component SHARED src/hazard_lights_restamp.cpp)
target_include_directories(hazard_lights_restamp_component PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
ament_target_dependencies(hazard_lights_restamp_component
  rclcpp rclcpp_components autoware_vehicle_msgs)
rclcpp_components_register_node(hazard_lights_restamp_component
  PLUGIN "island_restamp::HazardLightsRestamp"
  EXECUTABLE hazard_lights_restamp)

install(TARGETS hazard_lights_restamp_component
  ARCHIVE DESTINATION lib LIBRARY DESTINATION lib RUNTIME DESTINATION bin)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  find_package(rosgraph_msgs REQUIRED)
  ament_add_gtest(test_restamp test/test_restamp.cpp TIMEOUT 60)
  target_include_directories(test_restamp PRIVATE include)
  ament_target_dependencies(test_restamp rclcpp autoware_vehicle_msgs rosgraph_msgs)
endif()

ament_package()
