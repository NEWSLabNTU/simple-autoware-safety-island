cmake_minimum_required(VERSION 3.14)
# Overlay-shadow of the installed tier4_planning_launch: identical except the
# manual_lane_change_handler include is removed — its endpoints are the prime
# suspect for the island abort (nano-ros issue 0371): the demo passed on
# 2026-07-31 while this node happened to be crashed (sim 32/33), and fails
# deterministically with it healthy (33/33).
project(tier4_planning_launch)
find_package(ament_cmake REQUIRED)
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})
ament_package()
