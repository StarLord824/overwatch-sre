"""
Demo instrumented service - a tiny two-service checkout flow wired to SigNoz via
OpenTelemetry. Run it to generate REAL traces/logs/metrics so the agent has live
data to investigate (instead of the mock fallback).

  pip install -e ".[demo]"     # or: uv sync --group demo
  # point OTLP at your SigNoz collector:
  export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
  export OTEL_SERVICE_NAME=checkout-service
  python demo/sample_app.py

Then drive traffic + inject a fault with demo/trigger_incident.py.

The fault: after /break is called, checkout starts calling a saturated
payment-gateway that times out - producing exactly the errors described in the
checkout-5xx runbook.
"""

from __future__ import annotations

import logging
import os
import random
import time

from dotenv import load_dotenv
from flask import Flask, jsonify

# Pick up SIGNOZ_INGESTION_KEY / SIGNOZ_REGION from the agent's .env automatically.
load_dotenv()

# -- OpenTelemetry setup -------------------------------------------------------
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor

# Logs signal - so the pool-timeout ERROR lines actually reach SigNoz and the
# agent's signoz_search_logs returns real evidence (not just traces).
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "checkout-service")

# -- Exporter: SigNoz Cloud (if an ingestion key is set) or local collector -----
# Cloud: set SIGNOZ_INGESTION_KEY (+ optionally SIGNOZ_REGION, default us2). The
# exporter uses TLS to ingest.<region>.signoz.cloud:443 with the ingestion-key
# header - no code changes, no local collector, matches the SETUP-LIVE cloud path.
# Local: falls back to insecure OTLP at OTEL_EXPORTER_OTLP_ENDPOINT (:4317).
# Both traces AND logs share the same endpoint/auth.
_INGEST_KEY = os.getenv("SIGNOZ_INGESTION_KEY", "")
_REGION = os.getenv("SIGNOZ_REGION", "us2")

if _INGEST_KEY:
    _endpoint = os.getenv("OTLP_ENDPOINT", f"ingest.{_REGION}.signoz.cloud:443")
    _exp_kwargs = dict(
        endpoint=_endpoint,
        insecure=False,  # TLS to SigNoz Cloud
        headers=(("signoz-ingestion-key", _INGEST_KEY),),
    )
    logging.getLogger(SERVICE_NAME).info("Exporting traces + logs to SigNoz Cloud: %s", _endpoint)
else:
    _endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    _exp_kwargs = dict(endpoint=_endpoint, insecure=True)

resource = Resource.create({"service.name": SERVICE_NAME})

# Traces
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**_exp_kwargs)))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# Logs - route Python logging for this service through OTLP to SigNoz. Because
# each logger.error() below runs inside the request span, logs carry trace
# context and correlate with the failing traces.
_logger_provider = LoggerProvider(resource=resource)
_logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(**_exp_kwargs)))
set_logger_provider(_logger_provider)
_otel_log_handler = LoggingHandler(level=logging.INFO, logger_provider=_logger_provider)
logging.getLogger(SERVICE_NAME).addHandler(_otel_log_handler)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(SERVICE_NAME)

# -- payment-gateway as a SEPARATE service -------------------------------------
# The downstream dependency gets its own resource (service.name=payment-gateway)
# for both traces and logs, so SigNoz sees a genuine two-service distributed
# trace - and an investigator querying logs/traces for "payment-gateway" finds
# real telemetry there, exactly as it would in production. Spans still inherit
# the active context, so they remain children of the checkout-service span.
DOWNSTREAM_SERVICE = "payment-gateway"
_pg_resource = Resource.create({"service.name": DOWNSTREAM_SERVICE})

_pg_tracer_provider = TracerProvider(resource=_pg_resource)
_pg_tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**_exp_kwargs)))
pg_tracer = _pg_tracer_provider.get_tracer(__name__)

_pg_logger_provider = LoggerProvider(resource=_pg_resource)
_pg_logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(**_exp_kwargs)))
pg_logger = logging.getLogger(DOWNSTREAM_SERVICE)
pg_logger.addHandler(LoggingHandler(level=logging.INFO, logger_provider=_pg_logger_provider))

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

# In-memory fault switch - flipped by /break and /heal.
STATE = {"broken": False}


def call_payment_gateway() -> None:
    """Simulate a downstream call to the payment-gateway service."""
    with pg_tracer.start_as_current_span("charge_card") as span:
        span.set_attribute("service.name", DOWNSTREAM_SERVICE)
        span.set_attribute("db.connection_pool.max", 20)
        if STATE["broken"]:
            # Pool exhaustion: slow, then time out.
            time.sleep(random.uniform(3.0, 4.5))
            span.set_attribute("error", True)
            span.set_attribute("db.connection_pool.active", 20)
            span.record_exception(
                RuntimeError("connection pool exhausted (max=20); request timed out after 5000ms")
            )
            pg_logger.error(
                "HikariCP connection is not available, request timed out after 5000ms (pool size 20)"
            )
            raise RuntimeError("upstream timeout to payment-gateway")
        time.sleep(random.uniform(0.02, 0.08))
        span.set_attribute("db.connection_pool.active", random.randint(2, 8))
        span.set_attribute("http.status_code", 200)


@app.post("/checkout")
def checkout():
    with tracer.start_as_current_span("POST /checkout") as span:
        span.set_attribute("http.route", "/checkout")
        try:
            call_payment_gateway()
        except Exception as exc:  # noqa: BLE001
            span.set_attribute("error", True)
            logger.error("checkout-service: upstream timeout after 3 retries to payment-gateway")
            return jsonify({"error": str(exc)}), 500
        return jsonify({"status": "ok"}), 200


@app.post("/break")
def break_it():
    STATE["broken"] = True
    logger.warning("FAULT INJECTED: payment-gateway pool now saturated.")
    return jsonify({"broken": True})


@app.post("/heal")
def heal():
    STATE["broken"] = False
    return jsonify({"broken": False})


@app.get("/health")
def health():
    return jsonify({"status": "ok", "broken": STATE["broken"]})


if __name__ == "__main__":
    logger.info(
        "Demo services %s + %s exporting traces & logs to %s",
        SERVICE_NAME, DOWNSTREAM_SERVICE, _endpoint,
    )
    try:
        app.run(host="0.0.0.0", port=8081)
    finally:
        # Flush the downstream service's batched telemetry on shutdown so the
        # last spans/logs aren't lost when you Ctrl+C.
        _pg_tracer_provider.shutdown()
        _pg_logger_provider.shutdown()
