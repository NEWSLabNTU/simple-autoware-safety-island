/*
 * Host tests of the supervisor's standstill verdicts (phase15-S3):
 * src/zephyr_entry/src/island_supervisor_judge.h, the functions the reaction
 * thread calls at route 2's and route 3's dues. `just supervisor-test`; CI
 * runs it too (.github/workflows/check.yml).
 */
#include <stdio.h>

#include "../../src/zephyr_entry/src/island_supervisor_judge.h"

static int fails;

#define CHECK(cond)                                                                  \
	do {                                                                         \
		if (!(cond)) {                                                       \
			printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);       \
			fails++;                                                     \
		}                                                                    \
	} while (0)

#define FRESH ISLAND_STANDSTILL_FRESH_MS

static void standstill(void)
{
	/* a fresh zero speed is a standstill */
	CHECK(island_judge_standstill(10000u, 0u, 9900u, FRESH));
	CHECK(island_judge_standstill(10000u, 0u, 10000u - FRESH, FRESH));
	/* moving, even 1 mm/s, is not */
	CHECK(!island_judge_standstill(10000u, 1u, 9900u, FRESH));
	/* stale: a zero speed older than the freshness bound is not seen */
	CHECK(!island_judge_standstill(10000u, 0u, 10000u - FRESH - 1u, FRESH));
	CHECK(island_judge_stale(10000u, 10000u - FRESH - 1u, FRESH));
	CHECK(!island_judge_stale(10000u, 9900u, FRESH));
	/* no sample ever noted */
	CHECK(!island_judge_standstill(10000u, 0u, 0u, FRESH));
	CHECK(island_judge_stale(10000u, 0u, FRESH));
	/* the uptime ms wraps at 2^32 */
	CHECK(island_judge_standstill(50u, 0u, 0xFFFFFFF0u, FRESH));
	CHECK(!island_judge_stale(50u, 0xFFFFFFF0u, FRESH));
}

/* Route 3's span: the emergency settle + the standstill observation
 * (CONFIG_ISLAND_SUPERVISOR_EMERGENCY_MS 4485 + _STANDSTILL_OBSERVE_MS 136). */
#define SPAN 4621u

static void floor_route(void)
{
	/* met: at standstill by the due, whatever the latch or the brake age */
	CHECK(island_judge_floor(true, false, 0u, SPAN) == ISLAND_FLOOR_MET);
	CHECK(island_judge_floor(true, true, SPAN, SPAN) == ISLAND_FLOOR_MET);
	CHECK(island_judge_floor(true, true, 10u, SPAN) == ISLAND_FLOOR_MET);
	/* missed, nothing latched yet: the command never took effect -> the
	 * direct path */
	CHECK(island_judge_floor(false, false, 0u, SPAN) == ISLAND_FLOOR_LATCH);
	/* missed under the island's braking command that ran a whole settle:
	 * the vehicle's fault */
	CHECK(island_judge_floor(false, true, SPAN, SPAN) == ISLAND_FLOOR_VEHICLE_FAULT);
	CHECK(island_judge_floor(false, true, SPAN + 5000u, SPAN) == ISLAND_FLOOR_VEHICLE_FAULT);
	/* phase15-S6: latched, but the braking command is younger than a
	 * settle -> no verdict yet, re-arm */
	CHECK(island_judge_floor(false, true, 0u, SPAN) == ISLAND_FLOOR_WAIT);
	CHECK(island_judge_floor(false, true, SPAN - 1u, SPAN) == ISLAND_FLOOR_WAIT);
}

/* The whole judgement at a due, as island_supervisor.c composes it: `brake`
 * is when the island's braking command (re)started (0: not latched). */
static enum island_floor_verdict at_due(uint32_t now, uint32_t v, uint32_t at, int latched, uint32_t brake)
{
	return island_judge_floor(island_judge_standstill(now, v, at, FRESH), latched != 0,
				  latched ? (uint32_t)(now - brake) : 0u, SPAN);
}

