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

#ifndef AUTOWARE__MRM_COMFORTABLE_STOP_OPERATOR__MRM_COMFORTABLE_STOP_OPERATOR_CORE_HPP_
#define AUTOWARE__MRM_COMFORTABLE_STOP_OPERATOR__MRM_COMFORTABLE_STOP_OPERATOR_CORE_HPP_

// Autoware
#include <autoware_internal_planning_msgs/msg/velocity_limit.hpp>
#include <autoware_internal_planning_msgs/msg/velocity_limit_clear_command.hpp>
#include <autoware_internal_planning_msgs/msg/velocity_limit_constraints.hpp>
#include <tier4_system_msgs/msg/mrm_behavior_status.hpp>
#include <tier4_system_msgs/srv/operate_mrm.hpp>

// nano-ros port: <rclcpp/rclcpp.hpp> → nros::ComponentNode (porting-notes 01).
#include <nros/component.hpp>
#include <nros/component_node.hpp>

// nano-ros port: namespace flattened to the pkg name (identity rule,
// porting-notes 02).
namespace autoware_mrm_comfortable_stop_operator
{

struct Parameters
{
  int64_t update_rate;      // [Hz]  (nano-ros port: int → int64_t param type)
  double min_acceleration;  // [m/s^2]
  double max_jerk;          // [m/s^3]
  double min_jerk;          // [m/s^3]
};

class MrmComfortableStopOperator : public ::nros::ComponentNode
{
public:
  // nano-ros port: NodeOptions ctor → NodeHandle ctor (porting-notes 01).
  explicit MrmComfortableStopOperator(::nros::NodeHandle handle);

private:
  // Parameters
  Parameters params_;

  // Server (porting-notes 01/04: Response-returning member, bound via
  // nros::bind_service)
  tier4_system_msgs::srv::OperateMrm::Response operateComfortableStop(
    const tier4_system_msgs::srv::OperateMrm::Request & request);

  // nano-ros port: add_on_set_parameters_callback dropped (porting-notes 03).

  // Publisher
  ::nros::Publisher<tier4_system_msgs::msg::MrmBehaviorStatus> pub_status_;
  ::nros::Publisher<autoware_internal_planning_msgs::msg::VelocityLimit> pub_velocity_limit_;
  ::nros::Publisher<autoware_internal_planning_msgs::msg::VelocityLimitClearCommand>
    pub_velocity_limit_clear_command_;

  void publishStatus();
  void publishVelocityLimit();
  void publishVelocityLimitClearCommand();

  // Timer — handle lives in the ComponentNode base (NROS_CREATE_TIMER).
  void onTimer();

  // States
  tier4_system_msgs::msg::MrmBehaviorStatus status_;
};

}  // namespace autoware_mrm_comfortable_stop_operator

#endif  // AUTOWARE__MRM_COMFORTABLE_STOP_OPERATOR__MRM_COMFORTABLE_STOP_OPERATOR_CORE_HPP_
