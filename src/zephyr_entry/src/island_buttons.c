/*
 * The visitor's buttons on the board (docs/design/carla-island-demo.md,
 * section 3.4, unit C6; CONFIG_ISLAND_BUTTONS, off by default, on in the
 * booth image).
 *
 *   SW1 (DT alias sw0, PTD15, active high)   the driver takes over
 *   SW2 (DT alias sw1, PTA25, active high)   the HPC is lost (the encore)
 *
 * A demo affordance, not a safety function. The island does not act on a
 * press: it records it, with the handler's state at that tick, in
 * `island_button_record`, and the act on the host reads the record over SWD
 * (tools/board/board_buttons.py, through the same pyocd session that
 * re-arms the trace window) and does what the act's own button did before:
 * SW1 asks the vehicle for MANUAL (/control/control_mode_request), SW2
 * SIGSTOPs the availability gate. So the island's ROS interface, its
 * contract and its trace-marker table are those of the gate image; a press
 * reaches nothing on the island but this record.
 *
 * A press is ACCEPTED only when it means something at that tick:
 *   SW1  while the island's takeover request is on (the driver answers it);
 *   SW2  while the handler runs and the MRM state is NORMAL (an HPC loss
 *        during an MRM would start nothing new);
 * and IGNORED otherwise (recorded with the reason, the host does nothing).
 *
 * Read: once per MRM handler tick (MrmHandler::onTimer, 10 Hz, beside the
 * LED update), by the GPIO driver's port_get_raw directly, not
 * gpio_pin_get_dt(): Zephyr 4.4's CTF backend traces every GPIO API call
 * (28 B each; island_led.c), and a poll through the API would write 20
 * records a second into the 52 KiB trace buffer. Two port reads per tick, no
 * trace record, no ISR, no thread, no timer. Debounce: a level counts once
 * two consecutive ticks read it (a contact bounces for milliseconds; ticks
 * are 100 ms apart), so a press is seen 100-200 ms after it starts and must
 * last about 200 ms.
 *
 * Injection (the gate, with nobody at the board): a debugger writes N into
 * `inject[b]`; for the next N ticks the button reads pressed (OR'ed with the
 * pin) and the firmware counts the word down. Everything after the pin read
 * -- the debounce, the edge, the state check, the record -- is the path a
 * real press takes.
 */
#include <stdint.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>

#define ISLAND_BUTTON_MAGIC 0x534e5442u /* "BTNS" little-endian */
#define ISLAND_BUTTON_RING 8u

/* autoware_adapi_v1_msgs/MrmState.state */
#define MRM_NORMAL 1u

/* Why a press was ignored (code bits 16-19). */
#define WHY_ACCEPTED 0u
#define WHY_NOT_RUNNING 1u  /* the handler is still in INIT */
#define WHY_NO_TAKEOVER 2u  /* SW1 with no takeover request on */
#define WHY_NOT_NORMAL 3u   /* SW2 while an MRM runs or after it */

/* Layout read by tools/board/board_buttons.py; all 32-bit. */
struct island_button_press {
	uint32_t uptime_ms; /* the tick that saw the press */
	uint32_t code;      /* button (1 SW1, 2 SW2) << 24 | why << 16 | state << 8 | behavior */
};

struct island_button_record {
	uint32_t magic;       /* ISLAND_BUTTON_MAGIC once the pins are configured */
	uint32_t ticks;       /* island_buttons_update calls */
	uint32_t level;       /* this tick: bit b sampled (pin | inject), bit 8+b pin, bit 16+b inject */
	uint32_t debounced;   /* bit b: the button is down (two ticks agree) */
	uint32_t presses;     /* press edges, both buttons, all time; ring[presses % RING] is next */
	uint32_t accepted[2]; /* SW1, SW2 */
	uint32_t ignored[2];
	uint32_t inject[2];   /* written by a debugger: ticks to read the button as pressed */
	uint32_t gpio_errors; /* failed configure/read calls */
	struct island_button_press ring[ISLAND_BUTTON_RING];
};

