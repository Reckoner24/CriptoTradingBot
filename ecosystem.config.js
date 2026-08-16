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
        NODE_ENV: 'production',
        DGT_LEVERAGE: '20',
        DGT_CAPITAL: '45'
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
        NODE_ENV: 'production',
        DGT_LEVERAGE: '20',
        DGT_CAPITAL: '45'
      }
    },
    {
      name: 'dgt-grid-bot',
      script: 'dgt_bot_sol.py',
      interpreter: pythonExec,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      env: {
        NODE_ENV: 'production',
        DGT_LEVERAGE: '20',
        DGT_CAPITAL: '45'
      }
    }
  ]
};
