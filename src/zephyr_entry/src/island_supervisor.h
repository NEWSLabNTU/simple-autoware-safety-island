/*
 * The board's supervised-deadline rung (phase11-S4, island_supervisor.c).
 * C linkage; the MRM handler declares the two calls it makes itself
 * (mrm_handler_core.cpp), as it does for the LED and button hooks.
 */
#ifndef ISLAND_SUPERVISOR_H
#define ISLAND_SUPERVISOR_H

#include <stdint.h>

#define ISLAND_SUPERVISOR_ROUTES 3

/* Route ids. 0: the hpc_loss reaction (mrm_handler/call_mrm on a tick that
 * sees the availability lost), armed from the handler's availability take. */
#define ISLAND_SUPERVISOR_ROUTE_CALL_MRM_HPC_LOSS 0u
/* 1: the executor's earliest pending supervised route (nano-ros phase-503,
 * nros_cpp_executor_route_next_due_us), re-armed after every spin. */
#define ISLAND_SUPERVISOR_ROUTE_EXECUTOR 1u
/* 2: the comfortable stop's standstill (phase11-S6, decision 4): armed by the
 * handler when it calls the comfortable stop, due = call + the comfortable
 * settle at the entry speed + its response (CONFIG_ISLAND_SUPERVISOR_
 * COMFORTABLE_MS). At the due the reaction thread judges the vehicle's last
 * reported speed (island_supervisor_note_speed): at standstill the route is
 * met; otherwise the comfortable stop has failed and the emergency stop is
 * commanded. The handler clears it when it sees the standstill itself or
 * leaves the comfortable stop. */
#define ISLAND_SUPERVISOR_ROUTE_COMFORTABLE_STANDSTILL 2u

/* The direct emergency path (phase11-S6, decision 2). A component registers
 * one function per slot at construction; once the output is latched the
 * reaction thread calls it at once and then every
 * CONFIG_ISLAND_SUPERVISOR_DIRECT_PERIOD_MS until that component's own
 * executor path reports the emergency running (island_supervisor_handover).
 * The function publishes on publishers the component built at construction,
 * from messages it owns alone; it never takes the executor, a service or the
 * component's spin-thread state. */
#define ISLAND_SUPERVISOR_DIRECT_SLOTS 2
#define ISLAND_SUPERVISOR_DIRECT_HANDLER 0u  /* mrm_handler: mrm_state + hazard */
#define ISLAND_SUPERVISOR_DIRECT_OPERATOR 1u /* emergency operator: control_cmd */
typedef void (*island_supervisor_direct_fn)(void *ctx, uint32_t seq, uint32_t since_latch_ms);

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
/* 1 once the safe-state output is latched (never cleared before reset). The
 * handler reads it every tick and then holds the emergency stop. */
uint32_t island_supervisor_latched(void);
/* Register the direct emergency function of a slot (construction only). */
void island_supervisor_set_direct(uint32_t slot, island_supervisor_direct_fn fn, void *ctx);
/* The slot's executor path now publishes the emergency itself: the reaction
 * thread stops calling its direct function. Called from the spin thread. */
void island_supervisor_handover(uint32_t slot);
/* The vehicle's speed from the latest kinematic_state take (|v|, mm/s),
 * stamped with the uptime: route 2's standstill judgement. */
void island_supervisor_note_speed(uint32_t speed_mm_s);
#ifdef __cplusplus
}
#endif

#endif /* ISLAND_SUPERVISOR_H */
