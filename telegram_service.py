import os
import json
import logging
import asyncio
from datetime import datetime, timezone
import aiohttp
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# --- CONFIGURACION ---
load_dotenv(override=True)
TELEGRAM_BOT_API = os.getenv("TELEGRAM_BOT_API", "")
TELEGRAM_ID = os.getenv("TELEGRAM_ID", "")
API_URL = "http://127.0.0.1:8000"
BOT_LEVERAGE = os.getenv("BOT_LEVERAGE", "3")  # etiqueta informativa en /portafolio
DAILY_BASELINE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "telegram_daily_baseline.json")

# --- MONITOR DE POSICIONES ---
POSITIONS_POLL_SECONDS = 30
_last_positions = {}
_positions_initialized = False

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
def _authorized_ids() -> list:
    """Retorna lista de chat_ids autorizados desde TELEGRAM_ID (separados por coma)."""
    if not TELEGRAM_ID:
        return []
    return [tid.strip() for tid in TELEGRAM_ID.split(",") if tid.strip()]

def is_authorized(update: Update) -> bool:
    chat_id = str(update.effective_chat.id)
    allowed = _authorized_ids()

    if not allowed:
        logger.error("TELEGRAM_ID no está configurado en .env")
        return False

    if chat_id not in allowed:
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

async def fetch_api_post(endpoint: str, payload: dict):
    try:
        async with aiohttp.ClientSession(timeout=API_TIMEOUT) as session:
            async with session.post(f"{API_URL}{endpoint}", json=payload) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return {"status": "error", "message": f"HTTP Error {response.status}"}
    except Exception as e:
        logger.error(f"Error conectando a la API local (POST): {e}")
        return {"status": "error", "message": f"No se pudo conectar a la API local: {e}"}

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

async def watch_positions_loop(app):
    """Cada 30s consulta /status y notifica cuando aparecen/desaparecen posiciones."""
    global _last_positions, _positions_initialized

    logger.info("📡 Monitor de posiciones iniciado: chequeando cada %ds", POSITIONS_POLL_SECONDS)
    await asyncio.sleep(5)

    while True:
        await asyncio.sleep(POSITIONS_POLL_SECONDS)
        data = await fetch_api("/status")

        if data.get("status") != "success":
            continue

        bot_data = data.get("data", {})
        current_raw = bot_data.get("open_positions", {})
        current_positions = {}
        for sym, directions in current_raw.items():
            for side, info in directions.items():
                if side not in ("LONG", "SHORT"):
                    continue
                current_positions[f"{sym}_{side}"] = {
                    "entry_price": info.get("entry_price", 0),
                    "last_mark_price": info.get("mark_price", info.get("entry_price", 0)),
                    "size_usd": info.get("size_usd", 0),
                    "unrealized_pnl": info.get("unrealized_pnl", 0),
                }

        if not _positions_initialized:
            _last_positions = current_positions
            _positions_initialized = True
            logger.info("Monitor: estado inicial guardado (%d posiciones)", len(current_positions))
            continue

        current_keys = set(current_positions.keys())
        last_keys = set(_last_positions.keys())

        opened_keys = current_keys - last_keys
        closed_keys = last_keys - current_keys

        messages = []

        for key in sorted(opened_keys):
            info = current_positions[key]
            sym, side = key.rsplit("_", 1)
            icon = "🟢" if side == "LONG" else "🔴"
            entry = info["entry_price"]
            size = info["size_usd"]
            messages.append(
                f"{icon} <b>ABRIÓ {side}</b> en {sym}\n"
                f"   Entrada: <code>${entry:,.4f}</code>\n"
                f"   Tamaño: <code>${size:,.2f}</code>"
            )

        for key in sorted(closed_keys):
            info = _last_positions.get(key, {})
            sym, side = key.rsplit("_", 1)
            icon = "🟢" if side == "LONG" else "🔴"
            entry = info.get("entry_price", 0)
            exit_price = info.get("last_mark_price", entry)
            pnl_pct = ((exit_price / entry) - 1.0) * 100 if entry > 0 else 0.0
            if side == "SHORT":
                pnl_pct = -pnl_pct
            pnl_icon = "📈" if pnl_pct >= 0 else "📉"
            messages.append(
                f"{icon} <b>CERRÓ {side}</b> en {sym}\n"
                f"   Entrada: <code>${entry:,.4f}</code>\n"
                f"   PnL: {pnl_icon} <b>{pnl_pct:+.2f}%</b>"
            )

        if messages:
            combined = "\n\n".join(messages)
            try:
                await app.bot.send_message(
                    chat_id=TELEGRAM_ID,
                    text=f"📊 <b>Movimiento de Posiciones</b>\n\n{combined}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Monitor: error enviando notificación: {e}")

        _last_positions = current_positions


