# Co-sim demo (phase 5 — not wired yet)

Planned contents:

- `docker-compose.yaml` — Autoware planning_simulator
  (`ghcr.io/autowarefoundation/autoware:*`) on domain 1 + `ros2 domain_bridge`
  running `bridge/bridge-config.yaml` + noVNC visualizer. Pattern lifted from
  the ASI fork's `demo/`.
- `autoware-overrides/` — launch arguments disabling the stock MRM nodes
  (`mrm_handler`, `mrm_emergency_stop_operator`, `mrm_comfortable_stop_operator`)
  so the island is the only MRM path.
- Scenario script: engage autonomous mode → kill heartbeat/availability →
  island engages MRM → vehicle stops in the simulator.

Run (once wired): `just demo-up`, then `just demo-kill-heartbeat`.
