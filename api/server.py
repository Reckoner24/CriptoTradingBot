from fastapi import FastAPI
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import get_latest_state

app = FastAPI(title="Cripto Trading Bot - Status API", version="1.0.0")

# Umbral de frescura del estado: si el timestamp tiene más de 60s, el estado se marca stale
STALE_THRESHOLD_SECONDS = 60


def _is_state_stale(state: dict) -> bool:
    """
    Devuelve True si el timestamp del estado tiene más de STALE_THRESHOLD_SECONDS
    de antigüedad (o si no se puede parsear, por seguridad).
    El timestamp viene de SQLite CURRENT_TIMESTAMP (UTC, 'YYYY-MM-DD HH:MM:SS').
    """
    ts = state.get("timestamp")
    if not ts:
        return True
    try:
        parsed = datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    age = (datetime.now(timezone.utc) - parsed).total_seconds()
    return age > STALE_THRESHOLD_SECONDS


@app.get("/")
async def root():
    return {"message": "Cripto Trading Bot API está en linea. Consulta /status para ver el estado actual."}

import ccxt.async_support as ccxt
from dotenv import load_dotenv
load_dotenv()

@app.get("/status")
async def get_status():
    """
    Devuelve el último estado guardado por el bot en la base de datos SQLite.
    Adicionalmente, consulta Binance en tiempo real para obtener el balance exacto.
    """
    state = await get_latest_state()
    if state:
        if "error" in state:
            return {"status": "error", "message": state["error"]}

        # Fetch live balance para exactitud milimetrica
        try:
            exchange = ccxt.binance({
                'apiKey': os.getenv("BINANCE_API_KEY"),
                'secret': os.getenv("BINANCE_API_SECRET"),
                'enableRateLimit': False,
                'options': {'defaultType': 'future'}
            })
            if os.getenv("USE_TESTNET", "True").lower() == "true":
                exchange.set_sandbox_mode(True)
                
            balance = await exchange.fetch_balance()
            if 'USDT' in balance:
                state['balance'] = balance['USDT'].get('total', balance['USDT']['free'])
                state['free_balance'] = balance['USDT']['free']
            await exchange.close()
        except Exception as e:
            pass # Si falla (ej. rate limit), usamos el cache de SQLite

        # Campo nuevo: los consumidores pueden saber si el trading-core está vivo
        state["stale"] = _is_state_stale(state)

        return {
            "status": "success",
            "data": state
        }
    return {"status": "waiting", "message": "Aún no hay datos del bot"}

@app.get("/positions")
async def get_positions():
    """
    Devuelve unicamente las posiciones abiertas actuales del bot.
    """
    state = await get_latest_state()
    if state and "open_positions" in state:
        return {
            "status": "success",
            "open_positions": state["open_positions"]
        }
    return {"status": "waiting", "message": "No hay posiciones registradas"}
