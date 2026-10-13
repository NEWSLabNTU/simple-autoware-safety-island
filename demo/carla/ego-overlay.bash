# shellcheck shell=bash
# Sourced by carla-scenario-bridge's `just ego-av` as EGO_OVERLAY (between
# Autoware and acb; just/carla.just sets it). Two things for the CARLA ego on
# rmw_zenoh_cpp (docs/design/carla-island-demo.md, unit C1):
#   * the island's overlay (build/l3-host-ws, `just l3-host-ws`): its
#     tier4_system_launch (stock MRM off, the availability converter's topic
#     and the diagnostic graph as arguments) and takeover_demo shadow Autoware's;
#   * the patched librclcpp (build/l3-host-rclcpp, `just carla-rclcpp`; trap 2b
#     of demo/l3/README.md) first on LD_LIBRARY_PATH, as the L3 image diverts it
#     over the packaged one. Missing, the ego still starts and the planner goes
#     silent on the first route; so refuse instead.
_ego_overlay_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$_ego_overlay_root/build/l3-host-ws/install/setup.bash"
_ego_rclcpp="$_ego_overlay_root/build/l3-host-rclcpp/install/rclcpp/lib"
if [ ! -f "$_ego_rclcpp/librclcpp.so" ]; then
    echo "ego-overlay: no patched rclcpp at $_ego_rclcpp -- run: just carla-rclcpp" >&2
    return 1
fi
export LD_LIBRARY_PATH="$_ego_rclcpp${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
unset _ego_overlay_root _ego_rclcpp
