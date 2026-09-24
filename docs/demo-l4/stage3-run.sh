#!/usr/bin/env bash
# Stage 3. Two runs of the mapper section 9.1 names, over section 9.1's own
# node set, rates and criticality tiers.
#
#   RUN A  stage3-partitions  section 2.2's five criticality tiers written out
#                             as `criticality:` labels, one per node.
#   RUN B  stage3-derived     no labels at all: criticality DERIVED from the
#                             design's own ASIL_D `hpc_loss` hazard, which is
#                             what the checker does whenever a contract
#                             declares one - and stage 1 declares exactly it.
#
# This unit produces a VERDICT, not a slide. Read stage3-verdict.md.
#
# No build is needed. `check --sched --explain` reads the launch file, the
# contract sidecar and the platform file beside it.
# `set -u` comes AFTER the ROS setup script, which reads unbound variables.
CHECK=${CHECK:-/home/aeon/repos/play_launch/install/play_launch/lib/play_launch/play_launch}
HERE=$(cd "$(dirname "$0")" && pwd)

source /opt/ros/humble/setup.bash
set -u

for stem in stage3-partitions stage3-derived; do
  echo
  echo "=== $stem ==="
  "$CHECK" check "$HERE/$stem.launch.xml" \
      --sched "$HERE/$stem.system.posix.yaml" --explain
done
