"use client";

import { useEffect, useRef } from "react";
import {
  AgentEvent,
  accentFor,
  familyOf,
  formatDuration,
  formatMET,
  labelFor,
  toolNameOf,
} from "../lib/events";

interface Props {
  events: AgentEvent[];
  t0: number | null;
  running: boolean;
  /** Ticks while running so the in-flight row's duration stays live. */
  now: number;
}

/*
  The signature of this console.

  An investigation *is* a trace: a sequence of spans, some of them nested. So it
  is drawn as one - a spine with nodes, tool calls indented as children of the
  reasoning that requested them, and a duration bar per step. Engineers who read
  SigNoz waterfalls all day can read this without being taught it.

  The gutter shows mission-elapsed time rather than wall clock, because during
  an incident the question is never "what time is it" - it is "how long has this
  been going on".
*/

function compactArgs(args: unknown): string | null {
  if (!args || typeof args !== "object") return null;
  const entries = Object.entries(args as Record<string, unknown>)
    .filter(([, v]) => v !== "" && v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  return entries.length ? entries.join("  ") : null;
}

export default function TraceStream({ events, t0, running, now }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  // Step duration = gap until the next event. The final row is still open
  // while the run is live, so it measures against the ticking clock.
  const durations = events.map((e, i) => {
    const next = events[i + 1];
    if (next) return next.receivedAt - e.receivedAt;
    return running ? Math.max(0, now - e.receivedAt) : 0;
  });
  const longest = Math.max(1, ...durations);

  return (
    <section className="flex min-h-[60vh] flex-col border border-rule bg-deck/40 lg:min-h-0">
      <div className="flex items-center justify-between border-b border-rule px-4 py-3">
        <h2 className="legend">Investigation trace</h2>
        <span className="legend">
          {events.length} {events.length === 1 ? "span" : "spans"}
        </span>
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {events.length === 0 ? (
          <div className="flex h-full min-h-[280px] flex-col items-center justify-center gap-3 text-center">
            <div className="h-px w-16 bg-rule-bright" />
            <p className="font-mono text-[13px] text-ink-2">Standing by.</p>
            <p className="max-w-xs text-[13px] leading-relaxed text-ink-3">
              Trigger an alert to begin an investigation. Every step the agent
              takes appears here as it happens.
            </p>
          </div>
        ) : (
          <ol className="relative">
            {/* the spine */}
            <span
              aria-hidden
              className="absolute bottom-2 left-[92px] top-2 w-px bg-rule"
            />

            {events.map((evt, i) => {
              const accent = accentFor(evt);
              const isTool = evt.type === "tool_call";
              const isReport = evt.type === "final_report";
              const dur = durations[i];
              const open = running && i === events.length - 1;
              const args = isTool ? compactArgs(evt.data?.args) : null;
              const tool = toolNameOf(evt);

              return (
                <li key={i} className="enter relative flex gap-3 pb-5">
                  {/* MET gutter */}
                  <span className="w-[76px] shrink-0 pt-[3px] text-right font-mono text-[11px] tnum text-ink-3">
                    {t0 !== null ? formatMET(evt.receivedAt - t0) : ""}
                  </span>

                  {/* spine node */}
                  <span className="relative w-[9px] shrink-0">
                    <span
                      aria-hidden
                      className="absolute left-1/2 top-[7px] block h-[7px] w-[7px] -translate-x-1/2 rounded-full ring-4 ring-void"
                      style={{ background: accent }}
                    />
                  </span>

                  {/* body - tool calls sit one level in, as child spans */}
                  <div className={`min-w-0 flex-1 ${isTool ? "pl-4" : ""}`}>
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <span
                        className="font-mono text-[12px] tracking-[0.04em]"
                        style={{ color: accent }}
                      >
                        {labelFor(evt)}
                      </span>

                      {isTool && (
                        <span className="legend">{familyOf(evt)}</span>
                      )}

                      {/* duration bar - proportional, with the number beside it */}
                      {(dur > 0 || open) && (
                        <span className="ml-auto flex items-center gap-2">
                          <span
                            aria-hidden
                            className="hidden h-[3px] rounded-full sm:block"
                            style={{
                              width: `${Math.max(4, (dur / longest) * 88)}px`,
                              background: accent,
                              opacity: open ? 0.45 : 0.75,
                            }}
                          />
                          <span className="font-mono text-[11px] tnum text-ink-3">
                            {open ? "running" : formatDuration(dur)}
                          </span>
                        </span>
                      )}
                    </div>

                    {/* the model's own words */}
                    {evt.content && !tool && (
                      <p className="mt-1.5 text-[13px] leading-relaxed text-ink-1">
                        {evt.content}
                      </p>
                    )}

                    {/* what the tool was actually asked */}
                    {args && (
                      <p className="mt-1.5 break-words font-mono text-[11px] leading-relaxed text-ink-2">
                        {args}
                      </p>
                    )}

                    {isReport && (
                      <p className="mt-1.5 text-[13px] text-ink-2">
                        Verdict delivered. See the panel on the right.
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
            <div ref={endRef} />
          </ol>
        )}
      </div>
    </section>
  );
}
