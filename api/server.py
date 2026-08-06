import sys
import os
import asyncio
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from fastapi import FastAPI
from dotenv import load_dotenv
from core.database import get_latest_state, init_db
import ccxt
from datetime import datetime, timezone

load_dotenv()
logger = logging.getLogger(__name__)

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
    ex.options['recvWindow'] = 30000
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

        raw_entry = float(item.get('entryPrice', 0))
        if raw_entry > 0:
            entry = raw_entry
        else:
            if side == 'LONG':
                entry = (notional - upnl) / size if size > 0 else 0
            else:
                entry = (abs(notional) + upnl) / abs(size) if abs(size) > 0 else 0

        raw_mark = float(item.get('markPrice', 0))
        if raw_mark > 0:
            mark = raw_mark
        else:
            mark = abs(notional) / abs(size) if abs(size) > 0 else entry

        size_usd = abs(size) * entry if entry > 0 else abs(notional)

        open_pos.setdefault(sym, {})[side] = {
            'entry_price': entry,
            'size_usd': size_usd,
            'unrealized_pnl': upnl,
            'mark_price': mark,
        }
    return open_pos

@app.get("/")
async def root():
    return {"message": "Cripto Trading Bot API. /status para estado en vivo."}

@app.get("/status")
async def get_status():
    # 1. Consultar DGT state de SQLite (siempre)
    dgt_state = None
    try:
        state = await get_latest_state()
        if state and "dgt" in state:
            dgt_state = state["dgt"]
    except Exception:
        pass

    # 2. Consultar Binance en vivo
    try:
        ex = _binance()
        if ex:
            bal = await asyncio.to_thread(ex.fetch_balance)
            usdt = bal['total'].get('USDT', 0)
            free = bal['free'].get('USDT', 0)
            open_pos = _parse_positions(bal)
            result = {
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
            if dgt_state:
                result["data"]["dgt"] = dgt_state
            return result
    except Exception as e:
        pass

    # 3. Fallback completo a SQLite
    state = await get_latest_state()
    if state:
        if "error" in state:
            return {"status": "error", "message": state["error"]}
        result = {"status": "success", "data": state}
        if dgt_state:
            result["data"]["dgt"] = dgt_state
        return result
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
        orders = await asyncio.to_thread(ex.fetch_open_orders)
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
        result.sort(key=lambda x: x["symbol"])
        return {"status": "success", "orders": result, "count": len(result)}
    except Exception as e:
        return {"status": "error", "message": f"Binance: {e}"}

@app.get("/metrics")
async def get_metrics():
    try:
        ex = _binance()
        trades = []
        if ex:
            try:
                trades = await asyncio.to_thread(ex.fetch_my_trades, limit=50)
            except Exception:
                trades = []

        if not trades:
            return {
                "status": "success",
                "data": {
                    "trades": 0,
                    "net_pnl": 0.0,
                    "win_rate": 0.0,
                    "profit_factor": None
                }
            }

        wins, losses = 0, 0
        total_pnl = 0.0
        gross_profit, gross_loss = 0.0, 0.0

        for t in trades:
            pnl = float(t.get('info', {}).get('realizedPnl', 0.0))
            total_pnl += pnl
            if pnl > 0:
                wins += 1
                gross_profit += pnl
            elif pnl < 0:
                losses += 1
                gross_loss += abs(pnl)

        total_closed = wins + losses
        win_rate = (wins / total_closed) if total_closed > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (None if gross_profit == 0 else 999.99)

        return {
            "status": "success",
            "data": {
                "trades": total_closed,
                "net_pnl": total_pnl,
                "win_rate": win_rate,
                "profit_factor": profit_factor
            }
        }
    except Exception as e:
        return {
            "status": "success",
            "data": {
                "trades": 0,
                "net_pnl": 0.0,
                "win_rate": 0.0,
                "profit_factor": None
            }
        }

from pydantic import BaseModel

class ClosePositionRequest(BaseModel):
    symbol: str

@app.post("/close_position")
async def close_position_endpoint(req: ClosePositionRequest):
    try:
        ex = _binance()
        if not ex:
            return {"status": "error", "message": "Sin credenciales de Binance"}
        
        symbol = req.symbol.upper().strip()
        if '/' not in symbol and 'USDT' in symbol:
            symbol = symbol.replace('USDT', '/USDT')
        
        raw_sym = symbol.replace('/', '')
        
        # 1. Registrar manual_reset en SQLite para notificar al bot DGT que reinicie su estado
        import sqlite3, os
        db_path = "data/trading_bot.db"
        try:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS manual_resets (symbol TEXT PRIMARY KEY, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("INSERT OR REPLACE INTO manual_resets (symbol) VALUES (?)", (symbol,))
            conn.commit()
            conn.close()
        except Exception as db_e:
            logger.error(f"Error escribiendo manual_reset en DB: {db_e}")

        # 2. Cancelar órdenes abiertas para ese símbolo
        try:
            await asyncio.to_thread(ex.cancel_all_orders, symbol)
        except Exception:
            pass

        # 2. Consultar posición real en Binance
        bal = await asyncio.to_thread(ex.fetch_balance)
        positions = bal.get('info', {}).get('positions', [])
        target_pos = None
        for p in positions:
            if p.get('symbol') == raw_sym and float(p.get('positionAmt', 0)) != 0:
                target_pos = p
                break
        
        if not target_pos:
            return {"status": "error", "message": f"No hay posición abierta activa para {symbol}"}
        
        amt = float(target_pos.get('positionAmt', 0))
        close_amt = float(ex.amount_to_precision(symbol, abs(amt)))
        if close_amt <= 0:
            return {"status": "error", "message": f"Cantidad inválida a cerrar para {symbol}: {amt}"}

        side = "sell" if amt > 0 else "buy"
        params = {'reduceOnly': True}
        if side == "sell":
            order = await asyncio.to_thread(ex.create_market_sell_order, symbol, close_amt, params)
        else:
            order = await asyncio.to_thread(ex.create_market_buy_order, symbol, close_amt, params)

        avg_price = order.get('average') or order.get('price')
        if not avg_price or float(avg_price) == 0:
            info = order.get('info', {})
            cum_quote = float(info.get('cumQuote', 0))
            executed_qty = float(info.get('executedQty', 0))
            if executed_qty > 0 and cum_quote > 0:
                avg_price = cum_quote / executed_qty
            else:
                try:
                    ticker = await asyncio.to_thread(ex.fetch_ticker, symbol)
                    avg_price = ticker.get('last', 0.0)
                except Exception:
                    avg_price = 0.0

        return {
            "status": "success",
            "message": f"Posición {symbol} ({amt}) cerrada a mercado exitosamente",
            "order_id": order.get('id'),
            "close_price": float(avg_price)
        }
    except Exception as e:
        return {"status": "error", "message": f"Error cerrando posición: {e}"}

