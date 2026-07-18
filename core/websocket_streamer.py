import asyncio
import json
import logging
import time
import websockets
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class WebSocketStreamer:
    """
    WebSocketStreamer gestiona el stream en tiempo real de Binance Futures.

    NOTA: actualmente SOLO se suscribe al stream `bookTicker` (mejor bid/ask)
    por cada símbolo. No hay suscripciones a aggTrade, depth, markPrice ni
    forceOrder; cualquier referencia anterior a esos streams está obsoleta.

    Implementa backoff exponencial para las reconexiones y mantiene en
    `mark_price_data[symbol]` el último precio conocido junto con el
    timestamp (epoch) del último mensaje recibido, para que el trading-core
    pueda detectar datos stale.
    """
    def __init__(self, buffer_size: int = 1000, testnet: bool = False):
        # Base URLs para Binance Futures
        self.base_url = "wss://stream.binancefuture.com/stream?streams=" if testnet else "wss://fstream.binance.com/stream?streams="
        # buffer_size se conserva por compatibilidad de firma, pero ya no hay
        # buffers intermedios: solo se guarda el último precio por símbolo.
        self.buffer_size = buffer_size

        # Último precio por símbolo: {"mark_price": float, "timestamp": epoch}
        self.mark_price_data: Dict[str, Any] = {}

        self.running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    async def start_streaming(self, symbols: List[str]):
        """Inicia el stream bookTicker para los símbolos indicados."""
        self.running = True
        streams = []
        for sym in symbols:
            # Binance stream symbols must be lowercase and without slashes (e.g. btcusdt)
            s = sym.replace('/', '').lower()
            streams.append(
                f"{s}@bookTicker" # bookTicker ha demostrado funcionar correctamente y ser muy rápido
            )

        stream_url = self.base_url + "/".join(streams)

        reconnect_delay = 1
        max_delay = 60

        while self.running:
            try:
                logger.info(f"Conectando a WebSocket: {stream_url}")
                async with websockets.connect(stream_url, ping_interval=180, ping_timeout=180) as ws:
                    self._ws = ws
                    logger.info("WebSocket conectado exitosamente.")
                    reconnect_delay = 1  # Reset delay on successful connection

                    async for message in ws:
                        if not self.running:
                            break
                        # Un mensaje malformado NO debe forzar una reconexión:
                        # se loguea y se descarta, continuando con el siguiente.
                        try:
                            parsed = json.loads(message)
                        except (json.JSONDecodeError, ValueError) as e:
                            logger.warning(f"Mensaje WebSocket malformado, se descarta: {e}")
                            continue
                        self._process_message(parsed)

            except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError, OSError) as e:
                logger.warning(f"Conexión perdida: {e}. Reconectando en {reconnect_delay} segundos...")
                if self.running:
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, max_delay)
            except Exception as e:
                logger.error(f"Error inesperado en WebSocket: {e}", exc_info=True)
                if self.running:
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, max_delay)

    async def stop_streaming(self):
        """Detiene el streaming de datos."""
        self.running = False
        if self._ws:
            await self._ws.close()
            logger.info("WebSocket desconectado a petición.")

    def _process_message(self, msg: Dict[str, Any]):
        """Procesa los mensajes recibidos del WebSocket (solo bookTicker)."""
        if "data" not in msg or "stream" not in msg:
            return

        stream_name = msg["stream"]
        data = msg["data"]

        symbol = data.get("s")

        if stream_name.endswith("@bookTicker"):
            # bookTicker nos da el mejor bid y ask en tiempo real.
            # OJO: el campo 'mark_price' NO es el mark price oficial de Binance,
            # es el precio medio (mid) del bookTicker: (best_bid + best_ask) / 2.
            bid = float(data.get("b", 0))
            ask = float(data.get("a", 0))
            mid_price = (bid + ask) / 2 if bid and ask else bid or ask

            self.mark_price_data[symbol] = {
                "mark_price": mid_price,
                "timestamp": time.time()  # epoch del último mensaje (detección de datos stale)
            }
