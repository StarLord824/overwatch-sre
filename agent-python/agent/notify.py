"""
Report delivery — post the finished investigation to an external channel.

This is OpenSRE's final step: once the agent produces an evidence-backed RCA, it
delivers a summary to where the on-call engineer actually is — Slack and/or
Telegram — so there's no context switch back to a dashboard.

Delivery is configured entirely by env and is a no-op if nothing is set, so the
agent runs fine with or without it:

  SLACK_WEBHOOK_URL       — a Slack incoming-webhook URL
  TELEGRAM_BOT_TOKEN      — a Telegram bot token (from @BotFather)
  TELEGRAM_CHAT_ID        — the chat/channel id to post to

Returns the list of channels it actually delivered to, for a status event.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def _confidence_emoji(confidence: str) -> str:
    return {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get((confidence or "").upper(), "⚪")


def _plain_summary(report: dict, alert: dict) -> str:
    """A compact, channel-agnostic text summary of the RCA."""
    alert_name = alert.get("alert_name") or alert.get("service") or "Production alert"
    conf = report.get("confidence", "—")
    lines = [
        f"🛡️ Over-Watch RCA — {alert_name}",
        "",
        f"{_confidence_emoji(conf)} Confidence: {conf}"
        + ("" if report.get("signoz_live", True) else "  (⚠ MOCK data — SigNoz not connected)"),
        "",
        f"Root cause: {report.get('root_cause', 'n/a')}",
    ]
    evidence = report.get("evidence") or []
    if evidence:
        lines += ["", "Evidence:"] + [f"  • {e}" for e in evidence[:5]]
    if report.get("prevention"):
        lines += ["", f"Prevention (recommended): {report['prevention']}"]
    links = report.get("signoz_links") or []
    if links:
        lines += ["", "Open in SigNoz:"] + [f"  • {l['label']}: {l['url']}" for l in links[:4]]
    return "\n".join(lines)


async def _post_slack(report: dict, alert: dict) -> bool:
    url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        return False
    conf = report.get("confidence", "")
    color = {"HIGH": "#36a64f", "MEDIUM": "#eebb00"}.get(conf.upper(), "#ff0000")
    alert_name = alert.get("alert_name") or alert.get("service") or "Production alert"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn",
         "text": f"*🛡️ Over-Watch RCA — {alert_name}*"}},
        {"type": "section", "text": {"type": "mrkdwn",
         "text": f"*Root Cause:*\n{report.get('root_cause', 'n/a')}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Confidence:*\n{_confidence_emoji(conf)} {conf}"},
            {"type": "mrkdwn", "text": f"*Summary:*\n{report.get('summary', '')[:2500]}"},
        ]},
    ]
    evidence = report.get("evidence") or []
    if evidence:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": "*Evidence:*\n" + "\n".join(f"• {e}" for e in evidence[:5])}})
    if report.get("prevention"):
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": f"*🛡️ Prevention (recommended):*\n{report['prevention']}"}})
    links = report.get("signoz_links") or []
    if links:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": "*Open in SigNoz:*\n" + "\n".join(f"• <{l['url']}|{l['label']}>" for l in links[:4])}})

    payload = {"attachments": [{"color": color, "blocks": blocks}]}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Slack delivery failed: %s", exc)
        return False


async def _post_telegram(report: dict, alert: dict) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    text = _plain_summary(report, alert)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            )
            resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram delivery failed: %s", exc)
        return False


async def deliver_report(report: dict, alert: dict) -> list[str]:
    """Post the report to every configured channel. Returns the ones that succeeded."""
    delivered: list[str] = []
    if await _post_slack(report, alert):
        delivered.append("Slack")
    if await _post_telegram(report, alert):
        delivered.append("Telegram")
    return delivered
