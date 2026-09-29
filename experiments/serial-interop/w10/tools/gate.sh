#!/usr/bin/env bash
# gate.sh NAME ELF SOAK NMID
# phase8-W10 late-join gate. The board is HALTED first, so the gateway comes up with no island.
# Then: a stand-in stock router (STOCKPORT, default 7471), the island gateway (`just l3-peer`,
# from the W10 island worktree, 921600, the FTDI by-id path or a socat tap when TAP=1),
# every contracted input at its contract rate through the stock router, PRE seconds of inputs
# flowing, THEN the board reset (cold join), SOAK seconds, and NMID more resets each followed
# by SOAK seconds (mid-run resets: the gateway still holds the old session).
set -u
S="$(cd "$(dirname "$0")" && pwd)"; W="$(dirname "$S")"
ISL=${ISL:-$(cd "$S/../../../.." && pwd)}   # the island checkout whose `just l3-peer` runs
name=$1 elf=$2 soak=$3 nmid=$4
R=$W/runs/$name; mkdir -p "$R"
TTY=/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0
SP=${STOCKPORT:-7471}; GP=${GWPORT:-7479}; PRE=${PRE:-20}
PUBPID=; POLLPID=; STOCKPID=; GWPID=; SOCATPID=
cleanup() {
  kill $PUBPID $POLLPID 2>/dev/null; sleep 2
  pkill -x l3-peer-zenohd 2>/dev/null; kill $GWPID $STOCKPID $SOCATPID 2>/dev/null
}
trap cleanup EXIT
for i in $(seq 40); do fuser "$TTY" >/dev/null 2>&1 || break; sleep 0.5; done
if ss -ltn | awk '{print $4}' | grep -qE "[:.]($SP|$GP)$"; then echo "port $SP or $GP busy"; exit 1; fi
bash "$S/offsets.sh" "$elf" > "$R/offsets.json"
echo "image=$elf sha256=$(sha256sum "$elf" | cut -d' ' -f1)" > "$R/meta.txt"
pyocd cmd -t s32k344 -O resume_on_disconnect=false -c halt > "$R/halt.log" 2>&1; echo "halted rc=$?" >> "$R/meta.txt"
"$S/r1stock.sh" $SP "$R/stock.log" & STOCKPID=$!
python3 -c 'import serial,sys; s=serial.Serial(sys.argv[1], 921600); s.set_low_latency_mode(True); s.close()' $TTY
if [ "${TAP:-0}" = 1 ]; then
  socat -x -v "$TTY",raw,echo=0,b921600 PTY,link=$R/ttyTAP,raw,echo=0 2> "$R/tap.hex" & SOCATPID=$!
  sleep 1; GWTTY=$R/ttyTAP
else
  GWTTY=$TTY
fi
( cd "$ISL" && L3_PEER_RUST_LOG=${L3_PEER_RUST_LOG:-zenoh=info,zenoh_transport=debug} \
    just l3-peer "$GWTTY" 921600 tcp/127.0.0.1:$SP $GP "$R/router.log" ) > "$R/l3-peer.stdout" 2>&1 & GWPID=$!
for i in $(seq 120); do grep -q "reached at: serial" "$R/router.log" 2>/dev/null && break; sleep 0.5; done
grep -q "reached at: serial" "$R/router.log" || { echo "gateway did not come up"; exit 1; }
total=$(( soak * (1 + nmid) ))
resets=0; for k in $(seq 1 $nmid); do resets="$resets,$(( k * soak ))"; done
if [ "${ISLAND_FIRST:-0}" = 1 ]; then
  echo "ISLAND FIRST: reset now, inputs start ${PUB_AFTER:-5}s later; resets at +[$resets] s" | tee -a "$R/meta.txt"
  python3 "$S/poll.py" "$elf" "$R/offsets.json" $(( total + 5 )) ${PERIOD:-2} --reset-at "$resets" --threads-every ${THEVERY:-30} > "$R/poll.log" 2>&1 & POLLPID=$!
  sleep ${PUB_AFTER:-5}
  PORT=$SP "$S/run_inputs.sh" --duration $(( total + 30 )) --report-period 1 > "$R/pub.log" 2>&1 & PUBPID=$!
else
PORT=$SP "$S/run_inputs.sh" --duration $(( PRE + total + 200 )) --report-period 1 > "$R/pub.log" 2>&1 & PUBPID=$!
# PRE counts from the publisher's first 1 s report, not from its launch: on a
# loaded host rclpy took 83 s to come up once, and that run was an island-first
# join, not a late one.
for i in $(seq 400); do grep -q '^wall=' "$R/pub.log" 2>/dev/null && break; sleep 0.5; done
grep -q '^wall=' "$R/pub.log" || { echo "inputs did not come up"; exit 1; }
sleep "$PRE"
echo "inputs flowing for ${PRE}s; cold join now; resets at +[$resets] s" | tee -a "$R/meta.txt"
python3 "$S/poll.py" "$elf" "$R/offsets.json" $(( total + 5 )) ${PERIOD:-2} --reset-at "$resets" --threads-every ${THEVERY:-30} > "$R/poll.log" 2>&1 & POLLPID=$!
fi
wait $POLLPID; POLLPID=
kill -INT $PUBPID 2>/dev/null; sleep 3; kill $PUBPID 2>/dev/null; PUBPID=
cat /sys/bus/usb-serial/devices/ttyUSB0/latency_timer > "$R/latency_timer.txt"
echo "gate run $name done"
