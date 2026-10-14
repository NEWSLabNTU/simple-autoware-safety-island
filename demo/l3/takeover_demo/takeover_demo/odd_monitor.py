"""odd_monitor: is the vehicle inside its operational design domain?

Two automatic conditions and one manual one, each LATCHED once it fires
(an ODD exit starts a takeover; it does not un-happen when the speed drops
again) until `~/clear` or `/demo/odd/inject false`:

  speed    |v| from /localization/kinematic_state above `max_speed_kmh`
           (30 km/h: the user's decision, phase-8 section 7 item 2)
  segment  the pose outside `segment_polygon` ("x,y;x,y;..." in map
           coordinates; empty = no segment bound). Armed by the first pose
           inside the polygon, so a pose before localization settles (or
           before the scenario's teleport) cannot latch an exit.
  inject   the booth button: `~/inject_exit` (std_srvs/Trigger) or
           /demo/odd/inject (std_msgs/Bool true)

The ODD can instead come from the scenario: `scenario_file` names an
OpenSCENARIO file whose ParameterDeclarations state IslandOddPolygon and/or
IslandOddMaxSpeed (odd_scenario.py). A declared value replaces the
parameter's; `segment_polygon` and a scenario polygon together are refused
(two sources for one bound).

Publishes /demo/odd/exit (std_msgs/Bool) and /demo/odd/reason
(std_msgs/String) at `rate_hz` (10), and once more at the instant an exit
fires, so the verdict leaves this node with the pose that caused it rather
than up to one period later (CARLA demo C4: the gate's receipt of it starts
the act's record).
"""
import math

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger

from . import common as c
from .odd_scenario import inside, parse_polygon, read_scenario_odd


class OddMonitor(Node):
    def __init__(self):
        super().__init__('odd_monitor')
        max_kmh = self.declare_parameter('max_speed_kmh', 30.0).value
        poly_text = self.declare_parameter('segment_polygon', '').value
        scenario = self.declare_parameter('scenario_file', '').value
        source = 'parameters'
        if scenario:
            s_poly, s_kmh = read_scenario_odd(scenario)
            if s_poly is not None:
                if poly_text:
                    raise ValueError('segment_polygon and the scenario both state the ODD polygon')
                poly_text = s_poly
            if s_kmh is not None:
                max_kmh = s_kmh
            source = scenario
        self.max_speed = max_kmh / 3.6
        self.poly = parse_polygon(poly_text)
        self.armed = False
        rate = self.declare_parameter('rate_hz', 10.0).value
        self.exit_reason = ''
        self.v = None
        self.pub_exit = self.create_publisher(Bool, c.ODD_EXIT, c.qos_volatile())
        self.pub_reason = self.create_publisher(String, c.ODD_REASON, c.qos_volatile())
        self.create_subscription(Odometry, c.KINEMATIC_STATE, self.on_odom, c.qos_volatile())
        self.create_subscription(Bool, c.ODD_INJECT, self.on_inject, c.qos_volatile())
        self.create_service(Trigger, '~/inject_exit', self.srv_inject)
        self.create_service(Trigger, '~/clear', self.srv_clear)
        self.create_timer(1.0 / rate, self.on_timer)
        self.get_logger().info(
            f'ODD: |v| <= {self.max_speed * 3.6:.1f} km/h'
            + (f', inside a {len(self.poly)}-point segment' if self.poly else ', no segment bound')
            + f' (from {source})')

    def fire(self, reason):
        if not self.exit_reason:
            self.exit_reason = reason
            self.get_logger().warn(f'ODD EXIT ({reason}) {c.stamp()}')
            self.on_timer()

    def clear(self):
        if self.exit_reason:
            self.get_logger().info(f'ODD exit cleared (was {self.exit_reason}) {c.stamp()}')
        self.exit_reason = ''

    def on_odom(self, m):
        self.v = m.twist.twist.linear.x
        if abs(self.v) > self.max_speed:
            self.fire(f'speed {abs(self.v) * 3.6:.1f} km/h > {self.max_speed * 3.6:.1f}')
        p = m.pose.pose.position
        if not self.poly:
            return
        if inside(self.poly, p.x, p.y):
            if not self.armed:
                self.armed = True
                self.get_logger().info(f'ODD segment armed at ({p.x:.1f}, {p.y:.1f}) {c.stamp()}')
        elif self.armed:
            self.fire(f'segment ({p.x:.1f}, {p.y:.1f}) outside the ODD polygon')

    def on_inject(self, m):
        self.fire('inject') if m.data else self.clear()

    def srv_inject(self, _req, res):
        self.fire('inject')
        res.success, res.message = True, self.exit_reason
        return res

    def srv_clear(self, _req, res):
        self.clear()
        res.success, res.message = True, 'in ODD'
        return res

    def on_timer(self):
        self.pub_exit.publish(Bool(data=bool(self.exit_reason)))
        self.pub_reason.publish(String(data=self.exit_reason or 'in ODD'))


def main():
    rclpy.init()
    node = OddMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
