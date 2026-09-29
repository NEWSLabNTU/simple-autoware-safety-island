#!/usr/bin/env bash
# react.sh NAME: late-join reaction. Inputs first; the board reset 20 s later;
# availability stopped STOP_AFTER s after the new instance's first mrm_state;
# host-side last availability -> MRM_OPERATING / first braking command.
S="$(cd "$(dirname "$0")" && pwd)"; W="$(dirname "$S")"
ISL=${ISL:-$(cd "$S/../../../.." && pwd)}
name=$1; R=$W/runs/$name; mkdir -p "$R"
TTY=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0
for i in $(seq 40); do fuser "$TTY" >/dev/null 2>&1 || break; sleep 0.5; done
cleanup() { kill $PUBPID 2>/dev/null; sleep 2; pkill -x l3-peer-zenohd 2>/dev/null; kill $STOCKPID 2>/dev/null; }
trap cleanup EXIT
pyocd cmd -t s32k344 -O resume_on_disconnect=false -c halt > "$R/halt.log" 2>&1
"$S/r1stock.sh" 7471 "$R/stock.log" & STOCKPID=$!
( cd "$ISL" && just l3-peer "$TTY" 921600 tcp/127.0.0.1:7471 7479 "$R/router.log" ) > "$R/l3-peer.stdout" 2>&1 &
for i in $(seq 120); do grep -q "reached at: serial" "$R/router.log" 2>/dev/null && break; sleep 0.5; done
PORT=7471 "$S/run_inputs.sh" --duration 60 --report-period 1 --first-mrm-after-gap --arm-after 0 \
    --stop-after-first-mrm ${STOP_AFTER:-5.0} > "$R/pub.log" 2>&1 & PUBPID=$!
sleep 20
date +%s.%N > "$R/reset.log"; pyocd reset -t s32k344 >> "$R/reset.log" 2>&1; date +%s.%N >> "$R/reset.log"
wait $PUBPID; PUBPID=
grep -E 'first mrm|STOPPED|mrm_state ->' "$R/pub.log"
grep -o '"host_last_avail_to_operating_ms": [0-9.]*, "host_last_avail_to_brake_ms": [0-9.]*' "$R/pub.log"
