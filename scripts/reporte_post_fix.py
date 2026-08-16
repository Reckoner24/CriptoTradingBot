"""
REPORTE DE RENDIMIENTO POST-FIX.

Mide el bot SOLO desde que se corrigieron los bugs (14-ago-2026 12:08 hora local),
para no contaminar la evaluacion con las perdidas que causaron los errores de codigo.

Que reporta:
  - esperanza por operacion (ganancia media vs perdida media) -- la metrica correcta
  - profit factor y payoff ratio
  - comision por operacion (para verificar que el cierre maker sigue funcionando)
  - balance y rendimiento acumulado desde el corte
  - cuantas operaciones faltan para que el resultado sea distinguible del azar

Uso:
    python scripts/reporte_post_fix.py
    python scripts/reporte_post_fix.py --dias 30
"""
import sys, os, argparse, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import warnings
warnings.filterwarnings('ignore')

import numpy as np
from dotenv import load_dotenv
import ccxt

from core.noise_gate import required_sample_size

load_dotenv(override=True)

# Corte: reinicio con el fix de apalancamiento (20x -> 10x) aplicado.
# Todo lo anterior refleja bugs ya corregidos y no debe mezclarse.
FIX_ISO = os.getenv('DGT_FIX_CUTOFF', '2026-08-14T18:08:00Z')   # UTC


def get_exchange():
    key = os.getenv('BINANCE_MAIN_KEY')
    secret = os.getenv('BINANCE_MAIN_SECRET')
    if not key or not secret:
        print("Faltan BINANCE_MAIN_KEY / BINANCE_MAIN_SECRET en .env")
        sys.exit(1)
    ex = ccxt.binance({'apiKey': key, 'secret': secret, 'enableRateLimit': True,
                       'options': {'defaultType': 'future'}, 'timeout': 30000})
    ex.options['recvWindow'] = 30000
    return ex


