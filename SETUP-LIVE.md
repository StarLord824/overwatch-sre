# Live SigNoz End-to-End Setup

This wires Over-Watch to **real** SigNoz telemetry (not fixtures/mock), so the
agent investigates actual traces/logs/metrics through the SigNoz MCP server. Do
this for the demo and for "Best Use of SigNoz."

There are two things you can run against live SigNoz:
- **The benchmark** — `eval.run_eval --live` (agent investigates real data).
- **The full pipeline** — webhook → gateway → agent → dashboard + Slack.

---

## 1. Stand up self-hosted SigNoz

```bash
git clone -b main https://github.com/SigNoz/signoz.git
cd signoz/deploy/docker
docker compose up -d          # ClickHouse + query-service + otel-collector + UI
```

Wait ~2 min, then open the SigNoz UI (commonly **http://localhost:3301** on the
classic layout, or **http://localhost:8080** on newer builds — whichever your
compose exposes). Create an API key: **Settings → API Keys → New Key**.

The OTel collector accepts telemetry on **:4317** (gRPC) and **:4318** (HTTP).

---

## 2. Pull the SigNoz MCP server image

The agent spawns this over stdio; pre-pull so the first call is fast:

```bash
docker pull signoz/signoz-mcp-server:latest
```

---

## 3. Configure `agent-python/.env`

```env
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4.1
EVAL_JUDGE_MODEL=gpt-4.1

SIGNOZ_URL=http://localhost:3301      # the URL you open SigNoz at
SIGNOZ_API_KEY=<the key you just made>
SIGNOZ_MCP_MODE=docker
```

> **Docker networking gotcha (handled for you):** the MCP server runs in a
> container, where `localhost` means the container itself. The config
> automatically rewrites `localhost`/`127.0.0.1` → `host.docker.internal` for the
> container and adds `--add-host ...:host-gateway`, so the container can reach
> SigNoz on your host. If SigNoz runs on another machine, set `SIGNOZ_URL` to that
> host's IP directly.

---

## 4. Preflight — confirm the agent can reach SigNoz

```bash
cd agent-python
uv sync
uv run python -m signoz_mcp.smoke
```

Expected: `✓ Connected. MCP exposes N tools.` and a `signoz_list_services`
response. If it says `✗ NOT connected`, fix that **before** anything else — the
message lists what to check. (If you can't get docker mode working, download the
[MCP server binary](https://github.com/SigNoz/signoz-mcp-server/releases) and set
`SIGNOZ_MCP_MODE=binary` + `SIGNOZ_MCP_BINARY=/path/to/signoz-mcp-server`.)

---

## 5. Generate real telemetry (so there's data to investigate)

```bash
uv sync --group demo
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   # SigNoz collector (gRPC)
python demo/sample_app.py            # instrumented checkout→payment-gateway
```

In another terminal, drive traffic + inject the fault:

```bash
python demo/trigger_incident.py      # baseline → /break → error traffic → webhook
```

Give SigNoz ~30–60s to ingest, then confirm `checkout-service` shows errors in
the SigNoz UI.

---

## 6a. Run the benchmark against live SigNoz

```bash
uv run python -m eval.run_eval --live --trials 1
```

> Note: the fixture scenarios reference synthetic services (checkout-service,
> payment-gateway, …). `--live` sends the same alerts but the agent now queries
> **your** SigNoz — so scores reflect whatever data actually exists there. Use
> `--live` to prove the integration works end-to-end; use the default
> (fixture) mode for the reproducible accuracy scorecard.

## 6b. Run the full pipeline (stage demo)

```bash
# from the repo root
docker compose up -d                 # RabbitMQ + Redis

cd gateway-node && npm install && npm start          # :4000
cd ../agent-python && uv run python main.py           # RabbitMQ consumer
cd ../frontend-mission-control && npm install && npm run dev   # :3000
```

Open http://localhost:3000 and click **Simulate Alert** — watch the live
reasoning stream, the final RCA with SigNoz deep-links, and the 🛡️ Prevention
card as the agent creates a guard alert. Point a real SigNoz webhook at
`http://<host>:4000/api/webhooks/signoz` to trigger from an actual alert.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| smoke: `✗ NOT connected` | SigNoz not up, wrong `SIGNOZ_URL`, missing API key, or image not pulled |
| MCP container can't reach SigNoz | Ensure `SIGNOZ_URL` uses `localhost` (auto-rewritten) or the host IP; SigNoz reachable from host |
| No data in SigNoz | Check `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`; give it 30–60s to ingest |
| Rate limits (429) | Low TPM tier — `eval.run_eval` already retries + paces (`--pace`) |
| Agent uses MOCK data | smoke first; the status banner + report flag `signoz_live=false` when mocked |
