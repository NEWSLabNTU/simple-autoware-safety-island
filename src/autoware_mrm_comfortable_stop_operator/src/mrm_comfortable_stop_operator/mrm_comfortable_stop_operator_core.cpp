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

#include "autoware/mrm_comfortable_stop_operator/mrm_comfortable_stop_operator_core.hpp"

#include <cstring>

// nano-ros port: platform monotonic stamps (porting-notes 05).
namespace
{
builtin_interfaces::msg::Time now_stamp()
{
  const uint64_t ns = nros_cpp_time_ns();
  builtin_interfaces::msg::Time t;
  t.sec = static_cast<int32_t>(ns / 1000000000ull);
  t.nanosec = static_cast<uint32_t>(ns % 1000000000ull);
  return t;
}
}  // namespace

namespace autoware::mrm_comfortable_stop_operator
{

MrmComfortableStopOperator::MrmComfortableStopOperator(::nros::NodeHandle handle)
: ::nros::ComponentNode(handle, "mrm_comfortable_stop_operator")
{
  // Parameter — upstream config/mrm_comfortable_stop_operator.param.yaml
  // values as node-local defaults (porting-notes 06).
  params_.update_rate = declare_parameter<int64_t>("update_rate", 10);
  params_.min_acceleration = declare_parameter<double>("min_acceleration", -1.0);
  params_.max_jerk = declare_parameter<double>("max_jerk", 0.3);
  params_.min_jerk = declare_parameter<double>("min_jerk", -0.3);

  // Server — resolved contract name (porting-notes 07):
  //   ~/input/mrm/comfortable_stop/operate → /system/mrm/comfortable_stop/operate
  ::nros::bind_service<tier4_system_msgs::srv::OperateMrm, MrmComfortableStopOperator,
                       &MrmComfortableStopOperator::operateComfortableStop>(
    node(), "/system/mrm/comfortable_stop/operate", this);

  // Publisher
  //   ~/output/mrm/comfortable_stop/status → /system/mrm/comfortable_stop/status
  //   ~/output/velocity_limit              → /planning/scenario_planning/max_velocity_candidates
  //   ~/output/velocity_limit/clear        → /planning/scenario_planning/clear_velocity_limit
  pub_status_ = create_publisher<tier4_system_msgs::msg::MrmBehaviorStatus>(
    "/system/mrm/comfortable_stop/status");
  pub_velocity_limit_ = create_publisher<autoware_internal_planning_msgs::msg::VelocityLimit>(
    "/planning/scenario_planning/max_velocity_candidates",
    ::nros::QoS(1).transient_local());
  pub_velocity_limit_clear_command_ =
    create_publisher<autoware_internal_planning_msgs::msg::VelocityLimitClearCommand>(
      "/planning/scenario_planning/clear_velocity_limit",
      ::nros::QoS(1).transient_local());

  // Timer
  NROS_CREATE_WALL_TIMER(static_cast<uint64_t>(1000 / params_.update_rate), onTimer);

  // Initialize
  status_ = {};
  status_.state = tier4_system_msgs::msg::MrmBehaviorStatus::AVAILABLE;
}

tier4_system_msgs::srv::OperateMrm::Response MrmComfortableStopOperator::operateComfortableStop(
  const tier4_system_msgs::srv::OperateMrm::Request & request)
{
  // nano-ros port: value-init — generated structs are PODs (porting-notes 09).
  tier4_system_msgs::srv::OperateMrm::Response response{};
  if (request.operate == true) {
    publishVelocityLimit();
    status_.state = tier4_system_msgs::msg::MrmBehaviorStatus::OPERATING;
    response.response.success = true;
  } else {
    publishVelocityLimitClearCommand();
    status_.state = tier4_system_msgs::msg::MrmBehaviorStatus::AVAILABLE;
    response.response.success = true;
  }
  return response;
}

void MrmComfortableStopOperator::publishStatus()
{
  auto status = status_;
  status.stamp = now_stamp();
  pub_status_.publish(status);
}

void MrmComfortableStopOperator::publishVelocityLimit()
{
  // nano-ros port: value-init (porting-notes 09); string field via FixedString
  // assignment.
  auto velocity_limit = autoware_internal_planning_msgs::msg::VelocityLimit{};
  velocity_limit.stamp = now_stamp();
  velocity_limit.max_velocity = 0;
  velocity_limit.use_constraints = true;
  velocity_limit.constraints.min_acceleration = static_cast<float>(params_.min_acceleration);
  velocity_limit.constraints.max_jerk = static_cast<float>(params_.max_jerk);
  velocity_limit.constraints.min_jerk = static_cast<float>(params_.min_jerk);
  velocity_limit.sender = "mrm_comfortable_stop_operator";

  pub_velocity_limit_.publish(velocity_limit);
}

void MrmComfortableStopOperator::publishVelocityLimitClearCommand()
{
  auto velocity_limit_clear_command =
    autoware_internal_planning_msgs::msg::VelocityLimitClearCommand{};
  velocity_limit_clear_command.stamp = now_stamp();
  velocity_limit_clear_command.command = true;
  velocity_limit_clear_command.sender = "mrm_comfortable_stop_operator";

  pub_velocity_limit_clear_command_.publish(velocity_limit_clear_command);
}

void MrmComfortableStopOperator::onTimer()
{
  publishStatus();
}

}  // namespace autoware::mrm_comfortable_stop_operator

// nano-ros port: RCLCPP_COMPONENTS_REGISTER_NODE → NROS_COMPONENT.
NROS_COMPONENT(autoware::mrm_comfortable_stop_operator::MrmComfortableStopOperator);
