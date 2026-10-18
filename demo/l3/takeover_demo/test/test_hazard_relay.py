"""hazard_relay.system_command: the selector's system input (phase9-W9).

Run: python3 -m pytest demo/l3/takeover_demo/test/test_hazard_relay.py with
ROS and Autoware sourced (it imports rclpy and autoware_vehicle_msgs).
The whole chain, with the real selector and gate: hazard_chain_replay.py.
"""
import pathlib
import sys

import pytest

PKG = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

msgs = pytest.importorskip('autoware_vehicle_msgs.msg')
from takeover_demo.hazard_relay import system_command  # noqa: E402

E = msgs.HazardLightsCommand.ENABLE
D = msgs.HazardLightsCommand.DISABLE
N = msgs.HazardLightsCommand.NO_COMMAND


@pytest.mark.parametrize('island, age, want', [
    (N, 0.05, D),      # normal: the island sends NO_COMMAND
    (E, 0.05, E),      # takeover request, comfortable stop, emergency stop
    (D, 0.05, D),
    (E, 1.5, D),       # the island fell silent after an ENABLE
    (None, None, D),   # nothing heard yet
])
def test_system_command(island, age, want):
    assert system_command(island, age, 1.0) == want


def test_no_mrm_state_needed():
    """The island decides when the lights are on; the relay only forwards,
    so the same ENABLE yields ENABLE whatever the MRM state is."""
    assert system_command(E, 0.0, 1.0) == E
