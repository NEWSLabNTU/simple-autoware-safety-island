#!/usr/bin/env bash
# direct (no tap) run with an alternative gateway config, via router.sh (same env as l3-peer)
S="$(cd "$(dirname "$0")" && pwd)"
name=$1 elf=$2 dur=$3 cfg=$4; shift 4
python3 -c 'import serial; s=serial.Serial("/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0", 921600); s.set_low_latency_mode(True); s.close()'
export NOTAP=1 CFG=$cfg CONNECT=tcp/127.0.0.1:7457 PUBPORT=7457 PERIOD=${PERIOD:-5} POLLFLAGS=--threads
exec $S/run_diag.sh "$name" 921600 "$elf" $((dur + 20)) 6 --duration "$dur" "$@"
