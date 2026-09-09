#!/usr/bin/env python3
"""
fund-flow-predictor 完整分析脚本
标的: 科创50ETF国泰 (589360)
日期: 2026-07-13
类型: 上海ETF → B轨(量价+消息面+概念板块资金流代理)
上市日期: 2026-06-26, 仅12个交易日
"""

import sys
sys.path.insert(0, '.claude/skills/_shared')
from cross_validation import (
    fetch_realtime_with_validation,
    print_validation_summary,
    markdown_validation_summary,
)
import os
import json
import requests
from datetime import datetime, timedelta

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 1: 数据采集
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_kline_eastmoney(code: str, days: int = 60) -> list[dict]:
    """
    从东财push2his获取日K线（前复权）。
    用于腾讯K线不可用的新上市ETF。
    格式: "日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率"
    """
    prefix = "1" if code.startswith(("5", "6", "9")) else "0"
    try:
        r = requests.get(
            'https://push2his.eastmoney.com/api/qt/stock/kline/get',
            params={
                'secid': f'{prefix}.{code}',
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
                'klt': '101', 'fqt': '1', 'end': '20500101', 'lmt': str(days),
            },
            timeout=15
        )
        d = r.json()
        raw = d.get('data', {}).get('klines', []) if d else []

        klines = []
        for line in raw:
            parts = line.split(',')
            if len(parts) < 11:
                continue
            date = parts[0]
            o = float(parts[1])
            c = float(parts[2])
            h = float(parts[3])
            l = float(parts[4])
            v = int(float(parts[5]))  # 成交量(手)
            chg = float(parts[8])     # 涨跌幅%
            amp = float(parts[7])     # 振幅%
            klines.append({
                "date": date,
                "open": o, "close": c, "high": h, "low": l,
                "volume": v,
                "change_pct": round(chg, 2),
                "amplitude": round(amp, 2),
                "main_net": 0, "super_net": 0, "large_net": 0,
                "mid_net": 0, "small_net": 0,
            })
        return klines
    except Exception as e:
        print(f"  ⚠️ 东财K线异常: {e}")
        return []


def fetch_kline_tencent(code: str, days: int = 60) -> list[dict]:
    """从腾讯获取日K线（前复权）— 新ETF可能无数据"""
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    try:
        r = requests.get(
            'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
            params={'param': f'{prefix}{code},day,,,{days},qfq'},
            timeout=15
        )
        data = r.json()
        raw = data.get('data', {}).get(f'{prefix}{code}', {}).get('qfqday', [])
        if not raw:
            raw = data.get('data', {}).get(f'{prefix}{code}', {}).get('day', [])
        klines = []
        for d in raw:
            date, open_p, close, high, low, vol = d[0], d[1], d[2], d[3], d[4], d[5]
            o, c, h, l, v = float(open_p), float(close), float(high), float(low), float(vol)
            chg = round((c - o) / o * 100, 2) if o > 0 else 0
            amp = round((h - l) / l * 100, 2) if l > 0 else 0
            klines.append({
                "date": date, "open": o, "close": c, "high": h, "low": l,
                "volume": v, "change_pct": chg, "amplitude": amp,
                "main_net": 0, "super_net": 0, "large_net": 0,
                "mid_net": 0, "small_net": 0,
            })
        return klines
    except Exception:
        return []


def fetch_realtime_tencent(code: str) -> dict:
    """从腾讯获取实时行情"""
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    r = requests.get(f'http://qt.gtimg.cn/q={prefix}{code}', timeout=10)
    r.encoding = "gbk"
    text = r.text
    if '~' not in text or '"' not in text:
        return {}
    parts = text.split('"')[1].split('~')
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


def fetch_news(keyword: str) -> list[dict]:
    """获取新闻"""
    try:
        from a_stock_api import eastmoney_stock_news
        raw = eastmoney_stock_news(keyword, page_size=10)
        news = []
        for item in raw:
            news.append({
                "title": item.get("title", ""),
                "date": str(item.get("date", ""))[:10] if item.get("date") else "",
                "summary": item.get("summary", ""),
                "url": item.get("url", ""),
            })
        return news
    except Exception:
        return []


# ETF→概念板块映射
STOCK_CONCEPT_MAP = {
    "589360": "BK0615",  # 科创50ETF国泰 → 科创50
}


def fetch_concept_board_flow(code: str) -> dict:
    """获取科创50概念板块成分股资金流排名"""
    board_code = STOCK_CONCEPT_MAP.get(code)
    if not board_code:
        return {"available": False, "reason": "未找到所属概念板块映射"}

    try:
        from a_stock_api import em_get
        r = em_get('https://push2.eastmoney.com/api/qt/clist/get', params={
            'pn': '1', 'pz': '50', 'po': '0', 'np': '1',
            'fltt': '2', 'invt': '2', 'fid': 'f62',
            'fs': f'b:{board_code}',
            'fields': 'f3,f12,f14,f62'
        }, timeout=15)
        d = r.json() if r else {}
        items = d.get('data', {}).get('diff', [])

        stocks = []
        total_main = 0
        for item in items:
            main_net_yi = (item.get('f62') or 0) / 1e8
            total_main += main_net_yi
            stocks.append({
                'code': item.get('f12', ''),
                'name': item.get('f14', ''),
                'change_pct': item.get('f3', 0),
                'main_net_yi': round(main_net_yi, 2),
            })

        return {
            "available": True,
            "board_code": board_code,
            "total_main_net_yi": round(total_main, 2),
            "stock_count": len(stocks),
            "stocks": stocks,
        }
    except Exception as e:
        return {"available": False, "reason": f"概念板块API异常: {e}"}


