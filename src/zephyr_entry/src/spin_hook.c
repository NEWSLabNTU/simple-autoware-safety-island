/*
 * The supervisor's per-spin hook (phase11-S4): the executor's spin entry
 * points, nros_cpp_spin_once (the adopted level) and, since nano-ros phase-509
 * P9b, nros_cpp_level_spin_once (each spawned level's worker), are wrapped
 * (-Wl,--wrap) so that every spin checks
 * its level in for SWT0 and, after it, the level that owns route 1 re-arms it
 * from its executor's earliest supervised due (island_supervisor.c). The
 * handle names the core's one executor; the entry point names the level.
 *
 * phase13-D3: this file used to be spin_priority.c and also raised the spin
 * thread to CONFIG_ISLAND_SPIN_THREAD_PRIORITY (3) on the first spin. The
 * executor's levels are derived by nano-ros, each at a priority allocated
 * from the contract and the image's priority plan; the runner registers at
 * CONFIG_MAIN_THREAD_PRIORITY and each level adopts its priority before its
 * first spin, which is what the raise did by hand.
 */
#include <stdint.h>
#include <zephyr/kernel.h>
#include "island_supervisor.h"

int __real_nros_cpp_spin_once(void *handle, int32_t timeout_ms);
int __real_nros_cpp_level_spin_once(void *scheduler, uint8_t level, int32_t timeout_ms);
int nros_cpp_executor_level(void *handle, uint8_t *out_level);
#ifdef CONFIG_ISLAND_LOCK_PROBE
/* nano-ros issue 2065: a spawned level's setup and steady stack peaks
 * (island_lock_probe.c, section 4). */
void island_lock_probe_level_pass(void);
#endif
void *nros_cpp_scheduler_owner(void *scheduler);

/* The adopted level (it owns the core's executor and runs on main()). */
int __wrap_nros_cpp_spin_once(void *handle, int32_t timeout_ms)
{
	uint8_t level = 0xFFu;

	(void)nros_cpp_executor_level(handle, &level);
	island_supervisor_spin(handle, level);
	const int rc = __real_nros_cpp_spin_once(handle, timeout_ms);

	island_supervisor_spin_after(handle, level);
	return rc;
}

/* nano-ros phase-509 P9b: a spawned level, a worker over the same executor. */
int __wrap_nros_cpp_level_spin_once(void *scheduler, uint8_t level, int32_t timeout_ms)
{
#ifdef CONFIG_ISLAND_LOCK_PROBE
	island_lock_probe_level_pass();
#endif
	void *executor = nros_cpp_scheduler_owner(scheduler);

	island_supervisor_spin(executor, level);
	const int rc = __real_nros_cpp_level_spin_once(scheduler, level, timeout_ms);

	island_supervisor_spin_after(executor, level);
	return rc;
}
