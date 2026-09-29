# The serial link: the stall, 921,600 baud, the island gateway

phase8-W2, 2026-09-28. Board MR-CANHUBK344 (S32K344, Cortex-M7 at 160 MHz),
DCD-LZ cable (FT232R, `0403:6001`) on the board's LPUART2, host `rmw_zenohd`
from ros-humble-rmw-zenoh-cpp 0.1.9 (zenoh 1.8.0). Everything below was
measured on the board today unless a line says otherwise. Raw data, the
scripts that produced it and the flashed image are under
`experiments/serial-interop/w2/` (`runs/<run>/`, `tools/`).

## 0. Short answer

- **Root cause of brief B's stall.** zenoh-pico's read task on the board
  EXITS the first time the session layer rejects one received message, and
  nothing closes the session. From then on the board hears nothing; its own
  lease expires two periods (2 x 10 s) later and it closes the session. That
  is the "router expires the session ~21 s after opening": measured 21.18 s,
  and the CLOSE comes from the board. Two things on this link produce such a
  message within seconds:
  1. the router's liveliness history burst when the island's service clients
     subscribe to `@ros2_lv/10/**` (2.5 KB for three CLI nodes, in three
     back-to-back frames) overflows the 1 KiB receive ring while the read task
     is starved by the busy-wait transmit (620 ms without a single context
     switch at 115200); a frame carrying `D_KEYEXPR`s is lost and the next
     `D_TOKEN` names one of its ids: `_Z_ERR_KEYEXPR_UNKNOWN`;
  2. host nodes leaving: the router sends `U_TOKEN` twice per rmw_zenoh token,
     once by the id it declared to the board and once by an id it never
     declared to it: `_Z_ERR_ENTITY_UNKNOWN`.
- **No-code mitigation, measured.** An ACL on the gateway router that denies
  `liveliness_token` on egress to the serial link: zero `D_TOKEN`/`U_TOKEN`
  toward the board, the host still lists the four island nodes, the read task
  survived a transient `ros2 node list`.
- **Firmware fix, prepared.** zenoh-pico: a rejected message is counted and
  dropped, the batch and the read task go on (nano-ros issue 1533, fork commit
  `52f60b79`, not yet pushed; see section 10). nano-ros PR #1386: a Kconfig
  for the receive ring, issues 1533 and 1534 (the priority inversion behind
  the starvation).
- **921,600 baud on both ends** (board locator and overlay, gateway listen
  endpoint, FTDI latency timer 1 ms). Neither end is exact: the board runs
  909,091 (-1.36 %, read back from LPUART2 BAUD), the FT232R 923,077
  (+0.16 %). 0 bad frames in either direction over 10 min through a wire tap.
  1,000,000 would be exact on both.
- **The gateway** (`just l3-peer`, `demo/l3/router/island-gateway.json5`):
  its own `rmw_zenohd` on the serial port by its `/dev/serial/by-id` path,
  connected to the stock router, keep_alive 6, egress downsampling of
  kinematic_state / control_mode (and gear_cmd until phase8-W25, after the
  island stopped reading it), the liveliness ACL, and a
  transmit queue raised from 2 to 16 batches: with the stock queue, zenoh 1.8
  stopped sending data to the board for good 215 s into a soak while its
  keepalives still passed (a false emergency).
- **Soak: PASS.** 600 s, every contracted input at its contract rate with real
  message sizes, through `just l3-peer` directly on the FTDI: session open
  throughout, no false emergency, in-run delivery 29.998-30.000/s and
  9.985-10.001/s per topic, 0 samples lost after startup on the undownsampled
  inputs. CPU: read task 32.1 %, busy-wait transmit 9.5 %, idle 51.4 %.
- **Reaction at 921,600**, availability stopped, on-board cycle-counter time:
  last availability sample to braking command **609.8 ms** (detection 592.8,
  then 17.0 ms to the brake; the `call_mrm` tick is 14.6 ms, was 28-38 ms at
  115200). Seen from the host: 644.4 ms to `MRM_OPERATING`, 697.9 ms to the
  first braking command.
- **Joining under load: solved (phase8-W10, section 11).** The cause was not
  the busy-wait alone: main registers the image's entities at Zephyr's default
  `CONFIG_MAIN_THREAD_PRIORITY` 0, above the read task (k_thread 4), and the
  tx-flush thread inherits that 0, so nothing drained the RX ring while the
  island registered; with the inputs already flowing it overflowed within
  180 ms of boot and the lost frames carried the router's answers to the
  publishers' write-filter interests (four of five outputs never sent; #1389
  keeps the reader alive, it does not bring those frames back). Fix: main
  registers at priority 5 (the flush thread follows, and nano-ros PR #1443
  pins it to the read band), the RX ring is 4 KiB, TX is interrupt-driven
  (zenoh-pico `e28ff603`). Gate on island main `3fb4cfb` (section 11.5): 5 cold
  joins and 3 mid-run resets with every input already flowing, 10 min soak
  after each: all eight joined 0.12-2.0 s after the reset, every output at
  rate, no false emergency, no RX ring overflow; two frames were lost in the
  80 min of soak (bad frames with no UART error, cause open).
  The island no longer has to join before the inputs flow.

## 1. The stall at 115200: what happens, with evidence

Instruments, all live while the board runs:

- `tools/swd_poll.py` reads over SWD without halting: the transport's
  `_read_task_running` and `_lease_task_running`, the RX ring's indices,
  LPUART2 `STAT` (OR, RDRF...), the graph cache, each subscription ring's
  `tail` (a monotonic count of samples accepted), and every thread's
  priority, state and `usage` (CONFIG_SCHED_THREAD_USAGE_ALL: CPU cycles).
- a socat tap (`socat -x -v <ftdi> PTY,...`, the router on the pty) and
  `tools/tapdecode.py` / `tools/declwalk.py`, which undo COBS and walk every
  zenoh network message per direction.

