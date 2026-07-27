import os
import logging
import asyncio
from datetime import datetime, timezone
import aiohttp
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- CONFIGURACION ---
load_dotenv()
TELEGRAM_BOT_API = os.getenv("TELEGRAM_BOT_API", "")
TELEGRAM_ID = os.getenv("TELEGRAM_ID", "")
API_URL = "http://127.0.0.1:8000"
BOT_LEVERAGE = os.getenv("BOT_LEVERAGE", "3")  # etiqueta informativa en /portafolio

# --- WATCHDOG ---
WATCHDOG_INTERVAL_SECONDS = 60      # chequeo cada 60s
WATCHDOG_MAX_FAILURES = 3           # 3 chequeos consecutivos sin API -> alarma
WATCHDOG_STALE_SECONDS = 300        # estado sin actualizarse > 5 min -> trading-core caído
API_TIMEOUT = aiohttp.ClientTimeout(total=10)  # timeout total de 10s para la API local

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
        async with aiohttp.ClientSession(timeout=API_TIMEOUT) as session:
            async with session.get(f"{API_URL}{endpoint}") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return {"status": "error", "message": f"HTTP Error {response.status}"}
    except Exception as e:
        logger.error(f"Error conectando a la API local: {e}")
        return {"status": "error", "message": "No se pudo conectar a la API local. ¿Está uvicorn corriendo?"}

# --- WATCHDOG DEL TRADING-CORE ---
async def _state_age_seconds(bot_data: dict):
    """Devuelve la antigüedad en segundos del timestamp del estado (UTC), o None si no se puede calcular."""
    ts = bot_data.get("timestamp")
    if not ts:
        return None
    try:
        parsed = datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()

