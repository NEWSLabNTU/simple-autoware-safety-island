/*
 * The board's supervised-deadline rung (phase11-S4, island_supervisor.c).
 * C linkage; the MRM handler declares the two calls it makes itself
 * (mrm_handler_core.cpp), as it does for the LED and button hooks.
 */
#ifndef ISLAND_SUPERVISOR_H
#define ISLAND_SUPERVISOR_H

#include <stdint.h>

#define ISLAND_SUPERVISOR_ROUTES 2

/* Route ids. 0: the hpc_loss reaction (mrm_handler/call_mrm on a tick that
 * sees the availability lost), armed from the handler's availability take. */
#define ISLAND_SUPERVISOR_ROUTE_CALL_MRM_HPC_LOSS 0u
/* 1: the executor's earliest pending supervised route (nano-ros phase-503,
 * nros_cpp_executor_route_next_due_us), re-armed after every spin. */
#define ISLAND_SUPERVISOR_ROUTE_EXECUTOR 1u

/* SUPERVISOR_SAFE_STATE's arg. */
#define ISLAND_SUPERVISOR_CAUSE_ROUTE 1u
#define ISLAND_SUPERVISOR_CAUSE_SWT 2u
#define ISLAND_SUPERVISOR_CAUSE_HOOK 3u /* the executor's reaction hook */

#ifdef __cplusplus
extern "C" {
#endif
/* Set route's due (uptime ms) and re-arm the timer to the earliest due. */
void island_supervisor_arm(uint32_t route, int64_t due_ms);
/* The route's output came in time: clear its due. */
void island_supervisor_done(uint32_t route);
/* Once per spin, from the spin thread (spin_priority.c): starts SWT0 on the
 * first call, feeds it after. */
void island_supervisor_spin(void);
/* After each spin: re-arm route 1 from the executor's next due. */
void island_supervisor_spin_after(void *executor);
#ifdef __cplusplus
}
#endif

#endif /* ISLAND_SUPERVISOR_H */
