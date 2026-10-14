#!/usr/bin/env python3
"""Tell the act daemon that the scenario reached its trigger (CARLA demo C4).

  act_trigger.py <socket> <command>       e.g. act_trigger.py build/timeline/<id>/act.sock hpc-loss

SSv2 runs an OpenSCENARIO CustomCommandAction whose `type` it does not know
as a command line (openscenario_interpreter ForkExecCommand): it forks,
execs and waitpid()s, with the scenario's world stopped meanwhile. So this
returns at once: one datagram to the act daemon's unix socket
(tools/timeline/scenario.py, SCENARIO_ACT_SOCKET), no reply awaited, the
standard library only (python3 -I, no ROS). The daemon presses the button
and stamps the press; this process stamps nothing.

The scenario names it through the environment, so the .xosc carries no
path of this checkout:

  <CustomCommandAction type="$(env SAI_ACT_TRIGGER true) hpc-loss"/>

run-board.sh --sim carla exports SAI_ACT_TRIGGER="python3 -I <this file>
<run dir>/act.sock"; without it the action runs `true hpc-loss`, which does
nothing. Exit 0 always (SSv2 ignores the status); a failure is one line on
stderr, which lands in the scenario's log.
"""
import socket
import sys


def main():
    if len(sys.argv) != 3:
        print("act_trigger: usage: act_trigger.py <socket> <command>", file=sys.stderr)
        return 0
    path, cmd = sys.argv[1], sys.argv[2]
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        s.sendto(cmd.encode(), path)
        print(f"act_trigger: sent {cmd} to {path}", file=sys.stderr)
    except OSError as e:
        print(f"act_trigger: {cmd} not delivered to {path}: {e}", file=sys.stderr)
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
