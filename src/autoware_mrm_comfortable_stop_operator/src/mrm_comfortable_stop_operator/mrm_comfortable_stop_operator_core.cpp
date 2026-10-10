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
#include <nros/clock.hpp>

#include <cstring>

// phase7-W1 trace markers (no-op unless the image enables CTF tracing).
#include "../../../safety_island_tracing/include/island_trace.h"

// nano-ros port: platform monotonic stamps (porting-notes 05).
namespace
{
// phase8-W18: a STAMP is read by the host, so it comes from the wall clock
// when the image has one (nano-ros issue 0758: the SNTP epoch, installed
// before any component is constructed). Autoware's vehicle_cmd_gate keeps its
// previous hazard/turn/gear command when the new one is stamped earlier
// (getContinuousTopic), so a boot-relative stamp is silently dropped. With no
// epoch the system clock reads 0 and the stamp stays monotonic, knowingly.
// Durations (now_sec) stay on the monotonic clock either way.
builtin_interfaces::msg::Time now_stamp()
{
  const int64_t wall = ::rclcpp::Clock(NROS_CLOCK_SYSTEM_TIME).now().nanoseconds();
  const uint64_t ns = wall > 0 ? static_cast<uint64_t>(wall) : nros_cpp_time_ns();
  builtin_interfaces::msg::Time t;
  t.sec = static_cast<int32_t>(ns / 1000000000ull);
  t.nanosec = static_cast<uint32_t>(ns % 1000000000ull);
  return t;
}
}  // namespace

namespace autoware::mrm_comfortable_stop_operator
{

MrmComfortableStopOperator::MrmComfortableStopOperator(::rclcpp::NodeHandle handle)
: ::rclcpp::NodeWithTimers<1>(handle, "mrm_comfortable_stop_operator")
{
  // Parameter — upstream config/mrm_comfortable_stop_operator.param.yaml
  // values as node-local defaults (porting-notes 06).
  params_.update_rate = declare_parameter<int64_t>("update_rate", 10);
  params_.min_acceleration = declare_parameter<double>("min_acceleration", -1.0);
  params_.max_jerk = declare_parameter<double>("max_jerk", 0.3);
  params_.min_jerk = declare_parameter<double>("min_jerk", -0.3);

  // Server — resolved contract name (porting-notes 07):
  //   ~/input/mrm/comfortable_stop/operate → /system/mrm/comfortable_stop/operate
  ::rclcpp::bind_service<tier4_system_msgs::srv::OperateMrm, MrmComfortableStopOperator,
                       &MrmComfortableStopOperator::operateComfortableStop>(
    *this, "/system/mrm/comfortable_stop/operate", this);

  // Publisher
  //   ~/output/mrm/comfortable_stop/status → /system/mrm/comfortable_stop/status
  //   ~/output/velocity_limit              → /planning/scenario_planning/max_velocity_candidates
  //   ~/output/velocity_limit/clear        → /planning/scenario_planning/clear_velocity_limit
  pub_status_ = create_publisher_in<tier4_system_msgs::msg::MrmBehaviorStatus>(
    "/system/mrm/comfortable_stop/status");
  pub_velocity_limit_ = create_publisher_in<autoware_internal_planning_msgs::msg::VelocityLimit>(
    "/planning/scenario_planning/max_velocity_candidates",
    ::rclcpp::QoS(1).transient_local());
  pub_velocity_limit_clear_command_ =
    create_publisher_in<autoware_internal_planning_msgs::msg::VelocityLimitClearCommand>(
      "/planning/scenario_planning/clear_velocity_limit",
      ::rclcpp::QoS(1).transient_local());

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
  ISLAND_TRACE(ISLAND_MK_SERVE_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE_ENTRY, request.operate);
  // phase8-W7: the contract's `operate` path (a service callback that
  // publishes the velocity limit, the comfortable rung's safe state) is this
  // callback taking an operate=1 request.
  ISLAND_TRACE(ISLAND_MK_TAKE_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE, request.operate);
  if (request.operate == true) {
    ISLAND_TRACE(ISLAND_MK_PATH_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE_ENTRY, status_.state);
    publishVelocityLimit();
    status_.state = tier4_system_msgs::msg::MrmBehaviorStatus::OPERATING;
    response.response.success = true;
    ISLAND_TRACE(ISLAND_MK_PATH_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE_EXIT, status_.state);
  } else {
    publishVelocityLimitClearCommand();
    status_.state = tier4_system_msgs::msg::MrmBehaviorStatus::AVAILABLE;
    response.response.success = true;
  }
  ISLAND_TRACE(ISLAND_MK_SERVE_MRM_COMFORTABLE_STOP_OPERATOR_OPERATE_EXIT, status_.state);
  return response;
}

void MrmComfortableStopOperator::publishStatus()
{
  auto status = status_;
  status.stamp = now_stamp();
  ISLAND_TRACE(ISLAND_MK_PUB_MRM_COMFORTABLE_STOP_OPERATOR_STATUS, status.state);
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

  ISLAND_TRACE(ISLAND_MK_PUB_MRM_COMFORTABLE_STOP_OPERATOR_MAX_VELOCITY_CANDIDATES, 0);
  pub_velocity_limit_.publish(velocity_limit);
}

void MrmComfortableStopOperator::publishVelocityLimitClearCommand()
{
  auto velocity_limit_clear_command =
    autoware_internal_planning_msgs::msg::VelocityLimitClearCommand{};
  velocity_limit_clear_command.stamp = now_stamp();
  velocity_limit_clear_command.command = true;
  velocity_limit_clear_command.sender = "mrm_comfortable_stop_operator";

  ISLAND_TRACE(ISLAND_MK_PUB_MRM_COMFORTABLE_STOP_OPERATOR_CLEAR_VELOCITY_LIMIT, 0);
  pub_velocity_limit_clear_command_.publish(velocity_limit_clear_command);
}

void MrmComfortableStopOperator::onTimer()
{
  ISLAND_TRACE(ISLAND_MK_PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER_ENTRY, status_.state);
  publishStatus();
  ISLAND_TRACE(ISLAND_MK_PATH_MRM_COMFORTABLE_STOP_OPERATOR_ON_TIMER_EXIT, status_.state);
}

}  // namespace autoware::mrm_comfortable_stop_operator

// nano-ros port: RCLCPP_COMPONENTS_REGISTER_NODE → NROS_COMPONENT.
NROS_COMPONENT(autoware::mrm_comfortable_stop_operator::MrmComfortableStopOperator);
