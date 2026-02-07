const WebSocket = require('ws');
const express = require('express');
const fetch = require('node-fetch');

const app = express();
const wss = new WebSocket.Server({ port: 8080 });

let latestData = { status: "connected", timestamp: Date.now() };

wss.on('connection', ws => {
  ws.send(JSON.stringify(latestData));
});

setInterval(() => {
  latestData = {
    metric: Math.random() * 100,
    timestamp: Date.now()
  };

  wss.clients.forEach(client => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(JSON.stringify(latestData));
    }
  });
}, 1000);

// í´¹ Telegram Feed Endpoint
app.get('/telegram', async (_, res) => {
  res.json([
    { user: "MERID", message: "Live intelligence update", time: Date.now() }
  ]);
});

app.listen(8080, () =>
  console.log('MERID backend running on ws://localhost:8080')
);
