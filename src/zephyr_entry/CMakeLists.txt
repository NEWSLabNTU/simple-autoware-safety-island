# P4 — Zephyr (native_sim) entry: all four ported Autoware nodes in one
# bootable image. Shape mirrors nano-ros examples/workspaces/mixed/src/
# zephyr_entry (C++-only variant — no Rust node, no NROS_WS_RUST_NODE_DIRS).
#
#   west build -b native_sim/native/64 src/zephyr_entry \
#     -- -DCONF_FILE="prj.conf;prj-cyclonedds.conf" -D_NANO_ROS_CODEGEN_TOOL=<nros>

cmake_minimum_required(VERSION 3.20.0)

# Workspace-local msg pkgs resolve through the auto-emitted Find-stubs — the
# search path must be visible before nano_ros's stub machinery loads.
set(NROS_INTERFACE_SEARCH_PATH "${CMAKE_CURRENT_SOURCE_DIR}/..")

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(safety_island_zephyr_entry)

# RFC-0048: on Zephyr find_package(nano_ros) supplies the verbs + entry
# machinery; the nano-ros west module already provides the runtime.
find_package(nano_ros REQUIRED)

if(NOT COMMAND nano_ros_workspace_pkg_guard)
    function(nano_ros_workspace_pkg_guard)
    endfunction()
endif()

# Interface union first (one superset FFI archive — nano-ros #253), then the
# node component libs the model names.
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../island_interfaces" island_interfaces)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_emergency_stop_operator" autoware_mrm_emergency_stop_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_comfortable_stop_operator" autoware_mrm_comfortable_stop_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_stop_mode_operator" autoware_stop_mode_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_handler" autoware_mrm_handler)

nano_ros_add_executable(zephyr_entry
    BOARD   zephyr
    MODEL   "${CMAKE_CURRENT_SOURCE_DIR}/../safety_island_bringup/config/system_model.yaml"
    TYPED
    DEPLOY  zephyr)
