# Runbook: checkout-service elevated 5xx / error rate

**Symptoms:** checkout-service error rate spikes, POST /checkout returning 500s,
often within ~20 min of a deploy.

## Most common root causes (in order)
1. **payment-gateway connection pool exhaustion** — checkout depends on
   payment-gateway; if its DB/HTTP connection pool (HikariCP, default max=20)
   saturates, calls queue and time out. Look for `connection pool exhausted` or
   `connection is not available` in payment-gateway logs.
2. **Downstream timeout / context deadline exceeded** — checkout's client
   timeout is shorter than payment-gateway's p99 under load. Traces show the
   error originating in the payment-gateway span.
3. **Bad deploy** — correlate the incident start time with the most recent
   deploy marker (e.g. v2.4.1). If it lines up, suspect a regression.

## Investigation steps
1. `signoz_list_services` — confirm which services are unhealthy and their p99.
2. `signoz_search_traces service=checkout-service error=true` — find the failing
   span and follow it downstream (`signoz_get_trace_details`).
3. `signoz_search_logs service=payment-gateway severity=ERROR` — look for pool /
   timeout messages.
4. `signoz_query_metrics metricName=connection_pool_active` — confirm saturation.

## Remediation
- Immediate: raise payment-gateway pool size and/or roll back the correlated deploy.
- Durable: add a circuit breaker + bulkhead on checkout→payment-gateway calls.
