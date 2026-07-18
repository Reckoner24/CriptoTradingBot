import ccxt
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("BINANCE_TESTNET_KEY", "")
API_SECRET = os.getenv("BINANCE_TESTNET_SECRET", "")

exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})
exchange.enable_demo_trading(True)
exchange.apiKey = API_KEY
exchange.secret = API_SECRET

try:
    print("Abriendo posicion...")
    order = exchange.create_market_order('SOL/USDT', 'buy', 0.2)
    print("Orden recibida:")
    print(order)
except Exception as e:
    print("Error:", e)