volatile struct island_button_record island_button_record;

static const struct gpio_dt_spec btn[2] = {
	GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios),
	GPIO_DT_SPEC_GET(DT_ALIAS(sw1), gpios),
};
static uint32_t last_sample; /* bit b: the previous tick's sample */

static int pin_read(const struct gpio_dt_spec *spec)
{
	/* the driver's port read (gpio_nxp_siul2.c: PGPDI), not gpio_pin_get_dt():
	 * no CTF record per call (file header) */
	const struct gpio_driver_api *api = (const struct gpio_driver_api *)spec->port->api;
	gpio_port_value_t v = 0;

	if (api->port_get_raw(spec->port, &v) != 0) {
		island_button_record.gpio_errors++;
		return 0;
	}
	const int high = (v & BIT(spec->pin)) != 0U;

	return ((spec->dt_flags & GPIO_ACTIVE_LOW) != 0U) ? !high : high;
}

void island_buttons_update(uint32_t run, uint32_t state, uint32_t behavior, uint32_t takeover)
{
	if (island_button_record.magic != ISLAND_BUTTON_MAGIC) {
		return;
	}
	uint32_t level = 0U;
	uint32_t sample = 0U;

	for (uint32_t b = 0U; b < 2U; b++) {
		const uint32_t inj = island_button_record.inject[b];
		const int pin = pin_read(&btn[b]);

		if (inj != 0U) {
			island_button_record.inject[b] = inj - 1U;
			level |= BIT(16 + b);
		}
		if (pin) {
			level |= BIT(8 + b);
		}
		if (pin || inj != 0U) {
			sample |= BIT(b);
		}
	}
	level |= sample;
	island_button_record.ticks = island_button_record.ticks + 1U;
	island_button_record.level = level;

	/* two ticks agree -> the debounced level; a 0 -> 1 change is a press */
	const uint32_t stable = ~(sample ^ last_sample) & 3U;
	const uint32_t prev = island_button_record.debounced;
	const uint32_t now = (prev & ~stable) | (sample & stable);

	last_sample = sample;
	island_button_record.debounced = now;
	for (uint32_t b = 0U; b < 2U; b++) {
		if ((now & ~prev & BIT(b)) == 0U) {
			continue;
		}
		uint32_t why;

		if (!run) {
			why = WHY_NOT_RUNNING;
		} else if (b == 0U) {
			why = takeover ? WHY_ACCEPTED : WHY_NO_TAKEOVER;
		} else {
			why = (state == MRM_NORMAL) ? WHY_ACCEPTED : WHY_NOT_NORMAL;
		}
		const uint32_t n = island_button_record.presses;

		island_button_record.ring[n % ISLAND_BUTTON_RING].uptime_ms = k_uptime_get_32();
		island_button_record.ring[n % ISLAND_BUTTON_RING].code =
			((b + 1U) << 24) | (why << 16) | ((state & 0xffU) << 8) | (behavior & 0xffU);
		if (why == WHY_ACCEPTED) {
			island_button_record.accepted[b] = island_button_record.accepted[b] + 1U;
		} else {
			island_button_record.ignored[b] = island_button_record.ignored[b] + 1U;
		}
		/* the count last: a reader that sees it sees the entry */
		island_button_record.presses = n + 1U;
	}
}

static int island_buttons_init(void)
{
	for (size_t b = 0; b < ARRAY_SIZE(btn); b++) {
		if (!gpio_is_ready_dt(&btn[b]) || gpio_pin_configure_dt(&btn[b], GPIO_INPUT) != 0) {
			island_button_record.gpio_errors++;
		}
	}
	island_button_record.magic = ISLAND_BUTTON_MAGIC;
	return 0;
}
SYS_INIT(island_buttons_init, APPLICATION, 91);
