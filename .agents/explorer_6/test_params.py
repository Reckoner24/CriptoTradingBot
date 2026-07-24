import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

import importlib.util

spec = importlib.util.spec_from_file_location(
    'bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot
spec.loader.exec_module(bot)

print(f"bot.LEVERAGE: {bot.LEVERAGE}")
print(f"bot.MAX_MARGIN_PER_TRADE_PCT: {bot.MAX_MARGIN_PER_TRADE_PCT}")
print(f"bot.MAX_TOTAL_MARGIN_PCT: {bot.MAX_TOTAL_MARGIN_PCT}")
print(f"bot.MAX_RISK: {bot.MAX_RISK}")
print(f"bot.RISK_PCT_MIN: {bot.RISK_PCT_MIN}")
print(f"bot.RISK_PCT_MAX: {bot.RISK_PCT_MAX}")
print(f"bot.MAX_ER_FOR_GRID: {bot.MAX_ER_FOR_GRID}")
print(f"bot.get_er_max('BTC/USDT'): {bot.get_er_max('BTC/USDT')}")
print(f"bot.get_er_max('ETH/USDT'): {bot.get_er_max('ETH/USDT')}")
print(f"bot.get_er_max('SOL/USDT'): {bot.get_er_max('SOL/USDT')}")
