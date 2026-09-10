#!/usr/bin/env bash
# Print the nros-sdk-index.toml entry for the Zephyr SDK a workspace asks for.
#
#   scripts/zephyr-sdk-tool.sh <nano-ros-root> <zephyr-workspace>
#
# prints `<tool> <version>`, e.g. `zephyr-sdk-1-0-1 1.0.1`.
#
# The SDK is a per-LINE fact the Zephyr tree states in zephyr/SDK_VERSION, and
# FindZephyr-sdk.cmake refuses anything older. The index does not name its
# entries by one rule (0.16.8 is `zephyr-sdk`, 1.0.1 is `zephyr-sdk-1-0-1`), so
# this finds the entry whose VERSION matches rather than composing a name.
set -euo pipefail

root="${1:?usage: zephyr-sdk-tool.sh <nano-ros-root> <zephyr-workspace>}"
ws="${2:?usage: zephyr-sdk-tool.sh <nano-ros-root> <zephyr-workspace>}"
nros="$root/packages/cli/target/release/nros"
index="$root/nros-sdk-index.toml"

if [ ! -f "$ws/zephyr/SDK_VERSION" ]; then
    echo "zephyr-sdk-tool: $ws/zephyr/SDK_VERSION missing -- not a Zephyr workspace" >&2
    exit 1
fi
ver="$(tr -d '[:space:]' < "$ws/zephyr/SDK_VERSION")"
tool="$("$nros" setup --list --index "$index" \
    | awk -v v="$ver" '$1 == "[tool]" && $2 ~ /^zephyr-sdk/ && $3 == v { print $2; exit }')"
if [ -z "$tool" ]; then
    echo "zephyr-sdk-tool: $ws/zephyr/SDK_VERSION asks for Zephyr SDK $ver," >&2
    echo "zephyr-sdk-tool:   and $index pins no zephyr-sdk entry at that version" >&2
    exit 1
fi
printf '%s %s\n' "$tool" "$ver"
