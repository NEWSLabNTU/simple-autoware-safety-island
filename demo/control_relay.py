#!/usr/bin/env python3
"""Typed relay for /system/emergency/control_cmd, domain 2 -> domain 1.

Stand-in for the dropped domain_bridge row (nano-ros #267): the island's
Control message decodes CLEANLY through a typed subscriber but corrupts
through domain_bridge's serialized byte-level rebroadcast. This relay does
deserialize -> reserialize, which regularizes the wire representation.
Remove once #267 lands and restore the bridge row.
"""
import os
# Domain 2 ONLY: lo + unicast peers (island side). Domain 1 (the publisher
# into the sim) stays on cyclone defaults — the sim runs on the default
# interface, and a lo-pinned d1 participant is deaf to it on hosts where lo
# lacks the MULTICAST flag.
LO_URI = ('<CycloneDDS><Domain Id="2"><General>'
          '<Interfaces><NetworkInterface name="lo"/></Interfaces>'
          '<AllowMulticast>spdp</AllowMulticast></General>'
          '<Discovery><ParticipantIndex>auto</ParticipantIndex>'
          '<MaxAutoParticipantIndex>60</MaxAutoParticipantIndex>'
          '<Peers><Peer Address="127.0.0.1"/></Peers></Discovery>'
          '</Domain></CycloneDDS>')
os.environ['CYCLONEDDS_URI'] = LO_URI
os.environ['RMW_IMPLEMENTATION'] = 'rmw_cyclonedds_cpp'

import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from autoware_control_msgs.msg import Control

def main():
    ctx2 = Context(); rclpy.init(context=ctx2, domain_id=2)
    ctx1 = Context(); rclpy.init(context=ctx1, domain_id=1)
    n2 = rclpy.create_node('si_control_relay_d2', context=ctx2)
    n1 = rclpy.create_node('si_control_relay_d1', context=ctx1)
    pub = n1.create_publisher(Control, '/system/emergency/control_cmd', 1)
    n2.create_subscription(Control, '/system/emergency/control_cmd',
                           pub.publish, 1)
    ex = SingleThreadedExecutor(context=ctx2); ex.add_node(n2)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
