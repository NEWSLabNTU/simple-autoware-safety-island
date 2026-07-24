cmake_minimum_required(VERSION 3.14)
# Overlay-shadow of the installed tier4_system_launch: identical except the
# MRM operator/handler includes are removed (the safety island provides MRM).
project(tier4_system_launch)
find_package(ament_cmake REQUIRED)
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
ament_package()
