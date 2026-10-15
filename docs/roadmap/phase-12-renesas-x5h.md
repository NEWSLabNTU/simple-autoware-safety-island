# Phase 12 - the island on an R-Car's real-time cores, Autoware on its application cores

**Goal:** the ODD-exit and takeover demo on one Renesas SoC: the island
(nano-ros, Zephyr) on the Cortex-R52 cores, Autoware and play_launch in
containers on the application cores, with as much as possible built and
run before X5H hardware or its SDK is in hand.

**Status (2026-10-16): plan. Nothing here is implemented.** Findings:
`docs/design/renesas-rcar-platforms.md`.

## Why

The island today is a separate board (S32K344) on a UART to a PC. The
SoCs that target centralised vehicle compute put both on one chip:
lockstep Cortex-R52 cores for the safety functions, Cortex-A cores for the
stack. R-Car Gen5 (X5H) is one of them, and a planned Autoware reference
platform. Upstream Zephyr already supports the X5H's R52 on its evaluation
board, so the island's RTOS side needs no vendor SDK to build; running it
does (a virtual platform or the board), and that access is gated.

## Units

### X1. A nano-ros board package for the X5H's R52 (nano-ros, PR)

- What: a Zephyr board package for `rcar_ironhide_x5h/r8a78000/r52`.
  The board is newer than the Zephyr 4.4 nano-ros pins, so its files come
  downstream (as `fvp-aemv8r-smp` does with `west-downstream.yml`) until
  nano-ros moves to a Zephyr release that has them. Transport: zenoh-pico
  serial over an HSCIF UART first (the island's link today); the MFIS
  mailbox plus shared memory is X6.
- Gate: a nano-ros example and the island's image build and link for the
  board in CI; the board facts (RAM 2 MiB, console HSCIF1) recorded.

### X2. The island built for the X5H's R52 (this repo)

- What: a board conf and overlay for the Ironhide R52: the link on an
  HSCIF, the island's LEDs on led47-49, the trigger button on sw47, the
  heap and the stacks priced against 2 MiB. Build-only.
- Gate: `just board-build` for the board exits 0; the image's RAM and the
  board facts in `docs/board-facts.md`'s form.

### X3. The island on an emulated R52 (nano-ros, this repo)

- What: the same island logic on a model of the same core: QEMU's
  `mps3-an536` (dual R52; nano-ros runs FreeRTOS there) or the Arm FVP's
  AArch32 AEMv8-R configuration under Zephyr, whichever boots the island
  image with a network or serial path to the host first. Against the
  planning simulator on the host: the three acts.
- Gate: acts a, b and encore PASS with the island emulated; timing rows
  reported but not judged (no timing fidelity).

### X4. The host side on AutoSD (this repo, play_launch)

- What: AutoSD in a VM (x86_64 and aarch64 images run in QEMU): Autoware
  (an Open AD Kit-style container, the planning simulator's subset) in the
  QM partition, launched by play_launch with its scheduling, on AutoSD's
  kernel; the island on the S32K344 as today. Record what play_launch's
  capability helper and cgroup handling need on an image-based OS, and
  what a quadlet-generating mode would carry.
- Gate: the three acts PASS against AutoSD's host; the gaps found listed
  as play_launch issues.

### X5. Access to the X5H (no code)

- What: request the RoX SDK with its virtual platform (RFS2) and, later,
  an Ironhide board, through Renesas or a partner that holds them. What
  to ask for: RFS2 with the R52 cluster modelled; the R52's memory map,
  boot and load procedure (ROM Writer, or loading from the A720AE side);
  the inter-processor interfaces (MFIS, shared memory regions) and their
  Linux-side drivers; the HSCIF and GPIO routing on Ironhide; the Linux
  BSP or AutoSD enablement for the A720AE.
- Gate: access granted, or the answer recorded.

### X6. On the X5H, virtual then real (nano-ros, this repo)

- What: X2's image on RFS2, then on the board. The island and the host
  on one SoC: the link on an HSCIF loop or the MFIS mailbox with shared
  memory (a nano-ros transport, if the serial one is not enough); the
  host side as X4 on the A720AE. The shared clock lets a runtime monitor
  check the host-to-island hop (phase 10 deferred it for want of one).
- Gate: the three acts PASS on RFS2, then on silicon, with the contract's
  rows.

### X7. Optional: R-Car S4 Spider (Gen4, on sale)

- What: if an X5H stays out of reach, the same split on the S4: AutoSD
  supports it, Zephyr supports its R52 (in 4.4). Autoware's
  planning/control subset only (A55 cores).
- Gate: as X6, on the S4.

## Order

X1 and X3 first (no hardware, no SDK). X2 after X1. X4 in parallel. X5
now, as it takes the longest. X6 after X5. X7 only if X5 stalls.

## Not in this phase

- A FreeRTOS island on the X5H. Zephyr has the board upstream and the
  island is Zephyr; FreeRTOS on an R52 is covered by nano-ros's S32Z270
  bundle, should a partner require it.
- Perception on Renesas accelerators.
- Safety certification (RHIVOS, ASIL claims).
