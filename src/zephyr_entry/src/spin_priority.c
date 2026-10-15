/*
 * The executor's priority once registration is done (phase9 spin latency).
 *
 * The main thread registers every entity BELOW zenoh-pico's read task
 * (CONFIG_MAIN_THREAD_PRIORITY 5 against the read task's k_thread 4,
 * phase8-W10): while it registers, the read task must drain the serial RX
 * ring, or the router's answers to the island's interests are lost. The same
 * main thread then runs the executor, and at 5 the transport's read, flush and
 * lease tasks (all k_thread 4) run ahead of a release that is due: 1.7 ms
 * median of every late spin in sl-rclcpp-diag.
 *
 * The first spin is after registration (nros_cpp_spin_once is the executor's
 * single entry point, as native_sim's sim_clock_catch_up.c relies on), so
 * this raises the spin thread there, once.
 *
 * phase11-S4: the same entry point feeds the supervisor's SWT0, once per
 * spin (island_supervisor.c), so this wrapper is linked when either option
 * is on.
 */
#include <stdbool.h>
#include <stdint.h>
#include <zephyr/kernel.h>
#if defined(CONFIG_ISLAND_SUPERVISOR)
#include "island_supervisor.h"
#endif

int __real_nros_cpp_spin_once(void *handle, int32_t timeout_ms);

int __wrap_nros_cpp_spin_once(void *handle, int32_t timeout_ms)
{
#if defined(CONFIG_ISLAND_SPIN_RAISE)
	static bool raised;

	if (!raised) {
		raised = true;
		k_thread_priority_set(k_current_get(), CONFIG_ISLAND_SPIN_THREAD_PRIORITY);
	}
#endif
#if defined(CONFIG_ISLAND_SUPERVISOR)
	island_supervisor_spin();
	const int rc = __real_nros_cpp_spin_once(handle, timeout_ms);

	island_supervisor_spin_after(handle);
	return rc;
#else
	return __real_nros_cpp_spin_once(handle, timeout_ms);
#endif
}
