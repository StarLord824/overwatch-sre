"use client";

import { ArrowUpRight } from "lucide-react";
import { Report, SigNozLink, confidenceColor } from "../lib/events";

interface Props {
  report: Report | null;
  running: boolean;
}

function Block({
  label,
  children,
  accent,
}: {
  label: string;
  children: React.ReactNode;
  accent?: string;
}) {
  return (
    <section>
      <h3 className="legend mb-2" style={accent ? { color: accent } : undefined}>
        {label}
      </h3>
      {children}
    </section>
  );
}

export default function VerdictPanel({ report, running }: Props) {
  return (
    <section className="flex min-h-[50vh] flex-col border border-rule bg-deck/40 lg:min-h-0">
      <div className="flex items-center justify-between border-b border-rule px-4 py-3">
        <h2 className="legend">Verdict</h2>
        {report && (
          <span
            className="font-mono text-[11px] tracking-[0.1em]"
            style={{ color: confidenceColor(report.confidence) }}
          >
            {report.confidence?.toUpperCase()}
          </span>
        )}
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {!report ? (
          <div className="flex h-full min-h-[280px] flex-col items-center justify-center gap-3 text-center">
            <div className="h-px w-16 bg-rule-bright" />
            <p className="font-mono text-[13px] text-ink-2">
              {running ? "Investigating." : "No verdict yet."}
            </p>
            <p className="max-w-[24ch] text-[13px] leading-relaxed text-ink-3">
              {running
                ? "The report appears here the moment the agent reaches a conclusion."
                : "Root cause, evidence and prevention appear here after a run."}
            </p>
          </div>
        ) : (
          <div className="enter space-y-6">
            {/* Honesty first: if the evidence was mocked, say so above the verdict. */}
            {report.signoz_live === false && (
              <p className="border-l-2 border-signal bg-signal/10 px-3 py-2 text-[12px] leading-relaxed text-signal">
                This run used mock telemetry. SigNoz was unreachable, so the
                evidence below is illustrative, not measured.
              </p>
            )}

            <Block label="Root cause">
              <p className="text-[14px] leading-relaxed text-ink-1">
                {report.root_cause}
              </p>
            </Block>

            {report.summary && (
              <Block label="Remediation">
                <p className="whitespace-pre-line text-[13px] leading-relaxed text-ink-2">
                  {report.summary}
                </p>
              </Block>
            )}

            {!!report.evidence?.length && (
              <Block label={`Evidence · ${report.evidence.length} cited`}>
                <ol className="space-y-2">
                  {report.evidence.map((item, i) => (
                    <li
                      key={i}
                      className="flex gap-2.5 border-l border-rule-bright pl-3"
                    >
                      <span className="shrink-0 font-mono text-[11px] tnum text-trace">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span className="break-words font-mono text-[11px] leading-relaxed text-ink-2">
                        {item}
                      </span>
                    </li>
                  ))}
                </ol>
              </Block>
            )}

            {report.prevention && (
              <Block label="Prevention · recommended guard alert">
                <p className="whitespace-pre-line border-l-2 border-nominal bg-nominal/5 px-3 py-2.5 text-[13px] leading-relaxed text-ink-1">
                  {report.prevention}
                </p>
              </Block>
            )}

            {!!report.signoz_links?.length && (
              <Block label="Open in SigNoz">
                <div className="flex flex-col gap-px">
                  {report.signoz_links.map((l: SigNozLink, i: number) => (
                    <a
                      key={i}
                      href={l.url}
                      target="_blank"
                      rel="noreferrer"
                      className="group flex items-center justify-between gap-3 border-b border-rule py-2 text-[12px] text-ink-2 transition-colors last:border-0 hover:text-trace"
                    >
                      <span className="truncate font-mono">{l.label}</span>
                      <ArrowUpRight className="h-3.5 w-3.5 shrink-0 opacity-40 transition-opacity group-hover:opacity-100" />
                    </a>
                  ))}
                </div>
              </Block>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
