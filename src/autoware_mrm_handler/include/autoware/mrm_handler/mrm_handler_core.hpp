// Copyright 2024 TIER IV, Inc.
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

#ifndef AUTOWARE__MRM_HANDLER__MRM_HANDLER_CORE_HPP_
#define AUTOWARE__MRM_HANDLER__MRM_HANDLER_CORE_HPP_

// Autoware
#include <autoware_adapi_v1_msgs/msg/mrm_state.hpp>
#include <autoware_adapi_v1_msgs/msg/operation_mode_state.hpp>
#include <autoware_vehicle_msgs/msg/control_mode_report.hpp>
#include <autoware_vehicle_msgs/msg/gear_command.hpp>
#include <autoware_vehicle_msgs/msg/hazard_lights_command.hpp>
#include <autoware_vehicle_msgs/msg/turn_indicators_command.hpp>
#include <tier4_system_msgs/msg/emergency_holding_state.hpp>
#include <tier4_system_msgs/msg/mrm_behavior_status.hpp>
#include <tier4_system_msgs/msg/operation_mode_availability.hpp>
#include <tier4_system_msgs/srv/operate_mrm.hpp>

#include <nav_msgs/msg/odometry.hpp>

// nano-ros port: <rclcpp/rclcpp.hpp> → nros::ComponentNode (porting-notes 01).
#include <nros/component.hpp>
#include <nros/component_node.hpp>

namespace autoware::mrm_handler
{

struct HazardLampPolicy
{
  bool emergency;
};

struct TurnIndicatorPolicy
{
  bool emergency;
};

struct Param
{
  int64_t update_rate;
  double timeout_operation_mode_availability;
  double timeout_call_mrm_behavior;
  double timeout_cancel_mrm_behavior;
  bool use_emergency_holding;
  double timeout_emergency_recovery;
  bool use_parking_after_stopped;
  bool use_pull_over;
  bool use_comfortable_stop;
  HazardLampPolicy turning_hazard_on{};
  TurnIndicatorPolicy turning_indicator_on{};
};

class MrmHandler : public ::nros::ComponentNode
{
public:
  explicit MrmHandler(::nros::NodeHandle handle);

private:
  // type
  enum RequestType { CALL, CANCEL };

  // nano-ros port (porting-notes 14): autoware_utils::InterProcessPollingSubscriber
  // → plain member-callback subscriptions caching the latest sample + a has_
  // flag ("take_data" == read the cache). pull_over has no on-island operator;
  // its subscription and client are dropped (use_pull_over stays false).
  void onOperationModeAvailability(const tier4_system_msgs::msg::OperationModeAvailability & msg);
  void onOdometry(const nav_msgs::msg::Odometry & msg);
  void onControlMode(const autoware_vehicle_msgs::msg::ControlModeReport & msg);
  void onComfortableStopStatus(const tier4_system_msgs::msg::MrmBehaviorStatus & msg);
  void onEmergencyStopStatus(const tier4_system_msgs::msg::MrmBehaviorStatus & msg);
  void onOperationModeState(const autoware_adapi_v1_msgs::msg::OperationModeState & msg);
  void onGearCmd(const autoware_vehicle_msgs::msg::GearCommand & msg);

  tier4_system_msgs::msg::OperationModeAvailability operation_mode_availability_{};
  bool has_operation_mode_availability_{false};
  nav_msgs::msg::Odometry odom_{};
  bool has_odom_{false};
  autoware_vehicle_msgs::msg::ControlModeReport control_mode_{};
  bool has_control_mode_{false};
  tier4_system_msgs::msg::MrmBehaviorStatus mrm_comfortable_stop_status_{};
  bool has_mrm_comfortable_stop_status_{false};
  tier4_system_msgs::msg::MrmBehaviorStatus mrm_emergency_stop_status_{};
  bool has_mrm_emergency_stop_status_{false};
  autoware_adapi_v1_msgs::msg::OperationModeState operation_mode_state_{};
  bool has_operation_mode_state_{false};
  autoware_vehicle_msgs::msg::GearCommand gear_cmd_{};
  bool has_gear_cmd_{false};

  // Publisher
  ::nros::Publisher<autoware_vehicle_msgs::msg::TurnIndicatorsCommand> pub_turn_indicator_cmd_;
  ::nros::Publisher<autoware_vehicle_msgs::msg::HazardLightsCommand> pub_hazard_cmd_;
  ::nros::Publisher<autoware_vehicle_msgs::msg::GearCommand> pub_gear_cmd_;
  ::nros::Publisher<autoware_adapi_v1_msgs::msg::MrmState> pub_mrm_state_;
  ::nros::Publisher<tier4_system_msgs::msg::EmergencyHoldingState> pub_emergency_holding_;

  void publishTurnIndicatorCmd();
  void publishHazardCmd();
  void publishGearCmd();
  void publishMrmState();
  void publishEmergencyHolding();

  autoware_adapi_v1_msgs::msg::MrmState mrm_state_{};

  // Clients — nano-ros POLL model (porting-notes 14): raw client storage +
  // send/try-recv; replies are drained on the next timer ticks instead of the
  // upstream 10 ms blocking future wait.
  ::nros::ServiceClientStorage client_mrm_comfortable_stop_;
  ::nros::ServiceClientStorage client_mrm_emergency_stop_;

  bool requestMrmBehavior(uint16_t mrm_behavior, RequestType request_type);
  void drainMrmClientReplies();

  // Parameters
  Param param_;

  bool isDataReady();
  void onTimer();

  // Heartbeat (porting-notes 05: double-seconds monotonic timestamps)
  double stamp_operation_mode_availability_{0.0};
  double stamp_current_operation_mode_become_unavailable_{0.0};
  bool has_stamp_current_operation_mode_become_unavailable_{false};
  bool is_operation_mode_availability_timeout{false};
  void checkOperationModeAvailabilityTimeout();

  // Algorithm
  bool is_emergency_holding_ = false;
  uint8_t last_gear_command_{autoware_vehicle_msgs::msg::GearCommand::DRIVE};
  void transitionTo(const int new_state);
  void updateMrmState();
  void operateMrm();
  void handleFailedRequest();
  uint16_t getCurrentMrmBehavior();
  bool isStopped();
  bool isEmergency();
  bool isControlModeAutonomous();
  bool isComfortableStopStatusAvailable();
  bool isEmergencyStopStatusAvailable();
  bool isArrivedAtGoal();
  bool isAvailableCurrentOperationMode();
  uint8_t getCurrentOperationMode();
};

}  // namespace autoware::mrm_handler

#endif  // AUTOWARE__MRM_HANDLER__MRM_HANDLER_CORE_HPP_
