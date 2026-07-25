/*
  The wire contract, mirrored from agent-python/agent/loop.py.

  The agent emits five event types over Redis -> gateway -> socket.io:
    status        lifecycle notes; carries signoz_live on the connection event
    thinking      the model reasoning out loud between tool calls
    tool_call     one tool invocation, tagged with its family
    final_report  the parsed RCA
    cost          token/USD totals, emitted once at the end
*/

export type EventType =
  | "status"
  | "thinking"
  | "tool_call"
  | "final_report"
  | "cost";

export type ToolFamily = "observability" | "knowledge" | "unknown";

export interface SigNozLink {
  label: string;
  url: string;
  kind: "trace" | "service" | "logs" | string;
}

export interface Report {
  root_cause: string;
  confidence: "HIGH" | "MEDIUM" | "LOW" | string;
  summary: string;
  evidence?: string[];
  prevention?: string;
  report_md?: string;
  signoz_live?: boolean;
  signoz_links?: SigNozLink[];
}

export interface CostSummary {
  total_cost_usd: number;
  total_tokens: number;
  llm_calls: number;
  model: string | null;
}

export interface AgentEvent {
  incident_id: string;
  type: EventType;
  content?: string;
  data?: Record<string, unknown>;
  /** Client receive time, used for mission-elapsed-time and step durations. */
  receivedAt: number;
}

/** Mission elapsed time: T+MM:SS.d, relative to the first event of the run. */
export function formatMET(ms: number): string {
  if (ms < 0) ms = 0;
  const total = ms / 1000;
  const m = Math.floor(total / 60);
  const s = Math.floor(total % 60);
  const d = Math.floor((total * 10) % 10);
  return `T+${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${d}`;
}

/** Short duration label for a single step. */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** The colour a step's spine node and duration bar take. */
export function accentFor(evt: AgentEvent): string {
  if (evt.type === "final_report") return "var(--color-nominal)";
  if (evt.type === "thinking") return "var(--color-signal)";
  if (evt.type === "status") return "var(--color-ink-3)";
  if (evt.type === "tool_call") {
    return familyOf(evt) === "knowledge"
      ? "var(--color-recall)"
      : "var(--color-trace)";
  }
  return "var(--color-ink-3)";
}

export function familyOf(evt: AgentEvent): ToolFamily {
  const fam = evt.data?.family;
  return fam === "knowledge" || fam === "observability" ? fam : "unknown";
}

export function toolNameOf(evt: AgentEvent): string | null {
  const t = evt.data?.tool;
  return typeof t === "string" ? t : null;
}

/** Row label shown in the trace: the tool name, or the event type. */
export function labelFor(evt: AgentEvent): string {
  return toolNameOf(evt) ?? evt.type.replace("_", " ");
}

export function confidenceColor(confidence: string): string {
  const c = confidence?.toUpperCase();
  if (c === "HIGH") return "var(--color-nominal)";
  if (c === "MEDIUM") return "var(--color-signal)";
  return "var(--color-fault)";
}
