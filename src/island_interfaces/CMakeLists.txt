cmake_minimum_required(VERSION 3.22)
# Union interface closure — see package.xml. No sources; the single
# nros_find_interfaces call here generates every msg pkg (topo order) and one
# superset FFI archive that all node pkgs / entries link.
project(island_interfaces LANGUAGES C CXX)

find_package(nano_ros REQUIRED)

nros_find_interfaces(LANGUAGE cpp SKIP_INSTALL
    CODEGEN_CONFIG "${CMAKE_CURRENT_SOURCE_DIR}/nros-codegen.toml")
