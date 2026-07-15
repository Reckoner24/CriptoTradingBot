import os
import json
import logging
import asyncio
import aiohttp
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURACION ---
load_dotenv()
TELEGRAM_BOT_API = os.getenv("TELEGRAM_BOT_API", "")
TELEGRAM_ID = os.getenv("TELEGRAM_ID", "")
API_URL = "http://127.0.0.1:8000"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- GESTION DE ADMINISTRADOR ---
def is_authorized(update: Update) -> bool:
    chat_id = str(update.effective_chat.id)
    
    if not TELEGRAM_ID:
        logger.error("TELEGRAM_ID no está configurado en .env")
        return False
        
    if chat_id != TELEGRAM_ID:
        logger.warning(f"Intento de acceso no autorizado desde Chat ID: {chat_id}")
        return False
        
    return True

# --- LLAMADAS A LA API LOCAL ---
async def fetch_api(endpoint: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_URL}{endpoint}") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return {"status": "error", "message": f"HTTP Error {response.status}"}
    except Exception as e:
        logger.error(f"Error conectando a la API local: {e}")
        return {"status": "error", "message": "No se pudo conectar a la API local. ¿Está uvicorn corriendo?"}

# --- COMANDOS DEL BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado para usar este bot.")
        return
        
    welcome_msg = (
        "🤖 *Cripto Trading Bot*\n\n"
        "¡Hola! Soy tu bot asistente. A partir de ahora solo responderé a tus comandos.\n\n"
        "Comandos disponibles:\n"
        "🔹 /status - Resumen del balance y estado del sistema\n"
        "🔹 /posiciones - Detalles de las operaciones abiertas"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
        
    await update.message.reply_chat_action(action="typing")
    data = await fetch_api("/status")
    
    if data.get("status") == "success":
        bot_data = data["data"]
        balance = bot_data.get("balance", 0.0)
        bot_state = bot_data.get("status", "Desconocido")
        last_update = bot_data.get("timestamp", "Nunca")
        open_pos_count = len(bot_data.get("open_positions", {}))
        
        msg = (
            "📊 *Estado del Bot*\n"
            f"💰 *Balance Total:* `${balance:,.2f}` USDT\n"
            f"🔄 *Estado:* `{bot_state}`\n"
            f"📈 *Pares con Posiciones:* `{open_pos_count}`\n"
            f"⏱ *Última Actualización:* `{last_update}`"
        )
    else:
        msg = f"⚠️ *Error al obtener el estado:*\n{data.get('message', 'Desconocido')}"
        
    await update.message.reply_text(msg, parse_mode="Markdown")

async def posiciones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
        
    await update.message.reply_chat_action(action="typing")
    data = await fetch_api("/status")
    
    if data.get("status") == "success":
        bot_data = data["data"]
        open_pos = bot_data.get("open_positions", {})
        
        if not open_pos:
            await update.message.reply_text("✅ No hay posiciones abiertas actualmente.")
            return
            
        msg = "🎯 *Posiciones Abiertas*\n\n"
        for sym, directions in open_pos.items():
            for d_name, d_info in directions.items():
                entry = d_info.get("entry_price", 0)
                size = d_info.get("size_usd", 0)
                candles = d_info.get("candles_held", 0)
                
                icono = "🟢" if d_name == "LONG" else "🔴"
                msg += (
                    f"{icono} *{sym}* ({d_name})\n"
                    f"   Entrada: `${entry:,.4f}`\n"
                    f"   Tamaño: `${size:,.2f}`\n"
                    f"   Velas Sostenida: `{candles}`\n\n"
                )
    else:
        msg = f"⚠️ *Error al obtener las posiciones:*\n{data.get('message', 'Desconocido')}"
        
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- BUCLE PRINCIPAL ---
def main():
    if not TELEGRAM_BOT_API:
        logger.error("No se encontró TELEGRAM_BOT_API en el archivo .env")
        return
        
    app = ApplicationBuilder().token(TELEGRAM_BOT_API).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("posiciones", posiciones))

    logger.info("🤖 Bot de Telegram iniciado y escuchando comandos...")
    app.run_polling()

if __name__ == '__main__':
    main()
