#!/usr/bin/env bash
# reaction.sh NAME ELF: gateway (l3-peer recipe) first, all contracted inputs from the host
# through the stand-in stock router, board reset, availability stopped 1.0 s after the
# new island instance's first mrm_state, then the trace read over SWD.
set -u
S="$(cd "$(dirname "$0")" && pwd)"; REPO=/home/aeon/repos/simple-autoware-safety-island
name=$1 elf=$2
R=$S/runs/$name; mkdir -p "$R"
TTY=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0
PUBPID=
cleanup() { kill $PUBPID 2>/dev/null; pkill -x l3-peer-zenohd 2>/dev/null; sleep 1; }
trap cleanup EXIT
( cd $REPO && just l3-peer "$TTY" 921600 tcp/127.0.0.1:7457 7449 "$R/router.log" ) > "$R/l3-peer.stdout" 2>&1 &
for i in $(seq 120); do grep -q "reached at: serial" "$R/router.log" 2>/dev/null && break; sleep 0.5; done
if [ "${ISLAND_FIRST:-0}" = 1 ]; then
  # the island joins an idle domain (as in the soak), the inputs start ~PUB_AFTER s after the reset
  date +%s.%N > "$R/reset.log"; pyocd reset -t s32k344 >> "$R/reset.log" 2>&1; date +%s.%N >> "$R/reset.log"
  sleep ${PUB_AFTER:-3}
  PORT=7457 $S/run_inputs.sh --duration ${DUR:-40} --first-mrm-after-gap --arm-after 0 --stop-after-first-mrm ${STOP_AFTER:-0.5} > "$R/pub.log" 2>&1 &
  PUBPID=$!
else
  PORT=7457 $S/run_inputs.sh --duration ${DUR:-60} --first-mrm-after-gap --arm-after 3 --stop-after-first-mrm ${STOP_AFTER:-1.0} > "$R/pub.log" 2>&1 &
  PUBPID=$!
  sleep 6
  date +%s.%N > "$R/reset.log"; pyocd reset -t s32k344 >> "$R/reset.log" 2>&1; date +%s.%N >> "$R/reset.log"
fi
wait $PUBPID
# the trace (one-shot RAM buffer) over SWD
NM=/home/aeon/.nros/sdk/arm-none-eabi-gcc/13.2-nros4/bin/arm-none-eabi-nm
read -r addr len _ < <($NM -S "$elf" | awk '$4=="ram_tracing"{print $1, $2}')
pyocd cmd -t s32k344 -c "savemem 0x$addr $((16#$len)) $R/trace.bin" > "$R/savemem.log" 2>&1
echo "image=$elf" > "$R/trace.bin.meta"; echo "image_sha256=$(sha256sum "$elf" | cut -d' ' -f1)" >> "$R/trace.bin.meta"
echo "captured=$(date -u +%FT%TZ)" >> "$R/trace.bin.meta"
echo "reaction $name done"