def fetch_income(ex, since_ms):
    """Pagina el historial de income (la API devuelve max 1000 por llamada)."""
    rows, cursor = [], since_ms
    now = ex.milliseconds()
    while cursor < now:
        batch = ex.fapiPrivateGetIncome({'startTime': cursor, 'limit': 1000})
        if not batch:
            break
        rows.extend(batch)
        last = int(batch[-1]['time'])
        if last <= cursor or len(batch) < 1000:
            break
        cursor = last + 1
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dias', type=int, default=None,
                    help='ventana hacia atras; por defecto usa el corte del fix')
    args = ap.parse_args()

    ex = get_exchange()
    fix_ms = ex.parse8601(FIX_ISO)
    since = ex.milliseconds() - args.dias*24*3600*1000 if args.dias else fix_ms

    rows = fetch_income(ex, min(since, fix_ms))
    pre = [r for r in rows if int(r['time']) < fix_ms]
    post = [r for r in rows if int(r['time']) >= fix_ms]

    def agg(rs, kind):
        return sum(float(r['income']) for r in rs if r['incomeType'] == kind)

    bal = ex.fetch_balance()
    equity = float(bal['total'].get('USDT', 0))

    pnl = [float(r['income']) for r in post if r['incomeType'] == 'REALIZED_PNL']
    comm_post = agg(post, 'COMMISSION')
    fund_post = agg(post, 'FUNDING_FEE')
    net_post = sum(pnl) + comm_post + fund_post

    fix_dt = datetime.datetime.fromtimestamp(fix_ms/1000)
    dias = (ex.milliseconds() - fix_ms) / (1000*3600*24)

    print("="*78)
    print(f"RENDIMIENTO POST-FIX  |  corte: {fix_dt:%Y-%m-%d %H:%M}  ({dias:.1f} dias)")
    print("="*78)

    if pre:
        net_pre = agg(pre,'REALIZED_PNL') + agg(pre,'COMMISSION') + agg(pre,'FUNDING_FEE')
        n_pre = sum(1 for r in pre if r['incomeType']=='REALIZED_PNL')
        print(f"  [referencia] antes del fix: ${net_pre:+.2f} en {n_pre} cierres")
        print()

    n = len(pnl)
    print(f"  Cierres desde el fix:    {n}")
    print(f"  PnL de trading:          ${sum(pnl):+.4f}")
    print(f"  Comisiones:              ${comm_post:+.4f}")
    print(f"  Funding:                 ${fund_post:+.4f}")
    print(f"  NETO:                    ${net_post:+.4f}")
    print(f"  Balance actual:          ${equity:.2f}")
    if equity - net_post > 0:
        print(f"  Rendimiento:             {net_post/(equity-net_post)*100:+.2f}%"
              f"  ({net_post/max(dias,0.1):+.3f} $/dia)")

    if n == 0:
        print("\n  Aun no hay cierres desde el corte. Vuelve a correr mas tarde.")
        return

    arr = np.array(pnl)
    wins, losses = arr[arr > 0], arr[arr < 0]
    exp = arr.mean()
    sd = arr.std(ddof=1) if n > 1 else 0.0
    t = exp/(sd/np.sqrt(n)) if sd > 0 else 0.0
    pf = (wins.sum()/abs(losses.sum())) if len(losses) and losses.sum() != 0 else float('inf')
    payoff = (wins.mean()/abs(losses.mean())) if len(wins) and len(losses) else float('inf')

    print("\n  " + "-"*74)
    print("  ESPERANZA (la metrica que decide, no el % de acierto)")
    print("  " + "-"*74)
    print(f"  Operaciones ganadoras:   {len(wins):3d}   media ${wins.mean() if len(wins) else 0:+.4f}")
    print(f"  Operaciones perdedoras:  {len(losses):3d}   media ${losses.mean() if len(losses) else 0:+.4f}")
    print(f"  Esperanza por operacion: ${exp:+.4f}")
    print(f"  Profit factor:           {pf:.2f}   (>1 = las ganancias superan las perdidas)")
    print(f"  Payoff ratio:            {payoff:.2f}   (ganancia media / perdida media)")
    print(f"  Acierto:                 {(arr>0).mean()*100:.1f}%   (descriptivo)")

    print("\n  " + "-"*74)
    print("  COSTOS  (verificacion de que el cierre maker sigue funcionando)")
    print("  " + "-"*74)
    n_comm = sum(1 for r in post if r['incomeType']=='COMMISSION')
    if n_comm:
        print(f"  Comision por cierre:     ${abs(comm_post)/max(n,1):.4f}"
              f"   (referencia pre-fix: $0.0830)")
        ratio = abs(comm_post)/abs(sum(pnl)) if sum(pnl) != 0 else float('inf')
        print(f"  Comision / PnL bruto:    {ratio:.2f}"
              f"   ({'las comisiones dominan' if ratio > 1 else 'el trading domina'})")

    print("\n  " + "-"*74)
    print("  SIGNIFICANCIA")
    print("  " + "-"*74)
    print(f"  t-stat de la esperanza:  {t:+.2f}   (>2 = distinguible del azar)")
    if sd > 0 and exp > 0:
        n_req = required_sample_size(exp, sd)
        print(f"  Operaciones necesarias:  {n_req:.0f}   (llevamos {n})")
        if n < n_req:
            faltan = n_req - n
            ritmo = n/max(dias,0.1)
            print(f"  Faltan ~{faltan:.0f} cierres"
                  f"{f' (~{faltan/ritmo:.0f} dias al ritmo actual)' if ritmo > 0 else ''}")
        else:
            print("  Muestra suficiente para concluir.")
    elif exp <= 0:
        print("  Esperanza negativa: no hay nada que confirmar todavia.")

    print("\n" + "="*78)
    if n < 30:
        print(f"  LECTURA: {n} operaciones es muestra insuficiente para concluir nada.")
        print("  El signo puede cambiar con los proximos cierres. Seguir midiendo.")
    elif t > 2 and exp > 0:
        print("  LECTURA: esperanza positiva y estadisticamente significativa.")
    elif exp > 0:
        print("  LECTURA: esperanza positiva pero aun no significativa. Seguir midiendo.")
    else:
        print("  LECTURA: esperanza negativa. El bot pierde dinero por operacion.")
    print("="*78)


if __name__ == '__main__':
    main()
