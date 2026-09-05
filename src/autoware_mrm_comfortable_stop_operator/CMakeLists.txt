cmake_minimum_required(VERSION 3.22)
# nano-ros port — same shape as autoware_mrm_emergency_stop_operator.
project(autoware_mrm_comfortable_stop_operator VERSION 0.48.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17) # upstream Autoware standard — nested namespaces port verbatim (RFC-0057)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(nano_ros REQUIRED)
find_package(autoware_internal_planning_msgs REQUIRED)
find_package(tier4_system_msgs REQUIRED)

nano_ros_auto_add_library(mrm_comfortable_stop_operator_lib STATIC src/mrm_comfortable_stop_operator/mrm_comfortable_stop_operator_core.cpp)

nros_components_register_node(mrm_comfortable_stop_operator_lib
    PLUGIN autoware::mrm_comfortable_stop_operator::MrmComfortableStopOperator
    EXECUTABLE mrm_comfortable_stop_operator
    HEADER autoware/mrm_comfortable_stop_operator/mrm_comfortable_stop_operator_core.hpp
    # phase-412 -- `ENTITIES` is retired. This node's subscriptions,
    # publishers and timer are stated in
    # safety_island_bringup/launch/safety_island.contract.yaml, beside the
    # launch file that runs it, and reach the pool sizing through the
    # resolved SystemModel. The list that used to live here was
    # hand-maintained with nothing comparing it to the code, and one of
    # them was short by a subscription the node creates.
)

# Topo-last superset interface lib only (porting-notes 08 / nano-ros #253).
