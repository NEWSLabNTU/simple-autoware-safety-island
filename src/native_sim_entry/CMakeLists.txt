# Zephyr native_sim entry -- the island the demo runs (`just zephyr-build`,
# `just demo-all`): all four ported Autoware nodes in one zephyr.exe, on
# Cyclone DDS, joining Autoware's domain directly.
#
#   west build -b native_sim/native/64 -d build-zephyr src/native_sim_entry \
#     -- -DCONF_FILE="prj.conf;prj-cyclonedds.conf" -DZEPHYR_EXTRA_MODULES=<nano-ros>
#
# WHY A SECOND ENTRY PACKAGE (2026-09-21, nano-ros f0d191c98). This image and
# the board's (src/zephyr_entry) used to be ONE package built two ways:
# -DCONF_FILE for native_sim/Cyclone, `-S nros-zenoh` for the board. nano-ros
# resolves an image from its entry package (`nros image-facts --for-entry`,
# first match) and refuses a west build whose Kconfig RMW disagrees with the
# image's declared `rmw` (cmake/NanoRosImageAgreement.cmake). One package
# declares one `rmw`, so the two builds could not both pass; nano-ros's own
# examples/workspaces/cpp keeps `zephyr_entry` (zenoh) beside
# `zephyr_cyclonedds_entry` for exactly this reason and says so in its
# demo_bringup/system.toml. So: one entry per (board, RMW) variant. Board-only
# policy -- the TCM relocation, boards/, snippets/ -- stays with the board
# entry; this one is the plain image.

cmake_minimum_required(VERSION 3.20.0)

# Workspace-local msg pkgs resolve through the auto-emitted Find-stubs -- the
# search path must be visible before nano_ros's stub machinery loads.
set(NROS_INTERFACE_SEARCH_PATH "${CMAKE_CURRENT_SOURCE_DIR}/..")

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(safety_island_native_sim_entry)

# Pin nano_ros to the submodule, for the reason src/zephyr_entry/CMakeLists.txt
# gives at length: unpinned, find_package() is free to pick any checkout on
# CMAKE_PREFIX_PATH, and the failure lands far from the cause (unbounded-type
# errors in messages nobody touched). An explicit -Dnano_ros_DIR= still wins.
if(NOT DEFINED nano_ros_DIR)
    set(nano_ros_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../third-party/nano-ros"
        CACHE PATH "nano-ros checkout backing this island (default: the submodule)")
endif()
find_package(nano_ros REQUIRED)
get_filename_component(_nros_resolved "${nano_ros_DIR}" REALPATH)
get_filename_component(_nros_expected "${CMAKE_CURRENT_SOURCE_DIR}/../../third-party/nano-ros" REALPATH)
if(NOT _nros_resolved STREQUAL _nros_expected)
    message(WARNING
        "nano_ros resolved to ${_nros_resolved}, NOT this repo's submodule at "
        "${_nros_expected}. That is supported, but say so deliberately -- an "
        "ACCIDENTAL one produces unbounded-type errors in untouched messages.")
endif()

if(NOT COMMAND nano_ros_workspace_pkg_guard)
    function(nano_ros_workspace_pkg_guard)
    endfunction()
endif()

# Interface union first (one superset FFI archive -- nano-ros #253), then the
# node component libs the model names.
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../island_interfaces" island_interfaces)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_emergency_stop_operator" autoware_mrm_emergency_stop_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_comfortable_stop_operator" autoware_mrm_comfortable_stop_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_stop_mode_operator" autoware_stop_mode_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_handler" autoware_mrm_handler)

# BRINGUP names the package a human authors; the launch tree inside it is what
# `nros sync` resolves (src/zephyr_entry/CMakeLists.txt records why MODEL,
# which named a resolved artifact, is gone).
nano_ros_add_executable(native_sim_entry
    BOARD   zephyr
    BRINGUP "${CMAKE_CURRENT_SOURCE_DIR}/../safety_island_bringup"
    TYPED
    DEPLOY  zephyr)
