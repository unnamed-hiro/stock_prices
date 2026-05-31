import pandas as pd
from .config import AppConfig
from .portfolio import Portfolio
from .strategies.base import Strategy, Signal


def _close_on(df: pd.DataFrame, date: pd.Timestamp) -> float | None:
    if date in df.index:
        return float(df.loc[date, "Close"])
    sub = df.loc[:date]
    return float(sub["Close"].iloc[-1]) if len(sub) else None


def _check_exits(
    portfolio: Portfolio,
    date: pd.Timestamp,
    prices: dict[str, float],
    stop_loss: float,
    take_profit: float,
    max_holding_days: int,
) -> list[str]:
    to_exit: list[tuple[str, str]] = []
    for ticker, pos in list(portfolio.positions.items()):
        px = prices.get(ticker)
        if px is None:
            continue
        ret = (px - pos.entry_price) / pos.entry_price
        days = (date - pos.entry_date).days
        if ret <= -stop_loss:
            to_exit.append((ticker, "stop_loss"))
        elif ret >= take_profit:
            to_exit.append((ticker, "take_profit"))
        elif days >= max_holding_days:
            to_exit.append((ticker, "max_holding"))
    reasons = []
    for ticker, reason in to_exit:
        if portfolio.sell(ticker, prices[ticker], date):
            reasons.append(f"{ticker}: {reason}")
    return reasons


def _size_position(
    portfolio: Portfolio,
    price: float,
    pct_per_position: float,
    min_cash_reserve_pct: float,
    base_equity: float | None = None,
) -> int:
    # base_equity を渡せば「現在の総資産」基準 (複利)、無ければ初期資金基準
    base = base_equity if base_equity is not None else portfolio.initial_capital
    target_yen = base * pct_per_position
    available = portfolio.cash - portfolio.initial_capital * min_cash_reserve_pct
    budget = min(target_yen, available)
    if budget <= 0 or price <= 0:
        return 0
    return int(budget // (price * 100)) * 100 if price * 100 <= budget else 0


def run_backtest(
    config: AppConfig,
    strategy: Strategy,
    price_data: dict[str, pd.DataFrame],
    verbose: bool = True,
) -> Portfolio:
    start = pd.Timestamp(config.simulation.start_date)
    end = pd.Timestamp(config.simulation.end_date)

    all_dates = sorted({d for df in price_data.values() for d in df.index if start <= d <= end})

    pf = Portfolio(
        initial_capital=config.simulation.initial_capital,
        commission_rate=config.simulation.commission_rate,
        slippage_rate=config.simulation.slippage_rate,
    )

    risk = config.risk
    univ_max = config.universe.max_positions

    for i, date in enumerate(all_dates):
        prices = {t: _close_on(df, date) for t, df in price_data.items()}
        prices = {t: p for t, p in prices.items() if p is not None}

        _check_exits(pf, date, prices,
                     risk.stop_loss_pct, risk.take_profit_pct, risk.max_holding_days)

        held = set(pf.positions.keys())
        signals = strategy.generate_signals(date, price_data, held)

        sells = [s for s in signals if s.action == "sell" and s.ticker in held]
        for s in sells:
            if s.ticker in prices:
                pf.sell(s.ticker, prices[s.ticker], date)

        buys = sorted([s for s in signals if s.action == "buy" and s.ticker not in pf.positions],
                      key=lambda x: -x.confidence)
        base_equity = pf.total_equity(prices) if getattr(risk, "size_on_equity", True) else None
        for s in buys:
            if len(pf.positions) >= univ_max:
                break
            px = prices.get(s.ticker)
            if px is None:
                continue
            shares = _size_position(pf, px, risk.position_size_pct,
                                    risk.min_cash_reserve_pct, base_equity)
            if shares > 0:
                pf.buy(s.ticker, px, shares, date)

        pf.record_equity(date, prices)

        if verbose and i % 20 == 0:
            eq = pf.total_equity(prices)
            print(f"  {date.date()} | equity={eq:>12,.0f} | cash={pf.cash:>12,.0f} | pos={len(pf.positions)}")

    return pf
