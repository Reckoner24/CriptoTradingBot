import pandas as pd
import pandas_ta as ta
import numpy as np
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def plot_realworld_trades(sym):
    cache_file = f"data/{sym.replace('/', '_')}_15m_25000.csv"
    if not os.path.exists(cache_file):
        print(f"No hay datos locales para {sym}")
        return
        
    df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
    df = df.tail(96 * 7) # Ultimos 7 días
    
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA20'] = ta.ema(df['close'], length=20)
    df.dropna(inplace=True)
    
    # Parámetros estáticos promedio
    grid_spacing_mult_l = 1.5
    tp_mult_l = 1.0
    sl_mult_l = 2.0
    grid_spacing_mult_s = 1.5
    tp_mult_s = 1.0
    sl_mult_s = 2.0
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    atr = df['ATR'].values
    ema20 = df['EMA20'].values
    timestamps = df.index
    
    n = len(df)
    i = 0
    trades = []
    
    while i < n - 1:
        current_atr = atr[i]
        
        spacing_l = current_atr * grid_spacing_mult_l
        entry_long = close[i] - spacing_l
        sl_long = entry_long - (current_atr * sl_mult_l)
        tp_long = entry_long + (spacing_l * tp_mult_l)
        
        spacing_s = current_atr * grid_spacing_mult_s
        entry_short = close[i] + spacing_s
        sl_short = entry_short + (current_atr * sl_mult_s)
        tp_short = entry_short - (spacing_s * tp_mult_s)
        
        long_active = False; short_active = False
        salida_l = None; salida_s = None
        exit_idx_l = i; exit_idx_s = i
        
        for j in range(1, 41):
            if i+j >= n: break
            curr_h = high[i+j]; curr_l = low[i+j]; curr_c = close[i+j]
            
            # --- LONG ---
            if not long_active:
                if curr_l <= entry_long:
                    long_active = True
                    if curr_h >= tp_long and curr_l <= sl_long:
                        salida_l = sl_long; exit_idx_l = i+j
                    elif curr_l <= sl_long:
                        salida_l = sl_long; exit_idx_l = i+j
                    elif curr_h >= tp_long:
                        salida_l = tp_long; exit_idx_l = i+j
            else:
                if salida_l is None:
                    if curr_h >= tp_long and curr_l <= sl_long:
                        salida_l = sl_long; exit_idx_l = i+j
                    elif curr_l <= sl_long:
                        salida_l = sl_long; exit_idx_l = i+j
                    elif curr_h >= tp_long:
                        salida_l = tp_long; exit_idx_l = i+j
                    elif j == 20:
                        if curr_c <= ema20[i+j]: salida_l = curr_c; exit_idx_l = i+j
                    elif j == 40:
                        salida_l = curr_c; exit_idx_l = i+j
                        
            # --- SHORT ---
            if not short_active:
                if curr_h >= entry_short:
                    short_active = True
                    if curr_l <= tp_short and curr_h >= sl_short:
                        salida_s = sl_short; exit_idx_s = i+j
                    elif curr_h >= sl_short:
                        salida_s = sl_short; exit_idx_s = i+j
                    elif curr_l <= tp_short:
                        salida_s = tp_short; exit_idx_s = i+j
            else:
                if salida_s is None:
                    if curr_l <= tp_short and curr_h >= sl_short:
                        salida_s = sl_short; exit_idx_s = i+j
                    elif curr_h >= sl_short:
                        salida_s = sl_short; exit_idx_s = i+j
                    elif curr_l <= tp_short:
                        salida_s = tp_short; exit_idx_s = i+j
                    elif j == 20:
                        if curr_c >= ema20[i+j]: salida_s = curr_c; exit_idx_s = i+j
                    elif j == 40:
                        salida_s = curr_c; exit_idx_s = i+j
            
            if (not long_active or salida_l is not None) and (not short_active or salida_s is not None):
                break
                
        if long_active and salida_l is not None:
            trades.append({'time': timestamps[exit_idx_l], 'entry': entry_long, 'exit': salida_l, 'type': 'L', 'win': salida_l > entry_long})
        if short_active and salida_s is not None:
            trades.append({'time': timestamps[exit_idx_s], 'entry': entry_short, 'exit': salida_s, 'type': 'S', 'win': salida_s < entry_short})
            
        max_exit = i
        if long_active and salida_l is not None: max_exit = max(max_exit, exit_idx_l)
        if short_active and salida_s is not None: max_exit = max(max_exit, exit_idx_s)
        i = max_exit if max_exit > i else i + 1

    # Plotting
    fig, ax = plt.subplots(figsize=(15, 8))
    ax.plot(df.index, df['close'], color='#aaaaaa', linewidth=1.5, label='Precio SOL/USDT', zorder=1)
    
    # EMA20
    ax.plot(df.index, df['EMA20'], color='#ffff00', linewidth=1, alpha=0.5, label='Tendencia EMA20', zorder=1)
    
    l_entries_t = [t['time'] for t in trades if t['type'] == 'L']
    l_entries_p = [t['entry'] for t in trades if t['type'] == 'L']
    s_entries_t = [t['time'] for t in trades if t['type'] == 'S']
    s_entries_p = [t['entry'] for t in trades if t['type'] == 'S']
    
    win_t = [t['time'] for t in trades if t['win']]
    win_p = [t['exit'] for t in trades if t['win']]
    loss_t = [t['time'] for t in trades if not t['win']]
    loss_p = [t['exit'] for t in trades if not t['win']]
    
    ax.scatter(l_entries_t, l_entries_p, color='#00ffff', marker='^', s=120, label='Apertura Long', zorder=2)
    ax.scatter(s_entries_t, s_entries_p, color='#ff00ff', marker='v', s=120, label='Apertura Short', zorder=2)
    ax.scatter(win_t, win_p, color='#00ff00', marker='o', s=80, label='Take Profit', zorder=3)
    ax.scatter(loss_t, loss_p, color='#ff0000', marker='x', s=80, label='Stop Loss / Smart Close', zorder=3)
        
    ax.set_title(f"Mapeo de Zonas - Grid Bidireccional Real-World ({sym})", color='white', fontsize=16)
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    plt.xticks(rotation=45)
    plt.legend(facecolor='#1e1e1e', edgecolor='white', labelcolor='white')
    
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/realworld_trades_map_{sym.replace('/','_')}.png", dpi=100, bbox_inches='tight')

def main():
    for sym in ['SOL/USDT', 'BTC/USDT', 'ETH/USDT']:
        plot_realworld_trades(sym)

if __name__ == "__main__":
    main()
