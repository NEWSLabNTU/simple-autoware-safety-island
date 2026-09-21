# Zephyr entry for the BOARD (MR-CANHUBK344, zenoh): all four ported Autoware
# nodes in one bootable image. Shape mirrors nano-ros examples/workspaces/
# mixed/src/zephyr_entry (C++-only variant -- no Rust node).
#
#   just board-build     (west build -b mr_canhubk3/s32k344 -S nros-zenoh ...)
#
# The native_sim / Cyclone image the demo runs is src/native_sim_entry, a
# SEPARATE entry package since the nano-ros bump of 2026-09-21: nano-ros
# resolves an image from its ENTRY PACKAGE (`nros image-facts --for-entry`)
# and refuses a west build whose Kconfig RMW disagrees with the image's `rmw`
# (cmake/NanoRosImageAgreement.cmake), so one entry cannot honestly be both a
# zenoh board image and a Cyclone native_sim image. This package used to be
# both, built two ways. Board-only policy -- the TCM relocation below,
# boards/, snippets/ -- stays here.

cmake_minimum_required(VERSION 3.20.0)

# Workspace-local msg pkgs resolve through the auto-emitted Find-stubs — the
# search path must be visible before nano_ros's stub machinery loads.
set(NROS_INTERFACE_SEARCH_PATH "${CMAKE_CURRENT_SOURCE_DIR}/..")

# Transport snippets live in this directory (snippets/island-serial,
# snippets/island-ethernet). Zephyr resolves SNIPPET_ROOT relative to the
# application but does NOT seed it with the application itself, so without this
# line `-S island-serial` fails with "unknown snippet" and the caller has to
# remember -DSNIPPET_ROOT on every build. Must precede find_package(Zephyr):
# snippets are processed during its boilerplate.
list(APPEND SNIPPET_ROOT ${CMAKE_CURRENT_SOURCE_DIR})

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(safety_island_zephyr_entry)

# RFC-0048: on Zephyr find_package(nano_ros) supplies the verbs + entry
# machinery; the nano-ros west module already provides the runtime.
#
# PIN IT TO THE SUBMODULE. Unpinned, find_package() is free to resolve
# nano_ros from anywhere on CMAKE_PREFIX_PATH -- on a machine that also has a
# standalone nano-ros checkout it silently picks that one up, and the build
# then uses ANOTHER tree's cmake verbs and codegen against THIS tree's sources.
# It fails far away from the cause: caps in nros-codegen.toml stop being
# applied, every type reads as unbounded, and the static_asserts fire on
# messages nobody touched. Diagnosed the long way once (seven separate
# detours); the tell is `nano_ros_DIR` in CMakeCache.txt naming a path outside
# this repo. An explicit -Dnano_ros_DIR= still wins, so this only supplies the
# default nobody should have to remember.
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

# Platform thread/tier stack pools: NOT set here. Kconfig owns them.
#
# This block used to call zephyr_compile_definitions() with
# NROS_ZEPHYR_MAX_TIERS=1, NROS_ZEPHYR_TIER_STACK_SIZE=4096 and
# NROS_ZEPHYR_MAX_THREADS=4, and the comment claimed the entry kept "one
# minimal slot". It did not. nano-ros emits the same three tokens from Kconfig
# (third-party/nano-ros/zephyr/CMakeLists.txt:97-108), so BOTH landed on every
# compile command and gcc warned three times per TU:
#
#   <command-line>: warning: "NROS_ZEPHYR_MAX_TIERS" redefined
#
# CMake sorts and de-duplicates the -D list, so which copy survives was decided
# by the lexicographic order of the whole token, not by call order. Measured in
# build-board/compile_commands.json, in this order:
#
#   -DNROS_ZEPHYR_MAX_THREADS=4      (here)      -DNROS_ZEPHYR_MAX_THREADS=5     (Kconfig, wins)
#   -DNROS_ZEPHYR_MAX_TIERS=1        (here)      -DNROS_ZEPHYR_MAX_TIERS=4       (Kconfig, wins)
#   -DNROS_ZEPHYR_TIER_STACK_SIZE=16384 (Kconfig) -DNROS_ZEPHYR_TIER_STACK_SIZE=4096 (here, wins)
#
# "16384" sorts before "4096", so the entry won exactly one of the three, by
# accident. The effective build was MAX_THREADS=5, MAX_TIERS=4,
# TIER_STACK_SIZE=4096, confirmed in build-board/zephyr/zephyr_pre0.map:
#
#   nros_thread_stacks    0xa000 = 5 x NROS_ZEPHYR_STACK_SIZE(8192)   LINKED
#   nros_tier_threads     0x440  = 4 x sizeof(struct k_thread)        discarded
#   the tier stack array  0x4000 = 4 x 4096                           discarded
#
# Both tier objects sit in the map's "Discarded input sections" list: this
# entry's system model declares no tier and the generated entry contains no
# tier spawn, so --gc-sections drops the pool whatever its size. That is why
# the redefinition was harmless HERE and cost 0 bytes -- not because the
# numbers agreed.
#
# So the definitions are deleted rather than reconciled. Both knobs have
# Kconfig rows with help text (nano-ros zephyr/Kconfig, NROS_ZEPHYR_TASK_SLOTS
# / NROS_ZEPHYR_MAX_TIERS / NROS_ZEPHYR_TIER_STACK_SIZE), and the board conf
# already sets CONFIG_NROS_ZEPHYR_TASK_SLOTS=5 with its reasoning. Set these
# from a .conf, next to the rest of this image's sizing; a value written here
# would only re-enter the same coin toss.

