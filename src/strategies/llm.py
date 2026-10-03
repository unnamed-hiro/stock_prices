import os
import json
import pandas as pd
from .base import Strategy, Signal


PROMPT_TEMPLATE = """あなたは慎重な株式トレーダーです。以下の銘柄について、直近の値動きと最新ニュースから翌週の方向性を判断し、JSONで返してください。

判定対象日: {date}
評価基準: 翌5営業日で+3%以上上昇しそうなら "buy"、-3%以上下落しそうなら "sell"、それ以外は "hold"

判断の指針:
- "news" があればその内容(業績上方修正/下方修正、増配、不祥事、提携など)を値動きより重視する
- 決算発表直後の急騰/急落はニュースの中身で持続性を判断する
- ニュースが無い銘柄は値動きのみで判断し、確信が持てなければ "hold"

銘柄データ:
{data}

出力形式 (JSONのみ、説明文不要):
{{"signals": [{{"ticker": "XXXX.T", "action": "buy|sell|hold", "confidence": 0.0〜1.0, "reason": "簡潔な根拠"}}]}}
"""


def _fetch_news(ticker: str, max_items: int = 3) -> list[dict]:
    """yfinance から直近ニュース見出しを取得。失敗は空リスト (fail-open)。"""
    try:
        import yfinance as yf
        items = yf.Ticker(ticker).news or []
        out = []
        for it in items[:max_items]:
            # yfinance>=0.2.40 は {"content": {...}} 形式、旧版はフラット
            c = it.get("content", it)
            title = c.get("title", "")
            pub = c.get("pubDate") or c.get("providerPublishTime") or ""
            if title:
                out.append({"title": title, "published": str(pub)[:10]})
        return out
    except Exception:
        return []


def _summarize(ticker: str, df: pd.DataFrame, news: list[dict] | None = None) -> dict:
    last = df.iloc[-1]
    ret_5 = df["Close"].pct_change(5).iloc[-1]
    ret_20 = df["Close"].pct_change(20).iloc[-1]
    vol_ratio = df["Volume"].iloc[-1] / df["Volume"].rolling(20).mean().iloc[-1]
    d = {
        "ticker": ticker,
        "close": round(float(last["Close"]), 2),
        "ret_5d_%": round(float(ret_5) * 100, 2),
        "ret_20d_%": round(float(ret_20) * 100, 2),
        "volume_ratio_vs_20d": round(float(vol_ratio), 2),
    }
    if news:
        d["news"] = news
    return d


class LLMStrategy(Strategy):
    """Claude APIに直近の値動きサマリを渡して売買判断させる"""

    name = "llm"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.model = self.params.get("model", "claude-sonnet-5-5")
        self.api_key_env = self.params.get("api_key_env", "ANTHROPIC_API_KEY")
        self.batch_size = self.params.get("max_tickers_per_call", 10)
        # ニュース注入は「判断日が現在から3日以内」のときのみ (ライブ運用)。
        # 過去日付のバックテストに今のニュースを混ぜると先読みになるため。
        self.use_news = self.params.get("use_news", True)
        self.news_max_items = self.params.get("news_max_items", 3)
        self._client = None

    def warmup_days(self) -> int:
        return 30

    def _get_client(self):
        if self._client is None:
            try:
                from anthropic import Anthropic
            except ImportError as e:
                raise RuntimeError("anthropic SDK が未インストール") from e
            key = os.environ.get(self.api_key_env)
            if not key:
                raise RuntimeError(f"環境変数 {self.api_key_env} が未設定")
            self._client = Anthropic(api_key=key)
        return self._client

    def _ask(self, date: pd.Timestamp, batch: list[dict]) -> list[Signal]:
        client = self._get_client()
        prompt = PROMPT_TEMPLATE.format(
            date=date.strftime("%Y-%m-%d"),
            data=json.dumps(batch, ensure_ascii=False, indent=2),
        )
        resp = client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            parsed = json.loads(text[start:end])
        except Exception as e:
            print(f"[llm] parse error: {e}")
            return []
        out = []
        for s in parsed.get("signals", []):
            if s.get("action") in ("buy", "sell"):
                out.append(Signal(s["ticker"], s["action"],
                                  confidence=float(s.get("confidence", 0.5)),
                                  reason=s.get("reason", "")))
        return out

    def generate_signals(
        self,
        date: pd.Timestamp,
        price_history: dict[str, pd.DataFrame],
        held_tickers: set[str],
    ) -> list[Signal]:
        # ニュースはライブ運用 (判断日≒今日) のときだけ取得・注入する。
        # 過去日付の判断に現在のニュースを使うと先読みバイアスになる。
        live_mode = abs((pd.Timestamp.now().normalize() - date.normalize()).days) <= 3
        fetch_news = self.use_news and live_mode

        summaries = []
        for ticker, df in price_history.items():
            window = df.loc[:date]
            if len(window) < self.warmup_days():
                continue
            news = _fetch_news(ticker, self.news_max_items) if fetch_news else None
            summaries.append(_summarize(ticker, window, news))

        signals: list[Signal] = []
        for i in range(0, len(summaries), self.batch_size):
            batch = summaries[i:i + self.batch_size]
            try:
                signals.extend(self._ask(date, batch))
            except Exception as e:
                print(f"[llm] call failed: {e}")
        return signals
