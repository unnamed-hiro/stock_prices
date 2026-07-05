"""バックテスト結果ダッシュボード + 操作パネル

起動: streamlit run app/dashboard.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# クラウド等でカレントディレクトリが異なる場合に備えてルートへ移動
os.chdir(PROJECT_ROOT)

RESULTS_DIR = Path("results")
DAILY_DIR = Path("results/daily")
REALTIME_DIR = Path("results/realtime")
STATE_PATH = Path("data/state/portfolio.json")
REALTIME_STATE_PATH = Path("data/state/realtime_portfolio.json")
CONFIG_PATH = Path("config.yaml")


@st.cache_resource
def bootstrap_demo_data() -> list[str]:
    """結果や価格データが無い環境 (Streamlit Cloud初回など) で
    デモデータとサンプル結果を自動生成する。1セッション1回のみ実行。"""
    msgs: list[str] = []
    cache_dir = Path("data/cache")
    if not cache_dir.exists() or not any(cache_dir.glob("*.parquet")):
        r = subprocess.run([sys.executable, "scripts/generate_demo_prices.py"],
                           cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        if r.returncode == 0:
            msgs.append("デモ価格データを生成しました")
    if not RESULTS_DIR.exists() or not any(RESULTS_DIR.glob("*.json")):
        r = subprocess.run(
            [sys.executable, "scripts/generate_sample_results.py", "--all"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        if r.returncode == 0:
            msgs.append("サンプル結果を生成しました")
    return msgs


def list_runs() -> list[Path]:
    if not RESULTS_DIR.exists():
        return []
    return sorted(
        [p for p in RESULTS_DIR.glob("*.json") if p.parent == RESULTS_DIR],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )


def list_daily_logs() -> list[Path]:
    if not DAILY_DIR.exists():
        return []
    return sorted(DAILY_DIR.glob("*.json"), key=lambda p: p.name)


@st.cache_data
def load_run(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def trades_dataframe(trades: list[dict]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame(trades)
    df["date"] = pd.to_datetime(df["date"])
    return df


def per_ticker_summary(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()
    sells = trades_df[trades_df["side"] == "sell"].copy()
    if sells.empty:
        return pd.DataFrame()
    grouped = sells.groupby("ticker").agg(
        取引回数=("pnl", "count"),
        合計損益=("pnl", "sum"),
        平均損益=("pnl", "mean"),
        勝ち=("pnl", lambda s: (s > 0).sum()),
        負け=("pnl", lambda s: (s <= 0).sum()),
        平均保有日=("holding_days", "mean"),
    ).reset_index()
    grouped["勝率_%"] = (grouped["勝ち"] / grouped["取引回数"] * 100).round(1)
    grouped = grouped.sort_values("合計損益", ascending=False).reset_index(drop=True)
    return grouped


def equity_chart(equity_curve: list) -> go.Figure:
    if not equity_curve:
        return go.Figure()
    df = pd.DataFrame(equity_curve, columns=["date", "equity"])
    df["date"] = pd.to_datetime(df["date"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["date"], y=df["equity"], mode="lines",
                             name="評価額", line=dict(color="#1f77b4", width=2)))
    fig.update_layout(
        title="ポートフォリオ評価額の推移",
        xaxis_title="日付", yaxis_title="評価額 (円)",
        hovermode="x unified", height=400,
    )
    return fig


def render_overview(data: dict):
    m = data["metrics"]
    success = data.get("success", {})

    st.subheader("総合サマリ")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最終評価額", f"{m['final_equity']:,.0f} 円",
              f"{m['total_return_pct']:+.2f}%")
    c2.metric("年率リターン", f"{m['annual_return_pct']:.2f}%")
    c3.metric("シャープ比", f"{m['sharpe']:.2f}")
    c4.metric("最大DD", f"{m['max_drawdown_pct']:.2f}%")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("勝率", f"{m['win_rate']:.1f}%")
    c6.metric("損益比", f"{m['profit_factor']:.2f}")
    c7.metric("取引数", f"{m['n_sells']} 売 / {m['n_buys']} 買")
    c8.metric("平均保有日数", f"{m['avg_holding_days']:.1f} 日")

    if success:
        st.subheader("採用判定")
        all_ok = all(v["pass"] for v in success.values())
        if all_ok:
            st.success("★ 全項目クリア — この戦略は採用候補です ★")
        else:
            st.warning("× 一部未達 — パラメータ再調整を推奨")

        rows = []
        for name, info in success.items():
            rows.append({"指標": name,
                         "判定": "OK" if info["pass"] else "NG",
                         "実績/基準": info["detail"]})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.plotly_chart(equity_chart(data.get("equity_curve", [])), width="stretch")


def render_per_ticker(trades_df: pd.DataFrame):
    st.subheader("銘柄別パフォーマンス")
    summary = per_ticker_summary(trades_df)
    if summary.empty:
        st.info("売却済み取引がまだありません")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("取引のあった銘柄数", len(summary))
    c2.metric("黒字銘柄", int((summary["合計損益"] > 0).sum()))
    c3.metric("赤字銘柄", int((summary["合計損益"] <= 0).sum()))

    top_n = st.slider("表示件数", 5, min(100, len(summary)), min(20, len(summary)))
    st.dataframe(
        summary.head(top_n).style.format({
            "合計損益": "{:,.0f}",
            "平均損益": "{:,.0f}",
            "平均保有日": "{:.1f}",
            "勝率_%": "{:.1f}",
        }),
        width="stretch", hide_index=True,
    )

    fig = px.bar(summary.head(top_n), x="ticker", y="合計損益",
                 color="合計損益", color_continuous_scale="RdYlGn",
                 title=f"銘柄別 合計損益 (上位{top_n})")
    fig.update_layout(height=400, xaxis_title="銘柄", yaxis_title="損益 (円)")
    st.plotly_chart(fig, width="stretch")


def render_ticker_detail(trades_df: pd.DataFrame):
    st.subheader("銘柄別の取引履歴")
    if trades_df.empty:
        st.info("取引履歴がありません")
        return
    tickers = sorted(trades_df["ticker"].unique().tolist())
    selected = st.multiselect("銘柄を選択", tickers,
                              default=tickers[: min(5, len(tickers))])
    if not selected:
        st.info("銘柄を選択してください")
        return
    filtered = trades_df[trades_df["ticker"].isin(selected)].sort_values("date")
    st.dataframe(
        filtered.style.format({
            "price": "{:,.2f}",
            "pnl": "{:,.0f}",
            "shares": "{:,.0f}",
        }),
        width="stretch", hide_index=True,
    )

    sells = filtered[filtered["side"] == "sell"]
    if not sells.empty:
        fig = px.scatter(sells, x="date", y="pnl", color="ticker",
                         hover_data=["shares", "price", "holding_days"],
                         title="売却タイミング別 損益")
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(height=400)
        st.plotly_chart(fig, width="stretch")


def render_all_trades(trades_df: pd.DataFrame):
    st.subheader("全取引ログ")
    if trades_df.empty:
        st.info("取引履歴がありません")
        return
    side_filter = st.radio("種別", ["全て", "buy のみ", "sell のみ"], horizontal=True)
    df = trades_df.copy()
    if side_filter == "buy のみ":
        df = df[df["side"] == "buy"]
    elif side_filter == "sell のみ":
        df = df[df["side"] == "sell"]
    st.dataframe(
        df.sort_values("date", ascending=False).style.format({
            "price": "{:,.2f}",
            "pnl": "{:,.0f}",
            "shares": "{:,.0f}",
        }),
        width="stretch", hide_index=True, height=500,
    )
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("CSV をダウンロード", csv, "trades.csv", "text/csv")


def render_live_state():
    st.subheader("AIライブ・ペーパー口座 (現在の状態)")
    if not STATE_PATH.exists():
        st.info("`python scripts/run_live.py` をまだ実行していません")
        return
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    eq_history = state.get("equity_curve", [])
    current_eq = eq_history[-1][1] if eq_history else state["cash"]
    initial = state["initial_capital"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("現在評価額", f"{current_eq:,.0f} 円",
              f"{(current_eq - initial) / initial * 100:+.2f}%")
    c2.metric("現金残", f"{state['cash']:,.0f} 円")
    c3.metric("保有銘柄数", len(state["positions"]))
    c4.metric("総取引数", len(state["trades"]))

    if state["positions"]:
        st.markdown("**現在の保有ポジション**")
        rows = []
        for t, p in state["positions"].items():
            rows.append({"銘柄": t, "株数": p["shares"],
                         "取得単価": p["entry_price"],
                         "取得日": p["entry_date"][:10]})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    daily_logs = list_daily_logs()
    if daily_logs:
        st.markdown("---")
        st.markdown(f"**日次ログ ({len(daily_logs)}日分)**")
        rows = []
        for p in daily_logs:
            log = json.loads(p.read_text(encoding="utf-8"))
            rows.append({
                "日付": log["date"],
                "戦略": log["strategy"],
                "評価額": log["ending_equity"],
                "現金": log["cash"],
                "保有": log["n_positions"],
                "AI買付": len(log.get("executed_buys", [])),
                "AI売却": len(log.get("executed_sells", [])),
                "リスク決済": len(log.get("exits", [])),
            })
        log_df = pd.DataFrame(rows)
        st.dataframe(
            log_df.style.format({"評価額": "{:,.0f}", "現金": "{:,.0f}"}),
            width="stretch", hide_index=True,
        )

        st.markdown("**個別の日次レポート**")
        selected_day = st.selectbox("日付を選択",
                                    [p.stem for p in reversed(daily_logs)])
        log = json.loads((DAILY_DIR / f"{selected_day}.json").read_text(encoding="utf-8"))

        for section, items, color in [
            ("リスク管理による決済", log.get("exits", []), "orange"),
            ("AI判断による売却", log.get("executed_sells", []), "blue"),
            ("AI判断による買付", log.get("executed_buys", []), "green"),
        ]:
            if items:
                st.markdown(f"##### :{color}[{section}] ({len(items)}件)")
                for it in items:
                    cols = st.columns([2, 3, 5])
                    cols[0].write(f"**{it['ticker']}**")
                    if "price" in it:
                        cols[1].write(f"{it['price']:,.0f}円")
                    cols[2].write(it.get("reason", ""))


def render_realtime_state():
    st.subheader("準リアルタイム AI 売買 (5分ポーリング)")
    auto = st.checkbox("自動更新 (30秒ごと)", value=False,
                       help="run_realtime.bat 実行中にチェックすると最新tickが自動表示される")
    if auto:
        # Streamlit 1.30+ : st.experimental_rerun の代替
        try:
            from streamlit_autorefresh import st_autorefresh  # type: ignore
            st_autorefresh(interval=30_000, key="rt_refresh")
        except ImportError:
            import time as _t
            _t.sleep(30)
            st.rerun()

    if not REALTIME_STATE_PATH.exists():
        st.info("リアルタイムモードはまだ実行されていません。\n\n"
                "`run_realtime.bat` をダブルクリックして起動してください。")
        return
    state = json.loads(REALTIME_STATE_PATH.read_text(encoding="utf-8"))

    # 最新スナップショットを探す
    snapshots: list[Path] = []
    if REALTIME_DIR.exists():
        for d in sorted(REALTIME_DIR.iterdir()):
            if d.is_dir():
                snapshots.extend(sorted(d.glob("*.json")))
    latest_eq = state["cash"]
    if snapshots:
        latest = json.loads(snapshots[-1].read_text(encoding="utf-8"))
        latest_eq = latest["equity"]

    initial = state["initial_capital"]
    pnl_pct = (latest_eq - initial) / initial * 100

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最新評価額", f"{latest_eq:,.0f} 円", f"{pnl_pct:+.2f}%")
    c2.metric("現金残", f"{state['cash']:,.0f} 円")
    c3.metric("保有銘柄数", len(state["positions"]))
    c4.metric("総取引数", len(state["trades"]))

    if state["positions"]:
        st.markdown("**現在の保有ポジション**")
        rows = [{"銘柄": t, "株数": p["shares"], "取得単価": p["entry_price"],
                 "取得日時": p["entry_date"][:19]}
                for t, p in state["positions"].items()]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if snapshots:
        st.markdown("---")
        st.markdown(f"**ティック履歴 ({len(snapshots)}件)**")
        eq_rows = []
        for s in snapshots:
            d = json.loads(s.read_text(encoding="utf-8"))
            eq_rows.append({"timestamp": d["timestamp"], "equity": d["equity"],
                            "cash": d["cash"], "n_positions": d["n_positions"]})
        eq_df = pd.DataFrame(eq_rows)
        eq_df["timestamp"] = pd.to_datetime(eq_df["timestamp"])
        fig = px.line(eq_df, x="timestamp", y="equity",
                      title="評価額の推移 (1日)")
        fig.add_hline(y=initial, line_dash="dash", line_color="gray",
                      annotation_text=f"初期資金 {initial:,.0f}円")
        st.plotly_chart(fig, width="stretch")

        # 直近の約定
        recent_trades = []
        for s in snapshots[-20:]:
            d = json.loads(s.read_text(encoding="utf-8"))
            for e in d.get("executed", []):
                recent_trades.append({"時刻": d["timestamp"][11:19], **e})
        if recent_trades:
            st.markdown("**直近の約定**")
            st.dataframe(pd.DataFrame(recent_trades),
                         width="stretch", hide_index=True)


def run_subprocess_streaming(cmd: list[str], label: str = "実行中"):
    """Pythonスクリプトをサブプロセスで起動し、出力をリアルタイム表示。"""
    placeholder = st.empty()
    log_lines: list[str] = []
    st.caption(f"実行コマンド: `{' '.join(cmd)}`")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except FileNotFoundError as e:
        st.error(f"起動失敗: {e}")
        return False
    with st.spinner(label):
        assert proc.stdout is not None
        for line in proc.stdout:
            log_lines.append(line.rstrip())
            placeholder.code("\n".join(log_lines[-50:]), language=None)
        proc.wait()
    if proc.returncode == 0:
        st.success(f"完了 (exit=0)")
        return True
    st.error(f"異常終了 (exit={proc.returncode})")
    return False


def render_run_backtest():
    st.subheader("バックテスト実行")
    st.caption("過去データで戦略を検証します。終了後、サイドバーで結果を選んで確認できます。")
    c1, c2, c3 = st.columns(3)
    strategy = c1.selectbox("戦略",
                            ["ensemble", "technical", "ml", "fundamental", "llm"],
                            help="ensemble=マルチAI合議制(推奨) / "
                                 "fundamental=財務指標 / llm は ANTHROPIC_API_KEY 必須")
    limit_choice = c2.selectbox("銘柄数",
                                ["10 (動作確認・1分)", "20", "50",
                                 "100", "全銘柄 (5〜15分)"],
                                index=0)
    limit_map = {"10 (動作確認・1分)": 10, "20": 20, "50": 50,
                 "100": 100, "全銘柄 (5〜15分)": None}
    limit = limit_map[limit_choice]
    use_cache = c3.checkbox("キャッシュ利用", value=True,
                            help="チェックを外すとyfinanceから再取得")
    if st.button("バックテスト開始", type="primary", width="stretch"):
        cmd = [sys.executable, "scripts/run_backtest.py", "--strategy", strategy]
        if limit is not None:
            cmd += ["--limit", str(limit)]
        if not use_cache:
            cmd.append("--no-cache")
        run_subprocess_streaming(cmd, "バックテスト実行中...")
        st.info("結果ファイルが results/ に保存されました。サイドバーから選択してください。")

    with st.expander("🔬 ウォークフォワード検証 (安定性チェック)"):
        st.caption("期間を複数の連続ウィンドウに分割し、各ウィンドウで独立に検証します。"
                   "特定期間だけ勝つ「まぐれ/過剰最適化」を検出できます。")
        wf_windows = st.slider("分割ウィンドウ数", 2, 8, 4)
        if st.button("ウォークフォワード実行", width="stretch", key="run_wf"):
            cmd = [sys.executable, "scripts/run_walkforward.py",
                   "--strategy", strategy, "--windows", str(wf_windows)]
            if limit is not None:
                cmd += ["--limit", str(limit)]
            run_subprocess_streaming(cmd, "ウォークフォワード実行中...")
        wf_path = Path(f"results/walkforward_{strategy}.json")
        if wf_path.exists():
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
            st.markdown(f"**前回の結果** — α>0 は "
                        f"{wf['n_windows_alpha_positive']} / {wf['n_windows']} ウィンドウ、"
                        f"最悪α {wf['worst_alpha_pct']:+.1f}%")
            wdf = pd.DataFrame(wf["windows"])
            st.dataframe(
                wdf[["start", "end", "return_pct", "benchmark_pct",
                     "alpha_pct", "sharpe", "n_sells"]].style.format(
                    {"return_pct": "{:+.1f}", "benchmark_pct": "{:+.1f}",
                     "alpha_pct": "{:+.1f}", "sharpe": "{:.2f}"}),
                width="stretch", hide_index=True)
            if wf["consistent"]:
                st.success("全ウィンドウで市場超過 — 安定性あり (将来の保証ではない)")
            elif wf["n_windows_alpha_positive"] == 0:
                st.error("全ウィンドウで市場に負け — この戦略に優位性は無い")
            else:
                st.warning("勝敗が期間依存 — 過剰最適化の可能性。採用は慎重に")


def render_run_live():
    st.subheader("AI日次判断 (1日分)")
    st.caption("当日(または指定日)の終値をもとに、AIに売買判断をさせて仮想口座を更新します。")
    c1, c2 = st.columns(2)
    strategy = c1.selectbox("戦略",
                            ["ensemble", "technical", "ml", "fundamental", "llm"],
                            key="live_strat",
                            help="ensemble=マルチAI合議制(推奨)")
    date = c2.date_input("判断日", value=pd.Timestamp.today().date(),
                         help="休場日でも直近営業日のデータで動く")
    c3, c4 = st.columns(2)
    dry = c3.checkbox("dry-run (判断のみ、口座変更なし)", value=False)
    limit = c4.number_input("銘柄数 (0=config値)", value=0, min_value=0,
                            max_value=500, step=10)

    cc1, cc2 = st.columns([3, 1])
    if cc1.button("AI判断を実行", type="primary", width="stretch",
                  key="run_live_btn"):
        cmd = [sys.executable, "scripts/run_live.py",
               "--strategy", strategy, "--date", str(date)]
        if dry:
            cmd.append("--dry-run")
        if limit > 0:
            cmd += ["--limit", str(limit)]
        run_subprocess_streaming(cmd, "AI判断実行中...")
    if cc2.button("口座をリセット", width="stretch", key="live_reset"):
        run_subprocess_streaming([sys.executable, "scripts/run_live.py", "--reset"],
                                  "リセット中...")


def render_run_intraday():
    st.subheader("本日トレードシミュレーション")
    st.caption("その日の1分足を寄り付きから引けまで時系列で再生し、AIが分単位で売買したら"
               "どうなるかを一気に再現します (引け後の実行がおすすめ)。")

    c1, c2, c3 = st.columns(3)
    date = c1.date_input("対象日", value=pd.Timestamp.today().date(),
                         help="1分足はyfinance仕様で直近約7日まで")
    step = c2.selectbox("判断間隔", [1, 5, 15], index=0,
                        format_func=lambda x: f"{x}分ごと",
                        help="間隔を広げると高速になります")
    eod_hold = c3.checkbox("引けで持ち越す", value=False,
                           help="OFFなら引けで全ポジション手仕舞い")

    today = pd.Timestamp.today().date()
    if st.button("シミュレーション開始", type="primary",
                 width="stretch", key="run_intraday_btn"):
        cmd = [sys.executable, "scripts/run_intraday.py", "--step", str(step)]
        if date != today:
            cmd += ["--date", str(date)]
        if eod_hold:
            cmd.append("--hold")
        run_subprocess_streaming(cmd, "本日シミュレーション実行中...")
        st.rerun()

    # 直近の結果を表示
    intraday_dir = Path("results/intraday")
    files = sorted(intraday_dir.glob("*.json")) if intraday_dir.exists() else []
    if not files:
        st.info("まだ実行結果がありません。上のボタンで実行してください。")
        return

    st.markdown("---")
    sel = st.selectbox("結果を表示", list(reversed(files)),
                       format_func=lambda p: p.stem, key="intraday_sel")
    r = json.loads(Path(sel).read_text(encoding="utf-8"))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("対象日", r["date"])
    m2.metric("終了評価額", f"{r['ending_equity']:,.0f}円", f"{r['pnl_pct']:+.2f}%")
    n_sells = sum(1 for t in r["trades"] if t["side"] == "sell")
    n_buys = sum(1 for t in r["trades"] if t["side"] == "buy")
    m3.metric("約定", f"{n_buys}買 / {n_sells}売")
    win = sum(1 for t in r["trades"] if t["side"] == "sell" and t["pnl"] > 0)
    m4.metric("利益確定", f"{win} / {n_sells}" if n_sells else "0")

    if r.get("equity_curve"):
        ec = pd.DataFrame(r["equity_curve"], columns=["time", "equity"])
        ec["time"] = pd.to_datetime(ec["time"])
        fig = px.line(ec, x="time", y="equity",
                      title=f"{r['date']} のイントラデイ評価額推移")
        fig.add_hline(y=r["starting_equity"], line_dash="dash",
                      line_color="gray", annotation_text="開始評価額")
        fig.update_layout(height=380, xaxis_title="時刻", yaxis_title="評価額(円)")
        st.plotly_chart(fig, width="stretch")

    if r["trades"]:
        st.markdown("**約定履歴**")
        tdf = pd.DataFrame(r["trades"])
        tdf["time"] = pd.to_datetime(tdf["time"]).dt.strftime("%H:%M")
        st.dataframe(
            tdf[["time", "ticker", "side", "shares", "price", "pnl"]].style.format(
                {"price": "{:,.0f}", "pnl": "{:,.0f}", "shares": "{:,.0f}"}),
            width="stretch", hide_index=True,
        )


def render_run_realtime():
    st.subheader("準リアルタイム AI 売買")
    st.caption("yfinance 1分足を取得 → AI判断 → 仮想売買。約15分遅延あり。")
    c1, c2, c3 = st.columns(3)
    dry = c1.checkbox("dry-run", value=False, key="rt_dry")
    force = c2.checkbox("force-run (営業時間外も実行)", value=True, key="rt_force")
    auto = c3.checkbox("30秒ごと自動実行", value=False, key="rt_auto",
                       help="チェックすると30秒ごとに1ティック実行を繰り返す")

    cc1, cc2 = st.columns([3, 1])
    if cc1.button("1ティック実行", type="primary",
                  width="stretch", key="rt_once"):
        cmd = [sys.executable, "scripts/run_realtime.py",
               "--once", "--interval", "1"]
        if dry:
            cmd.append("--dry-run")
        if force:
            cmd.append("--force-run")
        run_subprocess_streaming(cmd, "1ティック実行中...")
        st.rerun()
    if cc2.button("口座リセット", width="stretch", key="rt_reset"):
        run_subprocess_streaming(
            [sys.executable, "scripts/run_realtime.py", "--reset"], "リセット中...")
        st.rerun()

    st.markdown("---")
    render_realtime_state_compact()

    if auto:
        time.sleep(30)
        st.rerun()


def render_realtime_state_compact():
    """リアルタイム状態の簡易表示 (render_realtime_state より軽量)"""
    if not REALTIME_STATE_PATH.exists():
        st.info("まだ1度も実行されていません。「1ティック実行」を押してください。")
        return
    state = json.loads(REALTIME_STATE_PATH.read_text(encoding="utf-8"))

    snapshots: list[Path] = []
    if REALTIME_DIR.exists():
        for d in sorted(REALTIME_DIR.iterdir()):
            if d.is_dir():
                snapshots.extend(sorted(d.glob("*.json")))
    latest_eq = state["cash"]
    if snapshots:
        latest = json.loads(snapshots[-1].read_text(encoding="utf-8"))
        latest_eq = latest["equity"]

    initial = state["initial_capital"]
    pnl_pct = (latest_eq - initial) / initial * 100
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最新評価額", f"{latest_eq:,.0f}円", f"{pnl_pct:+.2f}%")
    c2.metric("現金残", f"{state['cash']:,.0f}円")
    c3.metric("保有銘柄数", len(state["positions"]))
    c4.metric("総取引数", len(state["trades"]))

    if state["positions"]:
        st.markdown("**現在の保有ポジション**")
        rows = [{"銘柄": t, "株数": p["shares"], "取得単価": p["entry_price"],
                 "取得日時": p["entry_date"][:19]}
                for t, p in state["positions"].items()]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if snapshots:
        eq_rows = []
        for s in snapshots:
            d = json.loads(s.read_text(encoding="utf-8"))
            eq_rows.append({"timestamp": d["timestamp"], "equity": d["equity"]})
        eq_df = pd.DataFrame(eq_rows)
        eq_df["timestamp"] = pd.to_datetime(eq_df["timestamp"])
        fig = px.line(eq_df, x="timestamp", y="equity", title="評価額推移")
        fig.add_hline(y=initial, line_dash="dash", line_color="gray")
        st.plotly_chart(fig, width="stretch")


def render_settings():
    st.subheader("設定 (config.yaml)")
    st.caption("初期資金、リスク設定、監視銘柄リスト等を直接編集できます。"
               "変更後「保存」を押すと次回実行から反映されます。")

    if not CONFIG_PATH.exists():
        st.error(f"{CONFIG_PATH} が見つかりません")
        return

    current_text = CONFIG_PATH.read_text(encoding="utf-8")
    edited = st.text_area("config.yaml", value=current_text, height=500,
                          key="config_editor")

    c1, c2, c3 = st.columns([1, 1, 4])
    if c1.button("保存", type="primary", key="save_cfg"):
        try:
            yaml.safe_load(edited)  # 構文チェック
        except yaml.YAMLError as e:
            st.error(f"YAML構文エラー: {e}")
            return
        backup = CONFIG_PATH.with_suffix(".yaml.bak")
        backup.write_text(current_text, encoding="utf-8")
        CONFIG_PATH.write_text(edited, encoding="utf-8")
        st.success(f"保存しました (バックアップ: {backup.name})")
    if c2.button("元に戻す", key="reset_cfg"):
        st.rerun()


def render_logs_browser():
    st.subheader("生ログ閲覧")
    st.caption("results/ 配下のJSONログを直接閲覧できます。")
    log_kind = st.radio("ログ種別",
                        ["日次レポート (results/daily/)",
                         "リアルタイム・スナップショット (results/realtime/)",
                         "バックテスト結果 (results/*.json)"],
                        horizontal=True)
    if log_kind.startswith("日次"):
        files = list_daily_logs()
    elif log_kind.startswith("リアルタイム"):
        files = []
        if REALTIME_DIR.exists():
            for d in sorted(REALTIME_DIR.iterdir()):
                if d.is_dir():
                    files.extend(sorted(d.glob("*.json")))
    else:
        files = list_runs()

    if not files:
        st.info("まだログがありません")
        return

    selected = st.selectbox(
        "ファイル選択",
        files,
        format_func=lambda p: f"{p} "
                              f"({pd.Timestamp(p.stat().st_mtime, unit='s').strftime('%m-%d %H:%M')})",
    )
    data = json.loads(Path(selected).read_text(encoding="utf-8"))
    st.json(data, expanded=False)


def main():
    st.set_page_config(page_title="株式売買シミュレーション", layout="wide",
                       initial_sidebar_state="expanded")
    st.title("株式売買シミュレーション")
    st.caption("📊 結果閲覧 + ▶️ 操作パネル を1つのWebUIに統合 / "
               "コマンドプロンプト不要")

    boot_msgs = bootstrap_demo_data()
    is_cloud = bool(os.environ.get("STREAMLIT_RUNTIME_ENV")) or \
        "/mount/src" in str(PROJECT_ROOT)
    if boot_msgs:
        st.info("初回起動: " + " / ".join(boot_msgs))
    if is_cloud:
        st.warning(
            "☁️ クラウド版では、設定変更・口座状態・実行結果は再起動で消えます "
            "(一時的なファイルシステムのため)。継続運用はローカルPC版を推奨します。",
            icon="⚠️",
        )

    main_tabs = st.tabs([
        "📊 結果ダッシュボード",
        "📅 本日シミュレーション",
        "▶️ バックテスト実行",
        "🤖 AI日次判断",
        "⏱️ 準リアルタイム",
        "📁 生ログ",
        "⚙️ 設定編集",
    ])

    with main_tabs[0]:
        render_results_dashboard()
    with main_tabs[1]:
        render_run_intraday()
    with main_tabs[2]:
        render_run_backtest()
    with main_tabs[3]:
        render_run_live()
    with main_tabs[4]:
        render_run_realtime()
    with main_tabs[5]:
        render_logs_browser()
    with main_tabs[6]:
        render_settings()


def render_results_dashboard():
    """既存の結果閲覧UI"""
    runs = list_runs()
    live_exists = STATE_PATH.exists()
    rt_exists = REALTIME_STATE_PATH.exists()

    if not runs and not live_exists and not rt_exists:
        st.info("まだ結果がありません。\n\n"
                "**「▶️ バックテスト実行」** タブからバックテストを実行するか、\n"
                "**「🤖 AI日次判断」** タブから1日分のAI判断を実行してください。")
        return

    options = []
    if runs:
        options.append("バックテスト結果")
    if live_exists:
        options.append("AIライブ運用 (日次)")
    if rt_exists:
        options.append("準リアルタイム")

    mode = st.sidebar.radio("表示モード", options, index=0)

    if mode == "AIライブ運用 (日次)":
        render_live_state()
        return
    if mode == "準リアルタイム":
        render_realtime_state()
        return

    with st.sidebar:
        st.markdown("---")
        st.header("結果ファイル選択")
        selected_run = st.selectbox(
            "実行結果",
            runs,
            format_func=lambda p: f"{p.name} ({pd.Timestamp(p.stat().st_mtime, unit='s').strftime('%Y-%m-%d %H:%M')})",
        )

    data = load_run(str(selected_run))
    trades_df = trades_dataframe(data.get("trades", []))

    st.caption(f"戦略: **{data.get('strategy', 'unknown')}** | "
               f"ファイル: `{selected_run.name}`")

    tabs = st.tabs(["総合サマリ", "銘柄別", "銘柄詳細", "全取引"])
    with tabs[0]:
        render_overview(data)
    with tabs[1]:
        render_per_ticker(trades_df)
    with tabs[2]:
        render_ticker_detail(trades_df)
    with tabs[3]:
        render_all_trades(trades_df)


if __name__ == "__main__":
    main()
