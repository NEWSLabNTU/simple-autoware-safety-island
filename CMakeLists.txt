cmake_minimum_required(VERSION 3.22)

project(autoware_safety_island_example LANGUAGES C CXX)

# nano-ros 3-role workspace (RFC-0048): vendored msg pkgs + ported Node pkgs
# + bringup + entries. Resolve nano-ros via -DNANO_ROS_ROOT=<checkout>.
#
# Workspace build:
#     cmake -S . -B build -DNANO_ROS_ROOT=/path/to/nano-ros && cmake --build build
# Standalone solo build of any subdir:
#     cmake -S src/<pkg> -B build -DNANO_ROS_ROOT=/path/to/nano-ros

# Workspace-local msg pkgs (the vendored autoware_*/tier4_* subsets) resolve
# through auto-emitted Find-stubs scanned from this path — must be set BEFORE
# nano_ros is imported (Phase 210.A.4).
set(NROS_INTERFACE_SEARCH_PATH "${CMAKE_CURRENT_SOURCE_DIR}/src")

find_package(nano_ros REQUIRED COMPONENTS workspace)

# One platform per configure. Default posix (native dev loop); the Zephyr
# entry (phase 4) builds through west against the zephyr platform instead.
if(NOT NANO_ROS_PLATFORM)
    set(NANO_ROS_PLATFORM posix)
endif()

# NOTE: the vendored msg pkgs (src/autoware_*_msgs, src/tier4_system_msgs) are
# NOT CMake subdirs — nano-ros resolves them from each Node pkg's package.xml
# <depend> closure via the NROS_INTERFACE_SEARCH_PATH auto-stubs; their
# CMakeLists.txt exists only so they still build verbatim under colcon.
set(_ws_subdirs
    # FIRST: union interface closure (one superset FFI archive — see
    # src/island_interfaces/package.xml + nano-ros issue 0253).
    src/island_interfaces

    # Ported node packages
    src/autoware_mrm_emergency_stop_operator          # P1
    src/autoware_mrm_comfortable_stop_operator        # P2
    src/autoware_stop_mode_operator                   # P2
    # src/autoware_mrm_handler                        # P3
)

if(NANO_ROS_PLATFORM STREQUAL "posix")
    list(APPEND _ws_subdirs
        src/native_entry)
endif()

nano_ros_workspace(
    BACKEND  cyclonedds
    PLATFORM "${NANO_ROS_PLATFORM}"
    SUBDIRS  ${_ws_subdirs})
