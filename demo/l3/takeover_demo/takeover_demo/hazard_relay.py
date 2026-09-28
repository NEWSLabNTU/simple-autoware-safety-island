"""hazard_relay: the island's hazard lights, in the comfortable-stop branch.

VERIFIED in the 1.5.0 source (autoware_vehicle_cmd_gate/src/
vehicle_cmd_gate.cpp, onMrmState): the gate treats the system as in
emergency, and takes the island's /system/emergency/* commands (control,
gear, hazard, turn), ONLY while mrm_state.state is MRM_OPERATING,
MRM_SUCCEEDED or MRM_FAILED AND mrm_state.behavior == EMERGENCY_STOP. In a
COMFORTABLE_STOP the gate keeps passing the planner's commands, and the
planner's hazard lights come from autoware_hazard_lights_selector, which ORs
/planning/behavior_path_planner/hazard_lights_cmd with its system input
/system/hazard_lights_cmd. Nothing drives that input once the stock MRM is
disabled, so without this relay a comfortable stop has no hazard lights.

At `rate_hz` (10) it publishes /system/hazard_lights_cmd: the island's last
/system/emergency/hazard_lights_cmd while mrm_state says COMFORTABLE_STOP
(operating or succeeded), DISABLE otherwise. DISABLE is always safe to send:
the selector ORs its two inputs, and it keeps the last system sample
forever, so the relay must keep saying DISABLE rather than fall silent.
"""
import time

import rclpy
from autoware_adapi_v1_msgs.msg import MrmState
from autoware_vehicle_msgs.msg import HazardLightsCommand
from rclpy.node import Node

from . import common as c


class HazardRelay(Node):
    def __init__(self):
        super().__init__('hazard_relay')
        rate = self.declare_parameter('rate_hz', 10.0).value
        self.fresh = self.declare_parameter('input_timeout_s', 1.0).value
        self.mrm = None
        self.hazard = None
        self.hazard_t = 0.0
        self.last = None
        self.pub = self.create_publisher(HazardLightsCommand, c.SYSTEM_HAZARD, c.qos_volatile())
        self.create_subscription(MrmState, c.MRM_STATE, self.on_mrm, c.qos_volatile())
        self.create_subscription(HazardLightsCommand, c.EMERGENCY_HAZARD, self.on_hazard, c.qos_volatile())
        self.create_timer(1.0 / rate, self.on_timer)

    def on_mrm(self, m):
        self.mrm = m

    def on_hazard(self, m):
        self.hazard = m.command
        self.hazard_t = time.monotonic()

    def on_timer(self):
        comfortable = (self.mrm is not None
                       and self.mrm.behavior == MrmState.COMFORTABLE_STOP
                       and self.mrm.state in (MrmState.MRM_OPERATING, MrmState.MRM_SUCCEEDED))
        fresh = time.monotonic() - self.hazard_t < self.fresh
        on = comfortable and fresh and self.hazard == HazardLightsCommand.ENABLE
        out = HazardLightsCommand()
        out.stamp = self.get_clock().now().to_msg()
        out.command = HazardLightsCommand.ENABLE if on else HazardLightsCommand.DISABLE
        self.pub.publish(out)
        if on != self.last:
            self.get_logger().info(f'system hazard lights -> {"ENABLE" if on else "DISABLE"} {c.stamp()}')
            self.last = on


def main():
    rclpy.init()
    node = HazardRelay()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
