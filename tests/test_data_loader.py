import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from core.data_loader import ExchangeManager
import ccxt

def test_exchange_manager_init():
    manager = ExchangeManager(primary_exchange='binance', secondary_exchanges=['bybit'])
    assert 'binance' in manager.exchanges
    assert 'bybit' in manager.exchanges
    assert manager.primary_name == 'binance'
    assert 'bybit' in manager.secondary_names

@patch('ccxt.binance.fetch_ohlcv')
def test_fetch_ohlcv_success(mock_fetch):
    manager = ExchangeManager(primary_exchange='binance')
    
    # Mocking CCXT output (timestamp, open, high, low, close, volume)
    mock_fetch.return_value = [
        [1672531200000, 16000, 16100, 15900, 16050, 100],
        [1672534800000, 16050, 16200, 16000, 16150, 150]
    ]
    
    df = manager.fetch_ohlcv('BTC/USDT', '1h', limit=2)
    
    assert not df.empty
    assert len(df) == 2
    assert 'open' in df.columns
    assert 'close' in df.columns
    assert df.index.name == 'timestamp'
    assert df.iloc[0]['close'] == 16050.0

@patch('ccxt.binance.fetch_ohlcv')
@patch('ccxt.bybit.fetch_ohlcv')
def test_fetch_ohlcv_fallback(mock_bybit_fetch, mock_binance_fetch):
    manager = ExchangeManager(primary_exchange='binance', secondary_exchanges=['bybit'])
    
    # Simulate Binance failure
    mock_binance_fetch.side_effect = ccxt.NetworkError("Binance is down")
    
    # Simulate Bybit success
    mock_bybit_fetch.return_value = [
        [1672531200000, 16000, 16100, 15900, 16050, 100]
    ]
    
    df = manager.fetch_ohlcv('BTC/USDT', '1h', limit=1)
    
    assert mock_binance_fetch.called
    assert mock_bybit_fetch.called
    assert not df.empty
    assert df.iloc[0]['close'] == 16050.0