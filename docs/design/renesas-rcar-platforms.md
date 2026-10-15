# Renesas R-Car as the island's target: what is public, what is gated

Survey of 2026-10-16. Question: can the island (nano-ros on an RTOS) and
the host side (Autoware, play_launch) run on one Renesas R-Car SoC, and run
the ODD-exit and takeover demo there? Facts are from public pages, linked;
"not found" means a search did not find it, not that it does not exist.

## The two sides of one chip

| | R-Car S4 (Gen4) | R-Car X5H (Gen5) |
|---|---|---|
| application cores | Cortex-A55 | 32 Cortex-A720AE ([R&D World](https://www.rdworldonline.com/renesas-starts-sampling-3nm-r-car-x5h-gen-5-automotive-soc-previews-ces-2026-multi-domain-demos/)) |
| real-time cores | Cortex-R52 | 6 Cortex-R52, dual lockstep, ASIL D |
| board | Spider | Ironhide (evaluation board) |
| availability | on sale | sampling to selected customers and partners, with the RoX Whitebox SDK ([Renesas](https://www.renesas.com/en/about/newsroom/renesas-fast-tracks-sdv-innovation-r-car-gen-5-soc-based-end-end-multi-domain-solution-platform)) |
| Autoware | no public port | Renesas joined the Autoware Foundation; TIER IV plans R-Car Gen5 as a primary Autoware reference platform ([press release](https://www.plantautomation-technology.com/pressreleases/tier-iv-collaborates-with-renesas-to-build-an-open)) |

The island maps onto the real-time cores and Autoware onto the
application cores: the architecture this repository runs on two boards
(the host PC and the S32K344) becomes one SoC.

## The island side (R52)

- **Zephyr, upstream.**
  - `rcar_ironhide_x5h/r8a78000/r52`
    ([Zephyr](https://docs.zephyrproject.org/latest/boards/renesas/rcar_ironhide_x5h/doc/index.html)):
    GICv3 and the architected timer, SCIF/HSCIF UARTs (console HSCIF1,
    1,843,200 baud), GPIO with LEDs led47-49 and button sw47, CAN-FD, the
    MFIS mailbox, SCMI; 2 MiB RAM. Not listed: Ethernet, remoteproc. JTAG
    not usable yet; images are flashed as `.srec` with Renesas's ROM
    Writer. The board is newer than Zephyr 4.4, which nano-ros uses (its
    4.4 tree has only rcar_h3ulcb, salvator_x(s) and spider_s4).
  - `rcar_spider_s4/r8a779f0/r52`
    ([Zephyr](https://docs.zephyrproject.org/latest/boards/renesas/rcar_spider_s4/doc/rcar_spider_r52.html)):
    UART, GPIO, I2C, PWM; no Ethernet. In Zephyr 4.4.
- **FreeRTOS.** The 2024 RoX announcement lists FreeRTOS and Zephyr among
  the package's royalty-free software
  ([BusinessWire](https://www.businesswire.com/news/home/20240620639535/en/Renesas-R-Car-Open-Access-Platform-Accelerates-Software-Defined-Vehicle-Development-With-Market-Ready-Software));
  no public FreeRTOS port for the X5H's R52 was found. nano-ros has a
  FreeRTOS board bundle for another R52 SoC, the NXP S32Z270 (vendor
  drivers linked from outside the tree through weak hooks, the vendor's
  GIC port), and `mps3-an536-freertos` (QEMU, dual R52).
- **Emulation.** Neither Arm FVP nor QEMU models R-Car peripherals: an
  image linked for the X5H's memory map does not boot there. They run the
  same core and ISA (Armv8-R AArch32), so the FreeRTOS or Zephyr port, the
  MPU set-up, the executor and the island logic can be exercised there,
  without timing fidelity. nano-ros's FVP support is Zephyr on the AArch64
  AEMv8-R model, build-only in CI.

## The host side (application cores)

- **AutoSD** (CentOS Automotive SIG; the public preview of Red Hat
  In-Vehicle OS). Hardware list includes the R-Car S4, not the X5H
  ([provisioning](https://sig.centos.org/automotive/latest/provisioning/index.html)).
  Workloads are containers (systemd quadlets); a QM partition separates
  non-safety containers from ASIL ones
  ([QM partition](https://sig.centos.org/automotive/building/deploying_apps_in_qm_partition)).
  AutoSD is not ISO 26262 certified; RHIVOS is certified as a SEooC for
  ASIL B on its listed hardware and uses PREEMPT_RT
  ([datasheet](https://www.redhat.com/en/resources/in-vehicle-operating-system-datasheet)).
  Red Hat is listed among the RoX SDK's partners. Autoware's Open AD Kit
  already ships Autoware as containers, which is what AutoSD runs.
- **Yocto.** meta-ros provides ROS 2 Humble on Scarthgap (LTS)
  ([meta-ros](https://index.ros.org/r/meta-ros/)); only Autoware's
  message and utility packages have recipes, no full stack. With Autoware
  and play_launch in a container, the image needs a container runtime, not
  Autoware recipes. Renesas's BSPs are Yocto-based.
- **Real-time.** PREEMPT_RT is in mainline Linux since 6.12; AutoSD's and
  Yocto's kernels can carry it. play_launch already applies SCHED_FIFO/RR,
  SCHED_DEADLINE, CPU affinity, utilisation clamps and cgroups per
  container, with priorities derived from the contract
  (play_launch `docs/guide/rt-scheduling.md`); on a PREEMPT_RT kernel these
  become bounded. Not there yet: generating quadlet units with their
  scheduling and the ASIL/QM placement from the contract, and checking
  that play_launch's capability helper works on an image-based OS.

## Pre-silicon X5H

- **Renesas RoX Virtual Platform (RFS2):** ships inside the RoX SDK;
  Renesas states more than 1/2 of real CPU speed
  ([RoX VP](https://www.renesas.com/en/software-tool/rox-virtual-platform)).
- **Synopsys VDK for R-Car Gen5:** a commercial license, more than 1/17 of
  real speed ([Synopsys](https://synopsys.com/blogs/chip-design/driving-the-future-renesas-r-car-gen-5-virtual-prototypes-enable-sdvs.html));
  eSOL runs its RTOS on the X5H virtual platform this way
  ([eSOL](https://esol.com/news/news_192.html)).
- No public download, trial or academic programme for either was found.
  Access goes through Renesas (sales/FAE) or a partner that holds the SDK.

## What runs the demo, by step

| step | host side | island side | link | needs |
|---|---|---|---|---|
| today | x86, Ubuntu, CARLA | S32K344 (Cortex-M7), Zephyr | UART | - |
| emulated R52 | x86 | R52 in QEMU (an536) or FVP | emulated UART or network | nothing |
| R-Car S4 | A55, AutoSD, Autoware's planning/control subset in a QM container; perception and CARLA on a PC | S4 R52, Zephyr | on-chip UART or shared memory | a Spider board |
| X5H, virtual | A720AE, the SDK's Linux or AutoSD | X5H R52, Zephyr (upstream board) | HSCIF or MFIS mailbox + shared memory | the RoX SDK (RFS2) |
| X5H | as above, on silicon | as above | as above | an Ironhide board |

On one SoC the island and the host share a clock: the runtime check of a
host-to-island hop, deferred in phase 10 for want of one, becomes possible.
