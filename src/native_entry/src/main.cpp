// Entry pkg — boots the safety-island topology on the native board.
// The CMake `nano_ros_add_executable(MODEL …)` call generates the real
// `int main()`; NROS_MAIN is a doc/IDE hint mirroring the declarative shape.

#include <nros/main.hpp>

NROS_MAIN(::nros::board::NativeBoard, "safety_island_bringup");
