#!/usr/bin/env python3
"""
工业富联(601138) 买入安全区间研判
fund-flow-predictor V1.6
"""
import sys, os, json, requests, csv
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.claude', 'skills', '_shared'))
from a_stock_api import (
    eastmoney_stock_news,
    industry_comparison,
    em_get,
    eastmoney_datacenter,
    stock_fund_flow_120d,
)

CODE = "601138"
TARGET_NAME = "工业富联"

# ============================================================
# 1. 数据拉取
# ============================================================

def fetch_kline_tencent(code, days=60):
    """从腾讯获取日K线（前复权 qfq）"""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    url = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"{prefix}{code},day,,,{days},qfq"}
    r = requests.get(url, params=params, timeout=15)
    data = r.json()
    raw = data.get("data", {}).get(f"{prefix}{code}", {}).get("qfqday", [])
    klines = []
    for d in raw:
        date, open_p, close, high, low, vol = d
        o, c, h, l, v = float(open_p), float(close), float(high), float(low), float(vol)
        chg = round((c - o) / o * 100, 2) if o > 0 else 0
        amp = round((h - l) / l * 100, 2) if l > 0 else 0
        klines.append({
            "date": date, "open": o, "close": c, "high": h, "low": l,
            "volume": v, "change_pct": chg, "amplitude": amp,
            "main_net": 0, "super_net": 0, "large_net": 0, "mid_net": 0, "small_net": 0,
        })
    return klines

def fetch_realtime_tencent(code):
    """腾讯实时行情"""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    r = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=10)
    r.encoding = "gbk"
    text = r.text
    if "~" not in text or '"' not in text:
        return {}
    parts = text.split('"')[1].split("~")
    if len(parts) < 50:
        return {}
    return {
        "name": parts[1], "code": parts[2],
        "price": float(parts[3]) if parts[3] else 0,
        "last_close": float(parts[4]) if parts[4] else 0,
        "open": float(parts[5]) if parts[5] else 0,
        "volume": int(float(parts[6])) if parts[6] else 0,
        "change_amt": float(parts[31]) if parts[31] else 0,
        "change_pct": float(parts[32]) if parts[32] else 0,
        "high": float(parts[33]) if parts[33] else 0,
        "low": float(parts[34]) if parts[34] else 0,
        "amount_wan": float(parts[37]) if parts[37] else 0,
        "turnover_pct": float(parts[38]) if parts[38] else 0,
        "pe_ttm": float(parts[39]) if parts[39] else 0,
        "amplitude_pct": float(parts[43]) if parts[43] else 0,
        "mcap_yi": float(parts[44]) if parts[44] else 0,
        "float_mcap_yi": float(parts[45]) if parts[45] else 0,
        "pb": float(parts[46]) if parts[46] else 0,
        "limit_up": float(parts[47]) if parts[47] else 0,
        "limit_down": float(parts[48]) if parts[48] else 0,
    }

def fetch_realtime_sina(code):
    """新浪实时行情（交叉验证源）"""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={prefix}{code}",
                         headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        data = r.text.split('"')[1].split(",")
        if len(data) < 30:
            return {"available": False, "reason": "数据字段不足"}
        return {
            "available": True, "name": data[0],
            "open": float(data[1]), "last_close": float(data[2]),
            "price": float(data[3]), "high": float(data[4]), "low": float(data[5]),
            "volume": int(float(data[8])),
            "amount_yi": float(data[9]) / 1e8,
            "change_pct": round((float(data[3]) - float(data[2])) / float(data[2]) * 100, 2),
        }
    except Exception as e:
        return {"available": False, "reason": str(e)[:80]}

def cross_validate(tencent, sina):
    """交叉验证腾讯 vs 新浪"""
    checks = []
    def compare(metric, tv, sv, threshold):
        if tv is None or sv is None or sv == 0:
            return {"metric": metric, "tencent": tv, "sina": sv, "diff_pct": None, "ok": None}
        diff = abs(tv - sv) / abs(sv) * 100
        return {"metric": metric, "tencent": tv, "sina": sv, "diff_pct": round(diff, 3), "ok": diff < threshold}
    checks.append(compare("当前价", tencent.get("price"), sina.get("price"), 0.5))
    checks.append(compare("开盘价", tencent.get("open"), sina.get("open"), 0.5))
    checks.append(compare("最高价", tencent.get("high"), sina.get("high"), 0.5))
    checks.append(compare("最低价", tencent.get("low"), sina.get("low"), 0.5))
    checks.append(compare("昨收价", tencent.get("last_close"), sina.get("last_close"), 0.5))
    checks.append(compare("涨跌幅%", tencent.get("change_pct"), sina.get("change_pct"), 0.5))
    tc_amt = (tencent.get("amount_wan", 0) or 0) / 1e4
    sa_amt = sina.get("amount_yi", 0)
    checks.append(compare("成交额(亿)", tc_amt, sa_amt, 2.0))
    tc_vol = (tencent.get("volume", 0) or 0) * 100
    sa_vol = sina.get("volume", 0)
    checks.append(compare("成交量(股)", tc_vol, sa_vol, 5.0))
    passed = sum(1 for c in checks if c["ok"] is True)
    failed = sum(1 for c in checks if c["ok"] is False)
    single = sum(1 for c in checks if c["ok"] is None)
    if failed == 0 and single <= 2:
        quality = "🟢 高置信度(双源验证通过)"
    elif failed == 0:
        quality = "🟡 中等置信度(部分单源)"
    else:
        quality = f"🔴 低置信度({failed}项未通过)"
    return {"passed": failed == 0, "quality": quality, "checks": checks,
            "summary": f"通过{passed}项, 未通过{failed}项, 单源{single}项"}

def merge_fund_flow(daily, fund_flow):
    flow_map = {f["date"]: f for f in fund_flow}
    for d in daily:
        if d["date"] in flow_map:
            f = flow_map[d["date"]]
            d["main_net"] = round(f.get("main_net", 0) / 1e4, 1)
            d["super_net"] = round(f.get("super_net", 0) / 1e4, 1)
            d["large_net"] = round(f.get("large_net", 0) / 1e4, 1)
            d["mid_net"] = round((f.get("mid_net", 0) or 0) / 1e4, 1)
            d["small_net"] = round((f.get("small_net", 0) or 0) / 1e4, 1)

def update_last_day(daily, realtime):
    if not daily or not realtime:
        return
    today_str = datetime.now().strftime("%Y-%m-%d")
    last = daily[-1]
    if last["date"] == today_str:
        last["close"] = realtime.get("price", last["close"])
        last["open"] = realtime.get("open", last["open"])
        last["high"] = realtime.get("high", last["high"])
        last["low"] = realtime.get("low", last["low"])
        last["volume"] = realtime.get("volume", last["volume"])
        if last["open"] > 0:
            last["change_pct"] = round((last["close"] - last["open"]) / last["open"] * 100, 2)
        if last["low"] > 0:
            last["amplitude"] = round((last["high"] - last["low"]) / last["low"] * 100, 2)

# ============================================================
# 2. 信号检测
# ============================================================

def detect_selling_exhaustion(daily, track="B"):
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}
    recent = daily[-5:]
    lows = [d["low"] for d in recent]
    prev_lows = [d["low"] for d in daily[-10:-5]]
    no_new_low = min(lows) >= min(prev_lows) if prev_lows else False

    if track == "A":
        outflows = [d["main_net"] for d in recent if d["main_net"] < 0]
        if len(outflows) < 3:
            return {"triggered": False, "reason": "近期无持续流出，不需判断衰竭"}
        is_decreasing = all(abs(outflows[i]) > abs(outflows[i+1]) for i in range(len(outflows)-1))
        avg_outflow = sum(abs(o) for o in outflows) / len(outflows)
        latest_outflow = abs(outflows[-1])
        ratio = latest_outflow / avg_outflow if avg_outflow > 0 else 1
        triggered = is_decreasing and ratio < 0.5 and no_new_low
        return {
            "triggered": triggered, "signal_name": "F1: 主力流出衰竭",
            "decreasing": is_decreasing, "latest_vs_avg_ratio": round(ratio, 2),
            "no_new_low": no_new_low,
            "strength": "强" if triggered and ratio < 0.3 else ("中" if triggered else "弱"),
            "meaning": "卖方力量在减弱，卖压接近衰竭" if triggered else "卖压尚未衰竭，继续观察",
        }
    else:
        declines = [abs(d["change_pct"]) for d in recent if d["change_pct"] < 0]
        is_decreasing = len(declines) >= 2 and all(declines[i] > declines[i+1] for i in range(len(declines)-1))
        vols = [d["volume"] for d in recent]
        avg_vol_5 = sum(vols) / len(vols)
        prev_vols = [d["volume"] for d in daily[-10:-5]]
        avg_vol_prev = sum(prev_vols) / len(prev_vols) if prev_vols else avg_vol_5
        vol_shrink = avg_vol_5 < avg_vol_prev * 0.7
        triggered = is_decreasing and vol_shrink and no_new_low
        return {
            "triggered": triggered, "signal_name": "F1: 卖压衰竭(量价)",
            "decreasing_declines": is_decreasing, "volume_shrink": vol_shrink,
            "no_new_low": no_new_low, "strength": "强" if triggered else "弱",
            "meaning": "卖压在减弱，下跌动能衰竭" if triggered else "卖压尚未衰竭，继续观察",
        }

