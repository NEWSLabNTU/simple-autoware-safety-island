#!/usr/bin/env bash
# a stock rmw_zenohd (stand-in for Autoware's router) on PORT, default 7457, stock config
port=${1:-7457}; log=${2:-/dev/null}
exec env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c '
  source /opt/ros/humble/setup.bash
  export ZENOH_CONFIG_OVERRIDE="listen/endpoints=[\"tcp/[::]:'"$port"'\"]"
  export RUST_LOG=zenoh=info
  exec /opt/ros/humble/lib/rmw_zenoh_cpp/rmw_zenohd
' > "$log" 2>&1
