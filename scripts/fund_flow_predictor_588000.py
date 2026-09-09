#!/usr/bin/env python3
"""
fund-flow-predictor 完整分析脚本
标的: 科创50ETF华夏 (588000)
日期: 2026-07-15
"""

import sys
sys.path.insert(0, '.claude/skills/_shared')
import os
import json
import requests
from datetime import datetime, timedelta

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 1: 数据采集
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_kline_tencent(code: str, days: int = 60) -> list[dict]:
    """从腾讯获取日K线（前复权）— 上海ETF用 sh 前缀"""
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    r = requests.get(
        'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
        params={'param': f'{prefix}{code},day,,,{days},qfq'},
        timeout=15
    )
    data = r.json()
    raw = data.get('data', {}).get(f'{prefix}{code}', {}).get('qfqday', [])
    klines = []
    for d in raw:
        date, open_p, close, high, low, vol = d
        o, c, h, l, v = float(open_p), float(close), float(high), float(low), float(vol)
        chg = (c - o) / o * 100 if o > 0 else 0
        amp = (h - l) / l * 100 if l > 0 else 0
        klines.append({
            "date": date,
            "open": o, "close": c, "high": h, "low": l,
            "volume": v,
            "change_pct": round(chg, 2),
            "amplitude": round(amp, 2),
        })
    return klines


def fetch_realtime_tencent(code: str) -> dict:
    """从腾讯获取实时行情 — 上海ETF用 sh 前缀"""
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    r = requests.get(f'http://qt.gtimg.cn/q={prefix}{code}', timeout=10)
    text = r.text
    if '~' not in text:
        return {}
    parts = text.split('"')[1].split('~')
    if len(parts) < 40:
        return {}
    return {
        "name": parts[1],
        "code": parts[2],
        "price": float(parts[3]),
        "last_close": float(parts[4]),
        "open": float(parts[5]),
        "volume": int(float(parts[6])),
        "change": float(parts[31]) if len(parts) > 31 else 0,
        "change_pct": float(parts[32]) if len(parts) > 32 else 0,
        "high": float(parts[33]) if len(parts) > 33 else 0,
        "low": float(parts[34]) if len(parts) > 34 else 0,
        "amount_yi": float(parts[37]) if len(parts) > 37 else 0,
        "turnover": float(parts[38]) if len(parts) > 38 else 0,
    }


def fetch_realtime_sina(code: str) -> dict:
    """从新浪获取实时行情 — 作为腾讯的交叉验证源"""
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    try:
        r = requests.get(
            f'https://hq.sinajs.cn/list={prefix}{code}',
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10
        )
        r.encoding = "gbk"
        data = r.text.split('"')[1].split(",")
        if len(data) < 30:
            return {"available": False, "reason": "数据字段不足"}
        return {
            "available": True,
            "name": data[0],
            "open": float(data[1]),
            "last_close": float(data[2]),
            "price": float(data[3]),
            "high": float(data[4]),
            "low": float(data[5]),
            "volume": int(float(data[8])),
            "amount_yi": float(data[9]) / 1e8,
            "change_pct": round((float(data[3]) - float(data[2])) / float(data[2]) * 100, 2),
        }
    except Exception as e:
        return {"available": False, "reason": str(e)[:80]}


def cross_validate_realtime(tencent: dict, sina: dict) -> dict:
    """交叉验证腾讯 vs 新浪实时行情"""
    checks = []
    all_ok = True

    def compare(metric, tv, sv, threshold_pct):
        nonlocal all_ok
        if tv is None or sv is None or sv == 0:
            return {"metric": metric, "tencent": tv, "sina": sv, "diff_pct": None, "ok": None, "note": "单源无法比较"}
        diff = abs(tv - sv) / abs(sv) * 100
        ok = diff < threshold_pct
        if not ok:
            all_ok = False
        return {"metric": metric, "tencent": tv, "sina": sv, "diff_pct": round(diff, 3), "ok": ok}

    checks.append(compare("当前价", tencent.get("price"), sina.get("price"), 0.5))
    checks.append(compare("开盘价", tencent.get("open"), sina.get("open"), 0.5))
    checks.append(compare("最高价", tencent.get("high"), sina.get("high"), 0.5))
    checks.append(compare("最低价", tencent.get("low"), sina.get("low"), 0.5))
    checks.append(compare("昨收价", tencent.get("last_close"), sina.get("last_close"), 0.5))
    checks.append(compare("涨跌幅%", tencent.get("change_pct"), sina.get("change_pct"), 0.5))

    tencent_amount = (tencent.get("amount_yi", 0) or 0)
    sina_amount = sina.get("amount_yi", 0)
    checks.append(compare("成交额(亿)", tencent_amount, sina_amount, 2.0))

    tencent_vol = (tencent.get("volume", 0) or 0) * 100
    sina_vol = sina.get("volume", 0)
    checks.append(compare("成交量(股)", tencent_vol, sina_vol, 5.0))

    passed = sum(1 for c in checks if c["ok"] is True)
    failed = sum(1 for c in checks if c["ok"] is False)
    single = sum(1 for c in checks if c["ok"] is None)

    if failed == 0 and single <= 2:
        quality = "🟢 高置信度(双源验证通过)"
    elif failed == 0:
        quality = "🟡 中等置信度(部分单源)"
    else:
        quality = f"🔴 低置信度({failed}项未通过交叉验证)"

    return {
        "passed": all_ok and failed == 0,
        "quality": quality,
        "checks": checks,
        "summary": f"通过{passed}项, 未通过{failed}项, 单源{single}项 → {quality}",
    }


def fetch_news(keyword: str) -> list[dict]:
    """获取新闻"""
    try:
        from a_stock_api import eastmoney_stock_news
        raw = eastmoney_stock_news(keyword, page_size=10)
        news = []
        for item in raw:
            news.append({
                "title": item.get("title", ""),
                "date": item.get("date", ""),
                "summary": item.get("summary", ""),
                "url": item.get("url", ""),
            })
        return news
    except Exception:
        return []


def fetch_industry_flows() -> list[dict]:
    """获取行业板块资金流"""
    try:
        from a_stock_api import industry_comparison
        return industry_comparison(top_n=50)
    except Exception:
        return []


