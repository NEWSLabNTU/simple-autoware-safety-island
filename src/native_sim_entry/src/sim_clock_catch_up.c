/*
 * The native_sim clock catch-up before the first spin (phase8-W29).
 *
 * WHAT IT FIXES. On native_sim the island heard its first availability
 * sample at 0.202 s of simulated time and the next at 0.82 s: a 520-630 ms
 * gap in every traced run (w8a-e, w14-e, w27-a/b/e), past the island's 500 ms
 * silence bound, and one tick of false MRM right after start-up. The gap is
 * not on the wire. Run w29-base-a, with the island's console stamped on the
 * host (tools/timeline/stamp.py):
 *
 *     host ms   island line
 *        45.7   [00:00:00.000,002] dds_create_participant returned
 *       729.2   [00:00:00.202,261] ... claimed at first spin
 *       730.5   [mrm_handler] INIT -> RUN
 *       759.8   [00:00:00.712,000] silence-runtime .../operation_mode_availability
 *       791.1   [mrm_handler] MRM State changed: NORMAL -> MRM_OPERATING
 *
 * 510 ms of simulated time between the last two nros lines took 30 ms of host
 * time. The gate published every 100 ms throughout (its stats: largest publish
 * gap 101.7 ms), and the host probe heard it every 100 ms.
 *
 * WHY. native_sim's simulated clock does not advance while embedded code
 * computes or blocks in a host call; it advances only when the CPU idles, and
 * in real-time mode it then runs as fast as it can until it is level with the
 * host again (scripts/native_simulator/native/src/timer_model.c,
 * hwtimer_tick_timer_reached: it sleeps only when AHEAD of the host). Joining
 * a running Autoware graph costs the island's boot 500-650 ms of host time --
 * participant creation, Cyclone ingesting the graph's discovery, the
 * components' registration -- at simulated time 0 to 0.2 s. The executor's
 * first spin therefore ran 530 ms behind the host, took the latest sample, and
 * then watched its clock sprint through half a second of simulated time in
 * about 40 ms of host time, during which, of course, nothing arrived. The
 * island's timers, and its 500 ms availability bound, run on that clock.
 * A board has no such clock: its boot costs the same work, but in real time,
 * before its first spin (experiments/serial-interop/w10: each 10 Hz input
 * taken 20-21 times in the first 2 s after a cold reset).
 *
 * THE FIX. The first call into the executor waits, in simulated time, until the
 * simulated clock is level with the host (to within CATCH_UP_SLACK_US), so the
 * sprint happens before the island takes or times anything, not after its
 * first sample. The wait is k_sleep(): an idle CPU is exactly what lets the
 * clock catch up. It is bounded (CATCH_UP_MAX_MS of simulated time) so a host
 * that cannot keep up cannot hold the island forever.
 *
 * HOW IT IS HOOKED. nano-ros's ZephyrBoard::run_components has no hook between
 * the components' setup and the spin loop (only nros_board_network_wait, which
 * runs before the session exists, and so before most of the stall). The link
 * wraps nros_cpp_spin_once (CMakeLists.txt: --wrap), the executor's single
 * entry point, so the first spin -- the spin loop's, or a blocking wait inside
 * a component's setup, whichever comes first -- goes through here. This file
 * is in the native_sim entry only; the board image is built from
 * src/zephyr_entry and never sees it.
 */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

#include <stdbool.h>
#include <stdint.h>

/* native_sim's RTC (boards/native/native_sim, native_rtc.h): the simulated
 * clock, and the host's own clock seen through the same offset. */
#define RTC_CLOCK_REALTIME 1
#define RTC_CLOCK_PSEUDOHOSTREALTIME 2
extern uint64_t native_rtc_gettime_us(int clock_type);

#define CATCH_UP_SLACK_US 2000
#define CATCH_UP_MAX_MS 10000

int __real_nros_cpp_spin_once(void *handle, int32_t timeout_ms);

static int64_t lag_us(void)
{
	return (int64_t)native_rtc_gettime_us(RTC_CLOCK_PSEUDOHOSTREALTIME) -
	       (int64_t)native_rtc_gettime_us(RTC_CLOCK_REALTIME);
}

static void catch_up(void)
{
	const int64_t lag0 = lag_us();
	const int64_t t0 = k_uptime_get();
	int64_t lag = lag0;

	while (lag > CATCH_UP_SLACK_US && k_uptime_get() - t0 < CATCH_UP_MAX_MS) {
		k_sleep(K_USEC(lag < 50000 ? lag : 50000));
		lag = lag_us();
	}
	printk("[native_sim] first spin at %lld ms: the clock was %lld ms behind the host "
	       "(boot work at simulated time 0), held %lld ms to catch up, %lld ms behind now\n",
	       (long long)t0, (long long)(lag0 / 1000), (long long)(k_uptime_get() - t0),
	       (long long)(lag / 1000));
}

int __wrap_nros_cpp_spin_once(void *handle, int32_t timeout_ms)
{
	static bool caught_up;

	if (!caught_up) {
		caught_up = true;
		catch_up();
	}
	return __real_nros_cpp_spin_once(handle, timeout_ms);
}
