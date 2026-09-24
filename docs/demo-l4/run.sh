#!/usr/bin/env bash
# The whole demo. Each stage is two runs with one changed number between them.
#
# STAGE 0, the interface declared -- design section 8.
#
#   RUN A  stage0-interface         the 11 inbound rows of section 8.1 and the
#                                   9 outbound rows of section 8.2, as declared.
#   RUN B  stage0-interface-broken  the same file with section 8.1's heartbeat
#                                   row at 10 Hz instead of 100, while the
#                                   consumer still asks for the 100 the table
#                                   promises it. `rate-hierarchy`, exit 1.
#
# STAGE 1, the budget -- design section 9.2.
#
#   RUN A  l4_designed  the production interface of design section 9.2:
#                       30 ms heartbeat detection, 70 ms FTTI.
#   RUN B  l4_current   the evaluation island that exists today:
#                       the same contract with a 500 ms watchdog instead.
#
# STAGE 2, the degradation ladder -- design section 3.
#
#   RUN A  stage2-ladder      B1 to B4 as modes with a fallback ladder, on
#                             section 3.1's own T_ack 2 s, T_odd 10 s and
#                             T_refuge 5 s. Checks clean.
#   RUN B  stage2-noFloor     the same file with B4 given a requirement, so
#                             the floor can be blocked by the very fault the
#                             ladder exists to survive. `ladder-unterminated`,
#                             exit 1. The budget line is unchanged: what fails
#                             is the argument, not the arithmetic.
#   RUN C  stage2-rungBudget  the same file with B1's compliance deadline at
#                             the 10 s of its MRM-request rung instead of the
#                             3 s of its restrict rung -- both section 3.1's,
#                             from one table row. `ladder-rung-budget`, exit 1.
#
# No build is needed. `check` reads the launch file and its contract sidecar.
CHECK=${CHECK:-/home/aeon/repos/play_launch/install/play_launch/lib/play_launch/play_launch}
HERE=$(cd "$(dirname "$0")" && pwd)

# ROS 2's setup.bash reads variables it has not set, so `set -u` goes on
# after it rather than before: with the two in the other order this script
# exits on its own first line.
source /opt/ros/humble/setup.bash
set -u

echo "########## STAGE 0 - the interface, declared ##########"
echo
echo "=== the one number that differs ==="
diff "$HERE/stage0-interface.contract.yaml" \
     "$HERE/stage0-interface-broken.contract.yaml" | tail -4

for stem in stage0-interface stage0-interface-broken; do
  echo
  echo "=== $stem ==="
  "$CHECK" check "$HERE/$stem.launch.xml"
done

echo
echo "########## STAGE 1 - the fault-reaction budget ##########"
echo
echo "=== the one line that differs ==="
diff "$HERE/l4_designed.contract.yaml" "$HERE/l4_current.contract.yaml" | tail -4

for stem in l4_designed l4_current; do
  echo
  echo "=== $stem ==="
  "$CHECK" check "$HERE/$stem.launch.xml"
done

echo
echo "########## STAGE 2 - the degradation ladder ##########"
echo
echo "=== the one line that gives B4 a precondition ==="
diff "$HERE/stage2-ladder.contract.yaml" "$HERE/stage2-noFloor.contract.yaml" | tail -4
echo
echo "=== the one line that holds B1 to its MRM-request deadline ==="
diff "$HERE/stage2-ladder.contract.yaml" "$HERE/stage2-rungBudget.contract.yaml" | tail -4

for stem in stage2-ladder stage2-noFloor stage2-rungBudget; do
  echo
  echo "=== $stem ==="
  "$CHECK" check "$HERE/$stem.launch.xml"
done
