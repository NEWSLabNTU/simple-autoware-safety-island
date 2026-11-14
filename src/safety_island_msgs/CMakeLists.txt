cmake_minimum_required(VERSION 3.20)
project(safety_island_msgs)

# ROS 2 (colcon) build of the island's L4 messages. nano-ros does not use this
# file: it resolves the package from package.xml through the workspace's
# NROS_INTERFACE_SEARCH_PATH, like the vendored Autoware subsets beside it.

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
    # RFC section 8.1, HPC -> island
    msg/HpcHeartbeat.msg
    msg/HpcCapability.msg
    msg/ActiveOdd.msg
    msg/OddStatus.msg
    msg/SafetyCorridor.msg
    msg/PullOverRefuge.msg
    # RFC section 8.2, island -> HPC
    msg/IslandState.msg
    msg/SafetyWorldState.msg
    msg/SensorHealth.msg
    msg/IslandSensorHealth.msg
    msg/OddVerdict.msg
    msg/FallbackAvailability.msg
    msg/SafetyEnvelopeCommand.msg
    # island-internal (RFC sections 6.1, 6.2, 8.4)
    msg/LaneBoundaries.msg
    msg/RadarTrack.msg
    msg/RadarTracks.msg
    msg/SensorState.msg
    msg/SafetyEvent.msg
    msg/FaultVerdict.msg
    DEPENDENCIES builtin_interfaces geometry_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
