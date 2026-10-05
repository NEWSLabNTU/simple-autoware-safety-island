#!/usr/bin/env bash
# Regression check for `just demo-down` (phase9-W22, DX 7.3): the orphan sweep
# selects a process by this checkout's SAI_DEMO_RUN in its environment, never
# by CYCLONEDDS_URI. Before eb82dcf the key was CYCLONEDDS_URI, which direnv
# exports into the interactive shell, and the sweep TERMed then KILLed a
# Claude Code session started in this checkout (twice, 2026-09-28).
#
# Starts three `sleep`s and runs the sweep's selection only
# (`just _sweep-orphans dry`, which kills nothing):
#   bystander  CYCLONEDDS_URI set, no SAI_DEMO_RUN       -> must NOT be selected
#   neighbour  SAI_DEMO_RUN=<another checkout's path>     -> must NOT be selected
#   demo       SAI_DEMO_RUN=<this checkout>               -> MUST be selected
# The last one proves the check can fail. Runs in about a second.
#
#   scripts/test-demo-down-spares-bystanders.sh
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null; wait 2>/dev/null; }
trap cleanup EXIT

env -u SAI_DEMO_RUN CYCLONEDDS_URI="file://$root/demo/cyclonedds.xml" sleep 30 &
bystander=$!; pids+=($!)
env SAI_DEMO_RUN="$root-elsewhere" CYCLONEDDS_URI="file://$root/demo/cyclonedds.xml" sleep 30 &
neighbour=$!; pids+=($!)
env SAI_DEMO_RUN="$root" sleep 30 &
demo=$!; pids+=($!)
sleep 0.2   # let the three exec into sleep, so /proc/<pid>/environ is theirs

out="$(just _sweep-orphans dry 2>&1)"
selected() { printf '%s\n' "$out" | grep -q "^select $1 "; }

fail=0
if selected "$bystander"; then echo "FAIL bystander $bystander (CYCLONEDDS_URI, no SAI_DEMO_RUN) selected"; fail=1
else echo "ok   bystander $bystander (CYCLONEDDS_URI, no SAI_DEMO_RUN) spared"; fi
if selected "$neighbour"; then echo "FAIL neighbour $neighbour (another checkout's SAI_DEMO_RUN) selected"; fail=1
else echo "ok   neighbour $neighbour (another checkout's SAI_DEMO_RUN) spared"; fi
if selected "$demo"; then echo "ok   demo $demo (this checkout's SAI_DEMO_RUN) selected"
else echo "FAIL demo $demo (this checkout's SAI_DEMO_RUN) not selected: the check cannot see the sweep"; fail=1; fi
[ "$fail" = 0 ] || printf '%s\n' "$out" | sed 's/^/     /'
echo "demo-down bystander check: $([ "$fail" = 0 ] && echo PASS || echo FAIL)"
exit $fail
