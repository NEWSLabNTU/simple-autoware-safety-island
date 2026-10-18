// phase9-W9: the restamp, alone and through the node.
#include "island_restamp/hazard_lights_restamp.hpp"

#include <gtest/gtest.h>

#include <rclcpp/rclcpp.hpp>
#include <rosgraph_msgs/msg/clock.hpp>

#include <chrono>
#include <memory>
#include <string>
#include <thread>
#include <vector>

using autoware_vehicle_msgs::msg::HazardLightsCommand;
using namespace std::chrono_literals;

namespace
{

// A boot-relative stamp, as the board sends: two minutes after reset.
HazardLightsCommand island_command(uint8_t command)
{
  HazardLightsCommand m;
  m.stamp.sec = 120;
  m.stamp.nanosec = 500000000u;
  m.command = command;
  return m;
}

int64_t ns(const builtin_interfaces::msg::Time & t)
{
  return static_cast<int64_t>(t.sec) * 1000000000LL + t.nanosec;
}

}  // namespace

TEST(Restamp, ReplacesTheStampOnly)
{
  builtin_interfaces::msg::Time now;
  now.sec = 1792140133;
  now.nanosec = 92600110u;
  for (uint8_t c :
       {HazardLightsCommand::NO_COMMAND, HazardLightsCommand::DISABLE,
        HazardLightsCommand::ENABLE}) {
    const auto out = island_restamp::restamp(island_command(c), now);
    EXPECT_EQ(out.command, c);
    EXPECT_EQ(out.stamp.sec, now.sec);
    EXPECT_EQ(out.stamp.nanosec, now.nanosec);
  }
}

// The node in process, on topics of its own: what goes in comes out once,
// with the node's clock as the stamp.
class RestampNode : public ::testing::Test
{
protected:
  static void SetUpTestSuite() { rclcpp::init(0, nullptr); }
  static void TearDownTestSuite() { rclcpp::shutdown(); }

  void start(const std::string & tag, bool sim_time)
  {
    const std::string in = "/w9_test/" + tag + "/in", out = "/w9_test/" + tag + "/out";
    rclcpp::NodeOptions opts;
    opts.arguments({"--ros-args", "-r", "input:=" + in, "-r", "output:=" + out});
    opts.append_parameter_override("use_sim_time", sim_time);
    node_ = std::make_shared<island_restamp::HazardLightsRestamp>(opts);
    peer_ = std::make_shared<rclcpp::Node>("w9_test_peer_" + tag);
    pub_ = peer_->create_publisher<HazardLightsCommand>(in, rclcpp::QoS{1});
    clock_pub_ = peer_->create_publisher<rosgraph_msgs::msg::Clock>("/clock", rclcpp::QoS{10});
    sub_ = peer_->create_subscription<HazardLightsCommand>(
      out, rclcpp::QoS{10}, [this](HazardLightsCommand::ConstSharedPtr m) { got_.push_back(*m); });
    exec_.add_node(node_);
    exec_.add_node(peer_);
    // discovery: until the node sees the peer's publisher and the peer sees
    // the node's
    spin_until([&] {
      return pub_->get_subscription_count() > 0 && sub_->get_publisher_count() > 0;
    });
  }

  void TearDown() override
  {
    if (node_) exec_.remove_node(node_);
    if (peer_) exec_.remove_node(peer_);
  }

  template <class Pred>
  bool spin_until(Pred done, std::chrono::milliseconds limit = 5000ms)
  {
    const auto end = std::chrono::steady_clock::now() + limit;
    while (!done() && std::chrono::steady_clock::now() < end) {
      exec_.spin_some(10ms);
      std::this_thread::sleep_for(1ms);
    }
    return done();
  }

  rclcpp::executors::SingleThreadedExecutor exec_;
  std::shared_ptr<island_restamp::HazardLightsRestamp> node_;
  std::shared_ptr<rclcpp::Node> peer_;
  rclcpp::Publisher<HazardLightsCommand>::SharedPtr pub_;
  rclcpp::Publisher<rosgraph_msgs::msg::Clock>::SharedPtr clock_pub_;
  rclcpp::Subscription<HazardLightsCommand>::SharedPtr sub_;
  std::vector<HazardLightsCommand> got_;
};

// The planning simulator's case: the host runs on the wall clock, the
// island's stamp is two minutes after its reset. Out comes the host's time.
TEST_F(RestampNode, WallClockStampAtReceipt)
{
  start("wall", false);
  const int64_t before = node_->now().nanoseconds();
  pub_->publish(island_command(HazardLightsCommand::ENABLE));
  ASSERT_TRUE(spin_until([&] { return !got_.empty(); }));
  const int64_t after = node_->now().nanoseconds();
  ASSERT_EQ(got_.size(), 1u);
  EXPECT_EQ(got_[0].command, HazardLightsCommand::ENABLE);
  EXPECT_GE(ns(got_[0].stamp), before);
  EXPECT_LE(ns(got_[0].stamp), after);
  // no repeats: nothing more arrives without another input
  spin_until([] { return false; }, 300ms);
  EXPECT_EQ(got_.size(), 1u);
}

// The CARLA case: Autoware on /clock. The stamp is the simulation time at
// receipt, whatever the island's boot stamp says.
TEST_F(RestampNode, SimTimeStampAtReceipt)
{
  start("sim", true);
  rosgraph_msgs::msg::Clock c;
  c.clock.sec = 5000;
  c.clock.nanosec = 250000000u;
  ASSERT_TRUE(spin_until([&] {
    clock_pub_->publish(c);
    return node_->now().nanoseconds() == ns(c.clock);
  }));
  pub_->publish(island_command(HazardLightsCommand::ENABLE));
  ASSERT_TRUE(spin_until([&] { return got_.size() >= 1; }));
  pub_->publish(island_command(HazardLightsCommand::NO_COMMAND));
  ASSERT_TRUE(spin_until([&] { return got_.size() >= 2; }));
  ASSERT_EQ(got_.size(), 2u);
  EXPECT_EQ(got_[0].command, HazardLightsCommand::ENABLE);
  EXPECT_EQ(got_[1].command, HazardLightsCommand::NO_COMMAND);
  for (const auto & m : got_) EXPECT_EQ(ns(m.stamp), ns(c.clock));
}
