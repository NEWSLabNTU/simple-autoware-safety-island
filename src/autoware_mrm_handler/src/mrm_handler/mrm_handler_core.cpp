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
#include <nros/clock.hpp>
#include <nros/nros.hpp>

#include <cstdio>

// phase7-W1 trace markers (no-op unless the image enables CTF tracing); this
// TU also carries the tracing runtime (heartbeat, provenance, native_sim dump).
#define ISLAND_TRACE_DEFINE_RUNTIME
#include "../../../safety_island_tracing/include/island_trace.h"

// nano-ros port: platform monotonic stamps (porting-notes 05); RCLCPP_* logs →
// printf (porting-notes 01). <cmath> avoided — Zephyr minimal libcpp
// (porting-notes 18).
#if defined(__ZEPHYR__)
#include <zephyr/kernel.h>
// phase9-W4: when and why the handler armed nano-ros's contract monitors,
// readable by name over SWD (tools/timeline/violations.py): the uptime of the
// call (0 = not yet) and the transition that made it (ARM_VIA_*).
extern "C" {
volatile uint32_t island_monitors_armed_uptime_ms;
volatile uint32_t island_monitors_armed_via;
#if defined(CONFIG_ISLAND_DEBUG_OVERRUN)
// phase9-W4 debug hook (CONFIG_ISLAND_DEBUG_OVERRUN, Kconfig.island_trace):
// 0 from boot; a debugger writes N > 0 and the next RUN tick busy-waits N ms,
// once. Read and cleared only by onTimer(). By name over SWD:
// tools/timeline/violations.py overrun N.
volatile uint32_t island_debug_overrun_ms;
#endif
}
#endif

namespace
{
double abs_d(double v) { return v < 0 ? -v : v; }

// phase9-W4: the island's start-up is over -- arm nano-ros's contract
// monitors (CONFIG_NROS_MONITOR_ARM_ON_CALL, nano-ros phase-474 I2). Armed at
// the FIRST tick that finds every required input established, which is one of
// two transitions:
//   ARM_VIA_INIT_DONE      INIT -> RUN (marker INIT_DONE);
//   ARM_VIA_INIT_RECOVERY  RUN + init failure -> RUN, the failure cleared.
// NOT at INIT_TIMEOUT. On the board the island boots minutes before Autoware
// (tools/timeline/run-board.sh: reset at step 3, Autoware at step 5), so
// init_timeout (3.0 s) always passes first; arming there would store the
// availability's silence-runtime for the minutes Autoware takes to start,
// a start-up wait the handler already reports as its own fault (init
// failure, isInputLost(): emergency stop, INIT_TIMEOUT marker). The monitors
// judge the running system from the tick it is whole, and a handler whose
// inputs never establish stays in that fault, unmonitored by nano-ros but
// never silent. Before the call every verdict is counted in
// suppressed_before_arm and not stored. On an image without ARM_ON_CALL the
// monitors armed at the first spin and the call does nothing.
enum : uint32_t { ARM_VIA_INIT_DONE = 1u, ARM_VIA_INIT_RECOVERY = 2u };
void arm_contract_monitors(uint32_t via)
{
  nros::arm_monitors();
#if defined(__ZEPHYR__)
  island_monitors_armed_uptime_ms = k_uptime_get_32();
  island_monitors_armed_via = via;
#else
  (void)via;
#endif
}

double now_sec()
{
  return static_cast<double>(nros_cpp_time_ns()) * 1e-9;
}

// phase8-W18: a STAMP is read by the host, so it comes from the wall clock
// when the image has one (nano-ros issue 0758: the SNTP epoch, installed
// before any component is constructed). Autoware's vehicle_cmd_gate keeps its
// previous hazard/turn/gear command when the new one is stamped earlier
// (getContinuousTopic), so a boot-relative stamp is silently dropped. With no
// epoch the system clock reads 0 and the stamp stays monotonic, knowingly.
// Durations (now_sec) stay on the monotonic clock either way.
builtin_interfaces::msg::Time now_stamp()
{
  const int64_t wall = ::nros::Clock(NROS_CLOCK_SYSTEM_TIME).now().nanoseconds();
  const uint64_t ns = wall > 0 ? static_cast<uint64_t>(wall) : nros_cpp_time_ns();
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

// phase8-W27: the required inputs, by their contract subscriber names, in the
// bit order of MrmHandler::RequiredInput.
constexpr const char * kRequiredInputNames[] = {
  "operation_mode_availability", "operation_mode_state", "comfortable_stop_status",
  "emergency_stop_status"};

// Integer ms: the Zephyr image's minimal printf has no %f.
int to_ms(double sec) { return static_cast<int>(sec * 1000.0); }

void print_inputs(uint32_t mask)
{
  if (mask == 0) {
    std::printf("none");
    return;
  }
  const char * sep = "";
  for (uint32_t i = 0; i < sizeof(kRequiredInputNames) / sizeof(kRequiredInputNames[0]); ++i) {
    if (mask & (1u << i)) {
      std::printf("%s%s", sep, kRequiredInputNames[i]);
      sep = ", ";
    }
  }
}
}  // namespace

namespace autoware::mrm_handler
{

MrmHandler::MrmHandler(::nros::NodeHandle handle)
: ::nros::NodeWithTimers<1>(handle, "mrm_handler")
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
  param_.use_pull_over = declare_parameter<bool>("use_pull_over", false);
  param_.use_comfortable_stop = declare_parameter<bool>("use_comfortable_stop", true);
  param_.turning_hazard_on.emergency = declare_parameter<bool>("turning_hazard_on.emergency", true);
  // phase8-W7 demo extension (not upstream): the takeover request. The
  // contract's takeover_request window is bound to the timeout.
  param_.use_takeover_request = declare_parameter<bool>("use_takeover_request", true);
  param_.takeover_request_timeout = declare_parameter<double>("takeover_request_timeout", 10.0);
  // phase8-W27 (not upstream): how long INIT may last before it is a failure.
  param_.init_timeout = declare_parameter<double>("init_timeout", 3.0);

