const redis = require('redis');
const { sendSlackReport } = require('../services/slack');

const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379';
const AGENT_UPDATES_CHANNEL = 'agent_updates';

async function initRedisSubscriber(io) {
  const subscriber = redis.createClient({ url: REDIS_URL });

  subscriber.on('error', (err) => console.error('[Redis] Client Error', err));
  
  await subscriber.connect();
  console.log(`[Redis] Connected and subscribed to channel: ${AGENT_UPDATES_CHANNEL}`);

  await subscriber.subscribe(AGENT_UPDATES_CHANNEL, async (message) => {
    try {
      const event = JSON.parse(message);
      console.log(`[Redis] Received event: ${event.type} for incident ${event.incident_id}`);
      
      // Broadcast to all connected Next.js clients
      io.emit('agent_event', event);

      // If it's a final report, optionally send it to Slack
      if (event.type === 'final_report') {
        await sendSlackReport(event);
      }
    } catch (error) {
      console.error('[Redis] Error processing message:', error);
    }
  });
}

module.exports = {
  initRedisSubscriber
};
