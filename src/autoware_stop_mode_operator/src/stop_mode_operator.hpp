//  Copyright 2025 The Autoware Contributors
//
//  Licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
//  Unless required by applicable law or agreed to in writing, software
//  distributed under the License is distributed on an "AS IS" BASIS,
//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//  See the License for the specific language governing permissions and
//  limitations under the License.

#ifndef STOP_MODE_OPERATOR_HPP_
#define STOP_MODE_OPERATOR_HPP_

#include "continuous_condition.hpp"

// nano-ros port: <rclcpp/rclcpp.hpp> -> nros::Node (porting-notes 01). A
// component IS-A node since nano-ros 1f3b88aec; the timer pool is the base's
// template argument, so a node with one timer derives NodeWithTimers<1>.
#include <nros/component.hpp>
// component_node.hpp used to pull this in; component.hpp does not, and the
// nros::Publisher<M> members below plus create_publisher_in need it complete.
#include <nros/publisher.hpp>
// The freestanding parameter forwarders the declare_parameter helper below
// calls (nros::Node hosts the same facade, but only under NROS_CPP_STD).
#include <nros/node_parameters.hpp>

#include <autoware_control_msgs/msg/control.hpp>
#include <autoware_planning_msgs/msg/route_state.hpp>
#include <autoware_vehicle_msgs/msg/gear_command.hpp>
#include <autoware_vehicle_msgs/msg/hazard_lights_command.hpp>
#include <autoware_vehicle_msgs/msg/steering_report.hpp>
#include <autoware_vehicle_msgs/msg/turn_indicators_command.hpp>
#include <autoware_vehicle_msgs/msg/velocity_report.hpp>

namespace autoware::stop_mode_operator
{

using autoware_control_msgs::msg::Control;
using autoware_planning_msgs::msg::RouteState;
using autoware_vehicle_msgs::msg::GearCommand;
using autoware_vehicle_msgs::msg::HazardLightsCommand;
using autoware_vehicle_msgs::msg::SteeringReport;
using autoware_vehicle_msgs::msg::TurnIndicatorsCommand;
using autoware_vehicle_msgs::msg::VelocityReport;

class StopModeOperator : public ::nros::NodeWithTimers<1>
{
public:
  // nano-ros port: NodeOptions ctor → NodeHandle ctor (porting-notes 01).
  explicit StopModeOperator(::nros::NodeHandle handle);

private:

  // nano-ros port: the parameter facade `ComponentNode` carried unconditionally
  // now lives on `nros::Node` behind NROS_CPP_NODE_HOSTED, which nano-ros
  // phase-438 W2 made an opt-in (`NROS_CPP_STD`) this node cannot take: the
  // same sources build for Zephyr, whose minimal libcpp has no <memory> /
  // <string> / <vector>. Same shape, same store -- the freestanding forwarders
  // onto the executor's parameter server, which is what the retired facade
  // called too.
  template <typename T>
  T declare_parameter(const char * name, T default_value = T{})
  {
    const nros_cpp_node_t * h = ffi_handle();
    const ::nros::Result r = ::nros::detail::node_param_declare(h, name, default_value);
    // A launch-seeded parameter is declared before this ctor runs, so a
    // re-declare adopts the override instead of failing.
    if (!r.ok() && r.code() != ::nros::ErrorCode::AlreadyExists) {
      set_error("declare_parameter", r.raw());
      return default_value;
    }
    T out{};
    const ::nros::Result g = ::nros::detail::node_param_get(h, name, out);
    if (!g.ok()) {
      set_error("declare_parameter(read-back)", g.raw());
      return default_value;
    }
    return out;
  }
  void on_timer();
  void publish_control_command();
  void publish_gear_command();
  void publish_turn_indicators_command();
  void publish_hazard_lights_command();

  // nano-ros port: upstream binds lambdas; nano-ros subscriptions are typed
  // member callbacks (porting-notes 04).
  void on_steering(const SteeringReport & msg);
  void on_velocity(const VelocityReport & msg);
  void on_route_state(const RouteState & msg);

  ::nros::Publisher<Control> pub_control_;
  ::nros::Publisher<GearCommand> pub_gear_;
  ::nros::Publisher<TurnIndicatorsCommand> pub_turn_indicators_;
  ::nros::Publisher<HazardLightsCommand> pub_hazard_lights_;

  SteeringReport current_steering_;
  RouteState current_route_state_;
  ContinuousCondition vehicle_stop_check_;

  double stop_hold_acceleration_;
  bool enable_auto_parking_;

  static constexpr double vehicle_stop_duration_ = 1.0;
  static constexpr double vehicle_stop_timeout_ = 1.0;
};

}  // namespace autoware::stop_mode_operator

#endif  // STOP_MODE_OPERATOR_HPP_
