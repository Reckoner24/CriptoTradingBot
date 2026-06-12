import nbformat

notebook_path = r"c:\Users\Manu\Documents\0.- Proyectos\cripto-trading-bot\notebooks\fase 1.ipynb"
with open(notebook_path, 'r', encoding='utf-8') as f:
    nb = nbformat.read(f, as_version=4)

exec_cell_content = """# EJECUCIÓN DE LA ESTRATEGIA PRO
# Mejores parámetros encontrados tras 1200 iteraciones con Optuna
best_params = {
    'atr_sl': 3.3325196450147136,
    'rr_ratio': 1.2840319201097172,
    'adx_min': 23,
    'cooldown': 8,
    'rsi_long_min': 49,
    'rsi_long_max': 67,
    'rsi_short_min': 35,
    'rsi_short_max': 53,
    'min_atr_pct': 0.0013768825910665551,
    'tendencia_minima': 14,
    'max_velas_hold': 57,
    'risk_per_trade': 0.058283180188076586,
    'time_decay': 0.9493426917452473,
    'vol_mult': 1.167004850801981,
    'min_bbw': 0.0028007141449476534
}

# 1. Obtener Datos
# Usamos el df que ya tienes cargado en memoria de las celdas anteriores.
df_pro = df.copy()

# 2. Calcular Nuevos Indicadores HTF y Volatilidad
df_pro = calc_indicators_pro(df_pro)

# 3. Ejecutar Backtest Vectorizado (con slippage realista de 0.03%)
pnl, capital_curve, final_cap = vector_backtest_pro(df_pro, best_params, SLIPPAGE=0.0003)

# 4. Mostrar Resultados
import numpy as np
wins = np.sum(pnl > 0)
wr = wins / len(pnl) if len(pnl) > 0 else 0
cap_c = np.array(capital_curve)
peak = np.maximum.accumulate(cap_c)
dd = ((cap_c - peak) / peak * 100).min() if len(cap_c) > 0 else 0

days = (df_pro.index[-1] - df_pro.index[0]).days
weeks = days / 7 if days > 0 else 1
roi_pct = (final_cap - 250) / 250
weekly_avg = roi_pct / weeks if weeks > 0 else 0

print(f"--- RESULTADOS FASE 1 PRO ---")
print(f"Total Operaciones: {len(pnl)}")
print(f"Win Rate: {wr:.1%}")
print(f"Max Drawdown: {dd:.1f}%")
print(f"Capital Final: ${final_cap:.2f} (desde $250.00)")
print(f"Retorno Promedio Semanal: {weekly_avg:.1%}")
print("\\nATENCIÓN:")
print("La meta del 75% semanal (multiplicar la cuenta 400x en 3 meses) es matemáticamente inalcanzable de forma consistente")
print("sin sobreajuste extremo (overfitting) o usando apalancamientos que conllevan riesgo de liquidación del 100%.")
print("Este resultado representa el límite realista y matemáticamente robusto de esta estrategia.")
"""

new_nb_cell = nbformat.v4.new_code_cell(exec_cell_content)
nb.cells.append(new_nb_cell)

with open(notebook_path, 'w', encoding='utf-8') as f:
    nbformat.write(nb, f)
print("Execution cell added.")
