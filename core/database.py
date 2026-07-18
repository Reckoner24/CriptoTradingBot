import asyncio
import aiosqlite
import json
import logging
from pathlib import Path

logger = logging.getLogger('bot_logger')

# Ruta anclada al raíz del repo (independiente del CWD desde el que se lance el proceso)
DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'trading_bot.db'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Lock a nivel de módulo para serializar escrituras concurrentes fire-and-forget
# y evitar errores 'database is locked' de SQLite.
_db_write_lock = asyncio.Lock()

async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS bot_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT,
                balance REAL,
                free_balance REAL,
                open_positions TEXT,
                last_wfo_time TEXT
            )
        ''')
        await db.commit()
        logger.info("Base de datos SQLite inicializada correctamente.")

async def update_bot_state(status: str, balance: float, free_balance: float, open_positions: dict, last_wfo_time: str):
    async with _db_write_lock:
        try:
            async with aiosqlite.connect(str(DB_PATH)) as db:
                pos_json = json.dumps(open_positions)
                # Primero checamos si existe la fila 1
                async with db.execute('SELECT 1 FROM bot_state WHERE id = 1') as cursor:
                    row = await cursor.fetchone()
                    if row:
                        await db.execute('''
                            UPDATE bot_state
                            SET timestamp = CURRENT_TIMESTAMP, status = ?, balance = ?, free_balance = ?, open_positions = ?, last_wfo_time = ?
                            WHERE id = 1
                        ''', (status, balance, free_balance, pos_json, last_wfo_time))
                    else:
                        await db.execute('''
                            INSERT INTO bot_state (id, status, balance, free_balance, open_positions, last_wfo_time)
                            VALUES (1, ?, ?, ?, ?, ?)
                        ''', (status, balance, free_balance, pos_json, last_wfo_time))
                await db.commit()
        except Exception as e:
            logger.error(f"Error actualizando la base de datos: {e}")

async def get_latest_state():
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            async with db.execute('SELECT timestamp, status, balance, free_balance, open_positions, last_wfo_time FROM bot_state ORDER BY id DESC LIMIT 1') as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "timestamp": row[0],
                        "status": row[1],
                        "balance": row[2],
                        "free_balance": row[3],
                        "open_positions": json.loads(row[4]),
                        "last_wfo_time": row[5]
                    }
                return None
    except Exception as e:
        # Tipo de retorno consistente: dict con el estado o None (nunca {'error': ...})
        logger.error(f"Error leyendo el último estado de la base de datos: {e}")
        return None
