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
    
    class MockContextManager:
        async def __aenter__(self):
            # Raising inside to trigger exception handling
            raise websockets.exceptions.ConnectionClosed(1006, "Abnormal closure")
            
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    with patch("websockets.connect", return_value=MockContextManager()), patch("asyncio.sleep", new=mock_sleep):
        # This should loop 3 times due to mock_sleep stopping the streamer, testing the backoff
        await streamer.start_streaming(["BTCUSDT"])
        
    assert len(sleeps) == 3
    # Check that backoff logic is applied: 1, 2, 4
    assert sleeps == [1, 2, 4]

@pytest.mark.asyncio
async def test_websocket_process_messages():
    streamer = WebSocketStreamer()
    
    # aggTrade message
    msg_trade = {
        "stream": "btcusdt@aggTrade",
        "data": {
            "e": "aggTrade",
            "E": 123456789,
            "s": "BTCUSDT",
            "a": 5933014,
            "p": "0.001",
            "q": "100",
            "f": 100,
            "l": 105,
            "T": 123456785,
            "m": True
        }
    }
    streamer._process_message(msg_trade)
    assert len(streamer.ticks_buffer) == 1
    assert streamer.ticks_buffer[0]["price"] == 0.001
    assert streamer.ticks_buffer[0]["quantity"] == 100.0
    
    # depth message
    msg_depth = {
        "stream": "btcusdt@depth20@100ms",
        "data": {
            "e": "depthUpdate",
            "E": 123456789,
            "s": "BTCUSDT",
            "b": [["0.0024", "10"]],
            "a": [["0.0026", "100"]]
        }
    }
    streamer._process_message(msg_depth)
    assert "BTCUSDT" in streamer.order_book
    assert streamer.order_book["BTCUSDT"]["bids"][0] == [0.0024, 10.0]
    
    # markPrice message
    msg_mark = {
        "stream": "btcusdt@markPrice",
        "data": {
            "e": "markPriceUpdate",
            "E": 123456789,
            "s": "BTCUSDT",
            "p": "11794.15000000",
            "i": "11784.62659091",
            "P": "11784.25627172",
            "r": "0.00038167",
            "T": 1597392000000
        }
    }
    streamer._process_message(msg_mark)
    assert "BTCUSDT" in streamer.mark_price_data
    assert streamer.mark_price_data["BTCUSDT"]["mark_price"] == 11794.15
    assert streamer.mark_price_data["BTCUSDT"]["funding_rate"] == 0.00038167
    
    # forceOrder message
    msg_force = {
        "stream": "btcusdt@forceOrder",
        "data": {
            "e": "forceOrder",
            "E": 1568014460893,
            "o": {
                "s": "BTCUSDT",
                "c": "TEST",
                "S": "SELL",
                "o": "LIMIT",
                "f": "IOC",
                "q": "0.001",
                "p": "7110",
                "ap": "7110",
                "X": "FILLED",
                "l": "0.001",
                "z": "0.001",
                "T": 1568014460893
            }
        }
    }
    streamer._process_message(msg_force)
    assert len(streamer.liquidations) == 1
    assert streamer.liquidations[0]["side"] == "SELL"
    assert streamer.liquidations[0]["price"] == 7110.0
