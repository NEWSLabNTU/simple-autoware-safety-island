"""takeover_hmi: the cabin's takeover request (TOR), a 10 s countdown.

States, published on /demo/takeover/state (std_msgs/String) with the
seconds left on /demo/takeover/remaining (std_msgs/Float32), both at
`rate_hz` (10):

  NOT_ENGAGED       Autoware is not driving (operation mode != AUTONOMOUS or
                    the vehicle's control mode != AUTONOMOUS)
  AUTOPILOT         driving autonomously inside the ODD
  TOR_ACTIVE        the ODD was left while driving; the driver has
                    `takeover_request_timeout` (10 s, phase-8 section 7
                    item 3) to respond
  DRIVER_TOOK_OVER  the driver responded and the vehicle reports MANUAL
  TOR_EXPIRED       nobody responded in time (from here the island's
                    ladder owns the vehicle)

A driver response (/demo/driver/response, std_msgs/Empty) requests MANUAL
from the VEHICLE, /control/control_mode_request
(autoware_vehicle_msgs/srv/ControlModeCommand), which the planning
simulator serves; it is not routed through Autoware's ADAPI, so it works
with the HPC gone.

This node does not tell the island anything. Today the island reacts to the
ODD exit at once (the gate turns availability.autonomous false and
mrm_handler starts the MRM on its next tick); the 10 s rung in the handler
is unit W7's.
"""
import time

import rclpy
from autoware_adapi_v1_msgs.msg import MrmState, OperationModeState
from autoware_vehicle_msgs.msg import ControlModeReport
from autoware_vehicle_msgs.srv import ControlModeCommand
from rclpy.node import Node
from std_msgs.msg import Bool, Empty, Float32, String

from . import common as c

MRM_STATES = {0: 'UNKNOWN', 1: 'NORMAL', 2: 'MRM_OPERATING', 3: 'MRM_SUCCEEDED', 4: 'MRM_FAILED'}
MRM_BEHAVIORS = {0: 'UNKNOWN', 1: 'NONE', 2: 'EMERGENCY_STOP', 3: 'COMFORTABLE_STOP', 4: 'PULL_OVER'}


class TakeoverHmi(Node):
    def __init__(self):
        super().__init__('takeover_hmi')
        self.window = self.declare_parameter('takeover_request_timeout', 10.0).value
        rate = self.declare_parameter('rate_hz', 10.0).value
        self.state = 'NOT_ENGAGED'
        self.tor_t0 = None
        self.odd_exit = False
        self.op_mode = None
        self.ctrl_mode = None
        self.mrm = None
        self.pending = None
        self.pub_state = self.create_publisher(String, c.TAKEOVER_STATE, c.qos_volatile())
        self.pub_left = self.create_publisher(Float32, c.TAKEOVER_REMAINING, c.qos_volatile())
        self.create_subscription(Bool, c.ODD_EXIT, self.on_odd, c.qos_volatile())
        self.create_subscription(OperationModeState, c.OPERATION_MODE_STATE, self.on_op, c.qos_latched())
        self.create_subscription(ControlModeReport, c.CONTROL_MODE, self.on_ctrl, c.qos_volatile())
        self.create_subscription(MrmState, c.MRM_STATE, self.on_mrm, c.qos_volatile())
        self.create_subscription(Empty, c.DRIVER_RESPONSE, self.on_response, c.qos_volatile())
        self.cli = self.create_client(ControlModeCommand, c.CONTROL_MODE_REQUEST)
        self.create_timer(1.0 / rate, self.on_timer)

    def set_state(self, s, note=''):
        if s != self.state:
            self.get_logger().warn(f'{self.state} -> {s}{" (" + note + ")" if note else ""} {c.stamp()}')
            self.state = s

    def engaged(self):
        return (self.op_mode == OperationModeState.AUTONOMOUS
                and self.ctrl_mode == ControlModeReport.AUTONOMOUS)

    def on_odd(self, m):
        self.odd_exit = m.data

    def on_op(self, m):
        self.op_mode = m.mode

    def on_ctrl(self, m):
        self.ctrl_mode = m.mode

    def on_mrm(self, m):
        prev = self.mrm
        self.mrm = (m.state, m.behavior)
        if prev != self.mrm:
            self.get_logger().info(
                f'island mrm_state {MRM_STATES.get(m.state, m.state)}/'
                f'{MRM_BEHAVIORS.get(m.behavior, m.behavior)} {c.stamp()}')

    def on_response(self, _m):
        self.get_logger().warn(f'driver response in state {self.state} {c.stamp()}')
        if not self.cli.service_is_ready():
            self.get_logger().error(f'{c.CONTROL_MODE_REQUEST} is not available')
            return
        req = ControlModeCommand.Request()
        req.stamp = self.get_clock().now().to_msg()
        req.mode = ControlModeCommand.Request.MANUAL
        self.pending = self.cli.call_async(req)
        self.pending.add_done_callback(
            lambda f: self.get_logger().info(
                f'control_mode_request MANUAL -> success={f.result().success if f.result() else None} {c.stamp()}'))

    def on_timer(self):
        left = 0.0
        manual = self.ctrl_mode == ControlModeReport.MANUAL
        if self.state == 'TOR_ACTIVE':
            left = max(0.0, self.window - (time.monotonic() - self.tor_t0))
            if manual:
                self.set_state('DRIVER_TOOK_OVER', f'{self.window - left:.2f} s into the window')
            elif left <= 0.0:
                self.set_state('TOR_EXPIRED', 'no driver response')
        elif self.state in ('DRIVER_TOOK_OVER', 'TOR_EXPIRED'):
            if not self.odd_exit and self.engaged():
                self.set_state('AUTOPILOT', 'ODD re-entered and re-engaged')
            elif not self.odd_exit and not self.engaged() and self.state == 'TOR_EXPIRED':
                self.set_state('NOT_ENGAGED', 'ODD exit cleared')
        elif self.engaged():
            if self.odd_exit:
                self.tor_t0 = time.monotonic()
                left = self.window
                self.set_state('TOR_ACTIVE', f'ODD exit, {self.window:.0f} s to take over')
            else:
                self.set_state('AUTOPILOT')
        else:
            self.set_state('DRIVER_TOOK_OVER' if manual and self.state == 'TOR_ACTIVE' else 'NOT_ENGAGED')
        self.pub_state.publish(String(data=self.state))
        self.pub_left.publish(Float32(data=float(left)))


def main():
    rclpy.init()
    node = TakeoverHmi()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
