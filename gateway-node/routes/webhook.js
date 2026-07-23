const express = require('express');
const router = express.Router();
const { publishIncident } = require('../queue/rabbitmq');

/**
 * POST /api/webhooks/signoz
 * Endpoint for SigNoz to send alert webhooks when an anomaly is detected.
 */
router.post('/signoz', async (req, res) => {
  try {
    const alertPayload = req.body;
    
    console.log('[Webhook] Received alert from SigNoz:', alertPayload.alert_name || 'Unknown Alert');
    
    // Construct a standardized incident object
    const incident = {
      id: `inc-${Date.now()}`,
      source: 'signoz',
      timestamp: new Date().toISOString(),
      raw_payload: alertPayload,
      status: 'pending_investigation'
    };

    // Push to RabbitMQ for the Python worker to pick up
    await publishIncident(incident);

    console.log(`[Webhook] Incident ${incident.id} queued successfully.`);
    return res.status(202).json({ message: 'Alert received and queued', incident_id: incident.id });
  } catch (error) {
    console.error('[Webhook] Error processing alert:', error);
    return res.status(500).json({ error: 'Internal Server Error' });
  }
});

module.exports = router;
