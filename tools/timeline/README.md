# tools/timeline - the live timeline (phase 8, unit W7)

One JSON Lines event stream (`t_mono_ns`, `source`, `kind`, `hazard`,
`rung`, `marker`, `value`) fed by the play_launch observer log, the
contract-generated probe and logger, the scenario controller, and the
island's trace markers; a pyqtgraph live drawer and a matplotlib renderer
that draw the same file. Declared bars come from the checker's arithmetic;
observed edges from events. Design: `docs/roadmap/phase-8-rtss-work-demo.md`, D7.
