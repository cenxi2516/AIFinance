#!/usr/bin/env python3
"""稀有金属8标的 stock-pick 多策略数据准备"""
import os, sys, json
import pandas as pd
import numpy as np
from mootdx.quotes import Quotes

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'outputs', 'stock-pick')
os.makedirs(OUTPUT_DIR, exist_ok=True)

STOCKS = {
    "000831": "中国稀土", "600111": "北方稀土", "002428": "云南锗业",
    "600497": "驰宏锌锗", "601020": "华钰矿业", "002155": "湖南黄金",
    "000657": "中钨高新", "600549": "厦门钨业",
}

def fetch_kline(symbol, n_bars=120):
    client = Quotes.factory(market="std")
    df = client.bars(symbol=symbol, frequency=9, offset=n_bars)
    if df is None or df.empty:
        return None
    df["date"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("date").reset_index(drop=True)
    for col in ["open","high","low","close","volume","amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["date","open","high","low","close","volume","amount"]]

def calc_indicators(df):
    d = df.copy()
    # 均线
    d["MA5"] = d["close"].rolling(5).mean()
    d["MA10"] = d["close"].rolling(10).mean()
    d["MA20"] = d["close"].rolling(20).mean()
    d["MA60"] = d["close"].rolling(60).mean()
    # RSI(14)
    delta = d["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    d["RSI14"] = 100 - (100 / (1 + rs))
    # ATR(14)
    high_low = d["high"] - d["low"]
    high_close = (d["high"] - d["close"].shift()).abs()
    low_close = (d["low"] - d["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    d["ATR14"] = tr.rolling(14).mean()
    # 换手率模拟 (量/流通股本，这里用 volume 做相对比较)
    d["vol_ma5"] = d["volume"].rolling(5).mean()
    d["vol_ma20"] = d["volume"].rolling(20).mean()
    # MACD
    ema12 = d["close"].ewm(span=12).mean()
    ema26 = d["close"].ewm(span=26).mean()
    d["MACD"] = ema12 - ema26
    d["MACD_signal"] = d["MACD"].ewm(span=9).mean()
    d["MACD_hist"] = d["MACD"] - d["MACD_signal"]
    # 近期涨跌幅
    d["chg_5d"] = d["close"].pct_change(5) * 100
    d["chg_10d"] = d["close"].pct_change(10) * 100
    d["chg_20d"] = d["close"].pct_change(20) * 100
    # 近期最高/最低
    d["high_20d"] = d["high"].rolling(20).max()
    d["low_20d"] = d["low"].rolling(20).min()
    d["high_60d"] = d["high"].rolling(60).max()
    d["low_60d"] = d["low"].rolling(60).min()
    # 振幅
    d["amplitude"] = (d["high"] - d["low"]) / d["close"].shift() * 100
    # 乖离率
    d["bias_ma20"] = (d["close"] - d["MA20"]) / d["MA20"] * 100
    d["bias_ma60"] = (d["close"] - d["MA60"]) / d["MA60"] * 100
    # ADX (简版)
    plus_dm = d["high"].diff().clip(lower=0)
    minus_dm = (-d["low"].diff()).clip(lower=0)
    atr14 = d["ATR14"]
    d["plus_di14"] = (plus_dm.rolling(14).mean() / atr14 * 100).fillna(0)
    d["minus_di14"] = (minus_dm.rolling(14).mean() / atr14 * 100).fillna(0)
    dx = ((d["plus_di14"] - d["minus_di14"]).abs() / (d["plus_di14"] + d["minus_di14"] + 1e-10) * 100)
    d["ADX14"] = dx.rolling(14).mean()
    return d.dropna()

results = {}
for sym, name in STOCKS.items():
    print(f"📊 {sym} {name}...")
    df = fetch_kline(sym, 120)
    if df is None or len(df) < 60:
        print(f"  ❌ 数据不足")
        continue
    d = calc_indicators(df)
    last = d.iloc[-1]
    prev = d.iloc[-2] if len(d) > 1 else last

    # 提取关键特征
    results[sym] = {
        "name": name,
        "date": str(last["date"].date()),
        "close": round(float(last["close"]), 2),
        "features": {
            "MA5": round(float(last["MA5"]), 2),
            "MA10": round(float(last["MA10"]), 2),
            "MA20": round(float(last["MA20"]), 2),
            "MA60": round(float(last["MA60"]), 2),
            "RSI14": round(float(last["RSI14"]), 1),
            "ATR14": round(float(last["ATR14"]), 2),
            "ATR_pct": round(float(last["ATR14"] / last["close"] * 100), 2),
            "MACD_hist": round(float(last["MACD_hist"]), 4),
            "bias_ma20": round(float(last["bias_ma20"]), 1),
            "bias_ma60": round(float(last["bias_ma60"]), 1),
            "chg_5d": round(float(last["chg_5d"]), 1),
            "chg_10d": round(float(last["chg_10d"]), 1),
            "chg_20d": round(float(last["chg_20d"]), 1),
            "ADX14": round(float(last["ADX14"]), 1),
            "amplitude": round(float(last["amplitude"]), 1),
            "vol_ratio": round(float(last["volume"] / (last["vol_ma20"] + 1e-10)), 2),
            "high_20d": round(float(last["high_20d"]), 2),
            "low_20d": round(float(last["low_20d"]), 2),
            "high_60d": round(float(last["high_60d"]), 2),
            "low_60d": round(float(last["low_60d"]), 2),
        },
        # 过去20天关键形态
        "last_20d": {
            "max_chg": round(float(d["chg_5d"].tail(20).max()), 1),
            "min_chg": round(float(d["chg_5d"].tail(20).min()), 1),
            "days_below_ma20": int((d["close"].tail(20) < d["MA20"].tail(20)).sum()),
            "days_above_ma20": int((d["close"].tail(20) > d["MA20"].tail(20)).sum()),
            "vol_expand_days": int((d["volume"].tail(20) > d["vol_ma20"].tail(20) * 1.5).sum()),
            "vol_shrink_days": int((d["volume"].tail(20) < d["vol_ma20"].tail(20) * 0.5).sum()),
        }
    }

with open(os.path.join(OUTPUT_DIR, "tech_data.json"), "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\n✅ 数据已保存: {os.path.join(OUTPUT_DIR, 'tech_data.json')}")
print(f"   标的数: {len(results)}")