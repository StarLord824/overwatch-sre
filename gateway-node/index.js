const express = require('express');
const http = require('http');
const cors = require('cors');
const { Server } = require('socket.io');
const dotenv = require('dotenv');

dotenv.config();

// Initialize Express & Socket.io
const app = express();
// The Socket.io CORS block below only covers the websocket handshake - the
// plain REST routes (e.g. the dashboard's "Simulate Alert" POST) need their
// own CORS headers or the browser blocks the request before it ever reaches
// the webhook handler.
app.use(cors({ origin: '*' }));
app.use(express.json());
const server = http.createServer(app);
const io = new Server(server, {
  cors: {
    origin: '*', // Allow Next.js frontend to connect
    methods: ['GET', 'POST']
  }
});

// Import modules
const { initRabbitMQ } = require('./queue/rabbitmq');
const { initRedisSubscriber } = require('./queue/redis');
const webhookRoutes = require('./routes/webhook');

// Setup Socket.io connection handling
io.on('connection', (socket) => {
  console.log(`[Socket.io] Client connected: ${socket.id}`);
  
  socket.on('disconnect', () => {
    console.log(`[Socket.io] Client disconnected: ${socket.id}`);
  });
});

// Register routes
app.use('/api/webhooks', webhookRoutes);

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'gateway-node' });
});

const PORT = process.env.PORT || 4000;

async function bootstrap() {
  try {
    // 1. Connect to RabbitMQ
    await initRabbitMQ();
    
    // 2. Connect to Redis and pass io instance to broadcast events
    await initRedisSubscriber(io);

    // 3. Start server
    server.listen(PORT, () => {
      console.log(`[Gateway] Server running on port ${PORT}`);
    });
  } catch (error) {
    console.error('[Gateway] Failed to start:', error);
    process.exit(1);
  }
}

bootstrap();
