# 🛡️ Project Over-Watch — System Architecture & Documentation

This document is a component-by-component, decision-by-decision breakdown of
Project Over-Watch: an autonomous SRE investigation agent built for the
**Agents of SigNoz** hackathon (Track 01 — AI & Agent Observability), designed
to replicate and extend [OpenSRE](https://github.com/Tracer-Cloud/opensre)'s
direct-tool-calling-loop philosophy on top of SigNoz.

It is written for hackathon judges, maintainers, and future contributors who
want to understand not just *what* the system does but *why* it's built this
way — including the design decisions we deliberately reversed mid-build.

---

## 0. Design Philosophy — Why This Architecture

Three decisions define this system, each made after checking what actually
works rather than what looks impressive:

1. **Direct tool-calling loop, not a graph framework.** OpenSRE's own
   `AGENTS.md` documents that they moved *away* from graph/chain frameworks
   (like LangGraph) toward a single ReAct loop where the LLM freely picks
   tools. We initially built the brain on LangGraph with a fixed
   `planner → {metrics,log,trace}_agent → synthesizer` DAG — rigid, and it had
   a real bug (an unimported `AIMessage` that would `NameError` on first use).
   We deleted it and rebuilt on a direct loop (§2.1), matching OpenSRE and
   fixing the bug at the same time.

2. **A quantified benchmark, not just a demo.** OpenSRE's actual moat is its
   synthetic RCA benchmark suite (`tests/benchmarks/`) — scored incidents with
   red herrings and closed-vocabulary root-cause classification. A hackathon
   demo that "looks like it works" is not the same claim as "provably gets the
   right answer, resists distractors, and costs $0.05." We built an equivalent
   benchmark (§5) because unproven capability is not a differentiator in a
   crowded "SRE sidekick" hackathon track.

3. **Closes the loop, not just reads.** Most "AI observability copilot" entries
   stop at printing an answer. Over-Watch writes every resolved incident back
   to memory (so a repeat failure is recognised, not re-investigated),
   recommends the specific guard alert that would have caught it earlier, and
   delivers the finished report to Slack/Telegram — the same
   investigate-then-deliver shape OpenSRE uses (§2.2, §6).

   > We originally had the agent *create* the SigNoz alert itself via
   > `signoz_create_alert`. The real tool requires a full Query-Builder v5 rule
   > definition plus a pre-existing notification channel, which an LLM composes
   > unreliably — and our code recorded "created" the moment the tool was
   > called, so a failed creation still appeared successful. Rather than ship a
   > claim we couldn't stand behind, the step became an explicit
   > *recommendation* in the report. See §6.

---

## 1. High-Level Architecture

Three tiers: an ingress/streaming gateway, an autonomous Python agent, and a
live dashboard — connected by RabbitMQ (durable queueing) and Redis (pub/sub
fan-out).

```mermaid
flowchart TD
    SigNoz([SigNoz Alert / Simulate Alert]) -->|POST webhook| Gateway[Node.js Gateway]

    subgraph Gateway Layer
        Gateway -->|publish incident| RabbitMQ[(RabbitMQ<br/>incidents_queue)]
    end

    subgraph Brain Layer — agent-python
        RabbitMQ -->|consume| Main[main.py worker]
        Main -->|mask PII| Mask[utils/masking.py]
        Mask --> Loop[Investigator<br/>direct tool-calling loop]
        Loop <-->|stdio, real tool names| MCP[SigNoz MCP Server<br/>docker/binary subprocess]
        Loop <-->|search / recall / save| Knowledge[(Knowledge & Memory<br/>runbooks + incidents.json)]
        Loop -->|Slack / Telegram| Notify([Report delivery])
        Loop -->|emit every step| Redis[(Redis Pub/Sub<br/>agent_updates)]
    end

    subgraph Frontend Layer
        Redis -->|subscribe| Gateway
        Gateway -->|Socket.io| UI[Next.js Mission Control]
        Gateway -->|final_report| Slack([Slack Webhook])
    end

    subgraph Proof Layer — offline, no infra needed
        Eval[eval.run_eval] -->|injects fixtures| Loop
        Eval --> Judge[LLM Judge<br/>closed-vocab + rubric]
        Judge --> Scorecard[Scorecard:<br/>accuracy, variance, cost]
    end
```

### The Four Layers
1. **Gateway (`gateway-node/`)** — ingress/egress controller. Durable webhook
   intake, Redis→WebSocket bridge, Slack delivery.
2. **Brain (`agent-python/`)** — the autonomous investigator. A single
   tool-calling loop over two tool domains (Observability + Knowledge) that
   saves each resolution to memory and delivers the report onward.
3. **Command Center (`frontend-mission-control/`)** — live dashboard into the
   agent's reasoning, evidence, and prevention guidance.
4. **Proof Layer (`agent-python/eval/`)** — the benchmark that turns "trust us"
   into a number. Runs independently of the other three layers; needs only an
   LLM key, no SigNoz/Docker/RabbitMQ.

---

## 2. The Brain: `agent-python/`

### 2.1 The Investigation Loop (`agent/loop.py`)

The `Investigator` class is the entire agent. No graph, no chain, no planner
node — one loop:

```
messages = [system_prompt, alert_as_user_message]
open one SigNoz MCP session for the whole investigation
loop up to MAX_ITERATIONS (12):
    response = LLM(messages, tools=ALL_TOOLS, tool_choice="auto")
    if response wants tool calls:
        emit "thinking" (if the model also reasoned in text)
        execute every requested tool call, append results to messages
        emit "tool_call" per call
        continue
    else:  # model produced a final answer, no more tool calls
        parse the Markdown into a structured report
        attach SigNoz deep-links, then deliver to Slack/Telegram
        emit "final_report", emit "cost"
        return report
```

Key implementation details:

- **Streaming via `emit` callback.** Every step — `status`, `thinking`,
  `tool_call`, `final_report`, `cost` — is pushed through a synchronous
  callback. In production (`main.py`) this callback publishes to Redis; in the
  benchmark it appends to an in-memory list. Same agent code, two consumers.
- **Guardrail:** hard cap of `MAX_ITERATIONS = 12`. If the loop doesn't
  converge, it emits a degraded `final_report` rather than hanging.
- **Injectable telemetry source.** `Investigator.__init__(signoz=...)` accepts
  any object exposing `.session()` / `.call(name, args)` / `.is_live`. In
  production this is `SigNozMCP` (real stdio session); in the benchmark it's
  `ScenarioSigNoz` (fixture-driven). This one seam is what lets the exact same
  agent code run against fixtures, mocks, or live SigNoz — see §5.
- **Model-agnostic temperature handling.** GPT-5 / o-series / Codex reasoning
  models reject a custom `temperature` parameter outright (only the API
  default is accepted). `config.model_supports_temperature()` detects the
  model family and the loop omits `temperature` for those models instead of
  crashing — verified against `gpt-4o`, `gpt-4.1`, `gpt-5.3-codex`, `o1`,
  `o3-mini`, `o4`.
- **Finalize + deliver.** Once the model stops calling tools, `_finalize`
  attaches `signoz_links` (deep links built from every trace ID/service cited
  in the report — §2.5), then `_deliver` posts the report to Slack/Telegram if
  configured (§6) and emits a `status` event naming the channels it reached.

### 2.2 The System Prompt (`agent/prompts.py`)

The prompt encodes the investigation *method*, not just the tool list — this
is what makes the agent behave like a senior SRE instead of a keyword-matcher:

1. **Check memory and runbooks FIRST** (`recall_similar_incidents`,
   `search_runbooks`) — if this exact failure happened before, don't
   re-derive it from scratch, but still confirm against live data.
2. **Form 1–3 testable hypotheses**, stated explicitly in reasoning.
3. **Test each hypothesis against real telemetry**, following the causal
   chain: list services → find the failing/slow trace → follow it downstream
   → confirm with logs and metrics. Every claim must cite something the agent
   actually observed (trace ID, log line + timestamp, metric value) —
   explicit anti-hallucination instruction, and MOCK-sourced data must be
   labeled as such in the report.
4. **Close the loop before finishing**: call `save_incident_memory` so the next
   occurrence is recognised instantly, and recommend a guard alert in the
   Prevention section targeting the *leading* signal (e.g. "pool nearing
   saturation") — not a duplicate of the alert that already fired.
5. **Final report is a fixed 5-section Markdown template** — Root Cause,
   Confidence, Evidence, Recommended Remediation, Prevention — parsed
   deterministically by `_parse_report()` via section-heading regex, with
   graceful fallback if the model doesn't follow the template exactly (root
   cause defaults to the first 400 chars; confidence defaults to MEDIUM if no
   HIGH/MEDIUM/LOW token is found).

### 2.3 Tool Registry (`agent/tools.py`)

A single flat list of **9 tools** presented to the LLM, split into two
families the dispatcher routes independently:

| Family | Tools | Backend |
|---|---|---|
| `observability` | `signoz_list_services`, `signoz_search_traces`, `signoz_get_trace_details`, `signoz_search_logs`, `signoz_query_metrics`, `signoz_list_alerts` | SigNoz MCP session |
| `knowledge` | `search_runbooks`, `recall_similar_incidents`, `save_incident_memory` | Local `KnowledgeStore` |

`dispatch(name, arguments, signoz_session, knowledge)` is the single async
entrypoint every tool call goes through — verified offline that all 9 tools
are unique, every tool classifies into exactly one family, and the
observability schema names match the MCP client's real tool set exactly (no
drift between what's advertised to the LLM and what's dispatchable).

