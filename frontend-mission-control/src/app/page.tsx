"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { io, Socket } from "socket.io-client";

import StatusRail from "./components/StatusRail";
import TraceStream from "./components/TraceStream";
import VerdictPanel from "./components/VerdictPanel";
import { AgentEvent, CostSummary, Report } from "./lib/events";

const GATEWAY =
  process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:4000";

// The last run survives a reload via localStorage - there's no server-side
// history endpoint, and losing an in-progress or just-finished investigation
// to an accidental refresh is a worse experience than a stale one persisting
// until the next "Simulate Alert".
const STORAGE_KEY = "overwatch:lastRun";

export default function MissionControl() {
  // Starts empty so the client's first paint matches the server-rendered
  // HTML (which can't see localStorage) - hydrating from storage happens in
  // an effect below, after mount, as a normal post-hydration state update
  // rather than a value baked into the initial render.
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const socketRef = useRef<Socket | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      // useSyncExternalStore doesn't fit here - it wants the external source
      // to stay authoritative every render, but `events` is owned by React
      // and mutated continuously by the socket handler below; localStorage is
      // only a one-time rehydration backup at mount, not a live source.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (raw) setEvents(JSON.parse(raw) as AgentEvent[]);
    } catch {
      // Corrupt or unavailable storage - starting empty is a fine fallback.
    }
  }, []);

  useEffect(() => {
    const socket = io(GATEWAY);
    socketRef.current = socket;

    socket.on("connect", () => setConnected(true));
    socket.on("disconnect", () => setConnected(false));
    socket.on("agent_event", (evt: Omit<AgentEvent, "receivedAt">) => {
      setEvents((prev) => {
        // A run can arrive from anywhere - the dashboard's own button, the
        // CLI's `overwatch demo`, a real SigNoz webhook - and since events
        // now persist across reloads, an unrelated new incident must start a
        // fresh trace rather than append onto whatever was left over, or the
        // waterfall mixes runs and the verdict below picks up a stale report.
        const current = prev[prev.length - 1]?.incident_id;
        const isNewIncident = Boolean(
          evt.incident_id && current && evt.incident_id !== current,
        );
        const base = isNewIncident ? [] : prev;
        return [...base, { ...evt, receivedAt: Date.now() }];
      });
    });

    return () => {
      socket.disconnect();
    };
  }, []);

  useEffect(() => {
    try {
      if (events.length) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(events));
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // Storage full or unavailable - losing persistence isn't worth surfacing.
    }
  }, [events]);

  const incidentId = useMemo(
    () => events[events.length - 1]?.incident_id ?? null,
    [events],
  );

  // Derived run state -------------------------------------------------------
  // findLast, not find: defensive belt-and-suspenders in case a stray retry
  // ever puts two of the same event type in one incident's array - the most
  // recent one is always the one that should win.
  const report = useMemo(
    () =>
      (events.findLast((e) => e.type === "final_report")?.data as
        | Report
        | undefined) ?? null,
    [events],
  );

  const cost = useMemo(
    () =>
      (events.findLast((e) => e.type === "cost")?.data as
        | CostSummary
        | undefined) ?? null,
    [events],
  );

  // The agent reports which telemetry source it actually reached; surfacing
  // that is the difference between an honest demo and a misleading one.
  const signozLive = useMemo<boolean | null>(() => {
    if (report && typeof report.signoz_live === "boolean")
      return report.signoz_live;
    for (const e of events) {
      const v = e.data?.signoz_live;
      if (typeof v === "boolean") return v;
    }
    return null;
  }, [events, report]);

  const t0 = events.length ? events[0].receivedAt : null;
  const running = events.length > 0 && !report;

  // T+MM:SS is deliberately relative (see TraceStream) - but that means it
  // says nothing about *when* a persisted run actually happened, which
  // matters once a run can survive a reload or a later look-back. This is
  // the one absolute anchor for it.
  const startedAt = useMemo(
    () => (t0 !== null ? new Date(t0).toLocaleTimeString() : null),
    [t0],
  );

  // One ticker drives both the elapsed clock and the in-flight span duration.
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [running]);

  const met = useMemo(() => {
    if (t0 === null) return null;
    const end = report
      ? (events[events.length - 1]?.receivedAt ?? now)
      : now;
    return end - t0;
  }, [t0, report, events, now]);

  const simulate = useCallback(async () => {
    setEvents([]);
    setNow(Date.now());
    try {
      await fetch(`${GATEWAY}/api/webhooks/signoz`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          alert_name: "High Error Rate - Checkout Service",
          service: "checkout-service",
          severity: "critical",
          description:
            "Error rate exceeded 15% threshold in the last 5 minutes.",
          user_email: "oncall@example.com",
          user_ip: "192.168.1.55",
        }),
      });
    } catch {
      // The gateway being down is a normal state to be in, not an exception to
      // throw at the user: the rail already shows "no link".
    }
  }, []);

  return (
    /* Locked to the viewport on wide screens so both panels scroll
       independently, like a real console. On narrow screens the panels stack
       and the page scrolls normally - two half-height panes on a phone is
       unusable. */
    <div className="flex min-h-screen flex-col lg:h-screen">
      <StatusRail
        connected={connected}
        incidentId={incidentId}
        startedAt={startedAt}
        met={met}
        running={running}
        cost={cost}
        signozLive={signozLive}
        onSimulate={simulate}
        busy={running}
      />

      <main className="mx-auto grid w-full max-w-[1600px] flex-1 grid-cols-1 gap-4 px-5 py-4 sm:px-7 lg:min-h-0 lg:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
        <TraceStream events={events} t0={t0} running={running} now={now} />
        <VerdictPanel report={report} running={running} />
      </main>

      {!connected && (
        <p className="border-t border-rule bg-deck/60 px-5 py-2 text-center font-mono text-[11px] text-ink-3 sm:px-7">
          Gateway unreachable at {GATEWAY} — start it with{" "}
          <span className="text-ink-2">npm start</span> in{" "}
          <span className="text-ink-2">gateway-node/</span>
        </p>
      )}
    </div>
  );
}