Threads on the board image (read from `k_thread`, entry symbolised):

    th 20404980 <unnamed>     prio=0   entry _zpico_tx_flush_task_fn, arg g_sessions
    th 20404840 zpico_lease   prio=4
    th 20404700 zpico_read    prio=4
    th 2040b8d8 main          prio=0 at registration, 4 afterwards

The transmit (the tx-flush task, and main while it declares) runs ABOVE the
read task, and the serial transmit is `uart_poll_out` per byte, a busy-wait
(86.8 us per byte at 115200). Issue 0626 stated the read and lease
priorities; the flush task has no default and lands at `k_thread` 0.

### 1.1 Trigger 1: host nodes leave (run r2)

Three `ros2 topic pub` nodes published for 40 s, then exited. The router's
undeclarations toward the board (`declwalk.py`, id and wire-expr extension):

    18:35:13.030811 U_TOKEN None 17 ['0000']
    18:35:13.030811 U_TOKEN None 19 ['0000']
    18:35:13.030811 U_TOKEN None 18 ['0000']
    18:35:13.030811 U_TOKEN None 26 ['0000']
    18:35:13.030811 U_TOKEN None 29 ['0247']
    18:35:13.030811 U_TOKEN None 30 ['024e']
    ...
    18:35:13.032156 U_TOKEN None 38 ['024a']

