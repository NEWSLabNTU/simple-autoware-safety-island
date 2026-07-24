cmake_minimum_required(VERSION 3.22)
# Entry pkg (RFC-0048): no hand-written main — `nano_ros_add_executable(MODEL …)`
# drives `nros codegen entry --lang cpp --typed` at configure time and links
# every Node pkg the model names.
project(native_entry VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)

nano_ros_add_executable(native_entry
    SOURCES src/main.cpp
    BOARD   native
    MODEL   "${CMAKE_CURRENT_SOURCE_DIR}/../safety_island_bringup/config/system_model.yaml"
    TYPED
    DEPLOY  native)
