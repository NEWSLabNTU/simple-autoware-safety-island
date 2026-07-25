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

#include "continuous_condition.hpp"

namespace autoware::stop_mode_operator
{

void ContinuousCondition::update(double stamp_sec, bool condition)
{
  if (!condition) {
    has_last_ = false;
    has_start_ = false;
  } else {
    last_stamp_ = stamp_sec;
    has_last_ = true;
    if (!has_start_) {
      start_stamp_ = stamp_sec;
      has_start_ = true;
    }
  }
}

void ContinuousCondition::update_timeout(double stamp_sec, double timeout)
{
  if (has_last_) {
    if (timeout <= (stamp_sec - last_stamp_)) {
      has_last_ = false;
      has_start_ = false;
    }
  }
}

bool ContinuousCondition::check(double stamp_sec, double duration) const
{
  if (!has_start_) {
    return false;
  }
  return duration <= (stamp_sec - start_stamp_);
}

}  // namespace autoware::stop_mode_operator
