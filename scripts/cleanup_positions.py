"""
Script de Limpieza de Posiciones y Órdenes Abiertas.
Cancela todas las órdenes flotantes y cierra a mercado cualquier posición abierta en Binance Futures.
"""
import sys
import os
from pathlib import Path

# Configurar sys.path para importar correctamente desde el proyecto
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
os.chdir(str(root_dir))

from dotenv import load_dotenv
load_dotenv()

from scripts.dgt_bot import get_exchange, SYMBOLS

def cleanup_all():
    print("=" * 60)
    print("INICIANDO LIMPIEZA DE CUENTA EN BINANCE FUTURES")
    print("=" * 60)

    ex = get_exchange()
    
    # 1. Cancelar todas las órdenes abiertas para los símbolos objetivo
    print("\n--- 1. Cancelando Órdenes Abiertas ---")
    for sym in SYMBOLS:
        try:
            open_orders = ex.fetch_open_orders(sym)
            if open_orders:
                print(f"[{sym}] Cancelando {len(open_orders)} órdenes abiertas...")
                ex.cancel_all_orders(sym)
                print(f"[{sym}] Órdenes canceladas con éxito.")
            else:
                print(f"[{sym}] No hay órdenes abiertas.")
        except Exception as e:
            print(f"[{sym}] Error al cancelar órdenes: {e}")

    # 2. Consultar balance y posiciones abiertas
    print("\n--- 2. Cerrando Posiciones Abiertas a Mercado ---")
    bal = ex.fetch_balance()
    positions = bal.get('info', {}).get('positions', [])
    open_pos = [p for p in positions if abs(float(p.get('positionAmt', 0))) > 0]

    if not open_pos:
        print("No se encontraron posiciones abiertas en la cuenta.")
    else:
        for p in open_pos:
            sym_raw = p.get('symbol')
            amt = float(p.get('positionAmt', 0))
            
            # Mapear símbolo raw (ej. BTCUSDT) a formato CCXT (ej. BTC/USDT)
            sym = sym_raw
            if not '/' in sym:
                if sym.endswith('USDT'):
                    sym = f"{sym[:-4]}/USDT"
            
            side = "LONG" if amt > 0 else "SHORT"
            close_side = "sell" if side == "LONG" else "buy"
            close_amt = abs(amt)
            
            print(f"Cerrando posición [{sym}] {side} de cantidad {close_amt}...")
            try:
                if close_side == "sell":
                    ex.create_market_sell_order(sym, close_amt, {'reduceOnly': True})
                else:
                    ex.create_market_buy_order(sym, close_amt, {'reduceOnly': True})
                print(f"[{sym}] Posición {side} cerrada exitosamente.")
            except Exception as e:
                print(f"[{sym}] Error al cerrar posición {side}: {e}")

    # 3. Estado final de la cuenta
    bal_after = ex.fetch_balance()
    wallet_usdt = bal_after['total'].get('USDT', 0)
    free_usdt = bal_after['free'].get('USDT', 0)
    
    print("\n" + "=" * 60)
    print("ESTADO FINAL DE LA CUENTA")
    print(f"Wallet Balance (USDT): ${wallet_usdt:.2f}")
    print(f"Free Margin (USDT):    ${free_usdt:.2f}")
    print("=" * 60)

if __name__ == "__main__":
    cleanup_all()
