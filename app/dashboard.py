"""バックテスト結果ダッシュボード

起動: streamlit run app/dashboard.py
"""
import json
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go


RESULTS_DIR = Path("results")


def list_runs() -> list[Path]:
    if not RESULTS_DIR.exists():
        return []
    return sorted(RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


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
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.plotly_chart(equity_chart(data.get("equity_curve", [])), use_container_width=True)


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
        use_container_width=True, hide_index=True,
    )

    fig = px.bar(summary.head(top_n), x="ticker", y="合計損益",
                 color="合計損益", color_continuous_scale="RdYlGn",
                 title=f"銘柄別 合計損益 (上位{top_n})")
    fig.update_layout(height=400, xaxis_title="銘柄", yaxis_title="損益 (円)")
    st.plotly_chart(fig, use_container_width=True)


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
        use_container_width=True, hide_index=True,
    )

    sells = filtered[filtered["side"] == "sell"]
    if not sells.empty:
        fig = px.scatter(sells, x="date", y="pnl", color="ticker",
                         hover_data=["shares", "price", "holding_days"],
                         title="売却タイミング別 損益")
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)


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
        use_container_width=True, hide_index=True, height=500,
    )
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("CSV をダウンロード", csv, "trades.csv", "text/csv")


def main():
    st.set_page_config(page_title="株式売買シミュレーション結果", layout="wide")
    st.title("株式売買シミュレーション ダッシュボード")

    runs = list_runs()
    if not runs:
        st.error("`results/` に結果ファイルがありません。\n\n"
                 "先に `python scripts/run_backtest.py` を実行してください。")
        return

    with st.sidebar:
        st.header("結果ファイル選択")
        selected_run = st.selectbox(
            "実行結果",
            runs,
            format_func=lambda p: f"{p.name} ({pd.Timestamp(p.stat().st_mtime, unit='s').strftime('%Y-%m-%d %H:%M')})",
        )
        st.markdown("---")
        st.caption("バックテストを再実行するには:")
        st.code("python scripts/run_backtest.py", language="bash")

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
