import asyncio
import json
import logging
import websockets
from collections import deque
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class WebSocketStreamer:
    """
    WebSocketStreamer manages real-time data streams from Binance Futures.
    It supports aggTrade, depth20, markPrice, and forceOrder streams.
    Implements exponential backoff for reconnections and maintains a tick buffer.
    """
    def __init__(self, buffer_size: int = 1000, testnet: bool = False):
        # Base URLs para Binance Futures
        self.base_url = "wss://stream.binancefuture.com/stream?streams=" if testnet else "wss://fstream.binance.com/stream?streams="
        self.buffer_size = buffer_size
        
        # Buffers en memoria
        self.ticks_buffer: deque = deque(maxlen=self.buffer_size)
        self.order_book: Dict[str, Any] = {}
        self.mark_price_data: Dict[str, Any] = {}
        self.liquidations: deque = deque(maxlen=self.buffer_size)
        
        self.running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    async def start_streaming(self, symbols: List[str]):
        """Inicia todos los streams para los símbolos indicados."""
        self.running = True
        streams = []
        for sym in symbols:
            s = sym.lower()
            streams.extend([
                f"{s}@aggTrade",
                f"{s}@depth20@100ms",
                f"{s}@markPrice",
                f"{s}@forceOrder"
            ])
            
        stream_url = self.base_url + "/".join(streams)
        
        reconnect_delay = 1
        max_delay = 60
        
        while self.running:
            try:
                logger.info(f"Conectando a WebSocket: {stream_url}")
                async with websockets.connect(stream_url) as ws:
                    self._ws = ws
                    logger.info("WebSocket conectado exitosamente.")
                    reconnect_delay = 1  # Reset delay on successful connection
                    
                    async for message in ws:
                        if not self.running:
                            break
                        self._process_message(json.loads(message))
                        
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
        """Procesa los mensajes recibidos del WebSocket y los almacena en el buffer correspondiente."""
        if "data" not in msg or "stream" not in msg:
            return
            
        stream_name = msg["stream"]
        data = msg["data"]
        
        event_type = data.get("e")
        symbol = data.get("s")
        
        if stream_name.endswith("@aggTrade"):
            # Aggregated Trade
            tick = {
                "timestamp": data.get("T"),
                "symbol": symbol,
                "price": float(data.get("p", 0)),
                "quantity": float(data.get("q", 0)),
                "is_buyer_maker": data.get("m", False)
            }
            self.ticks_buffer.append(tick)
            
        elif stream_name.endswith("@depth20@100ms"):
            # Partial Book Depth
            if symbol not in self.order_book:
                self.order_book[symbol] = {}
            self.order_book[symbol] = {
                "bids": [[float(p), float(q)] for p, q in data.get("b", [])],
                "asks": [[float(p), float(q)] for p, q in data.get("a", [])],
                "timestamp": data.get("E")
            }
            
        elif stream_name.endswith("@markPrice"):
            # Mark Price and Funding Rate
            if symbol not in self.mark_price_data:
                self.mark_price_data[symbol] = {}
            self.mark_price_data[symbol] = {
                "mark_price": float(data.get("p", 0)),
                "funding_rate": float(data.get("r", 0)),
                "next_funding_time": data.get("T")
            }
            
        elif stream_name.endswith("@forceOrder"):
            # Liquidation Order
            order = data.get("o", {})
            liquidation = {
                "symbol": symbol,
                "side": order.get("S"),
                "type": order.get("o"),
                "price": float(order.get("p", 0)),
                "quantity": float(order.get("q", 0)),
                "timestamp": data.get("E")
            }
            self.liquidations.append(liquidation)