### 2.4 SigNoz MCP Client (`signoz_mcp/client.py`)

The window into production telemetry — and the piece we were most careful to
get *factually correct* rather than plausible-looking, because the original
LangGraph-era client invented tool names (`signoz_get_logs`,
`check_metric_usage`) that don't exist on the real server and used a naive
single-POST JSON-RPC call against a transport the real server doesn't speak
that way.

**Real transport:** the official SigNoz MCP server
(`signoz/signoz-mcp-server`) speaks **stdio** (default) or **streamable
HTTP**. We use stdio: the agent spawns the server as a subprocess via the
official `mcp` Python SDK (`StdioServerParameters` + `stdio_client` +
`ClientSession`), performs the real `initialize` handshake, then calls
`list_tools()` to confirm what's actually available before trusting any tool
name.

**Real tool names used** (verified against the SigNoz MCP server's own
documented parameter schemas, not guessed):
- `signoz_list_services(timeRange, limit)`
- `signoz_search_traces(service, operation, error, minDuration, timeRange, limit)`
- `signoz_search_logs(service, severity, searchText, timeRange, limit)`
- `signoz_query_metrics(metricName, timeAggregation, spaceAggregation, filter, timeRange)`
- `signoz_list_alerts(active, limit)`
- `signoz_get_trace_details(traceId)`
(`signoz_create_alert` exists on the server but is deliberately not exposed to
the agent — see §0 and §6.)

