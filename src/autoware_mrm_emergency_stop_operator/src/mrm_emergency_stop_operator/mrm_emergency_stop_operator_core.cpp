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
#include <rclcpp/clock.hpp>

// phase7-W1 trace markers (no-op unless the image enables CTF tracing).
#include "../../../safety_island_tracing/include/island_trace.h"

#if defined(__ZEPHYR__)
#include <zephyr/kernel.h>
#include <zephyr/spinlock.h>
#endif
#if defined(__ZEPHYR__) && defined(CONFIG_ISLAND_SUPERVISOR)
// phase11-S6 (src/zephyr_entry/src/island_supervisor.h): the direct
// emergency path, slot 1.
extern "C" {
uint32_t island_supervisor_latched(void);
typedef void (*island_supervisor_direct_fn)(void * ctx, uint32_t seq, uint32_t since_latch_ms);
void island_supervisor_set_direct(uint32_t slot, island_supervisor_direct_fn fn, void * ctx);
void island_supervisor_handover(uint32_t slot);
}
#endif
#if defined(__ZEPHYR__) && defined(CONFIG_ISLAND_DEBUG_FLOOR_INJECT)
// phase15-S4 test hook (CONFIG_ISLAND_DEBUG_FLOOR_INJECT, only in the
// island-floor-inject snippet's image): 0 from boot; a debugger writes
// non-zero (tools/board/violations.py floor-inject stall) and from the next
// tick in OPERATING this node's timer does nothing: no braking command, no
// status. The operator's tick is not running, while its level still spins.
extern "C" {
volatile uint32_t island_debug_floor_stall;
}
#endif


// nano-ros port: no rclcpp::Clock — stamps come from the platform monotonic
// clock (nros_cpp_time_ns), and dt is computed from message stamps
// (porting-notes 05). <algorithm>/<cmath> avoided — Zephyr minimal libcpp
// has no std headers (porting-notes 18).
namespace
{
double max_d(double a, double b) { return a > b ? a : b; }

// phase8-W18: a STAMP is read by the host, so it comes from the wall clock
// when the image has one (nano-ros issue 0758: the SNTP epoch, installed
// before any component is constructed). Autoware's vehicle_cmd_gate keeps its
// previous hazard/turn/gear command when the new one is stamped earlier
// (getContinuousTopic), so a boot-relative stamp is silently dropped. With no
// epoch the system clock reads 0 and the stamp stays monotonic, knowingly.
// Durations (now_sec) stay on the monotonic clock either way.
builtin_interfaces::msg::Time now_stamp()
{
  const int64_t wall = ::rclcpp::Clock(RCL_SYSTEM_TIME).now().nanoseconds();
  const uint64_t ns = wall > 0 ? static_cast<uint64_t>(wall) : nros_cpp_time_ns();
  builtin_interfaces::msg::Time t;
  t.sec = static_cast<int32_t>(ns / 1000000000ull);
  t.nanosec = static_cast<uint32_t>(ns % 1000000000ull);
  return t;
}

#if defined(__ZEPHYR__) && defined(CONFIG_ISLAND_SUPERVISOR)
// phase11-S6 (decision 2): this operator's half of the direct emergency
// path. Called on the supervisor's reaction thread once the safe-state output
// is latched, then every 33 ms (this node's update_rate), until this node's
// own tick runs OPERATING and takes over (onTimer). It publishes the braking
// command the operator would: from the last control command seen before the
// latch (velocity, acceleration, steering, copied into `seed` by the spin
// thread in onControlCommand), the acceleration ramps at target_jerk to
// target_acceleration and the velocity follows it, in closed form from the
// latch. Everything it reads or writes is in DirectBrake; `last` is what
// onTimer seeds its own ramp from on the takeover, under `lock`.
struct DirectBrake
{
  ::rclcpp::Publisher<autoware_control_msgs::msg::Control> * pub;
  double target_acceleration;
  double target_jerk;
  struct Seed
  {
    volatile float velocity;
    volatile float acceleration;
    volatile float steering;
    volatile uint32_t valid;
  } seed;
  float v0, a0, steer;
  k_spinlock lock;
  autoware_control_msgs::msg::Control last;
  bool has_last;
};
DirectBrake g_direct_brake{};

void direct_brake(void * ctx, uint32_t seq, uint32_t since_latch_ms)
{
  auto * d = static_cast<DirectBrake *>(ctx);
  if (seq == 0u) {
    const bool valid = d->seed.valid != 0u;
    d->v0 = valid ? d->seed.velocity : 0.0f;
    d->a0 = valid ? d->seed.acceleration : 0.0f;
    d->steer = valid ? d->seed.steering : 0.0f;
  }
  const double t = static_cast<double>(since_latch_ms) * 1e-3;
  const double A = d->target_acceleration;  // < 0
  const double J = d->target_jerk;          // < 0
  const double a0 = d->a0 < A ? A : static_cast<double>(d->a0);
  // a(t) = max(a0 + J t, A); v(t) = v0 + the integral, clamped at 0.
  const double t_ramp = (A - a0) / J;  // >= 0
  double acc, vel;
  if (t < t_ramp) {
    acc = a0 + J * t;
    vel = d->v0 + a0 * t + 0.5 * J * t * t;
  } else {
    acc = A;
    vel = d->v0 + a0 * t_ramp + 0.5 * J * t_ramp * t_ramp + A * (t - t_ramp);
  }
  if (vel < 0.0) vel = 0.0;
  autoware_control_msgs::msg::Control c{};
  c.stamp = now_stamp();
  c.longitudinal.stamp = c.stamp;
  c.longitudinal.velocity = static_cast<float>(vel);
  c.longitudinal.acceleration = static_cast<float>(acc);
  c.longitudinal.jerk = acc > A ? static_cast<float>(J) : 0.0f;
  c.lateral.stamp = c.stamp;
  c.lateral.steering_tire_angle = d->steer;
  c.lateral.steering_tire_rotation_rate = 0.0f;
  (void)d->pub->publish(c);
  k_spinlock_key_t key = k_spin_lock(&d->lock);
  d->last = c;
  d->has_last = true;
  k_spin_unlock(&d->lock, key);
}
#endif

double seconds_since(const builtin_interfaces::msg::Time & then)
{
  const auto now = now_stamp();
  return (static_cast<double>(now.sec) - static_cast<double>(then.sec)) +
         (static_cast<double>(now.nanosec) - static_cast<double>(then.nanosec)) * 1e-9;
}
}  // namespace

