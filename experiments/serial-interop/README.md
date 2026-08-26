# zenoh-over-serial: board ↔ host ROS 2 (in progress)

Bringing the MR-CANHUBK344 up against a host `rmw_zenohd` over the DCD-LZ UART,
because the T1 Ethernet link needs a media converter we do not have.

## Reproduce

    W=~/repos/nano-ros-workspace-4.4
    export NANO_ROS_ROOT=<repo>/third-party/nano-ros nano_ros_ROOT=$NANO_ROS_ROOT
    export PATH=$W/.venv312/bin:$NANO_ROS_ROOT/packages/cli/target/release:$HOME/.local/bin:$PATH
    west build -b mr_canhubk3/s32k344 -S nros-zenoh -d build-talker \
      $NANO_ROS_ROOT/examples/zephyr/c/talker \
      -- -Dnano_ros_ROOT=$NANO_ROS_ROOT \
         -DZEPHYR_EXTRA_MODULES=$W/modules/debug/segger -DNROS_ZENOH_DEBUG=3 \
         -DEXTRA_CONF_FILE="talker-serial.conf;rtt.conf" \
         -DEXTRA_DTC_OVERLAY_FILE=talker-serial.overlay
    west flash -d build-talker -r pyocd

Host side — the router LISTENS on the serial line and bridges to TCP:

    ZENOH_CONFIG_OVERRIDE='listen/endpoints=["serial//dev/ttyUSB0#baudrate=115200","tcp/[::]:7447"]' \
      ros2 run rmw_zenoh_cpp rmw_zenohd

## Reading the board

zenoh owns the only wired UART, so the console moves to unwired lpuart0 and the
log goes out over RTT on the existing SWD link:

    pyocd rtt -t s32k344 -a $(arm-none-eabi-nm zephyr.elf | awk '$3=="_SEGGER_RTT"{print "0x"$1}')

Four things this needs and none are discoverable from the errors: the SEGGER
module is absent from this workspace (clone zephyrproject-rtos/segger into
modules/debug/segger), west does not register it (-DZEPHYR_EXTRA_MODULES),
`pyocd rtt` needs a TTY (run it under `script -qec`), and it needs the control
block address (-a). The default 1 KiB up-buffer also wraps before a post-hoc
reader attaches; CONFIG_SEGGER_RTT_BUFFER_SIZE_UP=16384.

## What works

The board completes the whole zenoh handshake and reaches ROS discovery:

    _z_connect_serial: connected
    Sending Z_INIT(Syn) -> Received Z_INIT(Ack)
    Sending Z_OPEN(Syn) -> Received Z_OPEN(Ack)
    _z_liveliness_register_token (@ros2_lv/.../node)
    _z_liveliness_register_token (@ros2_lv/.../talker)
    _z_liveliness_register_token (@ros2_lv/0/.../3/MP/%/%/talker/%chatter/...)
    Publishing: 'Hello World: 40'

and the router accepts the link:

    zenoh_transport::unicast::manager: New transport opened between ...
    zenoh_transport::unicast::establishment::accept: New transport link accepted

## E2E ACHIEVED — once, with real data, not yet reliably

Standard ROS 2 tooling on the host, over UART, against nano-ros on the S32K344:

    $ ros2 node list
    /talker

    $ ros2 topic info /chatter
    Type: std_msgs/msg/String
    Publisher count: 1
    Subscription count: 0

    $ ros2 topic echo /chatter --qos-reliability best_effort --once
    data: 'Hello World: 74'
    ---

**The last blocker was a domain mismatch, and it is invisible at the transport
layer.** The board defaulted to `CONFIG_NROS_DOMAIN_ID=0` while this project runs
on 10. The domain is the FIRST element of every key rmw_zenoh builds --
`@ros2_lv/<domain>/...` and `<domain>/chatter/...` -- so with a mismatch the
session opens, the board publishes, the router forwards, and `ros2 topic list`
simply never matches. Nothing anywhere reports an error. Both sides must agree;
the conf now pins 10.

## Still flaky — the open item

That result has not reproduced: 0/5 subsequent runs showed the node, while the
board side is provably healthy every time. RTT shows the full handshake
(Z_INIT/Z_OPEN both ways), liveliness tokens registered on the right domain
(`@ros2_lv/10/...`), and continuous publishing; the router logs
`New transport opened` and never logs a close or a lease expiry.

So transport and both endpoints are fine and DISCOVERY is what does not
propagate. That is the next thing to chase, and it is a different layer from
everything solved so far.

One measurement trap to avoid repeating: `grep -c "transport opened"` on the
router log is meaningless unless `RUST_LOG=zenoh_transport=debug` is set --
without it the router logs nothing at that level and the count is always 0,
which reads as "the board never connected".

