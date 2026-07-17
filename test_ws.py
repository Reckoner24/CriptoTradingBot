import asyncio
import websockets
import json
import sys

async def test():
    uri = "wss://fstream.binance.com/stream?streams=btcusdt@bookTicker/ethusdt@bookTicker"
    print("Connecting...")
    async with websockets.connect(uri) as ws:
        print("Connected.")
        for i in range(5):
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print("Received:", msg[:150])
            
asyncio.run(test())
