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
# `<stem>.launch.xml` beside it. Only src/ is searched. Exit 0 when every
# verdict matches its expectation.
#
# Every contract here is the island's own, under src/. The evaluation's
# contracts (the L3 demo composition, the L4 design stages, the island
# variants) and their expected verdicts moved to NEWSLabNTU/rtss-work-2026-demo
# in phase 14 P2, which checks them against this repo as a submodule.
set -u
cd "$(dirname "$0")/.."
PL="${PLAY_LAUNCH:-play_launch}"

# Expected verdict per contract stem, as "<exit>:<rule id>"; anything not
# listed must pass (0). An exit-1 row passes only when the output names its
# rule as `error[<rule>]`: a contract can exit 1 for another reason, and a
# play_launch too old to parse it exits 1 with `error[manifest-parse]`, which
# is never an expected verdict (phase9-W22: comparing exit codes alone passed
# such a run). A rule ending in `!` must be the ONLY error the output names
# (phase10-B5).
# CORE: the island's own contract passes (no entry); nothing core is
# expected to fail. Kept as its own table so a core variant has a place.
declare -A EXPECT_CORE=(
)

contracts() {
    find ./src -name '*.contract.yaml' -print
}

echo "play_launch: $(command -v "$PL") ($("$PL" --version 2>/dev/null)); contracts: core"
fail=0 n=0
while read -r c; do
    [ -n "$c" ] || continue
    stem="${c%.contract.yaml}"; stem="${stem#./}"
    launch="$stem.launch.xml"
    spec="${EXPECT_CORE[$stem]:-0}"
    want="${spec%%:*}" rule=""
    [ "$spec" != "$want" ] && rule="${spec#*:}"
    only=0; [ "${rule%!}" != "$rule" ] && { only=1; rule="${rule%!}"; }
    n=$((n + 1))
    if [ ! -f "$launch" ]; then
        echo "FAIL $stem: no $launch beside the contract"; fail=1; continue
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
        echo "ok   $stem (exit $got${rule:+, error[$rule]}) $summary"
    else
        echo "FAIL $stem: $why $summary"
        printf '%s\n' "$out" | grep -E 'error\[|warning\[' | head -20 | sed 's/^/     /'
        fail=1
    fi
done < <(contracts | sort)
[ "$n" -gt 0 ] || { echo "no contract found under src/"; fail=1; }
echo "$n contract(s) checked; $([ $fail = 0 ] && echo 'every verdict as expected' || echo 'VERDICT MISMATCH')"
exit $fail
