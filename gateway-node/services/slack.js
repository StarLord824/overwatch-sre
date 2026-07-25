/*
 * Slack delivery from the gateway.
 *
 * Uses the runtime's built-in fetch (Node 18+) rather than an HTTP client
 * dependency - one less package, and one less way for the gateway to fail to
 * boot.
 *
 * Note: the Python agent also delivers reports directly (agent/notify.py). Set
 * SLACK_WEBHOOK_URL in exactly one of the two, or the same report is posted
 * twice.
 */

const SLACK_WEBHOOK_URL = process.env.SLACK_WEBHOOK_URL;

const CONFIDENCE_COLOR = {
  HIGH: '#7ee787',
  MEDIUM: '#ffb454',
  LOW: '#f26d6d',
};

/**
 * Sends the final investigation report to a Slack channel.
 * @param {Object} event - the final_report event from the Python agent
 */
async function sendSlackReport(event) {
  if (!SLACK_WEBHOOK_URL) {
    console.log('[Slack] No webhook configured, skipping.');
    return;
  }

  const { incident_id, data = {} } = event;
  const {
    summary,
    root_cause,
    confidence,
    evidence = [],
    prevention,
    signoz_links = [],
    signoz_live,
  } = data;

  const blocks = [
    {
      type: 'section',
      text: { type: 'mrkdwn', text: `*Root cause*\n${root_cause || 'n/a'}` },
    },
    {
      type: 'section',
      fields: [
        { type: 'mrkdwn', text: `*Confidence*\n${confidence || 'n/a'}` },
        { type: 'mrkdwn', text: `*Remediation*\n${summary || 'n/a'}` },
      ],
    },
  ];

  if (signoz_live === false) {
    blocks.push({
      type: 'context',
      elements: [
        {
          type: 'mrkdwn',
          text: ':warning: This run used mock telemetry - SigNoz was unreachable.',
        },
      ],
    });
  }

  if (evidence.length) {
    blocks.push(
      { type: 'divider' },
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `*Evidence*\n${evidence.slice(0, 5).map((e) => `• ${e}`).join('\n')}`,
        },
      },
    );
  }

  if (prevention) {
    blocks.push({
      type: 'section',
      text: { type: 'mrkdwn', text: `*Prevention*\n${prevention}` },
    });
  }

  if (signoz_links.length) {
    blocks.push({
      type: 'context',
      elements: [
        {
          type: 'mrkdwn',
          text: signoz_links
            .slice(0, 4)
            .map((l) => `<${l.url}|${l.label}>`)
            .join('  ·  '),
        },
      ],
    });
  }

  const payload = {
    text: `Over-Watch incident report [${incident_id}]`,
    attachments: [
      {
        color: CONFIDENCE_COLOR[String(confidence).toUpperCase()] || '#8b97a8',
        blocks,
      },
    ],
  };

  try {
    const resp = await fetch(SLACK_WEBHOOK_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      // Slack answers with a plain-text reason (e.g. "invalid_payload").
      console.error(`[Slack] Rejected (${resp.status}): ${await resp.text()}`);
      return;
    }
    console.log(`[Slack] Report sent for incident ${incident_id}`);
  } catch (error) {
    console.error('[Slack] Failed to send report:', error.message);
  }
}

module.exports = { sendSlackReport };
