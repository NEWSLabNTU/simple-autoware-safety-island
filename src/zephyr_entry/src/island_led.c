/*
 * The island's MRM state on the board's LEDs (docs/design/carla-island-demo.md,
 * section 3; CONFIG_ISLAND_LED, off by default).
 *
 * The user RGB LED (DT aliases led0/led1/led2: red PTE14, green PTA27, blue
 * PTE12, gpio-leds, active low) shows the handler's state; CAN LED0 (PTC18)
 * is a heartbeat. Both are driven from the MRM handler's own 10 Hz tick
 * (MrmHandler::onTimer -> island_led_update), so no thread, timer or ISR is
 * added, and a handler that stops ticking freezes the heartbeat: a dark or
 * steady CAN LED0 is itself the "island stuck" indication.
 *
 *   before the first tick        blue steady          (boot, SYS_INIT)
 *   INIT (waiting for inputs)    blue blinking 1 Hz
 *   NORMAL                       green steady
 *   NORMAL, takeover requested   amber (R+G) blinking 2.5 Hz
 *   COMFORTABLE_STOP operating   amber steady
 *   EMERGENCY_STOP operating     red blinking 2.5 Hz
 *   MRM_SUCCEEDED                red steady
 *   MRM_FAILED                   magenta (R+B) blinking 2.5 Hz
 *   heartbeat (CAN LED0)         toggles every 5 ticks (1 Hz blink at 10 Hz)
 *
 * The pin writes are SIUL2 PGPDO read-modify-writes (gpio_nxp_siul2.c) on the
 * spin thread, made only when a pin's level changes (at most 7 a second, in a
 * blinking state) and kept out of the CTF trace (see led_set()). No other
 * code drives these ports' output bits: the LPUART pins are pinctrl-muxed,
 * and the pwm-leds node (eMIOS) for the same LED is not enabled in this
 * image.
 *
 * `island_led_record` keeps what was shown, for the SWD readout
 * (tools/timeline/led_readout.py): the current pattern and the last
 * ISLAND_LED_RING transitions with their uptime. Cost: the 88 B record and a
 * 4 B level cache in .bss (DTCM), ~1.3 KB of flash.
 */
#include <stdint.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>

#define ISLAND_LED_MAGIC 0x5344454cu /* "LEDS" little-endian */
#define ISLAND_LED_RING 8u

/* Pattern bits, as recorded and as shown. */
#define LED_R BIT(0)
#define LED_G BIT(1)
#define LED_B BIT(2)
#define LED_BLINK BIT(3)

/* autoware_adapi_v1_msgs/MrmState values (state, behavior). */
#define MRM_NORMAL 1u
#define MRM_OPERATING 2u
#define MRM_SUCCEEDED 3u
#define MRM_FAILED 4u
#define MRM_BEH_COMFORTABLE 3u
#define MRM_BEH_EMERGENCY 2u

/* Layout read by tools/timeline/led_readout.py; all 32-bit. */
struct island_led_transition {
	uint32_t uptime_ms;
	uint32_t code; /* state << 24 | behavior << 16 | takeover << 8 | pattern */
};

struct island_led_record {
	uint32_t magic;        /* ISLAND_LED_MAGIC once the LEDs are configured */
	uint32_t pattern;      /* LED_* bits currently selected */
	uint32_t code;         /* the code of the current pattern */
	uint32_t ticks;        /* island_led_update calls */
	uint32_t transitions;  /* pattern changes, all time */
	uint32_t gpio_errors;  /* failed configure/set calls */
	struct island_led_transition ring[ISLAND_LED_RING]; /* [transitions % RING] is next */
};

volatile struct island_led_record island_led_record;

static const struct gpio_dt_spec led_r = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static const struct gpio_dt_spec led_g = GPIO_DT_SPEC_GET(DT_ALIAS(led1), gpios);
static const struct gpio_dt_spec led_b = GPIO_DT_SPEC_GET(DT_ALIAS(led2), gpios);
static const struct gpio_dt_spec led_hb = GPIO_DT_SPEC_GET(DT_NODELABEL(can_led0), gpios);

