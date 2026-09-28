#!/usr/bin/env bash
# soak.sh NAME ELF DURATION [extra island_inputs args]
# The real configuration: `just l3-peer` (gateway, 921600, by-id tty, no tap) connecting to a
# stand-in stock router on 7457; the contracted inputs from the host through the stock router.
set -u
S="$(cd "$(dirname "$0")" && pwd)"; REPO=/home/aeon/repos/simple-autoware-safety-island
name=$1 elf=$2 dur=$3; shift 3
R=$S/runs/$name; mkdir -p "$R"
TTY=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0
PUBPID=; POLLPID=
cleanup() { kill $PUBPID $POLLPID 2>/dev/null; pkill -x l3-peer-zenohd 2>/dev/null; sleep 1; }
trap cleanup EXIT
( cd $REPO && just l3-peer "$TTY" 921600 tcp/127.0.0.1:${STOCKPORT:-7457} 7449 "$R/router.log" ) > "$R/l3-peer.stdout" 2>&1 &
for i in $(seq 120); do grep -q "reached at: serial" "$R/router.log" 2>/dev/null && break; sleep 0.5; done
grep -q "reached at: serial" "$R/router.log" || { echo "router did not come up"; exit 1; }
sleep 1
date +%s.%N > "$R/reset.log"; pyocd reset -t s32k344 >> "$R/reset.log" 2>&1; date +%s.%N >> "$R/reset.log"
python3 $S/swd_poll.py "$elf" $((dur + 25)) ${PERIOD:-10} --threads > "$R/poll.log" 2>&1 &
POLLPID=$!
sleep ${PUBDELAY:-6}
PORT=${STOCKPORT:-7457} $S/run_inputs.sh --duration "$dur" "$@" > "$R/pub.log" 2>&1 &
PUBPID=$!
wait $PUBPID
sleep 5
kill $POLLPID 2>/dev/null
cat /sys/bus/usb-serial/devices/ttyUSB0/latency_timer > "$R/latency_timer.txt"
echo "soak $name done"