## What does not

(superseded -- see above.)

## Sizing, all of it measured the hard way

  - z_malloc on Zephyr is k_malloc (zenoh-pico src/system/zephyr/system.c), so
    zenoh's buffers come from CONFIG_HEAP_MEM_POOL_SIZE, NOT the libc malloc
    arena. Serial send and receive each take 1507+1516 B and can be live at
    once. Sizing the arena instead does nothing; cutting the kernel heap to 4 KiB
    made every send fail from boot.
  - MAIN_STACK_SIZE=4096 overflows in the declare path (_z_declare_resource
    alone reserves 340 B). It presents as a USAGE FAULT with a garbage PC and
    "Illegal use of the EPSR", NOT as a stack error. CONFIG_MPU_STACK_GUARD=y
    turns it into "ZEPHYR FATAL ERROR 2: Stack overflow" -- worth enabling to
    diagnose, but its per-stack reservation does not fit this image, so leave it
    off and size the stack instead. 8192 works.
  - NROS_MAX_LARGE_SUBSCRIBERS=0 is worth ~60 KiB on a talker.

## Open bug: CONFIG_NROS_DOMAIN_ID is applied inconsistently

The listener example, built with `CONFIG_NROS_DOMAIN_ID=10` (confirmed present in
the build's `autoconf.h`), registers its entities across TWO domains:

    @ros2_lv/10/d1cd18cb.../0/0/NN/%/%/node                    <- domain 10
    Allocating sub decl for (0/chatter/std_msgs::msg::dds_::String_/*)   <- domain 0
    @ros2_lv/0/d1cd18cb.../0/0/NN/%/%/listener                 <- domain 0
    @ros2_lv/0/d1cd18cb.../0/3/MS/%/%/listener/%chatter/...    <- domain 0

Counted over the whole trace: 1x `@ros2_lv/10`, 2x `@ros2_lv/0`, subscription key
on `0/`. The talker in the same configuration is consistent -- 3x `@ros2_lv/10`
and its interest on `10/` -- and the talker is the one that produced a working
`ros2 topic echo`.

So the domain reaches one code path and not the others. Since the domain is the
first element of every key rmw_zenoh matches on, a split like this cannot be seen
at the transport layer: the session opens, entities register, nothing errors, and
discovery simply never matches.

This is the strongest candidate for the E2E flakiness recorded above -- a run
matches only when the entities that matter happen to land on the same domain.
Worth filing against nano-ros and fixing before any further entity-kind bring-up;
testing services on top of a broken domain plumbing would only produce more
unexplained flakiness.

Reproduce: build either example with `-DNROS_ZENOH_DEBUG=3`, read RTT, and
`grep -oE '@ros2_lv/[0-9]+' | sort | uniq -c`.

## E2E flakiness: measured, NOT fixed (2026-08-26)

Issue 0801 (entities on the wrong ROS domain) was a real cause and is fixed --
the listener now receives from the host, which had never worked. It was not the
only cause: the talker still shows the node in roughly 1 run in 3.

What instrumentation established, by counting connect attempts in a static read
over SWD:

    g_dbg_connect_calls   = 1     (connect entered once)
    g_dbg_connect_retries = 9     (EVERY run, deterministically)

Nine of ten allowed attempts fail before the handshake completes, so a connect
that should take ~25 ms takes ~11 s. Each failed attempt sends a fresh INIT, the
router accepts a new link, and 1-2 transports open per boot with the earlier one
expiring 10 s later -- churn that discovery lands on the wrong side of.

The asymmetry is the useful part: the router logs `New transport opened` every
run, so board -> router works. The board times out waiting for the reply nine
times, so router -> board is what fails. Reads DO eventually work (the traces
show `Received Z_INIT(Ack)` and a completed handshake), so it is not a dead path
-- it is unreliable.

Ruled out along the way:

  - RX FIFO disabled. It is enabled: LPUART2 FIFO reads 0x00c00099 (RXFE and
    TXFE set), WATER 0. The FIFO is only 4 bytes deep though, against a ~9-byte
    frame.
  - `k_yield()` inside the byte loop overrunning that 4-byte FIFO mid-frame.
    Restricting the yield to between frames changed the retry count not at all
    (still exactly 9) and made node discovery worse, so it was reverted rather
    than kept on a plausible story.

Next: instrument the READ rather than the retry -- count bytes received per
attempt and whether `_z_serial_msg_deserialize` fails or the wait simply expires
with nothing arriving. Those are different bugs (corruption vs. never delivered)
and the retry counter cannot tell them apart.
