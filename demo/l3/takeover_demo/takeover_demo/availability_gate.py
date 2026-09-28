"""availability_gate: Autoware's availability, with the ODD folded in.

The overlay renames the stock converter's output to
/system/operation_mode/availability_raw; this node republishes every raw
sample on /system/operation_mode/availability -- the topic the island's
mrm_handler guards -- with `autonomous &= !odd_exit`. Same type, same QoS
(depth 1, reliable, volatile), one sample out per sample in, so the rate the
island sees is the converter's.

Fail-safe by construction: if this process stops (SIGSTOP, crash, the HPC
pulled), the stream stops and the island's 0.5 s availability timeout fires.
That is the demo's HPC-loss act. If the ODD monitor is silent for longer than
`odd_timeout_s`, the ODD is treated as left.
"""
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool
from tier4_system_msgs.msg import OperationModeAvailability

from . import common as c


class AvailabilityGate(Node):
    def __init__(self):
        super().__init__('availability_gate')
        self.odd_timeout = self.declare_parameter('odd_timeout_s', 1.0).value
        self.odd_exit = None
        self.odd_t = 0.0
        self.last_out = None
        self.n = 0
        self.pub = self.create_publisher(OperationModeAvailability, c.AVAILABILITY, c.qos_volatile())
        self.create_subscription(OperationModeAvailability, c.AVAILABILITY_RAW, self.on_raw, c.qos_volatile())
        self.create_subscription(Bool, c.ODD_EXIT, self.on_odd, c.qos_volatile())

    def on_odd(self, m):
        self.odd_exit = m.data
        self.odd_t = time.monotonic()

    def on_raw(self, raw):
        stale = self.odd_exit is None or time.monotonic() - self.odd_t > self.odd_timeout
        blocked = stale or self.odd_exit
        out = raw
        out.autonomous = bool(raw.autonomous and not blocked)
        self.pub.publish(out)
        self.n += 1
        if out.autonomous != self.last_out:
            why = 'odd monitor silent' if stale else ('ODD exit' if self.odd_exit else 'in ODD')
            self.get_logger().info(
                f'availability.autonomous -> {out.autonomous} (raw {raw.autonomous}, {why}) '
                f'sample {self.n} {c.stamp()}')
            self.last_out = out.autonomous


def main():
    rclpy.init()
    node = AvailabilityGate()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
