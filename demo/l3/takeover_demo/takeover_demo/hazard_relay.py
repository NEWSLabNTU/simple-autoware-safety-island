"""hazard_relay: the island's hazard lights, into Autoware's AUTO path.

The ONE publisher of /system/hazard_lights_cmd (phase9-W9). Until then
W18's topic_tools relay in the demo's tier4_system_launch also published
there, forwarding the island's command as received, while this node said
DISABLE outside a comfortable stop: in a takeover request (MRM NORMAL, the
island's ENABLE) the two raced at the selector, which keeps whichever
sample came last, so act a's hazard lights flickered or never showed. The
relay is gone; this node carries both jobs.

VERIFIED in the 1.5.0 source: vehicle_cmd_gate takes the island's
/system/emergency/* commands only while mrm_state.behavior is EMERGENCY_STOP
(onMrmState); otherwise it passes the AUTO hazard command,
/planning/hazard_lights_cmd, which autoware_hazard_lights_selector ORs from
the path planner and from its system input /system/hazard_lights_cmd, and
restamps with host time. So outside an emergency stop this input is the only
way the island's hazard lights reach the vehicle.

What it says (`system_command`): ENABLE while the island's last
/system/emergency/hazard_lights_cmd is ENABLE and fresh (younger than
`input_timeout_s`), DISABLE otherwise. The island already decides when the
lights are on (mrm_handler: ENABLE in a takeover request, a comfortable stop
and an emergency stop; NO_COMMAND in NORMAL), so this node forwards that
decision and adds no state machine of its own; in an emergency stop the
gate reads the island's command directly (through island_restamp) and this
input is moot but consistent. It publishes at `rate_hz` (10) whatever
happens: the selector keeps its last system sample forever, so falling
silent after an ENABLE would leave the lights on. A silent island therefore
turns the lights off after `input_timeout_s`, the stock behavior without an
MRM.
"""
import time

import rclpy
from autoware_vehicle_msgs.msg import HazardLightsCommand
from rclpy.node import Node

from . import common as c


def system_command(island_command, age_s, timeout_s):
    """The selector's system input for the island's last command, received
    `age_s` ago (None: never)."""
    fresh = age_s is not None and age_s < timeout_s
    if fresh and island_command == HazardLightsCommand.ENABLE:
        return HazardLightsCommand.ENABLE
    return HazardLightsCommand.DISABLE


class HazardRelay(Node):
    def __init__(self):
        super().__init__('hazard_relay')
        rate = self.declare_parameter('rate_hz', 10.0).value
        self.timeout = self.declare_parameter('input_timeout_s', 1.0).value
        self.hazard = None
        self.hazard_t = None
        self.last = None
        self.pub = self.create_publisher(HazardLightsCommand, c.SYSTEM_HAZARD, c.qos_volatile())
        self.create_subscription(HazardLightsCommand, c.EMERGENCY_HAZARD, self.on_hazard, c.qos_volatile())
        self.create_timer(1.0 / rate, self.on_timer)

    def on_hazard(self, m):
        self.hazard = m.command
        self.hazard_t = time.monotonic()

    def on_timer(self):
        age = None if self.hazard_t is None else time.monotonic() - self.hazard_t
        cmd = system_command(self.hazard, age, self.timeout)
        out = HazardLightsCommand()
        out.stamp = self.get_clock().now().to_msg()
        out.command = cmd
        self.pub.publish(out)
        if cmd != self.last:
            name = 'ENABLE' if cmd == HazardLightsCommand.ENABLE else 'DISABLE'
            self.get_logger().info(f'system hazard lights -> {name} {c.stamp()}')
            self.last = cmd


def main():
    rclpy.init()
    node = HazardRelay()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
