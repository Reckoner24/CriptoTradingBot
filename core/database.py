import aiosqlite
import json
import logging
import os

logger = logging.getLogger('bot_logger')
DB_PATH = "data/trading_bot.db"

async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
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
    try:
        async with aiosqlite.connect(DB_PATH) as db:
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
        async with aiosqlite.connect(DB_PATH) as db:
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
        return {"error": str(e)}
