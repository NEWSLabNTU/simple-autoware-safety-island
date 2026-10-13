#!/usr/bin/env python3
"""A stand-in for the island's two always-on outputs, for runs with no island.

CARLA demo unit C1 (docs/design/carla-island-demo.md section 5) runs the ego
with the island's overlay, which removes Autoware's mrm_handler and MRM
operators, and with no island attached. Two of the island's outputs are then
missing, and Autoware will not drive without them:

  /system/fail_safe/mrm_state     (MrmState, 10 Hz)  vehicle_cmd_gate's system
                                  heartbeat; without it the gate holds an
                                  emergency and refuses to engage
  /system/emergency/control_cmd   (Control, 30 Hz)   the diagnostic graph's
                                  /autoware/system/topic_rate_check/emergency_control_command,
                                  in every mode's subtree: without it
                                  autonomous is never available

This publishes what the island publishes while nothing is wrong: mrm_state
NORMAL / NONE, and the emergency stop operator's idle output, which passes
the latest /control/command/control_cmd through (as the island's
mrm_emergency_stop_operator does before it operates). It never reacts: an MRM
request, an availability drop or an ODD exit changes nothing here, which is
exactly "nothing answers MRM" (G1). Never run it beside an island: two
publishers of mrm_state would mask the island's.

demo/l3 (Step 1, the host path) used the same stand-in by hand.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy

from autoware_adapi_v1_msgs.msg import MrmState
from autoware_control_msgs.msg import Control


class IslandStandin(Node):
    def __init__(self):
        super().__init__("island_standin")
        qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE,
                         history=HistoryPolicy.KEEP_LAST, depth=1)
        self.pub_state = self.create_publisher(MrmState, "/system/fail_safe/mrm_state", qos)
        self.pub_cmd = self.create_publisher(Control, "/system/emergency/control_cmd", qos)
        self.create_subscription(Control, "/control/command/control_cmd", self.on_cmd, qos)
        self.last_cmd = Control()
        self.create_timer(0.1, self.on_state_timer)
        self.create_timer(1.0 / 30.0, self.on_cmd_timer)
        self.get_logger().warn("island stand-in: mrm_state NORMAL at 10 Hz, emergency control_cmd "
                               "pass-through at 30 Hz; no MRM reaction (no island attached)")

    def on_cmd(self, msg):
        self.last_cmd = msg

    def on_state_timer(self):
        msg = MrmState()
        msg.stamp = self.get_clock().now().to_msg()
        msg.state = MrmState.NORMAL
        msg.behavior = MrmState.NONE
        self.pub_state.publish(msg)

    def on_cmd_timer(self):
        msg = self.last_cmd
        msg.stamp = self.get_clock().now().to_msg()
        self.pub_cmd.publish(msg)


def main():
    rclpy.init()
    node = IslandStandin()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
