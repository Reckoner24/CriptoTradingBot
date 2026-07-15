class context:
    def __init__(self):
        self.SYMBOL = "BTCUSDT"
        self.TIMEFRAME = "15m"
        self.LEVERAGE = 3
        self.RISK_PER_TRADE_PCT = 0.01
        self.KELLY_FRACTION = 0.25
        self.ATR_PERIOD = 14
        self.ATR_MULTIPLIER_SL = 2.2
        self.RISK_REWARD_RATIO = 3.5
        self.ZSCORE_THRESHOLD = 1.3
        self.ADF_PVALUE_THRESHOLD = 0.10
        self.MAX_DAILY_LOSS_PCT = 0.03
        self.MAX_DRAWDOWN_PAUSE_PCT = 0.15
        self.MAX_DRAWDOWN_STOP_PCT = 0.25
        self.CONSECUTIVE_LOSSES_HALFSIZE = 3
        self.WFO_TRAIN_MONTHS = 6
        self.WFO_TEST_MONTHS = 2
        self.PAPER_TRADING_DAYS_REQUIRED = 30