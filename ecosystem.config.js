module.exports = {
  apps: [
    {
      name: 'api-server',
      script: 'pythonw',
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
      name: 'trading-core',
      script: 'scripts/bot_live_bidirectional.py',
      interpreter: 'pythonw',
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
      interpreter: 'pythonw',
      watch: false,
      autorestart: true,
      max_restarts: 10,
      env: {
        NODE_ENV: 'production'
      }
    }
  ]
