#!/usr/bin/env bash
# run_diag.sh NAME BAUD ELF SECS PUB_DELAY [publisher args...]
# socat tap on the FTDI -> pty; rmw_zenohd (board-peer recipe) on the pty; SWD poller with reset;
# the input publisher after PUB_DELAY seconds. Everything logged under runs/NAME/.
set -u
S="$(cd "$(dirname "$0")" && pwd)"
name=$1 baud=$2 elf=$3 secs=$4 delay=$5; shift 5
R=$S/runs/$name; mkdir -p "$R"
REPO=/home/aeon/repos/simple-autoware-safety-island
TTY=${TTY:-/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0}
cleanup() { kill $PUBPID $POLLPID 2>/dev/null; pkill -f "board-peer-zenohd" 2>/dev/null; kill $SOCATPID 2>/dev/null; sleep 1; }
trap cleanup EXIT
if [ "${NOTAP:-0}" = 1 ]; then
  RTTY=$TTY; SOCATPID=
else
  socat -x -v "$TTY",raw,echo=0,b$baud PTY,link=$R/ttyTAP,raw,echo=0 2> "$R/tap.hex" &
  SOCATPID=$!; sleep 1; RTTY=$R/ttyTAP
fi
$S/router.sh "$RTTY" $baud ${PORT:-7449} "$R/router.log" "${CFG:-$REPO/experiments/serial-interop/router-serial.json5}" "${CONNECT:-}" &
sleep 4
PUBPID=
if [ "${PUBFIRST:-0}" = 1 ] && [ $# -gt 0 ]; then PORT=${PUBPORT:-7449} ${PUBCMD:-$S/run_inputs.sh} "$@" > "$R/pub.log" 2>&1 & PUBPID=$!; sleep ${PUBFIRST_WAIT:-8}; fi
pyocd reset -t s32k344 > "$R/reset.log" 2>&1; date +%s.%N >> "$R/reset.log"
python3 $S/swd_poll.py "$elf" "$secs" "${PERIOD:-0.5}" ${POLLFLAGS:-} > "$R/poll.log" 2>&1 &
POLLPID=$!
if [ -n "${NODELIST_AT:-}" ]; then (sleep $NODELIST_AT; PORT=${PUBPORT:-7449} $S/nodelist.sh > "$R/nodelist.txt" 2>&1) & fi
sleep "$delay"
if [ "${PUBFIRST:-0}" != 1 ] && [ $# -gt 0 ]; then
  PORT=${PUBPORT:-7449} ${PUBCMD:-$S/run_inputs.sh} "$@" > "$R/pub.log" 2>&1 &
  PUBPID=$!
fi
wait $POLLPID
echo "run $name done"
