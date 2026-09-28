#!/usr/bin/env bash
# `play_launch check` on every contract in the repository (phase8-W3), each
# against the verdict it is MEANT to give. Run by .github/workflows/check.yml;
# runs the same way locally:
#
#   just l3-check                         # the pinned wheel, in build/l3-ci
#   PLAY_LAUNCH=/path/to/play_launch .github/check-contracts.sh
#
# The expectations below are the PINNED release's verdicts (check.yml,
# PLAY_LAUNCH_VERSION). A source-built play_launch that calls itself the same
# version can disagree (the island contract, below), so run it with the pin.
#
# A contract is `<stem>.contract.yaml`, the provider sidecar of
# `<stem>.launch.xml` beside it. Build trees, third-party and experiments are
# not searched. Exit 0 when every verdict matches its expectation.
set -u
cd "$(dirname "$0")/.."
PL="${PLAY_LAUNCH:-play_launch}"

# Expected exit code per contract stem; anything not listed must pass (0).
declare -A EXPECT=(
    # docs/demo-l4/run.sh: each "B" run is a one-number change that the
    # checker must REJECT. A pass here would be the regression.
    [docs/demo-l4/stage0-interface-broken]=1   # rate-hierarchy
    [docs/demo-l4/l4_current]=1                # fault-reaction-budget (500 ms watchdog)
    [docs/demo-l4/stage2-noFloor]=1            # ladder-unterminated
    [docs/demo-l4/stage2-rungBudget]=1         # ladder-rung-budget
    # The island's own contract needs the reaction walk to cross a SERVICE
    # edge (mrm_handler -> operate -> the operator; play_launch phase 82),
    # which landed after v0.12.0: the published 0.12.0 wheel reports
    # `reaction-unreachable` (exit 1), while the demo host's play_launch,
    # a source-built wheel that also calls itself 0.12.0 (file://.../
    # play_launch/dist, 2026-09-25), passes it. Measured 2026-09-28 in a
    # clean ros:humble container. Since 20:45 the same day the file also
    # carries W6's `entry_speed` key, which 0.12.0 refuses to parse; either
    # way the pinned verdict is exit 1. Flip to 0 with the pin, when the next
    # play_launch release is on the package index.
    [src/safety_island_bringup/launch/safety_island]=1
)

echo "play_launch: $(command -v "$PL") ($("$PL" --version 2>/dev/null))"
fail=0 n=0
while IFS= read -r c; do
    stem="${c%.contract.yaml}"; stem="${stem#./}"
    launch="$stem.launch.xml"
    want="${EXPECT[$stem]:-0}"
    # phase8-W6's demo contracts (and their one-line variants) use the four
    # new keys (when:, window:, exit:, entry_speed/settle:) that the pinned
    # play_launch does not parse ("unknown key in hazards.<name>"). W6 moves
    # PLAY_LAUNCH_VERSION in check.yml, lists each variant's own verdict in
    # EXPECT and deletes this case in the same change.
    case "$stem" in demo/l3/contracts/*) [ -z "${EXPECT[$stem]:-}" ] && want=1;; esac
    n=$((n + 1))
    if [ ! -f "$launch" ]; then
        echo "FAIL $stem: no $launch beside the contract"; fail=1; continue
    fi
    out="$(timeout 120 "$PL" check "$launch" 2>&1)"; got=$?
    summary="$(printf '%s\n' "$out" | sed 's/\x1b\[[0-9;]*m//g' | grep -E 'manifest\(s\) checked' | tail -1)"
    if [ "$got" = "$want" ]; then
        echo "ok   $stem (exit $got, expected $want) $summary"
    else
        echo "FAIL $stem (exit $got, expected $want) $summary"
        printf '%s\n' "$out" | sed 's/\x1b\[[0-9;]*m//g' | grep -E 'error\[|warning\[' | head -20 | sed 's/^/     /'
        fail=1
    fi
done < <(find . \( -path ./third-party -o -path './build*' -o -path ./experiments \
                  -o -path ./play_log -o -path ./.git \) -prune \
              -o -name '*.contract.yaml' -print | sort)
echo "$n contract(s) checked; $([ $fail = 0 ] && echo 'every verdict as expected' || echo 'VERDICT MISMATCH')"
exit $fail
