"""ウォークフォワード検証 — 過剰最適化 (カーブフィッティング) の検出

全期間を N 個の連続ウィンドウに分割し、各ウィンドウで独立にバックテストする。
- 全ウィンドウで安定して市場に勝つ (α>0) 戦略 → 実力の可能性が高い
- 特定ウィンドウだけ大勝ちして他は負ける戦略 → まぐれ/過剰最適化の疑い

戦略はウィンドウごとに再生成する (ML戦略の学習状態がウィンドウを跨いで
漏れるのを防ぐ)。warmup 用の過去データは各ウィンドウ開始時点で既に存在した
履歴なので先読みには当たらない。
"""
from __future__ import annotations
import copy
from dataclasses import asdict
import pandas as pd

from .config import AppConfig
from .strategies import build_strategy
from .backtester import run_backtest, compute_benchmark
from .metrics import compute_metrics


def split_windows(start: pd.Timestamp, end: pd.Timestamp, n: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """[start, end] を n 個の等長・連続ウィンドウに分割する"""
    if n < 1:
        raise ValueError("n_windows must be >= 1")
    total_days = (end - start).days
    if total_days < n:
        raise ValueError("期間が短すぎてウィンドウ分割できません")
    edges = [start + pd.Timedelta(days=round(total_days * i / n)) for i in range(n + 1)]
    windows = []
    for i in range(n):
        w_start = edges[i] if i == 0 else edges[i] + pd.Timedelta(days=1)
        windows.append((w_start, edges[i + 1]))
    return windows


def run_walkforward(
    config: AppConfig,
    strategy_name: str,
    price_data: dict[str, pd.DataFrame],
    n_windows: int = 4,
    verbose: bool = False,
) -> dict:
    """ウィンドウごとに独立バックテストし、安定性サマリを返す"""
    start = pd.Timestamp(config.simulation.start_date)
    end = pd.Timestamp(config.simulation.end_date)
    windows = split_windows(start, end, n_windows)

    results: list[dict] = []
    for i, (w_start, w_end) in enumerate(windows, 1):
        cfg = copy.deepcopy(config)
        cfg.simulation.start_date = str(w_start.date())
        cfg.simulation.end_date = str(w_end.date())
        # 戦略はウィンドウごとに作り直す (学習状態の漏れ防止)
        strategy = build_strategy(strategy_name, cfg.strategy_params)
        pf = run_backtest(cfg, strategy, price_data, verbose=False)
        m = compute_metrics(pf)
        bench = compute_benchmark(price_data, w_start, w_end,
                                  cfg.simulation.initial_capital)
        alpha = m.total_return_pct - bench["total_return_pct"]
        row = {
            "window": i,
            "start": str(w_start.date()),
            "end": str(w_end.date()),
            "return_pct": m.total_return_pct,
            "benchmark_pct": bench["total_return_pct"],
            "alpha_pct": alpha,
            "sharpe": m.sharpe,
            "max_drawdown_pct": m.max_drawdown_pct,
            "n_sells": m.n_sells,
            "win_rate": m.win_rate,
        }
        results.append(row)
        if verbose:
            print(f"  window {i}/{n_windows} [{row['start']}〜{row['end']}] "
                  f"ret={row['return_pct']:+.1f}% α={alpha:+.1f}% "
                  f"sharpe={m.sharpe:.2f} trades={m.n_sells}")

    alphas = [r["alpha_pct"] for r in results]
    returns = [r["return_pct"] for r in results]
    n_alpha_pos = sum(1 for a in alphas if a > 0)
    n_ret_pos = sum(1 for r in returns if r > 0)
    summary = {
        "strategy": strategy_name,
        "n_windows": n_windows,
        "windows": results,
        "n_windows_alpha_positive": n_alpha_pos,
        "n_windows_return_positive": n_ret_pos,
        "worst_alpha_pct": min(alphas) if alphas else 0.0,
        "median_alpha_pct": float(pd.Series(alphas).median()) if alphas else 0.0,
        "consistent": n_alpha_pos == n_windows,
    }
    return summary


def format_walkforward(s: dict) -> str:
    lines = [
        "=" * 72,
        f"  ウォークフォワード検証  戦略: {s['strategy']}  ({s['n_windows']}ウィンドウ)",
        "=" * 72,
        f"  {'期間':<24}{'戦略%':>8}{'市場%':>8}{'α%':>8}{'ｼｬｰﾌﾟ':>7}{'取引':>5}",
        "-" * 72,
    ]
    for w in s["windows"]:
        lines.append(f"  {w['start']}〜{w['end']:<12}"
                     f"{w['return_pct']:>8.1f}{w['benchmark_pct']:>8.1f}"
                     f"{w['alpha_pct']:>8.1f}{w['sharpe']:>7.2f}{w['n_sells']:>5}")
    lines += [
        "-" * 72,
        f"  α>0 のウィンドウ  : {s['n_windows_alpha_positive']} / {s['n_windows']}",
        f"  最悪ウィンドウのα : {s['worst_alpha_pct']:+.1f}%",
        f"  α中央値           : {s['median_alpha_pct']:+.1f}%",
        "-" * 72,
    ]
    if s["consistent"]:
        lines.append("  判定: ○ 全ウィンドウで市場超過 — 安定性あり (ただし将来を保証しない)")
    elif s["n_windows_alpha_positive"] == 0:
        lines.append("  判定: × 全ウィンドウで市場に負け — この戦略に優位性は無い")
    else:
        lines.append("  判定: △ 勝敗が期間依存 — 特定期間のまぐれの可能性。採用は慎重に")
    lines.append("=" * 72)
    return "\n".join(lines)
