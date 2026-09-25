# Zephyr entry for QEMU `mps2/an385` (Cortex-M3), phase7-W2: all four ported
# Autoware nodes in one image that boots under qemu-system-arm, so execution
# can be observed before silicon.
#
#   just qemu-build   (west build -b mps2/an385 -S nros-zenoh -d build-qemu ...)
#   just qemu-run     (boots it under QEMU, bounded, console to a file)
#
# WHY A THIRD ENTRY PACKAGE. nano-ros resolves an image from its ENTRY PACKAGE
# (`nros image-facts --for-entry`) and checks the image's declared `rmw`
# against Kconfig, so one entry is one (board, RMW) image -- the reason
# src/native_sim_entry split from src/zephyr_entry on 2026-09-21. This one is
# the board entry's shape (zenoh, snippet form, boards/<board>.conf applied)
# WITHOUT its board-only policy: an385 has no ITCM/DTCM, so the
# zephyr_code_relocate() lines of src/zephyr_entry have nothing to target, and
# its island-serial snippet names LPUARTs this SoC does not have (this entry's
# snippets/qemu-serial is the same transport on the CMSDK UART1).
#
# WHAT THIS IMAGE IS NOT. It is not the S32K344 image run somewhere else. The
# ISA is ARMv7-M (no FPU, no caches, no TCM) where the board is ARMv7E-M with
# an FPU and I/D caches. The transport is the board's (zenoh over a UART, no IP
# stack) by default, on a different UART. What carries over is the software: the
# same components, the same contract, the same derivation, the same Zephyr line
# (4.4) and the same board-fact sizing (boards/mps2_an385.conf says which).

cmake_minimum_required(VERSION 3.20.0)

# Workspace-local msg pkgs resolve through the auto-emitted Find-stubs -- the
# search path must be visible before nano_ros's stub machinery loads.
set(NROS_INTERFACE_SEARCH_PATH "${CMAKE_CURRENT_SOURCE_DIR}/..")

# Transport snippets live in this directory (snippets/qemu-serial,
# snippets/qemu-ethernet); Zephyr does not seed SNIPPET_ROOT with the
# application, so without this `-S qemu-serial` is an "unknown snippet".
# Must precede find_package(Zephyr), as in src/zephyr_entry.
list(APPEND SNIPPET_ROOT ${CMAKE_CURRENT_SOURCE_DIR})

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(safety_island_qemu_entry)

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
# node component libs the model names. Identical to the other two entries.
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../island_interfaces" island_interfaces)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_emergency_stop_operator" autoware_mrm_emergency_stop_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_comfortable_stop_operator" autoware_mrm_comfortable_stop_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_stop_mode_operator" autoware_stop_mode_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_handler" autoware_mrm_handler)

# BRINGUP names the package a human authors; the launch tree inside it is what
# `nros sync` resolves. The same bringup, hence the same contract and the same
# derived entity counts, as the board image.
nano_ros_add_executable(qemu_entry
    BOARD   zephyr
    BRINGUP "${CMAKE_CURRENT_SOURCE_DIR}/../safety_island_bringup"
    TYPED
    DEPLOY  zephyr)
