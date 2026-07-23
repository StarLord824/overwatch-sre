const amqp = require('amqplib');

const RABBITMQ_URL = process.env.RABBITMQ_URL || 'amqp://guest:guest@localhost:5672';
const QUEUE_NAME = 'incidents_queue';

let channel = null;

async function initRabbitMQ() {
  try {
    const connection = await amqp.connect(RABBITMQ_URL);
    channel = await connection.createChannel();
    await channel.assertQueue(QUEUE_NAME, { durable: true });
    console.log(`[RabbitMQ] Connected and asserted queue: ${QUEUE_NAME}`);
  } catch (error) {
    console.error('[RabbitMQ] Connection failed:', error);
    throw error;
  }
}

async function publishIncident(incident) {
  if (!channel) {
    throw new Error('RabbitMQ channel not initialized');
  }
  
  const buffer = Buffer.from(JSON.stringify(incident));
  const result = channel.sendToQueue(QUEUE_NAME, buffer, { persistent: true });
  
  if (!result) {
    console.warn('[RabbitMQ] Queue is full or connection closed');
  }
  return result;
}

module.exports = {
  initRabbitMQ,
  publishIncident
};
