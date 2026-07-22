# Track 01: AI & Agent Observability
_Trace, monitor, and debug AI-native systems_

## Example Builds

* **AI Agents with E2E Observability on SigNoz**
  * Build Agents and setup E2E observability with SigNoz.
* **Self-Hosted Inference Observability (vLLM)**
  * For example: GPU utilization, queue depth, token throughput correlated with latency.
* **SRE Sidekick with SigNoz MCP**
  * SRE Sidekick built on SigNoz.
  * Debug production issues over call with SigNoz MCP.
* **n8n Workflows with E2E Observability**
  * Build n8n workflows and setup E2E observability with SigNoz.
* **Self-Healing Infra with SigNoz Metrics**
  * For example: A KEDA external scaler or autoscaling advisor driven by SigNoz metrics/anomalies, so a load spike triggers scale-up automatically. (You've already mapped out architectures for this one, so it doubles as a solid reference example.)

## Additional Ideas

* **Observability Slackbot on SigNoz**
* **Deploy Guardian**
  * For example: Correlate CI/CD deployment markers with error/latency regressions and auto-trigger a rollback or a Slack alert with the diff that likely caused it.
* **LLM Cost Tracer**
  * For example: Per-prompt/per-user/per-model cost dashboard plus a budget-spike alert.