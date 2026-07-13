import pandas as pd
import pandas_ta as ta
import numpy as np
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def plot_trades(sym):
    cache_file = f"data/{sym.replace('/', '_')}_15m_25000.csv"
    if not os.path.exists(cache_file):
        print(f"No hay datos locales para {sym}")
        return
        
    df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
    # Tomar los últimos 7 días para que la gráfica sea legible
    df = df.tail(96 * 7) 
    
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df.fillna(0, inplace=True)
    
    # Parámetros promedio del WFO
    grid_spacing_mult = 1.5
    tp_mult = 1.0
    sl_mult = 2.0
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    atr = df['ATR'].values
    timestamps = df.index
    
    n = len(df)
    i = 0
    trades = []
    
    while i < n - 1:
        current_atr = atr[i]
        spacing = current_atr * grid_spacing_mult
        
        entry_price = close[i] - spacing
        sl_price = entry_price - (current_atr * sl_mult)
        tp_price = entry_price + (spacing * tp_mult)
        
        trade_active = False
        salida = None
        exit_idx = i
        
        for j in range(1, 20):
            if i+j >= n: break
            
            if not trade_active:
                if low[i+j] <= entry_price:
                    trade_active = True
                    if high[i+j] >= tp_price:
                        salida = tp_price; exit_idx = i+j; break
                    if low[i+j] <= sl_price:
                        salida = sl_price; exit_idx = i+j; break
            else:
                if high[i+j] >= tp_price:
                    salida = tp_price; exit_idx = i+j; break
                if low[i+j] <= sl_price:
                    salida = sl_price; exit_idx = i+j; break
                    
        if trade_active and salida is not None:
            trades.append({
                'entry_time': timestamps[exit_idx], # Aproximación visual
                'entry_price': entry_price,
                'exit_time': timestamps[exit_idx],
                'exit_price': salida,
                'is_win': salida >= entry_price
            })
            i = exit_idx + 1
        else:
            i += 1

    # Plot
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(df.index, df['close'], color='#aaaaaa', linewidth=1, label='Precio')
    
    buy_times = [t['entry_time'] for t in trades]
    buy_prices = [t['entry_price'] for t in trades]
    
    sell_times = [t['exit_time'] for t in trades if t['is_win']]
    sell_prices = [t['exit_price'] for t in trades if t['is_win']]
    
    loss_times = [t['exit_time'] for t in trades if not t['is_win']]
    loss_prices = [t['exit_price'] for t in trades if not t['is_win']]
    
    ax.scatter(buy_times, buy_prices, color='#00ffff', marker='^', s=100, label='Compra (Grid Hit)')
    ax.scatter(sell_times, sell_prices, color='#00ff00', marker='v', s=100, label='Venta (Take Profit)')
    if loss_times:
        ax.scatter(loss_times, loss_prices, color='#ff0000', marker='x', s=100, label='Stop Loss')
        
    ax.set_title(f"Zonas de Inversión Grid Trading (Últimos 7 Días) - {sym}", color='white', fontsize=16)
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    plt.xticks(rotation=45)
    plt.legend(facecolor='#1e1e1e', edgecolor='white', labelcolor='white')
    
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/grid_trades_{sym.replace('/','_')}.png", dpi=100, bbox_inches='tight')
    print(f"Gráfica generada para {sym}")

if __name__ == "__main__":
    for coin in ['SOL/USDT', 'BTC/USDT', 'ETH/USDT']:
        plot_trades(coin)
