"""Topic names and small helpers shared by the takeover_demo nodes.

Every name here is also written in launch/takeover.contract.yaml; the
contract is what `play_launch check` reads, this module is what the nodes use.
"""
import time

from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

# Autoware <-> gate <-> island
AVAILABILITY_RAW = '/system/operation_mode/availability_raw'   # converter_node, renamed by the overlay
AVAILABILITY = '/system/operation_mode/availability'           # the island reads this one
KINEMATIC_STATE = '/localization/kinematic_state'
CONTROL_MODE = '/vehicle/status/control_mode'
CONTROL_MODE_REQUEST = '/control/control_mode_request'         # simple_planning_simulator's service
OPERATION_MODE_STATE = '/api/operation_mode/state'
MRM_STATE = '/system/fail_safe/mrm_state'
EMERGENCY_HAZARD = '/system/emergency/hazard_lights_cmd'       # the island's mrm_handler output
SYSTEM_HAZARD = '/system/hazard_lights_cmd'                    # hazard_lights_selector's system input

# the demo's own
ODD_EXIT = '/demo/odd/exit'
ODD_REASON = '/demo/odd/reason'
ODD_INJECT = '/demo/odd/inject'
TAKEOVER_STATE = '/demo/takeover/state'
TAKEOVER_REMAINING = '/demo/takeover/remaining'
DRIVER_RESPONSE = '/demo/driver/response'
GRAPH_EVENT = '/demo/graph/event'

# The island's nodes, as `ros2 node list` shows them (root namespace).
# Three since phase8-W8a: stop_mode_operator left the image (decision D4).
ISLAND_NODES = (
    '/mrm_handler',
    '/mrm_comfortable_stop_operator',
    '/mrm_emergency_stop_operator',
)


def qos_volatile(depth=1):
    return QoSProfile(depth=depth, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.VOLATILE)


def qos_latched(depth=1):
    return QoSProfile(depth=depth, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)


def stamp():
    """Wall time and CLOCK_MONOTONIC, the pair the phase-8 timeline aligns on."""
    return f'wall={time.time():.3f} mono={time.monotonic():.3f}'
