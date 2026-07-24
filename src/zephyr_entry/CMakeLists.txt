cmake_minimum_required(VERSION 3.22)
# P4 — Zephyr entry. Built through west (Zephyr owns the build): the zephyr
# CMake finds nano-ros as a module, this pkg contributes the entry codegen +
# node registration. find_package(Zephyr) first per RFC-0048 §3.
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(zephyr_entry VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)

nano_ros_add_executable(zephyr_entry
    SOURCES src/main.cpp
    BOARD   native_sim
    MODEL   "${CMAKE_CURRENT_SOURCE_DIR}/../safety_island_bringup/config/system_model.yaml"
    TYPED
    DEPLOY  zephyr)
