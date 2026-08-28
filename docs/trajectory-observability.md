# Trajectory observability integration

This fork adds the RMF task trajectory observability service as an optional
RMF Dashboard Framework MicroApp. Existing Map, Robots, Tasks and Custom tabs
are unchanged.

## Run the observability service

```bash
cd integrations/trajectory-observability
PORT=8080 python3 server.py
```

## Run the dashboard

```bash
export VITE_TRAJECTORY_OBSERVABILITY_URL=http://localhost:8080
pnpm install
pnpm --filter rmf-dashboard-framework start:example examples/demo
```

Open the `Trajectory` tab. The service starts with timestamped demo data and
can receive live Open-RMF `FleetState` messages at:

```text
POST /api/trajectory/live
```

The service is isolated in an iframe so it does not modify or take control of
the existing dashboard, RMF API server or task dispatcher.

For a hardware-free live feed:

```bash
python3 integrations/trajectory-observability/tools/mock_rmf_source.py \
  --url http://localhost:8080
```

See `integrations/trajectory-observability/INTEGRATION.md` for the message
contract, rosbridge envelope support and optional ingest authentication.
