"""graph_watcher: the island joining and leaving the ROS graph, live.

Polls the graph cache every `period_s` (0.1 s) -- rmw_zenoh_cpp fills it
from the liveliness tokens the island declares -- and prints one line per
change for each of the island's nodes, plus the publisher count on
/system/fail_safe/mrm_state (vehicle_cmd_gate's heartbeat):

  JOIN  /mrm_handler                    wall=... mono=...
  LEAVE /mrm_handler                    wall=... mono=...

The same lines go to /demo/graph/event (std_msgs/String) for the timeline.
A long-lived node rather than `watch ros2 node list`: each CLI call creates a
node and waits for discovery, which is slower than the event it looks for.
"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from . import common as c


class GraphWatcher(Node):
    def __init__(self):
        super().__init__('graph_watcher')
        self.watch = list(self.declare_parameter('island_nodes', list(c.ISLAND_NODES)).value)
        period = self.declare_parameter('period_s', 0.1).value
        self.present = set()
        self.mrm_pubs = None
        self.pub = self.create_publisher(String, c.GRAPH_EVENT, c.qos_volatile(depth=10))
        self.create_timer(period, self.on_timer)
        self.get_logger().info(f'watching {", ".join(self.watch)}')

    def emit(self, text):
        line = f'{text:<44} {c.stamp()}'
        print(line, flush=True)
        self.pub.publish(String(data=line))

    def on_timer(self):
        names = {(ns.rstrip('/') + '/' + n) for n, ns in self.get_node_names_and_namespaces()}
        now = {w for w in self.watch if w in names}
        for w in sorted(now - self.present):
            self.emit(f'JOIN  {w}')
        for w in sorted(self.present - now):
            self.emit(f'LEAVE {w}')
        if now != self.present:
            self.emit(f'island nodes present: {len(now)}/{len(self.watch)}')
        self.present = now
        n = self.count_publishers(c.MRM_STATE)
        if n != self.mrm_pubs:
            self.emit(f'publishers on {c.MRM_STATE}: {n}')
            self.mrm_pubs = n


def main():
    rclpy.init()
    node = GraphWatcher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
