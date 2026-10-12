#!/usr/bin/env bash
# phase9-U4: is the nano-ros this checkout builds with the one it pins, and
# were its two host tools built from it? Called by `just doctor`; prints one
# line per finding with the exact command that fixes it, exits 1 on any
# FAIL (WARNINGs alone exit 0).
#
#   scripts/check-nros-fresh.sh [<nros root>]   (default: third-party/nano-ros)
#
# What it checks, in the order a fix has to happen:
#   1. third-party/nano-ros is at the commit this repo records (`git submodule
#      status`: a leading `+` is another commit, `-` not checked out)
#   2. nano-ros's nested submodules the island's build reads are at the
#      commits nano-ros records: packages/cli/third-party/play_launch (the
#      launch resolver and the CLI's play_launch pin) and
#      packages/rmw/zenoh/zpico-sys/zenoh-pico (the board's zenoh-pico).
#      `git submodule update` without --recursive moves nano-ros and leaves
#      these behind; `just setup-launch-resolve` then dies on --locked.
#   3. the nros CLI the island resolves is <root>/packages/cli/target/release/nros
#      (the root is this checkout's submodule unless the justfile override
#      NANO_ROS_ALLOW_EXTERNAL_ROOT=1 names another; after sourcing the root's
#      activate.sh, as `just sync` does, `command -v nros` must be that file),
#      and it was built from the sources now checked out. nros reports no build
#      commit (`nros --version` says `nros 0.5.0`); it embeds a content stamp
#      of its own sources and of the play_launch pin at build time, and
#      `nros source-stamp` recomputes it against its tree (nano-ros issue
#      0363). Same sources = same build inputs, which is what "built from the
#      pin" has to mean once 1. and 2. hold.
#   4. nros-launch-resolve likewise, through nano-ros's own predicate
#      (scripts/check-launch-resolve-fresh.sh: the stamp setup-launch-resolve
#      writes beside the binary, over the resolver sources and the play_launch
#      pin).
# A modified tracked file in nano-ros or the two nested trees is a WARNING:
# `just board-build-diag` applies its patches there and reverts them; a tree
# still carrying them builds a diag image under the normal recipe.
set -u
# ISLAND_ROOT: another island checkout to inspect (read-only), default this one
cd "${ISLAND_ROOT:-$(dirname "$0")/..}" || exit 2
isl="$PWD"
root="${1:-$isl/third-party/nano-ros}"
sub="$isl/third-party/nano-ros"
NESTED="packages/cli/third-party/play_launch packages/rmw/zenoh/zpico-sys/zenoh-pico"
fail=0
FAIL() { echo "STALE: $*"; fail=1; }
WARN() { echo "  WARNING: $*"; }

