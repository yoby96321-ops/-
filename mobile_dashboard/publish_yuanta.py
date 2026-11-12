"""Publish read-only 00403A quote/model snapshots to a GitHub Pages data file.

The Yuanta password and GitHub token are requested interactively and are never
written to disk. Only stock quote and model output are published.
"""
from __future__ import annotations

import base64
import getpass
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "股票"
API_DIR = ROOT / "YuantaSparkAPI_win-x64_Python"
HISTORY_FILE = ROOT / "data" / "00403A_yuanta_5m.csv"
OUT_FILE = Path(__file__).resolve().parent / "data.json"
TZ = ZoneInfo("Asia/Taipei")

sys.path.insert(0, str(PROJECT_DIR))
from yuanta_readonly_feed import YuantaQuoteClient  # noqa: E402
from next_day_model import predict_price_path  # noqa: E402


def github_request(url: str, token: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "00403A-personal-dashboard")
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"GitHub 回應 {exc.code}：{detail}") from None


def publish(repo: str, token: str, data: dict) -> None:
    owner, name = repo.split("/", 1)
    path = "mobile_dashboard/data.json"
    endpoint = f"https://api.github.com/repos/{owner}/{name}/contents/{path}"
    try:
        current = github_request(endpoint + "?ref=main", token)
        sha = current.get("sha")
    except RuntimeError as exc:
        if "回應 404" not in str(exc):
            raise
        sha = None
    encoded = base64.b64encode(
        (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    ).decode("ascii")
    payload = {"message": f"Update 00403A market data {data['updated_at']}", "content": encoded, "branch": "main"}
    if sha:
        payload["sha"] = sha
    github_request(endpoint, token, "PUT", payload)


def read_remote(repo: str, token: str) -> dict:
    owner, name = repo.split("/", 1)
    endpoint = f"https://api.github.com/repos/{owner}/{name}/contents/mobile_dashboard/data.json?ref=main"
    try:
        item = github_request(endpoint, token)
    except RuntimeError as exc:
        if "回應 404" in str(exc):
            return {}
        raise
    encoded = item.get("content", "").replace("\n", "")
    return json.loads(base64.b64decode(encoded).decode("utf-8")) if encoded else {}


def load_history() -> pd.DataFrame:
    if not HISTORY_FILE.exists():
        raise FileNotFoundError(f"找不到歷史 5 分 K：{HISTORY_FILE}。請先在原本程式下載近 100 天資料。")
    frame = pd.read_csv(HISTORY_FILE, index_col=0, parse_dates=True)
    frame.index = pd.DatetimeIndex(frame.index)
    return frame.sort_index()


def build_daily(history: pd.DataFrame) -> pd.DataFrame:
    daily = yf.Ticker("00403A.TW").history(period="1y", interval="1d", auto_adjust=False)
    if daily.empty:
        raise RuntimeError("Yahoo Finance 日線資料暫時無法取得；歷史日線是模型輸入，不會替代元大即時報價。")
    daily = daily.rename(columns={"Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"})
    daily = daily[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    return daily


def pack_points(frame: pd.DataFrame, price_col: str, low_col: str | None = None, high_col: str | None = None) -> list[dict]:
    points = []
    for clock, row in frame.iterrows():
        item = {"time": str(clock), "price": float(row[price_col])}
        if low_col:
            item["low"] = float(row[low_col])
        if high_col:
            item["high"] = float(row[high_col])
        if "預測累積成交量" in row:
            item["volume_cumulative"] = float(row["預測累積成交量"])
        points.append(item)
    return points


def direction_text(price: float | None, ma5: float | None, rsi: float | None) -> str:
    if price is None or ma5 is None:
        return "目前資料不足，先觀察"
    if price > ma5 and (rsi is None or rsi < 70):
        return "短線偏強，分批觀察；不要只依模型追價。"
    if price < ma5 and (rsi is None or rsi > 30):
        return "短線偏弱，留意風險；依自己的計畫決定是否減碼。"
    return "訊號不明確，建議觀望並等更多資料。"


def main() -> None:
    print("00403A 本機行情發布器（唯讀，不會下單）")
    repo = input("GitHub repository（格式 owner/name）：").strip()
    if "/" not in repo:
        raise SystemExit("Repository 格式錯誤，請填 owner/name。")
    token = getpass.getpass("GitHub Fine-grained token（只存在本次執行記憶體）：").strip()
    account = input("元大 API 帳號：").strip()
    password = getpass.getpass("元大證券登入密碼（不會寫入檔案）：")
    history = load_history()
    daily = build_daily(history)
    remote = read_remote(repo, token)
    client = YuantaQuoteClient(API_DIR)
    try:
        print("正在登入元大 API…")
        client.connect(account, password)
        print("已連線。每 5 分鐘更新網站資料；按 Ctrl+C 可停止。")
        published_for = None
        today_label = datetime.now(TZ).date().isoformat()
        quote_samples: dict[str, dict] = {
            row["time"]: {"time": row["time"], "price": row.get("price", row.get("actual"))}
            for row in remote.get("today_actual_points", [])
            if row.get("date") == today_label
            and row.get("price", row.get("actual")) is not None
        }
        while True:
            now = datetime.now(TZ)
            quote = client.latest_quote() or {}
            if quote.get("price"):
                qtime = quote.get("time") or now
                if isinstance(qtime, datetime):
                    if qtime.tzinfo is None:
                        qtime = qtime.replace(tzinfo=TZ)
                    label = qtime.astimezone(TZ).strftime("%H:%M")
                else:
                    label = now.strftime("%H:%M")
                quote_samples[label] = {
                    "time": label,
                    "price": float(quote["price"]),
                }

            # Only publish every five minutes to limit repository commits.
            slot = now.strftime("%Y-%m-%d %H:%M")
            if now.minute % 5 == 0 and slot != published_for and quote.get("price"):
                published_for = slot
                # Exclude today's unfinished Yahoo daily candle during the session.
                model_daily = daily.copy()
                if now.strftime("%H:%M") < "14:00":
                    model_daily = model_daily[pd.Index(pd.to_datetime(model_daily.index).date) < now.date()]
                if model_daily.empty:
                    raise RuntimeError("沒有已完成的日線資料可供預測。")
                source_day = pd.Timestamp(model_daily.index[-1]).date()
                forecast, sample_count, neighbors, _ = predict_price_path(
                    model_daily, history, source_day, min_sessions=20, neighbors=20
                )
                if not forecast.empty:
                    close_median = float(forecast["預測價格"].iloc[-1])
                    close_low = float(forecast["偏低估計"].iloc[-1])
                    close_high = float(forecast["偏高估計"].iloc[-1])
                    target = source_day + timedelta(days=1)
                    while target.weekday() >= 5:
                        target += timedelta(days=1)
                    target_date = target.isoformat()
                    forecast_json = {
                        "target_date": target_date,
                        "sample_count": int(neighbors),
                        "close_median": close_median,
                        "close_low": close_low,
                        "close_high": close_high,
                        "points": pack_points(forecast, "預測價格", "偏低估計", "偏高估計"),
                    }
                else:
                    forecast_json = {"target_date": None, "sample_count": int(sample_count), "points": []}

                current_price = float(quote["price"])
                # Intraday actual-price points are quote snapshots, sampled each minute.
                points_today = [
                    {"time": item["time"], "actual": float(item["price"])}
                    for item in quote_samples.values()
                ]
                comparison = {"target_date": now.date().isoformat(), "points": []}
                comparison_forecast = forecast_json
                if comparison_forecast.get("target_date") != now.date().isoformat():
                    comparison_forecast = remote.get("comparison_forecast", {})
                if comparison_forecast.get("target_date") != now.date().isoformat():
                    comparison_forecast = remote.get("next_day_forecast", {})
                pred_map = {}
                if comparison_forecast.get("target_date") == now.date().isoformat():
                    pred_map = {p["time"]: p["price"] for p in comparison_forecast.get("points", [])}
                actual_map = {p["time"]: p["actual"] for p in points_today}
                comparison["points"] = [
                    {"time": t, "predicted": pred_map.get(t), "actual": actual_map.get(t)}
                    for t in sorted(set(pred_map) | set(actual_map))
                ]
                prior_rows = model_daily[pd.Index(pd.to_datetime(model_daily.index).date) < now.date()]
                last_close = float(prior_rows["Close"].iloc[-1]) if not prior_rows.empty else float(model_daily["Close"].iloc[-1])
                change_pct = (current_price / last_close - 1) * 100 if last_close else None
                response = {
                    "symbol": "00403A",
                    "updated_at": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    "latest_quote": {"price": current_price, "time": now.strftime("%Y-%m-%d %H:%M:%S"), "bid": quote.get("bid"), "ask": quote.get("ask")},
                    "today_change_pct": change_pct,
                    "today_estimated_volume": quote.get("volume"),
                    "direction_text": direction_text(current_price, float(daily["Close"].tail(5).mean()), None),
                    "model_note": f"預測使用歷史相似日模型；有效樣本 {neighbors} 天。每日資料來源 Yahoo Finance，盤中報價來自元大 SPARK API。",
                    "next_day_forecast": forecast_json,
                    "comparison_forecast": comparison_forecast if comparison_forecast.get("target_date") == now.date().isoformat() else remote.get("comparison_forecast", {}),
                    "comparison": comparison,
                    "today_actual_points": [dict(row, date=now.date().isoformat()) for row in points_today],
                }
                publish(repo, token, response)
                OUT_FILE.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
                remote = response
                print(f"{response['updated_at']} 已發布，最新價 {current_price:.2f} 元")
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n已停止發布。")
    finally:
        try:
            client.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()