def detect_institution_return(daily, track="B"):
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}
    if track == "A":
        early = daily[-10:-3]
        recent = daily[-3:]
        early_inst = sum(d.get("super_net", 0) for d in early)
        recent_inst = sum(d.get("super_net", 0) for d in recent)
        recent_retail = sum(d.get("mid_net", 0) + d.get("small_net", 0) for d in recent)
        triggered = early_inst < 0 and recent_inst > 0 and recent_retail < 0
        return {
            "triggered": triggered, "signal_name": "F2: 机构试探回流",
            "early_institution_net": round(early_inst, 1),
            "recent_institution_net": round(recent_inst, 1),
            "recent_retail_net": round(recent_retail, 1),
            "strength": "强" if triggered and recent_inst > abs(early_inst) * 0.3 else ("中" if triggered else "弱"),
            "meaning": "机构开始接盘，散户还在恐慌 → 典型底部特征" if triggered else "机构尚未回流",
        }
    else:
        early = daily[-10:-3]
        recent = daily[-3:]
        early_decline = sum(d["change_pct"] for d in early) < -3
        avg_vol_early = sum(d["volume"] for d in early) / len(early)
        has_bullish = any(d["change_pct"] > 2 and d["volume"] > avg_vol_early * 1.5 for d in recent)
        triggered = early_decline and has_bullish
        return {
            "triggered": triggered, "signal_name": "F2: 放量反弹回流",
            "early_decline": early_decline, "has_bullish_volume": has_bullish,
            "strength": "强" if triggered else "弱",
            "meaning": "前期下跌后放量反弹，资金回流迹象" if triggered else "未见明确的资金回流信号",
        }

def detect_retail_exhaustion(daily, track="B"):
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}
    if track == "A":
        recent = daily[-5:]
        retail_flows = [d.get("mid_net", 0) + d.get("small_net", 0) for d in recent]
        all_outflow = all(f < 0 for f in retail_flows)
        if not all_outflow:
            return {"triggered": False, "reason": "散户未持续流出"}
        recent_3 = retail_flows[-3:]
        is_decreasing = all(abs(recent_3[i]) > abs(recent_3[i+1]) for i in range(len(recent_3)-1))
        prices = [d["close"] for d in recent]
        if len(prices) >= 5:
            early_d = abs((prices[1]-prices[0])/prices[0]*100) if prices[0]>0 else 0
            late_d = abs((prices[-1]-prices[-2])/prices[-2]*100) if prices[-2]>0 else 0
            decline_narrowing = late_d < early_d
        else:
            decline_narrowing = False
        triggered = all_outflow and is_decreasing and decline_narrowing
        return {
            "triggered": triggered, "signal_name": "F3: 散户恐慌出尽",
            "consecutive_outflow_days": 5, "decreasing": is_decreasing,
            "decline_narrowing": decline_narrowing,
            "strength": "强" if triggered else "弱",
            "meaning": "恐慌盘出清，筹码趋于稳定" if triggered else "恐慌盘可能尚未出尽",
        }
    else:
        recent = daily[-5:]
        changes = [d["change_pct"] for d in recent]
        negatives = [c for c in changes if c < 0]
        decline_narrowing = len(negatives) >= 2 and all(
            abs(negatives[i]) > abs(negatives[i+1]) for i in range(len(negatives)-1))
        vols = [d["volume"] for d in recent]
        avg_vol_recent = sum(vols)/len(vols)
        prev_vols = [d["volume"] for d in daily[-10:-5]]
        avg_vol_prev = sum(prev_vols)/len(prev_vols) if prev_vols else avg_vol_recent
        vol_shrink = avg_vol_recent < avg_vol_prev * 0.6
        triggered = decline_narrowing and vol_shrink
        return {
            "triggered": triggered, "signal_name": "F3: 恐慌出尽(缩量)",
            "decline_narrowing": decline_narrowing, "volume_shrink": vol_shrink,
            "strength": "强" if triggered else "弱",
            "meaning": "恐慌盘出清，缩量止跌" if triggered else "恐慌盘可能尚未出尽",
        }

def detect_volume_stabilization(daily, track="B"):
    if len(daily) < 20:
        return {"triggered": False, "reason": "数据不足（需20日）"}
    recent_3 = daily[-3:]
    prev_20 = daily[-20:]
    changes = [abs(d["change_pct"]) for d in recent_3]
    narrow_range = all(c < 2.0 for c in changes) if changes else False
    vols_20 = [d["volume"] for d in prev_20]
    avg_vol_20 = sum(vols_20) / len(vols_20) if vols_20 else 1
    recent_vol = sum(d["volume"] for d in recent_3) / 3
    volume_shrink = recent_vol < avg_vol_20 * 0.6
    amplitudes = [d["amplitude"] for d in recent_3]
    amp_narrow = all(a < 5 for a in amplitudes) if amplitudes else False
    outflow_shrink = True
    if track == "A":
        recent_main = sum(d["main_net"] for d in recent_3)
        prev_main = sum(abs(d["main_net"]) for d in daily[-8:-3])
        avg_prev_main = prev_main / 5 if prev_main != 0 else 1
        outflow_shrink = abs(recent_main) / 3 < avg_prev_main * 0.3

    triggered = narrow_range and volume_shrink and amp_narrow and outflow_shrink
    return {
        "triggered": triggered, "signal_name": "F8: 缩量止跌盘整",
        "narrow_range": narrow_range, "volume_shrink": volume_shrink,
        "amp_narrow": amp_narrow, "outflow_shrink": outflow_shrink,
        "avg_vol_20": round(avg_vol_20, 0), "recent_vol_3": round(recent_vol, 0),
        "strength": "强" if triggered else "弱",
        "meaning": "卖压枯竭，底部盘整中 → 下行空间有限" if triggered else "尚未缩量止跌，仍在波动",
    }

def detect_accelerating_selling(daily, track="B"):
    if len(daily) < 8:
        return {"triggered": False, "reason": "数据不足"}
    if track == "A":
        recent_3 = daily[-3:]
        prev_5 = daily[-8:-3]
        outflows = [d["main_net"] for d in recent_3]
        all_out = all(f < 0 for f in outflows)
        if not all_out:
            return {"triggered": False, "reason": "近期非持续流出"}
        accelerating = abs(outflows[0]) < abs(outflows[1]) < abs(outflows[2])
        avg_prev = sum(abs(d["main_net"]) for d in prev_5) / 5 if prev_5 else 1
        surge = abs(outflows[-1]) > avg_prev * 2
        triggered = all_out and accelerating and surge
        return {
            "triggered": triggered, "signal_name": "F4: 🔴 主力加速流出",
            "danger_level": "高危", "accelerating": accelerating,
            "latest_vs_avg_ratio": round(abs(outflows[-1]) / avg_prev, 1) if avg_prev > 0 else 0,
            "meaning": "卖方力量在加速 → 绝对不要抄底！持币观望" if triggered else "主力流出尚未加速",
            "action": "🚫 不买，已持有则考虑减仓" if triggered else "继续观察",
        }
    else:
        recent_3 = daily[-3:]
        changes = [d["change_pct"] for d in recent_3]
        all_down = all(c < 0 for c in changes)
        if not all_down:
            return {"triggered": False, "reason": "近期非持续下跌"}
        accelerating = abs(changes[0]) < abs(changes[1]) < abs(changes[2])
        vols = [d["volume"] for d in recent_3]
        vol_expanding = vols[0] < vols[1] < vols[2]
        avg_vol_prev = sum(d["volume"] for d in daily[-8:-3]) / 5
        vol_surge = vols[-1] > avg_vol_prev * 2
        triggered = all_down and accelerating and vol_expanding and vol_surge
        return {
            "triggered": triggered, "signal_name": "F4: 🔴 加速放量下跌",
            "danger_level": "高危", "accelerating": accelerating,
            "volume_expanding": vol_expanding,
            "vol_surge_ratio": round(vols[-1] / avg_vol_prev, 1) if avg_vol_prev > 0 else 0,
            "meaning": "恐慌性抛售！放量加速下跌 → 绝对不要抄底！" if triggered else "下跌尚未加速",
            "action": "🚫 不买，持币观望" if triggered else "继续观察",
        }

