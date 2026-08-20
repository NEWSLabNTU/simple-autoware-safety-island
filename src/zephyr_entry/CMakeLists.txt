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

# Platform thread/tier stack pools (nros_platform_zephyr_shims.c:293-301,384-392).
# Both are #ifndef-guarded in a Zephyr MODULE, so add_compile_definitions() in
# this directory does not reach them -- zephyr_compile_definitions() does, via
# the zephyr_interface target every Zephyr library links.
#
#   nros_tier_stacks  = MAX_TIERS(4)   x TIER_STACK_SIZE(16384) = 64 KiB
#   nros_thread_stacks = MAX_THREADS(8) x CONFIG_MAIN_STACK_SIZE = 64 KiB
#
# This entry's system model declares no tiers and the generated entry contains
# no tier spawn, so the tier pool is dead weight here; keep one minimal slot
# rather than zero so the array stays well-formed and a stray spawn still gets
# the shim's "raise NROS_ZEPHYR_TIER_STACK_SIZE" diagnostic instead of UB.
#
# UNVALIDATED AT RUNTIME: MAX_THREADS=4 must cover every pthread the RMW starts
# (zenoh's read + lease tasks with CONFIG_NROS_ZENOH_MULTI_THREAD=y, plus the
# spin thread). Thread creation past the 4th returns an error -- raise this
# first if bring-up reports a failed pthread_create.
zephyr_compile_definitions(
    NROS_ZEPHYR_MAX_TIERS=1
    NROS_ZEPHYR_TIER_STACK_SIZE=4096
    NROS_ZEPHYR_MAX_THREADS=4)

# Per-node parameter pool sizing (nano-ros issue 0316 — an unknobbed pool).
# `ComponentNode` embeds `ParameterServer<NROS_COMPONENT_MAX_PARAMS, ...>` by
# value, so the default 256 scalar slots cost ~51 KiB of .bss PER NODE — 205 KiB
# across the island's four, on a part with 320 KiB of SRAM total. The busiest
# node (mrm_handler) declares 11 scalar parameters and none of the four declares
# a sequence parameter, so 16 slots leaves better than 45% headroom.
# Only overridable as a compile definition: the header guards each with #ifndef
# and nothing in CMake/Kconfig/env feeds them.
add_compile_definitions(
    NROS_COMPONENT_MAX_PARAMS=16
    NROS_COMPONENT_MAX_SEQ_PARAMS=2
    NROS_COMPONENT_SEQ_POOL_BYTES=512)

# Interface union first (one superset FFI archive — nano-ros #253), then the
# node component libs the model names.
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../island_interfaces" island_interfaces)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_emergency_stop_operator" autoware_mrm_emergency_stop_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_comfortable_stop_operator" autoware_mrm_comfortable_stop_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_stop_mode_operator" autoware_stop_mode_operator)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../autoware_mrm_handler" autoware_mrm_handler)

# Relocate the entry's .bss into DTCM. The S32K344 has 64 KiB ITCM + 128 KiB
# DTCM that this image otherwise leaves idle while SRAM runs near capacity. The
# app library's .bss is the executor storage (~68 KiB) plus the four per-node
# component buffers (~10 KiB) -- all CPU-only, which is the constraint that
# matters: TCM is NOT reachable by the DMA masters, so the Ethernet descriptors
# and the net_pkt/net_buf pools must stay in SRAM. Do not extend this to the
# net stack.
#
# REQUIRES patches/zephyr/0001-gen_relocate_app-fix-source-to-object-matching.
# Stock Zephyr 4.4 cannot relocate a source generated into the build root: its
# source-to-object matcher assumes the object tree mirrors the source tree, and
# on no match it writes an EMPTY fragment, prints nothing and exits 0. Without
# that patch this line links fine and relocates nothing.
#
# Verify by the DTCM line of the region report, never by the build succeeding.
zephyr_code_relocate(LIBRARY app LOCATION DTCM_BSS)

nano_ros_add_executable(zephyr_entry
    BOARD   zephyr
    MODEL   "${CMAKE_CURRENT_SOURCE_DIR}/../safety_island_bringup/config/system_model.yaml"
    TYPED
    DEPLOY  zephyr)
