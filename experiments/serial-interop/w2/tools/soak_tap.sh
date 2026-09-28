#!/usr/bin/env bash
# soak through the socat tap with the gateway config (router.sh == l3-peer's env and config)
S="$(cd "$(dirname "$0")" && pwd)"
name=$1 elf=$2 dur=$3; shift 3
export CFG=/home/aeon/repos/simple-autoware-safety-island/demo/l3/router/island-gateway.json5
export CONNECT=tcp/127.0.0.1:7457 PUBPORT=7457 PERIOD=${PERIOD:-5} POLLFLAGS=--threads
export RUST_LOG_R="${RUST_LOG_R:-zenoh=info,zenoh_transport=debug,zenoh::net::routing::interceptor=trace,zenoh::net::routing::dispatcher=debug}"
python3 -c 'import serial; s=serial.Serial("/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0", 921600); s.set_low_latency_mode(True); s.close()'
exec $S/run_diag.sh "$name" 921600 "$elf" $((dur + 20)) 6 --duration "$dur" "$@"
