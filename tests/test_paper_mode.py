"""
Tests unitarios de la lógica PURA del modo PAPER de scripts/bot_live_bidirectional.py.

Solo cubren lógica que no requiere red ni exchange:
  (a) Flujo LONG paper de 100 USD abierto a 1000 y cerrado a 1010:
      - PaperExecutor simula los fills al precio actual (mid), sin comisión.
      - El PnL neto se calcula con la fórmula real del código
        (LiveTrader._finalize_close): pnl_usdt = size * (pnl_pct - 0.0008)
        = 100 * (0.01 - 0.0008) = 0.92 USDT.
  (b) EXECUTION_MODE por defecto es 'paper'.
  (c) Existen las constantes de caps de margen:
      MAX_MARGIN_PER_TRADE_PCT = 0.35 y MAX_TOTAL_MARGIN_PCT = 0.80.

El módulo se carga con importlib.util.spec_from_file_location para evitar
problemas de paquete (scripts/ no es un paquete importable).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_PATH = PROJECT_ROOT / "scripts" / "bot_live_bidirectional.py"

# Asegurar que el root del proyecto es importable (el bot importa core.*).
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Fee round-trip aplicado en la contabilidad paper (0.08%).
PAPER_FEE = 0.0008


def load_bot_module():
    """Carga scripts/bot_live_bidirectional.py como módulo aislado."""
    spec = importlib.util.spec_from_file_location("bot_live_bidirectional", BOT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bot_live_bidirectional"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bot():
    return load_bot_module()


def test_execution_mode_default_is_paper(monkeypatch):
    """(b) Sin EXECUTION_MODE en el entorno, el default debe ser 'paper'."""
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    # Neutralizar load_dotenv para que un EXECUTION_MODE del .env local no
    # contamine el default bajo test.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    module = load_bot_module()
    assert module.EXECUTION_MODE == "paper"


def test_margin_caps_constants(bot):
    """(c) Caps de margen: 35% por trade y 80% total."""
    assert bot.MAX_MARGIN_PER_TRADE_PCT == 0.35
    assert bot.MAX_TOTAL_MARGIN_PCT == 0.80


def test_paper_long_pnl_net_of_fee(bot):
    """(a) LONG paper: 100 USD @ 1000 -> cierre @ 1010 => pnl neto 0.92 USDT.

    Fórmula real del código (LiveTrader._finalize_close):
        pnl_pct  = (close - entry) / entry        = 0.01
        pnl_usdt = size_usd * (pnl_pct - 0.0008)  = 100 * 0.0092 = 0.92
    """
    # 1) Fills simulados al precio actual (mid) vía PaperExecutor, sin comisión.
    executor = bot.PaperExecutor(leverage=3, price_getter=lambda sym: 1010.0)

    opened = executor.open_position("BTC/USDT", "LONG", 100.0, 1000.0)
    assert opened["status"] == "success"
    assert opened["entry_price"] == pytest.approx(1000.0)
    assert opened["amount"] == pytest.approx(0.1)
    assert opened["size_usd"] == pytest.approx(100.0)

    closed = executor.close_position("BTC/USDT", "LONG", opened["amount"])
    assert closed["status"] == "success"
    assert closed["close_price"] == pytest.approx(1010.0)

    # 2) PnL neto con la fórmula real del código. LiveTrader se instancia con
    #    __new__ (sin __init__, que tocaría red/exchange) y se parchean
    #    sync_balance/save_state: _finalize_close queda como lógica pura.
    trader = bot.LiveTrader.__new__(bot.LiveTrader)
    trader.state = {
        "balance": 1000.0,
        "free_balance": 900.0,
        "positions": {
            "BTC/USDT": {
                "LONG": {
                    "entry_price": opened["entry_price"],
                    "size_usd": opened["size_usd"],
                    "amount": opened["amount"],
                }
            }
        },
        "history": [],
        "cooldowns": {},
        "wfo_data": {},
        "last_wfo_time": "",
    }
    trader.sync_balance = lambda: None
    trader.save_state = lambda: None

    pnl_usdt = trader._finalize_close(
        "BTC/USDT", "LONG",
        trader.state["positions"]["BTC/USDT"]["LONG"],
        closed["close_price"],
        reason="test",
    )

    size_usd = 100.0
    pnl_pct = (1010.0 - 1000.0) / 1000.0
    expected_pnl = size_usd * (pnl_pct - PAPER_FEE)  # 0.92

    assert pnl_usdt == pytest.approx(expected_pnl, abs=1e-9)
    # Contabilidad local PAPER: el balance del estado absorbe el PnL neto.
    assert trader.state["balance"] == pytest.approx(1000.0 + expected_pnl, abs=1e-9)
    # La posición cerrada se limpia del estado y queda registrada en el historial.
    assert "BTC/USDT" not in trader.state["positions"]
    assert trader.state["history"][-1]["pnl"] == pytest.approx(expected_pnl, abs=1e-9)
