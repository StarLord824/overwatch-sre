"""
Incident trigger script — automates the demo scenario.

Usage:
    python demo/trigger_incident.py

What it does:
  1. Sends baseline healthy traffic to the checkout service (30 seconds)
  2. Enables fault injection
  3. Sends traffic that triggers errors (60 seconds)
  4. Prints a summary of what to investigate in Over-Watch
  5. Disables fault injection

This creates a clear "before vs after" pattern in SigNoz that the
Over-Watch agent can investigate.
"""

import sys
import time
import random
import httpx

DEMO_APP_URL = "http://localhost:5050"


def send_traffic(duration_seconds: int, label: str):
    """Send randomized checkout requests for a given duration."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Duration: {duration_seconds}s | Target: {DEMO_APP_URL}/checkout")
    print(f"{'='*60}\n")

    end_time = time.time() + duration_seconds
    success = 0
    errors = 0

    while time.time() < end_time:
        try:
            resp = httpx.post(
                f"{DEMO_APP_URL}/checkout",
                json={
                    "item": random.choice(["laptop", "phone", "headphones", "tablet", "keyboard"]),
                    "quantity": random.randint(1, 3),
                },
                timeout=10.0,
            )
            if resp.status_code == 200:
                success += 1
                print(f"  ✅ 200 OK — {resp.json().get('order_id', '?')} ({resp.json().get('latency_ms', '?')}ms)")
            else:
                errors += 1
                print(f"  ❌ {resp.status_code} — {resp.json().get('error', '?')[:80]}")
        except Exception as e:
            errors += 1
            print(f"  💥 Connection error: {e}")

        # Random delay between requests (50-300ms)
        time.sleep(random.uniform(0.05, 0.3))

    print(f"\n  Summary: {success} success, {errors} errors")
    return success, errors


def main():
    print("\n" + "🚀" * 30)
    print("\n  OVER-WATCH INCIDENT DEMO TRIGGER")
    print("  ================================\n")

    # Check the app is running
    try:
        resp = httpx.get(f"{DEMO_APP_URL}/health", timeout=5.0)
        print(f"  ✅ Demo app is healthy: {resp.json()}\n")
    except Exception:
        print(f"  ❌ Cannot reach demo app at {DEMO_APP_URL}")
        print("  Run the demo app first: python demo/sample_app.py")
        sys.exit(1)

    # Phase 1: Healthy baseline
    print("\n📊 PHASE 1: Establishing healthy baseline...")
    send_traffic(30, "🟢 BASELINE — Normal operation")

    # Phase 2: Enable faults
    print("\n💥 PHASE 2: Injecting faults...")
    try:
        resp = httpx.get(f"{DEMO_APP_URL}/fault/enable", timeout=5.0)
        print(f"  Fault mode: {resp.json()}")
    except Exception as e:
        print(f"  ❌ Failed to enable faults: {e}")
        sys.exit(1)

    # Phase 3: Traffic with faults
    _, error_count = send_traffic(60, "🔴 FAULT INJECTED — Errors happening now")

    # Phase 4: Summary
    print("\n" + "="*60)
    print("  📋 INCIDENT SUMMARY FOR OVER-WATCH")
    print("="*60)
    print(f"""
  The checkout-service is experiencing:
    • ~40% error rate on /checkout endpoint
    • Latency spikes of 2-5 seconds on failed requests
    • Error types: PaymentGatewayTimeout, InventoryServiceError, CheckoutValidationError

  Open Over-Watch and investigate with:
    "Our checkout service started returning 500 errors about 1 minute ago.
     Error rate is around 40%. Some requests are also timing out."

  Or click the "🔴 Simulate Alert" button in the sidebar.
""")

    # Phase 5: Disable faults (optional — leave enabled for investigation)
    input("  Press Enter to disable fault injection (or Ctrl+C to leave it on)...")
    try:
        resp = httpx.get(f"{DEMO_APP_URL}/fault/disable", timeout=5.0)
        print(f"  ✅ Fault mode disabled: {resp.json()}")
    except Exception:
        pass

    print("\n  Done! Open Over-Watch to investigate the incident.")


if __name__ == "__main__":
    main()
