"use client";

import { useEffect, useState, useRef } from "react";
import { io, Socket } from "socket.io-client";
import { 
  Activity, AlertTriangle, CheckCircle, Clock, 
  Terminal, ShieldAlert, Cpu, Network 
} from "lucide-react";

interface AgentEvent {
  incident_id: string;
  type: "status" | "thinking" | "info" | "tool_call" | "final_report";
  content?: string;
  data?: any;
  timestamp: string;
}

export default function MissionControl() {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [socketStatus, setSocketStatus] = useState<"disconnected" | "connected">("disconnected");
  const [incidentId, setIncidentId] = useState<string>("Waiting for incident...");
  const socketRef = useRef<Socket | null>(null);
  const endOfMessagesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Connect to the Node.js Gateway
    const socketUrl = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:4000";
    socketRef.current = io(socketUrl);

    socketRef.current.on("connect", () => {
      setSocketStatus("connected");
    });

    socketRef.current.on("disconnect", () => {
      setSocketStatus("disconnected");
    });

    socketRef.current.on("agent_event", (event: Omit<AgentEvent, "timestamp">) => {
      const newEvent = { ...event, timestamp: new Date().toLocaleTimeString() };
      setEvents((prev) => [...prev, newEvent]);
      setIncidentId(event.incident_id);
    });

    return () => {
      socketRef.current?.disconnect();
    };
  }, []);

  useEffect(() => {
    endOfMessagesRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const simulateAlert = async () => {
    try {
      setEvents([]);
      await fetch((process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:4000") + "/api/webhooks/signoz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          alert_name: "High Error Rate - Checkout Service",
          service: "checkout-service",
          severity: "critical",
          description: "Error rate exceeded 15% threshold in the last 5 minutes.",
          user_email: "oncall@example.com",
          user_ip: "192.168.1.55"
        })
      });
    } catch (e) {
      console.error("Failed to simulate alert", e);
    }
  };

  const finalReport = events.find(e => e.type === "final_report")?.data;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-300 font-sans p-6">
      <header className="flex justify-between items-center mb-8 border-b border-slate-800 pb-4">
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-8 h-8 text-indigo-500" />
          <h1 className="text-2xl font-bold text-white tracking-tight">Project Over-Watch</h1>
        </div>
        <div className="flex items-center gap-4">
          <div className={`flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium uppercase tracking-wide ${socketStatus === "connected" ? "bg-emerald-950 text-emerald-400 border border-emerald-800" : "bg-rose-950 text-rose-400 border border-rose-800"}`}>
            {socketStatus === "connected" ? <Network className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
            {socketStatus}
          </div>
          <button 
            onClick={simulateAlert}
            className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-md text-sm font-medium transition-colors shadow-[0_0_15px_rgba(79,70,229,0.3)]"
          >
            Simulate Alert
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Left Column: Live Agent Stream */}
        <div className="lg:col-span-2 flex flex-col h-[calc(100vh-140px)]">
          <div className="bg-slate-900 border border-slate-800 rounded-t-lg p-3 flex justify-between items-center">
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
              <Terminal className="w-4 h-4" /> Live Reasoning Stream
            </h2>
            <span className="text-xs font-mono bg-slate-950 px-2 py-1 rounded text-slate-500">
              {incidentId}
            </span>
          </div>
          
          <div className="flex-1 bg-black border-x border-b border-slate-800 rounded-b-lg p-4 overflow-y-auto font-mono text-sm shadow-inner">
            {events.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-600 space-y-4">
                <Cpu className="w-12 h-12 opacity-20" />
                <p>Waiting for SigNoz webhooks...</p>
              </div>
            ) : (
              <div className="space-y-4">
                {events.map((evt, idx) => (
                  <div key={idx} className="flex flex-col gap-1 pb-4 border-b border-slate-900 last:border-0">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-slate-500">[{evt.timestamp}]</span>
                      <span className={`px-2 py-[2px] rounded uppercase font-bold text-[10px] tracking-wider
                        ${evt.type === 'status' ? 'bg-blue-950 text-blue-400' : 
                          evt.type === 'thinking' ? 'bg-purple-950 text-purple-400' : 
                          evt.type === 'tool_call' ? 'bg-amber-950 text-amber-400' : 
                          evt.type === 'final_report' ? 'bg-emerald-950 text-emerald-400' : 
                          'bg-slate-800 text-slate-400'}`}
                      >
                        {evt.type}
                      </span>
                    </div>
                    {evt.content && <div className="text-slate-300 ml-2 mt-1">{evt.content}</div>}
                    {evt.data && evt.type !== 'final_report' && (
                      <pre className="bg-slate-900 p-2 rounded text-xs text-indigo-300 overflow-x-auto mt-2 ml-2 border border-slate-800">
                        {JSON.stringify(evt.data, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
                <div ref={endOfMessagesRef} />
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Final Report */}
        <div className="flex flex-col h-[calc(100vh-140px)]">
          <div className="bg-slate-900 border border-slate-800 rounded-t-lg p-3">
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
              <Activity className="w-4 h-4" /> Incident Diagnosis
            </h2>
          </div>
          
          <div className="flex-1 bg-slate-900/50 border-x border-b border-slate-800 rounded-b-lg p-5 overflow-y-auto">
            {!finalReport ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-600">
                <p className="text-center">No final report generated yet.<br/>Trigger an alert to start investigation.</p>
              </div>
            ) : (
              <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                <div>
                  <h3 className="text-xs uppercase text-slate-500 font-semibold mb-2">Root Cause</h3>
                  <div className="bg-slate-950 border border-slate-800 p-4 rounded-lg shadow-sm">
                    <p className="text-slate-200">{finalReport.root_cause}</p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-slate-950 border border-slate-800 p-4 rounded-lg">
                    <h3 className="text-[10px] uppercase text-slate-500 font-bold mb-1">Confidence</h3>
                    <div className={`text-lg font-bold ${
                      finalReport.confidence === 'HIGH' ? 'text-emerald-400' :
                      finalReport.confidence === 'MEDIUM' ? 'text-amber-400' : 'text-rose-400'
                    }`}>
                      {finalReport.confidence}
                    </div>
                  </div>
                  <div className="bg-slate-950 border border-slate-800 p-4 rounded-lg">
                    <h3 className="text-[10px] uppercase text-slate-500 font-bold mb-1">Status</h3>
                    <div className="text-lg font-bold text-blue-400 flex items-center gap-2">
                      <CheckCircle className="w-5 h-5" /> Resolved
                    </div>
                  </div>
                </div>

                <div>
                  <h3 className="text-xs uppercase text-slate-500 font-semibold mb-2">Summary & Remediation</h3>
                  <div className="bg-slate-950 border border-slate-800 p-4 rounded-lg text-sm leading-relaxed text-slate-300">
                    {finalReport.summary}
                  </div>
                </div>

                <div>
                  <h3 className="text-xs uppercase text-slate-500 font-semibold mb-2">Evidence Chain (SigNoz MCP)</h3>
                  <ul className="space-y-2">
                    {finalReport.evidence?.map((item: string, i: number) => (
                      <li key={i} className="bg-slate-900 border border-slate-800 p-3 rounded-md text-xs font-mono text-slate-400 flex items-start gap-2">
                        <span className="text-indigo-500 font-bold mt-[2px]">{i+1}.</span>
                        <span className="leading-relaxed">{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Prevention: the guard alert the agent recommends to catch this earlier */}
                {finalReport.prevention && (
                  <div>
                    <h3 className="text-xs uppercase text-emerald-500 font-semibold mb-2 flex items-center gap-2">
                      🛡️ Prevention · Recommended Guard Alert
                    </h3>
                    <div className="bg-emerald-950/40 border border-emerald-900 p-4 rounded-lg text-sm leading-relaxed text-emerald-100">
                      {finalReport.prevention}
                    </div>
                  </div>
                )}

                {/* Close the loop: clickable deep-links back into SigNoz */}
                {finalReport.signoz_links?.length > 0 && (
                  <div>
                    <h3 className="text-xs uppercase text-slate-500 font-semibold mb-2">Open in SigNoz</h3>
                    <div className="flex flex-wrap gap-2">
                      {finalReport.signoz_links.map((l: any, i: number) => (
                        <a key={i} href={l.url} target="_blank" rel="noreferrer"
                           className="bg-slate-900 border border-slate-700 hover:border-indigo-500 px-3 py-1.5 rounded-md text-xs text-indigo-300 transition-colors">
                          {l.label} ↗
                        </a>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
        
      </div>
    </div>
  );
}
