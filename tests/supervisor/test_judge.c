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

static void floor_route(void)
{
	/* met: at standstill by the due, whatever the stage or the latch */
	CHECK(island_judge_floor(true, false, ISLAND_FLOOR_OPERATOR) == ISLAND_FLOOR_MET);
	CHECK(island_judge_floor(true, true, ISLAND_FLOOR_DIRECT) == ISLAND_FLOOR_MET);
	/* missed, nothing latched yet: the command never took effect -> the
	 * direct path */
	CHECK(island_judge_floor(false, false, ISLAND_FLOOR_OPERATOR) == ISLAND_FLOOR_LATCH);
	/* missed under the direct path's own settle: the vehicle's fault */
	CHECK(island_judge_floor(false, true, ISLAND_FLOOR_DIRECT) == ISLAND_FLOOR_VEHICLE_FAULT);
	/* missed with the output latched before the call (route 0/1/2 or SWT0
	 * already braking on the direct path): the vehicle's fault */
	CHECK(island_judge_floor(false, true, ISLAND_FLOOR_OPERATOR) == ISLAND_FLOOR_VEHICLE_FAULT);
}

/* The whole judgement at a due, as island_supervisor.c composes it. */
static enum island_floor_verdict at_due(uint32_t now, uint32_t v, uint32_t at, int latched, uint32_t stage)
{
	return island_judge_floor(island_judge_standstill(now, v, at, FRESH), latched != 0, stage);
}

static void floor_sequences(void)
{
	/* stopped in time, seen on a fresh sample */
	CHECK(at_due(20000u, 0u, 19950u, 0, ISLAND_FLOOR_OPERATOR) == ISLAND_FLOOR_MET);
	/* stopped, but the last sample is stale (link down): a miss, the
	 * direct path brakes (it keeps commanding zero speed anyway) */
	CHECK(at_due(20000u, 0u, 19000u, 0, ISLAND_FLOOR_OPERATOR) == ISLAND_FLOOR_LATCH);
	/* request lost: still moving, nothing latched -> latch; then the direct
	 * path stops the vehicle by its own due -> met */
	CHECK(at_due(20000u, 4000u, 19950u, 0, ISLAND_FLOOR_OPERATOR) == ISLAND_FLOOR_LATCH);
	CHECK(at_due(24621u, 0u, 24600u, 1, ISLAND_FLOOR_DIRECT) == ISLAND_FLOOR_MET);
	/* vehicle does not decelerate: latch, then the direct path's due finds
	 * it moving -> vehicle fault */
	CHECK(at_due(24621u, 8300u, 24600u, 1, ISLAND_FLOOR_DIRECT) == ISLAND_FLOOR_VEHICLE_FAULT);
	/* stale under the direct path: still a fault (the island cannot see a
	 * stop) */
	CHECK(at_due(24621u, 0u, 24000u, 1, ISLAND_FLOOR_DIRECT) == ISLAND_FLOOR_VEHICLE_FAULT);
}

/* odd_exit, two faults (phase15-S4): the comfortable stop overruns, route 2
 * latches the output and the direct path brakes from that due; the handler,
 * reading the latch, calls the emergency stop, which arms route 3 at its
 * operator stage AFTER the latch. Its due finds the output latched: a miss
 * then is the vehicle's fault (a braking command has run at least a settle),
 * never a second latch and never a second direct-path settle (no re-arm). */
static void two_faults(void)
{
	/* latched by route 2 at 20000, route 3 armed at 20100: due 24721 */
	CHECK(at_due(24721u, 3000u, 24700u, 1, ISLAND_FLOOR_OPERATOR) == ISLAND_FLOOR_VEHICLE_FAULT);
	CHECK(at_due(24721u, 3000u, 24700u, 1, ISLAND_FLOOR_OPERATOR) != ISLAND_FLOOR_LATCH);
	/* the direct path stopped the vehicle in time: met */
	CHECK(at_due(24721u, 0u, 24700u, 1, ISLAND_FLOOR_OPERATOR) == ISLAND_FLOOR_MET);
	/* stale under the latch: the island cannot see a stop -> the fault */
	CHECK(at_due(24721u, 0u, 24000u, 1, ISLAND_FLOOR_OPERATOR) == ISLAND_FLOOR_VEHICLE_FAULT);
}

static void unseen(void)
{
	/* no sample since boot: route 3 waits (island_supervisor.c re-arms) */
	CHECK(island_judge_unseen(0u));
	/* any sample once taken: judged, a stale one as a miss */
	CHECK(!island_judge_unseen(1u));
	CHECK(!island_judge_unseen(19000u));
	CHECK(at_due(20000u, 0u, 19000u, 0, ISLAND_FLOOR_OPERATOR) == ISLAND_FLOOR_LATCH);
}

int main(void)
{
	standstill();
	floor_route();
	floor_sequences();
	unseen();
	two_faults();
	printf("supervisor judge: %s\n", fails ? "FAILED" : "OK");
	return fails ? 1 : 0;
}
