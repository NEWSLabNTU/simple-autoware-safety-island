#!/usr/bin/env bash
# DIAG (spin latency): one board act with the spin diag read just before and
# just after the act, so tools/timeline/actseg.py can count the act segment.
#
#   tools/timeline/run-diag.sh [run-board options] [a|b|encore] <run-id>
#
# The act defaults to encore (the act section 6 of the phase-9 roadmap
# measured). The image must be a diag build (`just board-build-diag`, ELF in
# build-board-diag/zephyr/zephyr.elf, the default --elf here); a plain image
# has no island_spin_diag and spin_diag.py refuses it. Every other option goes
# to run-board.sh as is (--no-flash, --dry-run, ...).
#
# The act is run-board.sh's own default act (RB_ACT), wrapped:
#   spin_diag.py read --out <dir>/spin-diag-pre; scenario.py run <act> ...;
#   spin_diag.py read --out <dir>/spin-diag-act; exit with the act's status
# Both reads attach without halting the core. run-board.sh flashes, runs,
# reads the trace and tears down as for any act; its output goes to
# build/timeline/<id>/run.log, and this prints the run's exit status and the
# act-segment count. Then: tools/timeline/actseg.py <id> [<id>...].
set -u
cd "$(dirname "$0")/../.."
opts=() elf=build-board-diag/zephyr/zephyr.elf
while [ $# -gt 0 ]; do
    case "$1" in
        --elf) elf="$2"; shift 2;;
        --target) opts+=("$1" "$2"); shift 2;;
        -h|--help) sed -n '2,/^set -u/p' "$0" | sed '$d'; exit 0;;
        --*) opts+=("$1"); shift;;
        *) break;;
    esac
done
if [ $# -ge 2 ]; then act="$1"; id="$2"; else act=encore; id="${1:?run id}"; fi
case "$act" in a|b|encore) ;; *) echo "run-diag: act is a, b or encore" >&2; exit 2;; esac
[ -f "$elf" ] || { echo "run-diag: no $elf -- just board-build-diag" >&2; exit 1; }
dir="build/timeline/$id"
sd="python3 tools/timeline/spin_diag.py read --elf $elf"
# run-board.sh's default RB_ACT, with the two reads around it
export RB_ACT="$sd --out $dir/spin-diag-pre; python3 tools/timeline/scenario.py run $act --log $dir/scenario.jsonl; rc=\$?; $sd --out $dir/spin-diag-act; exit \$rc"
mkdir -p "$dir"
echo "run-diag: $act $id, $elf; load at start: $(cat /proc/loadavg)"
tools/timeline/run-board.sh "${opts[@]}" --elf "$elf" "$act" "$id" > "$dir/run.log" 2>&1
rc=$?
echo "run-diag: run-board.sh exit $rc (log $dir/run.log)"
grep -E '^(VERDICT|SUMMARY)' "$dir/run.log" | tail -2
if [ -f "$dir/spin-diag-pre.txt" ] && [ -f "$dir/spin-diag-act.txt" ]; then
    python3 tools/timeline/actseg.py "$dir"
else
    echo "run-diag: no spin-diag-pre/act.txt in $dir (the act did not run, or a read failed: see act.log)"
fi
exit $rc
