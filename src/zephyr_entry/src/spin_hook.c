/*
 * The supervisor's per-spin hook (phase11-S4): the executor's single entry
 * point, nros_cpp_spin_once, is wrapped (-Wl,--wrap) so that every spin checks
 * its level in for SWT0 and, after it, the level that owns route 1 re-arms it
 * from its executor's earliest supervised due (island_supervisor.c). The
 * handle names the executor; the calling thread names the level (nano-ros
 * phase-509 I1).
 *
 * phase13-D3: this file used to be spin_priority.c and also raised the spin
 * thread to CONFIG_ISLAND_SPIN_THREAD_PRIORITY (3) on the first spin. The
 * executor now runs as the bringup's tier `mrm`, whose priority nano-ros
 * allocates from the contract and the image's priority plan; the tier runner
 * registers at CONFIG_MAIN_THREAD_PRIORITY and adopts the tier's priority
 * before the first spin, which is what the raise did by hand.
 */
#include <stdint.h>
#include <zephyr/kernel.h>
#include "island_supervisor.h"

int __real_nros_cpp_spin_once(void *handle, int32_t timeout_ms);

int __wrap_nros_cpp_spin_once(void *handle, int32_t timeout_ms)
{
	island_supervisor_spin(handle);
	const int rc = __real_nros_cpp_spin_once(handle, timeout_ms);

	island_supervisor_spin_after(handle);
	return rc;
}