static void floor_sequences(void)
{
	/* stopped in time, seen on a fresh sample */
	CHECK(at_due(20000u, 0u, 19950u, 0, 0u) == ISLAND_FLOOR_MET);
	/* stopped, but the last sample is stale (link down): a miss, the
	 * direct path brakes (it keeps commanding zero speed anyway) */
	CHECK(at_due(20000u, 0u, 19000u, 0, 0u) == ISLAND_FLOOR_LATCH);
	/* request lost: still moving, nothing latched -> latch at 20000 (the
	 * direct path starts); its own due 24621 finds the vehicle stopped ->
	 * met */
	CHECK(at_due(20000u, 4000u, 19950u, 0, 0u) == ISLAND_FLOOR_LATCH);
	CHECK(at_due(24621u, 0u, 24600u, 1, 20000u) == ISLAND_FLOOR_MET);
	/* vehicle does not decelerate: latch, then the direct path's due (a
	 * whole settle of its own) finds it moving -> vehicle fault */
	CHECK(at_due(24621u, 8300u, 24600u, 1, 20000u) == ISLAND_FLOOR_VEHICLE_FAULT);
	/* stale under the direct path: still a fault (the island cannot see a
	 * stop) */
	CHECK(at_due(24621u, 0u, 24000u, 1, 20000u) == ISLAND_FLOOR_VEHICLE_FAULT);
}

/* odd_exit, two faults (phase15-S4): the comfortable stop overruns, route 2
 * latches the output and the direct path brakes from that due; the handler,
 * reading the latch, calls the emergency stop, which arms route 3 AFTER the
 * latch. Its due is a whole span after the call, so the braking command
 * (the direct path, then the operator continuing its ramp) has run at least
 * a settle: a miss is the vehicle's fault, never a second latch. */
static void two_faults(void)
{
	/* latched by route 2 at 20000, route 3 armed at 20100: due 24721 */
	CHECK(at_due(24721u, 3000u, 24700u, 1, 20000u) == ISLAND_FLOOR_VEHICLE_FAULT);
	CHECK(at_due(24721u, 3000u, 24700u, 1, 20000u) != ISLAND_FLOOR_LATCH);
	/* the direct path stopped the vehicle in time: met */
	CHECK(at_due(24721u, 0u, 24700u, 1, 20000u) == ISLAND_FLOOR_MET);
	/* stale under the latch: the island cannot see a stop -> the fault */
	CHECK(at_due(24721u, 0u, 24000u, 1, 20000u) == ISLAND_FLOOR_VEHICLE_FAULT);
}

/* phase15-S6 (a): a real stall of the mrm tier. Route 3 is armed at the
 * call (20000, due 24621); the operator level stalls, SWT0 latches 300 ms
 * later... at 24400 in the worst case, just before route 3's due. The
 * direct path has braked 221 ms at the due: no verdict, re-armed at
 * 24400 + 4621 = 29021, judged then. */
static void latched_young(void)
{
	CHECK(at_due(24621u, 3000u, 24600u, 1, 24400u) == ISLAND_FLOOR_WAIT);
	/* the re-armed due: the direct path's whole settle */
	CHECK(at_due(29021u, 0u, 29000u, 1, 24400u) == ISLAND_FLOOR_MET);
	CHECK(at_due(29021u, 1000u, 29000u, 1, 24400u) == ISLAND_FLOOR_VEHICLE_FAULT);
	/* one ms short of it is still no verdict */
	CHECK(at_due(29020u, 1000u, 29000u, 1, 24400u) == ISLAND_FLOOR_WAIT);
}