namespace autoware::mrm_emergency_stop_operator
{

MrmEmergencyStopOperator::MrmEmergencyStopOperator(::rclcpp::NodeHandle handle)
: ::rclcpp::NodeWithTimers<1>(handle, "mrm_emergency_stop_operator")
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
  NROS_SUBSCRIBE(Control, onControlCommand, "/control/command/control_cmd", ::rclcpp::QoS(1));

  // Server
  //   ~/input/mrm/emergency_stop/operate → /system/mrm/emergency_stop/operate
  ::rclcpp::bind_service<OperateMrm, MrmEmergencyStopOperator,
                       &MrmEmergencyStopOperator::operateEmergencyStop>(
    *this, "/system/mrm/emergency_stop/operate", this);

  // Publisher
  //   ~/output/mrm/emergency_stop/status      → /system/mrm/emergency_stop/status
  //   ~/output/mrm/emergency_stop/control_cmd → /system/emergency/control_cmd
  pub_status_ = create_publisher_in<MrmBehaviorStatus>("/system/mrm/emergency_stop/status");
  // phase11-S6: express, as the handler's mrm_state: the supervisor's direct
  // path publishes the braking command on it from its own thread, and a
  // batched sample would wait for a flush a stalled spin thread starves.
  ::rclcpp::QoS express = ::rclcpp::QoS::default_profile();
  express.tx_express(true);
  pub_control_cmd_ = create_publisher_in<Control>("/system/emergency/control_cmd", express);

  // Timer
  NROS_CREATE_WALL_TIMER(static_cast<uint64_t>(1000 / params_.update_rate), onTimer);

#if defined(__ZEPHYR__) && defined(CONFIG_ISLAND_SUPERVISOR)
  // phase11-S6: the direct path publishes on this node's own publisher,
  // built above and never destroyed while the image runs.
  g_direct_brake.pub = &pub_control_cmd_;
  g_direct_brake.target_acceleration = params_.target_acceleration;
  g_direct_brake.target_jerk = params_.target_jerk;
  island_supervisor_set_direct(1u, direct_brake, &g_direct_brake);
#endif

  // Initialize
  status_.state = MrmBehaviorStatus::AVAILABLE;
  is_prev_control_cmd_subscribed_ = false;

  // nano-ros port: parameter update callback (add_on_set_parameters_callback +
  // autoware_utils::update_param) dropped — see porting-notes 03.
}

void MrmEmergencyStopOperator::onControlCommand(const Control & msg)
{
  ISLAND_TRACE_TAKE_BIND(MRM_EMERGENCY_STOP_OPERATOR_CONTROL_CMD);  // phase9-W4 rerun (F4)
  if (status_.state != MrmBehaviorStatus::OPERATING) {
    prev_control_cmd_ = msg;
    is_prev_control_cmd_subscribed_ = true;
#if defined(__ZEPHYR__) && defined(CONFIG_ISLAND_SUPERVISOR)
    // phase11-S6: the direct path's seed, word by word (each a single store).
    g_direct_brake.seed.velocity = msg.longitudinal.velocity;
    g_direct_brake.seed.acceleration = msg.longitudinal.acceleration;
    g_direct_brake.seed.steering = msg.lateral.steering_tire_angle;
    g_direct_brake.seed.valid = 1u;
#endif
  }
}

OperateMrm::Response MrmEmergencyStopOperator::operateEmergencyStop(
  const OperateMrm::Request & request)
{
  // nano-ros port: value-init — generated message structs are plain PODs
  // (no zeroing ctor, unlike rosidl C++ which zero-initializes); a default
  // init here leaked stack garbage into response.code (porting-notes 09).
  OperateMrm::Response response{};
  ISLAND_TRACE(ISLAND_MK_SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_ENTRY, request.operate);
  if (request.operate == true) {
    status_.state = MrmBehaviorStatus::OPERATING;
    response.response.success = true;
  } else {
    status_.state = MrmBehaviorStatus::AVAILABLE;
    response.response.success = true;
  }
  ISLAND_TRACE(ISLAND_MK_SERVE_MRM_EMERGENCY_STOP_OPERATOR_OPERATE_EXIT, status_.state);
  return response;
}

