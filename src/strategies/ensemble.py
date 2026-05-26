"""マルチAI合議制戦略 (アンサンブル)

複数の戦略を「専門家」とみなし、各自の判断を重み付きで集約して最終判断する。
全員一致なら強いシグナル、意見が割れれば見送り — ダマシを減らしリスクを分散する。

合議ルール:
  - 各メンバーの buy/sell シグナルを weight × confidence で加点
  - 買い: buy票数 >= min_agreement かつ 加重buyスコア >= buy_threshold
  - 売り(保有銘柄): 加重sellスコア >= sell_threshold または sell票数 >= min_agreement
"""
from __future__ import annotations
import pandas as pd
from .base import Strategy, Signal


class EnsembleStrategy(Strategy):
    name = "ensemble"

    def __init__(self, all_params: dict | None = None):
        all_params = all_params or {}
        ens = all_params.get("ensemble", {})
        super().__init__(ens)
        self.member_names: list[str] = ens.get(
            "members", ["technical", "ml", "fundamental"])
        self.weights: dict[str, float] = ens.get("weights", {})
        self.buy_threshold = ens.get("buy_threshold", 1.2)
        self.sell_threshold = ens.get("sell_threshold", 0.8)
        self.min_agreement = ens.get("min_agreement", 2)

        # メンバー戦略を生成 (循環import回避のため遅延import)
        from . import build_strategy
        self.members: dict[str, Strategy] = {}
        for m in self.member_names:
            if m == "ensemble":
                continue  # 自己参照は無視
            self.members[m] = build_strategy(m, all_params)

    def warmup_days(self) -> int:
        return max((m.warmup_days() for m in self.members.values()), default=60)

    def generate_signals(
        self,
        date: pd.Timestamp,
        price_history: dict[str, pd.DataFrame],
        held_tickers: set[str],
    ) -> list[Signal]:
        # ticker -> [(member, action, confidence, weight), ...]
        votes: dict[str, list[tuple]] = {}
        for mname, m in self.members.items():
            w = float(self.weights.get(mname, 1.0))
            try:
                msigs = m.generate_signals(date, price_history, held_tickers)
            except Exception as e:
                print(f"[ensemble] {mname} 失敗: {e}")
                continue
            for s in msigs:
                votes.setdefault(s.ticker, []).append(
                    (mname, s.action, s.confidence, w))

        n_members = max(1, len(self.members))
        signals: list[Signal] = []
        for ticker, vlist in votes.items():
            buy_score = sum(c * w for (_, a, c, w) in vlist if a == "buy")
            sell_score = sum(c * w for (_, a, c, w) in vlist if a == "sell")
            n_buy = sum(1 for (_, a, _, _) in vlist if a == "buy")
            n_sell = sum(1 for (_, a, _, _) in vlist if a == "sell")
            detail = ", ".join(f"{m}:{a}({c:.2f})" for (m, a, c, _) in vlist)

            if ticker not in held_tickers:
                if n_buy >= self.min_agreement and buy_score >= self.buy_threshold:
                    conf = min(1.0, buy_score / n_members)
                    signals.append(Signal(
                        ticker, "buy", confidence=conf,
                        reason=f"合議buy {n_buy}/{n_members} [{detail}]"))
            else:
                if sell_score >= self.sell_threshold or n_sell >= self.min_agreement:
                    conf = min(1.0, sell_score / n_members) if sell_score else 0.6
                    signals.append(Signal(
                        ticker, "sell", confidence=conf,
                        reason=f"合議sell {n_sell}/{n_members} [{detail}]"))
        return signals
