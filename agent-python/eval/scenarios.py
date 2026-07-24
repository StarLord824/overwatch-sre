"""
Injected-incident scenarios — the benchmark's ground truth.

Each scenario is a self-contained incident: an alert payload, the telemetry the
agent will see (with a deliberate RED HERRING planted on an unrelated service),
and the ground truth used to score the agent's RCA:

  expected_keywords  — ALL must appear in the agent's report for a correct RCA
  required_evidence  — evidence tokens the agent should surface (recall metric)
  forbidden_keywords — if these appear in the CONCLUDED root cause, the agent was
                       fooled by the red herring

Keep expected/forbidden sets small and strong so scoring is meaningful, not noisy.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scenario:
    id: str
    title: str
    alert: dict
    telemetry: dict
    expected_keywords: list[str]
    required_evidence: list[str]
    forbidden_keywords: list[str] = field(default_factory=list)
    # Filled in by _META below — keeps the fixtures above readable.
    category: str = ""
    root_cause_class: str = ""          # ground-truth class from CLASS_VOCAB
    rubric: list[str] = field(default_factory=list)  # scoring points for the LLM judge


# Closed vocabulary the LLM judge classifies the agent's conclusion into. The
# first five are the true causes; the last three are the distractor classes each
# red herring points at — so a fooled agent lands on a distractor and scores 0.
CLASS_VOCAB: tuple[str, ...] = (
    "downstream_dependency_saturation",
    "cpu_saturation",
    "bad_deploy_regression",
    "cache_stampede",
    "third_party_timeout",
    # distractor classes
    "database_slowdown",
    "memory_leak_oom",
    "network_fault",
)


SCENARIOS: list[Scenario] = [
    # ── 1. Downstream dependency: connection pool exhaustion ──────────────────
    Scenario(
        id="checkout-pool-exhaustion",
        title="checkout 5xx from payment-gateway connection pool exhaustion",
        alert={
            "alert_name": "High Error Rate - Checkout Service",
            "service": "checkout-service",
            "severity": "critical",
            "description": "Error rate exceeded 15% for checkout-service in the last 5 minutes.",
        },
        telemetry={
            "services": [
                {"name": "checkout-service", "p99_ms": 4200, "error_rate": 0.17, "rps": 320},
                {"name": "payment-gateway", "p99_ms": 3900, "error_rate": 0.02, "rps": 310},
                # Red herring: inventory-service looks scary but is unrelated.
                {"name": "inventory-service", "p99_ms": 260, "error_rate": 0.08, "rps": 120},
            ],
            "traces": {
                "checkout-service": [
                    {"traceId": "T1a", "spanId": "s1", "service": "checkout-service",
                     "operation": "POST /checkout", "durationMs": 4500, "status": "ERROR",
                     "error": "context deadline exceeded calling payment-gateway"},
                ],
                "inventory-service": [
                    {"traceId": "H1", "spanId": "h1", "service": "inventory-service",
                     "operation": "GET /stock", "durationMs": 90, "status": "ERROR",
                     "error": "sporadic 404 on discontinued SKU"},
                ],
            },
            "trace_details": {
                "T1a": {"traceId": "T1a", "spans": [
                    {"service": "checkout-service", "op": "POST /checkout", "ms": 4500},
                    {"service": "payment-gateway", "op": "charge_card", "ms": 4300,
                     "error": "connection pool exhausted (max=20)"},
                ]},
            },
            "logs": {
                "payment-gateway": [
                    {"ts": "10:31:02Z", "severity": "ERROR",
                     "body": "HikariCP - Connection is not available, request timed out after 5000ms (pool size 20)"},
                ],
                # Red herring log on inventory-service.
                "inventory-service": [
                    {"ts": "10:30:40Z", "severity": "ERROR",
                     "body": "java.lang.OutOfMemoryError: Java heap space in ReportBuilder"},
                ],
            },
            "metrics": {
                "connection_pool_active": {"series": [{"t": "10:25", "v": 12}, {"t": "10:28", "v": 20}, {"t": "10:31", "v": 20}],
                                           "note": "saturated at max=20 since 10:28"},
                "signoz_latency": {"series": [{"t": "10:25", "v": 300}, {"t": "10:31", "v": 4500}]},
            },
            "alerts": [
                {"name": "High Error Rate - checkout-service", "state": "firing", "since": "10:30"},
                {"name": "DB Connection Pool Saturation - payment-gateway", "state": "firing", "since": "10:28"},
            ],
        },
        expected_keywords=["payment-gateway", "pool"],
        required_evidence=["pool", "5000ms"],
        forbidden_keywords=["inventory", "outofmemory", "heap"],
    ),

    # ── 2. Resource saturation: CPU throttling ────────────────────────────────
    Scenario(
        id="cpu-saturation-latency",
        title="search-service p99 latency from CPU throttling",
        alert={
            "alert_name": "High Latency - Search Service",
            "service": "search-service",
            "severity": "warning",
            "description": "p99 latency for search-service exceeded 2s for 10 minutes.",
        },
        telemetry={
            "services": [
                {"name": "search-service", "p99_ms": 2600, "error_rate": 0.01, "rps": 90},
                {"name": "cart-service", "p99_ms": 210, "error_rate": 0.00, "rps": 140},
            ],
            "traces": {
                "search-service": [
                    {"traceId": "T2a", "spanId": "s2", "service": "search-service",
                     "operation": "GET /search", "durationMs": 2550, "status": "OK",
                     "error": "", "note": "time spent in local ranking compute, no slow downstream"},
                ],
            },
            "trace_details": {
                "T2a": {"traceId": "T2a", "spans": [
                    {"service": "search-service", "op": "GET /search", "ms": 2550},
                    {"service": "search-service", "op": "rank_results (CPU-bound)", "ms": 2400},
                ]},
            },
            "logs": {"search-service": [
                {"ts": "11:02Z", "severity": "WARN", "body": "cpu throttled: cfs_throttled_periods increasing"},
            ]},
            "metrics": {
                "container_cpu_usage": {"series": [{"t": "10:50", "v": 0.55}, {"t": "11:00", "v": 0.98}],
                                        "note": "search-service pods pinned ~98%, being throttled"},
                "container_memory_usage": {"series": [{"t": "11:00", "v": 0.40}], "note": "memory healthy — rules out leak"},
            },
            # Red herring: an unrelated deploy on cart-service.
            "alerts": [
                {"name": "CPU Throttling - search-service", "state": "firing", "since": "10:55"},
                {"name": "Deploy marker: cart-service v3.1.0", "state": "info", "since": "10:57"},
            ],
        },
        expected_keywords=["cpu", "search-service"],
        required_evidence=["cpu"],
        forbidden_keywords=["cart-service deploy", "memory leak", "v3.1.0"],
    ),

    # ── 3. Bad deploy: NullPointer regression ─────────────────────────────────
    Scenario(
        id="bad-deploy-npe",
        title="cart-service errors from v2.4.1 NullPointerException regression",
        alert={
            "alert_name": "High Error Rate - Cart Service",
            "service": "cart-service",
            "severity": "critical",
            "description": "cart-service error rate jumped to 22% at 09:15, ~2 min after a deploy.",
        },
        telemetry={
            "services": [
                {"name": "cart-service", "p99_ms": 320, "error_rate": 0.22, "rps": 200},
                {"name": "postgres", "p99_ms": 800, "error_rate": 0.00, "rps": 400},
            ],
            "traces": {"cart-service": [
                {"traceId": "T3a", "spanId": "s3", "service": "cart-service",
                 "operation": "POST /cart/apply-coupon", "durationMs": 120, "status": "ERROR",
                 "error": "NullPointerException at CartController.applyCoupon line 88"},
            ]},
            "logs": {"cart-service": [
                {"ts": "09:15:20Z", "severity": "ERROR",
                 "body": "java.lang.NullPointerException at CartController.applyCoupon(CartController.java:88) — introduced in v2.4.1"},
            ]},
            "metrics": {
                "signoz_calls_total": {"series": [{"t": "09:13", "v": 0.01}, {"t": "09:15", "v": 0.22}],
                                       "note": "error rate step-change at 09:15, aligns with deploy v2.4.1"},
                # Red herring: postgres latency is elevated but it's the nightly batch window (normal).
                "postgres_query_latency": {"series": [{"t": "09:15", "v": 800}],
                                           "note": "elevated but consistent with scheduled nightly batch — normal for this hour"},
            },
            "alerts": [
                {"name": "High Error Rate - cart-service", "state": "firing", "since": "09:15"},
                {"name": "Deploy marker: cart-service v2.4.1", "state": "info", "since": "09:13"},
            ],
        },
        expected_keywords=["v2.4.1", "cart-service"],
        required_evidence=["nullpointer", "v2.4.1"],
        forbidden_keywords=["postgres", "database", "nightly batch"],
    ),

    # ── 4. Cache stampede → DB overload ───────────────────────────────────────
    Scenario(
        id="cache-stampede",
        title="product-service latency from Redis cache eviction stampede",
        alert={
            "alert_name": "High Latency - Product Service",
            "service": "product-service",
            "severity": "warning",
            "description": "product-service p99 tripled starting 14:20.",
        },
        telemetry={
            "services": [
                {"name": "product-service", "p99_ms": 1800, "error_rate": 0.01, "rps": 500},
                {"name": "redis", "p99_ms": 5, "error_rate": 0.00, "rps": 4000},
            ],
            "traces": {"product-service": [
                {"traceId": "T4a", "spanId": "s4", "service": "product-service",
                 "operation": "GET /product/{id}", "durationMs": 1750, "status": "OK",
                 "error": "", "note": "12 sequential postgres reads per request — cache miss path"},
            ]},
            "logs": {"redis": [
                {"ts": "14:20Z", "severity": "WARN", "body": "maxmemory reached, evicting keys (allkeys-lru); 40k evictions/min"},
            ]},
            "metrics": {
                "cache_hit_ratio": {"series": [{"t": "14:15", "v": 0.95}, {"t": "14:22", "v": 0.20}],
                                    "note": "hit ratio collapsed 0.95 -> 0.20 at 14:20"},
                "db_query_count": {"series": [{"t": "14:15", "v": 1000}, {"t": "14:22", "v": 9000}],
                                   "note": "9x DB read amplification"},
            },
            # Red herring: a transient network alert on an unrelated node.
            "alerts": [
                {"name": "Cache Eviction Spike - redis", "state": "firing", "since": "14:20"},
                {"name": "Packet loss on node-3", "state": "resolved", "since": "14:05"},
            ],
        },
        expected_keywords=["cache", "product-service"],
        required_evidence=["eviction", "hit ratio"],
        forbidden_keywords=["packet loss", "network"],
    ),

    # ── 5. Third-party dependency timeout ─────────────────────────────────────
    Scenario(
        id="third-party-timeout",
        title="payment-service latency from external Stripe API timeouts",
        alert={
            "alert_name": "High Latency - Payment Service",
            "service": "payment-service",
            "severity": "critical",
            "description": "payment-service p99 spiked to 5s at 16:40; some requests timing out.",
        },
        telemetry={
            "services": [
                {"name": "payment-service", "p99_ms": 5100, "error_rate": 0.06, "rps": 150},
            ],
            "traces": {"payment-service": [
                {"traceId": "T5a", "spanId": "s5", "service": "payment-service",
                 "operation": "POST /charge", "durationMs": 5050, "status": "ERROR",
                 "error": "upstream timeout to external api.stripe.com"},
            ]},
            "trace_details": {"T5a": {"traceId": "T5a", "spans": [
                {"service": "payment-service", "op": "POST /charge", "ms": 5050},
                {"service": "external", "op": "POST https://api.stripe.com/v1/charges", "ms": 5000,
                 "error": "context deadline exceeded (external)"},
            ]}},
            "logs": {"payment-service": [
                {"ts": "16:41Z", "severity": "ERROR", "body": "stripe API call timed out after 5000ms (external dependency)"},
            ]},
            "metrics": {
                "external_call_latency": {"series": [{"t": "16:35", "v": 300}, {"t": "16:41", "v": 5000}],
                                          "note": "latency lives entirely in the external stripe.com span"},
                # Red herring: GC pauses slightly up but not the cause.
                "jvm_gc_pause_ms": {"series": [{"t": "16:41", "v": 45}], "note": "minor, well within normal — not the cause"},
            },
            "alerts": [
                {"name": "High Latency - payment-service", "state": "firing", "since": "16:40"},
            ],
        },
        expected_keywords=["stripe", "external"],
        required_evidence=["stripe", "5000ms"],
        forbidden_keywords=["gc pause", "garbage collection"],
    ),
]


# ── Ground-truth metadata (category / class / judge rubric) ───────────────────
# Kept separate so the fixtures above stay readable. The rubric is the list of
# scoring points the LLM judge grades the agent's conclusion against.
_META: dict[str, dict] = {
    "checkout-pool-exhaustion": {
        "category": "downstream_dependency",
        "root_cause_class": "downstream_dependency_saturation",
        "rubric": [
            "Identifies payment-gateway (not checkout itself) as the failing dependency",
            "Names connection pool exhaustion / saturation (max=20) as the mechanism",
            "Does NOT blame inventory-service or its OutOfMemory log (red herring)",
        ],
    },
    "cpu-saturation-latency": {
        "category": "resource_saturation",
        "root_cause_class": "cpu_saturation",
        "rubric": [
            "Identifies CPU saturation/throttling of search-service pods as the cause",
            "Notes time is spent in local CPU-bound compute, not a slow downstream",
            "Does NOT blame the unrelated cart-service deploy or a memory leak",
        ],
    },
    "bad-deploy-npe": {
        "category": "bad_deploy",
        "root_cause_class": "bad_deploy_regression",
        "rubric": [
            "Attributes the errors to the v2.4.1 deploy of cart-service",
            "Cites the NullPointerException in CartController.applyCoupon",
            "Does NOT blame postgres/database latency (red herring: nightly batch)",
        ],
    },
    "cache-stampede": {
        "category": "cache",
        "root_cause_class": "cache_stampede",
        "rubric": [
            "Identifies the Redis cache eviction / hit-ratio collapse as the trigger",
            "Connects it to DB read amplification driving product-service latency",
            "Does NOT blame the transient network/packet-loss alert (red herring)",
        ],
    },
    "third-party-timeout": {
        "category": "third_party",
        "root_cause_class": "third_party_timeout",
        "rubric": [
            "Identifies the external Stripe API call as where the latency lives",
            "Frames it as a third-party/external dependency timeout (~5000ms)",
            "Does NOT blame internal JVM GC pauses (red herring)",
        ],
    },
}

for _s in SCENARIOS:
    _m = _META[_s.id]
    _s.category = _m["category"]
    _s.root_cause_class = _m["root_cause_class"]
    _s.rubric = _m["rubric"]
