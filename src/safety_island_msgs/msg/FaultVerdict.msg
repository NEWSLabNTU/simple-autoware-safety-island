# Island-internal (RFC section 6.1): N8 si_fault_manager's single fault
# verdict for N3 si_state_machine, on /si/internal/fault_verdict, 100 Hz.

uint8 SEVERITY_NONE = 0
uint8 SEVERITY_DEGRADE = 1
uint8 SEVERITY_HPC_LOST = 2
uint8 SEVERITY_BLACKOUT = 3

builtin_interfaces/Time stamp
uint8 severity
# The DTC of the fault that set the severity (0 = none).
uint32 fault_code
