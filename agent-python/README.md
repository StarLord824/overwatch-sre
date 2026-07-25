# Over-Watch — Agent Brain (`agent-python`)

The autonomous SRE investigator. This is an **OpenSRE-style direct tool-calling
loop** (no LangGraph, no chains): one reasoning loop that freely chooses tools
across two domains and produces an evidence-backed root cause analysis.

```
Alert ─▶ [ mask PII ] ─▶ [ Investigator loop ] ─▶ RCA report ─▶ (Redis → gateway → UI + Slack)
                              │
        ┌─────────────────────┴─────────────────────┐
   Observability                              Knowledge & Memory
   (SigNoz MCP, real telemetry)               (runbooks + past incidents)
   list_services · search_traces ·            search_runbooks ·
   get_trace_details · search_logs ·          recall_similar_incidents ·
   query_metrics · list_alerts                save_incident_memory
```

## How it works

1. **Consume** an incident from RabbitMQ (`main.py`).
2. **Mask** PII in the alert payload (`utils/masking.py`).
3. **Investigate** (`agent/loop.py`): the LLM starts by checking memory/runbooks,
   forms hypotheses, then tests them against **real SigNoz telemetry** via the
   MCP server — following traces downstream, confirming with logs and metrics,
   and citing exact evidence.
4. **Remember**: it writes the resolved incident back to memory so the next
   occurrence is instant.
5. **Stream** every step (`thinking` / `tool_call` / `final_report` / `cost`) to
   Redis for the dashboard and Slack.

## SigNoz MCP (stdio)

The agent spawns the [official SigNoz MCP server](https://github.com/SigNoz/signoz-mcp-server)
as a subprocess and calls its real tools. Configure via `.env`:

```bash
SIGNOZ_URL=http://localhost:3301
SIGNOZ_API_KEY=...            # Settings → API Keys in SigNoz
SIGNOZ_MCP_MODE=docker        # default: runs signoz/signoz-mcp-server:latest over stdio
# or run a downloaded binary instead:
# SIGNOZ_MCP_MODE=binary
# SIGNOZ_MCP_BINARY=/path/to/signoz-mcp-server
```

Pre-pull the image so the first investigation is fast:

```bash
docker pull signoz/signoz-mcp-server:latest
```

**Preflight** — confirm the agent can actually reach SigNoz before a full run:

```bash
uv run overwatch doctor --deep
```

For the complete live end-to-end walkthrough (stand up SigNoz, generate real
data, run `--live` and the full pipeline), see [`../SETUP-LIVE.md`](../SETUP-LIVE.md).

> **Demo resilience:** if the MCP server can't be reached, the agent falls back to
> **clearly-labeled MOCK data** (`"_source": "MOCK"`) so a live demo never
> hard-crashes. The status banner and report both flag when data is mocked.

## Run

```bash
uv sync                       # installs the agent, CLI, and dependencies
cp .env.example .env          # fill in OPENAI_API_KEY, SIGNOZ_URL, SIGNOZ_API_KEY
uv run overwatch              # interactive menu
```

Everything is available through one command:

| Command | What it does |
|---|---|
| `overwatch` | Interactive menu — pick an action, no flags to memorise |
| `overwatch doctor` | Check the setup and say exactly what's broken (`--deep` also spawns the MCP server and runs a live query) |
| `overwatch eval` | Run the RCA benchmark and print a scorecard |
| `overwatch demo` | Drive real traffic through the demo app and inject a fault |
| `overwatch worker` | Consume incidents from RabbitMQ (the full pipeline) |
| `overwatch guide` | What Over-Watch does, how to run it, how to fix problems |

Run `overwatch <command> --help` for flags. The underlying modules
(`python main.py`, `python -m eval.run_eval`, …) still work unchanged if you
prefer them.

**Start here if something isn't working:** `uv run overwatch doctor`.

## 📊 RCA benchmark (the proof it works)

The eval harness runs the real agent against a suite of **injected incidents with
known root causes and deliberate red herrings**, then scores it. This is the
number for your demo — no clone-without-proof can match it.

```bash
uv run overwatch eval --list        # the 5 scenarios (no LLM needed)
uv run overwatch eval --dry-run     # validate fixtures + scorer (no LLM)
uv run overwatch eval               # run the benchmark (needs OPENAI_API_KEY)
uv run overwatch eval --trials 3    # repeat 3x and report variance (the honest number)
uv run overwatch eval --no-judge    # keyword-only scoring, no judge calls
uv run overwatch eval --live        # score against a real SigNoz MCP instead of fixtures
```

Each scenario ships its own telemetry, so the benchmark is **deterministic and
needs no SigNoz/Docker** — only an LLM key. Scoring is designed to be defensible,
not gameable:

- **RCA accuracy** — an **LLM judge** classifies the agent's conclusion into a
  **closed vocabulary** of causes (incl. the distractor classes the red herrings
  point at) and grades it against a per-scenario **rubric**. Falls back to keyword
  matching automatically when no judge is available.
- **Red-herring resistance** — did the concluded cause avoid the planted distractor?
- **Evidence recall** — did it cite the required signals?
- **Variance across trials** — `--trials N` reports mean ± spread, because a single
  LLM run isn't a number.
- **Cost / LLM calls per incident** — from the built-in cost tracker.
- **Per-category breakdown** — accuracy by fault class.

Output prints a scorecard (+ variance) and writes `eval/last_scorecard.json`.
Scenarios and their ground truth live in `eval/scenarios.py`; the judge in
`eval/judge.py`.

## Generate real SigNoz data (optional)

```bash
uv sync --group demo
uv run python demo/sample_app.py   # leave running: checkout-service + payment-gateway
uv run overwatch demo              # baseline traffic -> inject fault -> fire webhook
```

The demo app exports **traces and logs for two services** to SigNoz Cloud (set
`SIGNOZ_INGESTION_KEY` and `SIGNOZ_REGION` in `.env`), or to a local collector
via `OTEL_EXPORTER_OTLP_ENDPOINT` if no ingestion key is set.

## Layout

```
agent-python/
├── cli/                   # the `overwatch` command
│   ├── app.py             # Typer app: subcommands + no-arg interactive menu
│   ├── doctor.py          # environment diagnostics with remediation hints
│   ├── guide.py           # in-terminal guidance (scenarios pulled live)
│   ├── render.py          # Rich scorecard + variance rendering
│   ├── console.py         # shared console + colour theme
│   └── commands/          # thin wrappers over the underlying functions
├── main.py                # RabbitMQ worker → runs the investigation, streams to Redis
├── config.py              # all env config + MCP launch command builder
├── agent/
│   ├── loop.py            # the direct tool-calling investigation loop
│   ├── tools.py           # tool registry + async dispatcher (obs vs knowledge)
│   ├── prompts.py         # investigation system prompt
│   └── cost_tracker.py    # per-investigation LLM cost/token tracking
├── signoz_mcp/
│   └── client.py          # real SigNoz MCP stdio client + labeled mock fallback
├── knowledge/
│   ├── store.py           # runbook search + incident memory (file-backed)
│   ├── runbooks/*.md      # human-authored playbooks
│   └── memory/incidents.json  # past resolved incidents
├── eval/                  # RCA benchmark: injected incidents + scorer + runner
│   ├── scenarios.py       # 5 incidents with ground truth + red herrings
│   ├── session.py         # scenario-driven telemetry (stand-in for SigNoz)
│   ├── scorer.py          # accuracy / evidence recall / herring resistance
│   └── run_eval.py        # driver → console + last_scorecard.json
└── demo/                  # OTel-instrumented app + fault-injection trigger
```
