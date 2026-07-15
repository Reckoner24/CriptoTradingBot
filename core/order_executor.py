import logging
import ccxt

logger = logging.getLogger(__name__)

class OrderExecutor:
    def __init__(self, exchange: ccxt.Exchange, leverage: int = 3):
        self.exchange = exchange
        self.leverage = leverage
        self.configured_symbols = set()

    def _ensure_leverage(self, symbol: str):
        if symbol not in self.configured_symbols:
            try:
                # Modificar apalancamiento usando ccxt
                self.exchange.set_leverage(self.leverage, symbol)
                # Setear margin mode (opcional, dejamos default por ahora)
                self.configured_symbols.add(symbol)
                logger.info(f"[OrderExecutor] Leverage configurado exitosamente a {self.leverage}x para {symbol}")
            except Exception as e:
                logger.warning(f"[OrderExecutor] Error seteando leverage para {symbol} (puede que ya esté configurado): {e}")
                self.configured_symbols.add(symbol) # Evitar reintentos constantes

    def open_position(self, symbol: str, direction: str, size_usd: float, price: float) -> dict:
        self._ensure_leverage(symbol)
        
        # Calcular tamaño base (ej. cantidad de BTC). Se recorta a 4 decimales por seguridad, 
        # aunque ccxt manejará los precision rules internamente si amount_to_precision se usa
        amount = size_usd / price
        
        # Binance requiere formatear la cantidad según la precisión del mercado
        try:
            markets = self.exchange.load_markets()
            if symbol in markets:
                amount = float(self.exchange.amount_to_precision(symbol, amount))
        except Exception:
            pass
            
        side = 'buy' if direction == 'LONG' else 'sell'
        
        try:
            logger.info(f"[OrderExecutor] Abriendo {direction} en {symbol} | Cantidad: {amount} @ Market")
            order = self.exchange.create_market_order(symbol, side, amount)
            avg_price = order.get('average') or order.get('price') or price
            logger.info(f"[OrderExecutor] ✅ Orden ejecutada: ID {order.get('id')} a precio {avg_price}")
            return {
                'status': 'success',
                'order_id': order.get('id'),
                'entry_price': avg_price,
                'amount': amount,
                'size_usd': size_usd
            }
        except Exception as e:
            logger.error(f"[OrderExecutor] ❌ Error abriendo posición en {symbol}: {e}")
            return {'status': 'error', 'message': str(e)}

    def close_position(self, symbol: str, direction: str, amount: float) -> dict:
        side = 'sell' if direction == 'LONG' else 'buy'
        
        try:
            logger.info(f"[OrderExecutor] Cerrando {direction} en {symbol} | Cantidad: {amount} @ Market")
            # Usar reduceOnly para evitar abrir posiciones inversas por error
            params = {'reduceOnly': True}
            order = self.exchange.create_market_order(symbol, side, amount, params=params)
            avg_price = order.get('average') or order.get('price')
            logger.info(f"[OrderExecutor] ✅ Orden de cierre ejecutada: ID {order.get('id')}")
            return {
                'status': 'success',
                'order_id': order.get('id'),
                'close_price': avg_price
            }
        except Exception as e:
            logger.error(f"[OrderExecutor] ❌ Error cerrando posición en {symbol}: {e}")
            return {'status': 'error', 'message': str(e)}