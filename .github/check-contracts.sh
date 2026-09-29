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
    # phase8-W6's one-line variants of the takeover contract: each must
    # fail its comfortable-stop rung and nothing else (demo/l3/contracts/
    # README.md). The base contract and the island's own contract pass
    # since play_launch 0.13.0 (phases 82-84: the service-edge walk, the
    # takeover keys, window-expiry).
    [demo/l3/contracts/l3_takeover_window20]=1 # ladder-rung-budget 30828.67 ms
    [demo/l3/contracts/l3_takeover_65kmh]=1    # ladder-rung-budget 30558.67 ms
)

echo "play_launch: $(command -v "$PL") ($("$PL" --version 2>/dev/null))"
fail=0 n=0
while IFS= read -r c; do
    stem="${c%.contract.yaml}"; stem="${stem#./}"
    launch="$stem.launch.xml"
    want="${EXPECT[$stem]:-0}"
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
