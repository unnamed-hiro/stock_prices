import os
import json
import pandas as pd
from .base import Strategy, Signal


PROMPT_TEMPLATE = """あなたは慎重な株式トレーダーです。以下の銘柄について、直近の値動きから翌週の方向性を判断し、JSONで返してください。

判定対象日: {date}
評価基準: 翌5営業日で+3%以上上昇しそうなら "buy"、-3%以上下落しそうなら "sell"、それ以外は "hold"

銘柄データ:
{data}

出力形式 (JSONのみ、説明文不要):
{{"signals": [{{"ticker": "XXXX.T", "action": "buy|sell|hold", "confidence": 0.0〜1.0, "reason": "簡潔な根拠"}}]}}
"""


def _summarize(ticker: str, df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    ret_5 = df["Close"].pct_change(5).iloc[-1]
    ret_20 = df["Close"].pct_change(20).iloc[-1]
    vol_ratio = df["Volume"].iloc[-1] / df["Volume"].rolling(20).mean().iloc[-1]
    return {
        "ticker": ticker,
        "close": round(float(last["Close"]), 2),
        "ret_5d_%": round(float(ret_5) * 100, 2),
        "ret_20d_%": round(float(ret_20) * 100, 2),
        "volume_ratio_vs_20d": round(float(vol_ratio), 2),
    }


class LLMStrategy(Strategy):
    """Claude APIに直近の値動きサマリを渡して売買判断させる"""

    name = "llm"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.model = self.params.get("model", "claude-opus-4-7")
        self.api_key_env = self.params.get("api_key_env", "ANTHROPIC_API_KEY")
        self.batch_size = self.params.get("max_tickers_per_call", 10)
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
        summaries = []
        for ticker, df in price_history.items():
            window = df.loc[:date]
            if len(window) < self.warmup_days():
                continue
            summaries.append(_summarize(ticker, window))

        signals: list[Signal] = []
        for i in range(0, len(summaries), self.batch_size):
            batch = summaries[i:i + self.batch_size]
            try:
                signals.extend(self._ask(date, batch))
            except Exception as e:
                print(f"[llm] call failed: {e}")
        return signals
