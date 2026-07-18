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

@app.get("/status")
async def get_status():
    """
    Devuelve el último estado guardado por el bot en la base de datos SQLite.
    Incluye 'stale': true si el estado tiene más de 60s sin actualizarse.
    """
    state = await get_latest_state()
    if state:
        if "error" in state:
            return {"status": "error", "message": state["error"]}

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
