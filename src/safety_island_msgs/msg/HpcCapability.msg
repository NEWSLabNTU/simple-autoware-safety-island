# HPC -> island capability vector (RFC section 8.1, /si/in/capability).
# Producer: H2 hpc_capability_reporter, 10 Hz, age limit 300 ms, SI-E2E/B.
# A fixed-size condensation of the HPC's diagnostics; it replaces free-form
# diagnostics on the link.

uint8 SELF_TEST_UNKNOWN = 0
uint8 SELF_TEST_PASS = 1
uint8 SELF_TEST_FAIL = 2

uint8 TAKEOVER_REASON_NONE = 0
uint8 TAKEOVER_REASON_ODD_EXIT = 1
uint8 TAKEOVER_REASON_PLANNING_STUCK = 2
uint8 TAKEOVER_REASON_PERCEPTION_UNCERTAIN = 3
uint8 TAKEOVER_REASON_OTHER = 255

builtin_interfaces/Time stamp
bool perception_ok
bool localization_ok
bool planning_ok
# Smallest margin of any pipeline against its declared latency budget [s];
# negative when a pipeline is over budget.
float32 pipeline_latency_margin
# Lowest confidence over the perception outputs, 0..1.
float32 confidence_floor
uint8 self_test
bool remote_takeover_requested
uint8 remote_takeover_reason
