from fastapi import FastAPI
from pydantic import BaseModel
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import get_latest_state

app = FastAPI(title="Cripto Trading Bot - Status API", version="1.0.0")

@app.get("/")
async def root():
    return {"message": "Cripto Trading Bot API está en linea. Consulta /status para ver el estado actual."}

@app.get("/status")
async def get_status():
    """
    Devuelve el último estado guardado por el bot en la base de datos SQLite.
    """
    state = await get_latest_state()
    if state:
        if "error" in state:
            return {"status": "error", "message": state["error"]}
            
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