void MrmEmergencyStopOperator::publishStatus()
{
  auto status = status_;
  status.stamp = now_stamp();
  ISLAND_TRACE(ISLAND_MK_PUB_MRM_EMERGENCY_STOP_OPERATOR_STATUS, status.state);
  pub_status_.publish(status);
}

void MrmEmergencyStopOperator::publishControlCommand(const Control & command)
{
  ISLAND_TRACE(ISLAND_MK_PUB_MRM_EMERGENCY_STOP_OPERATOR_EMERGENCY_CONTROL_CMD, status_.state);
  pub_control_cmd_.publish(command);
}

void MrmEmergencyStopOperator::onTimer()
{
  // phase9-W4 rerun (phase-474 I3): this 30 Hz tick keeps every start/end pair
  // in nano-ros's callback trace while CONFIG_NROS_TRACE_TIMER_EVERY thins the
  // rest to one in ten (the island's own sink does not forward 18/19).
  ISLAND_TRACE_TIMER_BIND(1);
#if defined(__ZEPHYR__) && defined(CONFIG_ISLAND_DEBUG_FLOOR_INJECT)
  if (island_debug_floor_stall != 0u && status_.state == MrmBehaviorStatus::OPERATING) {
    static bool stall_seen = false;
    if (!stall_seen) {
      stall_seen = true;
      ISLAND_TRACE(ISLAND_MK_SUPERVISOR_INJECT, 0xFFFFFFFBu);
    }
    return;
  }
#endif
  ISLAND_TRACE(ISLAND_MK_PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER_ENTRY, status_.state);
  if (status_.state == MrmBehaviorStatus::OPERATING) {
#if defined(__ZEPHYR__) && defined(CONFIG_ISLAND_SUPERVISOR)
    // phase11-S6: the supervisor's direct path braked first; this tick takes
    // over and continues its ramp from the last command it published.
    if (!direct_taken_over_ && island_supervisor_latched() != 0u) {
      direct_taken_over_ = true;
      k_spinlock_key_t key = k_spin_lock(&g_direct_brake.lock);
      if (g_direct_brake.has_last) {
        prev_control_cmd_ = g_direct_brake.last;
        is_prev_control_cmd_subscribed_ = true;
      }
      k_spin_unlock(&g_direct_brake.lock, key);
      island_supervisor_handover(1u);
    }
#endif
    auto control_cmd = calcTargetAcceleration(prev_control_cmd_);
    publishControlCommand(control_cmd);
    prev_control_cmd_ = control_cmd;
  } else {
#if defined(__ZEPHYR__) && defined(CONFIG_ISLAND_SUPERVISOR)
    // phase15-S2: latched and not OPERATING (the operate request never
    // arrived): the direct path is the one braking on this topic, and the
    // pass-through of the last control command would interleave with it.
    if (island_supervisor_latched() == 0u) {
      publishControlCommand(prev_control_cmd_);
    }
#else
    publishControlCommand(prev_control_cmd_);
#endif
  }
  publishStatus();
  ISLAND_TRACE(ISLAND_MK_PATH_MRM_EMERGENCY_STOP_OPERATOR_ON_TIMER_EXIT, status_.state);
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
  // CLOCK-DOMAIN GUARD: the seed command comes from the HOST Autoware stack
  // (wall-clock stamps, ~1.8e9 s) while the island clock is platform
  // monotonic (boots near 0). A cross-clock dt is meaningless — the first
  // MRM tick computed dt ≈ -1.8e9 s and the "deceleration ramp" integrated
  // to +2.7e9 m/s², accelerating the vehicle to the sim cap. Clamp dt to
  // the timer-period scale: exact for steady-state ticks (same clock,
  // 1/update_rate), inert for the one cross-clock seed tick.
  const double raw_dt = seconds_since(prev_control_cmd.stamp);
  const double dt = raw_dt < 0.0 ? 0.0 : (raw_dt > 0.1 ? 0.1 : raw_dt);

  control_cmd.stamp = now_stamp();
  control_cmd.longitudinal.stamp = control_cmd.stamp;
  control_cmd.longitudinal.velocity = static_cast<float>(max_d(
    static_cast<double>(prev_control_cmd.longitudinal.velocity) +
      static_cast<double>(prev_control_cmd.longitudinal.acceleration) * dt,
    0.0));
  control_cmd.longitudinal.acceleration = static_cast<float>(max_d(
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

}  // namespace autoware::mrm_emergency_stop_operator

// nano-ros port: RCLCPP_COMPONENTS_REGISTER_NODE → NROS_COMPONENT (the
// C-ABI factory the generated entry constructs the node through).
NROS_COMPONENT(autoware::mrm_emergency_stop_operator::MrmEmergencyStopOperator);
