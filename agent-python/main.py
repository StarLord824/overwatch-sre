"""
Over-Watch agent worker.

Consumes incidents from RabbitMQ, sanitizes them, runs the direct tool-calling
investigation loop against the SigNoz MCP server, and streams every step back to
the Node.js gateway via Redis pub/sub (which relays to the dashboard + Slack).
"""

import json
import asyncio
import logging

import pika
import redis

from config import RABBITMQ_URL, REDIS_URL, QUEUE_NAME, REDIS_CHANNEL
from agent import Investigator
from utils.masking import sanitize_alert_payload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def publish_update(incident_id: str, update: dict) -> None:
    """Publish an agent event to Redis for the Node.js gateway to relay."""
    payload = {"incident_id": incident_id, **update}
    redis_client.publish(REDIS_CHANNEL, json.dumps(payload))
    logger.info("[Redis Publish] %s - %s", incident_id, update.get("type"))


async def async_process_incident(incident_id: str, raw_payload: dict) -> None:
    # 1. Mask PII before anything touches an external LLM.
    safe_payload = sanitize_alert_payload(raw_payload)
    logger.info("Sanitized payload for %s", incident_id)
    publish_update(incident_id, {
        "type": "status",
        "content": "Alert received and sanitized. Starting investigation.",
    })

    # 2. Run the streaming investigation loop.
    def emit(event: dict) -> None:
        publish_update(incident_id, event)

    investigator = Investigator(emit=emit)
    await investigator.investigate(safe_payload)


def process_incident(ch, method, properties, body) -> None:
    try:
        incident = json.loads(body)
        incident_id = incident.get("id", "unknown")
        raw_payload = incident.get("raw_payload", {})
        logger.info("Picked up incident: %s", incident_id)

        asyncio.run(async_process_incident(incident_id, raw_payload))

        logger.info("Completed investigation for %s", incident_id)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error processing incident: %s", exc)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main() -> None:
    logger.info("Starting Over-Watch agent worker...")
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=process_incident)

    logger.info("Waiting for incidents on %s. CTRL+C to exit.", QUEUE_NAME)
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        logger.info("Shutting down worker...")
        channel.stop_consuming()
    connection.close()


if __name__ == "__main__":
    main()