/*
 * Pin writes go to the driver's port_set/clear_bits_raw directly, not through
 * gpio_pin_set_dt(): Zephyr 4.4's CTF backend emits gpio_* trace events for
 * every GPIO API call whatever CONFIG_TRACING_GPIO says (ctf_top.c defines the
 * hooks unconditionally), 28 B per call. Measured on the board with
 * gpio_pin_set_dt() on every tick: 2,781 gpio set/clear events in 34 s filled the 52 KiB
 * RAM trace buffer before the act (run led-e2; the image without LEDs used
 * 20,752 B for the same act). So the trace sees none of these writes, and a
 * pin is written only when its level changes.
 */
static uint32_t led_level; /* bit i: led i is lit, as last written */

static void led_set(const struct gpio_dt_spec *spec, uint32_t bit, int on)
{
	const uint32_t want = on ? bit : 0U;

	if ((led_level & bit) == want) {
		return;
	}
	const struct gpio_driver_api *api = (const struct gpio_driver_api *)spec->port->api;
	const int high = ((spec->dt_flags & GPIO_ACTIVE_LOW) != 0U) ? !on : on;
	const int rc = high ? api->port_set_bits_raw(spec->port, BIT(spec->pin))
			    : api->port_clear_bits_raw(spec->port, BIT(spec->pin));

	if (rc != 0) {
		island_led_record.gpio_errors++;
		return;
	}
	led_level = (led_level & ~bit) | want;
}

static void led_show(uint32_t rgb)
{
	led_set(&led_r, LED_R, (rgb & LED_R) != 0U);
	led_set(&led_g, LED_G, (rgb & LED_G) != 0U);
	led_set(&led_b, LED_B, (rgb & LED_B) != 0U);
}

static uint32_t led_pattern(uint32_t run, uint32_t state, uint32_t behavior, uint32_t takeover)
{
	if (!run) {
		return LED_B | LED_BLINK;
	}
	switch (state) {
	case MRM_NORMAL:
		return takeover ? (LED_R | LED_G | LED_BLINK) : LED_G;
	case MRM_OPERATING:
		if (behavior == MRM_BEH_COMFORTABLE) {
			return LED_R | LED_G;
		}
		return LED_R | LED_BLINK;
	case MRM_SUCCEEDED:
		return LED_R;
	case MRM_FAILED:
	default:
		return LED_R | LED_B | LED_BLINK;
	}
}

void island_led_update(uint32_t run, uint32_t state, uint32_t behavior, uint32_t takeover)
{
	const uint32_t pattern = led_pattern(run, state, behavior, takeover);
	const uint32_t code = (state << 24) | ((behavior & 0xffU) << 16) |
			      ((takeover & 0xffU) << 8) | pattern;
	const uint32_t tick = island_led_record.ticks + 1U;

	island_led_record.ticks = tick;
	if (code != island_led_record.code || pattern != island_led_record.pattern) {
		const uint32_t n = island_led_record.transitions;

		island_led_record.ring[n % ISLAND_LED_RING].uptime_ms = k_uptime_get_32();
		island_led_record.ring[n % ISLAND_LED_RING].code = code;
		island_led_record.code = code;
		island_led_record.pattern = pattern;
		island_led_record.transitions = n + 1U;
	}

	/* Blink: 2 ticks on, 2 off (2.5 Hz at the 10 Hz tick); INIT 5/5 (1 Hz). */
	uint32_t shown = pattern & (LED_R | LED_G | LED_B);

	if ((pattern & LED_BLINK) != 0U) {
		const uint32_t half = run ? 2U : 5U;

		if (((tick / half) & 1U) != 0U) {
			shown = 0U;
		}
	}
	led_show(shown);
	led_set(&led_hb, BIT(4), ((tick / 5U) & 1U) != 0U);
}

static int island_led_init(void)
{
	const struct gpio_dt_spec *all[] = {&led_r, &led_g, &led_b, &led_hb};

	for (size_t i = 0; i < ARRAY_SIZE(all); i++) {
		if (!gpio_is_ready_dt(all[i]) ||
		    gpio_pin_configure_dt(all[i], GPIO_OUTPUT_INACTIVE) != 0) {
			island_led_record.gpio_errors++;
		}
	}
	/* Boot: blue steady until the handler's first tick. The pins were
	 * configured inactive (dark), which led_level's zero says. */
	island_led_record.pattern = LED_B;
	led_show(LED_B);
	island_led_record.magic = ISLAND_LED_MAGIC;
	return 0;
}
SYS_INIT(island_led_init, APPLICATION, 90);
