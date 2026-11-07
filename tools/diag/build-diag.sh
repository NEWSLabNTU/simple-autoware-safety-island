#!/usr/bin/env bash
# DIAG (spin latency): a board image with the spin diagnostic, built into its
# own directory so the normal build-board is untouched.
#
#   tools/diag/build-diag.sh [CONFIG_X=value ...]
#   (just board-build-diag [CONFIG_X=value ...])
#
# 1. applies nano-ros-diag.patch to the nano-ros submodule and
#    zenoh-pico-diag.patch to its zenoh-pico (both must apply cleanly: a tree
#    that already carries them is refused, with the command that reverts it)
# 2. runs `just BOARD_BUILD_DIR=<dir> board-build` with
#    ISLAND_BOARD_KCONFIG="CONFIG_ISLAND_SPIN_DIAG=y
#    CONFIG_NROS_ZENOH_SERIAL_ISR_STATS=y <your CONFIG_X=value ...>" (passed as
#    -D, the tracked board conf is not edited); once more if board-build asks
#    for the second pass (a fresh build dir needs it)
# 3. checks the build compiled the patched trees (compile_commands.json names
#    this checkout's zenoh-pico submodule, not the nros store's copy)
# 4. reverts both patches -- from an EXIT trap, so a failed build, Ctrl-C or
#    a kill short of SIGKILL never leaves the submodules patched
#
# Which zenoh-pico is compiled: nano-ros resolves the tree at configure time
# through `nros locate zenoh-pico` (RFC-0103 D5). A submodule at its pin and
# clean loses to the shared store copy (~/.nros/sources/zenoh-pico/<pin>),
# which is what a normal build-board compiles; a DIRTY submodule (the
# "local-edit" rung) outranks the store. Patching the submodule is therefore
# the per-build override: the store, shared by every checkout, is never
# touched, and west reconfigures on every board-build (the recipe passes
# cmake args), so the ladder is asked again with the patch applied. Step 3
# fails the build if it was not.
#
# <dir> is $BOARD_DIAG_BUILD_DIR, default build-board-diag; the ELF is
# <dir>/zephyr/zephyr.elf, which rtss-work-2026-demo:tools/eval/run-diag.sh flashes by
# default. Do not run a normal `just board-build` in the same checkout while
# this runs: it would compile the patched sources.
set -u
cd "$(dirname "$0")/../.."
repo="$PWD"
E="$repo/tools/diag"
# This checkout's submodule. Not $NROS_REPO_DIR: inherited, it names whatever
# checkout the calling shell sourced (a direnv of another worktree), and
# patching THAT tree is the one thing this must not do. `just
# board-build-diag` passes the root the justfile resolved (its
# NANO_ROS_ALLOW_EXTERNAL_ROOT override included) as ISLAND_NROS_ROOT.
NR="${ISLAND_NROS_ROOT:-$repo/third-party/nano-ros}"
NR="$(readlink -f "$NR")"  # compile_commands.json spells real paths
ZP="$NR/packages/rmw/zenoh/zpico-sys/zenoh-pico"
DIR="${BOARD_DIAG_BUILD_DIR:-build-board-diag}"
[ "$DIR" = build-board ] && { echo "build-diag: BOARD_DIAG_BUILD_DIR must not be build-board" >&2; exit 2; }
for kv in "$@"; do
    case "$kv" in CONFIG_*=*) ;; *) echo "build-diag: '$kv' is not CONFIG_<name>=<value>" >&2; exit 2;; esac
done

applied=()  # "<tree> <patch>", in apply order
revert() {
    local i tree patch rc=0
    for (( i=${#applied[@]}-1; i>=0; i-- )); do
        tree="${applied[$i]%% *}"; patch="${applied[$i]#* }"
        if git -C "$tree" apply -R "$patch"; then
            echo "build-diag: reverted $(basename "$patch")"
        else
            echo "build-diag: FAILED to revert $(basename "$patch") in $tree -- run: git -C $tree apply -R $patch" >&2; rc=1
        fi
    done
    applied=()
    return $rc
}
trap 'revert || exit 1' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

for pair in "$NR $E/nano-ros-diag.patch" "$ZP $E/zenoh-pico-diag.patch"; do
    tree="${pair%% *}"; patch="${pair#* }"
    if ! git -C "$tree" apply --check "$patch" 2>/dev/null; then
        if git -C "$tree" apply -R --check "$patch" 2>/dev/null; then
            echo "build-diag: $tree already carries $(basename "$patch") (a run killed by SIGKILL?)" >&2
            echo "build-diag:   revert it: git -C $tree apply -R $patch" >&2
        else
            echo "build-diag: $(basename "$patch") does not apply to $tree (pin moved? rebase the patch)" >&2
        fi
        exit 1
    fi
    git -C "$tree" apply "$patch" || exit 1
    applied+=("$tree $patch")
    echo "build-diag: applied $(basename "$patch") to $tree"
done

export ISLAND_BOARD_KCONFIG="CONFIG_ISLAND_SPIN_DIAG=y CONFIG_NROS_ZENOH_SERIAL_ISR_STATS=y $*"
log="$DIR.log"
echo "build-diag: just BOARD_BUILD_DIR=$DIR board-build, ISLAND_BOARD_KCONFIG=$ISLAND_BOARD_KCONFIG (log $log)"
for pass in 1 2; do
    just BOARD_BUILD_DIR="$DIR" board-build > "$log" 2>&1; rc=$?
    [ $rc = 0 ] && break
    grep -q 'the second pass converges' "$log" || break
    [ $pass = 1 ] && echo "build-diag: board-build asked for its second pass; running it"
done
grep -E '^\s+(FLASH|RAM|DTCM|ITCM):' "$log" | tail -4
if [ $rc = 0 ]; then
    # A patch that applied to a tree the build did not compile is silently a
    # no-op; refuse that image.
    for src in "$ZP/src/link/transport/serial/uart_zephyr.c" "$NR/zephyr/nros_zenoh_zephyr_system.c"; do
        if ! grep -qF "\"file\": \"$src\"" "$DIR/compile_commands.json" 2>/dev/null; then
            echo "build-diag: $DIR did not compile $src (another tree resolved: see 'nros locate zenoh-pico --why'); the image lacks the hooks" >&2
            rc=1
        fi
    done
fi
if [ $rc = 0 ]; then
    echo "build-diag: OK, $DIR/zephyr/zephyr.elf (sha256 $(sha256sum "$DIR/zephyr/zephyr.elf" | cut -c1-16)...)"
else
    tail -30 "$log"
    echo "build-diag: board-build failed (exit $rc), the full log is $log" >&2
fi
exit $rc