async def watchdog_loop(app):
    """
    Cada 60s consulta /status y alerta al TELEGRAM_ID autorizado cuando:
      (a) la API no responde en 3 chequeos consecutivos, o
      (b) el timestamp del estado lleva más de 5 minutos sin actualizarse.
    Envía UNA alerta al entrar en alarma y UN mensaje de recuperación al volver
    a la normalidad (sin spam).
    """
    consecutive_failures = 0
    alarm_active = False
    alarm_reason = ""

    logger.info("🩺 Watchdog iniciado: chequeando /status cada %ds", WATCHDOG_INTERVAL_SECONDS)

    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)

        data = await fetch_api("/status")
        current_reason = None

        if data.get("status") == "success":
            # La API responde: resetear fallos de conexión
            consecutive_failures = 0
            age = await _state_age_seconds(data.get("data", {}))
            if age is None:
                current_reason = "la API responde pero el estado no tiene timestamp válido"
            elif age > WATCHDOG_STALE_SECONDS:
                current_reason = (
                    f"el estado del trading-core lleva {int(age)}s sin actualizarse "
                    f"(umbral: {WATCHDOG_STALE_SECONDS}s). ¿Trading-core caído?"
                )
        else:
            consecutive_failures += 1
            logger.warning(f"Watchdog: API no disponible ({consecutive_failures}/{WATCHDOG_MAX_FAILURES})")
            if consecutive_failures >= WATCHDOG_MAX_FAILURES:
                current_reason = (
                    f"la API local no responde tras {consecutive_failures} chequeos consecutivos. "
                    f"¿api-server caído?"
                )

        if current_reason and not alarm_active:
            # Entrar en estado de alarma: una sola alerta
            alarm_active = True
            alarm_reason = current_reason
            logger.error(f"Watchdog ALARMA: {current_reason}")
            try:
                await app.bot.send_message(
                    chat_id=TELEGRAM_ID,
                    text=(
                        "🚨 <b>ALERTA WATCHDOG</b>\n\n"
                        f"Problema detectado: {current_reason}\n\n"
                        "Revisa los procesos de PM2 (<code>pm2 status</code>)."
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Watchdog: no se pudo enviar la alerta de Telegram: {e}")
        elif not current_reason and alarm_active:
            # Vuelta a la normalidad: un solo mensaje de recuperación
            alarm_active = False
            logger.info(f"Watchdog RECUPERADO (la alarma anterior era: {alarm_reason})")
            try:
                await app.bot.send_message(
                    chat_id=TELEGRAM_ID,
                    text=(
                        "✅ <b>RECUPERADO</b>\n\n"
                        f"El sistema volvió a la normalidad. La alarma anterior era: {alarm_reason}"
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Watchdog: no se pudo enviar el mensaje de recuperación: {e}")
            alarm_reason = ""

async def post_init(app):
    # UNA SOLA post_init: antes existian dos definiciones y la segunda
    # (set_my_commands) tapaba a esta, dejando el watchdog sin arrancar.
    # 1) Lanzar el watchdog en segundo plano cuando arranca la aplicación.
    app.create_task(watchdog_loop(app))
    # 2) Registrar los comandos visibles en el menú de Telegram.
    await app.bot.set_my_commands([
        ("start", "Inicia el bot y verifica seguridad"),
        ("status", "Muestra el estado general del bot"),
        ("posiciones", "Muestra las posiciones abiertas actuales"),
        ("portafolio", "Muestra el balance y pnl flotante"),
        ("orders", "Muestra las órdenes limit abiertas")
    ])

# --- COMANDOS DEL BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    welcome_msg = (
        "🤖 <b>Cripto Trading Bot</b>\n\n"
        "¡Hola! Soy tu bot asistente. A partir de ahora solo responderé a tus comandos.\n\n"
        "Comandos disponibles:\n"
        "🔹 /status - Resumen del balance y estado del sistema\n"
        "🔹 /posiciones - Detalles de las operaciones abiertas\n"
        "🔹 /portafolio - Balance, margen libre y PnL flotante"
    )
    await update.message.reply_text(welcome_msg, parse_mode="HTML")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    await update.message.reply_chat_action(action="typing")
    data = await fetch_api("/status")

    if data.get("status") == "success":
        bot_data = data["data"]
        balance = bot_data.get("balance", 0.0)
        bot_state = bot_data.get("status", "Desconocido")
        last_update = bot_data.get("timestamp", "Nunca")
        open_pos = bot_data.get("open_positions", {})
        stale = bot_data.get("stale", False)

        # Count actual active positions, not just symbols in dict
        open_pos_count = sum(1 for sym, dirs in open_pos.items() for d in dirs.keys() if d in ["LONG", "SHORT"])

        stale_warning = "\n⚠️ <b>Datos posiblemente desactualizados (stale)</b>" if stale else ""

        msg = (
            "📊 <b>Estado del Bot</b>\n"
            f"💰 <b>Balance Billetera (Total):</b> <code>${balance:,.2f}</code> USDT\n"
            f"🔄 <b>Estado:</b> <code>{bot_state}</code>\n"
            f"📈 <b>Operaciones Abiertas:</b> <code>{open_pos_count}</code>\n"
            f"⏱ <b>Última Actualización:</b> <code>{last_update}</code>"
            f"{stale_warning}"
        )
    else:
        msg = f"⚠️ <b>Error al obtener el estado:</b>\n{data.get('message', 'Desconocido')}"

    await update.message.reply_text(msg, parse_mode="HTML")

async def posiciones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    await update.message.reply_chat_action(action="typing")
    data = await fetch_api("/status")

    if data.get("status") == "success":
        bot_data = data["data"]
        open_pos = bot_data.get("open_positions", {})

        if not open_pos:
            await update.message.reply_text("✅ No hay posiciones abiertas actualmente.")
            return

        msg = "🎯 <b>Posiciones Abiertas</b>\n\n"
        for sym, directions in open_pos.items():
            for d_name, d_info in directions.items():
                entry = d_info.get("entry_price", 0)
                size = d_info.get("size_usd", 0)
                candles = d_info.get("candles_held", 0)

                icono = "🟢" if d_name == "LONG" else "🔴"
                msg += (
                    f"{icono} <b>{sym}</b> ({d_name})\n"
                    f"   Entrada: <code>${entry:,.4f}</code>\n"
                    f"   Tamaño: <code>${size:,.2f}</code>\n"
                    f"   Velas Sostenida: <code>{candles}</code>\n\n"
                )
    else:
        msg = f"⚠️ <b>Error al obtener las posiciones:</b>\n{data.get('message', 'Desconocido')}"

    await update.message.reply_text(msg, parse_mode="HTML")

async def portafolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    await update.message.reply_chat_action(action="typing")
    data = await fetch_api("/status")

    if data.get("status") == "success":
        bot_data = data["data"]
        balance_total = bot_data.get("balance", 0.0)
        free_balance = bot_data.get("free_balance", 0.0)
        open_pos = bot_data.get("open_positions", {})

        global_pnl = 0.0
        details = ""

        for sym, directions in open_pos.items():
            for d_name, d_info in directions.items():
                if d_name not in ["LONG", "SHORT"]: continue

                entry = d_info.get("entry_price", 0)
                current = d_info.get("current_price", entry)
                size = d_info.get("size_usd", 0)
                pnl = d_info.get("unrealized_pnl", 0.0)
                global_pnl += pnl

                icono = "🟢" if d_name == "LONG" else "🔴"
                pnl_icon = "📈" if pnl >= 0 else "📉"

                pnl_pct = (pnl / size * 100) if size else 0.0

                details += (
                    f"{icono} <b>{sym}</b> ({d_name})\n"
                    f"   Tamaño Apalancado ({BOT_LEVERAGE}x): <code>${size:,.2f}</code>\n"
                    f"   Entrada: <code>${entry:,.4f}</code>\n"
                    f"   Actual: <code>${current:,.4f}</code>\n"
                    f"   PnL: {pnl_icon} <b>${pnl:,.2f}</b> (<code>{pnl_pct:+.2f}%</code>)\n\n"
                )

        if details == "":
            details = "✅ No hay posiciones activas.\n"

        realized_line = ""
        metrics = await fetch_api("/metrics")
        if metrics.get("status") == "success":
            md = metrics.get("data") or {}
            if md.get("trades"):
                pf = md.get("profit_factor")
                pf_txt = f"{pf:.2f}" if pf is not None else "∞"
                realized_line = (
                    f"📒 <b>Realizado (últimos {md['trades']} cierres):</b> "
                    f"<code>${md.get('net_pnl', 0.0):,.2f}</code> | WR <code>{md.get('win_rate', 0.0) * 100:.0f}%</code> | PF <code>{pf_txt}</code>\n"
                )

        msg = (
            "💼 <b>Portafolio Actual</b>\n"
            f"💰 <b>Balance Billetera:</b> <code>${balance_total:,.2f}</code> USDT\n"
            f"🔓 <b>Margen Libre:</b> <code>${free_balance:,.2f}</code> USDT\n"
            f"⚖️ <b>PnL Flotante Total:</b> <b>${global_pnl:,.2f}</b> USDT\n"
            f"{realized_line}\n"
            f"📊 <b>Distribución de Activos:</b>\n"
            f"{details}"
        )
    else:
        msg = f"⚠️ <b>Error al obtener el portafolio:</b>\n{data.get('message', 'Desconocido')}"

    await update.message.reply_text(msg, parse_mode="HTML")

async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    await update.message.reply_chat_action(action="typing")
    data = await fetch_api("/orders")

    if data.get("status") == "success":
        orders_list = data.get("orders", [])
        if not orders_list:
            await update.message.reply_text("📭 No hay órdenes limit abiertas.")
            return

        msg = "📋 <b>Órdenes Limit Abiertas</b>\n\n"
        for o in orders_list:
            icon = "🟢" if o["side"] == "buy" else "🔴"
            remaining = o["remaining"]
            filled = o["filled"]
            total = o["amount"]
            pct = f"({filled/total*100:.0f}% llenada)" if total > 0 else ""
            msg += (
                f"{icon} <b>{o['symbol']}</b> {o['side'].upper()} {o['type']}\n"
                f"   Precio: <code>${o['price']:.4f}</code>\n"
                f"   Cant: <code>{remaining:.4f}</code> / <code>{total:.4f}</code> {pct}\n"
            )

        msg += f"\nTotal: <code>{data['count']}</code> órdenes"
    else:
        msg = f"⚠️ <b>Error al obtener órdenes:</b>\n{data.get('message', 'Desconocido')}"

    await update.message.reply_text(msg, parse_mode="HTML")

# --- BUCLE PRINCIPAL ---
def main():
    if not TELEGRAM_BOT_API:
        logger.error("No se encontró TELEGRAM_BOT_API en el archivo .env")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_API).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("posiciones", posiciones))
    app.add_handler(CommandHandler("portafolio", portafolio))
    app.add_handler(CommandHandler("orders", orders))

    logger.info("🤖 Bot de Telegram iniciado y escuchando comandos...")
    app.run_polling()

if __name__ == '__main__':
    main()
