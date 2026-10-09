from dataclasses import dataclass, field
import pandas as pd


@dataclass
class Position:
    ticker: str
    shares: int
    entry_price: float
    entry_date: pd.Timestamp
    peak_price: float = 0.0   # 取得後の最高値 (トレーリングストップ用)


@dataclass
class Trade:
    ticker: str
    side: str
    shares: int
    price: float
    date: pd.Timestamp
    pnl: float = 0.0
    holding_days: int = 0


@dataclass
class Portfolio:
    initial_capital: float
    commission_rate: float = 0.001
    slippage_rate: float = 0.001
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[pd.Timestamp, float]] = field(default_factory=list)
    # 積立入金の累計 (リターン計算で「入金による増加」を利益と混同しないため)
    total_deposits: float = 0.0
    # 入金の履歴 [(date, amount)] — 日次リターン計算で入金日のジャンプを除去する
    deposit_log: list[tuple[pd.Timestamp, float]] = field(default_factory=list)

    def __post_init__(self):
        self.cash = self.initial_capital

    def deposit(self, amount: float, date: pd.Timestamp | None = None):
        """積立入金。現金と入金累計の両方に記録する。"""
        if amount <= 0:
            return
        self.cash += amount
        self.total_deposits += amount
        if date is not None:
            self.deposit_log.append((date, amount))

    @property
    def invested_capital(self) -> float:
        """投下資本合計 = 初期資金 + 積立入金累計"""
        return self.initial_capital + self.total_deposits

    def _exec_price(self, price: float, side: str) -> float:
        return price * (1 + self.slippage_rate) if side == "buy" else price * (1 - self.slippage_rate)

    def buy(self, ticker: str, price: float, shares: int, date: pd.Timestamp) -> bool:
        if shares <= 0:
            return False
        exec_price = self._exec_price(price, "buy")
        cost = exec_price * shares
        commission = cost * self.commission_rate
        total = cost + commission
        if total > self.cash:
            return False
        self.cash -= total
        if ticker in self.positions:
            pos = self.positions[ticker]
            new_shares = pos.shares + shares
            pos.entry_price = (pos.entry_price * pos.shares + exec_price * shares) / new_shares
            pos.shares = new_shares
        else:
            self.positions[ticker] = Position(ticker, shares, exec_price, date, peak_price=exec_price)
        self.trades.append(Trade(ticker, "buy", shares, exec_price, date))
        return True

    def sell(self, ticker: str, price: float, date: pd.Timestamp, shares: int | None = None) -> bool:
        if ticker not in self.positions:
            return False
        pos = self.positions[ticker]
        sell_shares = shares if shares else pos.shares
        sell_shares = min(sell_shares, pos.shares)
        exec_price = self._exec_price(price, "sell")
        proceeds = exec_price * sell_shares
        commission = proceeds * self.commission_rate
        net = proceeds - commission
        pnl = (exec_price - pos.entry_price) * sell_shares - commission
        holding_days = (date - pos.entry_date).days
        self.cash += net
        self.trades.append(Trade(ticker, "sell", sell_shares, exec_price, date, pnl, holding_days))
        if sell_shares >= pos.shares:
            del self.positions[ticker]
        else:
            pos.shares -= sell_shares
        return True

    def market_value(self, prices: dict[str, float]) -> float:
        return sum(prices.get(t, p.entry_price) * p.shares for t, p in self.positions.items())

    def total_equity(self, prices: dict[str, float]) -> float:
        return self.cash + self.market_value(prices)

    def record_equity(self, date: pd.Timestamp, prices: dict[str, float]):
        self.equity_curve.append((date, self.total_equity(prices)))
