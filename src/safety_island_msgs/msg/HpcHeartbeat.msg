# HPC -> island heartbeat (RFC section 8.1, /si/in/heartbeat).
# Producer: H7 hpc_heartbeat, 100 Hz. Consumer: N2 si_hpc_supervisor, age
# limit 20 ms in the RFC table. Protection SI-E2E/B (section 8.4), applied by
# the link layer (H1/N1), not carried in this payload.

uint8 SELF_TEST_UNKNOWN = 0
uint8 SELF_TEST_PASS = 1
uint8 SELF_TEST_FAIL = 2

builtin_interfaces/Time stamp
# Increments by one per publication; N2 detects a stuck or repeated sender.
uint32 sequence
# Rolling self-test result and its fault code (0 = none).
uint8 self_test
uint32 self_test_fault_code