async def post_init(app):
    app.create_task(watchdog_loop(app))
    app.create_task(watch_positions_loop(app))
    await app.bot.set_my_commands([
        ("resumen", "Resumen rápido: PnL del día y órdenes abiertas"),
        ("start", "Inicia el bot y verifica seguridad"),
        ("status", "Salud del sistema y microservicios"),
        ("portafolio", "Resumen financiero, balance y patrimonio"),
        ("posiciones", "Mesa de operaciones abiertas en vivo"),
        ("grid", "Estado y niveles de la grilla DGT"),
        ("orders", "Resumen de órdenes límite activas"),
        ("metrics", "Rendimiento histórico (Win Rate, PnL)"),
        ("help", "Guía y menú de comandos")
    ])

def _get_daily_baseline(current_equity: float) -> float:
    """Patrimonio de referencia al inicio del dia (UTC). Si cambio el dia, se reinicia
    al patrimonio actual (el PnL del dia arranca en 0 para el nuevo dia)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        if os.path.exists(DAILY_BASELINE_FILE):
            with open(DAILY_BASELINE_FILE, "r") as f:
                data = json.load(f)
            if data.get("date") == today:
                return data.get("equity", current_equity)
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(DAILY_BASELINE_FILE), exist_ok=True)
        with open(DAILY_BASELINE_FILE, "w") as f:
            json.dump({"date": today, "equity": current_equity}, f)
    except Exception:
        pass
    return current_equity

# --- COMANDOS DEL BOT ---
async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    await update.message.reply_chat_action(action="typing")
    status_data = await fetch_api("/status")
    orders_data = await fetch_api("/orders")

    if status_data.get("status") != "success":
        await update.message.reply_text(
            f"⚠️ <b>Error al consultar resumen:</b>\n{status_data.get('message', 'Desconocido')}",
            parse_mode="HTML")
        return

    bot_data = status_data["data"]
    balance = bot_data.get("balance", 0.0)
    open_pos = bot_data.get("open_positions", {})
    total_upnl = sum(
        d_info.get("unrealized_pnl", 0.0)
        for directions in open_pos.values()
        for d_name, d_info in directions.items() if d_name in ["LONG", "SHORT"]
    )
    equity = balance + total_upnl
    baseline = _get_daily_baseline(equity)
    day_pnl = equity - baseline
    day_pnl_pct = (day_pnl / baseline * 100) if baseline > 0 else 0.0
    pnl_icon = "📈" if day_pnl >= 0 else "📉"

    orders_by_symbol = {}
    if orders_data.get("status") == "success":
        for o in orders_data.get("orders", []):
            sym = o["symbol"]
            orders_by_symbol[sym] = orders_by_symbol.get(sym, 0) + 1
    orders_txt = "\n".join(f"  • <b>{s}</b>: {n}" for s, n in sorted(orders_by_symbol.items())) \
        or "  • Sin órdenes abiertas"

    msg = (
        "📌 <b>Resumen del Día</b>\n\n"
        f"{pnl_icon} PnL hoy: <b>{day_pnl_pct:+.2f}%</b> (<code>${day_pnl:+,.2f}</code>)\n"
        f"💰 Patrimonio: <b>${equity:,.2f}</b>\n\n"
        f"📋 Órdenes abiertas:\n{orders_txt}"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    welcome_msg = (
        "🤖 <b>Cripto Trading Assist v2.0</b>\n"
        "⚡ <i>Asistente Cuantitativo de Monitoreo en Tiempo Real</i>\n\n"
        "<b>Comandos Especializados:</b>\n"
        "📌 /resumen — PnL del día y órdenes abiertas (rápido)\n"
        "🟢 /status — Salud de servicios y seguridad\n"
        "💰 /portafolio — Balance, margen libre y patrimonio\n"
        "🎯 /posiciones — Operaciones abiertas en vivo\n"
        "🧩 /grid — Monitoreo de niveles DGT por par\n"
        "📋 /orders — Resumen de órdenes límite activas\n"
        "📊 /metrics — Win Rate y PnL realizado histórico\n"
        "ℹ️ /help — Guía rápida de uso"
    )
    await update.message.reply_text(welcome_msg, parse_mode="HTML")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    help_msg = (
        "ℹ️ <b>Sitemap de Comandos Especializados</b>\n\n"
        "📌 <b>/resumen</b>\n"
        "Vistazo rapido: PnL del dia (% y $) y cantidad de ordenes abiertas por simbolo. Pensado para consultar en segundos, sin el detalle de /portafolio.\n\n"
        "🟢 <b>/status</b>\n"
        "Monitoreo operativo: estado de microservicios (API, Telegram, Bot), tiempo de actividad y nivel de riesgo configurado.\n\n"
        "💰 <b>/portafolio</b>\n"
        "Monitoreo financiero: balance en billetera, patrimonio estimado (equity), margen libre disponible y PnL flotante global.\n\n"
        "🎯 <b>/posiciones</b>\n"
        "Mesa de trading: precio de entrada, precio marca actual, valor nocional y PnL ($ y ROI %) por cada orden abierta con botón de cierre interactivo.\n\n"
        "🧩 <b>/grid</b>\n"
        "Monitoreo DGT: estado detallado de la grilla dinámica, órdenes activas, compras ejecutadas y margen por moneda.\n\n"
        "📋 <b>/orders</b>\n"
        "Resumen agrupado de órdenes límite de compra en grilla y ventas Take-Profit en Binance.\n\n"
        "📊 <b>/metrics</b>\n"
        "Estadísticas de cierres pasados: Win Rate %, PnL neto realizado y Profit Factor."
    )
    await update.message.reply_text(help_msg, parse_mode="HTML")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    await update.message.reply_chat_action(action="typing")
    data = await fetch_api("/status")

    if data.get("status") == "success":
        bot_data = data["data"]
        bot_state = bot_data.get("status", "Desconocido")
        last_update = bot_data.get("timestamp", "Nunca")
        stale = bot_data.get("stale", False)
        open_pos = bot_data.get("open_positions", {})
        open_pos_count = sum(1 for sym, dirs in open_pos.items() for d in dirs.keys() if d in ["LONG", "SHORT"])

        dgt = bot_data.get("dgt", {})
        params = dgt.get("params", {})
        lev = params.get("leverage", BOT_LEVERAGE)
        sp = params.get("spacing", 1.0)
        lvls = params.get("levels", 3)
        sl = params.get("stop_loss", 3.0)

        sys_status_icon = "🟢" if bot_state == "running" and not stale else "🔴"
        stale_warning = "\n⚠️ <i>Datos de estado desactualizados (stale)</i>" if stale else ""

        msg = (
            "🛡️ <b>Salud del Sistema & Operativa</b>\n\n"
            f"{sys_status_icon} <b>Estado Core:</b> <code>{bot_state.upper()}</code>\n"
            f"🔌 <b>Microservicios:</b> FastAPI <code>OK</code> | Telegram <code>OK</code> | DGT <code>OK</code>\n"
            f"⚡ <b>Riesgo Activo:</b> Apalancamiento <code>{lev}x</code> | Stop-Loss <code>{sl}%</code> (Aislado)\n"
            f"🧩 <b>Configuración DGT:</b> <code>sp={sp}</code> | <code>levels={lvls}</code>\n"
            f"📈 <b>Operaciones Abiertas:</b> <code>{open_pos_count}</code> en mercado\n"
            f"⏱ <b>Último Latido:</b> <code>{last_update} UTC</code>"
            f"{stale_warning}"
        )
    else:
        msg = f"⚠️ <b>Error al conectar con la API:</b>\n{data.get('message', 'Desconocido')}"

    await update.message.reply_text(msg, parse_mode="HTML")

async def portafolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    await update.message.reply_chat_action(action="typing")
    data = await fetch_api("/status")

    if data.get("status") == "success":
        bot_data = data["data"]
        balance = bot_data.get("balance", 0.0)
        free_balance = bot_data.get("free_balance", 0.0)
        open_pos = bot_data.get("open_positions", {})
        dgt = bot_data.get("dgt", {})
        active_lev = dgt.get("params", {}).get("leverage", BOT_LEVERAGE)

        total_pnl = 0.0
        details = ""

        for sym, directions in open_pos.items():
            for d_name, d_info in directions.items():
                if d_name not in ["LONG", "SHORT"]: continue
                size = d_info.get("size_usd", 0)
                pnl = d_info.get("unrealized_pnl", 0.0)
                total_pnl += pnl
                pnl_pct = (pnl / size * 100) if size > 0 else 0.0
                pnl_icon = "🟢" if pnl >= 0 else "🔴"
                details += f"  {pnl_icon} <b>{sym}</b> ({d_name}): <b>${pnl:,.2f}</b> (<code>{pnl_pct:+.2f}%</code>)\n"

        if not details:
            details = "  ✅ <i>Cero flotante (100% libre)</i>\n"

        equity = balance + total_pnl
        used_margin = balance - free_balance
        pnl_icon = "📈" if total_pnl >= 0 else "📉"

        msg = (
            "💰 <b>Resumen Financiero & Balance</b>\n\n"
            f"💵 <b>Balance Total Billetera:</b> <code>${balance:,.2f}</code> USDT\n"
            f"🔓 <b>Margen Libre Disponible:</b> <code>${free_balance:,.2f}</code> USDT\n"
            f"🔒 <b>Margen Ocupado en Garantía:</b> <code>${used_margin:,.2f}</code> USDT\n"
            f"💎 <b>Patrimonio Estimado (Equity):</b> <code>${equity:,.2f}</code> USDT\n"
            f"⚖️ <b>PnL Flotante Total:</b> {pnl_icon} <b>${total_pnl:,.2f}</b> USDT\n\n"
            f"📊 <b>Desglose por Moneda ({active_lev}x):</b>\n"
            f"{details}"
        )
    else:
        msg = f"⚠️ <b>Error al consultar portafolio:</b>\n{data.get('message', 'Desconocido')}"

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

        has_active = False
        for sym, directions in open_pos.items():
            for d_name, d_info in directions.items():
                if d_name not in ["LONG", "SHORT"]: continue
                has_active = True
                entry = d_info.get("entry_price", 0)
                mark = d_info.get("mark_price", entry)
                size = d_info.get("size_usd", 0)
                pnl = d_info.get("unrealized_pnl", 0.0)
                pnl_pct = (pnl / size * 100) if size > 0 else 0.0
                side_icon = "🟢" if d_name == "LONG" else "🔴"
                pnl_icon = "📈" if pnl >= 0 else "📉"

                pos_msg = (
                    f"{side_icon} <b>{sym}</b> [{d_name}]\n"
                    f"   Entrada: <code>${entry:,.2f}</code> | Marca: <code>${mark:,.2f}</code>\n"
                    f"   Nocional: <code>${size:,.2f} USD</code>\n"
                    f"   PnL Flotante: {pnl_icon} <b>${pnl:,.2f}</b> (<code>{pnl_pct:+.2f}%</code>)"
                )

                clean_sym = sym.replace('/', '')
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"❌ Cerrar Posición {sym}", callback_data=f"close_ask:{clean_sym}")]
                ])
                await update.message.reply_text(pos_msg, parse_mode="HTML", reply_markup=keyboard)

        if not has_active:
            await update.message.reply_text("✅ <b>Sin Posiciones Flotantes.</b> La mesa está 100% limpia.", parse_mode="HTML")
    else:
        msg = f"⚠️ <b>Error al consultar posiciones:</b>\n{data.get('message', 'Desconocido')}"
        await update.message.reply_text(msg, parse_mode="HTML")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = str(update.effective_chat.id)
    allowed = _authorized_ids()
    if allowed and chat_id not in allowed:
        await query.edit_message_text("⛔ No estás autorizado")
        return

    data = query.data
    if data.startswith("close_ask:"):
        clean_sym = data.split("close_ask:")[1]
        formatted_sym = clean_sym.replace("USDT", "/USDT")

        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Sí, Cerrar a Mercado", callback_data=f"close_exec:{clean_sym}"),
                InlineKeyboardButton("🚫 Cancelar", callback_data=f"close_cancel:{clean_sym}")
            ]
        ])
        await query.edit_message_text(
            f"⚠️ <b>¿Confirmas cerrar a mercado la posición en {formatted_sym}?</b>\n\n"
            f"<i>Se cancelarán las órdenes pendientes asociadas y se ejecutará la venta a mercado con reduceOnly=True.</i>",
            parse_mode="HTML",
            reply_markup=confirm_keyboard
        )
    elif data.startswith("close_exec:"):
        clean_sym = data.split("close_exec:")[1]
        formatted_sym = clean_sym.replace("USDT", "/USDT")

        await query.edit_message_text(f"⏳ <b>Ejecutando cierre a mercado de {formatted_sym}...</b>", parse_mode="HTML")

        res = await fetch_api_post("/close_position", {"symbol": formatted_sym})
        if res.get("status") == "success":
            await query.edit_message_text(
                f"✅ <b>Posición Cerrada Exitosamente</b>\n\n"
                f"Símbolo: <code>{formatted_sym}</code>\n"
                f"Detalle: {res.get('message')}\n"
                f"Precio de Cierre: <code>${res.get('close_price', 0):,.2f}</code>",
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text(
                f"❌ <b>Error al cerrar posición en {formatted_sym}:</b>\n{res.get('message')}",
                parse_mode="HTML"
            )
    elif data.startswith("close_cancel:"):
        clean_sym = data.split("close_cancel:")[1]
        formatted_sym = clean_sym.replace("USDT", "/USDT")
        await query.edit_message_text(f"ℹ️ <i>Cierre de posición en {formatted_sym} cancelado.</i>", parse_mode="HTML")

async def grid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    await update.message.reply_chat_action(action="typing")
    data = await fetch_api("/status")

    if data.get("status") == "success":
        bot_data = data["data"]
        dgt = bot_data.get("dgt", {})
        if not dgt or dgt.get("mode") != "dgt":
            await update.message.reply_text("ℹ️ El bot de grilla DGT no se encuentra activo.")
            return

        params = dgt.get("params", {})
        symbols_info = dgt.get("symbols", {})

        msg = (
            "🧩 <b>Monitoreo de Grilla Dinámica (DGT)</b>\n"
            f"⚙️ <b>Parámetros:</b> <code>{params.get('leverage', 20)}x</code> | "
            f"Cap Total: <code>${params.get('capital', 250):.0f} USDT</code> | "
            f"SL: <code>{params.get('stop_loss', 3)}%</code>\n\n"
        )

        for sym, sinfo in symbols_info.items():
            orders_cnt = sinfo.get("grid_orders_active", 0)
            fills_cnt = sinfo.get("buys_filled_count", 0)
            eq_sym = sinfo.get("equity_per_symbol", 83.33)
            lvls = sinfo.get("levels", [])
            center_price = lvls[len(lvls)//2] if lvls else 0.0

            msg += (
                f"🔹 <b>{sym}</b>\n"
                f"   Cap Asignado: <code>${eq_sym:.2f} USD</code>\n"
                f"   Órdenes Activas: <code>{orders_cnt}</code> | Fills Acumulados: <code>{fills_cnt}</code>\n"
                f"   Precio Centro Grilla: <code>${center_price:,.2f}</code>\n\n"
            )
    else:
        msg = f"⚠️ <b>Error al consultar estado DGT:</b>\n{data.get('message', 'Desconocido')}"

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
            await update.message.reply_text("📭 No hay órdenes límite activas en Binance.")
            return

        grouped = {}
        for o in orders_list:
            key = (o["symbol"], o["side"])
            grouped.setdefault(key, []).append(o)

        msg = f"📋 <b>Resumen de Órdenes Límite Activas ({data['count']} Total)</b>\n\n"
        for (sym, side), o_group in grouped.items():
            icon = "🟢" if side == "buy" else "🔴"
            side_txt = "COMPRA (Grilla)" if side == "buy" else "VENTA (Take-Profit)"
            total_amt = sum(o["amount"] for o in o_group)
            prices = [o["price"] for o in o_group]
            min_p, max_p = min(prices), max(prices)
            price_str = f"${min_p:,.2f}" if min_p == max_p else f"${min_p:,.2f} - ${max_p:,.2f}"

            msg += (
                f"{icon} <b>{sym}</b> — {len(o_group)} órdenes {side_txt}\n"
                f"   Rango: <code>{price_str}</code>\n"
                f"   Volumen: <code>{total_amt:,.4f}</code>\n\n"
            )
    else:
        msg = f"⚠️ <b>Error al obtener órdenes:</b>\n{data.get('message', 'Desconocido')}"

    await update.message.reply_text(msg, parse_mode="HTML")

async def metrics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ No estás autorizado")
        return

    await update.message.reply_chat_action(action="typing")
    data = await fetch_api("/metrics")

    if data.get("status") == "success":
        md = data.get("data", {})
        trades = md.get("trades", 0)
        net_pnl = md.get("net_pnl", 0.0)
        win_rate = md.get("win_rate", 0.0) * 100
        pf = md.get("profit_factor")
        pf_txt = f"{pf:.2f}" if pf is not None else "N/A"
        pnl_icon = "📈" if net_pnl >= 0 else "📉"

        msg = (
            "📊 <b>Rendimiento Histórico Realizado</b>\n\n"
            f"🔄 <b>Trades Cerrados:</b> <code>{trades}</code>\n"
            f"💰 <b>PnL Neto Realizado:</b> {pnl_icon} <code>${net_pnl:,.2f}</code> USDT\n"
            f"🎯 <b>Win Rate:</b> <code>{win_rate:.1f}%</code>\n"
            f"⚖️ <b>Profit Factor:</b> <code>{pf_txt}</code>"
        )
    else:
        msg = f"⚠️ <b>Error al consultar métricas:</b>\n{data.get('message', 'Desconocido')}"

    await update.message.reply_text(msg, parse_mode="HTML")

from telegram.error import NetworkError

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja de forma limpia los parpadeos transitorios de red de Telegram sin saturar el log."""
    if isinstance(context.error, NetworkError):
        logger.warning(f"Reconexión transitoria de red con Telegram: {context.error}")
    else:
        logger.error("Excepción no controlada en el bot de Telegram:", exc_info=context.error)

# --- BUCLE PRINCIPAL ---
def main():
    if not TELEGRAM_BOT_API:
        logger.error("No se encontró TELEGRAM_BOT_API en el archivo .env")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_API).post_init(post_init).build()
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("resumen", resumen))
    app.add_handler(CommandHandler("portafolio", portafolio))
    app.add_handler(CommandHandler("posiciones", posiciones))
    app.add_handler(CommandHandler("grid", grid))
    app.add_handler(CommandHandler("orders", orders))
    app.add_handler(CommandHandler("metrics", metrics))
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("🤖 Bot de Telegram iniciado y escuchando comandos...")
    app.run_polling()

if __name__ == '__main__':
    main()
