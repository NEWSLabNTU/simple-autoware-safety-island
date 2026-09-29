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
#include <autoware_vehicle_msgs/msg/hazard_lights_command.hpp>
#include <tier4_system_msgs/msg/mrm_behavior_status.hpp>
#include <tier4_system_msgs/msg/operation_mode_availability.hpp>
#include <tier4_system_msgs/srv/operate_mrm.hpp>

#include <nav_msgs/msg/odometry.hpp>

// nano-ros port: <rclcpp/rclcpp.hpp> -> nros::Node (porting-notes 01). A
// component IS-A node since nano-ros 1f3b88aec; the timer pool is the base's
// template argument, so a node with one timer derives NodeWithTimers<1>.
#include <nros/component.hpp>
// component_node.hpp used to pull this in; component.hpp does not, and the
// nros::Publisher<M> members below plus create_publisher_in need it complete.
#include <nros/publisher.hpp>
// The freestanding parameter forwarders the declare_parameter helper below
// calls (nros::Node hosts the same facade, but only under NROS_CPP_STD).
#include <nros/node_parameters.hpp>

namespace autoware::mrm_handler
{

struct HazardLampPolicy
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
  bool use_pull_over;
  bool use_comfortable_stop;
  HazardLampPolicy turning_hazard_on{};
  // phase8-W7 demo extension (not upstream): the takeover request.
  bool use_takeover_request;
  double takeover_request_timeout;
};

class MrmHandler : public ::nros::NodeWithTimers<1>
{
public:
  explicit MrmHandler(::nros::NodeHandle handle);

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

  tier4_system_msgs::msg::OperationModeAvailability operation_mode_availability_{};
  bool has_operation_mode_availability_{false};
  // phase8-W10: when the first availability sample arrived (the join grace below)
  double stamp_first_operation_mode_availability_{0.0};
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

  // Publisher. phase8-W8a (demo trim, not upstream): the turn-indicator,
  // gear and emergency-holding publishers and the gear pass-through input are
  // gone; their only readers hold or default the same values without them
  // (safety_island.contract.yaml, "WHAT THE IMAGE LEAVES OUT").
  ::nros::Publisher<autoware_vehicle_msgs::msg::HazardLightsCommand> pub_hazard_cmd_;
  ::nros::Publisher<autoware_adapi_v1_msgs::msg::MrmState> pub_mrm_state_;
  // phase8-W7: /system/takeover_request/state. MrmBehaviorStatus reused
  // (AVAILABLE = idle, OPERATING = request on) so the island needs no new
  // message package.
  ::nros::Publisher<tier4_system_msgs::msg::MrmBehaviorStatus> pub_takeover_request_state_;

  void publishHazardCmd();
  void publishMrmState();
  void publishTakeoverRequestState();

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

  // Takeover request (phase8-W7 demo extension, not upstream; porting-notes).
  // Entered on the value fault while AUTONOMOUS, left on MANUAL (the driver
  // answered), on expiry (the MRM starts) or when the fault clears.
  bool is_takeover_requested_{false};
  bool is_takeover_request_expired_{false};
  double stamp_takeover_request_{0.0};
  bool updateTakeoverRequest(bool is_control_mode_autonomous);
  void clearTakeoverRequest(const char * why);

  // Algorithm
  bool is_emergency_holding_ = false;
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