def fetch_margin_data(code: str) -> dict:
    """获取ETF融资融券数据"""
    try:
        r = requests.get('https://datacenter-web.eastmoney.com/api/data/v1/get', params={
            'reportName': 'RPTA_WEB_RZRQ_GGMX',
            'columns': 'ALL',
            'filter': f'(SCODE="{code}")',
            'pageNumber': '1', 'pageSize': '30',
            'sortTypes': '-1', 'sortColumns': 'DATE',
            'source': 'WEB', 'client': 'WEB'
        }, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        d = r.json()
        raw_records = d.get('result', {}).get('data', []) if d and d.get('result') else []

        records = []
        for item in raw_records[:30]:
            date_str = str(item.get('DATE', ''))[:10]
            rzye = (item.get('RZYE') or 0) / 1e8
            rzmre = (item.get('RZMRE') or 0) / 1e8
            rzche = (item.get('RZCHE') or 0) / 1e8
            records.append({
                'date': date_str,
                'rzye_yi': round(rzye, 2),
                'rzmre_yi': round(rzmre, 2),
                'rzche_yi': round(rzche, 2),
                'net_yi': round(rzmre - rzche, 2),
            })

        if not records:
            return {"available": False, "reason": "无融资融券数据"}

        recent_5 = records[:5]
        prev_5 = records[5:10] if len(records) >= 10 else []
        recent_avg = sum(r['rzye_yi'] for r in recent_5) / len(recent_5)
        prev_avg = sum(r['rzye_yi'] for r in prev_5) / len(prev_5) if prev_5 else recent_avg

        if recent_avg > prev_avg * 1.05:
            trend = "上升"
        elif recent_avg < prev_avg * 0.95:
            trend = "下降"
        else:
            trend = "平稳"

        net_5d = sum(r['net_yi'] for r in recent_5)
        net_10d = sum(r['net_yi'] for r in records[:10])

        return {
            "available": True, "records": records,
            "latest_balance_yi": records[0]['rzye_yi'] if records else 0,
            "trend": trend,
            "net_flow_5d_yi": round(net_5d, 2),
            "net_flow_10d_yi": round(net_10d, 2),
        }
    except Exception as e:
        return {"available": False, "reason": f"融资融券API异常: {e}"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 2: 安全信号提取 (B轨: 量价+消息面)
# 注意: 新上市ETF仅12个交易日，部分长周期信号需降级处理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_selling_exhaustion(daily: list[dict], track: str = "B") -> dict:
    """
    F1: 卖压衰竭检测
    B轨: 近5日跌幅逐日收窄 + 成交量萎缩 + 不再创新低
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": f"数据不足(仅{len(daily)}日, 需≥5日)"}

    recent = daily[-5:]

    # 不再创新低 — 用可用数据
    if len(daily) >= 10:
        prev_lows = [d["low"] for d in daily[-10:-5]]
        no_new_low = min(d["low"] for d in recent) >= min(prev_lows)
    else:
        # 少于10日时，检查最近3日vs前2日
        no_new_low = min(d["low"] for d in recent[-3:]) >= min(d["low"] for d in recent[:2])

    declines = [abs(d["change_pct"]) for d in recent if d["change_pct"] < 0]
    is_decreasing = len(declines) >= 2 and all(
        declines[i] > declines[i+1] for i in range(len(declines)-1)
    )
    vols = [d["volume"] for d in recent]
    avg_vol_5 = sum(vols) / len(vols)
    prev_vols = [d["volume"] for d in daily[:-5]]
    avg_vol_prev = sum(prev_vols) / len(prev_vols) if prev_vols else avg_vol_5
    vol_shrink = avg_vol_5 < avg_vol_prev * 0.7

    triggered = is_decreasing and vol_shrink and no_new_low
    return {
        "triggered": triggered,
        "signal_name": "F1: 卖压衰竭(量价)",
        "decreasing_declines": is_decreasing,
        "volume_shrink": vol_shrink,
        "no_new_low": no_new_low,
        "strength": "强" if triggered else "弱",
        "meaning": "卖压在减弱，下跌动能衰竭" if triggered else "卖压尚未衰竭，继续观察",
    }


def detect_institution_return(daily: list[dict], track: str = "B") -> dict:
    """
    F2: 资金回流检测
    B轨: 前期持续下跌 → 近3日有放量阳线
    新ETF适配: 前期阈值放宽
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": f"数据不足(仅{len(daily)}日, 需≥5日)"}

    if len(daily) >= 10:
        early = daily[-10:-3]
        recent = daily[-3:]
    elif len(daily) >= 6:
        early = daily[:-3]
        recent = daily[-3:]
    else:
        return {"triggered": False, "reason": "数据不足"}

    early_changes = [d["change_pct"] for d in early]
    early_decline = sum(early_changes) < -3
    avg_vol_early = sum(d["volume"] for d in early) / len(early) if early else 1
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


def detect_retail_exhaustion(daily: list[dict], track: str = "B") -> dict:
    """
    F3: 恐慌出尽检测
    B轨: 近5日跌幅收窄 + 成交量显著萎缩
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": f"数据不足(仅{len(daily)}日)"}

    recent = daily[-5:]
    changes = [d["change_pct"] for d in recent]
    negatives = [c for c in changes if c < 0]
    decline_narrowing = len(negatives) >= 2 and all(
        abs(negatives[i]) > abs(negatives[i+1]) for i in range(len(negatives)-1)
    )
    vols = [d["volume"] for d in recent]
    avg_vol_recent = sum(vols)/len(vols)
    prev_vols = [d["volume"] for d in daily[:-5]]
    avg_vol_prev = sum(prev_vols)/len(prev_vols) if prev_vols else avg_vol_recent
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


def detect_volume_stabilization(daily: list[dict], track: str = "B") -> dict:
    """
    F8: 缩量止跌
    新ETF适配: 使用全量数据计算均量(12日)代替20日均量
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": f"数据不足(仅{len(daily)}日)"}

    recent_3 = daily[-3:]
    # 小于20日时用全量数据
    use_all = len(daily) < 20
    all_data = daily if use_all else daily[-20:]

    changes = [abs(d["change_pct"]) for d in recent_3]
    narrow_range = all(c < 2.0 for c in changes) if changes else False

    vols_all = [d["volume"] for d in all_data]
    avg_vol_ref = sum(vols_all) / len(vols_all) if vols_all else 1
    recent_vol = sum(d["volume"] for d in recent_3) / 3
    volume_shrink = recent_vol < avg_vol_ref * 0.6

    amplitudes = [d["amplitude"] for d in recent_3]
    amp_narrow = all(a < 5 for a in amplitudes) if amplitudes else False

    triggered = narrow_range and volume_shrink and amp_narrow

    data_note = f"(全量{len(daily)}日均量)" if use_all else "(20日均量)"
    return {
        "triggered": triggered,
        "signal_name": f"F8: 缩量止跌盘整{data_note}",
        "narrow_range": narrow_range,
        "volume_shrink": volume_shrink,
        "amp_narrow": amp_narrow,
        "avg_vol_20": round(avg_vol_ref, 0),
        "recent_vol_3": round(recent_vol, 0),
        "strength": "强" if triggered else "弱",
        "meaning": "卖压枯竭，底部盘整中 → 下行空间有限" if triggered else "尚未缩量止跌，仍在波动",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 3: 危险信号检测 (B轨)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_accelerating_selling(daily: list[dict], track: str = "B") -> dict:
    """
    F4: 加速下跌
    B轨: 连续3日下跌 + 每日跌幅递增 + 成交量逐日放大
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": f"数据不足(仅{len(daily)}日)"}

    recent_3 = daily[-3:]
    changes = [d["change_pct"] for d in recent_3]
    all_down = all(c < 0 for c in changes)
    if not all_down:
        return {"triggered": False, "reason": "近期非持续下跌"}
    accelerating = abs(changes[0]) < abs(changes[1]) < abs(changes[2])
    vols = [d["volume"] for d in recent_3]
    vol_expanding = vols[0] < vols[1] < vols[2]
    prev_vols = [d["volume"] for d in daily[:-3]]
    avg_vol_prev = sum(prev_vols) / len(prev_vols) if prev_vols else 1
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


def detect_top_distribution(daily: list[dict], track: str = "B") -> dict:
    """
    F5: 高位逆转
    新ETF适配: 全量数据短，放宽前期窗口
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}

    # 用全量数据中更早的日作为"前期"
    if len(daily) >= 8:
        early = daily[:-2]
        recent_2 = daily[-2:]
    else:
        early = daily[:-2] if len(daily) >= 3 else daily
        recent_2 = daily[-2:] if len(daily) >= 2 else daily

    early_closes = [d["close"] for d in early]
    if len(early_closes) < 2:
        return {"triggered": False}
    early_rise = (early_closes[-1]-early_closes[0])/early_closes[0]*100 if early_closes[0]>0 else 0
    avg_vol_early = sum(d["volume"] for d in early)/len(early) if early else 1
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
    """F7: 利好出尽"""
    if not news:
        return {"triggered": False, "reason": "无消息数据"}
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}

    bullish_keywords = ['涨', '走强', '涨停', '利好', '突破', '新高', '订单', '扩产', '预增', '超预期', '科创']
    bullish_news = [n for n in news if any(kw in n.get("title","") for kw in bullish_keywords)]

    early = daily[:-2] if len(daily) >= 4 else daily
    early_closes = [d["close"] for d in early]
    pre_rise = (early_closes[-1]-early_closes[0])/early_closes[0]*100 if early_closes[0]>0 else 0
    recent = daily[-2:]
    high_open_low_close = any(d["change_pct"] < -3 for d in recent)

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

def check_stabilization(daily: list[dict], track: str = "B") -> dict:
    """企稳确认检查清单（5项）— 新ETF适配短数据"""
    if len(daily) < 5:
        return {"is_stabilized": False, "reason": f"数据不足(仅{len(daily)}日)", "passed_count": 0, "total_count": 5, "checks": {}}

    recent = daily[-3:]
    prev_n = daily[:-3] if len(daily) >= 6 else daily[:1]
    checks = {}

    # 1. 不再创新低
    recent_lows = [d["low"] for d in recent]
    prev_lows = [d["low"] for d in prev_n]
    checks["no_new_low"] = min(recent_lows) >= min(prev_lows) if prev_lows else False

    # 2. 振幅收窄
    checks["narrow_range"] = all(d["amplitude"] < 5 for d in recent) if recent else False

    # 3. 量能正常
    avg_vol_prev = sum(d["volume"] for d in prev_n) / len(prev_n) if prev_n else 1
    recent_vol = sum(d["volume"] for d in recent) / 3 if recent else 0
    checks["flow_normal"] = recent_vol < avg_vol_prev * 1.5

    # 4. 最低价抬高
    checks["lows_rising"] = recent_lows[-1] >= recent_lows[0] if len(recent_lows) >= 2 else False

    # 5. 站上5日均线
    if len(daily) >= 6:
        prices = [d["close"] for d in daily[-6:]]
        ma5 = sum(prices[:5]) / 5
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
# Layer 5: 安全评分计算 (V1.4 — 新ETF降权处理)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_safety_score(safety_signals: dict, danger_signals: dict, daily: list[dict],
                      track: str = "B", margin_data: dict = None, concept_flow: dict = None,
                      data_days: int = 60) -> dict:
    """
    安全区间综合评分 (0-100)
    新ETF适配: 数据<20日时，趋势修正/成交量修正权重减半
    """
    score = 50
    adjustment_details = []
    short_data = data_days < 20

    # ━━ 安全信号加分 (B轨权重) ━━
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

    # ━━ 危险信号减分 ━━
    if danger_signals.get("f4_accelerating", {}).get("triggered"):
        score -= 20
        adjustment_details.append(("F4 加速放量下跌", -20))
    if danger_signals.get("f5_top_distribution", {}).get("triggered"):
        score -= 18
        adjustment_details.append(("F5 高位放量逆转", -18))
    if danger_signals.get("f7_news_exhausted", {}).get("triggered"):
        score -= 15
        adjustment_details.append(("F7 利好出尽", -15))

    # ━━ 企稳确认 ━━
    stabilization = check_stabilization(daily, track)
    if stabilization["is_stabilized"]:
        score += 10
        adjustment_details.append(("企稳确认", +10))

    # ━━ 趋势强度修正 (短数据降权) ━━
    if len(daily) >= 5:
        ma_ref = sum(d["close"] for d in daily) / len(daily)  # 全量均线
        current = daily[-1]["close"]
        deviation = (current - ma_ref) / ma_ref * 100
        weight = 0.5 if short_data else 1.0
        if deviation > 15:
            adj = int(-5 * weight)
            score += adj
            adjustment_details.append((f"偏离均线+{deviation:.0f}%(超买)[短数据降权]", adj))
        elif deviation < -10:
            adj = int(5 * weight)
            score += adj
            adjustment_details.append((f"偏离均线{deviation:.0f}%(超卖)[短数据降权]", adj))

    # ━━ 成交量异常修正 (短数据降权) ━━
    if len(daily) >= 5:
        avg_vol_all = sum(d["volume"] for d in daily) / len(daily)
        today_vol = daily[-1]["volume"]
        vol_ratio = today_vol / avg_vol_all
        weight = 0.5 if short_data else 1.0
        if vol_ratio > 3.0 and daily[-1]["change_pct"] < -3:
            adj = int(-8 * weight)
            score += adj
            adjustment_details.append((f"恐慌放量({vol_ratio:.1f}x均量+大跌)[短数据降权]", adj))
        elif vol_ratio > 2.0 and daily[-1]["change_pct"] < -2:
            adj = int(-5 * weight)
            score += adj
            adjustment_details.append((f"放量下跌({vol_ratio:.1f}x均量)[短数据降权]", adj))
        elif vol_ratio < 0.4 and abs(daily[-1]["change_pct"]) < 1:
            adj = int(3 * weight)
            score += adj
            adjustment_details.append(("缩量止跌企稳[短数据降权]", adj))

    # ━━ V1.4: 融资融券修正 ━━
    if margin_data and margin_data.get("available"):
        trend = margin_data.get("trend", "")
        net_5d = margin_data.get("net_flow_5d_yi", 0)
        if trend == "下降" and net_5d < -1:
            score -= 7
            adjustment_details.append((f"融资去杠杆(近5日{net_5d:+.1f}亿)", -7))
        elif trend == "下降" and net_5d < 0:
            score -= 4
            adjustment_details.append((f"融资温和下降(近5日{net_5d:+.1f}亿)", -4))
        elif trend == "上升" and net_5d > 2:
            score += 5
            adjustment_details.append((f"融资加杠杆(近5日+{net_5d:.1f}亿)", +5))
        elif trend == "上升" and net_5d > 0:
            score += 3
            adjustment_details.append((f"融资温和上升(近5日+{net_5d:.1f}亿)", +3))

    # ━━ V1.4: 概念板块资金流修正 ━━
    if concept_flow and concept_flow.get("available") and track == "B":
        total_main = concept_flow.get("total_main_net_yi", 0)
        if total_main < -5:
            score -= 5
            adjustment_details.append((f"科创50板块主力大幅流出({total_main:+.1f}亿)", -5))
        elif total_main > 5:
            score += 3
            adjustment_details.append((f"科创50板块主力流入({total_main:+.1f}亿)", +3))

    # ━━ 新ETF数据不足风险提示 ━━
    if short_data:
        score -= 5
        adjustment_details.append((f"⚠️新上市仅{data_days}日数据(统计显著性不足)", -5))

    score = max(0, min(100, score))

    # ━━ 安全等级 ━━
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
        "safety_score": score,
        "safety_level": level,
        "can_enter": can_enter,
        "description": desc,
        "positive_signals": positive,
        "negative_signals": negative,
        "adjustment_details": adjustment_details,
        "stabilization": stabilization,
        "data_note": f"⚠️ 仅{data_days}个交易日(新上市ETF)，统计显著性不足，评分仅供参考" if short_data else "",
        "principle": "可以少挣，必须少亏 — 只有 ≥75 分才建议考虑入场",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 6: 买卖时机参考
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
    has_confirmation = any(d["change_pct"] > 2 for d in recent_3)
    entry_conditions.append({
        "condition": "近日放量阳线确认（增强信号）",
        "met": has_confirmation,
        "current": "已出现" if has_confirmation else "未出现",
        "weight": "加分项（非必须）",
    })

    must_met = all(c["met"] for c in entry_conditions if c["weight"] == "必须")
    all_met = all(c["met"] for c in entry_conditions)

    exit_conditions = [
        {"condition": "🔴 硬止损: 持仓亏损>5% + 持续放量下跌", "triggered": False,
         "rule": "F13: 亏损控制 — 亏损的数学是不对称的", "action": "全部离场"},
        {"condition": "🟠 利润保护: 盈利>5% + 高位放量逆转信号", "triggered": False,
         "rule": "F12: 利润保护 — 可以少挣，必须少亏", "action": "至少减仓50%"},
        {"condition": "🔴 任何高危信号触发 (F4/F5/F7)", "triggered": neg_count > 0,
         "current": f"{neg_count}个危险信号" if neg_count > 0 else "无",
         "rule": "危险信号 > 一切买入信号", "action": "不买，已持有则评估是否离场"},
        {"condition": "🔴 安全评分降至 < 40分", "triggered": safety_score["safety_score"] < 40,
         "current": f"{safety_score['safety_score']}分",
         "rule": "危险区间 = 持币观望", "action": "远离，等安全评分回升"},
    ]

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
        "exit": {"any_triggered": any(c["triggered"] for c in exit_conditions), "conditions": exit_conditions},
        "principle": "可以少挣，必须少亏 — 宁可错过，不可做错",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Console 打印
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _print_report(report: dict):
    """打印完整安全评估报告"""
    print()
    print("=" * 90)
    print("  🛡️  买入安全区间研判报告 (V1.4)")
    print(f"  标的: {report['target_name']} ({report['target']})")
    print(f"  类型: {report['target_type']} | 信号轨: {report.get('track_label', '')}")
    print(f"  生成: {report['generated_at']} | 原则: 可以少挣，必须少亏")
    print("=" * 90)

    score = report["safety_score"]
    summary = report.get("summary", {})
    realtime = report.get("realtime", {})
    daily = report.get("daily", [])

    # ━━ Part 1: 核心结论 ━━
    print()
    print("━" * 70)
    print("  🎯 Part 1: 核心结论")
    print("━" * 70)
    print(f"  当前价格: {summary['price']:.3f} | "
          f"涨跌: {summary.get('change', 0):+.3f} ({summary.get('change_pct', 0):+.2f}%)")
    print(f"  今开: {summary.get('open', 0):.3f} | 最高: {summary.get('high', 0):.3f} | "
          f"最低: {summary.get('low', 0):.3f}")
    print(f"  换手率: {summary.get('turnover_pct', 0):.2f}% | "
          f"成交额: {summary.get('amount_yi', 0):.2f}亿")
    print(f"  总市值: {summary.get('mcap_yi', 0):.1f}亿 | 流通市值: {summary.get('float_mcap_yi', 0):.1f}亿")
    if len(daily) >= 5:
        week_ago = daily[-6] if len(daily) >= 6 else daily[0]
        print(f"  1周涨跌: {summary.get('change_1w', 0):+.1f}% | "
              f"上市以来涨跌: {(summary['price']/daily[0]['close']-1)*100:+.1f}%")
    else:
        print(f"  上市以来: {len(daily)}个交易日")

    # ━━ 数据来源质量 ━━
    print_validation_summary(realtime.get("_validation", {}))
    print(f"  数据来源: 行情[腾讯+新浪交叉验证] | K线[东财push2his] | 融资融券[东财单源]")
    print(f"  ⚠️ K线源切换: 腾讯K线无新ETF数据，改用东财push2his({report.get('data_days', 0)}日)")

    # 数据不足提示
    data_note = score.get("data_note", "")
    if data_note:
        print(f"  {data_note}")

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

    # ━━ Part 2: 日度数据明细 ━━
    print()
    print("━" * 70)
    if len(daily) < 20:
        print(f"  📋 Part 2: 全量日度数据明细（仅{len(daily)}个交易日）")
    else:
        print("  📋 Part 2: 近20日日度数据明细")
    print("━" * 70)

    # ═══ 2A: 日度量价明细 ═══
    print()
    print("  ━" * 55)
    print(f"    📈 2A: 日度量价明细 (全量{len(daily)}日)")
    print("  ━" * 55)

    if daily:
        vols_all = [d["volume"] for d in daily]
        avg_vol_all = sum(vols_all) / len(vols_all) if vols_all else 1
        vol_max = max(vols_all) if vols_all else 1
        vol_min = min(vols_all) if vols_all else 0
        prices_all = [d["close"] for d in daily]
        price_h = max(prices_all) if prices_all else 1
        price_l = min(prices_all) if prices_all else 0

        header = (f"  {'日期':<12s} {'收盘':>8s} {'涨跌':>7s} {'振幅':>6s} "
                  f"{'换手':>6s} {'量比':>6s} {'量分位':>7s} {'价分位':>7s} {'走势':>6s}")
        sub_header = f"  {'─'*85}"
        print(header)
        print(sub_header)

        float_shares = realtime.get("float_mcap_yi", 1) / realtime.get("price", 1) * 1e8 if realtime.get("price") else 5e8

        for d in daily:
            date = d.get("date", "")
            close = d.get("close", 0)
            chg = d.get("change_pct", 0)
            amp = d.get("amplitude", 0)
            vol = d.get("volume", 0)
            turnover = round(vol * 100 / float_shares * 100, 2) if float_shares > 0 else 0
            vol_ratio = round(vol / avg_vol_all, 2) if avg_vol_all > 0 else 0
            vol_pct = round((vol - vol_min) / (vol_max - vol_min) * 100, 0) if vol_max > vol_min else 50
            price_pct = round((close - price_l) / (price_h - price_l) * 100, 0) if price_h > price_l else 50

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
        today = daily[-1]
        today_vol = today.get("volume", 0)
        today_vol_ratio = round(today_vol / avg_vol_all, 1) if avg_vol_all > 0 else 0
        today_vol_pct = round((today_vol - vol_min) / (vol_max - vol_min) * 100, 0) if vol_max > vol_min else 50
        today_price_pct = round((today.get("close", 0) - price_l) / (price_h - price_l) * 100, 0) if price_h > price_l else 50

        print(f"  📊 今日量:{today_vol:,.0f}手 | 量比(全量):{today_vol_ratio:.1f}x | "
              f"量分位:{today_vol_pct:.0f}% | 价分位:{today_price_pct:.0f}%")
        print(f"  📊 全量均量:{avg_vol_all:,.0f}手 | "
              f"最高价:{price_h:.3f} | 最低价:{price_l:.3f} | "
              f"距高:{(today.get('close',0)/price_h-1)*100:+.1f}% | 距低:{(today.get('close',0)/price_l-1)*100:+.1f}%")

        # 涨跌幅分布
        all_changes = [d["change_pct"] for d in daily]
        big_up = sum(1 for c in all_changes if c > 5)
        up = sum(1 for c in all_changes if 2 < c <= 5)
        flat = sum(1 for c in all_changes if -2 <= c <= 2)
        down = sum(1 for c in all_changes if -5 <= c < -2)
        big_down = sum(1 for c in all_changes if c < -5)
        print(f"  📊 全量涨跌分布: 🔥大涨{big_up}天 📈上涨{up}天 ➖震荡{flat}天 📉下跌{down}天 💧暴跌{big_down}天")

    # ═══ 2B: 资金流向详细 ═══
    print()
    print("  ━" * 55)
    print("    💰 2B: 资金流向详细")
    print("  ━" * 55)

    concept_data = report.get("concept_flow", {})
    if concept_data and concept_data.get("available"):
        print(f"  📊 科创50概念板块资金流 (代理指标 — ETF无直接资金流)")
        print(f"  板块代码: {concept_data.get('board_code','')} | "
              f"成分股{concept_data.get('stock_count',0)}只")
        print(f"  板块主力净流合计: {concept_data.get('total_main_net_yi',0):+.2f}亿")
        print(f"  ⚠️ ETF自身不是板块成分股，以下为科创50指数成分股资金流排名")
        print(f"\n  📋 科创50成分股资金流排名(主力净流，前15):")
        print(f"  {'排名':<5s} {'代码':<8s} {'名称':<10s} {'涨跌':>8s} {'主力净流':>10s}")
        print(f"  {'─'*48}")
        sorted_stocks = sorted(concept_data.get("stocks", []), key=lambda x: x['main_net_yi'], reverse=True)
        for i, s in enumerate(sorted_stocks[:15]):
            main_yi = s['main_net_yi']
            icon = "🔴" if main_yi < -1 else ("🟢" if main_yi > 1 else "➖")
            print(f"  {i+1:<5d} {s['code']:<8s} {s['name']:<10s} {s['change_pct']:>+7.2f}% {icon}{main_yi:>+8.2f}亿")
        inflow_count = sum(1 for s in sorted_stocks if s['main_net_yi'] > 0)
        outflow_count = sum(1 for s in sorted_stocks if s['main_net_yi'] < 0)
        print(f"\n  📊 板块成分股: {inflow_count}只流入 / {outflow_count}只流出")
        if inflow_count > outflow_count:
            print(f"  ✅ 多数成分股资金流入，板块整体偏多")
        else:
            print(f"  ⚠️ 多数成分股资金流出，板块整体偏空")
    else:
        print(f"  📊 概念板块资金流: 暂不可取")
        reason = concept_data.get("reason", "") if concept_data else ""
        if reason: print(f"     ({reason})")

    # ═══ 2C: 融资融券明细 ═══
    print()
    print("  ━" * 55)
    print("    🏦 2C: 融资融券明细")
    print("  ━" * 55)
    margin_print = report.get("margin_data", {})
    if margin_print and margin_print.get("available"):
        print(f"  最新融资余额: {margin_print.get('latest_balance_yi', 0):.2f}亿 | "
              f"趋势: {margin_print.get('trend', '')}")
        print(f"  近5日融资净买卖: {margin_print.get('net_flow_5d_yi', 0):+.2f}亿 | "
              f"近10日: {margin_print.get('net_flow_10d_yi', 0):+.2f}亿")
        records = margin_print.get('records', [])
        if records:
            print(f"\n  📅 融资日度明细(近{min(10, len(records))}日):")
            print(f"  {'日期':<12s} {'融资余额':>10s} {'买入额':>10s} {'偿还额':>10s} {'净买卖':>10s}")
            print(f"  {'─'*55}")
            for r in records[:10]:
                net_mark = "🔴" if r['net_yi'] > 1 else ("🟢" if r['net_yi'] < -1 else "  ")
                print(f"  {r['date']:<12s} {r.get('rzye_yi',0):>8.2f}亿 {r.get('rzmre_yi',0):>8.2f}亿 "
                      f"{r.get('rzche_yi',0):>8.2f}亿 {net_mark}{r.get('net_yi',0):>+8.2f}亿")
    else:
        print(f"  融资融券: 数据暂不可取")
        reason = margin_print.get("reason", "") if margin_print else ""
        if reason: print(f"     ({reason})")

    # ━━ Part 3-6: 信号/企稳/时机/离场 ━━
    print()
    print("━" * 70)
    print("  ✅ Part 3: 安全信号检测（企稳证据）")
    print("━" * 70)
    for key, sig in report["safety_signals"].items():
        triggered = sig.get("triggered", False)
        icon = "🟢" if triggered else "⚪"
        print(f"  {icon} {sig.get('signal_name', key)}")
        print(f"     {sig.get('meaning', '')}")
        if triggered:
            print(f"     强度: {sig.get('strength', '')}")

    print()
    print("━" * 70)
    print("  🚨 Part 3b: 危险信号检测（风险排查）")
    print("━" * 70)
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

    print()
    print("━" * 70)
    print("  📋 Part 4: 企稳确认清单 (需 ≥4/5)")
    print("━" * 70)
    checks = score["stabilization"]["checks"]
    labels = {
        "no_new_low": "不再创新低",
        "narrow_range": "振幅 < 5%",
        "flow_normal": "量能正常（不放量）",
        "lows_rising": "最低价抬高",
        "above_ma5": "站上5日均线",
    }
    for key, label in labels.items():
        ok = checks.get(key, False)
        print(f"  {'✅' if ok else '❌'} {label}")

    timing = report["timing"]
    print()
    print("━" * 70)
    print("  ⏰ Part 5: 买入时机参考条件")
    print("━" * 70)
    for i, cond in enumerate(timing["entry"]["conditions"]):
        met = cond["met"]
        icon = "✅" if met else "❌"
        print(f"  {icon} [{cond['weight']}] {cond['condition']}")
        print(f"     当前: {cond['current']}")
    print(f"\n  综合判断: {timing['entry']['verdict']}")

    print()
    print("━" * 70)
    print("  🚪 Part 6: 离场/风控参考")
    print("━" * 70)
    for cond in timing["exit"]["conditions"]:
        triggered = cond.get("triggered", False)
        icon = "🔴" if triggered else "  "
        print(f"  {icon} {cond['condition']}")
        if triggered:
            print(f"     规则: {cond.get('rule', '')}")
            print(f"     建议: {cond.get('action', '')}")

    news = report.get("news", [])
    if news:
        print()
        print("━" * 70)
        print("  📰 Part 7: 近期关键消息")
        print("━" * 70)
        for n in news[:6]:
            print(f"  [{n.get('date', '')[:10]}] {n.get('title', '')[:80]}")
            summary_text = n.get('summary', '')[:100]
            if summary_text:
                print(f"         {summary_text}")

    print()
    print("=" * 90)
    print("  ⚠️ 研究声明:")
    print("  1. 安全评分基于可验证的价格/成交量/资金流/消息面规则")
    print("  2. 买入/卖出参考条件是可验证的信号框架，不是买卖指令")
    print("  3. 核心原则: 可以少挣，必须少亏 — 安全评分<60坚决不入场")
    print("  4. 亏损的数学是不对称的: 亏50%需涨100%回本")
    print(f"  5. 信号轨: {report.get('track_label', '')}")
    print(f"  6. 新ETF仅{report.get('data_days', 0)}个交易日，统计显著性严重不足，评分仅供参考")
    print("  7. 所有分析基于公开数据，不构成投资建议")
    print("=" * 90)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Markdown 保存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _save_markdown(report: dict, path: str):
    """保存 Markdown 报告"""
    score = report["safety_score"]
    summary = report["summary"]
    daily = report["daily"]
    timing = report["timing"]
    realtime = report.get("realtime", {})

    lines = []
    lines.append(f"# 🛡️ 买入安全区间研判报告")
    lines.append(f"")
    lines.append(f"**标的**: {report['target_name']} ({report['target']}) | **类型**: ETF(新上市) | **信号轨**: {report.get('track_label', '')}")
    lines.append(f"**生成时间**: {report['generated_at']} | **交易日数**: {report.get('data_days', 0)}日")
    lines.append(f"**核心原则**: 可以少挣，必须少亏。所有判断用数据说话。")
    lines.append(f"")
    data_note = score.get("data_note", "")
    if data_note:
        lines.append(f"> {data_note}")
        lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 1: 核心结论")
    lines.append(f"")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 当前价格 | {summary['price']:.3f} |")
    lines.append(f"| 涨跌幅 | {summary.get('change', 0):+.3f} ({summary.get('change_pct', 0):+.2f}%) |")
    lines.append(f"| 换手率 | {summary.get('turnover_pct', 0):.2f}% |")
    lines.append(f"| 成交额 | {summary.get('amount_yi', 0):.2f}亿 |")
    if summary.get('pe_ttm', 0):
        lines.append(f"| PE(TTM) | {summary.get('pe_ttm', 0):.1f} |")
    lines.append(f"| 总市值 | {summary.get('mcap_yi', 0):.1f}亿 |")
    lines.append(f"| 上市以来涨跌 | {(summary['price']/daily[0]['close']-1)*100:+.1f}% |")
    lines.append(f"| 安全评分 | **{score['safety_score']}/100** → {score['safety_level']} |")
    lines.append(f"| 企稳状态 | {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} ({score['stabilization']['passed_count']}/5项) |")
    lines.append(f"| 能否入场 | {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'} |")

    validation_md_lines = markdown_validation_summary(realtime.get("_validation", {}))
    lines.extend(validation_md_lines)
    lines.append(f"")
    lines.append(f"**数据来源**: 行情[腾讯+新浪交叉验证] | K线[东财push2his({report.get('data_days', 0)}日)] | 融资融券[东财单源]")
    lines.append(f"")
    lines.append(f"**判断依据**: {score['description']}")
    lines.append(f"")
    lines.append(f"### 评分构成")
    lines.append(f"")
    for detail, adj in score["adjustment_details"]:
        sign = "+" if adj > 0 else ""
        lines.append(f"- {sign}{adj:>+3d}  {detail}")
    lines.append(f"")

    # Part 2
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 2: 全量日度数据明细（{len(daily)}个交易日）")
    lines.append(f"")

    # 2A
    lines.append(f"### 2A: 日度量价明细")
    lines.append(f"")
    if daily:
        vols_all = [d["volume"] for d in daily]
        avg_vol_all = sum(vols_all) / len(vols_all) if vols_all else 1
        prices_all = [d["close"] for d in daily]
        price_h = max(prices_all) if prices_all else 1
        price_l = min(prices_all) if prices_all else 0
        float_shares = realtime.get("float_mcap_yi", 1) / realtime.get("price", 1) * 1e8 if realtime.get("price") else 5e8

        lines.append(f"| 日期 | 收盘 | 涨跌幅 | 振幅 | 换手率 | 量比 | 价分位 | 走势 |")
        lines.append(f"|------|------|--------|------|--------|------|--------|------|")
        for d in daily:
            close = d.get("close", 0)
            chg = d.get("change_pct", 0)
            amp = d.get("amplitude", 0)
            vol = d.get("volume", 0)
            turnover = round(vol * 100 / float_shares * 100, 2) if float_shares > 0 else 0
            vol_ratio = round(vol / avg_vol_all, 2) if avg_vol_all > 0 else 0
            price_pct = round((close - price_l) / (price_h - price_l) * 100, 0) if price_h > price_l else 50

            if chg > 5: trend = "🔥大涨"
            elif chg > 2: trend = "📈上涨"
            elif chg > -2: trend = "➖震荡"
            elif chg > -5: trend = "📉下跌"
            else: trend = "💧暴跌"

            lines.append(f"| {d.get('date','')} | {close:.3f} | {chg:+.2f}% | {amp:.2f}% | {turnover:.2f}% | {vol_ratio:.1f}x | {price_pct:.0f}% | {trend} |")

        today = daily[-1]
        lines.append(f"")
        lines.append(f"> **全量均量**: {avg_vol_all:,.0f}手 | **最高价**: {price_h:.3f} | **最低价**: {price_l:.3f}")
    lines.append(f"")

    # 2B
    lines.append(f"### 2B: 资金流向详细")
    lines.append(f"")
    concept_md = report.get("concept_flow", {})
    if concept_md and concept_md.get("available"):
        lines.append(f"#### 科创50概念板块资金流 (代理指标)")
        lines.append(f"")
        lines.append(f"板块代码: {concept_md.get('board_code','')} | 成分股: {concept_md.get('stock_count',0)}只")
        lines.append(f"板块主力净流合计: {concept_md.get('total_main_net_yi',0):+.2f}亿")
        lines.append(f"")
        lines.append(f"| 排名 | 代码 | 名称 | 涨跌幅 | 主力净流(亿) |")
        lines.append(f"|------|------|------|--------|-------------|")
        sorted_md = sorted(concept_md.get("stocks", []), key=lambda x: x['main_net_yi'], reverse=True)
        for i, s in enumerate(sorted_md[:15]):
            lines.append(f"| {i+1} | {s['code']} | {s['name']} | {s['change_pct']:+.1f}% | {s['main_net_yi']:+.2f} |")
        inflow = sum(1 for s in sorted_md if s['main_net_yi'] > 0)
        outflow = sum(1 for s in sorted_md if s['main_net_yi'] < 0)
        lines.append(f"")
        lines.append(f"**板块统计**: {inflow}只流入 / {outflow}只流出")
    else:
        lines.append(f"概念板块资金流: 暂不可取")
    lines.append(f"")

    # 2C
    lines.append(f"### 2C: 融资融券明细")
    lines.append(f"")
    margin_md = report.get("margin_data", {})
    if margin_md and margin_md.get("available"):
        lines.append(f"**最新融资余额**: {margin_md.get('latest_balance_yi',0):.2f}亿 | **趋势**: {margin_md.get('trend','')}")
        lines.append(f"**近5日净买卖**: {margin_md.get('net_flow_5d_yi',0):+.2f}亿 | **近10日**: {margin_md.get('net_flow_10d_yi',0):+.2f}亿")
        lines.append(f"")
        records_md = margin_md.get('records', [])
        if records_md:
            lines.append(f"| 日期 | 融资余额(亿) | 买入额(亿) | 偿还额(亿) | 净买卖(亿) |")
            lines.append(f"|------|------------|-----------|-----------|-----------|")
            for r in records_md[:10]:
                lines.append(f"| {r.get('date','')} | {r.get('rzye_yi',0):.2f} | {r.get('rzmre_yi',0):.2f} | {r.get('rzche_yi',0):.2f} | {r.get('net_yi',0):+.2f} |")
            lines.append(f"")
    else:
        lines.append(f"融资融券: 数据暂不可取")
    lines.append(f"")

    # Part 3-7
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
    any_d = False
    for key, sig in report["danger_signals"].items():
        if sig.get("triggered", False):
            any_d = True
            lines.append(f"- 🔴 **{sig.get('signal_name', key)}** (危险等级: {sig.get('danger_level', '')})")
            lines.append(f"  - {sig.get('meaning', '')}")
            lines.append(f"  - → {sig.get('action', '')}")
    if not any_d:
        lines.append(f"✅ 未检测到高危信号")
    lines.append(f"")

    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 4: 企稳确认清单 (需 ≥4/5)")
    lines.append(f"")
    checks_md = score["stabilization"]["checks"]
    labels_md = {
        "no_new_low": "不再创新低",
        "narrow_range": "振幅 < 5%",
        "flow_normal": "量能正常（不放量）",
        "lows_rising": "最低价抬高",
        "above_ma5": "站上5日均线",
    }
    for key, label in labels_md.items():
        ok = checks_md.get(key, False)
        lines.append(f"- {'✅' if ok else '❌'} {label}")
    lines.append(f"")

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

    news_md = report.get("news", [])
    if news_md:
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Part 7: 近期关键消息")
        lines.append(f"")
        for n in news_md[:6]:
            lines.append(f"- [{n.get('date', '')[:10]}] {n.get('title', '')}")
            s = n.get('summary', '')
            if s:
                lines.append(f"  - {s[:120]}")

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## ⚠️ 研究声明")
    lines.append(f"")
    lines.append(f"1. 安全评分基于可验证的价格/成交量/资金流/消息面规则")
    lines.append(f"2. 买入/卖出参考条件是可验证的信号框架，不是买卖指令")
    lines.append(f"3. 核心原则: 可以少挣，必须少亏 — 安全评分<60坚决不入场")
    lines.append(f"4. 亏损的数学是不对称的: 亏50%需涨100%回本")
    lines.append(f"5. 信号轨: {report.get('track_label', '')}")
    lines.append(f"6. 新ETF仅{report.get('data_days', 0)}个交易日，统计显著性严重不足")
    lines.append(f"7. 所有分析基于公开数据，不构成投资建议")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 7: 主流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    code = "589360"
    target_name = "科创50ETF国泰"
    print(f"[识别] 上海ETF(新上市): {target_name} ({code})")
    print(f"[信号轨] B轨(ETF-量价+消息面+概念板块资金流代理)")

    # ━━ 1. 拉取K线 (东财为主，腾讯新ETF无数据) ━━
    print("[1/5] 拉取日K线...")
    print("  尝试腾讯K线...")
    kline = fetch_kline_tencent(code, days=60)
    if not kline:
        print("  腾讯K线无数据(新ETF)，改用东财push2his...")
        kline = fetch_kline_eastmoney(code, days=60)

    data_days = len(kline)
    print(f"  获取 {data_days} 个交易日K线")
    if kline:
        print(f"  范围: {kline[0]['date']} ~ {kline[-1]['date']}")

    # ━━ 2. 拉取实时行情 ━━
    print("[2/5] 拉取实时行情(腾讯+新浪交叉验证)...")
    realtime = fetch_realtime_with_validation(code)
    print(f"  名称: {realtime.get('name', '未知')} | 价格: {realtime.get('price', 0):.3f}")

    # 用实时行情更新最后一天
    if kline and realtime:
        last = kline[-1]
        today_str = datetime.now().strftime("%Y-%m-%d")
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

    daily = kline
    track = "B"
    track_label = f"B轨(ETF-量价分析+概念板块资金流代理, {data_days}日数据)"

    # ━━ 3. 拉取新闻 ━━
    print("[3/5] 拉取新闻...")
    news = fetch_news("科创50ETF")
    print(f"  获取 {len(news)} 条新闻")

    # ━━ 4. V1.4: 概念板块资金流 + 融资融券 ━━
    print("[4/5] 拉取科创50概念板块资金流...")
    concept_flow = fetch_concept_board_flow(code)
    if concept_flow.get("available"):
        print(f"  板块: {concept_flow.get('board_code','')} | "
              f"成分股{concept_flow.get('stock_count',0)}只 | "
              f"板块主力合计{concept_flow.get('total_main_net_yi',0):+.2f}亿")
    else:
        print(f"  ⚠️ 概念板块不可用: {concept_flow.get('reason','')}")

    print("[4/5] 拉取融资融券...")
    margin_data = fetch_margin_data(code)
    if margin_data.get("available"):
        print(f"  融资余额: {margin_data.get('latest_balance_yi',0):.2f}亿 | "
              f"趋势: {margin_data.get('trend','')} | "
              f"近5日净: {margin_data.get('net_flow_5d_yi',0):+.2f}亿")
    else:
        print(f"  ⚠️ 融资融券不可用: {margin_data.get('reason','')}")

    # ━━ 5. 信号检测 + 安全评分 + 时机 ━━
    print("[5/5] 信号检测 + 安全评分 + 时机参考...")
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

    safety_score = calc_safety_score(safety_signals, danger_signals, daily, track,
                                     margin_data=margin_data, concept_flow=concept_flow,
                                     data_days=data_days)
    timing = generate_timing(safety_score, daily)

    today = daily[-1] if daily else {}
    first_day = daily[0] if daily else {}

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": code,
        "target_type": "etf",
        "target_name": target_name,
        "track": track,
        "track_label": track_label,
        "data_days": data_days,
        "summary": {
            "price": realtime.get("price", today.get("close", 0)),
            "last_close": realtime.get("last_close", 0),
            "open": realtime.get("open", 0),
            "change": realtime.get("change_amt", 0),
            "change_pct": realtime.get("change_pct", 0),
            "high": realtime.get("high", 0),
            "low": realtime.get("low", 0),
            "volume": realtime.get("volume", 0),
            "amount_yi": realtime.get("amount_wan", 0) / 1e4 if realtime.get("amount_wan") else 0,
            "turnover_pct": realtime.get("turnover_pct", 0),
            "pe_ttm": realtime.get("pe_ttm", 0),
            "pb": realtime.get("pb", 0),
            "mcap_yi": realtime.get("mcap_yi", 0),
            "float_mcap_yi": realtime.get("float_mcap_yi", 0),
            "amplitude_pct": realtime.get("amplitude_pct", 0),
            "change_1w": round((today.get("close", 0) - first_day.get("close", 0)) / first_day.get("close", 1) * 100, 1) if first_day.get("close") else 0,
            "change_1m": 0,  # 不足1月
        },
        "realtime": realtime,
        "daily": daily,
        "safety_signals": safety_signals,
        "danger_signals": danger_signals,
        "safety_score": safety_score,
        "timing": timing,
        "news": news[:8] if news else [],
        "concept_flow": concept_flow,
        "margin_data": margin_data,
    }

    # ━━ 打印 + 保存 ━━
    _print_report(report)

    output_dir = f"src/资金预判/{datetime.now().strftime('%Y-%m-%d')}-{target_name}-{code}-安全评估"
    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    md_path = os.path.join(output_dir, "report.md")
    _save_markdown(report, md_path)

    print(f"\n报告已保存: {output_dir}/")
    return report


if __name__ == "__main__":
    main()