static void resume(void)
{
	/* the operator ticks at 33 ms; three periods silent is 99 ms */
	CHECK(!island_judge_resume(10098u, 10000u, 33u, 3u));
	CHECK(island_judge_resume(10099u, 10000u, 33u, 3u));
	CHECK(island_judge_resume(15000u, 10000u, 33u, 3u));
	/* the handler ticks at 100 ms: 300 ms */
	CHECK(!island_judge_resume(10299u, 10000u, 100u, 3u));
	CHECK(island_judge_resume(10300u, 10000u, 100u, 3u));
	/* the uptime ms wraps at 2^32 */
	CHECK(!island_judge_resume(50u, 0xFFFFFFF0u, 33u, 3u));
	CHECK(island_judge_resume(90u, 0xFFFFFFF0u, 33u, 3u));
}

/* phase15-S6 (b): the operator stalls after its handover. Route 2 latched
 * at 20000 (the direct path brakes), the handler's emergency call arms
 * route 3 at 20100 (due 24721), the operator takes over at 20150 and
 * reports every tick until 22000, then stalls. At 22099 it has been silent
 * three periods: the direct path resumes the slot, and the island's
 * braking command restarts there. */
static void stall_after_handover(void)
{
	CHECK(!island_judge_resume(22098u, 22000u, 33u, 3u));
	CHECK(island_judge_resume(22099u, 22000u, 33u, 3u));
	/* route 3's due: the resumed direct path has braked 2622 ms -> no
	 * verdict (was a vehicle fault before S6), re-armed at 22099 + 4621 */
	CHECK(at_due(24721u, 2000u, 24700u, 1, 22099u) == ISLAND_FLOOR_WAIT);
	/* the re-armed due: stopped -> met; still moving -> the vehicle's */
	CHECK(at_due(26720u, 0u, 26700u, 1, 22099u) == ISLAND_FLOOR_MET);
	CHECK(at_due(26720u, 2000u, 26700u, 1, 22099u) == ISLAND_FLOOR_VEHICLE_FAULT);
}

static void unseen(void)
{
	/* no sample since boot: route 3 waits (island_supervisor.c re-arms) */
	CHECK(island_judge_unseen(0u));
	/* any sample once taken: judged, a stale one as a miss */
	CHECK(!island_judge_unseen(1u));
	CHECK(!island_judge_unseen(19000u));
	CHECK(at_due(20000u, 0u, 19000u, 0, 0u) == ISLAND_FLOOR_LATCH);
}

/* phase15-S7: the vehicle-side fault is reported as MRM_FAILED, and Autoware
 * 1.5.0's vehicle_cmd_gate still passes the emergency command and hazard
 * lights for it (the behaviour stays EMERGENCY_STOP). */
static void mrm_failed(void)
{
	CHECK(island_judge_mrm_state(ISLAND_MRM_OPERATING, false) == ISLAND_MRM_OPERATING);
	CHECK(island_judge_mrm_state(ISLAND_MRM_SUCCEEDED, false) == ISLAND_MRM_SUCCEEDED);
	CHECK(island_judge_mrm_state(ISLAND_MRM_OPERATING, true) == ISLAND_MRM_FAILED);
	CHECK(island_judge_mrm_state(ISLAND_MRM_SUCCEEDED, true) == ISLAND_MRM_FAILED);
	/* the gate's emergency holds across OPERATING -> FAILED */
	CHECK(island_autoware_gate_emergency(ISLAND_MRM_OPERATING, ISLAND_MRM_EMERGENCY_STOP));
	CHECK(island_autoware_gate_emergency(island_judge_mrm_state(ISLAND_MRM_OPERATING, true),
					     ISLAND_MRM_EMERGENCY_STOP));
	/* it would not with another behaviour (why the island keeps it) */
	CHECK(!island_autoware_gate_emergency(ISLAND_MRM_FAILED, 3u /* COMFORTABLE_STOP */));
	CHECK(!island_autoware_gate_emergency(1u /* NORMAL */, ISLAND_MRM_EMERGENCY_STOP));
}

int main(void)
{
	standstill();
	floor_route();
	floor_sequences();
	unseen();
	two_faults();
	latched_young();
	resume();
	stall_after_handover();
	mrm_failed();
	printf("supervisor judge: %s\n", fails ? "FAILED" : "OK");
	return fails ? 1 : 0;
}
