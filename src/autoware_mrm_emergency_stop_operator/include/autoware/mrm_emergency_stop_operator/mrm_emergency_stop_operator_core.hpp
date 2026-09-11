// Copyright 2022 Tier IV, Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#ifndef AUTOWARE__MRM_EMERGENCY_STOP_OPERATOR__MRM_EMERGENCY_STOP_OPERATOR_CORE_HPP_
#define AUTOWARE__MRM_EMERGENCY_STOP_OPERATOR__MRM_EMERGENCY_STOP_OPERATOR_CORE_HPP_

// Autoware
#include <autoware_control_msgs/msg/control.hpp>
#include <tier4_system_msgs/msg/mrm_behavior_status.hpp>
#include <tier4_system_msgs/srv/operate_mrm.hpp>

// nano-ros port: <rclcpp/rclcpp.hpp> -> the nano-ros component surface.
// A component IS-A node since nano-ros 1f3b88aec, so the node derives
// nros::Node directly -- NodeWithTimers<1> because it owns one timer, and the
// timer pool is the base's template argument.
#include <nros/component.hpp>
// component_node.hpp used to pull this in; component.hpp does not, and the
// nros::Publisher<M> members below plus create_publisher_in need it complete.
#include <nros/publisher.hpp>
// The freestanding parameter forwarders the declare_parameter helper below
// calls (nros::Node hosts the same facade, but only under NROS_CPP_STD).
#include <nros/node_parameters.hpp>

namespace autoware::mrm_emergency_stop_operator
{
using autoware_control_msgs::msg::Control;
using tier4_system_msgs::msg::MrmBehaviorStatus;
using tier4_system_msgs::srv::OperateMrm;

struct Parameters
{
  int64_t update_rate;         // [Hz]  (nano-ros port: int → int64_t param type)
  double target_acceleration;  // [m/s^2]
  double target_jerk;          // [m/s^3]
};

class MrmEmergencyStopOperator : public ::nros::NodeWithTimers<1>
{
public:
  // nano-ros port: rclcpp::NodeOptions ctor → NodeHandle ctor (RFC-0044
  // "rclcpp" component shape; the generated entry constructs the node).
  explicit MrmEmergencyStopOperator(::nros::NodeHandle handle);

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
  // Parameters
  Parameters params_;

  // nano-ros port: add_on_set_parameters_callback / OnSetParametersCallbackHandle
  // not available — runtime reconfigure of target_acceleration/target_jerk is
  // dropped (porting-notes 03).

  // Subscriber
  // nano-ros port: the executor arena owns the subscription; the callback
  // takes const& instead of ConstSharedPtr (porting-notes 04).
  void onControlCommand(const Control & msg);

  // Server
  OperateMrm::Response operateEmergencyStop(const OperateMrm::Request & request);

  // Publisher
  ::nros::Publisher<MrmBehaviorStatus> pub_status_;
  ::nros::Publisher<Control> pub_control_cmd_;

  void publishStatus();
  void publishControlCommand(const Control & command);

  // Timer -- parked in the NodeWithTimers pool (NROS_CREATE_WALL_TIMER).
  void onTimer();

  // States
  MrmBehaviorStatus status_;
  Control prev_control_cmd_;
  bool is_prev_control_cmd_subscribed_;

  // Algorithm
  Control calcTargetAcceleration(const Control & prev_control_cmd) const;
};

}  // namespace autoware::mrm_emergency_stop_operator

#endif  // AUTOWARE__MRM_EMERGENCY_STOP_OPERATOR__MRM_EMERGENCY_STOP_OPERATOR_CORE_HPP_
