module.exports = {
  apps: [
    {
      name: 'api-server',
      script: 'pythonw',
      args: '-m uvicorn api.server:app --host 127.0.0.1 --port 8000',
      interpreter: 'none',
      cwd: __dirname,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      exp_backoff_restart_delay: 10000,
      env: {
        NODE_ENV: 'production'
      }
    },
    {
      name: 'trading-core',
      script: 'scripts/bot_live_bidirectional.py',
      interpreter: 'pythonw',
      cwd: __dirname,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      exp_backoff_restart_delay: 10000,
      max_memory_restart: '400M',
      env: {
        NODE_ENV: 'production'
      }
    },
    {
      name: 'telegram-bot',
      script: 'telegram_service.py',
      interpreter: 'pythonw',
      cwd: __dirname,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      exp_backoff_restart_delay: 10000,
      env: {
        NODE_ENV: 'production'
      }
    }
  ]
};
