"""
Motor de ejecucion Maker/Post-Only.

Uso previsto: entradas de una estrategia de senal (no las salidas de emergencia
del DGT bot -- stop-loss, liquidation guard y boundary break deben seguir usando
market orders, porque ahi lo que importa es garantizar la ejecucion, no ahorrar
comision).

Coloca una orden LIMIT con timeInForce=GTX (post-only real de Binance: se
rechaza si cruzaria el spread, nunca se convierte en taker por accidente).
Si no se llena en `timeout_s`, cancela y recoloca al nuevo mejor precio, hasta
`max_requeues` veces. Si se agotan los intentos, NO cae a market -- reporta
que no se lleno, para no contaminar la medicion de costo real.
"""
import time
import logging

LOG = logging.getLogger('maker_exec')


class MakerExecutionResult:
    def __init__(self):
        self.filled = False
        self.fill_price = None
        self.requested_price = None
        self.attempts = 0
        self.rejections = 0
        self.total_wait_s = 0.0
        self.order_ids = []


def place_maker_order(ex, symbol, side, amount, timeout_s=5.0, max_requeues=2, poll_s=0.5,
                       reduce_only=False):
    """side: 'buy' o 'sell'. amount ya en unidades del activo base.
    reduce_only=True para cerrar posicion sin poder abrir una nueva en sentido contrario."""
    result = MakerExecutionResult()
    market = ex.market(symbol)
    tick = market['precision']['price']

    for _ in range(max_requeues + 1):
        try:
            ob = ex.fetch_order_book(symbol, limit=5)
        except Exception as e:
            LOG.warning(f"[{symbol}] Error consultando order book: {e}")
            time.sleep(poll_s)
            continue
        if not ob['bids'] or not ob['asks']:
            continue
        best_bid = ob['bids'][0][0]
        best_ask = ob['asks'][0][0]

        if side == 'buy':
            price = best_bid + tick
            price = min(price, best_ask - tick)  # nunca cruzar (evitar rechazo GTX)
        else:
            price = best_ask - tick
            price = max(price, best_bid + tick)
        price = float(ex.price_to_precision(symbol, price))
        result.requested_price = price

        params = {'timeInForce': 'GTX'}
        if reduce_only:
            params['reduceOnly'] = True
        try:
            order = ex.create_order(symbol, 'limit', side, amount, price, params)
        except Exception as e:
            result.rejections += 1
            LOG.info(f"[{symbol}] post-only rechazada ({side} @ {price}): {e}")
            time.sleep(poll_s)
            continue

        result.order_ids.append(order['id'])
        result.attempts += 1
        start = time.time()
        while time.time() - start < timeout_s:
            time.sleep(poll_s)
            try:
                o = ex.fetch_order(order['id'], symbol)
            except Exception:
                continue
            if o['status'] == 'closed':
                result.filled = True
                result.fill_price = float(o.get('average') or price)
                result.total_wait_s += time.time() - start
                return result
            if o['status'] == 'canceled':
                break
        else:
            try:
                ex.cancel_order(order['id'], symbol)
            except Exception:
                pass
        result.total_wait_s += time.time() - start

    return result
