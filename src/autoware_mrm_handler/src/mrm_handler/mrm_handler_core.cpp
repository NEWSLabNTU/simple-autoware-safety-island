// Copyright 2024 TIER IV, Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
// CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language
// governing permissions and limitations under the License.

#include "autoware/mrm_handler/mrm_handler_core.hpp"

#include <cmath>
#include <cstdio>

// nano-ros port: platform monotonic stamps (porting-notes 05); RCLCPP_* logs →
// printf (single global log sink, porting-notes 01).
namespace
{
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

const char * behavior2string(const int behavior)
{
  using autoware_adapi_v1_msgs::msg::MrmState;
  if (behavior == MrmState::NONE) return "NONE";
  if (behavior == MrmState::PULL_OVER) return "PULL_OVER";
  if (behavior == MrmState::COMFORTABLE_STOP) return "COMFORTABLE_STOP";
  if (behavior == MrmState::EMERGENCY_STOP) return "EMERGENCY_STOP";
  return "INVALID";
}

const char * state2string(const int state)
{
  using autoware_adapi_v1_msgs::msg::MrmState;
  if (state == MrmState::NORMAL) return "NORMAL";
  if (state == MrmState::MRM_OPERATING) return "MRM_OPERATING";
  if (state == MrmState::MRM_SUCCEEDED) return "MRM_SUCCEEDED";
  if (state == MrmState::MRM_FAILED) return "MRM_FAILED";
  return "INVALID";
}
}  // namespace

