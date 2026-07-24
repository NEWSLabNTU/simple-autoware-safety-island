// Entry pkg — boots the safety-island topology on the Zephyr board.
// The generated entry owns the real main; this is the doc/IDE hint.

#include <nros/main.hpp>

NROS_MAIN(::nros::board::ZephyrBoard, "safety_island_bringup");
