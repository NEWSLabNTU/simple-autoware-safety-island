// phase9-W9: the island's hazard-lights command, stamped by the host.
//
// vehicle_cmd_gate keeps its previous hazard command whenever a new one is
// stamped earlier (getContinuousTopic, autoware_vehicle_cmd_gate 1.5.0
// vehicle_cmd_gate.cpp:393-408). The board has no time source over the
// serial link, so the island stamps from boot: on the planning simulator
// (wall clock) every island command is "older" than the gate's last one and
// is dropped, and on CARLA (use_sim_time, /clock from CARLA) the order of a
// boot stamp and a simulation stamp is an accident. Either way the hazard
// lights depend on how two unrelated clocks compare.
//
// The fix keeps the island on its own clock and gives the gate one clock: the
// gate reads this node's output, which is the island's message with the stamp
// replaced by the host node's clock (simulation time when use_sim_time is
// set) at receipt. The stamp then says when the host learned the command, as
// any host-side producer's stamp does; no latency is computed from it. The
// island's own trace, its markers and its own stamps are unchanged.
#pragma once

#include <autoware_vehicle_msgs/msg/hazard_lights_command.hpp>
#include <builtin_interfaces/msg/time.hpp>

namespace island_restamp
{

// The message as received, with `now` as its stamp. Every other field is
// carried unchanged.
inline autoware_vehicle_msgs::msg::HazardLightsCommand restamp(
  const autoware_vehicle_msgs::msg::HazardLightsCommand & in,
  const builtin_interfaces::msg::Time & now)
{
  autoware_vehicle_msgs::msg::HazardLightsCommand out = in;
  out.stamp = now;
  return out;
}

}  // namespace island_restamp
