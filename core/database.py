import aiosqlite
import json
import logging
import os

logger = logging.getLogger('bot_logger')
DB_PATH = os.path.abspath("data/trading_bot.db")

async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        try:
            await db.execute('PRAGMA journal_mode=WAL;')
            await db.execute('PRAGMA busy_timeout=30000;')
        except Exception:
            pass
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
        # Migration: add free_balance if missing
        try:
            await db.execute('ALTER TABLE bot_state ADD COLUMN free_balance REAL')
        except aiosqlite.OperationalError:
            pass
        # Migration: add dgt_state if missing
        try:
            await db.execute('ALTER TABLE bot_state ADD COLUMN dgt_state TEXT')
        except aiosqlite.OperationalError:
            pass
        await db.commit()
        logger.info("Base de datos SQLite inicializada correctamente.")

async def update_bot_state(status: str, balance: float, free_balance: float, open_positions: dict, last_wfo_time: str):
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
            await db.execute('PRAGMA journal_mode=WAL;')
            await db.execute('PRAGMA busy_timeout=30000;')
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

async def update_dgt_state(dgt_data: dict):
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
            await db.execute('PRAGMA journal_mode=WAL;')
            await db.execute('PRAGMA busy_timeout=30000;')
            dgt_json = json.dumps(dgt_data)
            async with db.execute('SELECT 1 FROM bot_state WHERE id = 1') as cursor:
                row = await cursor.fetchone()
                if row:
                    await db.execute('UPDATE bot_state SET dgt_state = ? WHERE id = 1', (dgt_json,))
                else:
                    await db.execute('INSERT INTO bot_state (id, dgt_state) VALUES (1, ?)', (dgt_json,))
            await db.commit()
    except Exception as e:
        logger.error(f"Error actualizando DGT state: {e}")

async def get_latest_state():
    try:
        async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
            await db.execute('PRAGMA journal_mode=WAL;')
            await db.execute('PRAGMA busy_timeout=30000;')
            async with db.execute('SELECT timestamp, status, balance, free_balance, open_positions, last_wfo_time, dgt_state FROM bot_state WHERE id = 1') as cursor:
                row = await cursor.fetchone()
                if row:
                    result = {
                        "timestamp": row[0],
                        "status": row[1],
                        "balance": row[2],
                        "free_balance": row[3],
                        "open_positions": json.loads(row[4]) if row[4] else {},
                        "last_wfo_time": row[5],
                    }
                    if row[6]:
                        result["dgt"] = json.loads(row[6])
                    return result
                return None
    except Exception as e:
        return {"error": str(e)}