# Parameter pool sizing -- STALE SINCE nano-ros 1f3b88aec (phase-427 W4).
#
# This used to size an unknobbed pool (nano-ros issue 0316): `ComponentNode`
# embedded a `ParameterServer<NROS_COMPONENT_MAX_PARAMS, ...>` by value, so the
# default 256 scalar slots cost ~51 KiB of .bss PER NODE, and the three
# `add_compile_definitions` below were the only way to shrink it (the header
# guarded each with #ifndef; nothing in CMake/Kconfig/env fed them otherwise).
#
# `ComponentNode` is gone, and with it that embed. `NROS_COMPONENT_MAX_PARAMS`,
# `NROS_COMPONENT_MAX_SEQ_PARAMS` and `NROS_COMPONENT_SEQ_POOL_BYTES` are not
# read by any nano-ros header any more -- the three lines this comment used to
# introduce are inert now, which is why they are gone too. Parameters live in
# ONE store the EXECUTOR owns (shared across every node on it, so `ros2 param
# get` and a sibling node both see what one node declared), sized by the
# Rust-side `NROS_MAX_PARAMETERS` knob (crate default 32) -- on Zephyr that is
# `CONFIG_NROS_MAX_PARAMETERS` in prj.conf, `-1` (derive from the system
# contract's declared `params:`) by Kconfig default, falling to the crate
# default where the contract declares none. Sizing that pool for this entry's
# four nodes is unstarted; it is not a compile definition here any more.

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

# ---------------------------------------------------------------------------
# ITCM: the safety application's own code.
#
# WHAT THIS BUYS. The I-cache is already on (CONFIG_ICACHE=y), so this is NOT a
# throughput win -- a hot loop already runs near zero-wait out of cache. What
# ITCM changes is DETERMINISM and cache pressure. The M7's I-cache is small
# against 421 KiB of text, so the MRM decision path competes for lines with the
# net stack, the shell and the Rust executor, and a decision that follows an
# idle period pays flash wait states on every miss. Code in ITCM is
# zero-wait-state ALWAYS, with no miss to jitter the response, and it stops
# occupying cache lines the rest of the image can then use. For a safety island
# the worst case is the number that matters, not the average.
#
# WHAT GOES HERE. The four MRM node bodies: 12,816 B measured, 19.6% of the
# region. NOT the Rust executor and NOT the net stack -- the net stack's buffers
# must stay DMA-reachable (see above; the same DMA constraint applies to ITCM).
#
# Be accurate about the granularity: LIBRARY moves the WHOLE library, so each
# node's constructor rides along even though it runs exactly once. That is a few
# KiB of one-shot code holding ITCM for the life of the image. It is accepted
# rather than filtered: 51 KiB of the region is still free, and the FILTER
# argument takes a regex over MANGLED C++ names, which stops matching on any
# rename and then relocates nothing while still linking green -- the same silent
# failure documented for the DTCM line above. A brittle filter is worse than a
# few KiB here.
#
# ORDER MATTERS: _TEXT is a COPY. The section is loaded in flash and copied to
# ITCM by z_data_copy() before main(), so it costs FLASH as well as ITCM, and
# nothing in it may run before that copy.
#
# Verify by the ITCM line of the region report, never by the build succeeding --
# the same silent-empty-fragment failure mode as the DTCM line above.
#
# NOT YET RUN ON SILICON. This links, places and reports correctly (ITCM 12,816 B,
# .itcm_text_reloc VMA 0x0 / LMA 0x004007fc), but no MR-CANHUBK344 has executed
# it -- the board is still blocked on the MCU-Link probe. The boot-time copy is
# exactly the thing a linker cannot check.
#
# TCM ECC needs no action from us: mr_canhubk3_common.dtsi already chooses both
# TCMs, so the 64-bit ECC init loops in soc_early_reset_hook are compiled in.
# See docs/tcm-relocation.md -- reading only mr_canhubk3.dts suggests otherwise
# and is wrong.
zephyr_code_relocate(LIBRARY mrm_handler_lib                   LOCATION ITCM_TEXT)
zephyr_code_relocate(LIBRARY stop_mode_operator_lib            LOCATION ITCM_TEXT)
zephyr_code_relocate(LIBRARY mrm_emergency_stop_operator_lib   LOCATION ITCM_TEXT)
zephyr_code_relocate(LIBRARY mrm_comfortable_stop_operator_lib LOCATION ITCM_TEXT)

# phase-405 W4 retired MODEL, which named a RESOLVED artifact directly and so
# let the entry be built from a stale system_model.yaml. BRINGUP names the
# package instead, and the launch file inside it is what gets resolved -- the
# launch tree is the source of truth for the node/topic structure, not a
# checked-in resolution of it.
nano_ros_add_executable(zephyr_entry
    BOARD   zephyr
    BRINGUP "${CMAKE_CURRENT_SOURCE_DIR}/../safety_island_bringup"
    TYPED
    DEPLOY  zephyr)