**Docker networking fix.** From *inside* the spawned MCP container,
`localhost` refers to the container itself, not the host — a subtle failure
mode that silently breaks connectivity to a host-run SigNoz instance.
`config.signoz_mcp_launch()` auto-rewrites `localhost` / `127.0.0.1` /
`0.0.0.0` in `SIGNOZ_URL` to `host.docker.internal` and adds
`--add-host host.docker.internal:host-gateway` (for Linux Docker parity with
Docker Desktop). Cloud URLs and real host IPs pass through untouched —
verified with unit tests distinguishing all three cases.

**Demo safety — labeled MOCK fallback.** If the MCP server can't be reached
(image not pulled, SigNoz down, offline demo), every tool call transparently
falls back to `_MockSession`, which returns a coherent, hand-authored incident
story (pool exhaustion, matching logs, matching metrics) so a live demo never
hard-crashes. Every mock payload is tagged `"_source": "MOCK"`, and the
investigation's `signoz_live` flag propagates to the final report and the
dashboard status banner — so mocked evidence is never silently mistaken for
real telemetry, in the UI or in the benchmark.

**Preflight smoke test (`signoz_mcp/smoke.py`).** Before trusting a `--live`
benchmark run or a demo, `uv run overwatch doctor --deep` spawns the MCP
server, confirms the handshake, lists the tools actually available, and
executes one real `signoz_list_services` call — exits 0 if genuinely
connected, 1 (with a targeted checklist) if it fell back to mock. This exists
because discovering "I was on mock the whole time" mid-demo is the single
worst failure mode for this project.

