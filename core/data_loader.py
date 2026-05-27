import logging
from typing import List, Dict, Optional, Any

import ccxt
import pandas as pd

class ExchangeManager:
    """
    Gestor de conexiones a exchanges usando CCXT.
    Soporta múltiples exchanges con fallback automático en caso de fallo.
    """

    def __init__(self, primary_exchange: str = 'binance', secondary_exchanges: Optional[List[str]] = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        # Configuración básica del logger si no existe
        if not self.logger.handlers:
            logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

        if secondary_exchanges is None:
            secondary_exchanges = ['bybit', 'kucoin']

        self.supported_exchanges = ['binance', 'bybit', 'kucoin']
        self.exchanges: Dict[str, ccxt.Exchange] = {}

        # Inicializar instancias de CCXT configuradas para futuros (perpetuos)
        for ex_name in [primary_exchange] + secondary_exchanges:
            if ex_name in self.supported_exchanges:
                exchange_class = getattr(ccxt, ex_name)
                self.exchanges[ex_name] = exchange_class({
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'future'  # Importante para funding rate y open interest
                    }
                })

        self.primary_name = primary_exchange
        self.secondary_names = [name for name in secondary_exchanges if name in self.supported_exchanges]

    def _execute_with_fallback(self, method_name: str, symbol: str, *args, **kwargs) -> Any:
        """
        Intenta ejecutar un método de CCXT en el exchange primario.
        Si falla por problemas de red o del exchange, hace fallback a los secundarios.
        """
        exchanges_to_try = [self.primary_name] + self.secondary_names

        for ex_name in exchanges_to_try:
            if ex_name not in self.exchanges:
                continue

            exchange = self.exchanges[ex_name]
            try:
                if not hasattr(exchange, method_name):
                    self.logger.warning(f"El método '{method_name}' no existe en {ex_name}.")
                    continue

                method = getattr(exchange, method_name)
                result = method(symbol, *args, **kwargs)
                self.logger.debug(f"Éxito al ejecutar {method_name} en {ex_name}")
                return result

            except (ccxt.NetworkError, ccxt.ExchangeError) as e:
                self.logger.warning(f"Error ({type(e).__name__}) en {ex_name} ejecutando {method_name}: {e}. Probando fallback...")
            except Exception as e:
                self.logger.error(f"Error inesperado en {ex_name} ejecutando {method_name}: {e}. Probando fallback...")

        self.logger.error(f"Todos los exchanges fallaron para la operación '{method_name}' en el símbolo {symbol}.")
        return None

    def fetch_ohlcv(self, symbol: str, timeframe: str = '15m', since: Optional[int] = None, limit: int = 1000) -> pd.DataFrame:
        """
        Descarga velas históricas (OHLCV).
        Retorna un DataFrame de Pandas validado sin NaNs.
        """
        data = self._execute_with_fallback('fetch_ohlcv', symbol, timeframe, since, limit)

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        # Limpiar datos para evitar errores en el pipeline de indicadores
        df.dropna(inplace=True)
        return df

    _VALID_OB_DEPTHS = [5, 10, 20, 50, 100, 500, 1000]

    def fetch_order_book(self, symbol: str, limit: int = 20) -> Dict:
        # Binance solo acepta profundidades específicas; snapeamos al valor válido más cercano
        valid_limit = min(self._VALID_OB_DEPTHS, key=lambda x: (abs(x - limit), x))
        if valid_limit != limit:
            self.logger.debug(f"fetch_order_book: limit={limit} ajustado a {valid_limit} (no válido para Binance)")
        result = self._execute_with_fallback('fetch_order_book', symbol, valid_limit)
        return result if result else {"bids": [], "asks": []}

    def fetch_funding_rate(self, symbol: str) -> Dict:
        result = self._execute_with_fallback('fetch_funding_rate', symbol)
        return result if result else {}

    def fetch_open_interest(self, symbol: str) -> Dict:
        result = self._execute_with_fallback('fetch_open_interest', symbol)
        return result if result else {}

    def fetch_liquidations(self, symbol: str, since: Optional[int] = None, limit: int = 100) -> List[Dict]:
        result = self._execute_with_fallback('fetch_liquidations', symbol, since, limit)
        return result if result else []

    def fetch_taker_ratio(self, symbol: str, limit: int = 500) -> float:
        trades = self._execute_with_fallback('fetch_trades', symbol, None, limit)
        if not trades:
            return 1.0  # Neutral

        buy_vol, sell_vol = 0.0, 0.0
        for trade in trades:
            vol = trade.get('amount', 0.0) * trade.get('price', 0.0)
            if trade.get('side') == 'buy': buy_vol += vol
            elif trade.get('side') == 'sell': sell_vol += vol

        return buy_vol / sell_vol if sell_vol > 0 else (float('inf') if buy_vol > 0 else 1.0)