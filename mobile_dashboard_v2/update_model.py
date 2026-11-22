"""Fetch free TWSE daily bars and build a chronological Ridge walk-forward feed."""
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
HISTORY = DATA / "daily_bars.json"
PUBLIC = DATA / "data.json"
SYMBOL = "00403A"
START_YEAR, START_MONTH = 2026, 5


def fetch_month(year, month):
    url = ("https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?"
           f"date={year}{month:02d}01&stockNo={SYMBOL}&response=json")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("stat") != "OK":
        return []
    rows = []
    for row in payload.get("data", []):
        try:
            y, m, d = map(int, row[0].split("/"))
            # TWSE date fields use ROC year.
            day = date(y + 1911, m, d).isoformat()
            vals = [float(str(v).replace(",", "")) for v in row[3:8]]
            open_, high, low, close, volume = vals
            if min(open_, high, low, close) <= 0 or volume < 0 or high < max(open_, low, close) or low > min(open_, high, close):
                continue
            rows.append({"date": day, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
        except (ValueError, IndexError):
            continue
    return rows


def fetch_history():
    today = date.today()
    months, y, m = [], START_YEAR, START_MONTH
    while (y, m) <= (today.year, today.month):
        months.append((y, m)); m += 1
        if m == 13: y, m = y + 1, 1
    bars = {}
    for y, m in months:
        try:
            for row in fetch_month(y, m): bars[row["date"]] = row
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"TWSE {y}-{m:02d} unavailable: {exc}")
        time.sleep(0.25)
    return [bars[k] for k in sorted(bars)]


FEATURES = 8
def features(rows, i):
    close = np.array([r["close"] for r in rows[:i+1]], dtype=float)
    volume = np.array([r["volume"] for r in rows[:i+1]], dtype=float)
    r1 = close[-1] / close[-2] - 1 if len(close) >= 2 else 0.0
    r5 = close[-1] / close[-6] - 1 if len(close) >= 6 else r1
    r20 = close[-1] / close[-21] - 1 if len(close) >= 21 else r5
    vol20 = float(np.std(np.diff(np.log(close[-21:])), ddof=1)) if len(close) >= 22 else 0.0
    row = rows[i]
    rng = (row["high"] - row["low"]) / row["close"]
    body = (row["close"] - row["open"]) / row["close"]
    location = (row["close"] - row["low"]) / max(row["high"] - row["low"], 1e-9)
    vmean = float(np.mean(volume[-20:])) or 1.0
    return np.array([r1,r5,r20,vol20,rng,body,location,row["volume"]/vmean])


def ridge_fit_predict(x, y, target, alpha=10.0):
    mu=x.mean(axis=0); sd=x.std(axis=0); sd[sd<1e-12]=1
    xs=(x-mu)/sd; xt=(target-mu)/sd
    design=np.column_stack([np.ones(len(xs)),xs]); penalty=np.eye(design.shape[1])*alpha; penalty[0,0]=0
    coef=np.linalg.solve(design.T@design+penalty,design.T@y)
    return float((coef[0]+xt@coef[1:]).item())


def run():
    rows=fetch_history()
    DATA.mkdir(exist_ok=True)
    HISTORY.write_text(json.dumps(rows,ensure_ascii=False),encoding="utf-8")
    predictions=[]
    # Walk forward from the first date for which earlier labeled examples exist.
    # Every earlier date is used; the first predictions carry a small-sample warning.
    for i in range(2,len(rows)):
        x=np.vstack([features(rows,j) for j in range(i-1)])
        y=np.array([rows[j+1]["close"]/rows[j]["close"]-1 for j in range(i-1)])
        pred=ridge_fit_predict(x,y,features(rows,i-1))
        actual=rows[i]["close"]/rows[i-1]["close"]-1
        predictions.append({"date":rows[i]["date"],"prediction":pred*100,"actual":actual*100,"train_days":i-1})
    # Train latest model on all matured next-day labels; the final close has no label yet.
    forecast=None
    if len(rows)>=3:
        x=np.vstack([features(rows,j) for j in range(len(rows)-1)])
        y=np.array([rows[j+1]["close"]/rows[j]["close"]-1 for j in range(len(rows)-1)])
        forecast=ridge_fit_predict(x,y,features(rows,len(rows)-1))
    tail=predictions[-60:]
    if tail:
        err=np.array([p["prediction"]-p["actual"] for p in tail]); baseline=np.array([p["actual"]-tail[max(i-1,0)]["actual"] if i else 0 for i,p in enumerate(tail)])
        metrics={"n":len(tail),"mae":float(np.mean(np.abs(err))),"rmse":float(np.sqrt(np.mean(err**2))),"baseline_mae":float(np.mean([abs(p["actual"]) for p in tail])),"direction_accuracy":float(np.mean([np.sign(p["prediction"])==np.sign(p["actual"]) for p in tail]))}
    else: metrics={"n":0,"mae":None,"rmse":None,"direction_accuracy":None}
    latest=rows[-1] if rows else None
    result={"schema_version":1,"symbol":SYMBOL,"updated_at":date.today().isoformat(),"data_status":"loaded" if rows else "no_data","latest_price":latest["close"] if latest else None,"forecast":{"return_pct":forecast*100,"close":latest["close"]*(1+forecast)} if latest and forecast is not None else None,"walk_forward_metrics":metrics,"prediction_log":tail,"daily_bars":rows}
    PUBLIC.write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")
    print(f"rows={len(rows)} forecast={forecast} metrics={metrics}")

if __name__=="__main__": run()

