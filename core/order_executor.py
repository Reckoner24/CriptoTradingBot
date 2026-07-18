import logging
import time
import ccxt

logger = logging.getLogger(__name__)

class OrderExecutor:
    def __init__(self, exchange: ccxt.Exchange, leverage: int = 3):
        self.exchange = exchange
        self.leverage = leverage
        self.configured_symbols = set()
        # Cache de mercados para no llamar load_markets() (REST pesado) en cada apertura
        self._markets = None

    def _ensure_leverage(self, symbol: str):
        if symbol not in self.configured_symbols:
            try:
                # Modificar apalancamiento usando ccxt
                self.exchange.set_leverage(self.leverage, symbol)
                # Setear margin mode (opcional, dejamos default por ahora)
                self.configured_symbols.add(symbol)
                logger.info(f"[OrderExecutor] Leverage configurado exitosamente a {self.leverage}x para {symbol}")
            except Exception as e:
                # NO marcamos el símbolo como configurado: así se reintentará en la próxima operación
                logger.warning(f"[OrderExecutor] Error seteando leverage para {symbol} (se reintentará en la próxima operación): {e}")

    def _get_markets(self) -> dict:
        """Devuelve los mercados del exchange, cacheándolos tras la primera carga."""
        if self._markets is None:
            self._markets = self.exchange.load_markets()
        return self._markets

    def _apply_amount_precision(self, symbol: str, amount: float):
        """
        Formatea la cantidad según la precisión del mercado.
        Devuelve (amount_formateado, error). Si error no es None, NO se debe enviar la orden.
        """
        try:
            markets = self._get_markets()
            if symbol in markets:
                return float(self.exchange.amount_to_precision(symbol, amount)), None
            return amount, None
        except Exception as e:
            logger.error(f"[OrderExecutor] Error aplicando amount_to_precision para {symbol}: {e}")
            return None, f"Error de precisión en amount para {symbol}: {e}"

    def _check_partial_fill(self, order: dict, requested_amount: float, result: dict):
        """Marca en el resultado si la orden se llenó parcialmente."""
        status = order.get('status')
        filled = order.get('filled')
        try:
            filled = float(filled) if filled is not None else None
        except (TypeError, ValueError):
            filled = None
        if filled is not None and requested_amount and filled < requested_amount:
            logger.warning(
                f"[OrderExecutor] FILL PARCIAL: {filled} de {requested_amount} ejecutado (status={status})"
            )
            result['partial'] = True
            result['filled'] = filled

    def open_position(self, symbol: str, direction: str, size_usd: float, price: float) -> dict:
        self._ensure_leverage(symbol)

        # Calcular tamaño base (ej. cantidad de BTC).
        amount = size_usd / price

        # Binance requiere formatear la cantidad según la precisión del mercado.
        # Si falla, NO enviamos el amount crudo: devolvemos error.
        amount, precision_error = self._apply_amount_precision(symbol, amount)
        if precision_error:
            return {'status': 'error', 'message': precision_error}

        side = 'buy' if direction == 'LONG' else 'sell'

        try:
            logger.info(f"[OrderExecutor] Abriendo {direction} en {symbol} | Cantidad: {amount} @ Market")
            order = self.exchange.create_market_order(symbol, side, amount)

            # Precio medio real de la respuesta (si viene)
            avg_price = order.get('average') or order.get('price')
            estimated = False

            if not avg_price and order.get('id'):
                try:
                    time.sleep(0.5) # Breve espera para asegurar que el exchange procese el trade
                    fetched = self.exchange.fetch_order(order.get('id'), symbol)
                    avg_price = fetched.get('average') or fetched.get('price')
                except Exception as ex:
                    logger.warning(f"[OrderExecutor] No se pudo hacer fetch_order para {symbol}: {ex}")

            if not avg_price:
                # Ni la respuesta ni fetch_order dieron precio medio: usamos el estimado
                # pero lo MARCAMOS para que el caller sepa que es aproximado.
                avg_price = price
                estimated = True

            result = {
                'status': 'success',
                'order_id': order.get('id'),
                'entry_price': avg_price,
                'amount': amount,
                'size_usd': size_usd
            }
            if estimated:
                result['estimated'] = True

            # Verificar fills: reportar si hubo ejecución parcial
            self._check_partial_fill(order, amount, result)

            logger.info(f"[OrderExecutor] Orden ejecutada: ID {order.get('id')} a precio {avg_price}"
                        f"{' (ESTIMADO)' if estimated else ''}"
                        f"{' (PARCIAL)' if result.get('partial') else ''}")
            return result
        except Exception as e:
            logger.error(f"[OrderExecutor] Error abriendo posición en {symbol}: {e}")
            return {'status': 'error', 'message': str(e)}

    def close_position(self, symbol: str, direction: str, amount: float) -> dict:
        side = 'sell' if direction == 'LONG' else 'buy'

        # Igual que en apertura: no enviar amount crudo si la precisión falla
        amount, precision_error = self._apply_amount_precision(symbol, amount)
        if precision_error:
            return {'status': 'error', 'message': precision_error}

        try:
            logger.info(f"[OrderExecutor] Cerrando {direction} en {symbol} | Cantidad: {amount} @ Market")
            # Usar reduceOnly para evitar abrir posiciones inversas por error
            params = {'reduceOnly': True}
            order = self.exchange.create_market_order(symbol, side, amount, params=params)
            avg_price = order.get('average') or order.get('price')
            if not avg_price and order.get('id'):
                try:
                    time.sleep(0.5)
                    fetched = self.exchange.fetch_order(order.get('id'), symbol)
                    avg_price = fetched.get('average') or fetched.get('price')
                except Exception as ex:
                    logger.warning(f"[OrderExecutor] No se pudo hacer fetch_order de cierre para {symbol}: {ex}")

            result = {
                'status': 'success',
                'order_id': order.get('id'),
                'close_price': avg_price
            }

            # Verificar fills: reportar si hubo cierre parcial
            self._check_partial_fill(order, amount, result)

            logger.info(f"[OrderExecutor] Orden de cierre ejecutada: ID {order.get('id')} a precio {avg_price}"
                        f"{' (PARCIAL)' if result.get('partial') else ''}")
            return result
        except Exception as e:
            logger.error(f"[OrderExecutor] Error cerrando posicion en {symbol}: {e}")
            return {'status': 'error', 'message': str(e)}
