#!/usr/bin/env bash
# router.sh TTY BAUD PORT LOG [CFG] [CONNECT]  -- board-peer's router without the fuser check (for the socat tap)
tty=$1 baud=$2 port=$3 log=$4
cfg=${5:-/home/aeon/repos/simple-autoware-safety-island/experiments/serial-interop/router-serial.json5}
connect=${6:-}
bin=/home/aeon/repos/simple-autoware-safety-island/build/trace/board-peer-zenohd
ln -sfn /opt/ros/humble/lib/rmw_zenoh_cpp/rmw_zenohd "$bin"
ovr="listen/endpoints=[\"serial/$tty#baudrate=$baud\",\"tcp/[::]:$port\"]"
[ -n "$connect" ] && ovr="$ovr;connect/endpoints=[\"$connect\"]"
env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin bash -c '
    source /opt/ros/humble/setup.bash
    export ROS_DOMAIN_ID=10
    export ZENOH_ROUTER_CONFIG_URI="'"$cfg"'"
    export ZENOH_CONFIG_OVERRIDE='"'$ovr'"'
    export RUST_LOG="'"${RUST_LOG_R:-zenoh=info,zenoh_transport=debug}"'"
    exec "'"$bin"'"
' 2>&1 | sed -u 's/\x1b\[[0-9;]*m//g' > "$log"