def fetch_margin_data(code: str) -> dict:
    """拉取融资融券数据（datacenter-web API, filter用SCODE）"""
    try:
        from a_stock_api import eastmoney_datacenter
        filter_str = f"(SCODE='{code}')"
        raw = eastmoney_datacenter(
            "RPTA_WEB_RZRQ_GGMX",
            filter_str=filter_str,
            page_size=30, sort_columns="DATE", sort_types="-1",
        )
        if not raw:
            return {"available": False, "reason": "无融资融券数据"}

        records = []
        for row in raw[:30]:
            rzye = (row.get("RZYE") or 0) / 1e8
            rzmre = (row.get("RZMRE") or 0) / 1e8
            rzche = (row.get("RZCHE") or 0) / 1e8
            net_yi = rzmre - rzche
            records.append({
                "date": str(row.get("DATE", ""))[:10],
                "rzye_yi": round(rzye, 2),
                "rzmre_yi": round(rzmre, 2),
                "rzche_yi": round(rzche, 2),
                "net_yi": round(net_yi, 2),
            })

        # 趋势分析
        if len(records) >= 10:
            recent_5 = sum(r["rzye_yi"] for r in records[:5]) / 5
            prev_5 = sum(r["rzye_yi"] for r in records[5:10]) / 5
            if recent_5 > prev_5 * 1.05:
                trend = "上升"
            elif recent_5 < prev_5 * 0.95:
                trend = "下降"
            else:
                trend = "平稳"
            net_5d = sum(r["net_yi"] for r in records[:5])
            net_10d = sum(r["net_yi"] for r in records[:10])
        else:
            trend = "数据不足"
            net_5d = 0
            net_10d = 0

        return {
            "available": True,
            "latest_balance_yi": records[0]["rzye_yi"] if records else 0,
            "trend": trend,
            "net_flow_5d_yi": round(net_5d, 2),
            "net_flow_10d_yi": round(net_10d, 2),
            "records": records,
        }
    except Exception as e:
        return {"available": False, "reason": str(e)[:80]}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 2: 安全信号提取 (B轨: ETF量价版)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_selling_exhaustion(daily: list[dict]) -> dict:
    """F1: 卖压衰竭检测 (ETF版 — 量价信号)"""
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}

    recent = daily[-5:]
    declines = [abs(d["change_pct"]) for d in recent if d["change_pct"] < 0]
    is_decreasing = len(declines) >= 2 and all(
        declines[i] > declines[i+1] for i in range(len(declines)-1)
    )

    vols = [d["volume"] for d in recent]
    avg_vol_5 = sum(vols) / len(vols)
    prev_vols = [d["volume"] for d in daily[-10:-5]]
    avg_vol_prev = sum(prev_vols) / len(prev_vols) if prev_vols else avg_vol_5
    vol_shrink = avg_vol_5 < avg_vol_prev * 0.7

    lows = [d["low"] for d in recent]
    prev_lows = [d["low"] for d in daily[-10:-5]]
    no_new_low = min(lows) >= min(prev_lows) if prev_lows else False

    triggered = is_decreasing and vol_shrink and no_new_low

    return {
        "triggered": triggered,
        "signal_name": "F1: 卖压衰竭",
        "decreasing_declines": is_decreasing,
        "volume_shrink": vol_shrink,
        "no_new_low": no_new_low,
        "strength": "强" if triggered else "弱",
        "meaning": "卖压在减弱，下跌动能衰竭" if triggered else "卖压尚未衰竭，继续观察",
    }


def detect_institution_return(daily: list[dict]) -> dict:
    """F2: 大资金回流检测 (ETF版)"""
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}

    early = daily[-10:-3]
    recent = daily[-3:]

    early_changes = [d["change_pct"] for d in early]
    early_decline = sum(early_changes) < -3

    avg_vol_early = sum(d["volume"] for d in early) / len(early)
    has_bullish = any(
        d["change_pct"] > 2 and d["volume"] > avg_vol_early * 1.5
        for d in recent
    )

    triggered = early_decline and has_bullish

    return {
        "triggered": triggered,
        "signal_name": "F2: 放量反弹回流",
        "early_decline": early_decline,
        "has_bullish_volume": has_bullish,
        "strength": "强" if triggered else "弱",
        "meaning": "前期下跌后放量反弹，资金回流迹象" if triggered else "未见明确的资金回流信号",
    }


def detect_retail_exhaustion(daily: list[dict]) -> dict:
    """F3: 恐慌出尽检测 (ETF版)"""
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}

    recent = daily[-5:]
    changes = [d["change_pct"] for d in recent]

    negatives = [c for c in changes if c < 0]
    decline_narrowing = False
    if len(negatives) >= 2:
        decline_narrowing = all(
            abs(negatives[i]) > abs(negatives[i+1])
            for i in range(len(negatives)-1)
        )

    vols = [d["volume"] for d in recent]
    avg_vol_recent = sum(vols) / len(vols)
    prev_vols = [d["volume"] for d in daily[-10:-5]]
    avg_vol_prev = sum(prev_vols) / len(prev_vols) if prev_vols else avg_vol_recent
    vol_shrink = avg_vol_recent < avg_vol_prev * 0.6

    triggered = decline_narrowing and vol_shrink

    return {
        "triggered": triggered,
        "signal_name": "F3: 恐慌出尽(缩量止跌)",
        "decline_narrowing": decline_narrowing,
        "volume_shrink": vol_shrink,
        "strength": "强" if triggered else "弱",
        "meaning": "恐慌盘出清，缩量止跌" if triggered else "恐慌盘可能尚未出尽",
    }


def detect_volume_stabilization(daily: list[dict]) -> dict:
    """F8: 缩量止跌 — 底部盘整"""
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

    triggered = narrow_range and volume_shrink and amp_narrow

    return {
        "triggered": triggered,
        "signal_name": "F8: 缩量止跌盘整",
        "narrow_range": narrow_range,
        "volume_shrink": volume_shrink,
        "amp_narrow": amp_narrow,
        "avg_vol_20": round(avg_vol_20, 0),
        "recent_vol_3": round(recent_vol, 0),
        "strength": "强" if triggered else "弱",
        "meaning": "卖压枯竭，底部盘整中 → 下行空间有限" if triggered else "尚未缩量止跌，仍在波动",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 3: 危险信号检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_accelerating_selling(daily: list[dict]) -> dict:
    """F4: 加速下跌检测 (ETF版)"""
    if len(daily) < 8:
        return {"triggered": False, "reason": "数据不足"}

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
        "triggered": triggered,
        "signal_name": "F4: 🔴 加速放量下跌",
        "danger_level": "高危",
        "accelerating": accelerating,
        "volume_expanding": vol_expanding,
        "vol_surge_ratio": round(vols[-1] / avg_vol_prev, 1) if avg_vol_prev > 0 else 0,
        "meaning": "恐慌性抛售！放量加速下跌 → 绝对不要抄底！" if triggered else "下跌尚未加速",
        "action": "🚫 不买，持币观望" if triggered else "继续观察",
    }