  // Subscribers — resolved contract names (porting-notes 07); the polling
  // subscribers became caching callbacks (porting-notes 14).
  NROS_SUBSCRIBE(
    tier4_system_msgs::msg::OperationModeAvailability, onOperationModeAvailability,
    "/system/operation_mode/availability", ::nros::QoS(1));
  NROS_SUBSCRIBE(nav_msgs::msg::Odometry, onOdometry, "/localization/kinematic_state", ::nros::QoS(1));
  NROS_SUBSCRIBE(
    autoware_vehicle_msgs::msg::ControlModeReport, onControlMode, "/vehicle/status/control_mode", ::nros::QoS(1));
  NROS_SUBSCRIBE(
    tier4_system_msgs::msg::MrmBehaviorStatus, onComfortableStopStatus,
    "/system/mrm/comfortable_stop/status", ::nros::QoS(1));
  NROS_SUBSCRIBE(
    tier4_system_msgs::msg::MrmBehaviorStatus, onEmergencyStopStatus,
    "/system/mrm/emergency_stop/status", ::nros::QoS(1));
  // TRANSIENT_LOCAL, as upstream: /api/operation_mode/state is published on
  // CHANGE by default_adapi (latched), so a reader that joins after the mode
  // was set sees nothing until the next change unless it reads the publisher's
  // cache. nano-ros serves the subscriber half since phase-473 W2 (one history
  // query on <key>/@adv/** at creation); phase7-W2 F3 had to make this VOLATILE
  // because the backend refused it then.
  create_subscription_in<autoware_adapi_v1_msgs::msg::OperationModeState, MrmHandler,
                         &MrmHandler::onOperationModeState>(
    "/api/operation_mode/state", ::nros::QoS(1).transient_local());

  // Publisher (phase8-W8a: turn indicators, gear and emergency holding
  // dropped for the demo image; see the header).
  pub_hazard_cmd_ = create_publisher_in<autoware_vehicle_msgs::msg::HazardLightsCommand>(
    "/system/emergency/hazard_lights_cmd");
  pub_mrm_state_ =
    create_publisher_in<autoware_adapi_v1_msgs::msg::MrmState>("/system/fail_safe/mrm_state");
  pub_takeover_request_state_ = create_publisher_in<tier4_system_msgs::msg::MrmBehaviorStatus>(
    "/system/takeover_request/state");

  // Clients — POLL model (porting-notes 14). Callback groups dropped (single
  // executor); pull_over client dropped (no on-island operator).
  ::nros::create_service_client_raw(
    *this, client_mrm_comfortable_stop_.bytes, "/system/mrm/comfortable_stop/operate",
    tier4_system_msgs::srv::OperateMrm::TYPE_NAME);
  ::nros::create_service_client_raw(
    *this, client_mrm_emergency_stop_.bytes, "/system/mrm/emergency_stop/operate",
    tier4_system_msgs::srv::OperateMrm::TYPE_NAME);