def detect_top_distribution(daily, track="B"):
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}
    if track == "A":
        recent = daily[-5:]
        prices = [d["close"] for d in recent]
        if len(prices) < 2:
            return {"triggered": False}
        price_up = (prices[-1]-prices[0])/prices[0]*100 > 3 if prices[0]>0 else False
        inst_out = sum(d.get("super_net", 0) for d in recent) < 0
        retail_in = sum(d.get("mid_net",0)+d.get("small_net",0) for d in recent) > 0
        triggered = price_up and inst_out and retail_in
        return {
            "triggered": triggered, "signal_name": "F5: 🔴 顶部派发",
            "danger_level": "高危", "price_up": price_up,
            "institution_outflow": inst_out, "retail_inflow": retail_in,
            "meaning": "机构在上涨中出货给散户 → 典型的派发结构" if triggered else "无顶部派发信号",
            "action": "🚫 不买，已持有则考虑减仓" if triggered else "继续观察",
        }
    else:
        early = daily[-10:-3]
        recent_2 = daily[-2:]
        early_closes = [d["close"] for d in early]
        if len(early_closes) < 2:
            return {"triggered": False}
        early_rise = (early_closes[-1]-early_closes[0])/early_closes[0]*100 if early_closes[0]>0 else 0
        avg_vol_early = sum(d["volume"] for d in early)/len(early) if early else 1
        has_distribution = any(d["change_pct"] < -3 and d["volume"] > avg_vol_early * 2 for d in recent_2)
        triggered = early_rise > 10 and has_distribution
        return {
            "triggered": triggered, "signal_name": "F5: 🔴 高位放量逆转",
            "danger_level": "高危", "early_rise_pct": round(early_rise, 1),
            "has_distribution": has_distribution,
            "meaning": f"前期涨{early_rise:.0f}%+放量逆转 → 典型的顶部派发信号" if triggered else "无顶部派发信号",
            "action": "🚫 不追高，已持有则考虑减仓" if triggered else "继续观察",
        }

def detect_news_exhausted(daily, news):
    if not news:
        return {"triggered": False, "reason": "无消息数据"}
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}
    bullish_keywords = ['涨', '走强', '涨停', '利好', '突破', '新高', '订单', '扩产']
    bullish_news = [n for n in news if any(kw in n.get("title","") for kw in bullish_keywords)]
    early = daily[-15:-5] if len(daily) >= 15 else daily[:-5]
    if len(early) < 5:
        return {"triggered": False}
    early_closes = [d["close"] for d in early]
    pre_rise = (early_closes[-1]-early_closes[0])/early_closes[0]*100 if early_closes[0]>0 else 0
    recent = daily[-2:]
    high_open_low_close = any(d["change_pct"] < -3 for d in recent)
    triggered = pre_rise > 10 and high_open_low_close and len(bullish_news) > 0
    return {
        "triggered": triggered, "signal_name": "F7: 🔴 利好出尽/高开低走",
        "danger_level": "非常高", "pre_rise_2w": round(pre_rise, 1),
        "latest_news": bullish_news[0].get("title", "")[:60] if bullish_news else "",
        "meaning": f"前期涨{pre_rise:.0f}%+利好兑现高开低走 → 大概率回调" if triggered else "前期涨幅可接受或未出现利好兑现",
        "action": "🚫 不要追！等回调充分后再评估" if triggered else "",
    }

# ============================================================
# 3. 企稳确认 + 安全评分 + 时机信号
# ============================================================

def check_stabilization(daily, track="B"):
    if len(daily) < 15:
        return {"is_stabilized": False, "reason": "数据不足"}
    recent = daily[-3:]
    prev_10 = daily[-15:-3]
    checks = {}
    recent_lows = [d["low"] for d in recent]
    prev_lows = [d["low"] for d in prev_10]
    checks["no_new_low"] = min(recent_lows) >= min(prev_lows)
    checks["narrow_range"] = all(d["amplitude"] < 5 for d in recent)
    if track == "A":
        recent_outflow = abs(sum(d["main_net"] for d in recent if d["main_net"] < 0))
        prev_outflow_avg = abs(sum(d["main_net"] for d in prev_10 if d["main_net"] < 0)) / max(len([x for x in prev_10 if x["main_net"] < 0]), 1)
        checks["flow_normal"] = recent_outflow < prev_outflow_avg * 0.5
    else:
        avg_vol_prev = sum(d["volume"] for d in prev_10) / len(prev_10)
        recent_vol = sum(d["volume"] for d in recent) / 3
        checks["flow_normal"] = recent_vol < avg_vol_prev * 1.5
    checks["lows_rising"] = recent_lows[-1] >= recent_lows[0] if len(recent_lows) >= 2 else False
    prices = [d["close"] for d in daily[-8:]]
    if len(prices) >= 6:
        ma5 = sum(prices[-6:-1]) / 5
        checks["above_ma5"] = prices[-1] > ma5
    else:
        checks["above_ma5"] = False
    passed = sum(1 for v in checks.values() if v)
    return {
        "is_stabilized": passed >= 4, "passed_count": passed, "total_count": 5,
        "checks": checks,
        "meaning": "企稳确认，下行风险大幅降低" if passed >= 4 else f"仅通过{passed}/5项，尚未企稳",
    }

def calc_safety_score(safety_signals, danger_signals, daily, track, auxiliary_data, concept_data=None):
    score = 50
    adjustment_details = []

    weight_map = {
        "f1_exhaustion": (15 if track == "A" else 12, "F1 主力流出衰竭" if track == "A" else "F1 卖压衰竭"),
        "f2_institution_return": (12 if track == "A" else 10, "F2 机构回流" if track == "A" else "F2 放量反弹"),
        "f3_retail_exhaustion": (10, "F3 恐慌出尽"),
        "f8_volume_stabilization": (8, "F8 缩量止跌"),
    }
    for key, (w, label) in weight_map.items():
        if safety_signals.get(key, {}).get("triggered"):
            score += w
            adjustment_details.append((label, +w))

    danger_weight_map = {
        "f4_accelerating": (22 if track == "A" else 20, "F4 加速流出" if track == "A" else "F4 加速放量下跌"),
        "f5_top_distribution": (20 if track == "A" else 18, "F5 顶部派发" if track == "A" else "F5 高位放量逆转"),
        "f7_news_exhausted": (15, "F7 利好出尽"),
    }
    for key, (w, label) in danger_weight_map.items():
        if danger_signals.get(key, {}).get("triggered"):
            score -= w
            adjustment_details.append((label, -w))

    stabilization = check_stabilization(daily, track)
    if stabilization["is_stabilized"]:
        score += 10
        adjustment_details.append(("企稳确认", +10))

    if len(daily) >= 20:
        ma20 = sum(d["close"] for d in daily[-20:]) / 20
        current = daily[-1]["close"]
        deviation = (current - ma20) / ma20 * 100
        if deviation > 15:
            score -= 5
            adjustment_details.append((f"偏离20MA+{deviation:.0f}%(超买)", -5))
        elif deviation < -10:
            score += 5
            adjustment_details.append((f"偏离20MA{deviation:.0f}%(超卖)", +5))

    if len(daily) >= 20:
        avg_vol_20 = sum(d["volume"] for d in daily[-20:]) / 20
        today_vol = daily[-1]["volume"]
        vol_ratio = today_vol / avg_vol_20
        if vol_ratio > 3.0 and daily[-1]["change_pct"] < -3:
            score -= 8
            adjustment_details.append((f"恐慌放量({vol_ratio:.1f}x均量+大跌)", -8))
        elif vol_ratio > 2.0 and daily[-1]["change_pct"] < -2:
            score -= 5
            adjustment_details.append((f"放量下跌({vol_ratio:.1f}x均量)", -5))
        elif vol_ratio < 0.4 and abs(daily[-1]["change_pct"]) < 1:
            score += 3
            adjustment_details.append(("缩量止跌企稳", +3))

    if auxiliary_data:
        if auxiliary_data.get("north_bound", {}).get("available"):
            nb = auxiliary_data["north_bound"]
            net_5d = nb.get("recent_5d_net_yi", 0)
            if net_5d < -10:
                score -= 5
                adjustment_details.append(("北向近5日流出>10亿", -5))
            elif net_5d > 10:
                score += 5
                adjustment_details.append(("北向近5日流入>10亿", +5))

        if auxiliary_data.get("margin", {}).get("available"):
            margin = auxiliary_data["margin"]
            trend = margin.get("margin_trend", "")
            net_flow = margin.get("net_margin_flow_5d_yi", 0)
            if trend == "下降" and net_flow < -0.5:
                score -= 8
                adjustment_details.append(("融资去杠杆", -8))
            elif trend == "下降" and net_flow < 0:
                score -= 4
                adjustment_details.append(("融资温和下降", -4))
            elif trend == "上升" and net_flow > 2:
                score += 5
                adjustment_details.append(("融资加杠杆", +5))
            elif trend == "上升" and net_flow > 0:
                score += 3
                adjustment_details.append(("融资温和上升", +3))

    # V1.4: 概念板块龙头修正
    if concept_data and concept_data.get("available"):
        tf = concept_data.get("target_flow", {})
        rank = concept_data.get("target_rank", 999)
        if tf.get("main_net_yi", 0) > 0 and rank == 1:
            score += 4
            adjustment_details.append(("概念板块流入龙头", +4))

    score = max(0, min(100, score))

    if score >= 75:
        level, can_enter, desc = "🟢 安全区间", True, "下行风险可控，可考虑入场（配合买入参考条件）"
    elif score >= 60:
        level, can_enter, desc = "🟡 接近安全", False, "部分条件满足，再等1-3日确认"
    elif score >= 40:
        level, can_enter, desc = "🟠 风险区间", False, "安全信号不足或有危险信号，不建议入场"
    else:
        level, can_enter, desc = "🔴 危险区间", False, "存在高危信号，远离，持币观望"

    positive = [sig.get("signal_name", key) for key, sig in safety_signals.items() if sig.get("triggered")]
    negative = [sig.get("signal_name", key) for key, sig in danger_signals.items() if sig.get("triggered")]

    return {
        "safety_score": score, "safety_level": level, "can_enter": can_enter,
        "description": desc, "positive_signals": positive, "negative_signals": negative,
        "adjustment_details": adjustment_details, "stabilization": stabilization,
        "principle": "可以少挣，必须少亏 — 只有 ≥75 分才建议考虑入场",
    }

