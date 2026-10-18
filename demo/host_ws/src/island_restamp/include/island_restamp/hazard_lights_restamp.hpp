// phase9-W9: subscribes the island's hazard-lights command (`input`,
// remapped to /system/emergency/hazard_lights_cmd) and republishes it at
// once, unchanged but for the stamp, which is this node's clock at receipt
// (`output`, remapped to the topic vehicle_cmd_gate's emergency input reads).
// One message out per message in: it never repeats or invents a command, so
// an island that falls silent stays silent. include/island_restamp/restamp.hpp
// says why.
#pragma once

#include "island_restamp/restamp.hpp"

#include <rclcpp/rclcpp.hpp>

#include <cstdint>
#include <optional>

namespace island_restamp
{

using autoware_vehicle_msgs::msg::HazardLightsCommand;

class HazardLightsRestamp : public rclcpp::Node
{
public:
  explicit HazardLightsRestamp(const rclcpp::NodeOptions & options)
  : Node("hazard_lights_restamp", options)
  {
    // depth 1, reliable, volatile: what vehicle_cmd_gate's polling
    // subscription and the island's publisher use.
    const auto qos = rclcpp::QoS{1};
    pub_ = create_publisher<HazardLightsCommand>("output", qos);
    sub_ = create_subscription<HazardLightsCommand>(
      "input", qos, [this](HazardLightsCommand::ConstSharedPtr msg) { on_command(*msg); });
  }

private:
  void on_command(const HazardLightsCommand & in)
  {
    const auto out = restamp(in, now());
    pub_->publish(out);
    // One line per command change (10 Hz input otherwise): both stamps, so a
    // run's log shows which clock the island was on.
    if (!last_command_ || *last_command_ != in.command) {
      RCLCPP_INFO(
        get_logger(), "hazard lights %u: island stamp %d.%09u, host stamp %d.%09u",
        static_cast<unsigned>(in.command),
        in.stamp.sec, in.stamp.nanosec, out.stamp.sec, out.stamp.nanosec);
      last_command_ = in.command;
    }
  }

  rclcpp::Publisher<HazardLightsCommand>::SharedPtr pub_;
  rclcpp::Subscription<HazardLightsCommand>::SharedPtr sub_;
  std::optional<uint8_t> last_command_;
};

}  // namespace island_restamp
