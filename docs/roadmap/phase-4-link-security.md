# Phase 4 — what protects the island's link

**Goal:** decide what, if anything, authenticates and protects the safety
island's network link before the board is attached to anything that is not an
isolated bench network.

**Status (2026-08-21): open question, no decision made.** This document exists
because phase 3 bring-up forced a weak random number generator into the image,
and working out how much that mattered surfaced a larger question that has never
been answered anywhere in this project.

Nothing here is a plan to implement cryptography. It is a decision gate, and the
decision is not ours alone to make.

---

## 1. How this came up

The phase-3 image would not link. Six undefined references to
`z_impl_sys_rand_get`: `CONFIG_ENTROPY_GENERATOR=y` enables the entropy *driver
class*, but the S32K344 has no entropy node in Zephyr 4.4, so
`ENTROPY_HAS_DRIVER` is unset, so both `ENTROPY_DEVICE_RANDOM_GENERATOR` and
`XOSHIRO_RANDOM_GENERATOR` are unselectable and nothing implements
`sys_rand_get()`.

The only selectable backend is `TEST_RANDOM_GENERATOR` → `TIMER_RANDOM_GENERATOR`.
Zephyr names it "TEST" deliberately: its output is predictable. That is what the
image currently ships, recorded in
`src/zephyr_entry/boards/mr_canhubk3_s32k344.conf`.

The first instinct was "this needs a real entropy source before the vehicle."
That instinct was aimed at the wrong layer, and the rest of this document is why.

## 2. What the weak RNG actually threatens

Measured against the built image, not assumed:

```
CONFIG_MBEDTLS is not set
CONFIG_NET_SOCKETS_SOCKOPT_TLS is not set
mbedtls symbols in zephyr.elf: 0   (CONFIG_MBEDTLS_VERSION_4_x and
                                    CONFIG_ZEPHYR_MBEDTLS_MODULE are absolute
                                    Kconfig markers, not code)
```

**Nothing in this image derives key material.** The consumers of `sys_rand_get()`
are:

- TCP initial sequence numbers, and `CONFIG_NET_TCP_RANDOMIZED_RTO`
- zenoh's session id

So the exposure from a predictable PRNG is off-path TCP sequence guessing —
connection injection or reset by an attacker who can already reach the network.

## 3. Why that is not the interesting risk

The island speaks zenoh over **plain, unauthenticated TCP**
(`CONFIG_NROS_ZENOH_LINK_TCP=y`, no TLS anywhere in the image). An attacker who
can reach that network does not need to guess a sequence number. They can open
their own session and publish `/mrm/*` traffic directly.

That reframes the problem. Hardening the RNG while the transport is
unauthenticated plaintext is fixing the lock on a door with no wall attached.
The RNG is not the weakest link; the transport is.

The right question is not *"how do we get real entropy?"* It is:

> **What authenticates this link, and what is the consequence if an attacker on
> the same network can publish MRM commands?**

For a node whose entire purpose is to command a minimum-risk manoeuvre — to stop
the vehicle — that consequence is worth stating explicitly rather than leaving
implied.

## 4. What real entropy would cost, if the answer requires it

Researched 2026-08-21; recorded so this does not have to be rediscovered.

**The hardware exists.** The S32K344 carries **HSE_B** (Hardware Security
Engine). Note it is *not* CSEc — that is the S32K1 generation.

**It is behind two walls.**

1. HSE requires an NXP-supplied **encrypted firmware binary** provisioned into
   the part before any service works (0.2.55 for S32K344 at time of writing, with
   a matching SBAF version; procedure in AN744810). It is distributed through
   NXP's Secure Files area — account and NDA gated — and provisioning touches the
   device security lifecycle, which is not a casually reversible operation.
2. Raw TRNG output is **never exposed** on S32K. The TRNG only seeds a
   SHE-specification PRNG; software reads pseudo-random output via `CMD_RND`.
   Standards-wise this is respectable — TRNG at AIS31 PTG.2 / SP800-90B, PRNG at
   DRG.2 — but it is not a raw entropy source, and a Zephyr entropy driver would
   be wrapping a PRNG.

