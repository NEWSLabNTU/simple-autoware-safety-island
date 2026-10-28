#!/usr/bin/env bash
# `play_launch check` on every contract in the repository (phase8-W3), each
# against the verdict it is MEANT to give. Run by .github/workflows/check.yml;
# runs the same way locally:
#
#   just contract-check                   # the pinned wheel, in build/l3-ci
#   PLAY_LAUNCH=/path/to/play_launch .github/check-contracts.sh
#
# The expectations below are the PINNED release's verdicts (check.yml,
# PLAY_LAUNCH_VERSION). A source-built play_launch that calls itself the same
# version can disagree (the island contract, below), so run it with the pin.
#
# A contract is `<stem>.contract.yaml`, the provider sidecar of
# `<stem>.launch.xml` beside it. Build trees, third-party and experiments are
# not searched. Exit 0 when every verdict matches its expectation.
#
# Two lists (phase14-P1.4). CORE is the island's own: every contract under
# src/. EVALUATION is everything else (demo/l3, docs/demo-l4,
# docs/island-variants), which leaves with the evaluation in phase 14 P2;
# a list whose paths are gone checks nothing and passes. CONTRACTS=core,
# CONTRACTS=evaluation or CONTRACTS=all (the default) picks them.
set -u
cd "$(dirname "$0")/.."
PL="${PLAY_LAUNCH:-play_launch}"
SCOPE="${CONTRACTS:-all}"
case "$SCOPE" in core|evaluation|all) ;; *) echo "CONTRACTS must be core, evaluation or all, not '$SCOPE'" >&2; exit 2;; esac

# Expected verdict per contract stem, as "<exit>:<rule id>"; anything not
# listed must pass (0). An exit-1 row passes only when the output names its
# rule as `error[<rule>]`: a contract can exit 1 for another reason, and a
# play_launch too old to parse it exits 1 with `error[manifest-parse]`, which
# is never an expected verdict (phase9-W22, DX 2.4). A rule ending in `!`
# must be the ONLY error the output names (phase10-B5).
# CORE: the island's own contract passes (no entry); nothing core is
# expected to fail. Kept as its own table so a core variant has a place.
declare -A EXPECT_CORE=(
)
# EVALUATION
declare -A EXPECT_EVAL=(
    # docs/demo-l4/run.sh: each "B" run is a one-number change that the
    # checker must REJECT. A pass here would be the regression.
    [docs/demo-l4/stage0-interface-broken]=1:rate-hierarchy
    [docs/demo-l4/l4_current]=1:fault-reaction-budget       # 500 ms watchdog
    [docs/demo-l4/stage2-noFloor]=1:ladder-unterminated
    [docs/demo-l4/stage2-rungBudget]=1:ladder-rung-budget
    # phase8-W6's one-line variants of the takeover contract: each must
    # fail its comfortable-stop rung and nothing else (demo/l3/contracts/
    # README.md). The base contract and the island's own contract pass
    # since play_launch 0.13.0 (phases 82-84: the service-edge walk, the
    # takeover keys, window-expiry).
    [demo/l3/contracts/l3_takeover_window20]=1:ladder-rung-budget   # 30776.67 ms
    [demo/l3/contracts/l3_takeover_65kmh]=1:ladder-rung-budget      # 30506.67 ms
    # phase10-B5: the same two one-line variants of the island's OWN
    # contract (docs/island-variants/), whose detection (100 ms) and
    # comfortable-stop route (149 ms) are the island's, not the composed
    # demo's; the 20 s one raises takeover_request_timeout with it, so the
    # comfortable-stop rung is the only error.
    [docs/island-variants/safety_island_window20]=1:ladder-rung-budget!  # 31393.67 ms
    [docs/island-variants/safety_island_65kmh]=1:ladder-rung-budget!     # 31123.67 ms
)

# The contracts of one list: core is ./src, evaluation everything else.
contracts() {
    case "$1" in
        core) [ -d src ] && find ./src -name '*.contract.yaml' -print ;;
        evaluation) find . \( -path ./third-party -o -path './build*' -o -path ./experiments \
                          -o -path ./play_log -o -path ./.git -o -path ./src \) -prune \
                      -o -name '*.contract.yaml' -print ;;
    esac
}

echo "play_launch: $(command -v "$PL") ($("$PL" --version 2>/dev/null)); contracts: $SCOPE"
fail=0 n=0
while IFS=' ' read -r list c; do
    [ -n "$c" ] || continue
    stem="${c%.contract.yaml}"; stem="${stem#./}"
    launch="$stem.launch.xml"
    if [ "$list" = core ]; then spec="${EXPECT_CORE[$stem]:-0}"; else spec="${EXPECT_EVAL[$stem]:-0}"; fi
    want="${spec%%:*}" rule=""
    [ "$spec" != "$want" ] && rule="${spec#*:}"
    only=0; [ "${rule%!}" != "$rule" ] && { only=1; rule="${rule%!}"; }
    n=$((n + 1))
    if [ ! -f "$launch" ]; then
        echo "FAIL [$list] $stem: no $launch beside the contract"; fail=1; continue
    fi
    out="$(timeout 120 "$PL" check "$launch" 2>&1)"; got=$?
    out="$(printf '%s\n' "$out" | sed 's/\x1b\[[0-9;]*m//g')"
    summary="$(printf '%s\n' "$out" | grep -E 'manifest\(s\) checked' | tail -1)"
    why=""
    if printf '%s\n' "$out" | grep -qF 'error[manifest-parse]'; then
        why="the contract did not parse (error[manifest-parse]): play_launch too old for its grammar?"
    elif [ "$got" != "$want" ]; then
        why="exit $got, expected $want"
    elif [ -n "$rule" ] && ! printf '%s\n' "$out" | grep -qF "error[$rule]"; then
        why="exit $got as expected, but no error[$rule] in the output"
    elif [ "$only" = 1 ]; then
        others="$(printf '%s\n' "$out" | grep -oE 'error\[[a-z0-9-]+\]' | sort -u | grep -vxF "error[$rule]" | paste -sd' ' -)"
        [ -z "$others" ] || why="error[$rule] as expected, but also $others"
    fi
    if [ -z "$why" ]; then
        echo "ok   [$list] $stem (exit $got${rule:+, error[$rule]}) $summary"
    else
        echo "FAIL [$list] $stem: $why $summary"
        printf '%s\n' "$out" | grep -E 'error\[|warning\[' | head -20 | sed 's/^/     /'
        fail=1
    fi
done < <(for l in core evaluation; do
             [ "$SCOPE" = all ] || [ "$SCOPE" = "$l" ] || continue
             contracts "$l" | sort | sed "s|^|$l |"
         done)
echo "$n contract(s) checked; $([ $fail = 0 ] && echo 'every verdict as expected' || echo 'VERDICT MISMATCH')"
exit $fail
