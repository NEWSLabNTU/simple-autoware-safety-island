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

#ifndef CONTINUOUS_CONDITION_HPP_
#define CONTINUOUS_CONDITION_HPP_

// nano-ros port: rclcpp::Time → double seconds from the platform monotonic
// clock (porting-notes 05); std::optional (C++17) → sentinel flags (the
// nano-ros C++ surface targets C++14).

// nano-ros port: namespace flattened (identity rule, porting-notes 02).
namespace autoware_stop_mode_operator
{

class ContinuousCondition
{
public:
  void update(double stamp_sec, bool condition);
  void update_timeout(double stamp_sec, double timeout);
  bool check(double stamp_sec, double duration) const;

private:
  bool has_last_{false};
  bool has_start_{false};
  double last_stamp_{0.0};
  double start_stamp_{0.0};
};

}  // namespace autoware_stop_mode_operator

#endif  // CONTINUOUS_CONDITION_HPP_
