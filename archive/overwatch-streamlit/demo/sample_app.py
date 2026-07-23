"""
Demo microservice — a simulated e-commerce checkout service instrumented
with OpenTelemetry. Sends traces, logs, and metrics to SigNoz.

Features:
  - /health         → Health check
  - /checkout       → Simulated checkout (normal or faulty based on FAULT_MODE)
  - /payment        → Downstream payment call
  - /inventory      → Downstream inventory check
  - /fault/enable   → Enable fault injection
  - /fault/disable  → Disable fault injection

The fault mode injects:
  - Random 500 errors on /checkout (~40% of requests)
  - High latency spikes (2-5 second delays)
  - Error logs with stack traces

This gives the Over-Watch agent real SigNoz data to investigate.
"""

import logging
import os
import random
import time
from datetime import datetime

from flask import Flask, jsonify, request

# ── OpenTelemetry Setup ──────────────────────────────────────────────────────

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

SERVICE = "checkout-service"
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

resource = Resource.create({SERVICE_NAME: SERVICE})

# Traces
trace_provider = TracerProvider(resource=resource)
trace_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{OTLP_ENDPOINT}/v1/traces"))
)
trace.set_tracer_provider(trace_provider)
tracer = trace.get_tracer(SERVICE)

# Metrics
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=f"{OTLP_ENDPOINT}/v1/metrics"),
    export_interval_millis=5000,
)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter(SERVICE)

# Custom metrics
checkout_counter = meter.create_counter(
    "checkout.requests",
    description="Total checkout requests",
    unit="1",
)
checkout_errors = meter.create_counter(
    "checkout.errors",
    description="Total checkout errors",
    unit="1",
)
checkout_latency = meter.create_histogram(
    "checkout.latency",
    description="Checkout request latency",
    unit="ms",
)

# Logs
log_provider = LoggerProvider(resource=resource)
log_provider.add_log_record_processor(
    BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{OTLP_ENDPOINT}/v1/logs"))
)
log_handler = LoggingHandler(level=logging.DEBUG, logger_provider=log_provider)

logger = logging.getLogger(SERVICE)
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)
logger.addHandler(logging.StreamHandler())  # Also log to console

# ── Flask App ────────────────────────────────────────────────────────────────

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

# Fault injection flag
FAULT_MODE = False


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "service": SERVICE, "timestamp": datetime.utcnow().isoformat()})


@app.route("/checkout", methods=["POST", "GET"])
def checkout():
    """Simulated checkout endpoint with optional fault injection."""
    start = time.time()
    order_id = f"ORD-{random.randint(10000, 99999)}"
    user_id = f"USR-{random.randint(1000, 9999)}"

    with tracer.start_as_current_span("checkout", attributes={
        "order.id": order_id,
        "user.id": user_id,
        "order.total": round(random.uniform(10.0, 500.0), 2),
    }) as span:
        checkout_counter.add(1, {"endpoint": "/checkout"})

        logger.info(f"Processing checkout for order {order_id}, user {user_id}")

        # Simulate downstream calls
        _call_inventory(order_id)

        if FAULT_MODE and random.random() < 0.4:
            # Inject fault: high latency + error
            delay = random.uniform(2.0, 5.0)
            time.sleep(delay)

            error_msg = random.choice([
                f"PaymentGatewayTimeout: upstream connection to payment-gateway timed out after {delay:.1f}s",
                f"InventoryServiceError: stock check failed for order {order_id} — database connection pool exhausted",
                f"CheckoutValidationError: order {order_id} failed validation — null pointer in price calculator (NullReferenceException at PriceService.java:142)",
            ])

            span.set_status(trace.StatusCode.ERROR, error_msg)
            span.set_attribute("error", True)
            span.set_attribute("error.message", error_msg)

            checkout_errors.add(1, {"endpoint": "/checkout", "error_type": error_msg.split(":")[0]})
            logger.error(f"Checkout FAILED for order {order_id}: {error_msg}")

            latency_ms = (time.time() - start) * 1000
            checkout_latency.record(latency_ms, {"endpoint": "/checkout", "status": "error"})

            return jsonify({"error": error_msg, "order_id": order_id}), 500
        else:
            # Normal successful checkout
            time.sleep(random.uniform(0.05, 0.3))
            _call_payment(order_id)

            latency_ms = (time.time() - start) * 1000
            checkout_latency.record(latency_ms, {"endpoint": "/checkout", "status": "success"})

            logger.info(f"Checkout SUCCESS for order {order_id} in {latency_ms:.0f}ms")
            return jsonify({
                "status": "success",
                "order_id": order_id,
                "latency_ms": round(latency_ms, 1),
            })


def _call_inventory(order_id: str):
    """Simulate a downstream call to inventory service."""
    with tracer.start_as_current_span("inventory-check", attributes={
        "service.name": "inventory-service",
        "order.id": order_id,
    }):
        time.sleep(random.uniform(0.01, 0.08))
        logger.debug(f"Inventory check passed for order {order_id}")


def _call_payment(order_id: str):
    """Simulate a downstream call to payment gateway."""
    with tracer.start_as_current_span("payment-process", attributes={
        "service.name": "payment-gateway",
        "order.id": order_id,
    }):
        time.sleep(random.uniform(0.02, 0.15))
        logger.info(f"Payment processed for order {order_id}")


@app.route("/fault/enable", methods=["POST", "GET"])
def enable_fault():
    """Enable fault injection — the moment things go wrong."""
    global FAULT_MODE
    FAULT_MODE = True
    logger.warning("⚠️ FAULT INJECTION ENABLED — errors will be injected into /checkout")
    return jsonify({"fault_mode": True, "message": "Fault injection enabled. ~40% of checkout requests will now fail."})


@app.route("/fault/disable", methods=["POST", "GET"])
def disable_fault():
    """Disable fault injection — return to normal."""
    global FAULT_MODE
    FAULT_MODE = False
    logger.info("✅ Fault injection disabled — returning to normal operation")
    return jsonify({"fault_mode": False, "message": "Fault injection disabled."})


@app.route("/status")
def status():
    return jsonify({
        "service": SERVICE,
        "fault_mode": FAULT_MODE,
        "timestamp": datetime.utcnow().isoformat(),
    })


if __name__ == "__main__":
    port = int(os.getenv("DEMO_APP_PORT", "5050"))
    logger.info(f"Starting {SERVICE} on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
