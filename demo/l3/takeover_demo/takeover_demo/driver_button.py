"""driver_button: the booth's buttons, on a keyboard.

  SPACE or t   the driver takes over      -> /demo/driver/response (Empty)
  o            ODD exit (the presenter)   -> /demo/odd/inject (Bool true)
  c            clear the ODD exit         -> /demo/odd/inject (Bool false)
  q            quit

Keys are read only when stdin is a terminal (`ros2 run takeover_demo
driver_button` in its own terminal). Under a launch file, where there is no
terminal, the same three actions are services: ~/take_over, ~/odd_exit and
~/odd_clear (std_srvs/Trigger), which is how the scenario script presses
them.
"""
import os
import select
import sys
import termios
import tty

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Empty
from std_srvs.srv import Trigger

from . import common as c


class DriverButton(Node):
    def __init__(self):
        super().__init__('driver_button')
        self.pub_resp = self.create_publisher(Empty, c.DRIVER_RESPONSE, c.qos_volatile())
        self.pub_odd = self.create_publisher(Bool, c.ODD_INJECT, c.qos_volatile())
        self.create_service(Trigger, '~/take_over', lambda q, r: self.act('t', r))
        self.create_service(Trigger, '~/odd_exit', lambda q, r: self.act('o', r))
        self.create_service(Trigger, '~/odd_clear', lambda q, r: self.act('c', r))

    def act(self, key, res=None):
        if key in (' ', 't'):
            self.pub_resp.publish(Empty())
            what = 'TAKE OVER'
        elif key == 'o':
            self.pub_odd.publish(Bool(data=True))
            what = 'ODD EXIT'
        elif key == 'c':
            self.pub_odd.publish(Bool(data=False))
            what = 'ODD CLEAR'
        else:
            return res
        self.get_logger().warn(f'button: {what} {c.stamp()}')
        if res is not None:
            res.success, res.message = True, what
        return res


def main():
    rclpy.init()
    node = DriverButton()
    tty_in = sys.stdin.isatty()
    old = None
    if tty_in:
        old = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        print('driver_button: SPACE/t take over, o ODD exit, c clear, q quit', flush=True)
    else:
        node.get_logger().info('no terminal on stdin: buttons are the ~/take_over, ~/odd_exit, ~/odd_clear services')
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.05)
            if tty_in and select.select([sys.stdin], [], [], 0)[0]:
                k = os.read(sys.stdin.fileno(), 1).decode(errors='ignore').lower()
                if k == 'q':
                    break
                node.act(k)
    except KeyboardInterrupt:
        pass
    finally:
        if old is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