  // Initialize
  mrm_state_ = {};
  mrm_state_.stamp = now_stamp();
  mrm_state_.state = autoware_adapi_v1_msgs::msg::MrmState::NORMAL;
  mrm_state_.behavior = autoware_adapi_v1_msgs::msg::MrmState::NONE;
  is_operation_mode_availability_timeout = false;
  // Boot: INIT starts here, and a stream never heard is as old as the node.
  stamp_boot_ = now_sec();
  stamp_operation_mode_availability_ = stamp_boot_;

  // Timer
  NROS_CREATE_WALL_TIMER(static_cast<uint64_t>(1000 / param_.update_rate), onTimer);
}

void MrmHandler::onOperationModeAvailability(
  const tier4_system_msgs::msg::OperationModeAvailability & msg)
{
  ISLAND_TRACE(ISLAND_MK_TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY, msg.autonomous);
  stamp_operation_mode_availability_ = now_sec();
  arrivals_operation_mode_availability_.note(stamp_operation_mode_availability_);
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
  // The driver's answer is read here (the contract's `driver_exit` path).
  ISLAND_TRACE(ISLAND_MK_TAKE_MRM_HANDLER_CONTROL_MODE, msg.mode);
  control_mode_ = msg;
  has_control_mode_ = true;
}

void MrmHandler::onComfortableStopStatus(const tier4_system_msgs::msg::MrmBehaviorStatus & msg)
{
  mrm_comfortable_stop_status_ = msg;
  has_mrm_comfortable_stop_status_ = true;
  // phase8-W28: a NOT_AVAILABLE sample restarts the "established" count.
  if (isComfortableStopStatusAvailable()) {
    arrivals_comfortable_stop_status_.note(now_sec());
  } else {
    arrivals_comfortable_stop_status_.reset();
  }
}

void MrmHandler::onEmergencyStopStatus(const tier4_system_msgs::msg::MrmBehaviorStatus & msg)
{
  mrm_emergency_stop_status_ = msg;
  has_mrm_emergency_stop_status_ = true;
  // phase8-W28: a NOT_AVAILABLE sample restarts the "established" count.
  if (isEmergencyStopStatusAvailable()) {
    arrivals_emergency_stop_status_.note(now_sec());
  } else {
    arrivals_emergency_stop_status_.reset();
  }
}

void MrmHandler::onOperationModeState(const autoware_adapi_v1_msgs::msg::OperationModeState & msg)
{
  operation_mode_state_ = msg;
  has_operation_mode_state_ = true;
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

  ISLAND_TRACE(ISLAND_MK_PUB_MRM_HANDLER_HAZARD_LIGHTS_CMD, msg.command);
  pub_hazard_cmd_.publish(msg);
}

void MrmHandler::publishMrmState()
{
  mrm_state_.stamp = now_stamp();
  ISLAND_TRACE(ISLAND_MK_PUB_MRM_HANDLER_MRM_STATE, (mrm_state_.state << 16) | mrm_state_.behavior);
  pub_mrm_state_.publish(mrm_state_);
}

void MrmHandler::publishTakeoverRequestState()
{
  using tier4_system_msgs::msg::MrmBehaviorStatus;
  MrmBehaviorStatus msg{};
  msg.stamp = now_stamp();
  if (!param_.use_takeover_request) {
    msg.state = MrmBehaviorStatus::NOT_AVAILABLE;
  } else {
    msg.state = is_takeover_requested_ ? MrmBehaviorStatus::OPERATING : MrmBehaviorStatus::AVAILABLE;
  }
  ISLAND_TRACE(ISLAND_MK_PUB_MRM_HANDLER_TAKEOVER_REQUEST_STATE, msg.state);
  pub_takeover_request_state_.publish(msg);
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
      ISLAND_TRACE(ISLAND_MK_CALL_MRM_HANDLER_COMFORTABLE_STOP_OPERATE, request.operate);
      break;
    case MrmState::EMERGENCY_STOP:
      client_storage = client_mrm_emergency_stop_.bytes;
      ISLAND_TRACE(ISLAND_MK_CALL_MRM_HANDLER_EMERGENCY_STOP_OPERATE, request.operate);
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
    while (nros_cpp_service_client_take_response(storage, resp, sizeof(resp), &rlen) == 0 &&
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

// phase8-W27: the required inputs are upstream's isDataReady() list -- the
// availability, and each operator status in use, reporting anything but
// NOT_AVAILABLE -- plus the operation mode state, without which every mode
// reads UNKNOWN and so "not available". Odometry and the control mode are not
// in it, as upstream: before they are heard the handler reads "not stopped"
// and "not AUTONOMOUS", the cautious defaults (an MRM is not declared
// finished, and none is started for a vehicle that is not in autonomous
// control).
//
// phase8-W28: INIT ends when each required input is ESTABLISHED, not when it
// has been heard once. One sample says a publisher exists; it does not say
// the stream keeps its period, and a stream that stalls right after its first
// sample (W27's acts a and b: first availability at 0.202 s, the next at
// 0.834 s) turned into an MRM on RUN's first ticks. The rule, per input:
//
//   operation_mode_availability  two consecutive samples at most
//       timeout_operation_mode_availability (0.5 s) apart, the newer one at
//       most that old at the tick. The same bound RUN judges the stream by,
//       so an established stream cannot time out on RUN's first tick.
//   comfortable_stop_status, emergency_stop_status  two consecutive samples,
//       each reporting anything but NOT_AVAILABLE (a NOT_AVAILABLE sample
//       restarts the count), at most timeout_operation_mode_availability
//       apart, the newer one at most that old at the tick. They have no
//       timeout parameter of their own; the operators publish their status
//       every tick (10 Hz and 30 Hz), and the availability timeout is the
//       only stream bound the handler has, 5 periods of the slower one. RUN
//       does not watch them (as before), so this is a start-up rule only.
//   operation_mode_state  ONE sample. It is TRANSIENT_LOCAL and published on
//       change (default_adapi latches it), so a second sample may never come
//       and a "two samples" rule would never end INIT. The sample is the
//       publisher's cache or a change, and either is the current mode.
bool MrmHandler::isEstablished(const Arrivals & a, double window, double now) const
{
  return a.count >= 2 && (a.last - a.prev) <= window && (now - a.last) <= window;
}

void MrmHandler::getUnestablishedInputs(uint32_t & never_heard, uint32_t & not_steady)
{
  const double now = now_sec();
  const double window = param_.timeout_operation_mode_availability;
  never_heard = 0;
  not_steady = 0;

  if (!has_operation_mode_availability_) {
    never_heard |= INPUT_OPERATION_MODE_AVAILABILITY;
  } else if (!isEstablished(arrivals_operation_mode_availability_, window, now)) {
    not_steady |= INPUT_OPERATION_MODE_AVAILABILITY;
  }

  if (!has_operation_mode_state_) never_heard |= INPUT_OPERATION_MODE_STATE;

  if (param_.use_comfortable_stop) {
    if (!has_mrm_comfortable_stop_status_) {
      never_heard |= INPUT_COMFORTABLE_STOP_STATUS;
    } else if (!isEstablished(arrivals_comfortable_stop_status_, window, now)) {
      not_steady |= INPUT_COMFORTABLE_STOP_STATUS;
    }
  }

  if (!has_mrm_emergency_stop_status_) {
    never_heard |= INPUT_EMERGENCY_STOP_STATUS;
  } else if (!isEstablished(arrivals_emergency_stop_status_, window, now)) {
    not_steady |= INPUT_EMERGENCY_STOP_STATUS;
  }
}

// phase8-W27: the start-up lifecycle. Returns false while the tick must stay
// silent (INIT), true once the state machine runs (RUN).
//
//   INIT --(every required input established)----------> RUN
//   INIT --(init_timeout after boot, one is not)-------> RUN, init failure
//   RUN, init failure --(every required input established)--> RUN
//
// There is no way back to INIT. In RUN a missing or stale input is a fault,
// judged by the existing timeouts; the init failure is one more such fault,
// raised once and cleared by the inputs, not by time.
bool MrmHandler::updatePhase()
{
  uint32_t never_heard = 0;
  uint32_t not_steady = 0;
  getUnestablishedInputs(never_heard, not_steady);
  const uint32_t pending = never_heard | not_steady;
  const double since_boot = now_sec() - stamp_boot_;

  if (phase_ == Phase::Run) {
    if (is_init_failed_ && pending == 0) {
      // The recovery is the state machine's, as from any fault: with the
      // init failure gone, isEmergency() is judged on the inputs alone.
      is_init_failed_ = false;
      arm_contract_monitors(ARM_VIA_INIT_RECOVERY);
      std::printf(
        "[mrm_handler] init failure cleared: every input established %d ms after boot\n",
        to_ms(since_boot));
    }
    return true;
  }

  if (pending == 0) {
    phase_ = Phase::Run;
    ISLAND_TRACE(ISLAND_MK_MRM_HANDLER_INIT_DONE, static_cast<uint32_t>(to_ms(since_boot)));
    arm_contract_monitors(ARM_VIA_INIT_DONE);
    std::printf(
      "[mrm_handler] INIT -> RUN: every input established %d ms after boot\n", to_ms(since_boot));
    return true;
  }

  if (since_boot >= param_.init_timeout) {
    phase_ = Phase::Run;
    is_init_failed_ = true;
    // arg: bits 0-3 the inputs never heard, bits 8-11 those heard but not
    // established (bit order: RequiredInput).
    ISLAND_TRACE(ISLAND_MK_MRM_HANDLER_INIT_TIMEOUT, never_heard | (not_steady << 8));
    std::printf(
      "[mrm_handler] ERROR: init failure: %d ms after boot, never heard: ", to_ms(since_boot));
    print_inputs(never_heard);
    std::printf("; not yet steady: ");
    print_inputs(not_steady);
    std::printf("; INIT -> RUN in fault, emergency until they are established\n");
    return true;
  }

  // Still INIT: publish nothing (as upstream while not ready), and say what
  // is awaited, once a second.
  if (!has_stamp_init_log_ || since_boot - stamp_init_log_ >= 1.0) {
    has_stamp_init_log_ = true;
    stamp_init_log_ = since_boot;
    std::printf("[mrm_handler] INIT %d ms: never heard: ", to_ms(since_boot));
    print_inputs(never_heard);
    std::printf("; not yet steady: ");
    print_inputs(not_steady);
    std::printf("\n");
  }
  return false;
}

// An input the handler cannot judge the vehicle by: the availability stream
// has gone stale, or (phase8-W27) a required input was not established
// within init_timeout. Both force the emergency stop and skip the takeover request.
bool MrmHandler::isInputLost()
{
  return is_operation_mode_availability_timeout || is_init_failed_;
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
  ISLAND_TRACE(ISLAND_MK_PATH_MRM_HANDLER_ON_TIMER_ENTRY, mrm_state_.state);
  drainMrmClientReplies();

  if (!updatePhase()) {
    ISLAND_TRACE(ISLAND_MK_PATH_MRM_HANDLER_ON_TIMER_EXIT, 0);
    return;
  }

  checkOperationModeAvailabilityTimeout();
  // call_mrm is this same body on a tick where the availability stream has
  // gone stale, or (phase8-W7) says the current mode is not available: the
  // two faults the contract's `call_mrm` answers.
  const bool is_fault = is_operation_mode_availability_timeout || !isAvailableCurrentOperationMode();
  if (is_fault) {
    ISLAND_TRACE(ISLAND_MK_PATH_MRM_HANDLER_CALL_MRM_ENTRY, mrm_state_.state);
  }
  const bool was_takeover_requested = is_takeover_requested_;
  updateMrmState();
  operateMrm();
  // driver_exit is this same body on the tick that reads the driver's MANUAL
  // while the takeover request is on (the contract's `driver_exit` path).
  const bool is_driver_exit =
    was_takeover_requested && !is_takeover_requested_ && !isControlModeAutonomous();
  if (is_driver_exit) {
    ISLAND_TRACE(ISLAND_MK_PATH_MRM_HANDLER_DRIVER_EXIT_ENTRY, control_mode_.mode);
  }

  publishMrmState();
  publishTakeoverRequestState();
  if (is_driver_exit) {
    ISLAND_TRACE(ISLAND_MK_PATH_MRM_HANDLER_DRIVER_EXIT_EXIT, is_takeover_requested_);
  }
  if (is_fault) {
    ISLAND_TRACE(ISLAND_MK_PATH_MRM_HANDLER_CALL_MRM_EXIT, mrm_state_.state);
  }
  publishHazardCmd();
#if defined(__ZEPHYR__) && defined(CONFIG_ISLAND_DEBUG_OVERRUN)
  // phase9-W4: the commanded overrun, after this tick's publishes so the
  // monitors charge it to them (one dispatch, every monitored publisher whose
  // count advanced in it).
  if (island_debug_overrun_ms != 0u) {
    const uint32_t ms = island_debug_overrun_ms;
    island_debug_overrun_ms = 0u;
    k_busy_wait(ms * 1000u);
  }
#endif
  ISLAND_TRACE(ISLAND_MK_PATH_MRM_HANDLER_ON_TIMER_EXIT, 1);
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
    // Back in the domain (or the stream is back): no request, and the next
    // fault gets a fresh window.
    if (is_takeover_requested_) clearTakeoverRequest("the fault cleared");
    is_takeover_request_expired_ = false;
    if (mrm_state_.state != MrmState::NORMAL) transitionTo(MrmState::NORMAL);
    return;
  }

  const bool is_control_mode_autonomous = isControlModeAutonomous();

  switch (mrm_state_.state) {
    case MrmState::NORMAL:
      // phase8-W7: ask the driver first, then fall to the MRM (below).
      if (updateTakeoverRequest(is_control_mode_autonomous)) return;
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

// phase8-W7 demo extension (not upstream; brief D section 1.5). Autoware
// 1.5.0 has no takeover request. Called in NORMAL while the handler sees a
// fault; returns true while the MRM must wait for the driver. The driver's
// answer needs nothing new: NORMAL starts an MRM only in AUTONOMOUS, so MANUAL
// is the cancel, and this only ends the request. The MRM that follows expiry
// is the one getCurrentMrmBehavior() picks, as for any fault; a silent
// availability stream is never waited on (it forces EMERGENCY_STOP there).
bool MrmHandler::updateTakeoverRequest(const bool is_control_mode_autonomous)
{
  if (!is_control_mode_autonomous) {
    if (is_takeover_requested_) clearTakeoverRequest("the driver took over");
    return false;
  }
  // Only the ODD exit asks the driver: the ADS is driving (operation mode
  // AUTONOMOUS) and its availability says it may not. Any other fault in
  // NORMAL -- a vehicle that boots in AUTONOMOUS control mode with nothing
  // available yet, as the planning simulator does -- takes the MRM at once,
  // as upstream does.
  using autoware_adapi_v1_msgs::msg::OperationModeState;
  if (
    !param_.use_takeover_request || is_takeover_request_expired_ ||
    getCurrentOperationMode() != OperationModeState::AUTONOMOUS) {
    return false;
  }
  if (isInputLost()) {
    if (is_takeover_requested_) clearTakeoverRequest("the availability stream stopped");
    return false;
  }
  if (!is_takeover_requested_) {
    is_takeover_requested_ = true;
    stamp_takeover_request_ = now_sec();
    // Integer ms: the Zephyr image's minimal printf has no %f.
    std::printf(
      "[mrm_handler] takeover request: on, the driver has %d ms\n",
      static_cast<int>(param_.takeover_request_timeout * 1000.0));
    return true;
  }
  if (now_sec() - stamp_takeover_request_ < param_.takeover_request_timeout) {
    return true;
  }
  is_takeover_request_expired_ = true;
  clearTakeoverRequest("the window expired");
  return false;
}

void MrmHandler::clearTakeoverRequest(const char * why)
{
  is_takeover_requested_ = false;
  std::printf(
    "[mrm_handler] takeover request: off after %d ms, %s\n",
    static_cast<int>((now_sec() - stamp_takeover_request_) * 1000.0), why);
}

uint16_t MrmHandler::getCurrentMrmBehavior()
{
  using autoware_adapi_v1_msgs::msg::MrmState;

  if (mrm_state_.behavior == MrmState::NONE || mrm_state_.behavior == MrmState::PULL_OVER) {
    if (isInputLost()) {
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
    if (isInputLost()) {
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
    if (isInputLost()) {
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
  return (abs_d(odom_.twist.twist.linear.x) < th_stopped_velocity);
}

bool MrmHandler::isEmergency()
{
  return !isAvailableCurrentOperationMode() || is_emergency_holding_ || isInputLost();
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

}  // namespace autoware::mrm_handler

// nano-ros port: RCLCPP_COMPONENTS_REGISTER_NODE → NROS_COMPONENT.
NROS_COMPONENT(autoware::mrm_handler::MrmHandler);