namespace autoware_mrm_handler
{

MrmHandler::MrmHandler(::nros::NodeHandle handle) : ::nros::ComponentNode(handle, "mrm_handler")
{
  ::setvbuf(stdout, nullptr, _IONBF, 0);

  // Parameter (upstream declares these with the same defaults;
  // use_comfortable_stop flipped to true — the island ships the operator).
  param_.update_rate = declare_parameter<int64_t>("update_rate", 10);
  param_.timeout_operation_mode_availability =
    declare_parameter<double>("timeout_operation_mode_availability", 0.5);
  param_.timeout_call_mrm_behavior = declare_parameter<double>("timeout_call_mrm_behavior", 0.01);
  param_.timeout_cancel_mrm_behavior =
    declare_parameter<double>("timeout_cancel_mrm_behavior", 0.01);
  param_.use_emergency_holding = declare_parameter<bool>("use_emergency_holding", false);
  param_.timeout_emergency_recovery = declare_parameter<double>("timeout_emergency_recovery", 5.0);
  param_.use_parking_after_stopped = declare_parameter<bool>("use_parking_after_stopped", false);
  param_.use_pull_over = declare_parameter<bool>("use_pull_over", false);
  param_.use_comfortable_stop = declare_parameter<bool>("use_comfortable_stop", true);
  param_.turning_hazard_on.emergency = declare_parameter<bool>("turning_hazard_on.emergency", true);
  param_.turning_indicator_on.emergency =
    declare_parameter<bool>("turning_indicator_on.emergency", true);

  // Subscribers — resolved contract names (porting-notes 07); the polling
  // subscribers became caching callbacks (porting-notes 14).
  NROS_SUBSCRIBE(
    tier4_system_msgs::msg::OperationModeAvailability, onOperationModeAvailability,
    "/system/operation_mode/availability");
  NROS_SUBSCRIBE(nav_msgs::msg::Odometry, onOdometry, "/localization/kinematic_state");
  NROS_SUBSCRIBE(
    autoware_vehicle_msgs::msg::ControlModeReport, onControlMode, "/vehicle/status/control_mode");
  NROS_SUBSCRIBE(
    tier4_system_msgs::msg::MrmBehaviorStatus, onComfortableStopStatus,
    "/system/mrm/comfortable_stop/status");
  NROS_SUBSCRIBE(
    tier4_system_msgs::msg::MrmBehaviorStatus, onEmergencyStopStatus,
    "/system/mrm/emergency_stop/status");
  NROS_SUBSCRIBE(
    autoware_adapi_v1_msgs::msg::OperationModeState, onOperationModeState,
    "/api/operation_mode/state");
  NROS_SUBSCRIBE(autoware_vehicle_msgs::msg::GearCommand, onGearCmd, "/control/command/gear_cmd");

  // Publisher
  pub_turn_indicator_cmd_ = create_publisher<autoware_vehicle_msgs::msg::TurnIndicatorsCommand>(
    "/system/emergency/turn_indicators_cmd");
  pub_hazard_cmd_ = create_publisher<autoware_vehicle_msgs::msg::HazardLightsCommand>(
    "/system/emergency/hazard_lights_cmd");
  pub_gear_cmd_ =
    create_publisher<autoware_vehicle_msgs::msg::GearCommand>("/system/emergency/gear_cmd");
  pub_mrm_state_ =
    create_publisher<autoware_adapi_v1_msgs::msg::MrmState>("/system/fail_safe/mrm_state");
  pub_emergency_holding_ = create_publisher<tier4_system_msgs::msg::EmergencyHoldingState>(
    "/system/fail_safe/emergency_holding");

  // Clients — POLL model (porting-notes 14). Callback groups dropped (single
  // executor); pull_over client dropped (no on-island operator).
  ::nros::create_service_client_raw(
    node(), client_mrm_comfortable_stop_.bytes, "/system/mrm/comfortable_stop/operate",
    tier4_system_msgs::srv::OperateMrm::TYPE_NAME);
  ::nros::create_service_client_raw(
    node(), client_mrm_emergency_stop_.bytes, "/system/mrm/emergency_stop/operate",
    tier4_system_msgs::srv::OperateMrm::TYPE_NAME);

  // Initialize
  mrm_state_ = {};
  mrm_state_.stamp = now_stamp();
  mrm_state_.state = autoware_adapi_v1_msgs::msg::MrmState::NORMAL;
  mrm_state_.behavior = autoware_adapi_v1_msgs::msg::MrmState::NONE;
  is_operation_mode_availability_timeout = false;
  stamp_operation_mode_availability_ = now_sec();

  // Timer
  NROS_CREATE_TIMER(static_cast<uint64_t>(1000 / param_.update_rate), onTimer);
}

void MrmHandler::onOperationModeAvailability(
  const tier4_system_msgs::msg::OperationModeAvailability & msg)
{
  stamp_operation_mode_availability_ = now_sec();
  operation_mode_availability_ = msg;
  has_operation_mode_availability_ = true;

  const bool skip_emergency_holding_check = !param_.use_emergency_holding || is_emergency_holding_;
  if (skip_emergency_holding_check) {
    return;
  }

  if (isAvailableCurrentOperationMode()) {
    has_stamp_current_operation_mode_become_unavailable_ = false;
    return;
  }

  if (!has_stamp_current_operation_mode_become_unavailable_) {
    stamp_current_operation_mode_become_unavailable_ = now_sec();
    has_stamp_current_operation_mode_become_unavailable_ = true;
  }

  const auto emergency_duration = now_sec() - stamp_current_operation_mode_become_unavailable_;
  is_emergency_holding_ = (emergency_duration > param_.timeout_emergency_recovery);
}

void MrmHandler::onOdometry(const nav_msgs::msg::Odometry & msg)
{
  odom_ = msg;
  has_odom_ = true;
}

void MrmHandler::onControlMode(const autoware_vehicle_msgs::msg::ControlModeReport & msg)
{
  control_mode_ = msg;
  has_control_mode_ = true;
}

void MrmHandler::onComfortableStopStatus(const tier4_system_msgs::msg::MrmBehaviorStatus & msg)
{
  mrm_comfortable_stop_status_ = msg;
  has_mrm_comfortable_stop_status_ = true;
}

void MrmHandler::onEmergencyStopStatus(const tier4_system_msgs::msg::MrmBehaviorStatus & msg)
{
  mrm_emergency_stop_status_ = msg;
  has_mrm_emergency_stop_status_ = true;
}

void MrmHandler::onOperationModeState(const autoware_adapi_v1_msgs::msg::OperationModeState & msg)
{
  operation_mode_state_ = msg;
  has_operation_mode_state_ = true;
}

void MrmHandler::onGearCmd(const autoware_vehicle_msgs::msg::GearCommand & msg)
{
  gear_cmd_ = msg;
  has_gear_cmd_ = true;
}

void MrmHandler::publishTurnIndicatorCmd()
{
  using autoware_vehicle_msgs::msg::TurnIndicatorsCommand;
  TurnIndicatorsCommand msg{};

  msg.stamp = now_stamp();
  if (param_.turning_indicator_on.emergency && isEmergency()) {
    msg.command = TurnIndicatorsCommand::DISABLE;
  } else {
    msg.command = TurnIndicatorsCommand::NO_COMMAND;
  }

  pub_turn_indicator_cmd_.publish(msg);
}

void MrmHandler::publishHazardCmd()
{
  using autoware_vehicle_msgs::msg::HazardLightsCommand;
  HazardLightsCommand msg{};

  msg.stamp = now_stamp();
  if (param_.turning_hazard_on.emergency && isEmergency()) {
    msg.command = HazardLightsCommand::ENABLE;
  } else {
    msg.command = HazardLightsCommand::NO_COMMAND;
  }

  pub_hazard_cmd_.publish(msg);
}

void MrmHandler::publishGearCmd()
{
  using autoware_vehicle_msgs::msg::GearCommand;
  GearCommand msg{};
  msg.stamp = now_stamp();

  if (isEmergency()) {
    msg.command =
      (param_.use_parking_after_stopped && isStopped()) ? GearCommand::PARK : last_gear_command_;
  } else {
    msg.command = has_gear_cmd_ ? gear_cmd_.command : last_gear_command_;
    last_gear_command_ = msg.command;
  }

  pub_gear_cmd_.publish(msg);
}

void MrmHandler::publishMrmState()
{
  mrm_state_.stamp = now_stamp();
  pub_mrm_state_.publish(mrm_state_);
}

void MrmHandler::publishEmergencyHolding()
{
  tier4_system_msgs::msg::EmergencyHoldingState msg{};
  msg.stamp = now_stamp();
  msg.is_holding = is_emergency_holding_;
  pub_emergency_holding_.publish(msg);
}

void MrmHandler::operateMrm()
{
  using autoware_adapi_v1_msgs::msg::MrmState;

  if (mrm_state_.state == MrmState::NORMAL) {
    const auto current_mrm_behavior = MrmState::NONE;
    if (current_mrm_behavior == mrm_state_.behavior) {
      return;
    }
    if (requestMrmBehavior(mrm_state_.behavior, RequestType::CANCEL)) {
      mrm_state_.behavior = current_mrm_behavior;
    } else {
      handleFailedRequest();
    }
    return;
  }
  if (mrm_state_.state == MrmState::MRM_OPERATING) {
    const auto current_mrm_behavior = getCurrentMrmBehavior();
    if (current_mrm_behavior == mrm_state_.behavior) {
      return;
    }
    if (!requestMrmBehavior(mrm_state_.behavior, RequestType::CANCEL)) {
      handleFailedRequest();
    } else if (requestMrmBehavior(current_mrm_behavior, RequestType::CALL)) {
      mrm_state_.behavior = current_mrm_behavior;
    } else {
      handleFailedRequest();
    }
    return;
  }
  if (mrm_state_.state == MrmState::MRM_SUCCEEDED) {
    return;
  }
  if (mrm_state_.state == MrmState::MRM_FAILED) {
    return;
  }
  std::printf("[mrm_handler] WARN: invalid MRM state: %d\n", mrm_state_.state);
}

void MrmHandler::handleFailedRequest()
{
  using autoware_adapi_v1_msgs::msg::MrmState;

  if (requestMrmBehavior(MrmState::EMERGENCY_STOP, CALL)) {
    if (mrm_state_.state != MrmState::MRM_OPERATING) transitionTo(MrmState::MRM_OPERATING);
  } else {
    transitionTo(MrmState::MRM_FAILED);
  }
  mrm_state_.behavior = MrmState::EMERGENCY_STOP;
}

bool MrmHandler::requestMrmBehavior(uint16_t mrm_behavior, RequestType request_type)
{
  using autoware_adapi_v1_msgs::msg::MrmState;

  // nano-ros port (porting-notes 14): the upstream 10 ms blocking future wait
  // becomes send-and-poll — a blocking wait inside a timer callback would need
  // a nested executor spin. The request is fired here; the reply is drained on
  // later ticks (drainMrmClientReplies) and only logged. "Success" therefore
  // means "request sent"; a failed/undelivered reply surfaces via the operator
  // status topics that the state machine already watches.
  tier4_system_msgs::srv::OperateMrm::Request request{};
  request.stamp = now_stamp();
  request.operate = (request_type == RequestType::CALL);

  uint8_t buf[64];
  size_t written = 0;
  if (tier4_system_msgs::srv::OperateMrm::Request::ffi_serialize(
        &request, buf, sizeof(buf), &written) != 0) {
    return false;
  }

  void * client_storage = nullptr;
  switch (mrm_behavior) {
    case MrmState::NONE:
      return true;
    case MrmState::PULL_OVER:
      // No on-island pull_over operator (use_pull_over defaults false).
      std::printf("[mrm_handler] WARN: pull_over requested but not available on-island\n");
      return false;
    case MrmState::COMFORTABLE_STOP:
      client_storage = client_mrm_comfortable_stop_.bytes;
      break;
    case MrmState::EMERGENCY_STOP:
      client_storage = client_mrm_emergency_stop_.bytes;
      break;
    default:
      std::printf("[mrm_handler] ERROR: invalid behavior: %d\n", mrm_behavior);
      return false;
  }

  if (nros_cpp_service_client_send_request(client_storage, buf, written) != 0) {
    std::printf(
      "[mrm_handler] ERROR: %s %s request send failed\n", behavior2string(mrm_behavior),
      request.operate ? "call" : "cancel");
    return false;
  }
  std::printf(
    "[mrm_handler] %s is %s (request sent).\n", behavior2string(mrm_behavior),
    request.operate ? "operated" : "canceled");
  return true;
}

void MrmHandler::drainMrmClientReplies()
{
  uint8_t resp[128];
  size_t rlen = 0;
  for (void * storage :
       {static_cast<void *>(client_mrm_comfortable_stop_.bytes),
        static_cast<void *>(client_mrm_emergency_stop_.bytes)}) {
    while (nros_cpp_service_client_try_recv_reply(storage, resp, sizeof(resp), &rlen) == 0 &&
           rlen > 0) {
      tier4_system_msgs::srv::OperateMrm::Response r{};
      if (tier4_system_msgs::srv::OperateMrm::Response::ffi_deserialize(resp, rlen, &r) == 0) {
        if (!r.response.success) {
          std::printf("[mrm_handler] ERROR: MRM operate request rejected by operator\n");
        }
      }
      rlen = 0;
    }
  }
}

bool MrmHandler::isDataReady()
{
  if (!has_operation_mode_availability_) {
    return false;
  }
  if (param_.use_comfortable_stop && !isComfortableStopStatusAvailable()) {
    return false;
  }
  if (!isEmergencyStopStatusAvailable()) {
    return false;
  }
  return true;
}

void MrmHandler::checkOperationModeAvailabilityTimeout()
{
  if (
    (now_sec() - stamp_operation_mode_availability_) >
    param_.timeout_operation_mode_availability) {
    is_operation_mode_availability_timeout = true;
  } else {
    is_operation_mode_availability_timeout = false;
  }
}

void MrmHandler::onTimer()
{
  drainMrmClientReplies();

  if (!isDataReady()) {
    return;
  }

  checkOperationModeAvailabilityTimeout();
  updateMrmState();
  operateMrm();

  publishMrmState();
  publishTurnIndicatorCmd();
  publishHazardCmd();
  publishGearCmd();
  publishEmergencyHolding();
}

void MrmHandler::transitionTo(const int new_state)
{
  std::printf(
    "[mrm_handler] MRM State changed: %s -> %s\n", state2string(mrm_state_.state),
    state2string(new_state));
  mrm_state_.state = static_cast<uint16_t>(new_state);
}

void MrmHandler::updateMrmState()
{
  using autoware_adapi_v1_msgs::msg::MrmState;

  const bool is_emergency = isEmergency();

  if (!is_emergency) {
    if (mrm_state_.state != MrmState::NORMAL) transitionTo(MrmState::NORMAL);
    return;
  }

  const bool is_control_mode_autonomous = isControlModeAutonomous();

  switch (mrm_state_.state) {
    case MrmState::NORMAL:
      if (is_control_mode_autonomous) {
        transitionTo(MrmState::MRM_OPERATING);
      }
      return;

    case MrmState::MRM_OPERATING:
      if (!isStopped()) return;
      if (mrm_state_.behavior != MrmState::PULL_OVER) {
        transitionTo(MrmState::MRM_SUCCEEDED);
        return;
      }
      if (isArrivedAtGoal()) {
        transitionTo(MrmState::MRM_SUCCEEDED);
      }
      return;

    case MrmState::MRM_SUCCEEDED:
      if (mrm_state_.behavior != getCurrentMrmBehavior()) {
        transitionTo(MrmState::MRM_OPERATING);
      }
      return;
    case MrmState::MRM_FAILED:
      return;

    default:
      // nano-ros port: upstream throws; no exceptions here (porting-notes 01).
      std::printf("[mrm_handler] ERROR: invalid state: %d\n", mrm_state_.state);
      return;
  }
}

uint16_t MrmHandler::getCurrentMrmBehavior()
{
  using autoware_adapi_v1_msgs::msg::MrmState;

  if (mrm_state_.behavior == MrmState::NONE || mrm_state_.behavior == MrmState::PULL_OVER) {
    if (is_operation_mode_availability_timeout) {
      return MrmState::EMERGENCY_STOP;
    }
    if (operation_mode_availability_.pull_over && param_.use_pull_over) {
      return MrmState::PULL_OVER;
    }
    if (operation_mode_availability_.comfortable_stop && param_.use_comfortable_stop) {
      return MrmState::COMFORTABLE_STOP;
    }
    if (!operation_mode_availability_.emergency_stop) {
      std::printf("[mrm_handler] WARN: no mrm operation available: operate emergency_stop\n");
    }
    return MrmState::EMERGENCY_STOP;
  }
  if (mrm_state_.behavior == MrmState::COMFORTABLE_STOP) {
    if (is_operation_mode_availability_timeout) {
      return MrmState::EMERGENCY_STOP;
    }
    if (isStopped() && operation_mode_availability_.pull_over && param_.use_pull_over) {
      return MrmState::PULL_OVER;
    }
    if (operation_mode_availability_.comfortable_stop && param_.use_comfortable_stop) {
      return MrmState::COMFORTABLE_STOP;
    }
    if (!operation_mode_availability_.emergency_stop) {
      std::printf("[mrm_handler] WARN: no mrm operation available: operate emergency_stop\n");
    }
    return MrmState::EMERGENCY_STOP;
  }
  if (mrm_state_.behavior == MrmState::EMERGENCY_STOP) {
    if (is_operation_mode_availability_timeout) {
      return MrmState::EMERGENCY_STOP;
    }
    if (isStopped() && operation_mode_availability_.pull_over && param_.use_pull_over) {
      return MrmState::PULL_OVER;
    }
    if (!operation_mode_availability_.emergency_stop) {
      std::printf("[mrm_handler] WARN: no mrm operation available: operate emergency_stop\n");
    }
    return MrmState::EMERGENCY_STOP;
  }

  return mrm_state_.behavior;
}

bool MrmHandler::isStopped()
{
  if (!has_odom_) return false;
  constexpr auto th_stopped_velocity = 0.001;
  return (std::abs(odom_.twist.twist.linear.x) < th_stopped_velocity);
}

bool MrmHandler::isEmergency()
{
  return !isAvailableCurrentOperationMode() || is_emergency_holding_ ||
         is_operation_mode_availability_timeout;
}

bool MrmHandler::isControlModeAutonomous()
{
  using autoware_vehicle_msgs::msg::ControlModeReport;
  if (!has_control_mode_) return false;
  return control_mode_.mode == ControlModeReport::AUTONOMOUS;
}

bool MrmHandler::isComfortableStopStatusAvailable()
{
  if (!has_mrm_comfortable_stop_status_) return false;
  return mrm_comfortable_stop_status_.state !=
         tier4_system_msgs::msg::MrmBehaviorStatus::NOT_AVAILABLE;
}

bool MrmHandler::isEmergencyStopStatusAvailable()
{
  if (!has_mrm_emergency_stop_status_) return false;
  return mrm_emergency_stop_status_.state !=
         tier4_system_msgs::msg::MrmBehaviorStatus::NOT_AVAILABLE;
}

bool MrmHandler::isArrivedAtGoal()
{
  using autoware_adapi_v1_msgs::msg::OperationModeState;
  if (!has_operation_mode_state_) return false;
  return operation_mode_state_.mode == OperationModeState::STOP;
}

bool MrmHandler::isAvailableCurrentOperationMode()
{
  using autoware_adapi_v1_msgs::msg::OperationModeState;
  const auto operation_mode = getCurrentOperationMode();
  switch (operation_mode) {
    case OperationModeState::UNKNOWN:
      return false;
    case OperationModeState::STOP:
      return operation_mode_availability_.stop;
    case OperationModeState::AUTONOMOUS:
      return operation_mode_availability_.autonomous;
    case OperationModeState::LOCAL:
      return operation_mode_availability_.local;
    case OperationModeState::REMOTE:
      return operation_mode_availability_.remote;
    default:
      std::printf("[mrm_handler] WARN: invalid operation mode: %d\n", operation_mode);
      return false;
  }
}

uint8_t MrmHandler::getCurrentOperationMode()
{
  using autoware_adapi_v1_msgs::msg::OperationModeState;
  if (!has_operation_mode_state_) return OperationModeState::UNKNOWN;
  return operation_mode_state_.mode;
}

}  // namespace autoware_mrm_handler

// nano-ros port: RCLCPP_COMPONENTS_REGISTER_NODE → NROS_COMPONENT.
NROS_COMPONENT(autoware_mrm_handler::MrmHandler);
