#!/usr/bin/env bash
# Source me: a Zephyr build environment, resolved from the nros store.
#
#   source scripts/board-env.sh <nano-ros-root> [<zephyr-line>]
#
# <zephyr-line> is 4.4 (default: the MR-CANHUBK344 board) or 3.7 (the LTS line
# the native_sim island runs on). Exports ZEPHYR_BASE (through the workspace's
# own zephyr/zephyr-env.sh), ZEPHYR_SDK_INSTALL_DIR and ZEPHYR_TOOLCHAIN_VARIANT,
# puts the workspace's py3.12 venv first on PATH when the line has one (4.4 needs
# python >= 3.12 for find_package(Python3)), and sets ISLAND_ZEPHYR_WS.
#
# Every path here is ASKED, never constructed:
#
#   workspace  nano-ros's one resolver, scripts/lib/zephyr-workspace.sh
#              (RFC-0095 D4): $NROS_ZEPHYR_WORKSPACE, then the store
#              ($NROS_STORE/workspaces/zephyr/<line>), then the checkout arm.
#   SDK        the version the Zephyr tree itself states (zephyr/SDK_VERSION),
#              mapped to its nros-sdk-index.toml entry by scripts/zephyr-sdk-tool.sh,
#              and located with `nros sdk-path --require`.
#
# The workspace's generated env.sh is deliberately NOT sourced. It names the SDK
# by the path setup.sh installed it at, which is inside whichever nano-ros
# checkout ran the setup (nano-ros issue 1254) -- this island's board builds
# compiled with a sibling clone's SDK for weeks because of it, and nothing said so.

_island_zephyr_env() {
    local root="${1:?usage: source scripts/board-env.sh <nano-ros-root> [<zephyr-line>]}"
    local line="${2:-4.4}"
    local nros="$root/packages/cli/target/release/nros"
    local index="$root/nros-sdk-index.toml"
    local lib="$root/scripts/lib/zephyr-workspace.sh"
    local here ws tool sdk_ver prefix sdk
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # The pinned checkout's own CLI: a released or sibling `nros` emits codegen
    # for a different runtime (RFC-0090), and ~/.nros/bin is not that binary.
    if [ ! -x "$nros" ]; then
        echo "board-env: no nros CLI at $nros" >&2
        echo "board-env:   build it: (cd $root && just setup-cli)" >&2
        return 1
    fi

    ws="${NROS_ZEPHYR_WORKSPACE:-$("$lib" --version "$line" resolve)}"
    if [ -z "$ws" ] || [ ! -d "$ws/zephyr" ]; then
        echo "board-env: no Zephyr $line workspace (default: $("$lib" --version "$line" default))" >&2
        [ "$line" = 4.4 ] && echo "board-env:   provision it: just board-setup" >&2
        [ "$line" = 3.7 ] && echo "board-env:   provision it: just zephyr-setup" >&2
        return 1
    fi

    # Which index entry: the one whose version the Zephyr tree asks for.
    read -r tool sdk_ver < <("$here/zephyr-sdk-tool.sh" "$root" "$ws") || true
    [ -n "${tool:-}" ] || return 1
    if ! prefix="$("$nros" sdk-path "$tool" --require --index "$index" 2>/dev/null)"; then
        echo "board-env: Zephyr SDK $sdk_ver ($tool) is not in the store" >&2
        echo "board-env:   provision it: just board-setup / just zephyr-setup" >&2
        return 1
    fi
    # The tarball carries a top-level zephyr-sdk-<ver>/ and is unpacked without
    # --strip-components, so the SDK root sits one level below the store
    # prefix. `nros sdk-path` has returned BOTH levels across pins: at
    # f0d191c98 it gave the store prefix and this script appended the
    # directory, and by 5e09e377a it returns the SDK root itself, which turned
    # the append into `.../zephyr-sdk-1.0.1/zephyr-sdk-1.0.1` and reported a
    # provisioned SDK as "unpacked but its installer never ran".
    #
    # Accept either shape rather than pick a side. Which one `sdk-path` OUGHT
    # to return is nano-ros's call, and a consumer that survives both does not
    # have to be right about it to keep working.
    sdk="$prefix/zephyr-sdk-$sdk_ver"
    if [ "$(basename "$prefix")" = "zephyr-sdk-$sdk_ver" ]; then
        sdk="$prefix"
    fi
    # `nros setup --tool` unpacks the bundle; the SDK's own installer fetches the
    # toolchains. 0.16.x keeps them at the top level, 1.x under gnu/.
    if ! compgen -G "$sdk/*-zephyr-*" >/dev/null && ! compgen -G "$sdk/gnu/*-zephyr-*" >/dev/null; then
        echo "board-env: $sdk is unpacked but its installer never ran (no toolchains)" >&2
        echo "board-env:   provision it: just board-setup / just zephyr-setup" >&2
        return 1
    fi

    # shellcheck disable=SC1091
    source "$ws/zephyr/zephyr-env.sh"
    export ZEPHYR_SDK_INSTALL_DIR="$sdk"
    export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
    # The pinned checkout's CLI, first on PATH. nano-ros's Zephyr cmake calls
    # `nros` by name -- board facts, codegen, and `nros sdk-path` to find the
    # store's Cyclone idlc -- and a configure outside direnv found none of them
    # ("no nros CLI", then "host Cyclone idlc not found"). Never ~/.nros/bin:
    # a stale copy there shadows the in-tree CLI (packages/cli/CLAUDE.md).
    export PATH="$root/packages/cli/target/release:$PATH"
    if [ -d "$ws/.venv312/bin" ]; then
        export PATH="$ws/.venv312/bin:$PATH"
    fi
    export ISLAND_ZEPHYR_WS="$ws"
}

_island_zephyr_env "$@"
