"""
Portfolio WFO Live Bot.
Replica en vivo el motor de scripts/backtest_20d_realworld.py: grid bidireccional
(LONG + SHORT) basado en ATR, con reoptimizacion diaria via Optuna sobre una
ventana de entrenamiento propia por simbolo (la que mejor rindio en el barrido
inicial de validacion). Conecta a Binance Futures Testnet/Demo.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import time
import signal
import logging
import sqlite3
import json
import re
import urllib.parse
import urllib.request
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv(override=True)

class SafeRotatingFileHandler(RotatingFileHandler):
    def emit(self, record):
        try:
            super().emit(record)
        except Exception:
            pass

    def handleError(self, record):
        pass

LOG = logging.getLogger('portfolio_wfo_bot')
LOG.setLevel(logging.INFO)
_handler = SafeRotatingFileHandler('portfolio_wfo_bot.log', maxBytes=150*1024, backupCount=4, delay=True)
_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
LOG.addHandler(_handler)
LOG.addHandler(logging.StreamHandler())

import ccxt
import pandas as pd
import optuna

optuna.logging.set_verbosity(optuna.logging.WARNING)

from scripts.backtest_20d_realworld import prepare_data, run_realworld_backtest, fetch_data

# --- Ventanas de entrenamiento por simbolo: las mejores encontradas en el barrido
# inicial (2,3,5,7,10,14,20,25,30,40 dias) sobre backtest_20d_realworld.py ---
TRAIN_DAYS_MAP = {
    'ETH/USDT': 25,  # verificado 2026-08-21: ya era el mejor de [15,20,25,30,40], no se toca
    'SOL/USDT': 25,  # bajado de 30 el 2026-08-21: margen y drawdown mas consistentes con 25d
    'LINK/USDT': 40,  # subido de 25 el 2026-08-21: margen mas parejo y drawdown mucho menor con 40d
    'BNB/USDT': 25,  # subido de 20 el 2026-08-21: margen negativo en ambos periodos con 20d,
                       # positivo con 25d (ver bnb_traindays_lab.py)
}
# BTC/USDT excluido el 2026-08-20: 5 ventanas de entrenamiento probadas (15-40d) con la config
# ganadora, ninguna dio margen sano sobre el equilibrio en el periodo reciente (drawdowns de
# -41% a -62% en todos los casos). No es un problema de calibracion, es regimen de mercado.
SYMBOLS = list(TRAIN_DAYS_MAP.keys())

CANDLES_PER_DAY = 96
TIMEFRAME = '15m'
LEVERAGE = int(os.getenv('DGT_LEVERAGE') or os.getenv('BOT_LEVERAGE') or '10')
TOTAL_CAPITAL = float(os.getenv('DGT_CAPITAL', '250'))
CAPITAL_PER_SYMBOL = TOTAL_CAPITAL  # cada simbolo se dimensiona como si tuviera su propio capital (igual que el backtest)
MAX_RISK = 0.08  # bajado de 0.20 el 2026-08-20: 14 dias de datos reales mostraron perdida neta de
                 # -$1521 (733 trades) con el tamano de posicion anterior -- se reduce el riesgo por
                 # operacion mientras MIN_RR demuestra su efecto con datos en vivo, para que ningun
                 # trade individual (ej. LINK -$136 el 19-ago) vuelva a golpear tan fuerte.
OPTUNA_TRIALS = 40
MIN_RR = 0.6  # ratio ganancia/riesgo minimo exigido en la optimizacion (grid_spacing*tp_mult/sl_mult).
              # Validado en laboratorio 2026-08-19: baja el acierto de equilibrio de ~70-80% a ~51-53%
              # sin sacrificar retorno total, y con menos operaciones (menos comision/exposicion a deslizamiento).
MIN_GRID_SPACING = 1.5  # piso del espaciado de grid (antes 0.5). Validado en 2 periodos independientes
              # de 30 dias (2026-08-20): entradas mas selectivas ganan en retorno, margen sobre el
              # equilibrio Y drawdown maximo en ambos periodos frente al piso anterior de 0.5.
COM = 0.0004
HARD_CAP_LIQUIDITY = 10000.0
IMMEDIATE_STOP_WINDOW_SEC = 5400  # 90 min: ventana para contar stops inmediatos
IMMEDIATE_STOP_MAX = 2            # a partir del 2do stop inmediato en la ventana -> veto
IMMEDIATE_STOP_PAUSE_HOURS = 3    # duracion del veto por tendencia adversa
CHURN_WINDOW_HOURS = 6         # ventana para medir sangria/churn por simbolo
CHURN_PAUSE_HOURS = 4          # cuanto dura el veto antes de reevaluar
CHURN_CHECK_INTERVAL_SEC = 1800  # cada cuanto se corre el chequeo (30 min)
CHURN_MIN_COMMISSION = 8.0     # piso de comision para considerar que hay churn real
CHURN_COMMISSION_RATIO = 1.5   # comision > 1.5x el resultado bruto -> el costo domina
CHURN_MAX_NET_LOSS_PCT = 0.01  # perdida neta > 1% del equity -> sangria
WEIGHT_MIN = 0.5  # piso: el simbolo mas debil nunca queda por debajo de la mitad del reparto parejo
WEIGHT_MAX = 2.0  # techo: el lider de momentum nunca supera el doble del reparto parejo
POLL_SECONDS = int(os.getenv('DGT_POLL', '15'))
REOPT_INTERVAL_SEC = 24 * 3600
TIME_EXIT_BAR_1 = 20
TIME_EXIT_BAR_2 = 40

_last_ip_alert_time = 0

def send_telegram_alert(message: str):
    token = os.getenv("TELEGRAM_BOT_API")
    chat_ids = [cid.strip() for cid in os.getenv("TELEGRAM_ID", "").split(",") if cid.strip()]
    if not token or not chat_ids:
        return
    for cid in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": cid,
                "text": message,
                "parse_mode": "HTML"
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            LOG.error(f"Error enviando alerta de Telegram: {e}")

def notify_ip_error(error_msg: str):
    global _last_ip_alert_time
    if time.time() - _last_ip_alert_time < 300:
        return
    _last_ip_alert_time = time.time()
    m = re.search(r"request ip:\s*([\d\.]+)", error_msg)
    if m:
        ip_match = m.group(1)
    else:
        try:
            ip_match = urllib.request.urlopen('https://api.ipify.org', timeout=3).read().decode('utf-8')
        except Exception:
            ip_match = "Desconocida"
    msg = (
        "🌐 <b>ALERTA BINANCE: IP RECHAZADA</b>\n\n"
        f"Binance bloqueo la conexion porque cambio tu direccion IP publica.\n\n"
        f"📍 <b>Nueva IP a agregar:</b> <code>{ip_match}</code>\n\n"
        f"<b>Solucion:</b> Copia la IP arriba e ingresala en Binance ➔ <i>API Management</i> ➔ <i>Edit Restrictions</i>."
    )
    send_telegram_alert(msg)

def _get_db_conn():
    db_path = os.path.abspath("data/trading_bot.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA busy_timeout=30000;')
    except Exception:
        pass
    return conn

def update_portfolio_state(status_text, balance, free_balance, open_positions, live_params):
    try:
        with _get_db_conn() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS portfolio_bot_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT,
                balance REAL,
                free_balance REAL,
                open_positions TEXT,
                live_params TEXT
            )''')
            pos_json = json.dumps(open_positions)
            params_json = json.dumps(live_params)
            row = conn.execute('SELECT 1 FROM portfolio_bot_state WHERE id = 1').fetchone()
            if row:
                conn.execute('''UPDATE portfolio_bot_state SET timestamp=CURRENT_TIMESTAMP,status=?,balance=?,
                               free_balance=?,open_positions=?,live_params=? WHERE id=1''',
                            (status_text, balance, free_balance, pos_json, params_json))
            else:
                conn.execute('''INSERT INTO portfolio_bot_state(id,status,balance,free_balance,open_positions,live_params)
                               VALUES(1,?,?,?,?,?)''',
                            (status_text, balance, free_balance, pos_json, params_json))
            conn.commit()
    except Exception as e:
        LOG.warning(f"DB update error: {e}")

def get_exchange():
    test_key = os.getenv('BINANCE_TESTNET_KEY')
    test_secret = os.getenv('BINANCE_TESTNET_SECRET')
    main_key = os.getenv('BINANCE_MAIN_KEY')
    main_secret = os.getenv('BINANCE_MAIN_SECRET')

    using_testnet = bool(test_key and test_secret)
    key = test_key if using_testnet else main_key
    secret = test_secret if using_testnet else main_secret

    if not key or not secret:
        LOG.error("No hay API keys en .env")
        sys.exit(1)

    if not using_testnet:
        LOG.error("BLOQUEADO: no hay claves testnet activas, y este bot solo debe correr contra testnet/demo.")
        sys.exit(1)

    ex = ccxt.binance({
        'apiKey': key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'},
    })
    ex.options['recvWindow'] = 30000
    ex.enable_demo_trading(True)
    LOG.info("Conectado a BINANCE DEMO TRADING (testnet)")
    return ex

def reoptimize_symbol(symbol):
    """Reoptimiza parametros para 'symbol' usando su propia ventana de entrenamiento,
    reutilizando el motor de backtest_20d_realworld.py tal cual fue validado.

    Ademas del ajuste en entrenamiento (best_value), calcula un PRONOSTICO FUERA DE MUESTRA:
    deja el ultimo dia fuera del entrenamiento y evalua ahi los parametros ganadores. Ese
    numero es mucho mas honesto que el de entrenamiento -- el de entrenamiento casi nunca
    sale mal porque es literalmente lo que Optuna acaba de optimizar, mientras que el fuera
    de muestra sirve como alerta temprana (en el analisis del 19-ago acerto la direccion en
    4 de 5 simbolos el dia previo a una racha perdedora)."""
    train_days = TRAIN_DAYS_MAP[symbol]
    limit = (train_days + 6) * CANDLES_PER_DAY
    df_raw = fetch_data(symbol, TIMEFRAME, limit=limit)
    df = prepare_data(df_raw)

    holdout_len = CANDLES_PER_DAY  # ultimo dia reservado para validacion fuera de muestra
    holdout_slice = df.iloc[-holdout_len:]
    train_source = df.iloc[:-holdout_len]
    train_slice = train_source.iloc[-(train_days * CANDLES_PER_DAY):]

    def objective(trial):
        gs_l = trial.suggest_float('grid_spacing_mult', MIN_GRID_SPACING, 3.0)
        sl_l = trial.suggest_float('sl_mult', 1.0, 4.0)
        tp_l_lo = max(0.5, MIN_RR * sl_l / gs_l)
        if tp_l_lo > 3.0:
            return -1000
        tp_l = trial.suggest_float('tp_mult', tp_l_lo, 3.0)

        gs_s = trial.suggest_float('grid_spacing_mult_s', MIN_GRID_SPACING, 3.0)
        sl_s = trial.suggest_float('sl_mult_s', 1.0, 4.0)
        tp_s_lo = max(0.5, MIN_RR * sl_s / gs_s)
        if tp_s_lo > 3.0:
            return -1000
        tp_s = trial.suggest_float('tp_mult_s', tp_s_lo, 3.0)

        params = {
            'grid_spacing_mult': gs_l,
            'tp_mult': tp_l,
            'sl_mult': sl_l,
            'grid_spacing_mult_s': gs_s,
            'tp_mult_s': tp_s,
            'sl_mult_s': sl_s,
            'risk_pct': trial.suggest_float('risk_pct', MAX_RISK * 0.5, MAX_RISK),
        }
        cap, _, t_count = run_realworld_backtest(train_slice, 0, len(train_slice), CAPITAL_PER_SYMBOL, params)
        if t_count < 3:
            return -1000
        return cap

    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=OPTUNA_TRIALS)

    # Pronostico fuera de muestra: los parametros ganadores aplicados al dia que NO se uso
    # para entrenar. Si sale muy negativo, es senal de alerta para ese simbolo hoy.
    try:
        oos_cap, _, oos_trades = run_realworld_backtest(
            holdout_slice, 0, len(holdout_slice), CAPITAL_PER_SYMBOL, study.best_params)
    except Exception as e:
        LOG.warning(f"[{symbol}] Error calculando pronostico fuera de muestra: {e}")
        oos_cap, oos_trades = CAPITAL_PER_SYMBOL, 0

    LOG.info(f"[{symbol}] Reoptimizado ({train_days}d train) -> entrenamiento=${study.best_value:.2f} | "
             f"pronostico fuera de muestra=${oos_cap:.2f} ({oos_trades} trades) | params={study.best_params}")
    return study.best_params, study.best_value, oos_cap

def _empty_side_state():
    return {
        'active': False,
        'entry_order_id': None,
        'entry_price': None,
        'pending_since': None,   # candle time en que se coloco la entrada pendiente
        'entry_time': None,      # candle time en que se lleno la entrada (posicion activa)
        'sl': None,
        'tp': None,
        'tp_order_id': None,
        'sl_order_id': None,
        'checked_time_exit_1': False,
    }

class PortfolioWFOBot:
    def __init__(self, exchange):
        self.ex = exchange
        self.leverage = LEVERAGE
        self.running = True
        self.params = {}
        self.state = {sym: {'long': _empty_side_state(), 'short': _empty_side_state()} for sym in SYMBOLS}
        self.last_reopt = 0
        self.entry_retry_cooldown = {}  # (symbol, side) -> timestamp hasta el cual no reintentar
        self.paused = set()  # simbolos sin edge validado en la ultima reoptimizacion
        self.capital_weights = {sym: 1.0 for sym in SYMBOLS}  # se recalcula por momentum
        self.churn_paused_until = {}  # symbol -> timestamp hasta el cual queda vetado por churn/sangria
        self.immediate_stops = {}     # symbol -> lista de timestamps de stops inmediatos recientes
        self.last_churn_check = 0
        # tope de notional por simbolo (dict) -- se recalcula en setup() segun capital real y peso
        self.max_notional_per_leg = {sym: HARD_CAP_LIQUIDITY for sym in SYMBOLS}

    def setup(self):
        for sym in SYMBOLS:
            try:
                self.ex.set_leverage(self.leverage, sym)
            except Exception as e:
                LOG.warning(f"[{sym}] Leverage: {e}")
        try:
            self.ex.set_position_mode(True)
            LOG.info("Hedge mode activado (LONG y SHORT simultaneos).")
        except Exception as e:
            LOG.warning(f"No se pudo forzar hedge mode (puede que ya este activo): {e}")

        self._compute_momentum_weights()
        self._recalc_notional_cap()
        self.reoptimize_all()
        self._reconcile_open_orders()

    def _reconcile_open_orders(self):
        """Al arrancar, reconecta el estado en memoria con lo que realmente existe en el
        exchange, para no dejar nada huerfano ni duplicar ordenes:
        (a) posiciones ya abiertas -> se marcan activas y se ADOPTA su TP/SL existente si
            ya lo tenian (evita el error -2022 ReduceOnly Order is rejected de intentar
            colocar un segundo TP/SL que reduciria mas cantidad de la que hay);
        (b) ordenes de entrada pendientes sin posicion -> se reconectan para seguir
            vigilandolas, en vez de quedar sin seguimiento hasta que alguien las notara."""
        for symbol in SYMBOLS:
            try:
                positions = self.ex.fetch_positions([symbol])
                open_orders = self.ex.fetch_open_orders(symbol)
                for side in ('long', 'short'):
                    st = self.state[symbol][side]
                    pos_amt = self._get_position_amt(positions, symbol, side)
                    position_side_tag = 'LONG' if side == 'long' else 'SHORT'

                    if pos_amt > 0:
                        entry_price = self._get_position_entry_price(positions, symbol, side)
                        st['active'] = True
                        st['entry_price'] = entry_price if entry_price > 0 else None
                        st['entry_time'] = pd.Timestamp.now().floor('15min')
                        st['checked_time_exit_1'] = False
                        close_order_side = 'sell' if side == 'long' else 'buy'
                        for o in open_orders:
                            o_pos_side = (o.get('info') or {}).get('positionSide')
                            if o_pos_side != position_side_tag or o.get('side') != close_order_side:
                                continue
                            if o.get('type') == 'limit' and st['tp_order_id'] is None:
                                st['tp_order_id'] = o['id']
                                st['tp'] = float(o.get('price') or 0)
                                LOG.info(f"[{symbol}] TP {side.upper()} existente adoptado (id {o['id']} @ {st['tp']})")
                            elif o.get('type') == 'STOP_MARKET' and st['sl_order_id'] is None:
                                st['sl_order_id'] = o['id']
                                st['sl'] = float(o.get('stopPrice') or 0)
                                LOG.info(f"[{symbol}] SL {side.upper()} existente adoptado (id {o['id']} @ {st['sl']})")
                        continue  # con posicion abierta no puede haber ademas entrada pendiente en el mismo lado

                    entry_order_side = 'buy' if side == 'long' else 'sell'
                    for o in open_orders:
                        o_pos_side = (o.get('info') or {}).get('positionSide')
                        if o_pos_side == position_side_tag and o.get('side') == entry_order_side and o.get('type') == 'limit':
                            st['entry_order_id'] = o['id']
                            st['entry_price'] = float(o.get('price') or 0)
                            ts = o.get('timestamp')
                            order_time = pd.to_datetime(ts, unit='ms') if ts else pd.Timestamp.now()
                            st['pending_since'] = order_time.floor('15min')
                            LOG.info(f"[{symbol}] Orden de entrada {side.upper()} pendiente reconectada "
                                     f"(id {o['id']} @ {st['entry_price']}, colocada {order_time})")
                            break
            except Exception as e:
                LOG.warning(f"[{symbol}] Error reconciliando ordenes/posiciones: {e}")

    def _compute_momentum_weights(self):
        """Pondera el capital de cada simbolo segun su momentum de 30 dias (vela diaria
        CERRADA, sin look-ahead), acotado entre WEIGHT_MIN y WEIGHT_MAX. Se renormaliza para
        que la suma total de pesos siga dando exactamente len(SYMBOLS) -- osea, se reparte el
        MISMO pool total de siempre, solo se inclina hacia el que viene con mas fuerza, sin
        arriesgar mas margen total del que ya teniamos calibrado como seguro."""
        scores = {}
        for sym in SYMBOLS:
            try:
                ohlcv = self.ex.fetch_ohlcv(sym, '1d', limit=35)
                df = pd.DataFrame(ohlcv, columns=['t', 'open', 'high', 'low', 'close', 'volume'])
                if len(df) < 32:
                    scores[sym] = 0.0
                    continue
                # -2 = ultima vela diaria cerrada (la -1 puede seguir formandose)
                scores[sym] = (df['close'].iloc[-2] / df['close'].iloc[-32] - 1) * 100
            except Exception as e:
                LOG.warning(f"[{sym}] Error calculando momentum: {e}")
                scores[sym] = 0.0

        n = len(SYMBOLS)
        min_score = min(scores.values())
        shifted = {s: v - min_score + 1.0 for s, v in scores.items()}  # todo positivo
        total = sum(shifted.values())
        raw_weights = {s: (v / total) * n for s, v in shifted.items()} if total > 0 else {s: 1.0 for s in SYMBOLS}
        clipped = {s: max(WEIGHT_MIN, min(WEIGHT_MAX, w)) for s, w in raw_weights.items()}
        clipped_total = sum(clipped.values())
        self.capital_weights = {s: (w / clipped_total) * n for s, w in clipped.items()}

        LOG.info("Pesos de capital por momentum: " +
                  ", ".join(f"{s}={self.capital_weights[s]:.2f}x(30d {scores[s]:+.1f}%)" for s in SYMBOLS))

    def _recalc_notional_cap(self):
        """Reparte el margen real disponible entre los 5 simbolos x 2 lados, inclinado segun
        capital_weights (en vez de un tope fijo de $10k que deja a los ultimos sin margen, o
        un reparto parejo que diluye al que tiene mejor momentum). La suma de pesos siempre da
        len(SYMBOLS), asi que el presupuesto total de margen usado en el peor caso no cambia."""
        try:
            bal = self.ex.fetch_balance()
            equity = bal['total'].get('USDT', CAPITAL_PER_SYMBOL)
            legs = len(SYMBOLS) * 2
            safety = 0.8
            base_cap = (equity * self.leverage * safety) / legs
            self.max_notional_per_leg = {
                sym: min(HARD_CAP_LIQUIDITY, base_cap * self.capital_weights.get(sym, 1.0))
                for sym in SYMBOLS
            }
            LOG.info("Topes de notional por simbolo: " +
                      ", ".join(f"{s}=${v:.2f}" for s, v in self.max_notional_per_leg.items()) +
                      f" (equity ${equity:.2f}, {self.leverage}x)")
        except Exception as e:
            LOG.warning(f"No se pudo recalcular el tope de notional, se mantienen los valores previos: {e}")
        self.health_check()

    def _check_symbol_health(self):
        """Veta temporalmente simbolos que estan sangrando, mirando el dinero REAL de la
        cuenta (no el backtest) en las ultimas CHURN_WINDOW_HOURS horas:

        (a) churn: la comision supera con creces a lo que el simbolo genero -> esta operando
            de mas y el costo se come el resultado (patron observado el 19-ago en BTC/SOL,
            con 43 y 32 operaciones y comision ~2x la perdida real);
        (b) sangria neta: la perdida neta del simbolo supera el 1% del equity de la cuenta.

        El veto dura CHURN_PAUSE_HOURS y luego se reevalua solo -- no es permanente."""
        now = time.time()
        if now - self.last_churn_check < CHURN_CHECK_INTERVAL_SEC:
            return
        self.last_churn_check = now

        try:
            bal = self.ex.fetch_balance()
            equity = bal['total'].get('USDT', CAPITAL_PER_SYMBOL)
        except Exception as e:
            LOG.warning(f"No se pudo obtener balance para chequeo de salud: {e}")
            return

        since_ms = int((now - CHURN_WINDOW_HOURS * 3600) * 1000)
        for sym in SYMBOLS:
            try:
                rows = self.ex.fapiPrivateGetIncome({
                    'symbol': sym.replace('/', ''), 'startTime': since_ms, 'limit': 1000})
                realized = sum(float(r['income']) for r in rows if r.get('incomeType') == 'REALIZED_PNL')
                commission = sum(float(r['income']) for r in rows if r.get('incomeType') == 'COMMISSION')
                n_trades = sum(1 for r in rows if r.get('incomeType') == 'REALIZED_PNL')
                net = realized + commission  # commission ya viene negativa

                churn = (abs(commission) > CHURN_MIN_COMMISSION
                         and abs(commission) > abs(realized) * CHURN_COMMISSION_RATIO
                         and net < 0)
                bleeding = net < -(equity * CHURN_MAX_NET_LOSS_PCT)

                if churn or bleeding:
                    motivo = "churn (comision > resultado)" if churn else "sangria neta sostenida"
                    self.churn_paused_until[sym] = now + CHURN_PAUSE_HOURS * 3600
                    LOG.warning(f"[{sym}] VETADO {CHURN_PAUSE_HOURS}h por {motivo}: "
                                f"{n_trades} trades, realizado=${realized:.2f}, comision=${commission:.2f}, "
                                f"neto=${net:.2f} en las ultimas {CHURN_WINDOW_HOURS}h")
                    send_telegram_alert(
                        f"\u26d4 <b>{sym} VETADO {CHURN_PAUSE_HOURS}h</b>\n{motivo}\n"
                        f"{n_trades} trades | realizado: <code>${realized:.2f}</code> | "
                        f"comision: <code>${commission:.2f}</code> | neto: <code>${net:.2f}</code>")
            except Exception as e:
                LOG.warning(f"[{sym}] Error en chequeo de salud: {e}")

    def _record_immediate_stop(self, symbol):
        """Registra un cierre por SL-ya-roto. Si se repiten en poco tiempo, es senal de que
        la tendencia esta atropellando sistematicamente las entradas de ese simbolo, asi que
        se lo veta unas horas en vez de seguir entrando y perdiendo en cada intento."""
        now = time.time()
        stamps = [t for t in self.immediate_stops.get(symbol, []) if now - t < IMMEDIATE_STOP_WINDOW_SEC]
        stamps.append(now)
        self.immediate_stops[symbol] = stamps
        if len(stamps) >= IMMEDIATE_STOP_MAX:
            self.churn_paused_until[symbol] = now + IMMEDIATE_STOP_PAUSE_HOURS * 3600
            self.immediate_stops[symbol] = []
            LOG.warning(f"[{symbol}] VETADO {IMMEDIATE_STOP_PAUSE_HOURS}h: {len(stamps)} stops inmediatos "
                        f"en {IMMEDIATE_STOP_WINDOW_SEC//60} min -- la tendencia esta atropellando las entradas.")
            send_telegram_alert(
                f"\u26d4 <b>{symbol} VETADO {IMMEDIATE_STOP_PAUSE_HOURS}h</b>\n"
                f"{len(stamps)} stops inmediatos seguidos: el mercado va en tendencia y la estrategia "
                f"(reversion a la media) esta entrando en contra.")

    def _is_vetoed(self, symbol):
        """True si el simbolo esta vetado por churn/sangria y el veto sigue vigente."""
        until = self.churn_paused_until.get(symbol, 0)
        if until and time.time() >= until:
            self.churn_paused_until.pop(symbol, None)
            LOG.info(f"[{symbol}] Veto por churn/sangria expirado -- vuelve a operar.")
            return False
        return bool(until)

    def reoptimize_all(self):
        self._compute_momentum_weights()
        self._recalc_notional_cap()
        min_ok = CAPITAL_PER_SYMBOL * 0.5
        # El pronostico fuera de muestra tiene su propio umbral: basta con que no pierda
        # de forma marcada (< -8% sobre el capital base) para vetar al simbolo ese dia.
        min_oos = CAPITAL_PER_SYMBOL * 0.92
        for sym in SYMBOLS:
            try:
                params, best_value, oos_value = reoptimize_symbol(sym)
                if best_value < min_ok:
                    self.paused.add(sym)
                    LOG.warning(f"[{sym}] PAUSADO: ni el mejor set de parametros valido en entrenamiento "
                                f"(${best_value:.2f} vs ${CAPITAL_PER_SYMBOL:.2f} inicial).")
                    send_telegram_alert(f"⏸️ <b>{sym} PAUSADO</b>\nReoptimizacion sin edge validado (${best_value:.2f}). No se abriran nuevas entradas.")
                elif oos_value < min_oos:
                    # Ajusta bien en entrenamiento pero pierde en el dia no visto -> sobreajuste.
                    self.paused.add(sym)
                    LOG.warning(f"[{sym}] PAUSADO por pronostico fuera de muestra (${oos_value:.2f} "
                                f"vs ${CAPITAL_PER_SYMBOL:.2f} base) -- ajusta en entrenamiento pero "
                                f"pierde fuera de muestra.")
                    send_telegram_alert(f"⏸️ <b>{sym} PAUSADO</b>\nPronostico fuera de muestra negativo (${oos_value:.2f}). No se abriran nuevas entradas hoy.")
                else:
                    self.paused.discard(sym)
                    self.params[sym] = params
            except Exception as e:
                LOG.error(f"[{sym}] Error reoptimizando: {e}")
        self.last_reopt = time.time()

    def health_check(self):
        try:
            bal = self.ex.fetch_balance()
            usdt = bal['total'].get('USDT', 0.0)
            free_usdt = bal['free'].get('USDT', 0.0)

            positions = self.ex.fetch_positions(SYMBOLS)
            open_pos_dict = {}
            for p in positions:
                contracts = float(p.get('contracts', 0) or 0)
                if contracts > 0:
                    sym = p.get('symbol')
                    side = p.get('side', '').upper()
                    open_pos_dict.setdefault(sym, {})[side] = {
                        "entry_price": float(p.get('entryPrice', 0) or 0),
                        "size_usd": abs(float(p.get('notional', 0) or 0)),
                        "unrealized_pnl": float(p.get('unrealizedPnl', 0) or 0),
                    }
            update_portfolio_state("running", usdt, free_usdt, open_pos_dict, self.params)
            pos_str = ', '.join(f"{s}:{list(v.keys())}" for s, v in open_pos_dict.items()) or 'ninguna'
            LOG.info(f"Balance: ${usdt:.2f} | Libre: ${free_usdt:.2f} | Posiciones: {pos_str}")
        except Exception as e:
            err_str = str(e)
            if "-2015" in err_str or "Invalid API-key" in err_str or "request ip" in err_str:
                notify_ip_error(err_str)
            LOG.warning(f"Health check error: {e}")

    def _cancel_order_safe(self, symbol, order_id):
        if not order_id:
            return
        try:
            self.ex.cancel_order(order_id, symbol)
        except Exception:
            pass

    def _get_position_amt(self, positions, symbol, side):
        # ccxt/Binance devuelve el symbol de la posicion con sufijo de settle
        # (ej. 'LINK/USDT:USDT'), mientras que 'symbol' aqui es el simple 'LINK/USDT'.
        # Comparamos solo la parte antes de ':' para que coincidan.
        want = 'LONG' if side == 'long' else 'SHORT'
        for p in positions:
            p_sym = (p.get('symbol') or '').split(':')[0]
            if p_sym == symbol and p.get('side', '').upper() == want:
                return abs(float(p.get('contracts', 0) or 0))
        return 0.0

    def _get_position_entry_price(self, positions, symbol, side):
        want = 'LONG' if side == 'long' else 'SHORT'
        for p in positions:
            p_sym = (p.get('symbol') or '').split(':')[0]
            if p_sym == symbol and p.get('side', '').upper() == want:
                return float(p.get('entryPrice', 0) or 0)
        return 0.0

    def evaluate_and_trade(self, symbol):
        try:
            p = self.params.get(symbol)
            if not p:
                return
            ohlcv = self.ex.fetch_ohlcv(symbol, TIMEFRAME, limit=150)
            if len(ohlcv) < 30:
                return
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = prepare_data(df.set_index('timestamp'))

            last_closed = df.iloc[-2]  # ultima vela cerrada (la -1 puede seguir formandose)
            candle_time = df.index[-2]
            close_p = float(last_closed['close'])
            atr_v = float(last_closed['ATR'])
            ema20 = float(last_closed['EMA20'])
            if atr_v <= 0:
                return
            # Referencia auto-calibrada: p25 del propio ATR en la ventana fetched (60 velas),
            # en vez de un % fijo del precio. Se adapta a la volatilidad real de cada simbolo
            # y no se deja enganar tan facil por una racha de velas corruptas del feed testnet
            # (mientras esa racha no domine mas de ~75% de la ventana).
            atr_hist = df['ATR'][df['ATR'] > 0]
            atr_ref = float(atr_hist.quantile(0.25)) if len(atr_hist) >= 10 else atr_v
            if atr_v > close_p * 0.03 or (atr_ref > 0 and atr_v > atr_ref * 4):
                # ATR implausible -- sintoma tipico de una mecha corrupta en el feed de
                # testnet (ej. un low pegado en un valor absurdo) contaminando el promedio
                # movil. Se salta este ciclo hasta que la vela mala salga de la ventana de
                # 14 periodos, en vez de operar con ella.
                LOG.warning(f"[{symbol}] ATR implausible (${atr_v:.4f} vs precio ${close_p:.2f}), "
                            f"se salta este ciclo -- probable dato corrupto del feed.")
                return

            positions = self.ex.fetch_positions([symbol])
            open_orders = self.ex.fetch_open_orders(symbol)
            open_order_ids = {o['id'] for o in open_orders}

            # El capital para dimensionar es fijo por simbolo (igual que en el backtest,
            # donde cada simbolo arranca con CAPITAL_PER_SYMBOL de forma independiente).
            # NO se usa el balance total de la cuenta: los risk_pct optimizados fueron
            # calibrados asumiendo ese capital base, no el saldo completo compartido
            # entre 5 simbolos x 2 lados -> eso agotaba el margen tras 2-3 simbolos.
            # Se pondera por el momentum de 30 dias (acotado 0.5x-2.0x, ver _compute_momentum_weights).
            equity = CAPITAL_PER_SYMBOL * self.capital_weights.get(symbol, 1.0)

            for side in ('long', 'short'):
                st = self.state[symbol][side]
                pos_amt = self._get_position_amt(positions, symbol, side)

                # --- entrada recien llenada: detectar transicion pendiente -> activa ---
                if not st['active'] and pos_amt > 0:
                    st['active'] = True
                    st['entry_time'] = candle_time
                    st['checked_time_exit_1'] = False
                    if st['sl'] is None or st['tp'] is None or st['entry_price'] is None:
                        # Posicion sin tracking previo (ej. el bot se reinicio con
                        # posiciones ya abiertas) -- nunca se calcularon SL/TP para ella.
                        # Se recalculan frescos con los parametros y el ATR actuales, en
                        # vez de dejarla sin proteccion (bracket con precio None fallaba).
                        actual_entry = self._get_position_entry_price(positions, symbol, side)
                        st['entry_price'] = actual_entry if actual_entry > 0 else close_p
                        if side == 'long':
                            spacing = atr_v * p['grid_spacing_mult']
                            st['sl'] = float(self.ex.price_to_precision(symbol, st['entry_price'] - atr_v * p['sl_mult']))
                            st['tp'] = float(self.ex.price_to_precision(symbol, st['entry_price'] + spacing * p['tp_mult']))
                        else:
                            spacing = atr_v * p['grid_spacing_mult_s']
                            st['sl'] = float(self.ex.price_to_precision(symbol, st['entry_price'] + atr_v * p['sl_mult_s']))
                            st['tp'] = float(self.ex.price_to_precision(symbol, st['entry_price'] - spacing * p['tp_mult_s']))
                        LOG.info(f"[{symbol}] Posicion {side.upper()} preexistente @ {st['entry_price']} "
                                 f"-> SL/TP recalculados: SL {st['sl']}, TP {st['tp']}")
                    sl_already_broken = self._place_bracket(symbol, side, st, pos_amt)
                    if sl_already_broken:
                        self._force_close(symbol, side, st, pos_amt, "SL ya roto al llenarse (rechazo -2021 en tiempo real)")
                        self._record_immediate_stop(symbol)
                        continue
                    send_telegram_alert(
                        f"✅ <b>ENTRADA LLENADA {side.upper()} — {symbol}</b>\n"
                        f"Entrada: <code>${st['entry_price']:,.4f}</code> | TP: <code>${st['tp']:,.4f}</code> | SL: <code>${st['sl']:,.4f}</code>"
                    )

                # --- posicion activa: manejar salidas por tiempo, o detectar cierre por TP/SL ---
                if st['active']:
                    if pos_amt <= 0:
                        # se cerro (TP o SL ejecutado, u otra causa) -> limpiar ordenes hermanas y resetear.
                        # No sabemos de antemano si fue TP o si el stop-order del exchange se disparo
                        # primero (mas rapido que nuestro chequeo activo) -- se decide por el signo del
                        # pnl real, no por el nombre generico del motivo.
                        self._cancel_order_safe(symbol, st['tp_order_id'])
                        self._cancel_order_safe(symbol, st['sl_order_id'])
                        pnl_cierre = self._notify_close(symbol, side, st, "Take-Profit / cierre en exchange")
                        if pnl_cierre is not None and pnl_cierre < 0:
                            self._record_immediate_stop(symbol)
                        self.state[symbol][side] = _empty_side_state()
                        continue

                    # Completar el bracket si quedo incompleto (ej. reconciliado desde una
                    # sesion anterior sin TP o sin SL existente en el exchange) -- calcula lo
                    # que falte con los parametros/ATR actuales y coloca solo esa pierna.
                    if st['tp_order_id'] is None or st['sl_order_id'] is None:
                        if st['sl'] is None or st['tp'] is None:
                            entry_ref = st['entry_price'] or close_p
                            if side == 'long':
                                spacing = atr_v * p['grid_spacing_mult']
                                st['sl'] = float(self.ex.price_to_precision(symbol, entry_ref - atr_v * p['sl_mult']))
                                st['tp'] = float(self.ex.price_to_precision(symbol, entry_ref + spacing * p['tp_mult']))
                            else:
                                spacing = atr_v * p['grid_spacing_mult_s']
                                st['sl'] = float(self.ex.price_to_precision(symbol, entry_ref + atr_v * p['sl_mult_s']))
                                st['tp'] = float(self.ex.price_to_precision(symbol, entry_ref - spacing * p['tp_mult_s']))
                        sl_already_broken = self._place_bracket(symbol, side, st, pos_amt, only_missing=True)
                        if sl_already_broken:
                            self._force_close(symbol, side, st, pos_amt, "SL ya roto (rechazo -2021 en tiempo real)")
                            self._record_immediate_stop(symbol)
                            continue

                    # Chequeo activo de SL: no confiamos solo en la orden STOP_MARKET del
                    # exchange -- en testnet a veces se acepta (sin error, con order id) pero
                    # despues no aparece ni funciona (mismo tipo de falla fantasma que ya
                    # vimos con closePosition). El bot vigila el precio el mismo y cierra
                    # por su cuenta si el SL quedaria roto, en vez de confiar ciegamente.
                    if st['sl'] is not None:
                        sl_breached = (close_p <= st['sl']) if side == 'long' else (close_p >= st['sl'])
                        if sl_breached:
                            self._force_close(symbol, side, st, pos_amt, "SL activo (vigilado por el bot)")
                            self._record_immediate_stop(symbol)
                            continue

                    bars_elapsed = int((candle_time - st['entry_time']) / pd.Timedelta(minutes=15))
                    if bars_elapsed >= TIME_EXIT_BAR_2:
                        self._force_close(symbol, side, st, pos_amt, "salida forzada (40 velas)")
                        continue
                    if bars_elapsed >= TIME_EXIT_BAR_1 and not st['checked_time_exit_1']:
                        st['checked_time_exit_1'] = True
                        adverse = (close_p <= ema20) if side == 'long' else (close_p >= ema20)
                        if adverse:
                            self._force_close(symbol, side, st, pos_amt, "salida por EMA20 (20 velas)")
                            continue
                    continue  # posicion activa y sin salida esta vez: no tocar entradas nuevas de este lado

                # --- sin posicion activa: gestionar orden de entrada pendiente ---
                if st['pending_since'] is not None:
                    still_open = st['entry_order_id'] in open_order_ids
                    if not still_open:
                        # No aparece en fetch_open_orders -- puede ser que se lleno/cancelo de
                        # verdad, o que la respuesta de la API vino incompleta por un hipo de
                        # red (sin lanzar excepcion). Verificamos la orden puntual antes de
                        # asumir que desaparecio, para no terminar con ordenes duplicadas.
                        try:
                            check = self.ex.fetch_order(st['entry_order_id'], symbol)
                            really_gone = check.get('status') not in ('open', 'NEW', 'PARTIALLY_FILLED')
                        except Exception:
                            really_gone = False  # ante la duda, no duplicar: se reintenta el proximo ciclo
                        if not really_gone:
                            continue
                        st['pending_since'] = None
                        st['entry_order_id'] = None
                    else:
                        bars_pending = int((candle_time - st['pending_since']) / pd.Timedelta(minutes=15))
                        if bars_pending < TIME_EXIT_BAR_2:
                            continue  # seguir esperando fill
                        self._cancel_order_safe(symbol, st['entry_order_id'])
                        st['pending_since'] = None
                        st['entry_order_id'] = None

                if symbol in self.paused or self._is_vetoed(symbol):
                    continue
                cooldown_until = self.entry_retry_cooldown.get((symbol, side), 0)
                if time.time() < cooldown_until:
                    continue
                self._place_entry(symbol, side, close_p, atr_v, p, equity, candle_time)

        except Exception as e:
            err_str = str(e)
            if "-2015" in err_str or "Invalid API-key" in err_str or "request ip" in err_str:
                notify_ip_error(err_str)
            LOG.warning(f"[{symbol}] Error evaluate_and_trade: {e}")

    def _place_entry(self, symbol, side, close_p, atr_v, p, equity, candle_time):
        try:
            if side == 'long':
                spacing = atr_v * p['grid_spacing_mult']
                entry = close_p - spacing
                sl = entry - atr_v * p['sl_mult']
                tp = entry + spacing * p['tp_mult']
                order_side = 'buy'
                position_side = 'LONG'
            else:
                spacing = atr_v * p['grid_spacing_mult_s']
                entry = close_p + spacing
                sl = entry + atr_v * p['sl_mult_s']
                tp = entry - spacing * p['tp_mult_s']
                order_side = 'sell'
                position_side = 'SHORT'

            if entry <= 0:
                return
            amt = self._sizing_amount(symbol, equity, p['risk_pct'], entry, sl)
            if amt <= 0:
                return
            entry_px = float(self.ex.price_to_precision(symbol, entry))
            amt_px = float(self.ex.amount_to_precision(symbol, amt))

            order = self.ex.create_order(symbol, 'limit', order_side, amt_px, entry_px,
                                          params={'positionSide': position_side})
            st = self.state[symbol][side]
            st['entry_order_id'] = order['id']
            st['entry_price'] = entry_px
            st['pending_since'] = candle_time
            st['sl'] = float(self.ex.price_to_precision(symbol, sl))
            st['tp'] = float(self.ex.price_to_precision(symbol, tp))
            LOG.info(f"[{symbol}] Entrada {side.upper()} colocada @ {entry_px} (SL {st['sl']}, TP {st['tp']}, amt {amt_px})")
            self.entry_retry_cooldown.pop((symbol, side), None)
        except Exception as e:
            err_str = str(e)
            cooldown_s = 180 if "-2019" in err_str or "insufficient" in err_str.lower() else 60
            self.entry_retry_cooldown[(symbol, side)] = time.time() + cooldown_s
            LOG.warning(f"[{symbol}] Error colocando entrada {side}: {e} (reintento en {cooldown_s}s)")

    def _sizing_amount(self, symbol, equity, risk_pct, entry, sl):
        riesgo_real_pct = abs(entry - sl) / entry
        pos_size_usd = (equity * risk_pct) / max(riesgo_real_pct, 0.001)
        cap = self.max_notional_per_leg.get(symbol, HARD_CAP_LIQUIDITY)
        pos_size_usd = min(pos_size_usd, cap)
        return pos_size_usd / entry

    def _place_bracket(self, symbol, side, st, pos_amt, only_missing=False):
        """Coloca TP y SL para una posicion. Con only_missing=True, no duplica una pierna
        que ya tenga order_id asignado (ej. adoptada de una sesion anterior via
        _reconcile_open_orders) -- evita el error -2022 ReduceOnly Order is rejected que
        sale cuando dos ordenes intentan reducir mas cantidad de la que hay en la posicion."""
        position_side = 'LONG' if side == 'long' else 'SHORT'
        close_side = 'sell' if side == 'long' else 'buy'
        amt_px = float(self.ex.amount_to_precision(symbol, pos_amt))

        if not (only_missing and st['tp_order_id']):
            try:
                tp_order = self.ex.create_order(symbol, 'limit', close_side, amt_px, st['tp'],
                                                 params={'positionSide': position_side})
                st['tp_order_id'] = tp_order['id']
            except Exception as e:
                LOG.warning(f"[{symbol}] Error colocando TP {side}: {e}")

        if not (only_missing and st['sl_order_id']):
            # closePosition=True dispara un bug de Binance testnet (-4130: rechaza la orden
            # alegando que ya existe una STOP/TP con closePosition, aunque no aparezca en
            # ninguna consulta ni se pueda cancelar). Usamos cantidad explicita en su lugar,
            # igual que el TP -- evita ese endpoint y es igual de efectivo para nuestro caso
            # (siempre cerramos toda la posicion de una).
            try:
                sl_order = self.ex.create_order(symbol, 'STOP_MARKET', close_side, amt_px, None,
                                                 params={'positionSide': position_side,
                                                         'stopPrice': st['sl']})
                st['sl_order_id'] = sl_order['id']
            except Exception as e:
                err_str = str(e)
                LOG.warning(f"[{symbol}] Error colocando SL {side}: {e}")
                if "-2021" in err_str:
                    # "Order would immediately trigger" -- Binance evalua contra el precio
                    # EN VIVO (no la vela cerrada que usa nuestro chequeo activo), asi que
                    # esto es en si mismo la confirmacion en tiempo real de que el SL ya
                    # esta roto. Se lo senalamos al caller para que cierre ya, en vez de
                    # reintentar la misma orden invalida cada ciclo sin cerrar nunca.
                    return True
        return False

    def _get_realized_pnl_and_price(self, symbol, position_side, lookback_sec=120):
        """Consulta los fills recientes para obtener el PnL realizado, precio promedio de
        salida y cantidad cerrada -- mas preciso que estimarlo con el TP/SL teorico porque
        refleja lo que realmente se ejecuto (incluye deslizamiento)."""
        try:
            since = int((time.time() - lookback_sec) * 1000)
            # limit generoso: se han visto entradas fragmentadas en hasta ~16 fills parciales
            # (ej. LINK) que podrian empujar el cierre real fuera de una ventana mas chica
            trades = self.ex.fetch_my_trades(symbol, since=since, limit=50)
            matching = [t for t in trades if t.get('info', {}).get('positionSide') == position_side]
            if not matching:
                return None, None, None
            pnl = sum(float(t.get('info', {}).get('realizedPnl', 0) or 0) for t in matching)
            total_amt = sum(float(t['amount']) for t in matching)
            avg_price = (sum(float(t['price']) * float(t['amount']) for t in matching) / total_amt
                         if total_amt > 0 else None)
            return pnl, avg_price, total_amt
        except Exception as e:
            LOG.warning(f"[{symbol}] No se pudo obtener PnL realizado del cierre: {e}")
            return None, None, None

    def _notify_close(self, symbol, side, st, motivo):
        """Alerta de cierre con PnL realizado ($ y %) y el patrimonio resultante -- antes
        solo se avisaba el motivo del cierre, sin ningun numero."""
        position_side = 'LONG' if side == 'long' else 'SHORT'
        pnl, avg_price, amt = self._get_realized_pnl_and_price(symbol, position_side)
        if pnl is None:
            send_telegram_alert(f"🔔 <b>{symbol} {side.upper()}</b> cerrada — {motivo}")
            return None
        entry = st.get('entry_price') or avg_price or 0
        notional = entry * amt if entry and amt else 0
        pct = (pnl / notional * 100) if notional > 0 else 0.0
        pnl_icon = '🟢' if pnl >= 0 else '🔴'
        try:
            bal = self.ex.fetch_balance()
            total = bal.get('USDT', {}).get('total', None)
        except Exception:
            total = None
        msg = (f"{pnl_icon} <b>{symbol} {side.upper()}</b> cerrada — {motivo}\n"
               f"PnL: <b>${pnl:+,.2f}</b> (<code>{pct:+.2f}%</code>)")
        if total is not None:
            signo = '+' if pnl >= 0 else ''
            msg += f"\nPortafolio: {signo}${pnl:,.2f} → total nuevo: <b>${total:,.2f}</b>"
        send_telegram_alert(msg)
        return pnl

    def _force_close(self, symbol, side, st, pos_amt, motivo):
        try:
            self._cancel_order_safe(symbol, st['tp_order_id'])
            self._cancel_order_safe(symbol, st['sl_order_id'])
            position_side = 'LONG' if side == 'long' else 'SHORT'
            close_side = 'sell' if side == 'long' else 'buy'
            amt_px = float(self.ex.amount_to_precision(symbol, pos_amt))
            self.ex.create_order(symbol, 'market', close_side, amt_px, None,
                                  params={'positionSide': position_side})
            LOG.info(f"[{symbol}] Cierre {side.upper()} por {motivo}")
            self._notify_close(symbol, side, st, motivo)
        except Exception as e:
            LOG.warning(f"[{symbol}] Error en cierre forzado {side}: {e}")
        finally:
            self.state[symbol][side] = _empty_side_state()

    def run(self):
        LOG.info(f"⚡ Portfolio WFO Bot Iniciado | {self.leverage}x | Simbolos: {SYMBOLS}")
        self.setup()

        last_health = 0
        while self.running:
            for sym in SYMBOLS:
                self.evaluate_and_trade(sym)

            if time.time() - last_health > 30:
                self.health_check()
                last_health = time.time()

            self._check_symbol_health()

            if time.time() - self.last_reopt > REOPT_INTERVAL_SEC:
                LOG.info("Iniciando reoptimizacion diaria...")
                self.reoptimize_all()

            time.sleep(POLL_SECONDS)

    def run_forever(self):
        signal.signal(signal.SIGTERM, lambda *_: self._shutdown())
        while True:
            try:
                self.run()
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:
                LOG.error(f"Error de red: {e}, reconectando en 10s...")
                time.sleep(10)
            except Exception as e:
                err_str = str(e)
                if "-2015" in err_str or "Invalid API-key" in err_str or "request ip" in err_str:
                    notify_ip_error(err_str)
                LOG.error(f"Error inesperado: {e}, reiniciando en 15s...")
                time.sleep(15)

    def _shutdown(self):
        LOG.info("SIGTERM recibido, apagando Portfolio WFO Bot...")
        self.running = False

def main():
    ex = get_exchange()
    bot = PortfolioWFOBot(ex)
    bot.run_forever()

if __name__ == '__main__':
    main()
