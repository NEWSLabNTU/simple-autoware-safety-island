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
  kinematic_state / control_mode / gear_cmd, the liveliness ACL, and a
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
- **Not solved: joining under load.** When the host is already publishing the
  inputs as the island joins, the registration burst starves the read task
  again: the board published `mrm_state` 46 times and the host received none.
  Until issue 1534 is fixed, the island must join before the inputs flow
  (the soak and the reaction above did).

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
2. Downsampling, serial egress, `put`: kinematic_state, control_mode and
   gear_cmd limited to 12 Hz. A limit AT the source rate drops samples to
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

## 7. Joining under load (react2, soak1): not solved

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

- nano-ros issue 1533: push fork branch `fix/serial-reader-survives-declare-errors`
  (`52f60b79`; it sits in the zenoh-pico submodule of the nano-ros worktree
  `.claude/worktrees/phase8-w2-serial`), move the zenoh-pico pin, rebuild the
  island. It adds
  `_z_zephyr_serial_stats` (overruns, ring overflows and high water, bad
  frames, TX busy cycles) and `_z_rx_rejections`, which would have made
  sections 1 and 6 two SWD reads.
- nano-ros issue 1534: the tx-flush task outranks the read task; section 7.
  Interrupt-driven TX would also return the 9.5 % busy-wait.
- `CONFIG_NROS_ZENOH_SERIAL_RX_RING_BYTES` (nano-ros PR #1386): the board has 2,016 B
  of SRAM free with the 24 KiB trace buffer, so a larger ring costs trace.
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
- The contract's `min_rate_hz: 30` on `emergency_control_cmd` is met on the
  board (29.3/s on the wire); the host's depth-1 view is 17.9/s.
