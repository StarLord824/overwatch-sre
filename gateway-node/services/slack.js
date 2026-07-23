const axios = require('axios');

const SLACK_WEBHOOK_URL = process.env.SLACK_WEBHOOK_URL;

/**
 * Sends the final investigation report to a Slack channel.
 * @param {Object} event - The final report event from the Python agent
 */
async function sendSlackReport(event) {
  if (!SLACK_WEBHOOK_URL) {
    console.log('[Slack] Webhook URL not configured. Skipping Slack notification.');
    return;
  }

  const { incident_id, data } = event;
  const { summary, root_cause, confidence, evidence } = data;

  const color = confidence === 'HIGH' ? '#36a64f' : (confidence === 'MEDIUM' ? '#eebb00' : '#ff0000');

  const payload = {
    text: `🚨 *Over-Watch Incident Report* [${incident_id}]`,
    attachments: [
      {
        color: color,
        blocks: [
          {
            type: 'section',
            text: {
              type: 'mrkdwn',
              text: `*Root Cause:*\n${root_cause}`
            }
          },
          {
            type: 'section',
            fields: [
              {
                type: 'mrkdwn',
                text: `*Confidence:*\n${confidence}`
              },
              {
                type: 'mrkdwn',
                text: `*Summary:*\n${summary}`
              }
            ]
          },
          {
            type: 'divider'
          },
          {
            type: 'section',
            text: {
              type: 'mrkdwn',
              text: `*Evidence Chain:*\n${evidence.map(e => `• ${e}`).join('\n')}`
            }
          }
        ]
      }
    ]
  };

  try {
    await axios.post(SLACK_WEBHOOK_URL, payload);
    console.log(`[Slack] Report sent for incident ${incident_id}`);
  } catch (error) {
    console.error('[Slack] Failed to send report:', error.message);
  }
}

module.exports = {
  sendSlackReport
};
