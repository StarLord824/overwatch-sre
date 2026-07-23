# 🛡️ Over-Watch — SigNoz SRE Command Center

> AI-powered incident investigation agent that uses SigNoz as its **exclusive** source of truth.

**Over-Watch** is an autonomous SRE Sidekick that investigates production incidents in real-time. When something breaks, it queries SigNoz traces, logs, metrics, and alerts — formulates hypotheses, gathers evidence, and delivers a structured diagnosis with linked evidence. No guessing, no hallucination.

Built for the [Agents of SigNoz](https://www.wemakedevs.org/hackathons/signoz) hackathon — Track 01: AI & Agent Observability.

---

## ✨ Features

- **🧠 Autonomous Investigation** — ReAct agent that reasons step-by-step, testing hypotheses against real SigNoz data
- **🔍 Deep SigNoz Integration** — All evidence comes exclusively from SigNoz via its API (traces, logs, metrics, alerts)
- **💬 Interactive Chat** — Describe an incident in plain English, watch the agent investigate in real-time
- **🕐 Investigation Timeline** — Step-by-step visualization of the agent's reasoning and SigNoz queries
- **💰 LLM Cost Dashboard** — Per-prompt, per-model token usage and cost tracking with budget alerts
- **🎭 Injectable Demo** — Built-in fault injection for reliable live demos

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                   STREAMLIT UI                       │
│  ┌──────────┐ ┌──────────────┐ ┌─────────────────┐  │
│  │   Chat   │ │  Timeline    │ │ Cost Dashboard   │  │
│  └──────────┘ └──────────────┘ └─────────────────┘  │
└──────────────────┬──────────────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │   ReAct Agent Core  │
        │  (Reason + Act loop)│
        │          │          │
        │  ┌───────▼───────┐  │
        │  │  SigNoz Tools │──────► SigNoz (traces, logs, metrics)
        │  └───────────────┘  │
        └─────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- A running SigNoz instance (cloud or self-hosted)
- An OpenAI API key (for GPT-4o)

### 1. Install Dependencies

```bash
cd overwatch
pip install -e .
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your SigNoz URL, API key, and OpenAI key
```

### 3. Run the Dashboard

```bash
streamlit run app.py
```

### 4. (Optional) Run the Demo Scenario

In a separate terminal, start the instrumented demo app:
```bash
pip install -e ".[demo]"
python demo/sample_app.py
```

Then trigger the incident:
```bash
python demo/trigger_incident.py
```

This sends baseline traffic, injects faults, and creates a real incident in SigNoz for the agent to investigate.

---

## 📁 Project Structure

```
overwatch/
├── app.py                   # Streamlit dashboard (3-panel UI)
├── config.py                # Centralized configuration
├── pyproject.toml            # Project metadata & dependencies
├── .env.example              # Environment variable template
├── agent/
│   ├── core.py               # ReAct investigation loop
│   ├── prompts.py            # System prompts & templates
│   ├── tools.py              # SigNoz API tool wrappers
│   └── cost_tracker.py       # LLM call cost tracking
└── demo/
    ├── sample_app.py          # OTel-instrumented Flask service
    └── trigger_incident.py    # Fault injection & traffic generator
```

---

## ⚖️ Judging Criteria Alignment

| Criteria | How Over-Watch Addresses It |
|----------|---------------------------|
| **Potential Impact** | Automates the first 45 minutes of incident investigation |
| **Creativity & Innovation** | Real-time streaming of AI investigation reasoning |
| **Technical Excellence** | Clean ReAct loop, proper tool abstractions, single-stack |
| **Best Use of SigNoz** | Agent's ONLY data source is SigNoz — traces, logs, metrics, alerts |
| **User Experience** | Polished Streamlit UI with chat, timeline, and cost dashboard |
| **Presentation Quality** | Injectable demo guarantees reliable, impressive live demos |

---

## 🔑 Key Design Decisions

1. **Single-stack Python** over multi-service (Python + Node.js + React) — ships faster, debugs trivially
2. **Streamlit** over custom Next.js — production-quality UI in 1/10th the code
3. **Framework-free ReAct loop** over LangGraph — explicit, debuggable, no magic
4. **SigNoz HTTP API** as the primary integration — works with any SigNoz deployment

---

## 📝 License

MIT

---

Built with ❤️ for the Agents of SigNoz hackathon.
