"""
Drive traffic against the demo app, inject a fault, then fire the SigNoz-style
webhook at the gateway so the full pipeline runs on REAL data.

  python demo/trigger_incident.py

Steps:
  1. Send baseline healthy traffic to the demo app (builds a normal p99 baseline).
  2. POST /break to saturate the payment-gateway.
  3. Send more traffic → errors + slow spans land in SigNoz.
  4. POST the alert webhook to the Node gateway → agent investigates.
"""

from __future__ import annotations

import os
import time

import requests

DEMO_APP = os.getenv("DEMO_APP_URL", "http://localhost:8081")
GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:4000")


def traffic(n: int) -> None:
    ok = err = 0
    for _ in range(n):
        try:
            r = requests.post(f"{DEMO_APP}/checkout", timeout=10)
            ok += r.status_code == 200
            err += r.status_code >= 500
        except requests.RequestException:
            err += 1
    print(f"  sent {n} requests → {ok} ok, {err} errors")


def main() -> None:
    print("1) Baseline healthy traffic...")
    traffic(20)

    print("2) Injecting fault (payment-gateway pool saturation)...")
    requests.post(f"{DEMO_APP}/break", timeout=10)

    print("3) Traffic under fault (generating error/slow traces)...")
    traffic(30)

    print("4) Firing SigNoz alert webhook at the gateway (optional)...")
    payload = {
        "alert_name": "High Error Rate - Checkout Service",
        "service": "checkout-service",
        "severity": "critical",
        "description": "Error rate exceeded 15% for checkout-service in the last 5 minutes.",
        "triggered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_email": "oncall@example.com",
        "user_ip": "192.168.1.55",
    }
    try:
        resp = requests.post(f"{GATEWAY}/api/webhooks/signoz", json=payload, timeout=10)
        print(f"   gateway responded {resp.status_code}: {resp.text}")
        print("\nWatch the dashboard at http://localhost:3000 — the agent is investigating.")
    except requests.RequestException:
        print("   (gateway not running — skipped. Telemetry was still sent to SigNoz.)")
        print("\n   Traffic + fault sent. In ~1-2 min checkout-service appears in SigNoz,")
        print("   then investigate it live with:")
        print("   uv run python -m eval.run_eval --live --only checkout-pool-exhaustion")


if __name__ == "__main__":
    main()
