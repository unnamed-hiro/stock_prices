import pandas as pd
from .config import AppConfig
from .portfolio import Portfolio
from .strategies.base import Strategy, Signal


def _close_on(df: pd.DataFrame, date: pd.Timestamp) -> float | None:
    if date in df.index:
        v = df.loc[date, "Close"]
        return float(v) if pd.notna(v) else None
    sub = df.loc[:date]
    return float(sub["Close"].iloc[-1]) if len(sub) else None


def _open_on(df: pd.DataFrame, date: pd.Timestamp) -> float | None:
    """指定日ちょうどの始値。約定用なので当日にバーが無ければ None (未約定)。"""
    if date in df.index:
        col = "Open" if "Open" in df.columns else "Close"
        v = df.loc[date, col]
        return float(v) if pd.notna(v) else None
    return None


def _plan_exits(
    portfolio: Portfolio,
    date: pd.Timestamp,
    closes: dict[str, float],
    stop_loss: float,
    take_profit: float,
    max_holding_days: int,
    trailing_stop: float = 0.0,
) -> list[dict]:
    """当日終値でリスク決済条件を判定し、決済すべき注文リストを返す(約定はしない)。
    peak_price を更新し、トレーリングストップ判定も行う。"""
    orders: list[dict] = []
    for ticker, pos in list(portfolio.positions.items()):
        px = closes.get(ticker)
        if px is None:
            continue
        # 取得後最高値を更新
        if px > pos.peak_price:
            pos.peak_price = px
        ret = (px - pos.entry_price) / pos.entry_price
        days = (date - pos.entry_date).days
        peak = pos.peak_price if pos.peak_price > 0 else pos.entry_price
        drop_from_peak = (px - peak) / peak
        reason = None
        if ret <= -stop_loss:
            reason = "stop_loss"
        elif trailing_stop > 0 and ret > 0 and drop_from_peak <= -trailing_stop:
            # 含み益がある状態で天井から trailing_stop 分下げたら利益確定
            reason = "trailing_stop"
        elif take_profit > 0 and ret >= take_profit:
            reason = "take_profit"
        elif days >= max_holding_days:
            reason = "max_holding"
        if reason:
            orders.append({"side": "sell", "ticker": ticker, "reason": reason})
    return orders


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


def _execute_orders(
    pf: Portfolio,
    orders: list[dict],
    fill_prices: dict[str, float],
    date: pd.Timestamp,
    config: AppConfig,
):
    """注文リストを fill_prices(始値 or 終値)で約定する。
    サイズは約定時の資産・現金で計算するため、翌日約定でも現金整合が取れる。"""
    risk = config.risk
    univ_max = config.universe.max_positions
    # 売り(決済)を先に処理して現金を確保
    for o in [x for x in orders if x["side"] == "sell"]:
        px = fill_prices.get(o["ticker"])
        if px is not None and o["ticker"] in pf.positions:
            pf.sell(o["ticker"], px, date)
    # 買いは信頼度順
    buys = sorted([x for x in orders if x["side"] == "buy"], key=lambda x: -x.get("confidence", 0))
    base_equity = pf.total_equity(fill_prices) if getattr(risk, "size_on_equity", True) else None
    for o in buys:
        if o["ticker"] in pf.positions:
            continue
        if len(pf.positions) >= univ_max:
            break
        px = fill_prices.get(o["ticker"])
        if px is None:
            continue
        shares = _size_position(pf, px, risk.position_size_pct,
                                risk.min_cash_reserve_pct, base_equity)
        if shares > 0:
            pf.buy(o["ticker"], px, shares, date)


def compute_benchmark(
    price_data: dict[str, pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
    initial_capital: float,
) -> dict:
    """全銘柄を等金額でバイ&ホールドした場合の成績 (市場ベンチマーク)。
    戦略がこれを上回れば α (超過リターン) がプラス。"""
    tickers = []
    for t, df in price_data.items():
        sub = df.loc[start:end]
        if len(sub) >= 2:
            tickers.append(t)
    if not tickers:
        return {"total_return_pct": 0.0, "final_equity": initial_capital}
    alloc = initial_capital / len(tickers)
    final = 0.0
    for t in tickers:
        sub = price_data[t].loc[start:end]
        entry = float(sub["Close"].iloc[0])
        exit_ = float(sub["Close"].iloc[-1])
        if entry > 0:
            final += alloc * (exit_ / entry)
    return {
        "total_return_pct": (final / initial_capital - 1) * 100,
        "final_equity": final,
        "n_tickers": len(tickers),
    }


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
    execution = getattr(config.simulation, "execution", "next_open")
    pending: list[dict] = []

    for i, date in enumerate(all_dates):
        closes = {t: _close_on(df, date) for t, df in price_data.items()}
        closes = {t: p for t, p in closes.items() if p is not None}
        opens = {t: _open_on(df, date) for t, df in price_data.items()}
        opens = {t: p for t, p in opens.items() if p is not None}

        # 1) 前日に出した注文を「当日の始値」で約定 (先読み排除)
        if execution == "next_open" and pending:
            _execute_orders(pf, pending, opens, date, config)
            pending = []

        # 2) 当日終値でリスク決済条件を判定 (トレーリングストップ含む)
        exit_orders = _plan_exits(pf, date, closes,
                                  risk.stop_loss_pct, risk.take_profit_pct,
                                  risk.max_holding_days,
                                  getattr(risk, "trailing_stop_pct", 0.0))
        exited = {o["ticker"] for o in exit_orders}

        # 3) 当日終値までの情報で戦略シグナル生成
        held = set(pf.positions.keys())
        signals = strategy.generate_signals(date, price_data, held)
        honor_sell = getattr(risk, "honor_strategy_sell", True)
        sig_orders = []
        for s in signals:
            if s.action == "sell" and s.ticker in held and s.ticker not in exited:
                # honor_strategy_sell=False の場合、戦略の売りは無視しリスク決済に委ねる
                # (過剰売買を抑えトレンドに乗り続ける)
                if honor_sell:
                    sig_orders.append({"side": "sell", "ticker": s.ticker, "reason": s.reason})
            elif s.action == "buy" and s.ticker not in held:
                sig_orders.append({"side": "buy", "ticker": s.ticker,
                                   "confidence": s.confidence, "reason": s.reason})

        orders = exit_orders + sig_orders
        if execution == "close":
            # 旧来: 当日終値で即約定 (先読みあり・非推奨)
            _execute_orders(pf, orders, closes, date, config)
        else:
            # 既定: 翌営業日の始値で約定するようキュー
            pending = orders

        pf.record_equity(date, closes)

        if verbose and i % 20 == 0:
            eq = pf.total_equity(closes)
            print(f"  {date.date()} | equity={eq:>12,.0f} | cash={pf.cash:>12,.0f} | pos={len(pf.positions)}")

    return pf