rel_root="$root"
case "$root" in "$isl"/*) rel_root="${root#"$isl"/}";; esac

# -- 1. the island's pin --------------------------------------------------
if [ "$(readlink -f "$root")" = "$(readlink -f "$sub")" ]; then
    line="$(git submodule status -- third-party/nano-ros 2>/dev/null)"
    pin="$(git ls-tree HEAD third-party/nano-ros | awk '{print $3}')"
    case "$line" in
        -*) FAIL "third-party/nano-ros is not checked out -- run: git submodule update --init third-party/nano-ros"
            echo "nros-fresh: FAIL"; exit 1;;
        +*) FAIL "third-party/nano-ros is at $(echo "${line:1}" | cut -c1-12), this commit pins ${pin:0:12} -- run: git submodule update third-party/nano-ros";;
        U*) FAIL "third-party/nano-ros has a merge conflict on its pin -- resolve it, then: git submodule update third-party/nano-ros";;
    esac
else
    WARN "nros root is $root, not this checkout's third-party/nano-ros (NANO_ROS_ALLOW_EXTERNAL_ROOT=1); its pin is not checked"
fi

# -- 2. nested submodules -------------------------------------------------
for p in $NESTED; do
    line="$(git -C "$root" submodule status -- "$p" 2>/dev/null)"
    want="$(git -C "$root" ls-tree HEAD "$p" | awk '{print $3}')"
    case "$line" in
        -*) FAIL "$rel_root/$p is not checked out -- run: git -C $rel_root submodule update --init $p";;
        +*) FAIL "$rel_root/$p is at $(echo "${line:1}" | cut -c1-12), nano-ros pins ${want:0:12} -- run: git -C $rel_root submodule update --init $NESTED";;
        U*) FAIL "$rel_root/$p has a merge conflict -- resolve it, then: git -C $rel_root submodule update --init $p";;
        "") FAIL "$rel_root/$p is not a submodule of $root (a nano-ros pin that moved it? update this list)";;
    esac
done
for t in "" $NESTED; do
    d="$root${t:+/$t}"
    [ -e "$d/.git" ] || continue
    mod="$(git -C "$d" status --porcelain --untracked-files=no --ignore-submodules=all 2>/dev/null | awk '{print $2}')"
    [ -n "$mod" ] || continue
    WARN "$rel_root${t:+/$t} has modified tracked files: $(echo $mod | cut -c1-160)"
    if [ -z "$t" ] && git -C "$root" apply -R --check "$isl/experiments/spin-latency/nano-ros-diag.patch" 2>/dev/null; then
        WARN "  that is the spin-diag patch (a killed board-build-diag?) -- run: git -C $rel_root apply -R experiments/spin-latency/nano-ros-diag.patch (path from $isl)"
    fi
done

# -- 3. the nros CLI --------------------------------------------------------
bin="$root/packages/cli/target/release/nros"
fixcli="(cd $rel_root && just setup-cli)"
if [ ! -x "$bin" ]; then
    FAIL "no nros CLI at $rel_root/packages/cli/target/release/nros -- run: $fixcli"
else
    got="$(bash -c 'source "$1/activate.sh" >/dev/null 2>&1; command -v nros' _ "$root")"
    if [ "$(readlink -f "${got:-/nonexistent}")" != "$(readlink -f "$bin")" ]; then
        FAIL "after $rel_root/activate.sh, nros resolves to ${got:-nothing}, not $bin -- remove the shadowing binary or put the checkout first (source $rel_root/activate.sh)"
    fi
    here="$(command -v nros 2>/dev/null || true)"
    if [ -n "$here" ] && [ "$(readlink -f "$here")" != "$(readlink -f "$bin")" ]; then
        WARN "this shell's PATH resolves nros to $here (another checkout's?); the recipes use $bin, an interactive nros does not"
    fi
    if out="$("$bin" source-stamp 2>&1)"; then
        echo "nros CLI: $bin ($out)"
    elif grep -qiE "unrecognized subcommand|unexpected argument" <<<"$out"; then
        FAIL "nros CLI predates the source stamp, so it was built from older sources -- run: $fixcli"
    else
        FAIL "nros CLI was built from other sources than $rel_root now holds -- run: $fixcli"
        sed 's/^/    /' <<<"$out" | head -12
    fi
fi

# -- 4. nros-launch-resolve ----------------------------------------------
lr="${CARGO_TARGET_DIR:-$root/packages/cli/nros-launch-resolve/target}/release/nros-launch-resolve"
fixlr="(cd $rel_root && just setup-launch-resolve)"
lc=""
if [ ! -x "$lr" ]; then
    FAIL "no nros-launch-resolve at $lr -- run: $fixlr"
elif [ ! -f "$root/scripts/check-launch-resolve-fresh.sh" ]; then
    WARN "$rel_root has no scripts/check-launch-resolve-fresh.sh; the resolver is not checked"
elif out="$(cd "$root" && bash scripts/check-launch-resolve-fresh.sh 2>&1)" \
    || { [ "${LC_ALL:-}" != C ] && (cd "$root" && LC_ALL=C bash scripts/check-launch-resolve-fresh.sh >/dev/null 2>&1) && lc=C; } \
    || { (cd "$root" && LC_ALL=C.UTF-8 bash scripts/check-launch-resolve-fresh.sh >/dev/null 2>&1) && lc=C.UTF-8; }; then
    # nano-ros's resolver stamp sorts the file list in the CALLER's locale
    # (launch-resolve-stale.sh: `sort` without LC_ALL), so a stamp written
    # under C.UTF-8 reads STALE under en_US.UTF-8 and back. Collation only
    # reorders the same files: an edit or a pin move misses under every
    # locale, so a match under either is a match.
    echo "nros-launch-resolve: $lr ($("$lr" --version 2>/dev/null | sed 's/^nros-launch-resolve //'), matches its sources${lc:+; the stamp was written under LC_ALL=$lc})"
else
    FAIL "nros-launch-resolve was built from other sources than $rel_root now holds -- run: $fixlr"
    grep -E 'built from|checked out at|PIN|no stamp' <<<"$out" | sed 's/^ */    /' | head -4
fi

if [ "$fail" = 0 ]; then echo "nros-fresh: OK (nano-ros $(git -C "$root" rev-parse --short=12 HEAD), the CLI and the resolver built from it)"
else echo "nros-fresh: FAIL -- fix in the order printed: the pin, the nested submodules, then setup-cli and setup-launch-resolve"; fi
[ "$fail" = 0 ]
