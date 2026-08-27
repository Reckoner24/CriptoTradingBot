import os
import sys
import json
import ccxt
import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_atr(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close'].shift(1)
    tr1 = high - low
    tr2 = (high - close).abs()
    tr3 = (low - close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return atr

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def run_analysis():
    key = os.getenv('BINANCE_MAIN_KEY')
    secret = os.getenv('BINANCE_MAIN_SECRET')
    
    ex = ccxt.binance({
        'apiKey': key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })
    
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    results = {}
    
    balance_info = ex.fetch_balance()
    usdt_total = balance_info['total'].get('USDT', 0)
    usdt_free = balance_info['free'].get('USDT', 0)
    
    positions_raw = balance_info.get('info', {}).get('positions', [])
    open_positions = {}
    for p in positions_raw:
        amt = float(p.get('positionAmt', 0))
        if abs(amt) > 0.0001:
            sym = p.get('symbol')
            norm_sym = sym.replace('USDT', '/USDT')
            notional = float(p.get('notional', 0))
            leverage = float(p.get('leverage', 10))
            upnl = float(p.get('unrealizedProfit', 0))
            entry = float(p.get('entryPrice', 0))
            mark = float(p.get('markPrice', 0))
            
            margin = abs(notional) / leverage if leverage > 0 else abs(notional)
            roe_pct = (upnl / margin * 100) if margin > 0 else 0.0
            
            open_positions[norm_sym] = {
                'symbol': sym,
                'side': 'LONG' if amt > 0 else 'SHORT',
                'amount': amt,
                'entry_price': entry,
                'mark_price': mark,
                'unrealized_pnl': upnl,
                'notional': notional,
                'margin': margin,
                'leverage': leverage,
                'roe_pct': roe_pct
            }

    for sym in symbols:
        ohlcv_15m = ex.fetch_ohlcv(sym, timeframe='15m', limit=100)
        df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        ohlcv_1h = ex.fetch_ohlcv(sym, timeframe='1h', limit=100)
        df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df_15m['rsi'] = calculate_rsi(df_15m['close'], 14)
        df_15m['atr'] = calculate_atr(df_15m, 14)
        df_15m['ema20'] = calculate_ema(df_15m['close'], 20)
        df_15m['ema50'] = calculate_ema(df_15m['close'], 50)
        
        df_1h['rsi'] = calculate_rsi(df_1h['close'], 14)
        df_1h['atr'] = calculate_atr(df_1h, 14)
        df_1h['ema20'] = calculate_ema(df_1h['close'], 20)
        df_1h['ema50'] = calculate_ema(df_1h['close'], 50)
        
        try:
            funding = ex.fetch_funding_rate(sym)
            funding_rate = funding.get('fundingRate', 0.0)
            funding_rate_pct = funding_rate * 100 if funding_rate else 0.0
        except Exception:
            funding_rate_pct = 0.0
            
        current_price = df_15m['close'].iloc[-1]
        rsi_15m = df_15m['rsi'].iloc[-1]
        atr_15m = df_15m['atr'].iloc[-1]
        ema20_15m = df_15m['ema20'].iloc[-1]
        ema50_15m = df_15m['ema50'].iloc[-1]
        
        rsi_1h = df_1h['rsi'].iloc[-1]
        atr_1h = df_1h['atr'].iloc[-1]
        ema20_1h = df_1h['ema20'].iloc[-1]
        ema50_1h = df_1h['ema50'].iloc[-1]
        
        ema_diff_pct = ((ema20_15m - ema50_15m) / ema50_15m) * 100
        ema_trend = 'ALCISTA (EMA20 > EMA50)' if ema20_15m > ema50_15m else 'BAJISTA (EMA20 < EMA50)'
        
        pos = open_positions.get(sym, None)
        
        results[sym] = {
            'current_price': float(current_price),
            'funding_rate_pct': float(funding_rate_pct),
            '15m': {
                'rsi': float(rsi_15m),
                'atr': float(atr_15m),
                'ema20': float(ema20_15m),
                'ema50': float(ema50_15m),
                'ema_trend': ema_trend,
                'ema_diff_pct': float(ema_diff_pct)
            },
            '1h': {
                'rsi': float(rsi_1h),
                'atr': float(atr_1h),
                'ema20': float(ema20_1h),
                'ema50': float(ema50_1h)
            },
            'position': pos
        }
        
    final_output = {
        'balance_total': float(usdt_total),
        'free_balance': float(usdt_free),
        'open_positions_count': len(open_positions),
        'open_positions': open_positions,
        'market_analysis': results
    }
    
    print(json.dumps(final_output, indent=2))

if __name__ == '__main__':
    run_analysis()
