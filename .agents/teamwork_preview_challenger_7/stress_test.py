"""
Adversarial Stress Testing Suite for CriptoTradingBot
Author: Challenger 7 (Empirical Challenger)

Tests:
1. Parameter Sensitivity / Perturbation (fragility check)
2. Fee & Slippage Stress (0.08% to 0.30% round trip)
3. Regime Shift Sensitivity (High ER trend vs low ER range)
4. Parameter Decay / Stale Parameter Impact
"""

import sys
import importlib.util
from pathlib import Path
import pandas as pd
import numpy as np
import optuna

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from parity_check_24h import fetch_data, prepare_data
from core.replay_engine import run_live_replay

spec = importlib.util.spec_from_file_location('bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot
spec.loader.exec_module(bot)

def run_stress_tests():
    print("=== STARTING ADVERSARIAL STRESS TEST SUITE ===")
    results = {}
    
    # 1. Fetch data for BTC/USDT (last 960 bars = 10 days)
    df_btc = prepare_data(fetch_data('BTC/USDT', '15m', limit=960))
    df_sol = prepare_data(fetch_data('SOL/USDT', '15m', limit=960))
    
    base_params = {
        'grid_spacing_mult_l': 1.0,
        'tp_mult_l': 2.0,
        'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 1.0,
        'tp_mult_s': 2.0,
        'sl_mult_s': 1.0,
        'risk_pct': 0.05,
    }
    
    # Test 1: Slippage & Fee Degradation
    print("\n--- TEST 1: Fee & Slippage Stress (BTC/USDT 10 days) ---")
    fee_results = []
    for fee in [0.0008, 0.0012, 0.0016, 0.0024]:
        for slippage in [0.0, 0.0005, 0.0010, 0.0020]:
            cap, trades = run_live_replay(
                df_btc, base_params, initial_balance=250.0, leverage=3,
                cap_per_trade=0.45, cap_total=0.85,
                fee_round_trip=fee, min_tp_distance_pct=3*fee,
                max_adx=25.0, slippage_pct=slippage,
                trend_filter=True, er_max=0.20, er_period=20
            )
            pnl = cap - 250.0
            fee_results.append({
                'fee_pct': fee*100,
                'slippage_pct': slippage*100,
                'final_cap': cap,
                'pnl': pnl,
                'trades': len(trades)
            })
            print(f"Fee {fee*100:.2f}% | Slip {slippage*100:.2f}% -> PnL: {pnl:+.2f} USD ({len(trades)} trades)")
    results['fee_stress'] = fee_results

    # Test 2: Parameter Sensitivity Perturbation
    print("\n--- TEST 2: Parameter Sensitivity Perturbation (+/- 15%, +/- 30%) ---")
    param_pert_results = []
    base_cap, _ = run_live_replay(
        df_btc, base_params, initial_balance=250.0, leverage=3,
        cap_per_trade=0.45, cap_total=0.85,
        fee_round_trip=0.0008, min_tp_distance_pct=0.0024,
        max_adx=25.0, slippage_pct=0.0005,
        trend_filter=True, er_max=0.20, er_period=20
    )
    print(f"Base Parameters PnL: {base_cap - 250.0:+.2f} USD")
    
    for factor in [0.70, 0.85, 1.00, 1.15, 1.30]:
        pert_params = {k: v * factor if k != 'risk_pct' else v for k, v in base_params.items()}
        cap, trades = run_live_replay(
            df_btc, pert_params, initial_balance=250.0, leverage=3,
            cap_per_trade=0.45, cap_total=0.85,
            fee_round_trip=0.0008, min_tp_distance_pct=0.0024,
            max_adx=25.0, slippage_pct=0.0005,
            trend_filter=True, er_max=0.20, er_period=20
        )
        pnl = cap - 250.0
        param_pert_results.append({'factor': factor, 'pnl': pnl, 'trades': len(trades)})
        print(f"Factor {factor*100:3.0f}% -> PnL: {pnl:+.2f} USD ({len(trades)} trades)")
    results['param_perturbation'] = param_pert_results

    # Test 3: Regime Shift (Efficiency Ratio ER threshold sensitivity)
    print("\n--- TEST 3: ER Regime Shift Filter Threshold (SOL/USDT 10 days) ---")
    er_results = []
    for er_threshold in [0.10, 0.15, 0.20, 0.25, 0.30, 0.99]: # 0.99 = no trend filter
        cap, trades = run_live_replay(
            df_sol, base_params, initial_balance=250.0, leverage=3,
            cap_per_trade=0.45, cap_total=0.85,
            fee_round_trip=0.0008, min_tp_distance_pct=0.0024,
            max_adx=25.0, slippage_pct=0.0005,
            trend_filter=(er_threshold < 0.90), er_max=er_threshold, er_period=20
        )
        pnl = cap - 250.0
        er_results.append({'er_threshold': er_threshold, 'pnl': pnl, 'trades': len(trades)})
        print(f"ER Max {er_threshold:.2f} -> PnL: {pnl:+.2f} USD ({len(trades)} trades)")
    results['er_regime_shift'] = er_results

    print("\n=== STRESS TEST COMPLETED ===")

if __name__ == '__main__':
    run_stress_tests()
