import sys
import os
import scripts.dgt_bot as dgt_bot
dgt_bot.SYMBOLS = ['SOL/USDT']
# Leverage viene solo de .env (DGT_LEVERAGE) -- no hardcodear aqui, ver auditoria 2026-08-14
if __name__ == '__main__':
    dgt_bot.main()