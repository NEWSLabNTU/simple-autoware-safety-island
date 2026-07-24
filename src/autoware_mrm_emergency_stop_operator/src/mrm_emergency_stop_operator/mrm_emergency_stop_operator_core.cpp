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

#include "autoware/mrm_emergency_stop_operator/mrm_emergency_stop_operator_core.hpp"

#include <algorithm>

// nano-ros port: no rclcpp::Clock — stamps come from the platform monotonic
// clock (nros_cpp_time_ns), and dt is computed from message stamps
// (porting-notes 05).
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

double seconds_since(const builtin_interfaces::msg::Time & then)
{
  const auto now = now_stamp();
  return (static_cast<double>(now.sec) - static_cast<double>(then.sec)) +
         (static_cast<double>(now.nanosec) - static_cast<double>(then.nanosec)) * 1e-9;
}
}  // namespace

namespace autoware_mrm_emergency_stop_operator
{

MrmEmergencyStopOperator::MrmEmergencyStopOperator(::nros::NodeHandle handle)
: ::nros::ComponentNode(handle, "mrm_emergency_stop_operator")
{
  // Parameter
  // nano-ros port: upstream declares these without defaults (values injected
  // by the launch param file). nano-ros params are node-local; the upstream
  // config/mrm_emergency_stop_operator.param.yaml values are the defaults
  // (porting-notes 06).
  params_.update_rate = declare_parameter<int64_t>("update_rate", 30);
  params_.target_acceleration = declare_parameter<double>("target_acceleration", -2.5);
  params_.target_jerk = declare_parameter<double>("target_jerk", -1.5);

  // Subscriber
  // nano-ros port: topic names are the resolved contract names — nano-ros
  // parses launch remaps but does not route them yet, and `~/` private
  // expansion is unsupported (porting-notes 07). Upstream:
  //   ~/input/control/control_cmd  → /control/command/control_cmd
  NROS_SUBSCRIBE(Control, onControlCommand, "/control/command/control_cmd");

  // Server
  //   ~/input/mrm/emergency_stop/operate → /system/mrm/emergency_stop/operate
  ::nros::bind_service<OperateMrm, MrmEmergencyStopOperator,
                       &MrmEmergencyStopOperator::operateEmergencyStop>(
    node(), "/system/mrm/emergency_stop/operate", this);

  // Publisher
  //   ~/output/mrm/emergency_stop/status      → /system/mrm/emergency_stop/status
  //   ~/output/mrm/emergency_stop/control_cmd → /system/emergency/control_cmd
  pub_status_ = create_publisher<MrmBehaviorStatus>("/system/mrm/emergency_stop/status");
  pub_control_cmd_ = create_publisher<Control>("/system/emergency/control_cmd");

  // Timer
  NROS_CREATE_TIMER(static_cast<uint64_t>(1000 / params_.update_rate), onTimer);

  // Initialize
  status_.state = MrmBehaviorStatus::AVAILABLE;
  is_prev_control_cmd_subscribed_ = false;

  // nano-ros port: parameter update callback (add_on_set_parameters_callback +
  // autoware_utils::update_param) dropped — see porting-notes 03.
}

void MrmEmergencyStopOperator::onControlCommand(const Control & msg)
{
  if (status_.state != MrmBehaviorStatus::OPERATING) {
    prev_control_cmd_ = msg;
    is_prev_control_cmd_subscribed_ = true;
  }
}

OperateMrm::Response MrmEmergencyStopOperator::operateEmergencyStop(
  const OperateMrm::Request & request)
{
  // nano-ros port: value-init — generated message structs are plain PODs
  // (no zeroing ctor, unlike rosidl C++ which zero-initializes); a default
  // init here leaked stack garbage into response.code (porting-notes 09).
  OperateMrm::Response response{};
  if (request.operate == true) {
    status_.state = MrmBehaviorStatus::OPERATING;
    response.response.success = true;
  } else {
    status_.state = MrmBehaviorStatus::AVAILABLE;
    response.response.success = true;
  }
  return response;
}

void MrmEmergencyStopOperator::publishStatus()
{
  auto status = status_;
  status.stamp = now_stamp();
  pub_status_.publish(status);
}

void MrmEmergencyStopOperator::publishControlCommand(const Control & command)
{
  pub_control_cmd_.publish(command);
}

void MrmEmergencyStopOperator::onTimer()
{
  if (status_.state == MrmBehaviorStatus::OPERATING) {
    auto control_cmd = calcTargetAcceleration(prev_control_cmd_);
    publishControlCommand(control_cmd);
    prev_control_cmd_ = control_cmd;
  } else {
    publishControlCommand(prev_control_cmd_);
  }
  publishStatus();
}

Control MrmEmergencyStopOperator::calcTargetAcceleration(const Control & prev_control_cmd) const
{
  auto control_cmd = Control();

  if (!is_prev_control_cmd_subscribed_) {
    control_cmd.stamp = now_stamp();
    control_cmd.longitudinal.stamp = now_stamp();
    control_cmd.longitudinal.velocity = 0.0;
    control_cmd.longitudinal.acceleration = static_cast<float>(params_.target_acceleration);
    control_cmd.longitudinal.jerk = 0.0;
    control_cmd.lateral.stamp = now_stamp();
    control_cmd.lateral.steering_tire_angle = 0.0;
    control_cmd.lateral.steering_tire_rotation_rate = 0.0;
    return control_cmd;
  }

  control_cmd = prev_control_cmd;
  // nano-ros port: (this->now() - prev.stamp).seconds() → stamp helper.
  const auto dt = seconds_since(prev_control_cmd.stamp);

  control_cmd.stamp = now_stamp();
  control_cmd.longitudinal.stamp = control_cmd.stamp;
  control_cmd.longitudinal.velocity = static_cast<float>(std::max(
    static_cast<double>(prev_control_cmd.longitudinal.velocity) +
      static_cast<double>(prev_control_cmd.longitudinal.acceleration) * dt,
    0.0));
  control_cmd.longitudinal.acceleration = static_cast<float>(std::max(
    static_cast<double>(prev_control_cmd.longitudinal.acceleration) + params_.target_jerk * dt,
    params_.target_acceleration));
  if (
    static_cast<double>(prev_control_cmd.longitudinal.acceleration) == params_.target_acceleration)
  {
    control_cmd.longitudinal.jerk = 0.0;
  } else {
    control_cmd.longitudinal.jerk = static_cast<float>(params_.target_jerk);
  }

  return control_cmd;
}

}  // namespace autoware_mrm_emergency_stop_operator

// nano-ros port: RCLCPP_COMPONENTS_REGISTER_NODE → NROS_COMPONENT (the
// C-ABI factory the generated entry constructs the node through).
NROS_COMPONENT(autoware_mrm_emergency_stop_operator::MrmEmergencyStopOperator);
