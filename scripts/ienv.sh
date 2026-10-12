#!/usr/bin/env bash
# Run a command in this checkout under a clean environment: `env -i` with only
# HOME, USER, TERM, LANG, XDG_RUNTIME_DIR and a minimal PATH, then
# scripts/env.sh sourced, so nothing the calling shell carries (a direnv of
# another worktree, the demo's CYCLONEDDS_URI, a sibling NANO_ROS_ROOT, a
# login shell that resolves the demo overlay) reaches the command.
#
#   scripts/ienv.sh '<command>'           e.g. scripts/ienv.sh 'just doctor'
#   ISL=<checkout> scripts/ienv.sh '...'  another checkout (default: this one)
#
# The command string is run by bash -c after `cd` into the checkout.
set -u
[ $# -ge 1 ] || { sed -n '2,/^set -u/p' "$0" | sed '$d'; exit 2; }
isl="${ISL:-$(cd "$(dirname "$0")/.." && pwd)}"
exec env -i HOME="$HOME" USER="$USER" TERM=dumb LANG=C.UTF-8 \
    PATH="$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin" \
    XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" \
    bash -c "cd '$isl' && source scripts/env.sh >/dev/null && $*"