**Zephyr does not support it.** The MR-CANHUBK3 board documentation lists no
entropy, TRNG, RNG or crypto support at all — the only security-adjacent entry is
the FS26 SBC watchdog, which is functional safety, not security. There is no
entropy node in `dts/arm/nxp/s32/nxp_s32k344_m7.dtsi`. Zephyr does ship
`drivers/crypto/crypto_nxp_s32_hse.c`, but it is `compatible =
"nxp,s32-crypto-hse-mu"`, implements cipher and hash only with **no RNG
service**, and its MU node exists only for S32Z27x.

So "add an entropy driver" is three jobs:

| | work | friction |
| --- | --- | --- |
| 1 | provision HSE firmware into the part | gated download, security lifecycle |
| 2 | add an S32K3 HSE MU devicetree node | upstream Zephyr change |
| 3 | write an entropy driver for the HSE RNG service | new driver; the existing one has no RNG |

**Alternative:** an external TRNG over SPI or I2C (the board has both). Adds BOM
and a board modification, but sidesteps the HSE firmware gate entirely.

## 5. The decision gate

These are ordered. The later ones are only worth doing if the earlier answer
demands them.

**Gate A — what is the threat model?** Is the island's network physically
isolated and access-controlled, or does it share a segment with anything an
attacker could reach? Until this is answered the rest is speculation.

**Gate B — what authenticates the link?** Options, roughly:

- *Nothing; rely on network and physical isolation.* Defensible for a closed
  vehicle network with controlled physical access. Then the timer RNG is well
  down the list of concerns and phase 3's current state is adequate.
- *zenoh access control / shared-key authentication.* Needs key material →
  needs real entropy → gate C becomes mandatory.
- *TLS/DTLS on the link.* Same conclusion, plus mbedTLS in an image that
  currently has 58 KiB of SRAM headroom. Worth sizing before committing.

**Gate C — entropy, only if B requires key material.** Then section 4's three
jobs, or an external TRNG, become required work rather than optional hardening.

## 6. What is true today

- The image ships a **non-cryptographic, timer-seeded PRNG**. This is recorded
  in the board conf with the reasoning, so it cannot quietly become permanent.
- No key material derives from it.
- The link is unauthenticated plaintext zenoh over TCP.
- The demo runs on an isolated lab network (ROS domain 10).

**That combination is acceptable for bench bring-up and nothing else.** The
constraint is not the RNG — it is the isolation of the network the board is
plugged into.

## 7. Open

- [ ] Gate A — threat model, from whoever owns the vehicle network architecture
- [ ] Gate B — link authentication decision
- [ ] Gate C — entropy work, conditional on B
- [ ] Size mbedTLS against the remaining SRAM headroom, if B goes that way

---

## Appendix — sources

- NXP community, [True Random Number Generator (TRNG): entropy source](https://community.nxp.com/t5/S32K/True-Random-Number-Generator-TRNG-Entropy-source/td-p/1721151)
  — TRNG is internal only, seeds the SHE PRNG, `CMD_RND` is the software interface
- NXP community, [HSE firmware installation](https://community.nxp.com/t5/S32K/HSE-firmware-installation/m-p/1808863)
  and [programming S32K344 with the HSE firmware binary](https://community.nxp.com/t5/S32K/How-to-Program-NXP-S32K344-MCU-with-HSE-Firmware-Binary-Which/m-p/2061212)
  — encrypted binary, version pairing with SBAF, AN744810, Secure Files distribution
- Zephyr, [MR-CANHUBK3 board documentation](https://docs.zephyrproject.org/latest/boards/nxp/mr_canhubk3/doc/index.html)
  — supported-features table lists no entropy or crypto
- Zephyr, [drivers/entropy/Kconfig](https://github.com/zephyrproject-rtos/zephyr/blob/main/drivers/entropy/Kconfig)
- In-tree, `zephyr/subsys/random/Kconfig` — `ENTROPY_DEVICE_RANDOM_GENERATOR` and
  `XOSHIRO_RANDOM_GENERATOR` both `depends on ENTROPY_HAS_DRIVER`
- In-tree, `zephyr/drivers/crypto/crypto_nxp_s32_hse.c` — cipher/hash only, S32Z MU
