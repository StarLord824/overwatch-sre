"use client";

import { CostSummary, formatMET } from "../lib/events";

interface Props {
  connected: boolean;
  incidentId: string | null;
  /** Wall-clock time the current run started, e.g. "14:32:07" - T+MM:SS
   *  alone can't answer "when did this actually happen". */
  startedAt: string | null;
  met: number | null;
  running: boolean;
  cost: CostSummary | null;
  /** null until the agent reports which source it reached. */
  signozLive: boolean | null;
  onSimulate: () => void;
  busy: boolean;
}

function Readout({
  label,
  children,
  width,
}: {
  label: string;
  children: React.ReactNode;
  width?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5" style={{ minWidth: width }}>
      <span className="legend">{label}</span>
      <span className="font-mono text-[13px] text-ink-1 tnum leading-none">
        {children}
      </span>
    </div>
  );
}

export default function StatusRail({
  connected,
  incidentId,
  startedAt,
  met,
  running,
  cost,
  signozLive,
  onSimulate,
  busy,
}: Props) {
  return (
    <header className="border-b border-rule bg-deck/60">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-end gap-x-8 gap-y-5 px-5 py-4 sm:px-7">
        {/* Identity */}
        <div className="mr-auto flex flex-col gap-1.5">
          <span className="legend">Autonomous SRE agent</span>
          <h1 className="font-mono text-[15px] font-medium leading-none tracking-[0.18em] text-ink-1">
            OVER<span className="text-signal">·</span>WATCH
          </h1>
        </div>

        {/* Link state */}
        <Readout label="Gateway" width="84px">
          <span className="inline-flex items-center gap-2">
            <span
              aria-hidden
              className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-nominal" : "bg-fault"} ${connected && running ? "pulse" : ""}`}
            />
            <span className={connected ? "text-ink-1" : "text-fault"}>
              {connected ? "linked" : "no link"}
            </span>
          </span>
        </Readout>

        {/* Telemetry source - only meaningful once the agent has reported it */}
        {signozLive !== null && (
          <Readout label="Telemetry" width="104px">
            <span className={signozLive ? "text-trace" : "text-signal"}>
              {signozLive ? "SigNoz live" : "MOCK data"}
            </span>
          </Readout>
        )}

        <Readout label="Incident" width="132px">
          <span className={incidentId ? "text-ink-1" : "text-ink-3"}>
            {incidentId ?? "--"}
          </span>
        </Readout>

        <Readout label="Elapsed" width="92px">
          <span
            className={running ? "text-signal" : "text-ink-1"}
            title={startedAt ? `Started ${startedAt}` : undefined}
          >
            {met === null ? "T+00:00.0" : formatMET(met)}
          </span>
        </Readout>

        <Readout label="Started" width="76px">
          <span className={startedAt ? "text-ink-1" : "text-ink-3"}>
            {startedAt ?? "--"}
          </span>
        </Readout>

        <Readout label="Cost" width="76px">
          <span className={cost ? "text-ink-1" : "text-ink-3"}>
            {cost ? `$${cost.total_cost_usd.toFixed(4)}` : "--"}
          </span>
        </Readout>

        <Readout label="LLM calls" width="64px">
          <span className={cost ? "text-ink-1" : "text-ink-3"}>
            {cost ? cost.llm_calls : "--"}
          </span>
        </Readout>

        <button
          onClick={onSimulate}
          disabled={busy}
          className="border border-signal/60 bg-signal/10 px-4 py-2 font-mono text-[11px] uppercase tracking-[0.14em] text-signal transition-colors hover:bg-signal/20 disabled:cursor-not-allowed disabled:border-rule disabled:bg-transparent disabled:text-ink-3"
        >
          {busy ? "investigating" : "Simulate alert"}
        </button>
      </div>
    </header>
  );
}
