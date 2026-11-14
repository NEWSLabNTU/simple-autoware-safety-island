cmake_minimum_required(VERSION 3.20)
project(tier4_system_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(autoware_common_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
    msg/EmergencyHoldingState.msg
    msg/MrmBehaviorStatus.msg
    msg/OperationModeAvailability.msg
    srv/OperateMrm.srv
    # Autoware 2.0.0 (tier4_system_msgs 0.53.0): the command mode messages of
    # command_mode_decider / command_mode_switcher / control_command_gate and
    # the in-lane stop trigger, named by the L4 island contract (island #17).
    msg/CommandModeAvailability.msg
    msg/CommandModeAvailabilityItem.msg
    msg/CommandModeRequest.msg
    msg/CommandModeRequestItem.msg
    msg/CommandModeStatus.msg
    msg/CommandModeStatusItem.msg
    msg/CommandSourceStatus.msg
    msg/InLaneStopTrigger.msg
    srv/SelectCommandSource.srv
    DEPENDENCIES builtin_interfaces autoware_common_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
