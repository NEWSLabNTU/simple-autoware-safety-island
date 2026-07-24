# Autoware overrides — disable the stock MRM path

`disable-mrm.args` is appended to the `planning_simulator.launch.xml`
invocation so the island provides the only MRM path.

**P5 bring-up TODO:** verify the exact arg names against the Autoware 1.5.0
launch tree (`tier4_system_launch` / `autoware_launch`); older trees gate the
MRM nodes behind different args (or need a patched `system.launch.xml`
mounted over the stock one). The fallback that always works: mount a copy of
`tier4_system_launch/launch/system.launch.xml` with the mrm_handler +
operator includes commented out.