def detect_top_distribution(daily: list[dict]) -> dict:
    """F5: 顶部逆转检测 (ETF版)"""
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}

    early = daily[-10:-3]
    recent_2 = daily[-2:]

    early_closes = [d["close"] for d in early]
    if len(early_closes) < 2:
        return {"triggered": False}
    early_rise = (early_closes[-1] - early_closes[0]) / early_closes[0] * 100 if early_closes[0] > 0 else 0

    avg_vol_early = sum(d["volume"] for d in early) / len(early) if early else 1
    has_distribution = any(
        d["change_pct"] < -3 and d["volume"] > avg_vol_early * 2
        for d in recent_2
    )

    triggered = early_rise > 10 and has_distribution

    return {
        "triggered": triggered,
        "signal_name": "F5: 🔴 高位放量逆转",
        "danger_level": "高危",
        "early_rise_pct": round(early_rise, 1),
        "has_distribution": has_distribution,
        "meaning": f"前期涨{early_rise:.0f}%+放量逆转 → 典型的顶部派发信号" if triggered else "无顶部派发信号",
        "action": "🚫 不追高，已持有则考虑减仓" if triggered else "继续观察",
    }


def detect_news_exhausted(daily: list[dict], news: list[dict]) -> dict:
    """F7: 利好出尽检测"""
    if not news:
        return {"triggered": False, "reason": "无消息数据"}

    bullish_keywords = ['涨', '走强', '涨停', '利好', '突破', '新高', '订单', '扩产']
    bullish_news = []
    for n in news:
        title = n.get("title", "")
        if any(kw in title for kw in bullish_keywords):
            bullish_news.append(n)

    if not bullish_news:
        return {"triggered": False, "reason": "无明确利好消息"}

    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}

    early = daily[-15:-5] if len(daily) >= 15 else daily[:-5]
    if len(early) < 5:
        return {"triggered": False}

    early_closes = [d["close"] for d in early]
    pre_rise = (early_closes[-1] - early_closes[0]) / early_closes[0] * 100 if early_closes[0] > 0 else 0

    recent = daily[-2:]
    high_open_low_close = any(
        d["change_pct"] < -3 for d in recent
    )

    triggered = pre_rise > 10 and high_open_low_close and len(bullish_news) > 0

    return {
        "triggered": triggered,
        "signal_name": "F7: 🔴 利好出尽/高开低走",
        "danger_level": "非常高",
        "pre_rise_2w": round(pre_rise, 1),
        "latest_news": bullish_news[0].get("title", "")[:60] if bullish_news else "",
        "meaning": f"前期涨{pre_rise:.0f}%+利好兑现高开低走 → 大概率回调" if triggered else "前期涨幅可接受或未出现利好兑现",
        "action": "🚫 不要追！等回调充分后再评估" if triggered else "",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 4: 企稳确认检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_stabilization(daily: list[dict]) -> dict:
    """企稳确认检查清单（5项，ETF版本）"""
    if len(daily) < 15:
        return {"is_stabilized": False, "reason": "数据不足"}

    recent = daily[-3:]
    prev_10 = daily[-15:-3]

    checks = {}

    # 1: 不再创新低
    recent_lows = [d["low"] for d in recent]
    prev_lows = [d["low"] for d in prev_10]
    checks["no_new_low"] = min(recent_lows) >= min(prev_lows)

    # 2: 振幅收窄
    amplitudes = [d["amplitude"] for d in recent]
    checks["narrow_range"] = all(a < 5 for a in amplitudes)

    # 3: 成交量回归正常
    avg_vol_prev = sum(d["volume"] for d in prev_10) / len(prev_10)
    recent_vol = sum(d["volume"] for d in recent) / 3
    checks["volume_normal"] = recent_vol < avg_vol_prev * 1.5

    # 4: 最低价抬高
    checks["lows_rising"] = recent_lows[-1] >= recent_lows[0] if len(recent_lows) >= 2 else False

    # 5: 站上5日均线
    prices = [d["close"] for d in daily[-8:]]
    if len(prices) >= 6:
        ma5 = sum(prices[-6:-1]) / 5
        checks["above_ma5"] = prices[-1] > ma5
    else:
        checks["above_ma5"] = False

    passed = sum(1 for v in checks.values() if v)
    is_stabilized = passed >= 4

    return {
        "is_stabilized": is_stabilized,
        "passed_count": passed,
        "total_count": 5,
        "checks": checks,
        "meaning": "企稳确认，下行风险大幅降低" if is_stabilized else f"仅通过{passed}/5项，尚未企稳",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 4b: 安全评分计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_safety_score(safety_signals: dict, danger_signals: dict, daily: list[dict],
                      margin_data: dict = None) -> dict:
    """安全区间综合评分 (0-100) — ETF版 + 融资修正"""
    score = 50
    adjustment_details = []

    # 安全信号加分
    if safety_signals.get("f1_exhaustion", {}).get("triggered"):
        score += 12
        adjustment_details.append(("F1 卖压衰竭", +12))
    if safety_signals.get("f2_institution_return", {}).get("triggered"):
        score += 10
        adjustment_details.append(("F2 放量反弹回流", +10))
    if safety_signals.get("f3_retail_exhaustion", {}).get("triggered"):
        score += 10
        adjustment_details.append(("F3 恐慌出尽", +10))
    if safety_signals.get("f8_volume_stabilization", {}).get("triggered"):
        score += 8
        adjustment_details.append(("F8 缩量止跌", +8))

    # 危险信号减分
    if danger_signals.get("f4_accelerating", {}).get("triggered"):
        score -= 22
        adjustment_details.append(("F4 加速放量下跌", -22))
    if danger_signals.get("f5_top_distribution", {}).get("triggered"):
        score -= 20
        adjustment_details.append(("F5 高位放量逆转", -20))
    if danger_signals.get("f7_news_exhausted", {}).get("triggered"):
        score -= 15
        adjustment_details.append(("F7 利好出尽", -15))

    # 企稳确认
    stabilization = check_stabilization(daily)
    if stabilization["is_stabilized"]:
        score += 10
        adjustment_details.append(("企稳确认", +10))

    # 趋势强度修正
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

    # 成交量异常修正
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

    # 融资趋势修正（V1.4）
    if margin_data and margin_data.get("available"):
        trend = margin_data.get("trend", "")
        net_5d = margin_data.get("net_flow_5d_yi", 0)
        if trend == "下降" and net_5d < -1:
            score -= 7
            adjustment_details.append(("融资去杠杆(趋势下降)", -7))
        elif trend == "下降" and net_5d < 0:
            score -= 4
            adjustment_details.append(("融资温和去杠杆", -4))
        elif trend == "上升" and net_5d > 2:
            score += 5
            adjustment_details.append(("融资加杠杆(趋势上升)", +5))
        elif trend == "上升" and net_5d > 0:
            score += 3
            adjustment_details.append(("融资温和上升", +3))

    score = max(0, min(100, score))

    # 安全等级
    if score >= 75:
        level = "🟢 安全区间"
        can_enter = True
        description = "下行风险可控，可考虑入场（配合买入参考条件）"
    elif score >= 60:
        level = "🟡 接近安全"
        can_enter = False
        description = "部分条件满足，再等1-3日确认"
    elif score >= 40:
        level = "🟠 风险区间"
        can_enter = False
        description = "安全信号不足或有危险信号，不建议入场"
    else:
        level = "🔴 危险区间"
        can_enter = False
        description = "存在高危信号，远离，持币观望"

    positive = [sig.get("signal_name", key) for key, sig in safety_signals.items() if sig.get("triggered")]
    negative = [sig.get("signal_name", key) for key, sig in danger_signals.items() if sig.get("triggered")]

    return {
        "safety_score": score,
        "safety_level": level,
        "can_enter": can_enter,
        "description": description,
        "positive_signals": positive,
        "negative_signals": negative,
        "adjustment_details": adjustment_details,
        "stabilization": stabilization,
        "principle": "可以少挣，必须少亏 — 只有 ≥75 分才建议考虑入场",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 5: 买卖时机参考
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_timing(safety_score: dict, daily: list[dict]) -> dict:
    """生成买卖时机参考"""
    entry_conditions = []

    entry_conditions.append({
        "condition": "安全评分 ≥ 75分",
        "met": safety_score["safety_score"] >= 75,
        "current": f"{safety_score['safety_score']}分",
        "weight": "必须",
    })

    entry_conditions.append({
        "condition": "企稳确认 (≥4/5项)",
        "met": safety_score["stabilization"]["is_stabilized"],
        "current": f"{safety_score['stabilization']['passed_count']}/5项",
        "weight": "必须",
    })

    pos_count = len(safety_score["positive_signals"])
    entry_conditions.append({
        "condition": "≥2个安全信号触发",
        "met": pos_count >= 2,
        "current": f"{pos_count}个",
        "weight": "建议",
    })

    neg_count = len(safety_score["negative_signals"])
    entry_conditions.append({
        "condition": "无危险信号",
        "met": neg_count == 0,
        "current": f"{neg_count}个危险信号" if neg_count > 0 else "0个",
        "weight": "必须",
    })

    recent_3 = daily[-3:] if len(daily) >= 3 else daily
    has_confirmation = any(
        d["change_pct"] > 2 for d in recent_3
    )
    entry_conditions.append({
        "condition": "近日放量阳线确认（增强信号）",
        "met": has_confirmation,
        "current": "已出现" if has_confirmation else "未出现",
        "weight": "加分项（非必须）",
    })

    must_met = all(c["met"] for c in entry_conditions if c["weight"] == "必须")
    all_met = all(c["met"] for c in entry_conditions)

    exit_conditions = []
    exit_conditions.append({
        "condition": "🔴 硬止损: 持仓亏损>5% + 仍在放量下跌",
        "triggered": False,
        "rule": "亏损的数学是不对称的",
        "action": "全部离场",
    })
    exit_conditions.append({
        "condition": "🟠 利润保护: 盈利>5% + 出现放量阴线",
        "triggered": False,
        "rule": "可以少挣，必须少亏",
        "action": "至少减仓50%",
    })
    exit_conditions.append({
        "condition": "🔴 任何高危信号触发 (F4/F5/F7)",
        "triggered": neg_count > 0,
        "current": f"{neg_count}个危险信号" if neg_count > 0 else "无",
        "rule": "危险信号 > 一切买入信号",
        "action": "不买，已持有则评估是否离场",
    })
    exit_conditions.append({
        "condition": "🔴 安全评分降至 < 40分",
        "triggered": safety_score["safety_score"] < 40,
        "current": f"{safety_score['safety_score']}分",
        "rule": "危险区间 = 持币观望",
        "action": "远离，等安全评分回升",
    })

    return {
        "entry": {
            "ready": must_met,
            "ready_enhanced": all_met,
            "conditions": entry_conditions,
            "verdict": (
                "✅ 买入参考条件全部满足，可考虑入场"
                if all_met else (
                    "⚠️ 必要条件满足但增强信号不足，可小仓试探"
                    if must_met else
                    "❌ 买入条件不满足，继续等待"
                )
            ),
        },
        "exit": {
            "any_triggered": any(c["triggered"] for c in exit_conditions),
            "conditions": exit_conditions,
        },
        "principle": "可以少挣，必须少亏 — 宁可错过，不可做错",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 6: 主流程 + 输出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    code = "588000"
    target_name = "科创50ETF华夏"
    print(f"[识别] ETF(上海): {target_name} ({code})")

    # ━━ 1. 拉取数据 ━━
    print("[1/6] 拉取60天日K线(腾讯)...")
    kline = fetch_kline_tencent(code, days=60)

    print("[2/6] 拉取实时行情(腾讯+新浪交叉验证)...")
    realtime = fetch_realtime_tencent(code)
    sina = fetch_realtime_sina(code)
    validation = None
    if sina.get("available") and realtime:
        validation = cross_validate_realtime(realtime, sina)
        realtime["_validation"] = validation
        realtime["_sources"] = ["腾讯", "新浪"]
        print(f"  数据质量: {validation.get('quality', '未知')}")
    elif realtime:
        realtime["_validation"] = {
            "passed": None, "quality": "🟡 单源(新浪不可用)",
            "checks": [], "summary": f"仅腾讯单源 — 新浪: {sina.get('reason', '未知')}"
        }
        realtime["_sources"] = ["腾讯"]
        print(f"  数据质量: 仅腾讯单源")

    # 合并K线和实时行情
    if kline and realtime:
        last = kline[-1]
        if last["date"] == datetime.now().strftime("%Y-%m-%d"):
            last["close"] = realtime["price"]
            last["open"] = realtime["open"]
            last["high"] = realtime["high"]
            last["low"] = realtime["low"]
            last["volume"] = realtime["volume"]

    daily = kline
    print(f"  获取 {len(daily)} 个交易日")

    print("[3/6] 拉取新闻(科创50)...")
    news = fetch_news("科创50")

    print("[4/6] 拉取行业资金流...")
    industry_flow = fetch_industry_flows()

    print("[5/6] 拉取融资融券数据...")
    margin_data = fetch_margin_data(code)
    if margin_data.get("available"):
        print(f"  融资余额: {margin_data.get('latest_balance_yi', 0):.2f}亿 | 趋势: {margin_data.get('trend', '')}")

    # ━━ 2. 信号检测 ━━
    print("[6/6] 信号检测+安全评分...")
    safety_signals = {
        "f1_exhaustion": detect_selling_exhaustion(daily),
        "f2_institution_return": detect_institution_return(daily),
        "f3_retail_exhaustion": detect_retail_exhaustion(daily),
        "f8_volume_stabilization": detect_volume_stabilization(daily),
    }

    danger_signals = {
        "f4_accelerating": detect_accelerating_selling(daily),
        "f5_top_distribution": detect_top_distribution(daily),
        "f7_news_exhausted": detect_news_exhausted(daily, news),
    }

    safety_score = calc_safety_score(safety_signals, danger_signals, daily, margin_data)
    timing = generate_timing(safety_score, daily)

    # ━━ 价格摘要 ━━
    today = daily[-1] if daily else {}
    week_ago = daily[-6] if len(daily) >= 6 else daily[0]
    month_ago = daily[-22] if len(daily) >= 22 else daily[0]

    # ━━ 构建报告 ━━
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": code,
        "target_type": "etf",
        "target_name": target_name,
        "track": "B",
        "track_label": "ETF轨(量价+消息面)",
        "summary": {
            "price": realtime.get("price", today.get("close", 0)),
            "last_close": realtime.get("last_close", 0),
            "change": realtime.get("change", 0),
            "change_pct": realtime.get("change_pct", 0),
            "high": realtime.get("high", 0),
            "low": realtime.get("low", 0),
            "volume": realtime.get("volume", 0),
            "amount_yi": realtime.get("amount_yi", 0),
            "change_1w": round((today.get("close", 0) - week_ago.get("close", 0)) / week_ago.get("close", 1) * 100, 1),
            "change_1m": round((today.get("close", 0) - month_ago.get("close", 0)) / month_ago.get("close", 1) * 100, 1),
        },
        "realtime": realtime,
        "daily": daily,
        "industry_flow": industry_flow,
        "margin_data": margin_data,
        "safety_signals": safety_signals,
        "danger_signals": danger_signals,
        "safety_score": safety_score,
        "timing": timing,
        "news": news[:8] if news else [],
        "principle": "可以少挣，必须少亏。所有判断基于数据，每个信号绑定可验证条件。",
    }

    # ━━ 打印报告 ━━
    _print_report(report)

    # ━━ 保存报告 ━━
    output_dir = f"src/资金预判/{datetime.now().strftime('%Y-%m-%d')}-{target_name}-{code}-安全评估"
    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    md_path = os.path.join(output_dir, "report.md")
    _save_markdown(report, md_path)

    print(f"\n报告已保存: {output_dir}/")
    return report


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Console 打印 (V1.5 Part 2 统一版: 2A/2B/2C)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _print_report(report: dict):
    """打印完整安全评估报告"""
    print()
    print("=" * 80)
    print("  🛡️  买入安全区间研判报告 (V1.6)")
    print(f"  标的: {report['target_name']} ({report['target']})")
    print(f"  类型: {report['target_type']} | 信号轨: {report.get('track_label', '')}")
    print(f"  生成: {report['generated_at']} | 原则: 可以少挣，必须少亏")
    print("=" * 80)

    # ━━ Part 1: 核心结论 ━━
    score = report["safety_score"]
    summary = report["summary"]
    realtime = report.get("realtime", {})
    validation = realtime.get("_validation", {})

    print()
    print("━" * 60)
    print("  🎯 Part 1: 核心结论")
    print("━" * 60)
    print(f"  当前价格: {summary['price']:.3f} | "
          f"涨跌: {summary['change']:+.3f} ({summary['change_pct']:+.2f}%)")
    print(f"  1周涨跌: {summary['change_1w']:+.1f}% | "
          f"1月涨跌: {summary['change_1m']:+.1f}%")
    if validation:
        print(f"  数据质量: {validation.get('quality', '未知')} | {validation.get('summary', '')}")
    print(f"  数据来源: 行情[腾讯+新浪] | K线[腾讯] | 融资融券[东财单源]")
    print(f"  安全评分: {score['safety_score']}/100 → {score['safety_level']}")
    print(f"  企稳状态: {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} "
          f"({score['stabilization']['passed_count']}/5项)")
    print(f"  能否入场: {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'}")
    print(f"  判断依据: {score['description']}")

    print(f"\n  📊 评分构成 (基准50):")
    for detail, adj in score["adjustment_details"]:
        sign = "+" if adj > 0 else ""
        print(f"     {sign}{adj:>+3d}  {detail}")

    # ━━ Part 2: 近20日日度数据明细 ━━
    print()
    print("━" * 70)
    print("  📋 Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）")
    print("━" * 70)
    daily = report.get("daily", [])

    # ═══ 2A: 日度量价明细 ═══
    print()
    print("  ━" * 55)
    print("    📈 2A: 日度量价明细")
    print("  ━" * 55)

    if daily:
        vols = [d["volume"] for d in daily[-25:-5] if d.get("volume")]
        avg_vol_20 = sum(vols) / len(vols) if vols else 1
        all_vols = [d["volume"] for d in daily if d.get("volume")]
        all_prices = [d["close"] for d in daily if d.get("close")]
        vol_max = max(all_vols) if all_vols else 1
        vol_min = min(all_vols) if all_vols else 0
        price_60h = max(all_prices) if all_prices else 1
        price_60l = min(all_prices) if all_prices else 0

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

            turnover = realtime.get("turnover", 0) if date == daily[-1]["date"] else 0
            if turnover == 0:
                float_shares = 5e8  # ETF默认5亿份
                if realtime.get("amount_yi") and realtime.get("price"):
                    float_shares = realtime["amount_yi"] / realtime["price"] * 1e8
                turnover = round(vol / float_shares * 100, 2) if float_shares > 0 else 0

            vol_ratio = round(vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0
            vol_pct = round((vol - vol_min) / (vol_max - vol_min) * 100, 0) if vol_max > vol_min else 50
            price_pct = round((close - price_60l) / (price_60h - price_60l) * 100, 0) if price_60h > price_60l else 50

            if chg > 5: trend = "🔥大涨"
            elif chg > 2: trend = "📈上涨"
            elif chg > -2: trend = "➖震荡"
            elif chg > -5: trend = "📉下跌"
            else: trend = "💧暴跌"

            vr = "🔴" if vol_ratio > 2.5 else ("🟠" if vol_ratio > 1.5 else ("🔵" if vol_ratio < 0.5 else "  "))
            vp_mark = "🔴" if vol_pct > 90 else ("🟠" if vol_pct > 70 else ("🔵" if vol_pct < 30 else "  "))
            pp_mark = "🔴" if price_pct > 90 else ("🟠" if price_pct > 70 else ("🔵" if price_pct < 30 else "  "))

            print(f"  {date:<12s} {close:>8.3f} {chg:>+6.2f}% {amp:>5.2f}% "
                  f"{turnover:>5.2f}% {vr}{vol_ratio:>5.1f}x "
                  f"{vp_mark}{vol_pct:>5.0f}% {pp_mark}{price_pct:>5.0f}% {trend}")

        print(sub_header)
        today = daily[-1] if daily else {}
        today_vol = today.get("volume", 0)
        today_vol_ratio = round(today_vol / avg_vol_20, 1) if avg_vol_20 > 0 else 0
        today_vol_pct = round((today_vol - vol_min) / (vol_max - vol_min) * 100, 0) if vol_max > vol_min else 50
        today_price_pct = round((today.get("close", 0) - price_60l) / (price_60h - price_60l) * 100, 0) if price_60h > price_60l else 50

        print(f"  📊 今日量:{today_vol:,.0f} | 量比:{today_vol_ratio:.1f}x | "
              f"量分位:{today_vol_pct:.0f}%(60日) | 价分位:{today_price_pct:.0f}%(60日)")
        print(f"  📊 20日均量:{avg_vol_20:,.0f} | "
              f"60日最高价:{price_60h:.3f} | 60日最低价:{price_60l:.3f} | "
              f"距高:{(today.get('close',0)/price_60h-1)*100:+.1f}% | 距低:{(today.get('close',0)/price_60l-1)*100:+.1f}%")

        all_changes = [d["change_pct"] for d in daily[-20:]]
        big_up = sum(1 for c in all_changes if c > 5)
        up = sum(1 for c in all_changes if 2 < c <= 5)
        flat = sum(1 for c in all_changes if -2 <= c <= 2)
        down = sum(1 for c in all_changes if -5 <= c < -2)
        big_down = sum(1 for c in all_changes if c < -5)
        print(f"  📊 近20日涨跌分布: 🔥大涨{big_up}天 📈上涨{up}天 ➖震荡{flat}天 📉下跌{down}天 💧暴跌{big_down}天")

    # ═══ 2B: 资金流向详细 (B轨: 行业资金流代理) ═══
    print()
    print("  ━" * 55)
    print("    💰 2B: 资金流向详细 (行业资金流代理)")
    print("  ━" * 55)
    industry_flows = report.get("industry_flow", [])
    if industry_flows:
        # 筛选与科创板/科技相关的行业
        tech_keywords = ['半导体', '电子', '芯片', '计算机', '通信', '软件', '人工智能', '科创', '科技']
        related = []
        for f in industry_flows:
            name = f.get('name', '')
            if any(kw in name for kw in tech_keywords):
                related.append(f)
        if not related:
            related = industry_flows[:5]

        print(f"  科技相关行业资金流(市场环境参考):")
        for f in related[:8]:
            name = f.get('name', '')
            chg = f.get('change_pct', 0)
            main_net = f.get('main_net', 0)
            print(f"     {name}: 涨跌{chg:+.2f}% | 主力净流{main_net/1e8:+.2f}亿")
    else:
        print(f"  行业资金流: 暂不可取")

    # ═══ 2C: 融资融券明细 ═══
    print()
    print("  ━" * 55)
    print("    🏦 2C: 融资融券明细")
    print("  ━" * 55)
    margin_data = report.get("margin_data") or report.get("auxiliary_data", {}).get("margin", {})
    if margin_data and margin_data.get("available"):
        balance = margin_data.get("latest_balance_yi") or margin_data.get("latest_margin_balance_yi", 0)
        trend = margin_data.get("trend") or margin_data.get("margin_trend", "平稳")
        net_5d = margin_data.get("net_flow_5d_yi") or margin_data.get("net_margin_flow_5d_yi", 0)
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
        print(f"  融资融券: 数据暂不可取（ETF通常无融资融券数据）")

    # ━━ Part 3: 信号检测 ━━
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

    # ━━ Part 4: 企稳确认清单 ━━
    print()
    print("━" * 60)
    print("  📋 Part 4: 企稳确认清单 (需 ≥4/5)")
    print("━" * 60)
    checks = score["stabilization"]["checks"]
    labels = {
        "no_new_low": "不再创新低",
        "narrow_range": "振幅 < 5%",
        "volume_normal": "成交量不异常放大",
        "lows_rising": "最低价抬高",
        "above_ma5": "站上5日均线",
    }
    for key, label in labels.items():
        ok = checks.get(key, False)
        print(f"  {'✅' if ok else '❌'} {label}")

    # ━━ Part 5: 买入时机 ━━
    timing = report["timing"]
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

    # ━━ Part 6: 离场预警 ━━
    print()
    print("━" * 60)
    print("  🚪 Part 6: 离场/风控参考")
    print("━" * 60)
    for cond in timing["exit"]["conditions"]:
        triggered = cond.get("triggered", False)
        icon = "🔴" if triggered else "  "
        print(f"  {icon} {cond['condition']}")
        if triggered:
            print(f"     规则: {cond.get('rule', '')}")
            print(f"     建议: {cond.get('action', '')}")

    # ━━ Part 7: 关键消息 ━━
    news = report.get("news", [])
    if news:
        print()
        print("━" * 60)
        print("  📰 Part 7: 近期关键消息")
        print("━" * 60)
        for n in news[:6]:
            print(f"  [{n.get('date', '')[:10]}] {n.get('title', '')[:80]}")
            summary = n.get('summary', '')[:100]
            if summary:
                print(f"         {summary}")

    # ━━ Footer ━━
    print()
    print("=" * 80)
    print("  ⚠️ 研究声明:")
    print("  1. 安全评分基于可验证的价格/成交量/消息面规则，每条规则可被盘面验证")
    print("  2. 买入/卖出参考条件是可验证的信号框架，不是买卖指令")
    print("  3. 核心原则: 可以少挣，必须少亏 — 安全评分<60坚决不入场")
    print("  4. 亏损的数学是不对称的: 亏50%需涨100%回本")
    print("  5. 数据来源: 行情[腾讯+新浪] | K线[腾讯] | 融资融券[东财单源]")
    print("  6. ETF分析基于价格+成交量+消息面+融资融券，无个股资金流维度")
    print("  7. 所有分析基于公开数据，不构成投资建议")
    print("=" * 80)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Markdown 保存 (V1.5 Part 2 统一版: 2A/2B/2C)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _save_markdown(report: dict, path: str):
    """保存 Markdown 报告"""
    score = report["safety_score"]
    summary = report["summary"]
    daily = report["daily"]
    timing = report["timing"]
    realtime = report.get("realtime", {})
    validation = realtime.get("_validation", {})

    lines = []
    lines.append(f"# 🛡️ 买入安全区间研判报告")
    lines.append(f"")
    lines.append(f"**标的**: {report['target_name']} ({report['target']}) | **类型**: ETF | **信号轨**: {report.get('track_label', '')}")
    lines.append(f"**生成时间**: {report['generated_at']} | **核心原则**: 可以少挣，必须少亏")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 1: 核心结论")
    lines.append(f"")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 当前价格 | {summary['price']:.3f} |")
    lines.append(f"| 涨跌幅 | {summary['change']:+.3f} ({summary['change_pct']:+.2f}%) |")
    lines.append(f"| 1周涨跌 | {summary['change_1w']:+.1f}% |")
    lines.append(f"| 1月涨跌 | {summary['change_1m']:+.1f}% |")
    if validation:
        lines.append(f"| 数据质量 | {validation.get('quality', '未知')} |")
    lines.append(f"| 安全评分 | **{score['safety_score']}/100** → {score['safety_level']} |")
    lines.append(f"| 企稳状态 | {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} ({score['stabilization']['passed_count']}/5项) |")
    lines.append(f"| 能否入场 | {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'} |")
    lines.append(f"")
    lines.append(f"> **数据来源**: 行情[腾讯+新浪交叉验证] | K线[腾讯] | 融资融券[东财单源]")
    lines.append(f"")
    lines.append(f"**判断依据**: {score['description']}")
    lines.append(f"")
    lines.append(f"### 评分构成 (基准50)")
    lines.append(f"")
    for detail, adj in score["adjustment_details"]:
        sign = "+" if adj > 0 else ""
        lines.append(f"- {sign}{adj:>+3d}  {detail}")
    lines.append(f"")

    # ━━ Part 2: 近20日日度数据明细 ━━
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）")
    lines.append(f"")

    # 2A: 日度量价明细
    lines.append(f"### 2A: 日度量价明细")
    lines.append(f"")
    if daily:
        vols = [d["volume"] for d in daily[-25:-5] if d.get("volume")]
        avg_vol_20 = sum(vols) / len(vols) if vols else 1
        all_vols_md = [d["volume"] for d in daily if d.get("volume")]
        all_prices_md = [d["close"] for d in daily if d.get("close")]
        vol_max_md = max(all_vols_md) if all_vols_md else 1
        vol_min_md = min(all_vols_md) if all_vols_md else 0
        price_60h_md = max(all_prices_md) if all_prices_md else 1
        price_60l_md = min(all_prices_md) if all_prices_md else 0

        lines.append(f"| 日期 | 收盘 | 涨跌幅 | 振幅 | 换手率 | 量比 | 价分位 | 走势 |")
        lines.append(f"|------|------|--------|------|--------|------|--------|------|")
        for d in daily[-20:]:
            date = d.get("date", "")
            close = d.get("close", 0)
            chg = d.get("change_pct", 0)
            amp = d.get("amplitude", 0)
            vol = d.get("volume", 0)
            float_shares = 5e8
            if realtime.get("amount_yi") and realtime.get("price"):
                float_shares = realtime["amount_yi"] / realtime["price"] * 1e8
            turnover_md = round(vol / float_shares * 100, 2) if float_shares > 0 else 0
            vol_ratio_md = round(vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0
            price_pct_md = round((close - price_60l_md) / (price_60h_md - price_60l_md) * 100, 0) if price_60h_md > price_60l_md else 50

            if chg > 5: trend = "🔥大涨"
            elif chg > 2: trend = "📈上涨"
            elif chg > -2: trend = "➖震荡"
            elif chg > -5: trend = "📉下跌"
            else: trend = "💧暴跌"

            lines.append(f"| {date} | {close:.3f} | {chg:+.2f}% | {amp:.2f}% | {turnover_md:.2f}% | {vol_ratio_md:.1f}x | {price_pct_md:.0f}% | {trend} |")

        today_md = daily[-1] if daily else {}
        today_vol_md = today_md.get("volume", 0)
        today_vol_ratio_md = round(today_vol_md / avg_vol_20, 1) if avg_vol_20 > 0 else 0
        today_vol_pct_md = round((today_vol_md - vol_min_md) / (vol_max_md - vol_min_md) * 100, 0) if vol_max_md > vol_min_md else 50
        today_price_pct_md = round((today_md.get("close", 0) - price_60l_md) / (price_60h_md - price_60l_md) * 100, 0) if price_60h_md > price_60l_md else 50
        lines.append(f"")
        lines.append(f"> **今日量**: {today_vol_md:,.0f} | **量比**: {today_vol_ratio_md:.1f}x | **量分位(60日)**: {today_vol_pct_md:.0f}% | **价分位(60日)**: {today_price_pct_md:.0f}%")
        lines.append(f"> **20日均量**: {avg_vol_20:,.0f} | **60日最高价**: {price_60h_md:.3f} | **60日最低价**: {price_60l_md:.3f}")
    lines.append(f"")

    # 2B: 资金流向详细
    lines.append(f"### 2B: 资金流向详细 (行业资金流代理)")
    lines.append(f"")
    industry_flows = report.get("industry_flow", [])
    if industry_flows:
        tech_keywords = ['半导体', '电子', '芯片', '计算机', '通信', '软件', '人工智能', '科创', '科技']
        related = []
        for f in industry_flows:
            name = f.get('name', '')
            if any(kw in name for kw in tech_keywords):
                related.append(f)
        if not related:
            related = industry_flows[:5]

        lines.append(f"| 行业 | 涨跌幅 | 主力净流(亿) |")
        lines.append(f"|------|--------|-------------|")
        for f in related[:8]:
            name = f.get('name', '')
            chg = f.get('change_pct', 0)
            main_net = f.get('main_net', 0)
            lines.append(f"| {name} | {chg:+.2f}% | {main_net/1e8:+.2f} |")
    else:
        lines.append(f"行业资金流: 暂不可取")
    lines.append(f"")

    # 2C: 融资融券明细
    lines.append(f"### 2C: 融资融券明细")
    lines.append(f"")
    margin_data = report.get("margin_data") or report.get("auxiliary_data", {}).get("margin", {})
    if margin_data and margin_data.get("available"):
        balance = margin_data.get("latest_balance_yi") or margin_data.get("latest_margin_balance_yi", 0)
        trend = margin_data.get("trend") or margin_data.get("margin_trend", "平稳")
        net_5d = margin_data.get("net_flow_5d_yi") or margin_data.get("net_margin_flow_5d_yi", 0)
        net_10d = margin_data.get("net_flow_10d_yi", 0)
        lines.append(f"**最新融资余额**: {balance:.2f}亿 | **趋势**: {trend}")
        lines.append(f"**近5日净买卖**: {net_5d:+.2f}亿 | **近10日净买卖**: {net_10d:+.2f}亿")
        records_md = margin_data.get("records", [])
        if records_md:
            lines.append(f"")
            lines.append(f"| 日期 | 融资余额(亿) | 买入额(亿) | 偿还额(亿) | 净买卖(亿) |")
            lines.append(f"|------|------------|-----------|-----------|-----------|")
            for r in records_md[:10]:
                lines.append(f"| {r.get('date','')} | {r.get('rzye_yi',0):.2f} | {r.get('rzmre_yi',0):.2f} | {r.get('rzche_yi',0):.2f} | {r.get('net_yi',0):+.2f} |")
    else:
        lines.append(f"融资融券: 数据暂不可取（ETF通常无融资融券数据）")
    lines.append(f"")

    # 信号
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 3: 安全信号检测")
    lines.append(f"")
    for key, sig in report["safety_signals"].items():
        triggered = sig.get("triggered", False)
        icon = "🟢" if triggered else "⚪"
        lines.append(f"- {icon} **{sig.get('signal_name', key)}**: {sig.get('meaning', '')}")
    lines.append(f"")

    lines.append(f"## Part 3b: 危险信号检测")
    lines.append(f"")
    any_danger = False
    for key, sig in report["danger_signals"].items():
        triggered = sig.get("triggered", False)
        if triggered:
            any_danger = True
            lines.append(f"- 🔴 **{sig.get('signal_name', key)}** (危险等级: {sig.get('danger_level', '')})")
            lines.append(f"  - {sig.get('meaning', '')}")
            lines.append(f"  - → {sig.get('action', '')}")
    if not any_danger:
        lines.append(f"✅ 未检测到高危信号")
    lines.append(f"")

    # 企稳
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 4: 企稳确认清单 (需 ≥4/5)")
    lines.append(f"")
    checks = score["stabilization"]["checks"]
    labels = {
        "no_new_low": "不再创新低",
        "narrow_range": "振幅 < 5%",
        "volume_normal": "成交量不异常放大",
        "lows_rising": "最低价抬高",
        "above_ma5": "站上5日均线",
    }
    for key, label in labels.items():
        ok = checks.get(key, False)
        lines.append(f"- {'✅' if ok else '❌'} {label}")
    lines.append(f"")

    # 时机
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 5: 买入时机参考条件")
    lines.append(f"")
    for cond in timing["entry"]["conditions"]:
        met = cond["met"]
        icon = "✅" if met else "❌"
        lines.append(f"- {icon} [{cond['weight']}] {cond['condition']} — 当前: {cond['current']}")
    lines.append(f"")
    lines.append(f"**综合判断**: {timing['entry']['verdict']}")
    lines.append(f"")

    # 离场
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 6: 离场/风控参考")
    lines.append(f"")
    for cond in timing["exit"]["conditions"]:
        triggered = cond.get("triggered", False)
        icon = "🔴" if triggered else "  "
        lines.append(f"- {icon} {cond['condition']}")
        if triggered:
            lines.append(f"  - 规则: {cond.get('rule', '')}")
            lines.append(f"  - 建议: {cond.get('action', '')}")
    lines.append(f"")

    # 消息
    news = report.get("news", [])
    if news:
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Part 7: 近期关键消息")
        lines.append(f"")
        for n in news[:6]:
            lines.append(f"- [{n.get('date', '')[:10]}] {n.get('title', '')}")
            s = n.get('summary', '')
            if s:
                lines.append(f"  - {s[:120]}")

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## ⚠️ 研究声明")
    lines.append(f"")
    lines.append(f"1. 安全评分基于可验证的价格/成交量/消息面规则")
    lines.append(f"2. 买入/卖出参考条件是可验证的信号框架，不是买卖指令")
    lines.append(f"3. 核心原则: 可以少挣，必须少亏 — 安全评分<60坚决不入场")
    lines.append(f"4. 亏损的数学是不对称的: 亏50%需涨100%回本")
    lines.append(f"5. 数据来源: 行情[腾讯+新浪交叉验证] | K线[腾讯] | 融资融券[东财单源]")
    lines.append(f"6. ETF分析基于价格+成交量+消息面+融资融券，无个股资金流维度")
    lines.append(f"7. 所有分析基于公开数据，不构成投资建议")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
