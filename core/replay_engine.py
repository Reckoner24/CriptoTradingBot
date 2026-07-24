"""Motor unico de replay para validar la estrategia ejecutable.

No usa red ni estado global. Modela los caps de margen, fills conservadores,
anti-churn, fee y el mismo gestor de salidas que el daemon.
"""

from core.exit_manager import protective_exit


def run_live_replay(df, params, initial_balance=250.0, leverage=5,
                    cap_per_trade=0.30, cap_total=0.85, fee_round_trip=0.0008,
                    min_tp_distance_pct=0.0024, max_adx=25.0,
                    slippage_pct=0.0002, exit_cfg=None, trend_filter=True,
                    er_max=None, er_period=20, rsi_filter=False,
                    rsi_long_max=45.0, rsi_short_min=55.0,
                    vol_filter=False, vol_min=0.5, vol_max=3.0,
                    hard_cap=10000.0):
    """Replay por velas 15m de la semantica ejecutable del bot.

    Devuelve ``(balance_final, trades)``. Cada trade contiene PnL y motivo,
    permitiendo que el optimizador penalice drawdown y resultados frágiles.

    ``exit_cfg`` (opcional): overrides para el gestor de salidas
    (be_trigger_frac, trail_frac, min_tp_frac).
    ``trend_filter``: si es True, las ENTRADAS se alinean con la pendiente de
    la EMA20 (LONG solo si sube, SHORT solo si baja). Las salidas no se ven
    afectadas nunca.
    ``er_max`` (opcional): si se indica, bloquea las ENTRADAS cuando el
    Kaufman Efficiency Ratio de ``er_period`` velas supera el umbral
    (mercado direccional: el grid mean-reversion es el que mas sufre).
    ``rsi_filter``: si es True, bloquea LONG cuando RSI > rsi_long_max
    (dip) y SHORT cuando RSI < rsi_short_min (rally). La columna 'RSI'
    debe existir en el DataFrame; si no esta presente, el filtro es no-op.
    """
    if len(df) < 3:
        return initial_balance, []

    o = df['open'].values; h = df['high'].values; l = df['low'].values
    c = df['close'].values; atr = df['ATR'].values; ema = df['EMA20'].values
    balance, used_margin = initial_balance, 0.0
    positions = {'LONG': None, 'SHORT': None}
    last_close = {'LONG': -1, 'SHORT': -1}
    trades = []
    exit_kwargs = dict(exit_cfg) if exit_cfg else {}

    def close(k, direction, pos, price, reason):
        nonlocal balance, used_margin
        price = price * (1 - slippage_pct if direction == 'LONG' else 1 + slippage_pct)
        pnl_pct = ((price - pos['entry']) / pos['entry'] if direction == 'LONG'
                   else (pos['entry'] - price) / pos['entry']) - fee_round_trip
        pnl = pos['size'] * pnl_pct
        balance += pnl
        used_margin = max(0.0, used_margin - pos['margin'])
        trades.append({'k': k, 'dir': direction, 'reason': reason, 'pnl': pnl,
                       'entry': pos['entry'], 'exit': price})
        positions[direction] = None
        last_close[direction] = k

    for k in range(1, len(df)):
        ref_atr, ref_close = atr[k - 1], c[k - 1]
        if not ref_atr or ref_atr <= 0:
            continue
        levels = {
            'LONG': (ref_close - ref_atr * params['grid_spacing_mult_l'],),
            'SHORT': (ref_close + ref_atr * params['grid_spacing_mult_s'],),
        }
        entry_l = levels['LONG'][0]
        entry_s = levels['SHORT'][0]
        levels['LONG'] = (entry_l, entry_l + (ref_close - entry_l) * params['tp_mult_l'],
                          entry_l - ref_atr * params['sl_mult_l'])
        levels['SHORT'] = (entry_s, entry_s - (entry_s - ref_close) * params['tp_mult_s'],
                           entry_s + ref_atr * params['sl_mult_s'])

        # Salidas: un SL se resuelve antes que el TP dentro de la misma vela.
        for direction in ('LONG', 'SHORT'):
            pos = positions[direction]
            if pos is None:
                continue
            held = k - pos['fill_idx']
            price = reason = None
            if direction == 'LONG':
                if l[k] <= pos['sl']:
                    price, reason = pos['sl'], 'STOP LOSS'
                elif h[k] >= pos['tp']:
                    price, reason = pos['tp'], 'TAKE PROFIT'
                else:
                    protected, why = protective_exit('LONG', pos['entry'], pos['tp'], pos['sl'],
                                                      pos['peak'], c[k], ema[k - 1], **exit_kwargs)
                    if protected is not None:
                        price, reason = protected, why
                    elif held == 20 and c[k] <= ema[k - 1]:
                        price, reason = c[k], 'SMART TIMEOUT (EMA CONTRA)'
                    elif held >= 40:
                        price, reason = c[k], 'HARD TIMEOUT'
                    else:
                        pos['peak'] = max(pos['peak'], h[k])
            else:
                if h[k] >= pos['sl']:
                    price, reason = pos['sl'], 'STOP LOSS'
                elif l[k] <= pos['tp']:
                    price, reason = pos['tp'], 'TAKE PROFIT'
                else:
                    protected, why = protective_exit('SHORT', pos['entry'], pos['tp'], pos['sl'],
                                                      pos['peak'], c[k], ema[k - 1], **exit_kwargs)
                    if protected is not None:
                        price, reason = protected, why
                    elif held == 20 and c[k] >= ema[k - 1]:
                        price, reason = c[k], 'SMART TIMEOUT (EMA CONTRA)'
                    elif held >= 40:
                        price, reason = c[k], 'HARD TIMEOUT'
                    else:
                        pos['peak'] = min(pos['peak'], l[k])
            if price is not None:
                close(k, direction, pos, price, reason)

        # Entradas posteriores a las salidas, con caps idénticos al daemon.
        # El grid sólo se habilita en rango; ADX alto indica tendencia y es la
        # condición que históricamente concentra los stops grandes. La puerta
        # aplica SOLO a entradas: las salidas ya se evaluaron arriba (antes el
        # 'continue' de ADX saltaba también las salidas: bug de paridad).
        if max_adx is not None and 'ADX' in df and df['ADX'].iloc[k - 1] > max_adx:
            continue
        # Filtro de regimen (Kaufman Efficiency Ratio): mercado direccional ->
        # el grid no entra. Solo afecta a entradas; las salidas ya se evaluaron.
        if er_max is not None and k > er_period:
            change = abs(c[k - 1] - c[k - 1 - er_period])
            path = 0.0
            for i in range(k - er_period, k):
                path += abs(c[i] - c[i - 1])
            if path > 0 and change / path > er_max:
                continue
        # Filtro de alineación MTF (1h/4h) para prevenir entradas contra-tendencia.
        macro_bearish = macro_bullish = False
        if trend_filter and k >= 17:
            macro_bullish = (ema[k - 1] >= ema[k - 5]) and (ema[k - 1] >= ema[k - 17])
            macro_bearish = (ema[k - 1] <= ema[k - 5]) and (ema[k - 1] <= ema[k - 17])

        for direction in ('LONG', 'SHORT'):
            if positions[direction] is not None or last_close[direction] >= k:
                continue
            if direction == 'LONG' and macro_bearish:
                continue
            if direction == 'SHORT' and macro_bullish:
                continue
            if rsi_filter and 'RSI' in df:
                rsi_val = df['RSI'].iloc[k - 1]
                if direction == 'LONG' and rsi_val > rsi_long_max:
                    continue
                if direction == 'SHORT' and rsi_val < rsi_short_min:
                    continue
            if vol_filter and 'REL_VOL' in df:
                rv = df['REL_VOL'].iloc[k - 1]
                if rv < vol_min or rv > vol_max:
                    continue
            entry, tp, sl = levels[direction]
            sane = sl < entry < tp if direction == 'LONG' else tp < entry < sl
            tp_dist = ((tp - entry) / entry if direction == 'LONG' else (entry - tp) / entry)
            touched = l[k] <= entry if direction == 'LONG' else h[k] >= entry
            if not sane or tp_dist < min_tp_distance_pct or not touched:
                continue
            fill = min(o[k], entry) if direction == 'LONG' else max(o[k], entry)
            fill = fill * (1 + slippage_pct if direction == 'LONG' else 1 - slippage_pct)
            if (direction == 'LONG' and fill <= sl) or (direction == 'SHORT' and fill >= sl):
                continue
            stop_pct = abs(entry - sl) / entry
            ideal = balance * params['risk_pct'] / max(stop_pct, 0.001)
            available = max(0.0, balance * cap_total - used_margin)
            size = min(ideal, balance * cap_per_trade * leverage, available * leverage, hard_cap)
            if size < 10:
                continue
            margin = size / leverage
            positions[direction] = {'entry': fill, 'tp': tp, 'sl': sl, 'peak': fill,
                                    'size': size, 'margin': margin, 'fill_idx': k}
            used_margin += margin

    # Marca a mercado de posiciones aún abiertas, como cualquier reporte OOS.
    for direction, pos in positions.items():
        if pos is not None:
            close(len(df) - 1, direction, pos, c[-1], 'FIN DE VENTANA (mark)')
    return balance, trades
