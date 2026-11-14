# Island-internal (RFC section 8.4): an SI-E2E verification failure raised by
# N1 si_safety_gateway to N8 si_fault_manager on /si/internal/e2e_event. A
# rejected message is a safety event, never a middleware exception.

uint8 KIND_CORRUPTION = 0
uint8 KIND_REPETITION = 1
uint8 KIND_RESEQUENCING = 2
uint8 KIND_LOSS = 3
uint8 KIND_DELAY = 4
uint8 KIND_INSERTION = 5
uint8 KIND_LENGTH = 6

builtin_interfaces/Time stamp
uint8 kind
# The Data ID of the interface the rejected message arrived on.
uint16 data_id
