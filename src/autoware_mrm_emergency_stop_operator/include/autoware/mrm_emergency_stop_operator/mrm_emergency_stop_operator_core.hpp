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

// nano-ros port: <rclcpp/rclcpp.hpp> → the nano-ros component surface.
// Services/parameters/clock are not in rclcpp_compat yet (porting-notes 01),
// so the node derives nros::ComponentNode (IS-A-node, rclcpp shape) instead
// of rclcpp::Node.
#include <nros/component.hpp>
#include <nros/component_node.hpp>

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

class MrmEmergencyStopOperator : public ::nros::ComponentNode
{
public:
  // nano-ros port: rclcpp::NodeOptions ctor → NodeHandle ctor (RFC-0044
  // "rclcpp" component shape; the generated entry constructs the node).
  explicit MrmEmergencyStopOperator(::nros::NodeHandle handle);

private:
  // Parameters
  Parameters params_;

  // nano-ros port: add_on_set_parameters_callback / OnSetParametersCallbackHandle
  // not available — runtime reconfigure of target_acceleration/target_jerk is
  // dropped (porting-notes 03).

  // Subscriber
  // nano-ros port: Subscription handles live in the ComponentNode base;
  // callback takes const& instead of ConstSharedPtr (porting-notes 04).
  void onControlCommand(const Control & msg);

  // Server
  OperateMrm::Response operateEmergencyStop(const OperateMrm::Request & request);

  // Publisher
  ::nros::Publisher<MrmBehaviorStatus> pub_status_;
  ::nros::Publisher<Control> pub_control_cmd_;

  void publishStatus();
  void publishControlCommand(const Control & command);

  // Timer — handle lives in the ComponentNode base (NROS_CREATE_WALL_TIMER).
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
