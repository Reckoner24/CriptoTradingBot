import pytest
import asyncio
from unittest.mock import patch, MagicMock
from core.websocket_streamer import WebSocketStreamer

@pytest.mark.asyncio
async def test_websocket_streamer_reconnection():
    streamer = WebSocketStreamer(testnet=True)

    # Mock websockets.connect to simulate a connection failure on the first try, then a success.
    # To do this without a real server, we will patch websockets.connect and simulate the iteration

    # Track the delay times it sleeps
    sleeps = []

    async def mock_sleep(delay):
        sleeps.append(delay)
        # We need a way to break out of the while loop after some reconnections
        if len(sleeps) >= 3:
            streamer.running = False

    # Creating a mock connection that raises ConnectionClosed immediately
    import websockets
    from websockets.frames import Close

    class MockContextManager:
        async def __aenter__(self):
            # Raising inside to trigger exception handling
            raise websockets.exceptions.ConnectionClosed(Close(1006, "Abnormal closure"), None)

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("websockets.connect", return_value=MockContextManager()), patch("asyncio.sleep", new=mock_sleep):
        # This should loop 3 times due to mock_sleep stopping the streamer, testing the backoff
        await streamer.start_streaming(["BTCUSDT"])

    assert len(sleeps) == 3
    # Check that backoff logic is applied: 1, 2, 4
    assert sleeps == [1, 2, 4]


def test_websocket_process_bookticker_message():
    """El streamer actual solo consume bookTicker: el 'mark_price' almacenado
    es el mid price (best_bid + best_ask) / 2 y debe incluir 'timestamp'."""
    streamer = WebSocketStreamer()

    # Mensaje combined real de Binance Futures: stream '{symbol}@bookTicker'
    msg = {
        "stream": "btcusdt@bookTicker",
        "data": {
            "e": "bookTicker",
            "u": 400900217,
            "E": 1568014460893,
            "T": 1568014460891,
            "s": "BTCUSDT",
            "b": "11790.00",  # best bid price
            "B": "0.500",     # best bid qty
            "a": "11792.00",  # best ask price
            "A": "0.250"      # best ask qty
        }
    }
    streamer._process_message(msg)

    assert "BTCUSDT" in streamer.mark_price_data
    entry = streamer.mark_price_data["BTCUSDT"]
    # mark_price = (bid + ask) / 2
    assert entry["mark_price"] == pytest.approx((11790.00 + 11792.00) / 2)
    # Debe existir la clave 'timestamp' (detección de datos stale)
    assert "timestamp" in entry
    assert isinstance(entry["timestamp"], float)
    assert entry["timestamp"] > 0


def test_websocket_process_bookticker_ignores_malformed():
    """Mensajes sin 'stream'/'data' o de otros streams no deben romper el handler."""
    streamer = WebSocketStreamer()

    # Sin claves combined
    streamer._process_message({"data": {}})
    streamer._process_message({"stream": "btcusdt@bookTicker"})
    # Stream desconocido: se ignora
    streamer._process_message({
        "stream": "btcusdt@aggTrade",
        "data": {"e": "aggTrade", "s": "BTCUSDT", "p": "100", "q": "1"}
    })

    assert streamer.mark_price_data == {}
