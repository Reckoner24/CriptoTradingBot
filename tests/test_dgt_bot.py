import pytest
from unittest.mock import MagicMock
from scripts.dgt_bot import DGTBot

def test_dgt_bot_capital_cap_enforced():
    mock_ex = MagicMock()
    # Exchange balance is $5,000 USDT
    mock_ex.fetch_balance.return_value = {'total': {'USDT': 5000.0}, 'free': {'USDT': 5000.0}}
    
    bot = DGTBot(mock_ex)
    bot.setup()
    
    # Capital per symbol must be capped at $250 / 3 = $83.333... even though wallet has $5000!
    cap = bot._current_capital('BTC/USDT')
    assert cap == pytest.approx(83.3333, abs=0.01)

def test_dgt_bot_place_grid_orders_safety():
    mock_ex = MagicMock()
    mock_ex.fetch_balance.return_value = {'total': {'USDT': 1000.0}, 'free': {'USDT': 1000.0}}
    mock_ex.fetch_ticker.return_value = {'last': 50000.0}
    mock_ex.market.return_value = {'precision': {'price': 0.1}}
    mock_ex.amount_to_precision.side_effect = lambda sym, amt: str(round(amt, 4))
    mock_ex.create_limit_buy_order.return_value = {'id': 'buy-123'}
    mock_ex.create_limit_sell_order.return_value = {'id': 'sell-123'}

    bot = DGTBot(mock_ex)
    bot.setup()

    # Stub ATR calculation
    import scripts.dgt_bot
    scripts.dgt_bot.calc_atr = lambda ex, sym, period: 500.0

    res = bot.place_grid_orders('BTC/USDT')
    assert res is True

    # Check that create_limit_buy_order was called for buy levels below center
    assert mock_ex.create_limit_buy_order.called
    
    # Check that NO sell orders were placed before any buy filled!
    assert mock_ex.create_limit_sell_order.call_count == 0

def test_dgt_bot_process_fills_places_tp_sell_with_reduce_only():
    mock_ex = MagicMock()
    mock_ex.fetch_balance.return_value = {'total': {'USDT': 1000.0}, 'free': {'USDT': 1000.0}}
    mock_ex.fetch_ticker.return_value = {'last': 49000.0}
    mock_ex.market.return_value = {'precision': {'price': 0.1}}
    mock_ex.amount_to_precision.side_effect = lambda sym, amt: str(round(float(amt), 4))
    mock_ex.create_limit_buy_order.return_value = {'id': 'buy-1'}
    mock_ex.create_limit_sell_order.return_value = {'id': 'sell-tp-1'}
    mock_ex.fetch_open_orders.return_value = [] # Order filled!
    mock_ex.fetch_order.return_value = {'status': 'closed', 'filled': 0.001, 'amount': 0.001}

    bot = DGTBot(mock_ex)
    bot.setup()

    import scripts.dgt_bot
    scripts.dgt_bot.calc_atr = lambda ex, sym, period: 500.0
    bot.place_grid_orders('BTC/USDT')

    # Simulate buy fill in process_fills
    bot.process_fills('BTC/USDT')

    # Verify that Take-Profit sell orders were created with reduceOnly=True
    assert mock_ex.create_limit_sell_order.called
    for call in mock_ex.create_limit_sell_order.call_args_list:
        args, kwargs = call
        assert kwargs.get('params') == {'reduceOnly': True} or (len(args) >= 4 and args[3] == {'reduceOnly': True})


def test_dgt_bot_exposure_cap_blocks_new_buys_when_position_already_at_cap():
    """Regression test for the 2026-08-14 incident: positions accumulated far beyond
    capital*leverage because nothing capped aggregate exposure before adding more orders."""
    import scripts.dgt_bot
    scripts.dgt_bot.send_telegram_alert = lambda *a, **k: None
    scripts.dgt_bot.calc_atr = lambda ex, sym, period: 500.0

    mock_ex = MagicMock()
    # Ya hay una posición real en Binance que consume TODO el presupuesto (capital_per_sym * leverage)
    mock_ex.fetch_balance.return_value = {
        'total': {'USDT': 1000.0}, 'free': {'USDT': 1000.0},
        'info': {'positions': [
            {'symbol': 'BTCUSDT', 'positionAmt': '0.02', 'entryPrice': '50000.0', 'notional': '900.0'}
        ]}
    }
    mock_ex.fetch_ticker.return_value = {'last': 50000.0}
    mock_ex.market.return_value = {'precision': {'price': 0.1}}
    mock_ex.amount_to_precision.side_effect = lambda sym, amt: str(round(amt, 4))

    bot = DGTBot(mock_ex)
    bot.setup()  # capital_per_sym = 250/3 ≈ 83.33 -> max_notional = 83.33 * leverage, ya excedido por los $900 "reales"

    bot.place_grid_orders('BTC/USDT')

    assert mock_ex.create_limit_buy_order.call_count == 0


