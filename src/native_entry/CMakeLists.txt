cmake_minimum_required(VERSION 3.22)
# Entry pkg (RFC-0048): no hand-written main -- `nano_ros_add_executable(BRINGUP
# ...)` drives `nros codegen entry --lang cpp --typed` at configure time and
# links every Node pkg the model names.
project(native_entry VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17) # class headers use nested namespaces (RFC-0057)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)

nano_ros_add_executable(native_entry
    SOURCES src/main.cpp
    BOARD   native
    # BRINGUP names the package a HUMAN authors -- system.toml, launch/ and
    # the launch file's contract sidecar. The SystemModel is a BUILD ARTIFACT
    # `nros sync` writes under build/nros/models/, located here by
    # `nros model-path`; nobody edits or commits it. MODEL named that artifact
    # directly, which is how this entry kept building from a model resolved
    # before the contract existed (4 nodes, 0 topics).
    BRINGUP "${CMAKE_CURRENT_SOURCE_DIR}/../safety_island_bringup"
    TYPED
    DEPLOY  native)
