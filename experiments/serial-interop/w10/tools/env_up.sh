#!/usr/bin/env bash
# env_up.sh DIR SECS [inputs=1]: stock router 7471 + gateway 7479 (+ inputs) for SECS, for debugger sessions
S="$(cd "$(dirname "$0")" && pwd)"; W="$(dirname "$S")"
R=$1; secs=$2; inputs=${3:-1}; mkdir -p "$R"
TTY=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0
"$S/r1stock.sh" 7471 "$R/stock.log" & SP=$!
( cd "${ISL:-$(cd "$S/../../../.." && pwd)}" && just l3-peer "$TTY" 921600 tcp/127.0.0.1:7471 7479 "$R/router.log" ) > "$R/l3.stdout" 2>&1 & GP=$!
for i in $(seq 60); do grep -q "reached at: serial" "$R/router.log" 2>/dev/null && break; sleep 0.5; done
[ "$inputs" = 1 ] && { PORT=7471 "$S/run_inputs.sh" --duration "$secs" --report-period 1 > "$R/pub.log" 2>&1 & IP=$!; }
echo "env up"
sleep "$secs"
kill $IP 2>/dev/null; sleep 2; kill $(pgrep -x l3-peer-zenohd) $SP 2>/dev/null
echo "env down"