def test_dgt_bot_fill_detection_does_not_assume_fill_on_error():
    """Regression test: an exception while checking order status must NOT be treated as a fill
    (previously `except Exception: is_closed = True` could fabricate phantom fills/TP orders)."""
    import scripts.dgt_bot
    scripts.dgt_bot.send_telegram_alert = lambda *a, **k: None
    scripts.dgt_bot.calc_atr = lambda ex, sym, period: 500.0
    scripts.dgt_bot.check_manual_reset = lambda sym: False

    mock_ex = MagicMock()
    mock_ex.fetch_balance.return_value = {'total': {'USDT': 1000.0}, 'free': {'USDT': 1000.0}}
    mock_ex.fetch_ticker.return_value = {'last': 50000.0}
    mock_ex.market.return_value = {'precision': {'price': 0.1}}
    mock_ex.amount_to_precision.side_effect = lambda sym, amt: str(round(amt, 4))
    mock_ex.create_limit_buy_order.return_value = {'id': 'buy-123'}

    bot = DGTBot(mock_ex)
    bot.setup()
    bot.place_grid_orders('BTC/USDT')

    # La orden ya no aparece entre las abiertas, y consultarla falla transitoriamente
    mock_ex.fetch_open_orders.return_value = []
    mock_ex.fetch_order.side_effect = Exception("timeout")

    bot.process_fills('BTC/USDT')

    assert mock_ex.create_limit_sell_order.call_count == 0
    assert not bot.state['BTC/USDT']['buys_filled']


def test_dgt_bot_recovers_orphan_position_for_stop_loss():
    """Regression test: on restart, a position Binance already holds must be tracked for
    stop-loss immediately, instead of the bot starting blind to it (as in the incident,
    where a pm2 restart wiped buy_entries while a real position stayed open)."""
    import scripts.dgt_bot
    scripts.dgt_bot.send_telegram_alert = lambda *a, **k: None

    mock_ex = MagicMock()
    mock_ex.fetch_balance.return_value = {
        'total': {'USDT': 1000.0}, 'free': {'USDT': 1000.0},
        'info': {'positions': [
            {'symbol': 'BTCUSDT', 'positionAmt': '0.01', 'entryPrice': '60000.0', 'notional': '600.0'}
        ]}
    }
    mock_ex.fetch_funding_rate.side_effect = Exception("n/a")

    bot = DGTBot(mock_ex)
    bot.setup()

    assert bot.state['BTC/USDT']['buy_entries'].get(-1) == pytest.approx(60000.0)


def test_dgt_bot_reset_kill_switch_pauses_symbol_after_repeated_boundary_breaks():
    """Regression test: the live incident had 20 forced market-closes in ~36h because nothing
    stopped the bot from resetting the grid indefinitely when it doesn't fit current volatility."""
    import scripts.dgt_bot
    scripts.dgt_bot.send_telegram_alert = lambda *a, **k: None
    scripts.dgt_bot.calc_atr = lambda ex, sym, period: 500.0
    scripts.dgt_bot.check_manual_reset = lambda sym: False

    mock_ex = MagicMock()
    mock_ex.fetch_balance.return_value = {'total': {'USDT': 1000.0}, 'free': {'USDT': 1000.0}}
    mock_ex.market.return_value = {'precision': {'price': 0.1}}
    mock_ex.amount_to_precision.side_effect = lambda sym, amt: str(round(amt, 4))
    mock_ex.fetch_open_orders.return_value = []

    bot = DGTBot(mock_ex)
    bot.setup()

    # La grilla siempre se re-centra en 50000, pero process_fills siempre lee 1_000_000 al
    # entrar -> boundary break garantizado en cada ciclo (no solo una vez).
    import itertools
    mock_ex.fetch_ticker.side_effect = itertools.cycle([{'last': 50000.0}, {'last': 1_000_000.0}])
    bot.place_grid_orders('BTC/USDT')

    for _ in range(scripts.dgt_bot.MAX_RESETS_PER_WINDOW - 1):
        bot.process_fills('BTC/USDT')
    assert 'BTC/USDT' not in bot.paused_symbols

    bot.process_fills('BTC/USDT')
    assert 'BTC/USDT' in bot.paused_symbols


def test_dgt_bot_drawdown_kill_switch_pauses_trading():
    """Regression test: nothing stopped the bot from continuing to open new exposure while
    bleeding money all night. A daily-drawdown breach must pause new orders (existing positions
    keep their stop-loss)."""
    import scripts.dgt_bot
    scripts.dgt_bot.send_telegram_alert = lambda *a, **k: None

    mock_ex = MagicMock()
    mock_ex.fetch_balance.return_value = {'total': {'USDT': 1000.0}, 'free': {'USDT': 1000.0}}
    mock_ex.fetch_funding_rate.side_effect = Exception("n/a")

    bot = DGTBot(mock_ex)
    bot.setup()  # primer health_check fija start_balance = 1000

    assert bot.start_balance == pytest.approx(1000.0)
    assert bot.trading_paused is False

    # Cae muy por debajo del umbral configurado (DGT_MAX_DRAWDOWN_PCT)
    mock_ex.fetch_balance.return_value = {'total': {'USDT': 500.0}, 'free': {'USDT': 500.0}}
    bot.health_check()

    assert bot.trading_paused is True
