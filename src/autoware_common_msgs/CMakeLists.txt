cmake_minimum_required(VERSION 3.20)
project(autoware_common_msgs)

# Verbatim upstream ROS 2 msg-package shape — builds unchanged under colcon;
# the nano-ros build routes rosidl_generate_interfaces to its codegen pipeline.
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
    msg/ResponseStatus.msg
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
