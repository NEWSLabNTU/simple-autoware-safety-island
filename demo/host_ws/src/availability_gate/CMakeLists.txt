cmake_minimum_required(VERSION 3.14)
project(availability_gate CXX)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_compile_options(-Wall -Wextra -Wpedantic)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(tier4_system_msgs REQUIRED)
find_package(Threads REQUIRED)

add_executable(availability_gate src/availability_gate.cpp)
ament_target_dependencies(availability_gate rclcpp std_msgs tier4_system_msgs)
target_link_libraries(availability_gate Threads::Threads)

install(TARGETS availability_gate DESTINATION lib/${PROJECT_NAME})
install(PROGRAMS scripts/gate-rt DESTINATION lib/${PROJECT_NAME})

ament_package()
