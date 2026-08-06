const path = require('path');
const pythonExec = path.join(__dirname, '.entorno', 'Scripts', 'pythonw.exe');

module.exports = {
  apps: [
    {
      name: 'api-server',
      script: pythonExec,
      args: '-m uvicorn api.server:app --host 127.0.0.1 --port 8000',
      interpreter: 'none',
      watch: false,
      autorestart: true,
      max_restarts: 10,
      env: {
        NODE_ENV: 'production'
      }
    },
    {
      name: 'telegram-bot',
      script: 'telegram_service.py',
      interpreter: pythonExec,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      env: {
        NODE_ENV: 'production'
      }
    },
    {
      name: 'dgt-grid-bot',
      script: 'scripts/dgt_bot.py',
      interpreter: pythonExec,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      env: {
        NODE_ENV: 'production'
      }
    }
  ]
};