The router had declared tokens 14-28 to the board, never 29-38; each of 29-38
carries the key of a token already undeclared by its first id (0x47 = key 71 =
the same node's `parameter_events` token as `D_TOKEN 19`). The board, polled
every 0.5 s:

    18:35:12.636 readtask=1 lease=1 ring=0/1024 ... gc(len=2266,n=15,drop=0) tails=[0 0 0 0 386 0 383 407 1231 387 0]
    18:35:13.137 readtask=0 lease=1 ring=163/1024 ... gc(len=1682,n=11,drop=0) tails=[0 0 0 0 390 0 387 412 1246 390 0]
    18:35:13.637 readtask=0 lease=1 ring=181/1024 ... gc(len=1682,n=11,drop=0) tails=[0 0 0 0 390 0 387 417 1260 390 0]

Four tokens left the graph cache (15 -> 11), the fifth undeclaration was
`U_TOKEN 29`, and the read task stopped: 181 bytes stay in the ring, the three
host-fed tails (slots 4, 6, 9) freeze, and the island-internal ones (7, 8)
keep counting.

### 1.2 Trigger 2: the history burst at join (run r4, brief B's shape)

Three `ros2 topic pub` nodes already running; the board reset into them. The
router's answer to the island's liveliness interest (id 80):

    18:46:59.824626 router->board ser=- len=182 FRAME DECLARE:D_KEYEXPR [...]
    18:46:59.824817 router->board ser=- len=1434 FRAME DECLARE:D_KEYEXPR [...]
    18:46:59.824817 router->board ser=- len=876 FRAME DECLARE:D_KEYEXPR [...]

The third frame ends with `D_TOKEN 14 -> key 1` ... `D_TOKEN 28 -> key 80`,
keys declared in the first two. The board:

    18:47:00.001 readtask=1 lease=1 ring=4/1024 rfull=0 ... gc(len=0,n=0,drop=0) tails=[0 0 0 0 3 0 2 4 8 1 0]
    18:47:03.003 readtask=0 lease=1 ring=1024/1024 rfull=1 ... gc(len=0,n=0,drop=0) tails=[0 0 0 0 3 0 2 34 99 1 0]
    18:47:21.019 readtask=0 lease=0 ring=11/1024 rfull=0 ... tails=[0 0 0 0 3 0 2 202 609 1 0]

Three, two and one samples at the first spin, then none: brief B's run 5
exactly. No token reached the graph cache, so the first `D_TOKEN` already
failed. The session:

    2026-09-28T10:46:58.724610Z DEBUG acc-0 ... New transport opened between 2611d9d63e2a8c4df9bb888091a4bc4d and c09dda6cd0f9cf6f04d9233b448394cb
    2026-09-28T10:47:19.897463Z DEBUG net-0 ... Closing transport with peer: c09dda6cd0f9cf6f04d9233b448394cb

21.17 s. On the wire, the close is the BOARD's:

    18:47:19.896344 board->router ser=- len=165 FRAME PUSH []
    18:47:19.896344 board->router ser=- len=2 CLOSE  []
    18:47:19.896344 board->router ser=INIT len=0 empty  []

zenoh-pico's lease task found nothing received for two 10 s periods, closed,
and began reconnecting. brief B read this as the router expiring the board.

### 1.3 The starvation behind the lost frame (run r5)

Same setup, SWD every 50 ms. `kus` is `_kernel.usage`, which moves only on a
context switch:

    18:48:56.087 readtask=1 lease=1 ring=76/1024 rfull=0 ... kus=2144855
    18:48:56.445 readtask=1 lease=1 ring=312/1024 rfull=0 ... kus=2144855
    18:48:56.596 readtask=1 lease=1 ring=588/1024 rfull=0 ... kus=2144855
    18:48:56.658 readtask=1 lease=1 ring=870/1024 rfull=0 ... kus=2144855
    18:48:56.708 readtask=1 lease=1 ring=1024/1024 rfull=1 ... kus=2144855
    18:48:56.870 readtask=1 lease=1 ring=2/1024 rfull=0 ... kus=183525107

620 ms without a context switch while the ring filled from 76 bytes to full
and latched `_z_serial_rx_ring_full`: the thread sending the island's
declarations busy-waited the whole time. In this run the lost bytes fell on
frames nothing referenced later, so the read task survived (graph cache 15
entries). UART hardware overruns (`STAT.OR`) were never seen; the loss is the
ring, not the ISR.

### 1.4 Why the read task stops

`_z_unicast_handle_frame` returned the first error `_z_handle_network_message`
gave; `_z_unicast_process_messages` returned it; `_zp_unicast_read_task`
answered with `_read_task_running = false` and returned. The lease task goes
on sending, so the router sees a live peer. Upstream zenoh-pico has the same
frame handler; its read task closes the session instead.

## 2. The no-code mitigation: the liveliness ACL (run g1)

On the gateway router (section 4), serial egress, `liveliness_token` on
`@ros2_lv/**` denied. Same trigger as r4 plus a transient `ros2 node list`
through the stock router 15 s after the reset:

    $ declwalk.py tap.hex | grep -c -E 'D_TOKEN|U_TOKEN'
    0
    18:55:00.561988035
    /mrm_comfortable_stop_operator
    /mrm_emergency_stop_operator
    /mrm_handler
    /stop_mode_operator
    18:55:01.438157406
    18:55:05.939 readtask=1 lease=1 ... gc(len=0,n=0,drop=0) tails=[0 0 0 0 189 0 188 188 566 188 0]
    18:55:30.962 readtask=1 lease=1 ... gc(len=0,n=0,drop=0) tails=[0 0 0 0 439 0 438 438 1325 438 0]

The ACL filters the history replay and the undeclarations alike (open
question 6 of brief C: yes, for zenoh 1.8 and `link_protocols: ["serial"]`).
The island's own tokens are ingress and reach the host. Side effect in the
router log, harmless here: `Transport returned multiple network interfaces,
current ACL logic might incorrectly apply filters` (it names the board's
interface `ttyACM0`, the MCU-Link port). The ACL removes trigger 2 at join and
trigger 1 entirely; it does not remove the starvation (section 7).

## 3. 921,600 baud: the settings

| place | setting |
| --- | --- |
| board locator | `CONFIG_NROS_ZENOH_LOCATOR="serial/uart@40330000#baudrate=921600"`, `src/zephyr_entry/snippets/island-serial/serial.conf`. zenoh-pico passes it to `uart_configure()`, so this is the rate. |
| board devicetree | `&lpuart2 { current-speed = <921600>; }`, `serial.overlay` (boot default only, kept equal) |
| LPUART2, read back | `BAUD = 0x15000002`: OSR 22, SBR 2, 40 MHz / 44 = **909,091** (-1.36 %) |
| FT232R | 3 MHz / 3.25 = **923,077** (+0.16 %); `latency_timer` 16 -> **1 ms**, set without root through the ASYNC_LOW_LATENCY flag (`l3-peer` does it) |
| gateway listen | `serial//dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B001UCTE-if00-port0#baudrate=921600` |
| `just board-peer` | now `baud=921600` by default (was hard-wired 115200) |

The 1.5 % mismatch between the two ends is inside what 8N1 tolerates, and the
10-minute tapped soak counted 0 bad frames in either direction
(`runs/soak3-tap/tap.stats.txt`):

    board->router: 5014198 wire bytes, 0 bad frames
    router->board: 17278830 wire bytes, 0 bad frames

1,000,000 baud is exact on both (OSR 20 x SBR 2; FT232R divisor 3) and would
remove the mismatch; the phase-8 decision says 921,600 and it works.

The image on the board for every 921,600 run below is `build-board-d8q`
(brief B's image: services off, heap 122,880, local queryable, 24 KiB trace)
with only the 37-byte locator string changed in place, `115200` -> `921600`
(ELF offset 415546, flash 0x46559a; ELF sha256 `3cd33b59...` from
`41332317...`). The source edits above make a fresh build say the same; the
patched ELF is `experiments/serial-interop/w2/zephyr-d8q-921600.elf.xz`.

Measured load at contract rates (soak3, 620 s on the tap): router -> board
27.9 KB/s = **30.3 %** of the line, board -> router 8.1 KB/s = **8.8 %**. A
sample costs about 100 B of wire beyond its payload: the router sends the
island's own declared key id plus the 22-byte suffix `/TypeHashNotSupported`
(not the full key; brief C open question 4), the 33-byte attachment, zenoh
framing, the serial header, CRC and COBS. Single-sample frames measured 114 B
(13 B payloads), 120 B (19 B), 818 B (Odometry, 718 B). The two island-internal
status topics also cross the link (`emergency_stop/status` 30.9/s,
`comfortable_stop/status` 10.2/s) with no remote reader: brief C's G7.

## 4. The island gateway router

`just l3-peer` (just/l3-demo.just), config `demo/l3/router/island-gateway.json5`
(a full copy of the stock router config, because `ZENOH_ROUTER_CONFIG_URI`
replaces rather than merges; its header lists the four deltas and the diff
command):

    just l3-peer [tty=/dev/serial/by-id/...FT232R...] [baud=921600] [stock=tcp/127.0.0.1:7447] [port=7449] [log=...]

1. `keep_alive: 6` (router-serial.json5's reason).
2. Downsampling, serial egress, `put`: kinematic_state and control_mode
   limited to 12 Hz (gear_cmd too until phase8-W25; the island has not read
   it since phase8-W8a). A limit AT the source rate drops samples to
   jitter; 12 Hz passes a 10 Hz source (0.13 % dropped, soak4) and takes one
   in four of the simulator's 40 Hz. steering_status, velocity_status and
   control_cmd are not downsampled: their contract rate is 30 Hz and dropping
   from 40 Hz gives 20 Hz; at 921,600 they fit at 40 Hz.
3. The liveliness ACL of section 2.
4. `queue.size.data: 16` and `congestion_control.drop.wait_before_drop: 50000`
   (stock 2 and 1000 us). Section 5.

It connects to the stock router with `connect/endpoints`; routers retry that
forever (`timeout_ms: router -1`), so start order between the two does not
matter, but the board must be reset after the gateway listens. For these
tests the stock router was a second `rmw_zenohd` on 7457 (`tools/r1stock.sh`),
because W3's router already held 7447 and a test domain must not leak into it.
The inputs and the output subscribers talked to that stock router, never to
the gateway, as Autoware will.

## 5. The gateway stall: zenoh 1.8 stops sending data to the board

soak2 ran with the stock queue (2 batches, 1 ms before drop), the gateway on
the FTDI directly. At 215 s:

    [INFO] [1790594076.103957204] [w2_island_inputs]: mrm_state -> state=2 behavior=2 at t=215.005s

a false emergency. The board's view, 10 s apart:

    19:14:44.236 readtask=1 lease=1 ring=0/1024 ... tails=[6432 6432 6431 6431 2144 2143 2143 2303 6975 2144 2143]
    19:14:54.247 readtask=1 lease=1 ring=0/1024 ... tails=[6432 6432 6431 6431 2144 2143 2143 2403 7279 2144 2143]
    19:14:34.228 read=32.1% flush=9.6% main=6.6% idle=51.7%
    19:14:44.236 read=4.1% flush=9.3% main=5.9% idle=80.6%
    19:14:54.247 read=0.0% flush=9.4% main=5.6% idle=85.2%

The read task is alive and has nothing to read; the session stays open for the
remaining 6 minutes, so keepalives still arrive. A subscriber on the gateway's
own TCP port still received availability, and a publisher on that port did
not reach the board: the gateway had stopped sending data on the serial face.

zenoh 1.8's transmission pipeline marks a priority queue congested when a
droppable message cannot get a batch within `wait_before_drop`, and from then
drops every droppable message at once until a refilled batch clears the flag;
keepalives are transport messages and bypass it. Provoking it (run p1, queue
1, wait 0, the FTDI direct): one sample reached the board, then none for 150 s,
with the session open:

    19:37:31.351 readtask=1 lease=1 sn_rel=149114024 ... tails=[0 0 0 0 1 0 0 207 626 0 0]
    19:40:01.538 readtask=1 lease=1 sn_rel=149114025 ... tails=[0 0 0 0 1 0 0 1709 5177 0 0]

(`sn_rel` is the board's last accepted reliable sequence number: it froze.)
The flag evidently did not clear; why, in zenoh's code, is not established.
The same stall never happened behind the socat tap (a pty's writes never
block): g2 60 s and soak3 600 s clean. With the stock queue on the FTDI
directly, s0 ran 60 s clean and soak2 stalled at 215 s (soak1 is confounded by
its late join, section 7). With 16 batches (about 260 ms of line at 921,600) and 50 ms
before a drop, soak4 ran 600 s clean on the FTDI directly (section 6). That is
evidence the stall needs congestion, not proof it cannot recur; the gateway
log is where to look first if the board goes quiet with its session open.

## 6. The soak (soak4)

Setup: `just l3-peer` on the FTDI directly (no tap), stand-in stock router on
7457, board reset after the gateway listened, then `tools/island_inputs.py`
through the stock router: every external input of the contract at its contract
rate with real message sizes (availability, kinematic_state as a 718 B
Odometry with covariances and frame ids, control_mode AUTONOMOUS, gear_cmd
DRIVE, operation_mode/state AUTONOMOUS at 10 Hz; control_cmd, steering_status,
velocity_status, route_state SET at 30 Hz), subscribed to the five outputs
vehicle_cmd_gate reads. The two operator status topics the handler reads are
published on the island itself and delivered locally, so the host does not
publish them (a second writer would override the operators). SWD every 5 s.

    SUMMARY {"duration": 600.0630918890238, "sent": {"availability": 6000, "kinematic_state": 6000, "control_mode": 6000, "gear_cmd": 6000, "operation_mode_state": 6000, "control_cmd": 18000, "steering_status": 18000, "velocity_status": 18000, "route_state": 18000}, "recv": {"mrm_state": 5999, "emergency_control_cmd": 10713, "emergency_gear_cmd": 5999, "emergency_hazard": 5999, "emergency_turn": 5999}, "mrm_states": [[0.192, 1, 1]], "mrm_gap_max": 0.16, ...}
    19:52:16.842 readtask=1 lease=1 sn_rel=246361366 ... rfull=0 ... tails=[17981 17981 17981 17981 5994 5986 5986 6209 18811 5994 5985]

| input | rate | sent | received on the island (final ring tail) | in-run rate over 565.5 s |
| --- | ---: | ---: | ---: | ---: |
| control_cmd | 30 | 18000 | 17981 | 29.998/s |
| steering_status | 30 | 18000 | 17981 | 29.998/s |
| velocity_status | 30 | 18000 | 17981 | 30.000/s |
| route_state | 30 | 18000 | 17981 | 29.998/s |
| availability | 10 | 6000 | 5994 | 9.999/s |
| kinematic_state (downsampled 12 Hz) | 10 | 6000 | 5986 | 9.988/s |
| control_mode (downsampled 12 Hz) | 10 | 6000 | 5986 | 9.986/s |
| operation_mode/state | 10 | 6000 | 5994 | 10.001/s |
| gear_cmd (downsampled 12 Hz) | 10 | 6000 | 5985 | 9.985/s |

Slots are mapped by creation order (the four 30 Hz inputs are slots 0-3 and
count identically, so their mutual order does not matter). The 19 / 6 missing
per topic are the first 0.6 s of publishing, the same for every topic
(startup, before the new publishers' routes existed); after that the
undownsampled inputs lost nothing. The downsampled three lose 8-9 more to the
12 Hz limit catching jitter.

| quantity | soak4 (direct, the gate) | soak3 (through the tap, stock queue) |
| --- | --- | --- |
| session | open 600 s, one transport, no close | open 600 s |
| false emergencies | 0 (`mrm_state` NORMAL throughout, max gap 160 ms at the host) | 0 (max gap 171 ms) |
| UART overruns (`STAT.OR`, sampled) | 0 seen | 0 seen |
| RX ring | never full when sampled | full never sampled, peak sampled 621/1024; the router sent 18000 of each 30 Hz input, the board took 17984-17990 (0.06-0.09 % lost on the board) |
| read task CPU | 32.1 % | 32.5 % |
| busy-wait transmit (tx-flush thread) CPU | **9.5 %** | 9.5 % |
| main (executor) CPU | 6.8 % | 6.5 % |
| idle | 51.4 % | 51.5 % |

CPU is each thread's `usage` delta between two SWD reads 525 s apart. The
tx-flush thread does nothing but flush, so its share is the busy-wait: 8.1 KB/s
x 10.85 us per byte = 8.8 % predicted, 9.5 % measured. The read task is the
surprise: about 1,800 cycles per received byte (per-byte ring get, uptime read
and `uart_err_check`, plus decoding).

`emergency/control_cmd` reaches the host at 17.9/s although the board sends
29.3/s (18,176 in soak3's tap): the board's 50 ms TX batches bring two at a
time and the depth-1 host subscriber keeps one. vehicle_cmd_gate reads it with
depth 1 too.

## 7. Joining under load (react2, soak1): not solved here; see section 11

react2: the inputs running first, then the board reset into them. The trace
(the one-shot 24 KiB RAM buffer, 5.6 s from boot):

    PUB_MRM_HANDLER_MRM_STATE                                     46
    TAKE_MRM_HANDLER_OPERATION_MODE_AVAILABILITY                  47

and the host received none of those 46 `mrm_state` samples (its count stayed
at the 51 the previous instance had sent), while `emergency/control_cmd`
arrived. About 70 s later the board's lease expired and it reconnected. soak1
(the gateway came up 17 s after the reset, so the board joined while the
inputs were flowing) showed the same asymmetry and was aborted. With 28 KB/s
arriving during the island's own registration burst, the read task is starved
as in section 1.3 and frames are lost; a publisher whose write-filter reply
is lost believes nobody listens and never sends. There was no tap on these
runs, so which frames were lost is inferred. Until the read task outranks the
transmit (nano-ros issue 1534), the island joins before the inputs flow:
reset the board with Autoware not yet publishing, as the soak did.

## 8. The reaction at 921,600 (react3)

Island first; the inputs started 3 s after the reset; availability stopped
0.5 s after the host saw the new instance's first `mrm_state`; the trace read
over SWD afterwards (`runs/react3/`). Host log:

    [INFO] [1790596749.754992603] [w2_island_inputs]: island first mrm_state (this instance) at t=0.229s
    [INFO] [1790596750.319138408] [w2_island_inputs]: availability publisher STOPPED at t=0.801s mono=4583757.304038 wall=1790596750.318946
    [INFO] [1790596750.863417138] [w2_island_inputs]: mrm_state -> state=2 behavior=2 at t=1.346s wall=1790596750.863189
    host_last_avail_to_operating_ms 644.4
    host_last_avail_to_brake_ms 697.9

On the board (cycle-counter time from the trace's first record; heartbeats put
it within 0.4 ms of uptime):

    last TAKE availability    4322.771 ms
    CALL_MRM entry            4915.596  (+592.8 ms)
    CALL operate              4920.509  (+597.7)
    PUB mrm_state OPERATING   4930.022  (+607.3)
    CALL_MRM exit             4930.226  tick 14.630 ms
    SERVE operate             4932.332  (+609.6)
    PUB control_cmd arg=2     4932.611  (+609.8)  detect->brake 17.0 ms

| | brief B, 115200 | this run, 921,600 |
| --- | --- | --- |
| last sample -> braking command | 554.8, 588.9 ms | **609.8 ms** |
| detection (last sample -> `call_mrm` tick) | 539.9, 515.8 ms | 592.8 ms |
| detecting tick -> braking command | 39.0, 49.0 ms | **17.0 ms** |
| `call_mrm` tick | 28-38 ms | 14.6 ms |
| emergency operator timer period, max | 61-68 ms | 37.2 ms |

The contract composes 610 ms: 500 ms of staleness plus `within: 110ms`.
Detection is 500 ms plus the phase of the handler's 100 ms tick, so it ranges
500-600 ms by construction; this run drew 92.8 ms of phase. What the faster
link bought is the part after detection, 39-49 ms down to 17 ms. The 14.6 ms
tick still holds about 10 ms between the `operate` call and the `mrm_state`
publish, consistent with waiting for a flush batch to finish transmitting.

## 9. Reproduce

    # router first, then the board
    just l3-peer                                     # or: just l3-peer <tty> 921600 tcp/127.0.0.1:7457 7449 <log>
    pyocd reset -t s32k344
    experiments/serial-interop/w2/tools/soak.sh <name> <elf> 600       # the gate run (uses just l3-peer)
    experiments/serial-interop/w2/tools/soak_tap.sh <name> <elf> 600   # the same through a socat tap
    ISLAND_FIRST=1 experiments/serial-interop/w2/tools/reaction.sh <name> <elf>

`soak.sh` expects a stock router on 7457 (`tools/r1stock.sh`). `swd_poll.py`
takes the ELF for its symbol addresses; the struct offsets in its header are
for Zephyr 4.4 and this nano-ros pin, re-read them with gdb for another build.
pyocd reset took 7-36 s instead of 1 s in three runs while the FTDI carried
traffic at a 1 ms latency timer; the scripts wait for it.

## 10. Open items

- nano-ros issue 1533: done (nano-ros PR #1389, zenoh-pico `52f60b79`, in
  the island pin bec9aecb8).
- nano-ros issue 1534: the flush-task default and interrupt-driven TX are
  nano-ros PR #1443 (zenoh-pico `e28ff603`); the island needs the pin bump
  after it merges. The main thread's registration priority is an image
  setting nano-ros does not state yet (section 11).
- `CONFIG_NROS_ZENOH_SERIAL_RX_RING_BYTES` is 4096 on the board now
  (section 11).
- zenoh 1.8's congestion flag (section 5): worth an upstream report with
  run p1 as the reproducer.
- W4 (D9, discovery off) makes the ACL unnecessary; keep the ACL until then.
  phase8-W14: the pin now carries it (nano-ros phase-473 W1), and the serial
  image DERIVES discovery off (`ZPICO_GRAPH_DISCOVERY=0 DERIVED from this
  image's zenoh links (serial)` at configure): no liveliness subscriber, no
  graph cache. The ACL's reason (section 2: the history replay and the token
  churn toward the board) is gone in the image, but the link has not been
  re-measured without the ACL on the board. That run (a tap on the serial
  link, `ros2 node list`, an Autoware restart) decides whether the ACL is
  retired; W10 owns the board.
- In-run bad frames with no UART error and no ring overflow, about one per
  80 min of soak at contract rates (3 in 250 min over 11.4, 11.5 and the
  capture soaks): cause open.
- The contract's `min_rate_hz: 30` on `emergency_control_cmd` is met on the
  board (29.3/s on the wire); the host's depth-1 view is 17.9/s.

## 11. Joining under load, solved (phase8-W10)

phase8-W10, 2026-09-29. Same board, cable and gateway as above; the stand-in
stock router on 7471 and `just l3-peer` on 7479. Every run below starts the
inputs of section 6 FIRST and resets the board 20 s later (a cold join: the
board was halted, so the gateway had never seen it), and the runs with a
mid-run reset reset it again 600 s later while the gateway still holds the old
session. Tools and run summaries: `experiments/serial-interop/w10/`
(`tools/gate.sh`, `tools/poll.py`, `tools/analyze.py`; `poll.py` reads
`_z_zephyr_serial_stats` and the subscription rings by symbol and gdb-derived
offsets, `analyze.py` prints one verdict per join).

### 11.1 The image the current pin builds does not reach the network

`55a65a4` on the pin bec9aecb8, as `just board-build` makes it, stops in
registration on the board (the boot report: stage 4, `RegisteringEntities`).
Three things, each found with a breakpoint, not by reading the conf:

1. `mrm_comfortable_stop_operator` `create_publisher_in` returns -3: its two
   TRANSIENT_LOCAL publishers each declare a cache queryable, and the derived
   `ZPICO_MAX_QUERYABLES` (2) counts only the two service servers.
2. `stop_mode_operator` `create_publisher_in` returns -100: the retention pool
   `ZPICO_MAX_TL_PUBLISHERS` is its builtin 2 for five TRANSIENT_LOCAL
   publishers, because the entity inventory refuses to count them
   ("publisher /system/operation_mode/availability states no `durability`").
   nano-ros main has since merged a fix for that refusal (#1567, not in the pin).
3. Under traffic, `nros_platform_panic("platform heap exhausted")` from the
   serial send path's per-frame `z_malloc` at a 122,880 heap.

For these runs: `CONFIG_NROS_MAX_QUERYABLES=7`, `ZPICO_MAX_TL_PUBLISHERS=5` in
the build environment (no Kconfig row), `CONFIG_NROS_ZEPHYR_HEAP_SIZE=134144`
(phase8-W1 asked for >= 133,952), `CONFIG_RAM_TRACING_BUFFER_SIZE` 2048 to pay
for it (RAM 99.42 %). These are W8's to size properly; they are not the fix.
phase8-W8a's `3fb4cfb`, which landed while this ran, sizes its own image
(stop_mode_operator out, heap 102,400, `CONFIG_NROS_MAX_QUERYABLES=4`);
section 11.5 runs that image with only the W10 settings added.

### 11.2 On the pin (the 1533 fix in), a late join still fails

    {"seg": 0, "kind": "cold", ... "join_s": null, "out_rates": {"mrm_state": 0.0, "emergency_control_cmd": 18.37, "emergency_gear_cmd": 0.0, "emergency_hazard": 0.0, "emergency_turn": 0.0}, ... "rx_ring_high_water": 1024 ...}

3 of 3 joins (1 cold, 2 mid-run): four publishers never sent, the island took
every input. The board's counters 180 ms after boot:

    tick=180 rx_bytes=1733 rx_frames=3 rx_bad_frames=0 rx_partial=0 overruns=0 ring_overflows=602 ring_high_water=1024

`_z_rx_rejections` stayed 0: the reader did not die (1533 holds). It was not
running. An instrument in the RX ISR (`tools/ovf.py`) recorded the running
thread and the `zpico_read` thread's state at each overflow:

    139 ms running=main                         reader=zpico_read   state=0x80 pended_on=0 held=1024
    159 ms running=main                         reader=zpico_read   state=0x80 pended_on=0 held=1024
    188 ms running=<zephyr_thread_wrapper+0x0>  reader=zpico_read   state=0x80 pended_on=0 held=1024
    270 ms running=zpico_read                   reader=zpico_read   state=0x80 pended_on=0 held=1024

READY (0x80) and preempted: by main, which registers every entity at Zephyr's
default `CONFIG_MAIN_THREAD_PRIORITY` 0, and by the tx-flush thread
(`<zephyr_thread_wrapper>`), which has no stated priority and inherits
main's. The frames lost carry the router's answers to the publishers'
write-filter interests; a multi-threaded zenoh-pico write filter starts closed
(`src/net/filtering.c`, `WRITE_FILTER_ACTIVE`) and opens only on such an
answer, so those publishers stay silent for the life of the session.

Ablation, 3 joins each:

| image | result |
| --- | --- |
| pin | 3 of 3 fail (four outputs silent) |
| pin + interrupt-driven TX (zenoh-pico) | 3 of 3 fail; 1115 overflows by 152 ms |
| pin + `CONFIG_MAIN_THREAD_PRIORITY=5`, polled TX | 3 of 3 pass, 0 overflows, ring high water 12-824 |

So the busy-wait of section 1.3 was one way to hold the CPU, not the only one:
registration is CPU work too, and it ran above the reader.

### 11.3 The fix

- Island, `boards/mr_canhubk3_s32k344.conf`: `CONFIG_MAIN_THREAD_PRIORITY=5`,
  below the read task's 4. The tx-flush thread inherits it.
- Island: `CONFIG_NROS_ZENOH_SERIAL_RX_RING_BYTES`, 2048 in the gate of 11.4
  and 4096 on `3fb4cfb` (11.5), which has the RAM. With the priorities right
  the 1 KiB ring still reached 793-1024 at joins in the first gate round, one
  cold join in five overflowed it (46 drains) without losing an output, and a
  60 min soak later peaked at 1,226.
- nano-ros PR #1443: the flush task defaults to the read band on Zephyr
  (whatever main's priority), interrupt-driven TX (zenoh-pico `e28ff603`: the
  sender sleeps on a 256-byte ring the TX ISR drains; 9.5 % of the CPU was the
  busy-wait), UART framing / noise / parity counters.
- Island, `autoware_mrm_handler`: in the first gate round one cold join in five
  published `MRM_OPERATING / EMERGENCY_STOP` once, then NORMAL 40 ms later:

      [INFO] [1790656578.427406085] [w10_island_inputs]: mrm_state -> state=2 behavior=3 at t=20.593s wall=1790656578.427295
      [INFO] [1790656578.467710251] [w10_island_inputs]: mrm_state -> state=1 behavior=1 at t=20.633s wall=1790656578.467501

  The first tick had the availability and both operator statuses but not yet
  `/api/operation_mode/state`; UNKNOWN is "not available", so it called an
  emergency. `isDataReady()` now waits for the operation mode, for at most
  `timeout_operation_mode_availability` after the first availability sample;
  after that UNKNOWN is a fault again (a mode that never arrives is G4, W4's).

### 11.4 The gate on 55a65a4 (with the triage of 11.1)

Everything in 11.2 to 11.4, cap-1, cap-2 and the reaction ran BEFORE the
host's ROS upgrade (rmw_zenoh_cpp 0.1.9, rclcpp 16.0.19); 11.5 ran after it.

Image `img-final2` (sha256 `6fa23365...`, the fixes above, RX ring 2 KiB),
5 cold joins, the
first three followed by a mid-run reset, 10 min soak after every join. Per join
(`analyze.py`; `join` is from the end of `pyocd reset` to the host's first
`mrm_state`; the soak window starts 10 s after the join):

| run | join | join (s) | outputs at the host (/s) | false emergency | mrm_state gap > 0.3 s | RX ring overflows (boot to end) | in-run bad frames |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| g2-1 | cold | 0.141 | 10.0 / 18.0 / 10.0 / 10.0 / 10.0 | 0 | 0 | 0 | 0 |
| g2-1 | mid-run | 0.518 | 10.0 / 18.03 / 10.0 / 10.0 / 10.0 | 0 | 0 | 0 | 0 |
| g2-2 | cold | 0.235 | 10.0 / 18.0 / 10.0 / 10.0 / 10.0 | 0 | 0 | 0 | 0 |
| g2-2 | mid-run | 1.071 | 10.0 / 17.94 / 10.0 / 10.0 / 10.0 | 0 | 0 | 0 | 0 |
| g2-3 | cold | 0.247 | 10.0 / 18.08 / 10.0 / 10.0 / 10.0 | 0 | 0 | 0 | 1 |
| g2-3 | mid-run | 2.125 | 10.0 / 18.08 / 10.0 / 10.0 / 10.0 | 0 | 0 | 0 | 0 |
| g2-4 | cold | 0.263 | 10.0 / 18.13 / 10.0 / 10.0 / 10.0 | 0 | 0 | 0 | 0 |
| g2-5 | cold | 0.202 | 10.0 / 18.07 / 10.0 / 10.0 / 10.0 | 0 | 0 | 0 | 0 |

Outputs in the order mrm_state, emergency control_cmd, gear, hazard lights,
turn indicators (control_cmd at 18/s is the host's depth-1 view, section 6).
Every `mrm_states` list in the five SUMMARY lines is a single NORMAL entry.
Samples: over each ~585 s window the four 30 Hz inputs, availability and the
operation mode reached the island within one sample of what the host sent
(the host count is interpolated from its 1 s reports); the three downsampled
inputs lost 0-3 each to the gateway's 12 Hz limit, as in section 6.

The mid-run joins also count 1-3 bad frames and at most one framing error at
boot: the gateway was mid-frame toward the old instance when the board reset.

The one in-run bad frame (g2-3, cold, 422 s after boot) came with no overrun,
no RX ring overflow and no framing, noise or parity error, and no input count
fell short of what the host sent; its cause is not established. Two more soaks
of the same image with a capture of the last bad frame (`img-cap`, the gate
image plus a 1,520-byte RAM copy of any frame that fails to decode) ran 30 and
60 min after a late join and saw none:

    cap-1 "len_s": 1804.0, "join_s": 5.124, "join_after_reset_done_s": 4.677, "segment_totals_from_boot": {"ring_overflows": 0, "rx_bad_frames": 0, "overruns": 0, "rej": 0, "ring_high_water": 1014, "framing_errors": 0, "noise_errors": 0}
    cap-2 "len_s": 3603.7, "join_s": 0.705, "join_after_reset_done_s": 0.283, "segment_totals_from_boot": {"ring_overflows": 0, "rx_bad_frames": 0, "overruns": 0, "rej": 0, "ring_high_water": 1226, "framing_errors": 0, "noise_errors": 0}

(cap-1's inputs came up 4.9 s AFTER the reset -- rclpy on the loaded host --
so cap-1 is an island-first join and its 4.7 s is the publisher starting;
cap-2's came up 19.5 s before it.)

cap-2's ring high water, 1,226 bytes, is past the old 1 KiB ring. cap-2 also
logged two host-side `mrm_state` gaps of 0.300 and 0.333 s at 694-695 s
(NORMAL throughout; the host ran at load 40-47 during these runs, so which
side paused is not established).

Reaction after a late join (`tools/react.sh`, inputs first, availability
stopped 5 s after the new instance's first `mrm_state`), seen from the host:

    [INFO] [1790670141.603326068] [w10_island_inputs]: availability publisher STOPPED at t=24.403s mono=4657148.588206 wall=1790670141.603114
    [INFO] [1790670142.118648883] [w10_island_inputs]: mrm_state -> state=2 behavior=2 at t=24.918s wall=1790670142.118448
    "host_last_avail_to_operating_ms": 615.2

(section 1's figure at 921,600 with the island joining first: 644.4 ms). The
behavior is COMFORTABLE_STOP since W7's parameters, so no braking
`emergency/control_cmd` follows; the board-side trace was not captured (2 KiB).

### 11.5 The gate on 3fb4cfb (phase8-W8a's demo image), the one that counts

`3fb4cfb` plus only the W10 changes (main at priority 5, RX ring 4 KiB, the
handler's join grace), on the pin bec9aecb8 with zenoh-pico `e28ff603` and the
flush-task default of nano-ros PR #1443 (image `img-main`, sha256
`061b9261...`, RAM 85.64 %). The image publishes three outputs (mrm_state,
emergency control_cmd, hazard lights; W8a dropped gear and turn indicators).
`tools/gate_all.sh` with `gate_v2.sh`, which counts the 20 s of inputs from
the publisher's first report (every join below had them flowing 21.9-24.3 s
before the reset). All eight runs are AFTER the host's ROS upgrade of
2026-09-29 18:30-18:37 (rmw_zenoh_cpp 0.1.10, rclcpp 16.0.21), every router and
publisher started fresh:

| run | join | join (s) | outputs (/s) | false emergency | mrm_state gaps > 0.3 s | RX ring overflows, boot to end | in-run bad frames | ring high water | verdict |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| g4-1 | cold | 0.158 | 10.0 / 18.78 / 10.0 | 0 | 0 | 0 | 0 | 827 | ok |
| g4-1 | mid-run | 0.4 | 10.0 / 18.81 / 10.0 | 0 | 0 | 0 | 0 | 679 | ok |
| g4-2 | cold | 0.168 | 9.97 / 18.69 / 9.96 | 0 | 4 | 0 | 1 | 764 | ok |
| g4-2 | mid-run | 2.006 | 10.0 / 18.78 / 10.0 | 0 | 0 | 0 | 0 | 816 | ok |
| g4-3 | cold | 0.122 | 9.99 / 18.76 / 9.99 | 0 | 0 | 0 | 0 | 694 | ok |
| g4-3 | mid-run | 0.982 | 10.0 / 18.77 / 10.0 | 0 | 0 | 0 | 1 | 696 | ok |
| g4-4 | cold | 0.142 | 10.0 / 18.77 / 10.0 | 0 | 0 | 0 | 0 | 715 | ok |
| g4-5 | cold | 0.172 | 10.0 / 18.78 / 10.0 | 0 | 0 | 0 | 0 | 809 | ok |

Every SUMMARY's `mrm_states` is a single NORMAL entry. The four gaps in g4-2's
cold soak (0.412, 0.395, 0.366, 0.567 s) fall in seconds where the host's own
30 Hz publisher managed 5-12 samples (`gaps_with_host_publisher_stalled`): the
harness stalled on a host at load 30-47, not the island. No run shows a lease
expiry: the gateway opened exactly one board session per reset in every run.

Not zero: in-run bad frames, 1 in g4-2 (cold) and 1 in g4-3 (mid-run) here,
1 in g2-3 in 11.4, none in 90 min of cap-1/cap-2. Each came with no overrun, no
ring overflow and no framing, noise or parity error, and each 30 Hz count fell
1-2 short of the host's interpolated count in that window, so a frame of
samples was lost. The cause is not established (the capture image caught
none); the next step is the capture image on a longer soak with a socat tap
on the host side, to tell a frame the router sent damaged from one the wire
damaged. Before this unit's runs, g3-1 (cold and mid-run, both ok) ran on the
same image before the ROS upgrade; g3-2 was voided (the publisher came up 83 s
late, and at 18:17:08 the gateway closed its own session on a signal no W10
script sent) and g3-3 (the upgrade ran during its start).

### 11.6 Current main (c2e77dd: pin da272e419, discovery off, 60 s lease)

The same late-join test (inputs first, 1 cold join and 2 mid-run resets, 120 s
each, `gate_v2.sh`), on c2e77dd as it is and with this change:

| image | joins | outputs (mrm_state / control_cmd / hazard, /s) | RX ring, boot to end |
| --- | --- | --- | --- |
| c2e77dd (`img-stock-main`, main at 0, 1 KiB ring) | 3 of 3 fail | 0.0 / 18.37 / 0.0 in every join | 4,033 overflows 423 ms after the cold boot; 5,254-5,526 per join; high water 1024 |
| c2e77dd + this change (`img-main2`) | 3 of 3 pass, 0.45-1.23 s | 10.0 / 17.5-17.7 / 10.0 | 0 overflows; high water 120-179 |

So W4's discovery-off does not remove the failure: with the liveliness
subscriber gone the router still answers the write-filter interests while
main registers above the reader, and those answers are lost. It does shrink
what arrives at a join: with this change the ring peaks at 120-179 bytes
instead of 679-1226.

### 11.7 What changes with W4, W15 and the pin bump

nano-ros PR #1435 (W4, merged after this pin) compiles graph discovery out on
a serial link: no liveliness subscriber and no `@ros2_lv/**` interest from the
island, so the router's answers at a join shrink by that interest's share.
That lowers the ring's peak at a join; it does not change which thread runs
while the island registers, which was the fault. phase8-W14 has since moved the
island's pin to nano-ros da272e419, which has #1435 and #1567 but not #1443:
on that pin the tx-flush thread still has no stated priority (it inherits
main's 5 from this change) and TX is still the busy-wait, which the ablation
in 11.2 shows is not needed for the join; #1443 comes with the next pin bump.

phase8-W15 found that the island's lease (`CONFIG_NROS_ZENOH_LEASE_MS`, 10 s)
equals the gateway's keepalive period (keep_alive 6), so one late or lost
keepalive expires the session; its fix (60 s, in the serial snippet, and
nano-ros PR #1461) postdates these images. None of the runs here expired: the
gateway opened exactly one board session per reset in every run.
