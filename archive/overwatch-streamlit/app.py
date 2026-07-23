"""
Over-Watch: SigNoz SRE Command Center
======================================
Streamlit dashboard with three panels:
  1. SRE Sidekick Chat — interact with the investigation agent
  2. Investigation Timeline — step-by-step view of the agent's reasoning
  3. LLM Cost Dashboard — per-prompt, per-model cost tracking

Run: streamlit run app.py
"""

import json
import time

import streamlit as st

from agent.core import SREAgent, AgentStep
from agent.cost_tracker import CostTracker
from agent.prompts import ALERT_CONTEXT_TEMPLATE, USER_QUERY_TEMPLATE


# ── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Over-Watch · SRE Command Center",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS for premium look ──────────────────────────────────────────────

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    /* Global */
    .stApp {
        font-family: 'Inter', sans-serif;
    }

    /* Header */
    .main-header {
        background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 50%, #0d1b2a 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        border: 1px solid rgba(99, 102, 241, 0.2);
        box-shadow: 0 4px 24px rgba(99, 102, 241, 0.08);
    }
    .main-header h1 {
        color: #e0e7ff;
        font-size: 1.8rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.02em;
    }
    .main-header p {
        color: #94a3b8;
        font-size: 0.9rem;
        margin: 0.3rem 0 0 0;
    }

    /* Status badge */
    .status-badge {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .status-ready { background: #065f46; color: #6ee7b7; }
    .status-investigating { background: #92400e; color: #fbbf24; }
    .status-done { background: #1e3a5f; color: #60a5fa; }

    /* Timeline step cards */
    .step-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 0.75rem;
        transition: border-color 0.2s;
    }
    .step-card:hover {
        border-color: #6366f1;
    }
    .step-thinking { border-left: 3px solid #8b5cf6; }
    .step-tool { border-left: 3px solid #06b6d4; }
    .step-report { border-left: 3px solid #10b981; }

    .step-label {
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.4rem;
    }
    .label-thinking { color: #8b5cf6; }
    .label-tool { color: #06b6d4; }
    .label-report { color: #10b981; }

    /* Tool call details */
    .tool-detail {
        background: #f1f5f9;
        border-radius: 6px;
        padding: 0.6rem 0.8rem;
        margin-top: 0.5rem;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.78rem;
        color: #334155;
    }

    /* Cost metric cards */
    .cost-card {
        background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
        border-radius: 10px;
        padding: 1.2rem;
        text-align: center;
        border: 1px solid rgba(99, 102, 241, 0.3);
    }
    .cost-card .value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #e0e7ff;
        font-family: 'JetBrains Mono', monospace;
    }
    .cost-card .label {
        font-size: 0.78rem;
        color: #a5b4fc;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-top: 0.3rem;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ── Session State Init ───────────────────────────────────────────────────────

if "cost_tracker" not in st.session_state:
    st.session_state.cost_tracker = CostTracker()

if "agent" not in st.session_state:
    st.session_state.agent = SREAgent(cost_tracker=st.session_state.cost_tracker)

if "messages" not in st.session_state:
    st.session_state.messages = []

if "investigation_steps" not in st.session_state:
    st.session_state.investigation_steps = []

if "status" not in st.session_state:
    st.session_state.status = "ready"


# ── Header ───────────────────────────────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <h1>🛡️ Over-Watch · SRE Command Center</h1>
    <p>AI-powered incident investigation — powered exclusively by SigNoz</p>
</div>
""", unsafe_allow_html=True)


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙️ Configuration")

    signoz_url = st.text_input(
        "SigNoz URL",
        value="http://localhost:3301",
        help="Base URL of your SigNoz instance",
    )
    signoz_key = st.text_input(
        "SigNoz API Key",
        type="password",
        help="API key for SigNoz access",
    )
    llm_model = st.selectbox(
        "LLM Model",
        ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        index=0,
    )

    st.divider()

    st.markdown("### 🎯 Quick Actions")

    # Pre-built alert scenarios for demo
    if st.button("🔴 Simulate Alert", use_container_width=True):
        st.session_state.demo_alert = ALERT_CONTEXT_TEMPLATE.format(
            alert_name="High Error Rate — checkout-service",
            severity="CRITICAL",
            service="checkout-service",
            triggered_at=time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            description="Error rate exceeded 15% threshold for checkout-service in the last 5 minutes",
            additional_context="Related services: payment-gateway, inventory-service. Recent deployment: v2.4.1 rolled out 20 minutes ago.",
        )

    if st.button("🧹 Clear Session", use_container_width=True):
        st.session_state.messages = []
        st.session_state.investigation_steps = []
        st.session_state.cost_tracker = CostTracker()
        st.session_state.agent = SREAgent(cost_tracker=st.session_state.cost_tracker)
        st.session_state.status = "ready"
        st.rerun()

    st.divider()

    # Status indicator
    status = st.session_state.status
    status_class = {
        "ready": "status-ready",
        "investigating": "status-investigating",
        "done": "status-done",
    }.get(status, "status-ready")
    status_label = status.upper()
    st.markdown(
        f'<span class="status-badge {status_class}">{status_label}</span>',
        unsafe_allow_html=True,
    )


# ── Main Layout: Three Panels ────────────────────────────────────────────────

col_chat, col_timeline, col_cost = st.columns([2, 1.5, 1.2])


# ── Panel 1: SRE Sidekick Chat ──────────────────────────────────────────────

with col_chat:
    st.markdown("### 💬 SRE Sidekick")

    # Display chat history
    chat_container = st.container(height=500)
    with chat_container:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"], avatar="🛡️" if msg["role"] == "assistant" else "👤"):
                st.markdown(msg["content"])

    # Check for simulated alert
    if "demo_alert" in st.session_state:
        user_input = st.session_state.pop("demo_alert")
    else:
        user_input = None

    # Chat input
    prompt = st.chat_input("Describe the incident or paste an alert...")

    if prompt:
        user_input = USER_QUERY_TEMPLATE.format(query=prompt)

    if user_input:
        # Add user message
        display_msg = user_input[:300] + "..." if len(user_input) > 300 else user_input
        st.session_state.messages.append({"role": "user", "content": display_msg})

        st.session_state.status = "investigating"

        # Run investigation
        agent = st.session_state.agent
        full_response = ""

        with chat_container:
            with st.chat_message("user", avatar="👤"):
                st.markdown(display_msg)

            with st.chat_message("assistant", avatar="🛡️"):
                response_placeholder = st.empty()
                step_counter = 0

                try:
                    for step in agent.investigate(user_input):
                        step_counter += 1
                        st.session_state.investigation_steps.append(step)

                        if step.step_type == "thinking":
                            full_response += f"\n\n🧠 **Reasoning (Step {step_counter})**\n{step.content}\n"
                            response_placeholder.markdown(full_response)

                        elif step.step_type == "tool_call":
                            tool_summary = "\n".join(
                                f"- `{tc.tool_name}({json.dumps(tc.arguments, indent=None)[:80]})`"
                                for tc in step.tool_calls
                            )
                            full_response += f"\n\n🔧 **SigNoz Query (Step {step_counter})**\n{tool_summary}\n"
                            response_placeholder.markdown(full_response)

                        elif step.step_type == "final_report":
                            full_response += f"\n\n{step.content}"
                            response_placeholder.markdown(full_response)

                except Exception as e:
                    full_response += f"\n\n❌ **Error**: {str(e)}"
                    response_placeholder.markdown(full_response)

        st.session_state.messages.append({"role": "assistant", "content": full_response})
        st.session_state.status = "done"
        st.rerun()


# ── Panel 2: Investigation Timeline ─────────────────────────────────────────

with col_timeline:
    st.markdown("### 🕐 Investigation Timeline")

    timeline_container = st.container(height=500)
    with timeline_container:
        if not st.session_state.investigation_steps:
            st.markdown(
                '<p style="color: #94a3b8; text-align: center; padding-top: 4rem;">'
                "Start an investigation to see the agent's reasoning steps here.</p>",
                unsafe_allow_html=True,
            )
        else:
            for i, step in enumerate(st.session_state.investigation_steps):
                step_class = {
                    "thinking": "step-thinking",
                    "tool_call": "step-tool",
                    "final_report": "step-report",
                }.get(step.step_type, "")
                label_class = {
                    "thinking": "label-thinking",
                    "tool_call": "label-tool",
                    "final_report": "label-report",
                }.get(step.step_type, "")
                icon = {"thinking": "🧠", "tool_call": "🔧", "final_report": "📋"}.get(
                    step.step_type, "•"
                )

                st.markdown(
                    f'<div class="step-card {step_class}">'
                    f'<div class="step-label {label_class}">{icon} Step {i+1} · {step.step_type.replace("_", " ").title()}</div>'
                    f"{step.content[:150]}{'...' if len(step.content) > 150 else ''}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                # Show tool details
                if step.tool_calls:
                    for tc in step.tool_calls:
                        st.markdown(
                            f'<div class="tool-detail">'
                            f"<strong>{tc.tool_name}</strong>"
                            f"({json.dumps(tc.arguments, indent=None)[:120]})"
                            f"</div>",
                            unsafe_allow_html=True,
                        )


# ── Panel 3: LLM Cost Dashboard ─────────────────────────────────────────────

with col_cost:
    st.markdown("### 💰 Cost Dashboard")

    tracker = st.session_state.cost_tracker

    # Metric cards
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f'<div class="cost-card">'
            f'<div class="value">${tracker.total_cost:.4f}</div>'
            f'<div class="label">Total Cost</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="cost-card">'
            f'<div class="value">{tracker.total_tokens:,}</div>'
            f'<div class="label">Total Tokens</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("")  # Spacer

    c3, c4 = st.columns(2)
    with c3:
        st.markdown(
            f'<div class="cost-card">'
            f'<div class="value">{tracker.call_count}</div>'
            f'<div class="label">LLM Calls</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
    with c4:
        avg_latency = (
            sum(r.latency_ms for r in tracker.records) / len(tracker.records)
            if tracker.records
            else 0
        )
        st.markdown(
            f'<div class="cost-card">'
            f'<div class="value">{avg_latency:.0f}ms</div>'
            f'<div class="label">Avg Latency</div>'
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("")

    # Cost by model
    if tracker.records:
        st.markdown("**Cost by Model**")
        cost_by_model = tracker.cost_by_model()
        for model, cost in cost_by_model.items():
            st.markdown(f"- `{model}`: **${cost:.4f}**")

        # Cost by purpose/phase
        st.markdown("**Cost by Phase**")
        cost_by_purpose = tracker.cost_by_purpose()
        for purpose, cost in cost_by_purpose.items():
            st.markdown(f"- {purpose}: **${cost:.4f}**")

        # Detailed call log
        with st.expander("📊 Detailed Call Log"):
            st.dataframe(
                tracker.to_display_records(),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.markdown(
            '<p style="color: #94a3b8; text-align: center; padding-top: 2rem;">'
            "No LLM calls yet.</p>",
            unsafe_allow_html=True,
        )