### 2.5 SigNoz Deep Links (`signoz_mcp/links.py`)

Part of "closing the loop": a finished report is post-processed to extract
every trace ID cited in the Markdown (12–32 hex chars containing at least one
letter, so pure-decimal timestamps/durations are never mistaken for trace IDs
— verified against exactly that case) and the alerting service, and turns
each into a clickable SigNoz UI URL (`/trace/{id}`, `/services/{name}`,
`/logs?service={name}`). These render as an "Open in SigNoz" button row on the
dashboard (§4.1) — an engineer can jump from "the agent says trace `a1b2c3`
shows the failure" straight into the real trace view.

### 2.6 Knowledge & Memory Layer (`knowledge/store.py`)

File-backed, deliberately simple (keyword/token-overlap matching — no vector
DB to stand up for a hackathon), and it is the literal "Knowledge" +
"Memories" boxes from the target architecture diagram:

- **Runbooks** (`knowledge/runbooks/*.md`) — human-authored playbooks
  (`checkout-5xx.md`, `latency-spike.md`) with symptoms, ranked root causes,
  and investigation steps. `search_runbooks(query)` scores by token overlap
  and returns the top matches.
- **Incident memory** (`knowledge/memory/incidents.json`) — an append-only
  log of resolved incidents. `recall_similar_incidents(description)` scores
  past incidents by signature overlap; `save_incident_memory(title,
  root_cause, summary, confidence)` appends the new resolution. Every real
  and benchmark investigation grows this file, so the system literally gets
  faster at recognizing repeat failures over time.

### 2.7 Data Sanitization (`utils/masking.py`)

A regex-based PII scrubber applied to the raw alert payload *before* it ever
reaches the LLM: emails → `[REDACTED_EMAIL]`, IPs → `[REDACTED_IP]`, phone
numbers → `[REDACTED_PHONE]`, SSN-shaped strings → `[REDACTED_SSN]`. Recurses
through nested dicts/lists in the payload.

### 2.8 Cost Tracking (`agent/cost_tracker.py`)