def generate_timing_signals(safety_score, safety_signals, danger_signals, daily):
    entry_conditions = []
    entry_conditions.append({
        "condition": "安全评分 ≥ 75分", "met": safety_score["safety_score"] >= 75,
        "current": f"{safety_score['safety_score']}分", "weight": "必须",
    })
    entry_conditions.append({
        "condition": "企稳确认 (≥4/5项)", "met": safety_score["stabilization"]["is_stabilized"],
        "current": f"{safety_score['stabilization']['passed_count']}/5项", "weight": "必须",
    })
    pos_count = len(safety_score["positive_signals"])
    entry_conditions.append({
        "condition": "≥2个安全信号触发", "met": pos_count >= 2,
        "current": f"{pos_count}个", "weight": "建议",
    })
    neg_count = len(safety_score["negative_signals"])
    entry_conditions.append({
        "condition": "无危险信号", "met": neg_count == 0,
        "current": f"{neg_count}个危险信号" if neg_count > 0 else "0个", "weight": "必须",
    })
    recent_3 = daily[-3:] if len(daily) >= 3 else daily
    has_confirmation = any(d.get("change_pct", 0) > 2 and d["main_net"] > 0 for d in recent_3)
    entry_conditions.append({
        "condition": "近日放量阳线确认（增强信号）", "met": has_confirmation,
        "current": "已出现" if has_confirmation else "未出现", "weight": "加分项（非必须）",
    })
    must_met = all(c["met"] for c in entry_conditions if c["weight"] == "必须")
    all_met = all(c["met"] for c in entry_conditions)

    exit_conditions = [
        {"condition": "🔴 硬止损: 持仓亏损>5% + 主力仍在净流出", "triggered": False,
         "rule": "F13: 亏损控制 — 亏损的数学是不对称的", "action": "全部离场"},
        {"condition": "🟠 利润保护: 盈利>5% + 主力连续2日净流出", "triggered": False,
         "rule": "F12: 利润保护 — 可以少挣，必须少亏", "action": "至少减仓50%"},
        {"condition": "🔴 任何高危信号触发 (F4/F5/F7)", "triggered": neg_count > 0,
         "current": f"{neg_count}个危险信号" if neg_count > 0 else "无",
         "rule": "危险信号 > 一切买入信号", "action": "不买，已持有则评估是否离场"},
        {"condition": "🔴 安全评分降至 < 40分", "triggered": safety_score["safety_score"] < 40,
         "current": f"{safety_score['safety_score']}分", "rule": "危险区间 = 持币观望", "action": "远离，等安全评分回升"},
    ]

    verdict = ("✅ 买入参考条件全部满足，可考虑入场" if all_met else
               ("⚠️ 必要条件满足但增强信号不足，可小仓试探" if must_met else
                "❌ 买入条件不满足，继续等待"))

    return {"entry": {"ready": must_met, "ready_enhanced": all_met, "conditions": entry_conditions, "verdict": verdict},
            "exit": {"any_triggered": any(c["triggered"] for c in exit_conditions), "conditions": exit_conditions},
            "principle": "可以少挣，必须少亏 — 宁可错过，不可做错"}

# ============================================================
# 4. 辅助数据
# ============================================================

def fetch_margin_data(code):
    """拉取融资融券数据（V1.4: filter 用 SCODE）"""
    filter_str = f'(SCODE="{code}")'
    try:
        raw = eastmoney_datacenter(
            "RPTA_WEB_RZRQ_GGMX",
            filter_str=filter_str,
            page_size=30, sort_columns="DATE", sort_types="-1",
        )
        if not raw:
            return {"available": False, "reason": "无融资融券数据"}
        records = []
        for row in raw[:30]:
            date = str(row.get("DATE", ""))[:10]
            rzye = (row.get("RZYE") or 0) / 1e8
            rzmre = (row.get("RZMRE") or 0) / 1e8
            rzche = (row.get("RZCHE") or 0) / 1e8
            records.append({
                "date": date, "rzye_yi": rzye, "rzmre_yi": rzmre,
                "rzche_yi": rzche, "net_yi": rzmre - rzche,
            })
        if len(records) >= 10:
            recent_5 = sum(r["rzye_yi"] for r in records[:5]) / 5
            prev_5 = sum(r["rzye_yi"] for r in records[5:10]) / 5
            trend = "上升" if recent_5 > prev_5 * 1.05 else ("下降" if recent_5 < prev_5 * 0.95 else "平稳")
            net_5d = sum(r["net_yi"] for r in records[:5])
            net_10d = sum(r["net_yi"] for r in records[:10])
        else:
            trend, net_5d, net_10d = "数据不足", 0, 0
        return {
            "available": True, "latest_balance_yi": records[0]["rzye_yi"] if records else 0,
            "trend": trend, "net_flow_5d_yi": round(net_5d, 2),
            "net_flow_10d_yi": round(net_10d, 2), "records": records,
        }
    except Exception as e:
        return {"available": False, "reason": str(e)[:80]}

def fetch_concept_flow(code):
    """拉取概念板块成分股资金流排名"""
    try:
        # Step 1: 获取个股所属概念板块
        from a_stock_api import eastmoney_concept_blocks
        blocks = eastmoney_concept_blocks(code)
        if not blocks:
            return {"available": False, "reason": "未找到概念板块"}
        # 取第一个概念板块（最相关）
        bk_code = blocks[0].get("code", "")
        bk_name = blocks[0].get("name", "")
        if not bk_code:
            return {"available": False, "reason": "概念板块代码缺失"}
    except Exception as e:
        return {"available": False, "reason": f"概念板块查询失败: {e}"}

    # Step 2: 拉取板块成分股资金流排名
    try:
        url = f"https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "50", "po": "1", "np": "1",
            "fltt": "2", "invt": "2",
            "fid": "f62",  # 主力净流入
            "fs": f"b:{bk_code}",
            "fields": "f12,f14,f2,f3,f62,f184,f66",
        }
        r = em_get(url, params=params)
        data = r.json()
        stocks_list = data.get("data", {}).get("diff", [])
        if not stocks_list:
            return {"available": False, "reason": "板块成分股为空"}

        stocks = []
        target_flow = {}
        for item in stocks_list:
            s = {
                "code": item.get("f12", ""),
                "name": item.get("f14", ""),
                "price": item.get("f2", 0) or 0,
                "change_pct": item.get("f3", 0) or 0,
                "main_net_yi": (item.get("f62", 0) or 0) / 1e8,
                "super_net_yi": (item.get("f184", 0) or 0) / 1e8,
                "total_mcap_yi": (item.get("f66", 0) or 0) / 1e8,
            }
            stocks.append(s)
            if s["code"] == code:
                target_flow = s

        total_main = sum(s["main_net_yi"] for s in stocks)
        sorted_stocks = sorted(stocks, key=lambda x: x["main_net_yi"], reverse=True)
        target_rank = next((i+1 for i, s in enumerate(sorted_stocks) if s["code"] == code), 0)

        return {
            "available": True, "board_code": bk_code, "board_name": bk_name,
            "stock_count": len(stocks), "total_main_net_yi": round(total_main, 2),
            "target_flow": target_flow, "target_rank": target_rank,
            "target_rank_total": len(stocks), "stocks": sorted_stocks,
        }
    except Exception as e:
        return {"available": False, "reason": f"概念板块资金流拉取失败: {e}"}

def fetch_north_bound_cache(days=30):
    csv_path = os.path.expanduser("~/.tradingagents/cache/northbound_daily.csv")
    if not os.path.exists(csv_path):
        return {"available": False, "reason": "北向缓存CSV不存在"}
    records = []
    with open(csv_path, "r") as f:
        for row in csv.DictReader(f):
            records.append({
                "date": row.get("date", ""),
                "hgt_net_yi": float(row.get("hgt", 0)),
                "sgt_net_yi": float(row.get("sgt", 0)),
            })
    records = records[-days:]
    recent_5 = sum(r["hgt_net_yi"] + r["sgt_net_yi"] for r in records[-5:])
    total_30 = sum(r["hgt_net_yi"] + r["sgt_net_yi"] for r in records)
    return {
        "available": True, "total_net_30d_yi": round(total_30, 2),
        "recent_5d_net_yi": round(recent_5, 2),
        "direction": "inflow" if recent_5 > 5 else ("outflow" if recent_5 < -5 else "neutral"),
    }

