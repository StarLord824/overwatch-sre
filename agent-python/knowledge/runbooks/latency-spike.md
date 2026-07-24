# Runbook: service p99 latency spike

**Symptoms:** A service's p99/p95 latency climbs sharply while request rate is
flat or only moderately up.

## Common root causes
1. **Downstream dependency slowdown** — the service is waiting on a slow
   dependency (DB, cache, another service). Traces show most time in a child span.
2. **Resource saturation** — CPU throttling or memory pressure on the pods.
   Check `container_cpu_usage` / `container_memory_usage` metrics.
3. **N+1 / cache miss storm** — a deploy changed a query pattern or invalidated a
   cache. Correlate with deploy markers.
4. **Lock/pool contention** — connection pool or mutex contention under load.

## Investigation steps
1. `signoz_query_metrics metricName=signoz_latency timeAggregation=p99` — confirm
   the spike and its start time.
2. `signoz_search_traces service=<svc> minDuration=2000000000` — pull the slowest
   traces and see where time is spent via `signoz_get_trace_details`.
3. `signoz_query_metrics` on CPU/memory to rule in/out saturation.

## Remediation
- Scale out or up if saturation; add caching / fix the query if N+1; roll back if
  a deploy correlates.
