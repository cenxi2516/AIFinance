#!/usr/bin/env python3
"""
fund-flow-predictor 完整分析脚本
标的: 半导体设备ETF国泰 (159516)
日期: 2026-07-10
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
    """从腾讯获取日K线（前复权）"""
    r = requests.get(
        'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
        params={'param': f'sz{code},day,,,{days},qfq'},
        timeout=15
    )
    data = r.json()
    raw = data.get('data', {}).get(f'sz{code}', {}).get('qfqday', [])
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
    """从腾讯获取实时行情"""
    r = requests.get(f'http://qt.gtimg.cn/q=sz{code}', timeout=10)
    text = r.text
    # 格式: v_sz159516="51~name~code~price~last_close~open~volume~..."
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 2: 安全信号提取
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_selling_exhaustion(daily: list[dict]) -> dict:
    """
    F1: 卖压衰竭检测
    由于ETF没有主力资金流数据，基于价格+成交量判断：
    1. 近5日跌幅逐日收窄
    2. 成交量萎缩至前5日均量的70%以下
    3. 股价不再创新低
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}

    recent = daily[-5:]
    # 跌幅收窄
    declines = [abs(d["change_pct"]) for d in recent if d["change_pct"] < 0]
    is_decreasing = len(declines) >= 2 and all(
        declines[i] > declines[i+1] for i in range(len(declines)-1)
    )

    # 成交量萎缩
    vols = [d["volume"] for d in recent]
    avg_vol_5 = sum(vols) / len(vols)
    prev_vols = [d["volume"] for d in daily[-10:-5]]
    avg_vol_prev = sum(prev_vols) / len(prev_vols) if prev_vols else avg_vol_5
    vol_shrink = avg_vol_5 < avg_vol_prev * 0.7

    # 不再创新低
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
    """
    F2: 大资金回流检测 (ETF版本)
    基于价格+成交量判断：
    1. 前期(前5-10日)持续下跌
    2. 近2日放量收阳
    3. 成交量放大 > 前5日均量的1.5倍
    """
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}

    early = daily[-10:-3]
    recent = daily[-3:]

    # 前期下跌
    early_changes = [d["change_pct"] for d in early]
    early_decline = sum(early_changes) < -3

    # 近3日有放量阳线
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
    """
    F3: 恐慌出尽检测 (ETF版本)
    1. 连续回调后出现缩量十字星/小阳线
    2. 跌幅收窄
    3. 成交量显著萎缩
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}

    recent = daily[-5:]
    changes = [d["change_pct"] for d in recent]

    # 跌幅收窄
    negatives = [c for c in changes if c < 0]
    decline_narrowing = False
    if len(negatives) >= 2:
        decline_narrowing = all(
            abs(negatives[i]) > abs(negatives[i+1])
            for i in range(len(negatives)-1)
        )

    # 成交量萎缩
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
    """
    F8: 缩量止跌 —— 底部盘整
    1. 股价连续3日涨跌幅在 ±2% 以内(ETF放宽)
    2. 成交量降至近20日均值的60%以下
    3. 近3日振幅 < 5%
    """
    if len(daily) < 20:
        return {"triggered": False, "reason": "数据不足（需20日）"}

    recent_3 = daily[-3:]
    prev_20 = daily[-20:]

    # 价格窄幅震荡
    changes = [abs(d["change_pct"]) for d in recent_3]
    narrow_range = all(c < 2.0 for c in changes) if changes else False

    # 成交量萎缩
    vols_20 = [d["volume"] for d in prev_20]
    avg_vol_20 = sum(vols_20) / len(vols_20) if vols_20 else 1
    recent_vol = sum(d["volume"] for d in recent_3) / 3
    volume_shrink = recent_vol < avg_vol_20 * 0.6

    # 振幅收窄
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
    """
    F4: 加速下跌检测 (ETF版本)
    1. 连续3日下跌
    2. 每日跌幅递增
    3. 成交量逐日放大
    → 最危险的信号，绝对不要抄底
    """
    if len(daily) < 8:
        return {"triggered": False, "reason": "数据不足"}

    recent_3 = daily[-3:]
    changes = [d["change_pct"] for d in recent_3]
    all_down = all(c < 0 for c in changes)

    if not all_down:
        return {"triggered": False, "reason": "近期非持续下跌"}

    # 跌幅递增
    accelerating = abs(changes[0]) < abs(changes[1]) < abs(changes[2])

    # 成交量放大
    vols = [d["volume"] for d in recent_3]
    vol_expanding = vols[0] < vols[1] < vols[2]

    # 最新成交量 vs 均值
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
    """
    F5: 顶部逆转检测 (ETF版本)
    1. 前期(5-10日)涨幅 > 10%
    2. 近2日出现放量下跌
    3. 最新成交量 > 前10日均量的2倍
    → 典型的顶部派发/出货信号
    """
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}

    early = daily[-10:-3]
    recent_2 = daily[-2:]

    # 前期上涨
    early_closes = [d["close"] for d in early]
    if len(early_closes) < 2:
        return {"triggered": False}
    early_rise = (early_closes[-1] - early_closes[0]) / early_closes[0] * 100 if early_closes[0] > 0 else 0

    # 近2日有放量下跌
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
    """
    F7: 利好出尽检测
    1. 近期有利好消息
    2. 消息当天或次日高开低走（下跌）
    3. 前期涨幅 > 10%
    → 历史回调概率高
    """
    if not news:
        return {"triggered": False, "reason": "无消息数据"}

    # 寻找最近的利好消息
    bullish_keywords = ['涨', '走强', '涨停', '利好', '突破', '新高', '订单', '扩产']
    bullish_news = []
    for n in news:
        title = n.get("title", "")
        if any(kw in title for kw in bullish_keywords):
            bullish_news.append(n)

    if not bullish_news:
        return {"triggered": False, "reason": "无明确利好消息"}

    # 检查前期涨幅
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}

    early = daily[-15:-5] if len(daily) >= 15 else daily[:-5]
    if len(early) < 5:
        return {"triggered": False}

    early_closes = [d["close"] for d in early]
    pre_rise = (early_closes[-1] - early_closes[0]) / early_closes[0] * 100 if early_closes[0] > 0 else 0

    # 消息当天是否高开低走
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

    # 检查1: 不再创新低
    recent_lows = [d["low"] for d in recent]
    prev_lows = [d["low"] for d in prev_10]
    checks["no_new_low"] = min(recent_lows) >= min(prev_lows)

    # 检查2: 振幅收窄
    amplitudes = [d["amplitude"] for d in recent]
    checks["narrow_range"] = all(a < 5 for a in amplitudes)

    # 检查3: 成交量回归正常（不异常放大）
    avg_vol_prev = sum(d["volume"] for d in prev_10) / len(prev_10)
    recent_vol = sum(d["volume"] for d in recent) / 3
    checks["volume_normal"] = recent_vol < avg_vol_prev * 1.5  # 不放量

    # 检查4: 最低价抬高
    checks["lows_rising"] = recent_lows[-1] >= recent_lows[0] if len(recent_lows) >= 2 else False

    # 检查5: 站上5日均线
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

def calc_safety_score(safety_signals: dict, danger_signals: dict, daily: list[dict]) -> dict:
    """安全区间综合评分 (0-100)"""
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

    # 趋势强度修正：检查20日趋势
    if len(daily) >= 20:
        ma20 = sum(d["close"] for d in daily[-20:]) / 20
        current = daily[-1]["close"]
        deviation = (current - ma20) / ma20 * 100

        if deviation > 15:  # 远离均线+高位放量 = 回调风险
            score -= 5
            adjustment_details.append((f"偏离20MA+{deviation:.0f}%(超买)", -5))
        elif deviation < -10:  # 远离均线下方+底部 = 反弹机会
            score += 5
            adjustment_details.append((f"偏离20MA{deviation:.0f}%(超卖)", +5))

    # 成交量异常检测
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

    # 汇总信号
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
    # 买入条件
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

    # 放量阳线确认
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

    # 离场条件
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
    code = "159516"
    target_name = "半导体设备ETF国泰"
    print(f"[识别] ETF: {target_name} ({code})")

    # 1. 拉取数据
    print("[1/5] 拉取30-60天日度数据...")
    kline = fetch_kline_tencent(code, days=60)
    realtime = fetch_realtime_tencent(code)

    # 合并K线和实时行情
    # 用realtime更新最后一天
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

    print("[2/5] 拉取消息...")
    news = fetch_news("半导体设备")

    # 2. 安全信号检测
    print("[3/5] 安全信号检测...")
    safety_signals = {
        "f1_exhaustion": detect_selling_exhaustion(daily),
        "f2_institution_return": detect_institution_return(daily),
        "f3_retail_exhaustion": detect_retail_exhaustion(daily),
        "f8_volume_stabilization": detect_volume_stabilization(daily),
    }

    # 3. 危险信号检测
    print("[4/5] 危险信号检测...")
    danger_signals = {
        "f4_accelerating": detect_accelerating_selling(daily),
        "f5_top_distribution": detect_top_distribution(daily),
        "f7_news_exhausted": detect_news_exhausted(daily, news),
    }

    # 4. 安全评分
    print("[5/5] 计算安全评分...")
    safety_score = calc_safety_score(safety_signals, danger_signals, daily)

    # 5. 买卖时机
    timing = generate_timing(safety_score, daily)

    # 6. 价格数据摘要
    today = daily[-1] if daily else {}
    week_ago = daily[-6] if len(daily) >= 6 else daily[0]
    month_ago = daily[-22] if len(daily) >= 22 else daily[0]

    # ━━ 构建报告 ━━
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": code,
        "target_type": "etf",
        "target_name": target_name,
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
        "daily": daily,
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

    # JSON
    json_path = os.path.join(output_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    # Markdown
    md_path = os.path.join(output_dir, "report.md")
    _save_markdown(report, md_path)

    print(f"\n报告已保存: {output_dir}/")
    return report


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Console 打印
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _print_report(report: dict):
    """打印完整安全评估报告"""
    print()
    print("=" * 80)
    print("  🛡️  买入安全区间研判报告")
    print(f"  标的: {report['target_name']} ({report['target']})")
    print(f"  类型: {report['target_type']} | {report['generated_at']}")
    print(f"  原则: 可以少挣，必须少亏。所有判断用数据说话。")
    print("=" * 80)

    # ━━ Part 1: 核心结论 ━━
    score = report["safety_score"]
    summary = report["summary"]
    print()
    print("━" * 60)
    print("  🎯 Part 1: 核心结论")
    print("━" * 60)
    print(f"  当前价格: {summary['price']:.3f} | "
          f"涨跌: {summary['change']:+.3f} ({summary['change_pct']:+.2f}%)")
    print(f"  1周涨跌: {summary['change_1w']:+.1f}% | "
          f"1月涨跌: {summary['change_1m']:+.1f}%")
    print(f"  安全评分: {score['safety_score']}/100 → {score['safety_level']}")
    print(f"  企稳状态: {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} "
          f"({score['stabilization']['passed_count']}/5项)")
    print(f"  能否入场: {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'}")
    print(f"  判断依据: {score['description']}")

    # 评分构成
    print(f"\n  📊 评分构成 (基准50):")
    for detail, adj in score["adjustment_details"]:
        sign = "+" if adj > 0 else ""
        print(f"     {sign}{adj:>+3d}  {detail}")

    # ━━ Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券） ━━
    print()
    print("━" * 70)
    print("  📋 Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）")
    print("━" * 70)
    daily = report.get("daily", [])
    realtime = report.get("realtime", {})

    # ═══════════════════════════════════════════════════════════════
    # 2A: 日度量价明细 (B轨: 量价+历史分位)
    # ═══════════════════════════════════════════════════════════════
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

            # 换手率估算
            turnover = realtime.get("turnover_pct", 0) if date == daily[-1]["date"] else 0
            if turnover == 0:
                float_shares = realtime.get("float_mcap_yi", 5) / realtime.get("price", 1) * 1e8 if realtime.get("price") else 5e8
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

        # 涨跌幅分布
        all_changes = [d["change_pct"] for d in daily[-20:]]
        big_up = sum(1 for c in all_changes if c > 5)
        up = sum(1 for c in all_changes if 2 < c <= 5)
        flat = sum(1 for c in all_changes if -2 <= c <= 2)
        down = sum(1 for c in all_changes if -5 <= c < -2)
        big_down = sum(1 for c in all_changes if c < -5)
        print(f"  📊 近20日涨跌分布: 🔥大涨{big_up}天 📈上涨{up}天 ➖震荡{flat}天 📉下跌{down}天 💧暴跌{big_down}天")

    # ═══════════════════════════════════════════════════════════════
    # 2B: 资金流向详细 (B轨: 行业资金流代理)
    # ═══════════════════════════════════════════════════════════════
    print()
    print("  ━" * 55)
    print("    💰 2B: 资金流向详细 (行业资金流代理)")
    print("  ━" * 55)
    industry_flows = report.get("industry_flow", [])
    if industry_flows:
        print(f"  相关行业资金流(市场环境参考):")
        for f in industry_flows[:5]:
            name = f.get('name', '')
            chg = f.get('change_pct', 0)
            main_net = f.get('main_net', 0)
            print(f"     {name}: 涨跌{chg:+.2f}% | 主力净流{main_net/1e8:+.2f}亿")
    else:
        print(f"  行业资金流: 暂不可取")

    # ═══════════════════════════════════════════════════════════════
    # 2C: 融资融券明细
    # ═══════════════════════════════════════════════════════════════
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
    print("  1. 安全评分基于可验证的价格/成交量/消息面规则")
    print("  2. 买入/卖出参考条件是可验证的信号框架，不是买卖指令")
    print("  3. 核心原则: 可以少挣，必须少亏 — 安全评分<60坚决不入场")
    print("  4. 亏损的数学是不对称的: 亏50%需涨100%回本")
    print("  5. ETF分析基于价格+成交量+消息面，无个股资金流维度")
    print("  6. 所有分析基于公开数据，不构成投资建议")
    print("=" * 80)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Markdown 保存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _save_markdown(report: dict, path: str):
    """保存 Markdown 报告"""
    score = report["safety_score"]
    summary = report["summary"]
    daily = report["daily"]
    timing = report["timing"]

    lines = []
    lines.append(f"# 🛡️ 买入安全区间研判报告")
    lines.append(f"")
    lines.append(f"**标的**: {report['target_name']} ({report['target']}) | **类型**: ETF")
    lines.append(f"**生成时间**: {report['generated_at']}")
    lines.append(f"**核心原则**: 可以少挣，必须少亏。所有判断用数据说话。")
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
    lines.append(f"| 安全评分 | **{score['safety_score']}/100** → {score['safety_level']} |")
    lines.append(f"| 企稳状态 | {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} ({score['stabilization']['passed_count']}/5项) |")
    lines.append(f"| 能否入场 | {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'} |")
    lines.append(f"")
    lines.append(f"**判断依据**: {score['description']}")
    lines.append(f"")
    lines.append(f"### 评分构成")
    lines.append(f"")
    for detail, adj in score["adjustment_details"]:
        sign = "+" if adj > 0 else ""
        lines.append(f"- {sign}{adj:>+3d}  {detail}")
    lines.append(f"")

    # ━━ Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券） ━━
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）")
    lines.append(f"")

    # 2A: 日度量价明细 (B轨)
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
            float_shares = realtime.get("float_mcap_yi", 1) / realtime.get("price", 1) * 1e8 if realtime.get("price") else 5e8
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

    # 2B: 资金流向详细 (B轨: 行业资金流代理)
    lines.append(f"### 2B: 资金流向详细 (行业资金流代理)")
    lines.append(f"")
    industry_flows = report.get("industry_flow", [])
    if industry_flows:
        lines.append(f"| 行业 | 涨跌幅 | 主力净流(亿) |")
        lines.append(f"|------|--------|-------------|")
        for f in industry_flows[:5]:
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
    lines.append(f"5. ETF分析基于价格+成交量+消息面，无个股资金流维度")
    lines.append(f"6. 所有分析基于公开数据，不构成投资建议")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