Every LLM call (agent loop + judge) is recorded with prompt/completion tokens,
latency, and an estimated USD cost from a per-model pricing table (`gpt-4o`,
`gpt-4o-mini`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano`, `gpt-5.3-codex`,
etc.). `CostTracker.summary()` is emitted as a `"cost"` event at the end of
every investigation — this is the built-in "LLM Cost Tracer" from the
hackathon's own idea list, delivered as a feature rather than a separate
service.

### 2.9 The Entrypoint (`main.py`)

Consumes `incidents_queue` from RabbitMQ (`pika`, `prefetch_count=1` for
one-at-a-time processing, durable queue). Per incident: sanitize → construct
an `Investigator` whose `emit` callback publishes straight to the
`agent_updates` Redis channel → run `investigate()` → ack on success, nack
(no requeue — a fixed bug from the LangGraph era, which would otherwise
poison-loop a message forever) on failure.

---

## 3. The Gateway: `gateway-node/`

Express + Socket.io + `amqplib` + `redis`. The traffic controller between
SigNoz, the agent, the dashboard, and Slack.

### 3.1 Webhook Ingestion (`routes/webhook.js`)
`POST /api/webhooks/signoz` accepts the raw SigNoz alert payload, wraps it in
a standardized incident envelope (`id`, `source`, `timestamp`, `raw_payload`),
and pushes it onto RabbitMQ's `incidents_queue` (persistent message) —
guaranteeing the alert survives even if the Python agent is temporarily down.

### 3.2 Real-Time Pub/Sub Bridge (`queue/redis.js`, `index.js`)
Subscribes to the `agent_updates` Redis channel. Every event the Python agent
publishes (`status`, `thinking`, `tool_call`, `final_report`, `cost`) is
immediately re-broadcast to all connected dashboard clients via
`io.emit('agent_event', event)`.

### 3.3 Slack Integration (`services/slack.js`)
On a `final_report` event, formats the RCA (root cause, confidence, summary,
evidence chain) into Slack Block Kit and posts it to a configured webhook —
color-coded by confidence (green/amber/red).

---

## 4. The Command Center: `frontend-mission-control/`

Next.js App Router + Tailwind CSS.

### 4.1 Live Reasoning Stream + Diagnosis (`src/app/page.tsx`)
- **WebSocket connection** to the Gateway via `socket.io-client`.
- **Left panel** — a terminal-style live console of every streamed event as
  it happens, giving full transparency into *how* the agent is investigating,
  not just the final answer.
- **Right panel**, once `final_report` arrives:
  - Root Cause, Confidence badge, Summary/Remediation
  - **Evidence Chain** — numbered citations
  - **🛡️ Prevention · Self-Improving card** — renders the agent's Prevention
    section text plus each guard alert it created (`created_alerts[]`, with
    name + condition), visually distinct (green) from the rest of the report
    so the prevention guidance is visible at a glance
  - **Open in SigNoz** — clickable deep-link buttons from `signoz_links[]`
- **Simulate Alert button** — bypasses SigNoz entirely, POSTs a synthetic
  alert straight to the Gateway webhook, for a 100%-reliable live demo path.

---

## 5. The Proof Layer: `agent-python/eval/`

This is the piece that separates Over-Watch from a plausible-looking demo:
a reproducible, adversarial benchmark modeled on OpenSRE's own
`tests/benchmarks/` suite (LLM judge + closed-vocabulary classification +
rubric grading + variance across trials — not naive keyword matching).

### 5.1 Why keyword matching alone isn't enough

An earlier version of this harness scored correctness by substring matching
against expected keywords. It produces both false negatives (agent says
"connection pool saturated," fixture expects the literal string "hit ratio" —
scored wrong despite being right) and false positives (agent parrots the
alert's own wording). Real run data showed exactly this: **cache-stampede**
scored `FAIL` under keyword matching purely because the agent said "hit-rate
collapse" instead of the fixture's literal "hit ratio" — the LLM judge (below)
correctly classified it as `cache_stampede`, the true cause, once introduced.

### 5.2 Scenarios (`eval/scenarios.py`)

**5 injected incidents**, each a distinct failure class with a **planted red
herring** pointing at a plausible-but-wrong distractor service/signal:

| Scenario | True cause | Red herring |
|---|---|---|
| `checkout-pool-exhaustion` | payment-gateway connection pool exhaustion | inventory-service OOM log |
| `cpu-saturation-latency` | search-service CPU throttling | unrelated cart-service deploy marker |
| `bad-deploy-npe` | NullPointerException from v2.4.1 deploy | postgres latency (actually normal nightly batch) |
| `cache-stampede` | Redis cache eviction → DB read amplification | transient network/packet-loss alert |
| `third-party-timeout` | external Stripe API timeout | internal JVM GC pause (minor, unrelated) |

Each scenario carries: full injected telemetry (services, traces, trace
details, logs, metrics, alerts), `expected_keywords` / `required_evidence` /
`forbidden_keywords` (keyword-fallback ground truth), and — the harder,
judge-graded ground truth — a `category`, a `root_cause_class` from a **closed
vocabulary** (`CLASS_VOCAB`: 5 true classes + 3 distractor classes the red
herrings point at), and a **rubric**: 3 specific scoring points per scenario
(e.g. "does NOT blame inventory-service's OutOfMemory log").

### 5.3 Scenario-Driven Telemetry Session (`eval/session.py`)

`ScenarioSigNoz` is a drop-in replacement for the real SigNoz MCP session —
same `.session()` / `.call(name, args)` / `.is_live` interface the
`Investigator` expects — that serves each scenario's fixture data instead of
a live server. This is the seam (§2.1) that lets the exact same agent code run
deterministically with **zero SigNoz, zero Docker**, only an LLM key. Includes
fuzzy metric-name matching (`connection_pool` → `connection_pool_active`) so
minor tool-argument variance doesn't break fixture lookup.

### 5.4 The LLM Judge (`eval/judge.py`)

A second, cheap model call (`EVAL_JUDGE_MODEL`, default `gpt-4o-mini`) grades
each finished report:
1. **Classifies** the agent's concluded root cause into exactly one class from
   the closed vocabulary — an exact class match, so vague or hedged answers
   can't pass.
2. **Grades** the report against the scenario's rubric, returning which
   specific points were satisfied.

Robust JSON extraction (fenced code blocks, raw JSON, or brace-scanning
fallback) handles model output variance. **Fully optional and gracefully
degrading**: no API key or any judge-call failure → `available=False` →
scorer automatically falls back to keyword matching, and the scorecard prints
*why* judge scoring didn't happen rather than silently mis-reporting.

### 5.5 Scoring (`eval/scorer.py`)

Per-scenario: `root_cause_correct` (judge class-match when available, else
keyword), `evidence_recall`, `herring_resisted` (did the *concluded* cause
avoid the forbidden/distractor tokens?), plus run metadata (LLM calls, tool
calls, cost, whether memory/runbooks were consulted). `Scorecard` aggregates:
accuracy, pass rate, mean evidence recall, mean rubric score, herring
resistance, cost/incident, LLM calls/incident, and **per-category
breakdown**.

### 5.6 Variance, Not a Single Run (`eval/run_eval.py`)

LLMs are nondeterministic — one run is not a defensible number. `--trials N`
repeats the full scenario suite N times and reports **mean ± population
stdev** per metric across trials, so "80% accuracy" versus "80% ± 0pp
accuracy across 3 trials" are visibly different claims.

**Transient-failure resilience** (added after real runs hit this): a
rate-limited API call is an infrastructure hiccup, not a wrong diagnosis.
`_run_one` retries an entire scenario up to 3× with backoff (15s × attempt) on
detected transient errors (`RateLimit`, `429`, `Timeout`, connection errors)
before it's allowed to count as a failure; `--pace` (default 6s) throttles
between scenarios to stay under low tokens-per-minute API tiers; both OpenAI
clients (`agent/loop.py`, `eval/judge.py`) set `max_retries` so the SDK rides
out 429s via `Retry-After` automatically.

**CLI:**
```bash
uv run overwatch eval --list          # scenario ids, no LLM
uv run overwatch eval --dry-run        # validate fixtures+scorer, no LLM
uv run overwatch eval --trials 3       # the real benchmark + variance
uv run overwatch eval --no-judge       # keyword-only scoring
uv run overwatch eval --live           # investigate real SigNoz instead of fixtures
uv run overwatch eval --pace 8         # more headroom for low-TPM API tiers
```

### 5.7 Actual Measured Result

Run on `gpt-4.1` (agent) + `gpt-4.1` (judge), 3 trials, judge-scored, against
this repository's own fixtures:

```
RCA accuracy        : 100%  (5/5)                    — mean 100% ± 0pp across 3 trials
Full pass rate       : 100%  (correct AND herring-resistant)
Rubric score         : 100%  (all judge rubric points satisfied)
Herring resistance   : 100%  (never fooled by a planted distractor, any trial)
Evidence recall      : 80–90% (mean; see §5.1 — the one sub-100 number, and why it's honest)
Cost / incident      : ~$0.048–0.058
LLM calls / incident : ~6.6–7.0
```

Zero variance across trials on the headline metrics is the load-bearing claim
here — it means this isn't a lucky single run.

---

## 6. Closing the Loop — Memory, Prevention, Delivery

An investigation that ends at a printed answer wastes most of its value. Three
mechanisms carry it forward, tying together §2.1, §2.2, §2.6 and §4.1:

**1. Memory — the genuinely self-improving part.**
`save_incident_memory` writes the resolution into
`knowledge/memory/incidents.json`. On the *next* investigation of the same
failure mode, `recall_similar_incidents` surfaces it in the agent's first tool
call and short-circuits the reasoning. This is measurable: a repeat live
investigation of the same incident dropped from **10 LLM calls to 4**, and from
**$0.10 to $0.067**, once memory contained the prior resolution.

**2. Prevention — a recommendation, honestly labelled.**
The prompt requires a **Prevention** section naming the guard alert (name +
condition + why) on the *leading* signal that would have caught this failure
earlier — e.g. "connection_pool_active >= 18 for 2m," not a duplicate of the
alert that already fired. `_parse_report` extracts it via
`_section(md, "Prevention")`, and the dashboard (§4.1) renders it as a distinct
green **Prevention · Recommended Guard Alert** card.

> **Why recommend, not create?** We first had the agent call
> `signoz_create_alert` directly. Inspecting the real tool's schema (via
> `signoz_mcp/inspect.py`) showed why that was fragile: it requires a full
> Query-Builder v5 `compositeQuery`, a `thresholds` spec, and *at least one
> pre-existing notification channel* — a payload an LLM composes unreliably. It
> also failed silently: our code recorded the alert as "created" the moment the
> tool was called, so a rejected creation still showed as success in the
> report. Presenting a recommendation the engineer applies is the claim we can
> actually stand behind.

**3. Delivery — the report reaches the human (`agent/notify.py`).**
`_deliver` posts the finished RCA to **Slack** (Block Kit, colour-coded by
confidence) and/or **Telegram**, including the evidence chain, the prevention
recommendation, and clickable SigNoz deep-links. Configured entirely by env
(`SLACK_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) and a silent
no-op when unset, so the agent runs identically with or without it. This
mirrors OpenSRE's final step: the on-call engineer never has to go looking for
the answer.

---

## 7. Infrastructure: `docker-compose.yml`

Root-level compose spins up the two stateful services on an isolated
`overwatch-net` bridge network:
- **RabbitMQ** (`rabbitmq:3-management-alpine`) — AMQP on `5672`, management
  UI on `15672`, with a healthcheck (`rabbitmq-diagnostics -q ping`).
- **Redis** (`redis:7-alpine`) — pub/sub on `6379`, healthcheck (`redis-cli
  ping`).

The SigNoz MCP server itself is **not** in this compose file — it's spawned
on-demand as a stdio subprocess by the agent (§2.4), not run as a long-lived
service, matching how MCP servers are normally consumed by an agent host.

See [`SETUP-LIVE.md`](SETUP-LIVE.md) for the full live-SigNoz runbook: standing
up self-hosted SigNoz, pulling the MCP image, the preflight smoke test,
generating real telemetry via the OTel-instrumented demo app
(`agent-python/demo/`), and running either `--live` benchmark or the full
webhook→dashboard pipeline end to end.

---

## 8. Judging Criteria Alignment

| Criterion | How this architecture addresses it |
|---|---|
| **Potential Impact** | Automates the first ~45 minutes of incident investigation; incident memory (§6) compounds that value — a repeat failure resolved in 4 LLM calls instead of 10. |
| **Creativity & Innovation** | Not just "SigNoz + LLM chat" — the agent *writes back* to SigNoz (new alerts) and to its own memory, and the benchmark (§5) is itself a novel proof mechanism most entries in this track won't have. |
| **Technical Excellence** | Real MCP protocol (not guessed tool names), a documented and fixed Docker-networking failure mode, retry/backoff resilience, model-family-aware API calls, and — the strongest evidence — a variance-checked benchmark, not just "it ran once." |
| **Best Use of SigNoz** | Every observability tool call goes through the genuine SigNoz MCP server over stdio with correct tool names/params (§2.4), verified against a live SigNoz Cloud instance using traces, logs and metrics from a two-service demo. |
| **User Experience** | One `overwatch` command with an interactive menu and a `doctor` that names the exact fix for every broken check; real-time reasoning stream, evidence chain with clickable SigNoz deep-links, Prevention card, Slack delivery, one-click demo trigger. |
| **Presentation Quality** | This document + `SETUP-LIVE.md` + the reproducible `--trials 3` scorecard mean the claims in the demo are independently checkable, not just asserted. |