# ============================================================
# 5. 主流程
# ============================================================

def main():
    print("=" * 90)
    print("  🛡️  工业富联(601138) 买入安全区间研判")
    print("=" * 90)

    # Step 1: K线
    print("[1/6] 拉取腾讯日K线(qfq)...")
    daily = fetch_kline_tencent(CODE, days=60)
    print(f"  获取 {len(daily)} 个交易日")

    # Step 2: 实时行情
    print("[2/6] 拉取实时行情(腾讯+新浪交叉验证)...")
    realtime_tc = fetch_realtime_tencent(CODE)
    realtime_sina = fetch_realtime_sina(CODE)
    if realtime_sina.get("available"):
        validation = cross_validate(realtime_tc, realtime_sina)
        realtime_tc["_validation"] = validation
        realtime_tc["_sources"] = ["腾讯", "新浪"]
        print(f"  数据质量: {validation.get('quality', '未知')}")
    else:
        realtime_tc["_validation"] = {"quality": "🟡 单源(新浪不可用)", "summary": f"新浪不可用: {realtime_sina.get('reason')}"}
        realtime_tc["_sources"] = ["腾讯"]
    print(f"  名称: {realtime_tc.get('name', '未知')} | 价格: {realtime_tc.get('price', 0):.2f}")

    # Step 3: 资金流
    print("[3/6] 拉取个股资金流(push2his)...")
    fund_flow = []
    try:
        fund_flow = stock_fund_flow_120d(CODE)
        print(f"  获取 {len(fund_flow)} 日资金流数据")
    except Exception as e:
        print(f"  ⚠️ push2his 不可用({e})，降级为量价分析模式")
    if fund_flow:
        merge_fund_flow(daily, fund_flow)

    # Step 4: 新闻
    print("[4/6] 拉取新闻...")
    try:
        news = eastmoney_stock_news(CODE, page_size=10)
    except Exception:
        news = []

    # Step 5: 行业资金流
    print("[5/6] 拉取行业板块资金流...")
    try:
        industry_flow = industry_comparison(top_n=50)
    except Exception:
        industry_flow = []

    # Step 6: 更新 + 辅助数据
    update_last_day(daily, realtime_tc)
    print("[6/6] 拉取辅助数据(融资融券+概念板块+北向)...")
    margin_data = fetch_margin_data(CODE)
    concept_flow = fetch_concept_flow(CODE)
    north_bound = fetch_north_bound_cache(30)

    # 数据完整度评估
    has_fund_flow = any(d.get("main_net", 0) != 0 for d in daily)
    track = "A" if has_fund_flow else "B"
    track_label = "个股轨(资金流+量价)" if track == "A" else "ETF轨(量价+消息面)"
    print(f"  信号轨: {track_label}")

    # 信号检测
    safety_signals = {
        "f1_exhaustion": detect_selling_exhaustion(daily, track),
        "f2_institution_return": detect_institution_return(daily, track),
        "f3_retail_exhaustion": detect_retail_exhaustion(daily, track),
        "f8_volume_stabilization": detect_volume_stabilization(daily, track),
    }
    danger_signals = {
        "f4_accelerating": detect_accelerating_selling(daily, track),
        "f5_top_distribution": detect_top_distribution(daily, track),
        "f7_news_exhausted": detect_news_exhausted(daily, news),
    }

    auxiliary_data = {
        "margin": margin_data,
        "north_bound": north_bound,
        "industry_flow": industry_flow,
    }

    safety_score = calc_safety_score(safety_signals, danger_signals, daily, track, auxiliary_data, concept_flow)
    timing = generate_timing_signals(safety_score, safety_signals, danger_signals, daily)

    # 价格摘要
    today = daily[-1] if daily else {}
    week_ago = daily[-6] if len(daily) >= 6 else daily[0]
    month_ago = daily[-22] if len(daily) >= 22 else daily[0]

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": CODE, "target_type": "stock", "target_name": realtime_tc.get("name", TARGET_NAME),
        "track": track, "track_label": track_label,
        "summary": {
            "price": realtime_tc.get("price", 0),
            "last_close": realtime_tc.get("last_close", 0),
            "change": realtime_tc.get("change_amt", 0),
            "change_pct": realtime_tc.get("change_pct", 0),
            "high": realtime_tc.get("high", 0),
            "low": realtime_tc.get("low", 0),
            "volume": realtime_tc.get("volume", 0),
            "turnover_pct": realtime_tc.get("turnover_pct", 0),
            "change_1w": round((today.get("close", 0) - week_ago.get("close", 0)) / week_ago.get("close", 1) * 100, 1),
            "change_1m": round((today.get("close", 0) - month_ago.get("close", 0)) / month_ago.get("close", 1) * 100, 1),
        },
        "realtime": realtime_tc, "daily": daily,
        "industry_flow": industry_flow, "auxiliary_data": auxiliary_data,
        "concept_flow": concept_flow, "margin_data": margin_data,
        "safety_signals": safety_signals, "danger_signals": danger_signals,
        "safety_score": safety_score, "timing": timing,
        "news": news[:8],
        "principle": "可以少挣，必须少亏。所有判断基于数据，每个信号绑定可验证条件。",
    }

    # ============================================================
    # Console 输出
    # ============================================================
    print()
    print("=" * 90)
    print("  🛡️  买入安全区间研判报告 (V1.6)")
    print(f"  标的: {report.get('target_name', CODE)} ({CODE})")
    print(f"  类型: {report['target_type']} | 信号轨: {report.get('track_label', '')}")
    print(f"  生成: {report['generated_at']} | 原则: 可以少挣，必须少亏")
    print("=" * 90)

    # Part 1
    score = report["safety_score"]
    summary = report.get("summary", {})
    print()
    print("━" * 70)
    print("  🎯 Part 1: 核心结论")
    print("━" * 70)
    print(f"  当前价格: {summary.get('price', 0):.2f} | "
          f"涨跌: {summary.get('change', 0):+.2f} ({summary.get('change_pct', 0):+.2f}%)")
    print(f"  1周涨跌: {summary.get('change_1w', 0):+.1f}% | "
          f"1月涨跌: {summary.get('change_1m', 0):+.1f}%")

    validation = realtime_tc.get("_validation", {})
    if validation:
        print(f"  数据质量: {validation.get('quality', '未知')} | {validation.get('summary', '')}")
    print(f"  数据来源: 行情[腾讯+新浪] | K线[腾讯] | PE/PB[腾讯单源] | 融资[东财单源]")
    print(f"  安全评分: {score['safety_score']}/100 → {score['safety_level']}")
    print(f"  企稳状态: {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} "
          f"({score['stabilization']['passed_count']}/5项)")
    print(f"  能否入场: {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'}")
    print(f"  判断依据: {score['description']}")

    if score.get("adjustment_details"):
        print(f"\n  📊 评分构成 (基准50):")
        for detail, adj in score["adjustment_details"]:
            sign = "+" if adj > 0 else ""
            print(f"     {sign}{adj:>+3d}  {detail}")

    # Part 2: 近20日日度数据
    print()
    print("━" * 70)
    print("  📋 Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）")
    print("━" * 70)

    # 2A
    print()
    print("  ━" * 55)
    print("    📈 2A: 日度量价明细")
    print("  ━" * 55)

    if daily:
        vols_20 = [d["volume"] for d in daily[-25:-5]]
        avg_vol_20 = sum(vols_20) / len(vols_20) if vols_20 else 1
        all_vols = [d["volume"] for d in daily]
        all_prices = [d["close"] for d in daily]
        vol_max = max(all_vols) if all_vols else 1
        vol_min = min(all_vols) if all_vols else 0
        price_60h = max(all_prices) if all_prices else 1
        price_60l = min(all_prices) if all_prices else 0

        if track == "A":
            header = (f"  {'日期':<12s} {'收盘':>8s} {'涨跌':>7s} {'振幅':>6s} "
                      f"{'换手':>6s} {'量比':>6s} {'主力净流(万)':>13s} {'走势':>6s}")
        else:
            header = (f"  {'日期':<12s} {'收盘':>8s} {'涨跌':>7s} {'振幅':>6s} "
                      f"{'换手':>6s} {'量比':>6s} {'量分位':>7s} {'价分位':>7s} {'走势':>6s}")
        sub_header = f"  {'─'*85}"
        print(header)
        print(sub_header)

        for d in daily[-20:]:
            date = d.get("date", "")
            close = d.get("close", 0)
            chg = d.get("change_pct", 0)
            amp = d.get("amplitude", 0)
            vol = d.get("volume", 0)

            turnover = realtime_tc.get("turnover_pct", 0) if date == daily[-1]["date"] else 0
            if turnover == 0:
                float_shares = realtime_tc.get("float_mcap_yi", 50) / realtime_tc.get("price", 1) * 1e8 if realtime_tc.get("price") else 5e9
                turnover = round(vol / float_shares * 100, 2) if float_shares > 0 else 0

            vol_ratio = round(vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0
            vol_pct = round((vol - vol_min) / (vol_max - vol_min) * 100, 0) if vol_max > vol_min else 50
            price_pct = round((close - price_60l) / (price_60h - price_60l) * 100, 0) if price_60h > price_60l else 50

            if chg > 5: trend = "🔥大涨"
            elif chg > 2: trend = "📈上涨"
            elif chg > -2: trend = "➖震荡"
            elif chg > -5: trend = "📉下跌"
            else: trend = "💧暴跌"

            if vol_ratio > 2.5: vr = "🔴"
            elif vol_ratio > 1.5: vr = "🟠"
            elif vol_ratio < 0.5: vr = "🔵"
            else: vr = "  "

            if vol_pct > 90: vp_mark = "🔴"
            elif vol_pct > 70: vp_mark = "🟠"
            elif vol_pct < 30: vp_mark = "🔵"
            else: vp_mark = "  "

            if price_pct > 90: pp_mark = "🔴"
            elif price_pct > 70: pp_mark = "🟠"
            elif price_pct < 30: pp_mark = "🔵"
            else: pp_mark = "  "

            if track == "A":
                main_net = d.get("main_net", 0)
                if main_net > 500: flow_mark = f"🔴 +{main_net:.0f}万"
                elif main_net > 0: flow_mark = f"🟢 +{main_net:.0f}万"
                elif main_net > -500: flow_mark = f"🟢 {main_net:.0f}万"
                else: flow_mark = f"🔴 {main_net:.0f}万"
                print(f"  {date:<12s} {close:>8.2f} {chg:>+6.2f}% {amp:>5.2f}% "
                      f"{turnover:>5.2f}% {vr}{vol_ratio:>5.1f}x {flow_mark:>13s} {trend}")
            else:
                print(f"  {date:<12s} {close:>8.2f} {chg:>+6.2f}% {amp:>5.2f}% "
                      f"{turnover:>5.2f}% {vr}{vol_ratio:>5.1f}x "
                      f"{vp_mark}{vol_pct:>5.0f}% {pp_mark}{price_pct:>5.0f}% {trend}")

        print(sub_header)
        today_d = daily[-1] if daily else {}
        today_vol = today_d.get("volume", 0)
        today_vol_ratio = round(today_vol / avg_vol_20, 1) if avg_vol_20 > 0 else 0
        today_vol_pct = round((today_vol - vol_min) / (vol_max - vol_min) * 100, 0) if vol_max > vol_min else 50
        today_price_pct = round((today_d.get("close", 0) - price_60l) / (price_60h - price_60l) * 100, 0) if price_60h > price_60l else 50

        print(f"  📊 今日量:{today_vol:,.0f} | 量比:{today_vol_ratio:.1f}x | "
              f"量分位:{today_vol_pct:.0f}%(60日) | 价分位:{today_price_pct:.0f}%(60日)")
        print(f"  📊 20日均量:{avg_vol_20:,.0f} | "
              f"60日最高价:{price_60h:.2f} | 60日最低价:{price_60l:.2f} | "
              f"距高:{(today_d.get('close',0)/price_60h-1)*100:+.1f}% | 距低:{(today_d.get('close',0)/price_60l-1)*100:+.1f}%")

        all_changes = [d["change_pct"] for d in daily[-20:]]
        big_up = sum(1 for c in all_changes if c > 5)
        up = sum(1 for c in all_changes if 2 < c <= 5)
        flat = sum(1 for c in all_changes if -2 <= c <= 2)
        down = sum(1 for c in all_changes if -5 <= c < -2)
        big_down = sum(1 for c in all_changes if c < -5)
        print(f"  📊 近20日涨跌分布: 🔥大涨{big_up}天 📈上涨{up}天 ➖震荡{flat}天 📉下跌{down}天 💧暴跌{big_down}天")

    # 2B
    print()
    print("  ━" * 55)
    print("    💰 2B: 资金流向详细")
    print("  ━" * 55)
    if daily:
        recent_5 = daily[-5:]
        recent_10 = daily[-10:]

        if track == "A":
            inst_5d = sum(d.get("super_net", 0) for d in recent_5)
            hm_5d = sum(d.get("large_net", 0) for d in recent_5)
            mid_5d = sum(d.get("mid_net", 0) for d in recent_5)
            small_5d = sum(d.get("small_net", 0) for d in recent_5)
            main_5d = inst_5d + hm_5d

            print(f"  📊 近5日资金组成(万元):")
            print(f"  🔴 超大单(机构): {inst_5d:>+12.0f}万 = {inst_5d/1e4:+.2f}亿 | {'流入' if inst_5d>0 else '流出'}")
            print(f"  🟡 大单(游资):   {hm_5d:>+12.0f}万 = {hm_5d/1e4:+.2f}亿")
            print(f"  🟢 中单:         {mid_5d:>+12.0f}万 = {mid_5d/1e4:+.2f}亿")
            print(f"  🟢 小单(散户):   {small_5d:>+12.0f}万 = {small_5d/1e4:+.2f}亿")
            print(f"  ─────────────────────────────────────────")
            print(f"  📊 主力合计:     {main_5d:>+12.0f}万 = {main_5d/1e4:+.2f}亿")

            if inst_5d < -500 and small_5d > 100:
                print(f"  ⚠️  机构卖+散户买 → 🔴 筹码从机构→散户(派发结构)")
            elif inst_5d > 500 and small_5d < -100:
                print(f"  ✅ 机构买+散户卖 → 🟢 筹码从散户→机构(吸筹结构)")
            elif abs(inst_5d) < 500 and abs(small_5d) < 500:
                print(f"  ➖ 机构散户均平淡 → 方向不明，等待信号")

            main_10d = sum(d.get("super_net", 0) + d.get("large_net", 0) for d in recent_10)
            trend_label = ("加速流入" if main_5d > main_10d * 0.7 else
                          ("流出放缓" if main_5d > main_10d * 0.3 else "趋势一致"))
            print(f"\n  📈 资金趋势对比:")
            print(f"     近10日主力: {main_10d/1e4:+.2f}亿 | 近5日主力: {main_5d/1e4:+.2f}亿 | {trend_label}")

            print(f"\n  📅 近5日每日资金组成(万元):")
            print(f"  {'日期':<12s} {'主力净流':>10s} {'超大单(机构)':>12s} {'大单(游资)':>12s} {'中单':>10s} {'小单(散户)':>12s}")
            print(f"  {'─'*72}")
            for d in recent_5:
                print(f"  {d.get('date',''):<12s} {d.get('main_net',0):>8.0f}万 "
                      f"{d.get('super_net',0):>10.0f}万 {d.get('large_net',0):>10.0f}万 "
                      f"{d.get('mid_net',0):>8.0f}万 {d.get('small_net',0):>10.0f}万")

            consec_in = 0; consec_out = 0
            for d in reversed(daily):
                mn = d.get("main_net", 0)
                if mn > 0:
                    if consec_out == 0: consec_in += 1
                    else: break
                elif mn < 0:
                    if consec_in == 0: consec_out += 1
                    else: break
                else: break
            print(f"\n  🔄 连续流入: {consec_in}日 | 连续流出: {consec_out}日")
        else:
            if concept_flow and concept_flow.get("available"):
                tf = concept_flow.get("target_flow", {})
                print(f"  📊 概念板块资金流 (代理指标 — push2his不可用时)")
                print(f"  板块: {concept_flow.get('board_code','')} {concept_flow.get('board_name','')} | "
                      f"成分股{concept_flow.get('stock_count',0)}只 | "
                      f"板块主力合计: {concept_flow.get('total_main_net_yi',0):+.2f}亿")
                if tf:
                    main_yi = tf.get('main_net_yi', 0)
                    rank = concept_flow.get('target_rank', 0)
                    total = concept_flow.get('target_rank_total', 0)
                    flow_icon = "🔴" if main_yi < -1 else ("🟢" if main_yi > 1 else "➖")
                    leader_note = ("🔴 板块内主力流出最多" if main_yi < 0 and rank <= 3 else
                                  ("🟢 板块内主力流入龙头" if main_yi > 0 and rank <= 3 else ""))
                    print(f"  {flow_icon} 目标个股: 主力{main_yi:+.2f}亿 | 板块排名 {rank}/{total} | {leader_note}")
                print(f"\n  📋 板块成分股资金流排名(主力净流):")
                print(f"  {'排名':<5s} {'代码':<8s} {'名称':<10s} {'涨跌':>8s} {'主力净流':>10s}")
                print(f"  {'─'*48}")
                sorted_stocks = sorted(concept_flow.get("stocks", []), key=lambda x: x['main_net_yi'], reverse=True)
                for i, s in enumerate(sorted_stocks[:30]):
                    marker = " ★目标" if s['code'] == CODE else ""
                    print(f"  {i+1:<5d} {s['code']:<8s} {s['name']:<10s} {s['change_pct']:>+7.2f}% {s['main_net_yi']:>+8.2f}亿{marker}")
            else:
                if industry_flow:
                    print(f"  概念板块资金流: 暂不可取，回退到行业资金流(市场环境参考):")
                    for f in industry_flow[:5]:
                        name = f.get('name', '')
                        chg = f.get('change_pct', 0)
                        main_net = f.get('main_net', 0)
                        print(f"     {name}: 涨跌{chg:+.2f}% | 主力净流{main_net/1e8:+.2f}亿")
                else:
                    reason = concept_flow.get("reason", "") if concept_flow else ""
                    print(f"  资金流向: 数据暂不可取" + (f" ({reason})" if reason else ""))

    # 2C
    print()
    print("  ━" * 55)
    print("    🏦 2C: 融资融券明细")
    print("  ━" * 55)
    if margin_data and margin_data.get("available"):
        balance = margin_data.get("latest_balance_yi", 0)
        trend = margin_data.get("trend", "平稳")
        net_5d = margin_data.get("net_flow_5d_yi", 0)
        net_10d = margin_data.get("net_flow_10d_yi", 0)
        print(f"  最新融资余额: {balance:.2f}亿 | 趋势: {trend}")
        print(f"  近5日融资净买卖: {net_5d:+.2f}亿 | 近10日: {net_10d:+.2f}亿")
        records = margin_data.get("records", [])
        if records:
            print(f"\n  📅 近10日融资日度明细:")
            print(f"  {'日期':<12s} {'融资余额':>10s} {'买入额':>10s} {'偿还额':>10s} {'净买卖':>10s}")
            print(f"  {'─'*55}")
            for r in records[:10]:
                net_mark = "🔴" if r.get('net_yi', 0) > 1 else ("🟢" if r.get('net_yi', 0) < -1 else "  ")
                print(f"  {r['date']:<12s} {r.get('rzye_yi',0):>8.2f}亿 {r.get('rzmre_yi',0):>8.2f}亿 "
                      f"{r.get('rzche_yi',0):>8.2f}亿 {net_mark}{r.get('net_yi',0):>+8.2f}亿")
        else:
            print(f"  (无日度明细记录)")
    else:
        reason = ""
        if margin_data:
            reason = margin_data.get("reason", "")
        print(f"  融资融券: 数据暂不可取" + (f" ({reason})" if reason else ""))

    # Part 3: 安全信号
    print()
    print("━" * 60)
    print("  ✅ Part 3: 安全信号检测（企稳证据）")
    print("━" * 60)
    for key, sig in report["safety_signals"].items():
        triggered = sig.get("triggered", False)
        icon = "🟢" if triggered else "⚪"
        print(f"  {icon} {sig.get('signal_name', key)}")
        print(f"     {sig.get('meaning', '')}")
        if triggered:
            print(f"     强度: {sig.get('strength', '')}")

    # Part 3b: 危险信号
    print()
    print("━" * 60)
    print("  🚨 Part 3b: 危险信号检测（风险排查）")
    print("━" * 60)
    any_danger = False
    for key, sig in report["danger_signals"].items():
        triggered = sig.get("triggered", False)
        if triggered:
            any_danger = True
            print(f"  🔴 {sig.get('signal_name', key)}")
            print(f"     危险等级: {sig.get('danger_level', '')}")
            print(f"     {sig.get('meaning', '')}")
            print(f"     → {sig.get('action', '')}")
    if not any_danger:
        print(f"  ✅ 未检测到高危信号")

    # Part 4: 企稳确认
    print()
    print("━" * 60)
    print("  📋 Part 4: 企稳确认清单 (需 ≥4/5)")
    print("━" * 60)
    checks = score["stabilization"]["checks"]
    labels = {
        "no_new_low": "不再创新低",
        "narrow_range": "振幅 < 5%",
        "flow_normal": "流出/量能正常",
        "lows_rising": "最低价抬高",
        "above_ma5": "站上5日均线",
    }
    for key, label in labels.items():
        ok = checks.get(key, False)
        print(f"  {'✅' if ok else '❌'} {label}")

    # Part 5: 买入时机
    print()
    print("━" * 60)
    print("  ⏰ Part 5: 买入时机参考条件")
    print("━" * 60)
    for i, cond in enumerate(timing["entry"]["conditions"]):
        met = cond["met"]
        icon = "✅" if met else "❌"
        print(f"  {icon} [{cond['weight']}] {cond['condition']}")
        print(f"     当前: {cond['current']}")
    print(f"\n  综合判断: {timing['entry']['verdict']}")

    # Part 6: 离场
    print()
    print("━" * 60)
    print("  🚪 Part 6: 离场/风控参考")
    print("━" * 60)
    for cond in timing["exit"]["conditions"]:
        triggered = cond["triggered"]
        icon = "🔴" if triggered else "  "
        print(f"  {icon} {cond['condition']}")
        if triggered:
            print(f"     规则: {cond.get('rule', '')}")
            print(f"     建议: {cond.get('action', '')}")

    # Part 7: 关键消息
    if news:
        print()
        print("━" * 60)
        print("  📰 Part 7: 近期关键消息")
        print("━" * 60)
        for n in news[:6]:
            title = n.get("title", "") or n.get("TITLE", "") or ""
            date = n.get("date", "") or n.get("pub_time", "") or n.get("PUB_TIME", "") or ""
            if isinstance(date, str) and len(date) > 10:
                date = date[:10]
            print(f"  [{date}] {title[:80]}")

    # Footer
    print()
    print("=" * 80)
    print("  ⚠️ 研究声明:")
    print("  1. 安全评分基于可验证的资金流规则，每条规则标注历史胜率")
    print("  2. 买入/卖出参考条件是可验证的信号框架，不是买卖指令")
    print("  3. 核心原则: 可以少挣，必须少亏 — 安全评分<60坚决不入场")
    print("  4. 亏损的数学是不对称的: 亏50%需涨100%回本")
    print(f"  5. 信号轨: {track_label}")
    print("  6. 所有分析基于公开数据，不构成投资建议")
    print("=" * 80)

    # 保存报告
    output_dir = f"src/资金预判/{datetime.now().strftime('%Y-%m-%d')}-{TARGET_NAME}-安全评估"
    os.makedirs(output_dir, exist_ok=True)

    # JSON
    json_path = os.path.join(output_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    # Markdown
    md_path = os.path.join(output_dir, "report.md")
    lines = []
    lines.append(f"# 🛡️ 买入安全区间研判报告")
    lines.append(f"")
    lines.append(f"**标的**: {report.get('target_name', CODE)} ({CODE}) | **类型**: stock | **信号轨**: {track_label}")
    lines.append(f"**生成时间**: {report['generated_at']} | **原则**: 可以少挣，必须少亏")
    lines.append(f"")
    lines.append(f"## Part 1: 核心结论")
    lines.append(f"")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 当前价格 | {summary.get('price', 0):.2f} |")
    lines.append(f"| 涨跌 | {summary.get('change', 0):+.2f} ({summary.get('change_pct', 0):+.2f}%) |")
    lines.append(f"| 1周涨跌 | {summary.get('change_1w', 0):+.1f}% |")
    lines.append(f"| 1月涨跌 | {summary.get('change_1m', 0):+.1f}% |")
    lines.append(f"| 安全评分 | **{score['safety_score']}/100 → {score['safety_level']}** |")
    lines.append(f"| 企稳状态 | {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} ({score['stabilization']['passed_count']}/5项) |")
    lines.append(f"| 能否入场 | {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'} |")
    if validation:
        lines.append(f"| 数据质量 | {validation.get('quality', '未知')} |")
    lines.append(f"")
    lines.append(f"> **数据来源**: 行情[腾讯+新浪交叉验证] | K线[腾讯] | PE/PB[腾讯单源] | 融资融券[东财单源]")
    lines.append(f"")
    lines.append(f"**判断依据**: {score['description']}")
    lines.append(f"")
    if score.get("adjustment_details"):
        lines.append(f"### 评分构成 (基准50)")
        lines.append(f"")
        for detail, adj in score["adjustment_details"]:
            sign = "+" if adj > 0 else ""
            lines.append(f"- {sign}{adj:>+3d}  {detail}")
    lines.append(f"")

    # Part 2 MD
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 2: 近20日日度数据明细")
    lines.append(f"")
    lines.append(f"### 2A: 日度量价明细")
    lines.append(f"")
    if daily:
        if track == "A":
            lines.append(f"| 日期 | 收盘 | 涨跌幅 | 振幅 | 换手率 | 量比 | 主力净流(万) | 走势 |")
            lines.append(f"|------|------|--------|------|--------|------|-------------|------|")
        else:
            lines.append(f"| 日期 | 收盘 | 涨跌幅 | 振幅 | 换手率 | 量比 | 价分位 | 走势 |")
            lines.append(f"|------|------|--------|------|--------|------|--------|------|")
        for d in daily[-20:]:
            close_md = d.get("close", 0)
            chg_md = d.get("change_pct", 0)
            amp_md = d.get("amplitude", 0)
            vol_md = d.get("volume", 0)
            float_shares_md = realtime_tc.get("float_mcap_yi", 1) / realtime_tc.get("price", 1) * 1e8 if realtime_tc.get("price") else 5e9
            turnover_md = round(vol_md / float_shares_md * 100, 2) if float_shares_md > 0 else 0
            vol_ratio_md = round(vol_md / avg_vol_20, 2) if avg_vol_20 > 0 else 0
            price_pct_md = round((close_md - price_60l) / (price_60h - price_60l) * 100, 0) if price_60h > price_60l else 50
            if chg_md > 5: tr = "🔥大涨"
            elif chg_md > 2: tr = "📈上涨"
            elif chg_md > -2: tr = "➖震荡"
            elif chg_md > -5: tr = "📉下跌"
            else: tr = "💧暴跌"
            if track == "A":
                lines.append(f"| {d.get('date','')} | {close_md:.2f} | {chg_md:+.2f}% | {amp_md:.2f}% | {turnover_md:.2f}% | {vol_ratio_md:.1f}x | {d.get('main_net',0):+.0f} | {tr} |")
            else:
                lines.append(f"| {d.get('date','')} | {close_md:.2f} | {chg_md:+.2f}% | {amp_md:.2f}% | {turnover_md:.2f}% | {vol_ratio_md:.1f}x | {price_pct_md:.0f}% | {tr} |")
        lines.append(f"")
        lines.append(f"> **今日量**:{today_vol:,.0f} | **量比**:{today_vol_ratio:.1f}x | **量分位(60日)**:{today_vol_pct:.0f}% | **价分位(60日)**:{today_price_pct:.0f}%")
        lines.append(f"> **20日均量**:{avg_vol_20:,.0f} | **60日最高价**:{price_60h:.2f} | **60日最低价**:{price_60l:.2f}")
        lines.append(f"")

    lines.append(f"### 2B: 资金流向详细")
    lines.append(f"")
    if daily and track == "A":
        lines.append(f"")
        lines.append(f"#### 近5日资金组成")
        lines.append(f"")
        lines.append(f"| 类型 | 净额(万元) | 净额(亿元) |")
        lines.append(f"|------|-----------|-----------|")
        lines.append(f"| 超大单(机构) | {inst_5d:+.0f} | {inst_5d/1e4:+.2f} |")
        lines.append(f"| 大单(游资) | {hm_5d:+.0f} | {hm_5d/1e4:+.2f} |")
        lines.append(f"| 中单 | {mid_5d:+.0f} | {mid_5d/1e4:+.2f} |")
        lines.append(f"| 小单(散户) | {small_5d:+.0f} | {small_5d/1e4:+.2f} |")
        lines.append(f"| **主力合计** | **{main_5d:+.0f}** | **{main_5d/1e4:+.2f}** |")
        lines.append(f"")
        lines.append(f"#### 近5日每日资金明细(万元)")
        lines.append(f"")
        lines.append(f"| 日期 | 主力净流 | 超大单(机构) | 大单(游资) | 中单 | 小单(散户) |")
        lines.append(f"|------|---------|------------|----------|------|----------|")
        for d in recent_5:
            lines.append(f"| {d.get('date','')} | {d.get('main_net',0):+.0f} | {d.get('super_net',0):+.0f} | {d.get('large_net',0):+.0f} | {d.get('mid_net',0):+.0f} | {d.get('small_net',0):+.0f} |")
        lines.append(f"")
        lines.append(f"**连续流入**: {consec_in}日 | **连续流出**: {consec_out}日")
        lines.append(f"")
    elif concept_flow and concept_flow.get("available"):
        lines.append(f"#### 概念板块资金流 (代理指标)")
        lines.append(f"")
        lines.append(f"板块: {concept_flow.get('board_code','')} {concept_flow.get('board_name','')} | 成分股: {concept_flow.get('stock_count',0)}只")
        lines.append(f"板块主力净流合计: {concept_flow.get('total_main_net_yi',0):+.2f}亿")
        tf_md = concept_flow.get("target_flow", {})
        if tf_md:
            lines.append(f"目标个股: 主力{tf_md.get('main_net_yi',0):+.2f}亿 | 排名 {concept_flow.get('target_rank',0)}/{concept_flow.get('target_rank_total',0)}")
        lines.append(f"")
        lines.append(f"| 排名 | 代码 | 名称 | 涨跌幅 | 主力净流(亿) |")
        lines.append(f"|------|------|------|--------|-------------|")
        for i, s in enumerate(concept_flow.get("stocks", [])[:30]):
            marker = " **←目标**" if s['code'] == CODE else ""
            lines.append(f"| {i+1} | {s['code']} | {s['name']} | {s['change_pct']:+.1f}% | {s['main_net_yi']:+.2f}{marker} |")
        lines.append(f"")
    else:
        lines.append(f"资金流向: 数据暂不可取")
        lines.append(f"")

    lines.append(f"### 2C: 融资融券明细")
    lines.append(f"")
    if margin_data and margin_data.get("available"):
        lines.append(f"**最新融资余额**: {balance:.2f}亿 | **趋势**: {trend}")
        lines.append(f"**近5日净买卖**: {net_5d:+.2f}亿 | **近10日净买卖**: {net_10d:+.2f}亿")
        lines.append(f"")
        records_md = margin_data.get("records", [])
        if records_md:
            lines.append(f"| 日期 | 融资余额(亿) | 买入额(亿) | 偿还额(亿) | 净买卖(亿) |")
            lines.append(f"|------|------------|-----------|-----------|-----------|")
            for r in records_md[:10]:
                lines.append(f"| {r.get('date','')} | {r.get('rzye_yi',0):.2f} | {r.get('rzmre_yi',0):.2f} | {r.get('rzche_yi',0):.2f} | {r.get('net_yi',0):+.2f} |")
            lines.append(f"")
    else:
        lines.append(f"融资融券: 数据暂不可取")
        lines.append(f"")

    # Part 3-7 MD
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 3: 安全信号检测")
    lines.append(f"")
    for key, sig in report["safety_signals"].items():
        triggered = sig.get("triggered", False)
        icon_md = "🟢" if triggered else "⚪"
        lines.append(f"- {icon_md} **{sig.get('signal_name', key)}**: {sig.get('meaning', '')}")
    lines.append(f"")
    lines.append(f"## Part 4: 危险信号检测")
    lines.append(f"")
    any_danger_md = False
    for key, sig in report["danger_signals"].items():
        triggered = sig.get("triggered", False)
        if triggered:
            any_danger_md = True
            lines.append(f"- 🔴 **{sig.get('signal_name', key)}** (危险等级: {sig.get('danger_level', '')})")
            lines.append(f"  - {sig.get('meaning', '')}")
            lines.append(f"  - → {sig.get('action', '')}")
    if not any_danger_md:
        lines.append(f"✅ 未检测到高危信号")
    lines.append(f"")
    lines.append(f"## Part 5: 企稳确认清单 (需 ≥4/5)")
    lines.append(f"")
    for key, label in labels.items():
        ok = checks.get(key, False)
        lines.append(f"- {'✅' if ok else '❌'} {label}")
    lines.append(f"")
    lines.append(f"## Part 6: 买入时机参考条件")
    lines.append(f"")
    for cond in timing["entry"]["conditions"]:
        met = cond["met"]
        icon_md = "✅" if met else "❌"
        lines.append(f"- {icon_md} [{cond['weight']}] {cond['condition']} — 当前: {cond['current']}")
    lines.append(f"")
    lines.append(f"**综合判断**: {timing['entry']['verdict']}")
    lines.append(f"")
    lines.append(f"## Part 7: 离场/风控参考")
    lines.append(f"")
    for cond in timing["exit"]["conditions"]:
        triggered = cond.get("triggered", False)
        icon_md = "🔴" if triggered else "  "
        lines.append(f"- {icon_md} {cond['condition']}")
        if triggered:
            lines.append(f"  - 规则: {cond.get('rule', '')}")
            lines.append(f"  - 建议: {cond.get('action', '')}")
    lines.append(f"")
    if news:
        lines.append(f"## Part 8: 近期关键消息")
        lines.append(f"")
        for n in news[:6]:
            title = n.get("title", "") or n.get("TITLE", "") or ""
            date = n.get("date", "") or n.get("pub_time", "") or n.get("PUB_TIME", "") or ""
            if isinstance(date, str) and len(date) > 10:
                date = date[:10]
            lines.append(f"- [{date}] {title}")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## ⚠️ 研究声明")
    lines.append(f"")
    lines.append(f"1. 安全评分基于可验证的价格/成交量/资金流/消息面规则")
    lines.append(f"2. 买入/卖出参考条件是可验证的信号框架，不是买卖指令")
    lines.append(f"3. 核心原则: 可以少挣，必须少亏 — 安全评分<60坚决不入场")
    lines.append(f"4. 亏损的数学是不对称的: 亏50%需涨100%回本")
    lines.append(f"5. 信号轨: {track_label}")
    lines.append(f"6. 所有分析基于公开数据，不构成投资建议")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n  报告已保存: {output_dir}/")
    return report

if __name__ == "__main__":
    main()
