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

#include "stop_mode_operator.hpp"

// nano-ros port: platform monotonic clock in seconds (porting-notes 05).
// <cmath> avoided — Zephyr minimal libcpp (porting-notes 18).
namespace
{
double abs_d(double v) { return v < 0 ? -v : v; }

double now_sec()
{
  return static_cast<double>(nros_cpp_time_ns()) * 1e-9;
}

builtin_interfaces::msg::Time now_stamp()
{
  const uint64_t ns = nros_cpp_time_ns();
  builtin_interfaces::msg::Time t;
  t.sec = static_cast<int32_t>(ns / 1000000000ull);
  t.nanosec = static_cast<uint32_t>(ns % 1000000000ull);
  return t;
}
}  // namespace

namespace autoware::stop_mode_operator
{

StopModeOperator::StopModeOperator(::nros::NodeHandle handle)
: ::nros::ComponentNode(handle, "stop_mode_operator")
{
  current_steering_ = {};
  current_steering_.steering_tire_angle = 0.0f;
  current_route_state_ = {};
  current_route_state_.state = RouteState::UNKNOWN;

  // Upstream config/default.param.yaml values as defaults (porting-notes 06).
  stop_hold_acceleration_ = declare_parameter<double>("stop_hold_acceleration", -1.5);
  enable_auto_parking_ = declare_parameter<bool>("enable_auto_parking", true);

  const auto control_qos = ::nros::QoS(5);
  const auto durable_qos = ::nros::QoS(1).transient_local();

  // Resolved contract names (porting-notes 07). Upstream remaps these into
  // the control_command_gate "stop" source; without the gate on-island they
  // publish under /system/stop_mode/ (gate port is a stretch goal).
  pub_control_ = create_publisher<Control>("/system/stop_mode/control", control_qos);
  pub_gear_ = create_publisher<GearCommand>("/system/stop_mode/gear", durable_qos);
  pub_turn_indicators_ =
    create_publisher<TurnIndicatorsCommand>("/system/stop_mode/turn_indicators", durable_qos);
  pub_hazard_lights_ =
    create_publisher<HazardLightsCommand>("/system/stop_mode/hazard_lights", durable_qos);

  NROS_SUBSCRIBE(SteeringReport, on_steering, "/vehicle/status/steering_status", ::nros::QoS(1));
  NROS_SUBSCRIBE(VelocityReport, on_velocity, "/vehicle/status/velocity_status", ::nros::QoS(1));
  NROS_SUBSCRIBE(RouteState, on_route_state, "/planning/route_state", ::nros::QoS(1));

  // Upstream: rate is a double parameter fed to rclcpp::Rate.
  const double rate = declare_parameter<double>("rate", 30.0);
  NROS_CREATE_WALL_TIMER(static_cast<uint64_t>(1000.0 / rate), on_timer);
}

void StopModeOperator::on_steering(const SteeringReport & msg)
{
  current_steering_ = msg;
}

void StopModeOperator::on_velocity(const VelocityReport & msg)
{
  vehicle_stop_check_.update(now_sec(), abs_d(msg.longitudinal_velocity) < 1e-3);
}

void StopModeOperator::on_route_state(const RouteState & msg)
{
  current_route_state_ = msg;
}

void StopModeOperator::on_timer()
{
  vehicle_stop_check_.update_timeout(now_sec(), vehicle_stop_timeout_);

  publish_control_command();
  publish_gear_command();
  publish_turn_indicators_command();
  publish_hazard_lights_command();
}

void StopModeOperator::publish_control_command()
{
  // TODO(Takagi, Isamu): stationary steering
  Control control{};
  control.stamp = control.longitudinal.stamp = control.lateral.stamp = now_stamp();
  control.lateral.steering_tire_angle = current_steering_.steering_tire_angle;
  control.lateral.steering_tire_rotation_rate = 0.0;
  control.longitudinal.velocity = 0.0;
  control.longitudinal.acceleration = static_cast<float>(stop_hold_acceleration_);
  pub_control_.publish(control);
}

void StopModeOperator::publish_gear_command()
{
  bool parking = false;

  if (enable_auto_parking_) {
    const bool parking_vehicle_stop = vehicle_stop_check_.check(now_sec(), vehicle_stop_duration_);
    const bool parking_route_state = current_route_state_.state == RouteState::UNSET ||
                                     current_route_state_.state == RouteState::ARRIVED;
    parking = parking_route_state && parking_vehicle_stop;
  }

  GearCommand gear{};
  gear.stamp = now_stamp();
  gear.command = parking ? GearCommand::PARK : GearCommand::NONE;
  pub_gear_.publish(gear);
}

void StopModeOperator::publish_turn_indicators_command()
{
  TurnIndicatorsCommand turn_indicators{};
  turn_indicators.stamp = now_stamp();
  turn_indicators.command = TurnIndicatorsCommand::DISABLE;
  pub_turn_indicators_.publish(turn_indicators);
}

void StopModeOperator::publish_hazard_lights_command()
{
  HazardLightsCommand hazard_lights{};
  hazard_lights.stamp = now_stamp();
  hazard_lights.command = HazardLightsCommand::DISABLE;
  pub_hazard_lights_.publish(hazard_lights);
}

}  // namespace autoware::stop_mode_operator

// nano-ros port: RCLCPP_COMPONENTS_REGISTER_NODE → NROS_COMPONENT.
NROS_COMPONENT(autoware::stop_mode_operator::StopModeOperator);
