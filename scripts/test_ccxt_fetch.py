import ccxt
import os
import time
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
    order_id = order['id']
    print(f"Orden ejecutada con ID: {order_id}")
    time.sleep(1)
    
    # fetch_order
    fetched = exchange.fetch_order(order_id, 'SOL/USDT')
    print("Fetched average:", fetched.get('average'))
    
    # fetch_my_trades
    trades = exchange.fetch_my_trades('SOL/USDT', limit=1)
    if trades:
        print("Latest trade price:", trades[-1].get('price'))
        
except Exception as e:
    print("Error:", e)
