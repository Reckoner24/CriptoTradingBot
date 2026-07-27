"""FastAPI server. /status now queries Binance live (fallback a SQLite)."""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from dotenv import load_dotenv
from core.database import get_latest_state, init_db
import ccxt
from datetime import datetime, timezone

load_dotenv()

app = FastAPI(title="Cripto Trading Bot - Status API", version="1.0.0")

@app.on_event("startup")
async def startup():
    await init_db()

def _binance():
    key = os.getenv('BINANCE_TESTNET_KEY') or os.getenv('BINANCE_MAIN_KEY')
    secret = os.getenv('BINANCE_TESTNET_SECRET') or os.getenv('BINANCE_MAIN_SECRET')
    if not key or not secret:
        return None
    ex = ccxt.binance({
        'apiKey': key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'},
    })
    if os.getenv('BINANCE_TESTNET_KEY'):
        ex.enable_demo_trading(True)
    return ex

def _parse_positions(bal):
    """Extract open positions from Binance balance response."""
    open_pos = {}
    for item in bal.get('info', {}).get('positions', []):
        size = float(item.get('positionAmt', 0))
        if abs(size) < 0.001:
            continue
        sym = item['symbol']
        side = 'LONG' if size > 0 else 'SHORT'
        notional = float(item.get('notional', 0))
        upnl = float(item.get('unrealizedProfit', 0))
        mark = notional / abs(size) if abs(size) > 0 and notional > 0 else 0
        entry = (notional - upnl) / abs(size) if abs(size) > 0 and notional > 0 else 0
        open_pos[sym] = {
            side: {
                'entry_price': entry,
                'size_usd': abs(size) * entry if entry > 0 else 0,
                'unrealized_pnl': upnl,
                'mark_price': mark,
            }
        }
    return open_pos

@app.get("/")
async def root():
    return {"message": "Cripto Trading Bot API. /status para estado en vivo."}

@app.get("/status")
async def get_status():
    try:
        ex = _binance()
        if ex:
            bal = ex.fetch_balance()
            usdt = bal['total'].get('USDT', 0)
            free = bal['free'].get('USDT', 0)
            open_pos = _parse_positions(bal)
            return {
                "status": "success",
                "data": {
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "running",
                    "balance": usdt,
                    "free_balance": free,
                    "open_positions": open_pos,
                    "last_wfo_time": "",
                }
            }
    except Exception as e:
        return {"status": "error", "message": f"Binance: {e}"}

    # Fallback a SQLite
    state = await get_latest_state()
    if state:
        if "error" in state:
            return {"status": "error", "message": state["error"]}
        return {"status": "success", "data": state}
    return {"status": "waiting", "message": "Sin datos"}

@app.get("/positions")
async def get_positions():
    data = (await get_status()).get("data", {})
    if data and "open_positions" in data:
        return {"status": "success", "open_positions": data["open_positions"]}
    return {"status": "waiting", "message": "No hay posiciones"}

@app.get("/orders")
async def get_orders():
    try:
        ex = _binance()
        if not ex:
            return {"status": "error", "message": "Sin credenciales"}
        ex.options.setdefault('fetchOpenOrders', {})['warnWithoutSymbol'] = False
        orders = ex.fetch_open_orders()
        result = []
        for o in orders:
            result.append({
                "symbol": o["symbol"],
                "side": o["side"],
                "type": o["type"],
                "price": o["price"],
                "amount": o["amount"],
                "filled": o["filled"],
                "remaining": o["remaining"],
                "status": o["status"],
                "id": o["id"],
            })
        # Ordenar por símbolo
        result.sort(key=lambda x: x["symbol"])
        return {"status": "success", "orders": result, "count": len(result)}
    except Exception as e:
        return {"status": "error", "message": f"Binance: {e}"}
