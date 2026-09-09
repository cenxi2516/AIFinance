#!/usr/bin/env python3
"""
fund-flow-predictor 完整分析脚本
标的: 京东方A (000725)
日期: 2026-07-11
类型: 深圳主板个股 → 尝试A轨(资金流), 不可用则降级B轨(量价)
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

CODE = "000725"
PREFIX = "sz"  # 深圳

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 1: 数据采集
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_kline_tencent(code: str, days: int = 60) -> list[dict]:
    """从腾讯获取日K线（前复权 qfq）"""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
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
            "date": date,
            "open": o, "close": c, "high": h, "low": l,
            "volume": v,
            "change_pct": chg,
            "amplitude": amp,
            "main_net": 0, "super_net": 0, "large_net": 0, "mid_net": 0, "small_net": 0,
        })
    return klines


def fetch_realtime_tencent(code: str) -> dict:
    """从腾讯获取实时行情"""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
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


def fetch_fund_flow(code: str) -> list[dict]:
    """尝试拉取个股日级资金流 (push2his)"""
    try:
        from a_stock_api import stock_fund_flow_120d
        raw = stock_fund_flow_120d(code)
        flows = []
        for item in raw:
            flows.append({
                "date": str(item.get("date", ""))[:10],
                "main_net": item.get("main_net_yi") or 0,        # 已是万元(透传)
                "super_net": item.get("super_large_net") or 0,        # 已是万元(透传)
                "large_net": item.get("large_net_yi") or 0,        # 已是万元(透传)
                "mid_net": item.get("mid_net_yi") or 0,        # 已是万元(透传)
                "small_net": item.get("small_net_yi") or 0,        # 已是万元(透传)
            })
        return flows
    except Exception as e:
        print(f"  ⚠️ push2his 不可用({e})，降级为量价分析模式")
        return []


def merge_fund_flow(daily: list[dict], fund_flow: list[dict]):
    """将资金流合并到 daily"""
    flow_map = {f["date"]: f for f in fund_flow}
    for d in daily:
        if d["date"] in flow_map:
            f = flow_map[d["date"]]
            d["main_net"] = round(f["main_net"], 1)
            d["super_net"] = round(f["super_net"], 1)
            d["large_net"] = round(f["large_net"], 1)
            d["mid_net"] = round(f["mid_net"], 1)
            d["small_net"] = round(f["small_net"], 1)


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
# V1.4 新增: 概念板块资金流 + 融资融券
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 个股→概念板块映射
STOCK_CONCEPT_MAP = {
    "000725": "BK0480",  # 京东方A → 面板/OLED概念
}

def _search_concept_board(code: str) -> str | None:
    """通过东财搜索API查找个股所属核心概念板块"""
    try:
        from a_stock_api import em_get
        prefix = "sh" if code.startswith(("6", "9")) else "sz"
        r = requests.get(f'http://qt.gtimg.cn/q={prefix}{code}', timeout=10)
        r.encoding = "gbk"
        name = r.text.split('"')[1].split('~')[1] if '~' in r.text else ""
        if not name:
            return None
        r2 = em_get('https://searchapi.eastmoney.com/api/suggest/get', params={
            'input': name, 'type': '14', 'token': 'D43BF722C8E33BDC906FB84D85E326E8',
            'count': '3'
        }, timeout=15)
        items = r2.json().get('QuotationCodeTable', {}).get('Data', [])
        for item in items:
            bk_code = item.get('Code', '')
            if bk_code.startswith('BK'):
                return bk_code
        return None
    except Exception:
        return None


def fetch_concept_board_flow(code: str) -> dict:
    """获取概念板块成分股资金流排名"""
    board_code = STOCK_CONCEPT_MAP.get(code)
    if not board_code:
        board_code = _search_concept_board(code)
    if not board_code:
        return {"available": False, "reason": "未找到所属概念板块"}

    try:
        from a_stock_api import em_get
        r = em_get('https://push2.eastmoney.com/api/qt/clist/get', params={
            'pn': '1', 'pz': '30', 'po': '0', 'np': '1',
            'fltt': '2', 'invt': '2', 'fid': 'f62',
            'fs': f'b:{board_code}',
            'fields': 'f3,f12,f14,f62'
        }, timeout=15)
        d = r.json()
        items = d.get('data', {}).get('diff', []) if d else []

        stocks = []
        total_main = 0
        target_flow = None
        for item in items:
            main_net_yi = (item.get('f62') or 0) / 1e8
            total_main += main_net_yi
            stock_info = {
                'code': item.get('f12', ''),
                'name': item.get('f14', ''),
                'change_pct': item.get('f3', 0),
                'main_net_yi': round(main_net_yi, 2),
            }
            stocks.append(stock_info)
            if stock_info['code'] == code:
                target_flow = stock_info

        sorted_by_flow = sorted(stocks, key=lambda x: x['main_net_yi'], reverse=True)
        target_rank = next((i+1 for i, s in enumerate(sorted_by_flow) if s['code'] == code), 0)

        return {
            "available": True,
            "board_code": board_code,
            "total_main_net_yi": round(total_main, 2),
            "stock_count": len(stocks),
            "stocks": stocks,
            "target_flow": target_flow,
            "target_rank": target_rank,
            "target_rank_total": len(stocks),
        }
    except Exception as e:
        return {"available": False, "reason": f"概念板块API异常: {e}"}


def fetch_margin_data(code: str) -> dict:
    """获取个股融资融券数据 (datacenter-web, filter用SCODE)"""
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
            "available": True,
            "records": records,
            "latest_balance_yi": records[0]['rzye_yi'] if records else 0,
            "trend": trend,
            "net_flow_5d_yi": round(net_5d, 2),
            "net_flow_10d_yi": round(net_10d, 2),
        }
    except Exception as e:
        return {"available": False, "reason": f"融资融券API异常: {e}"}


def determine_track(daily: list[dict]) -> str:
    """判断信号轨: A(有资金流) 或 B(仅有量价)"""
    has_fund_flow = any(d.get("main_net", 0) != 0 for d in daily)
    return "A" if has_fund_flow else "B"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 2: 安全信号提取 (双轨)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_selling_exhaustion(daily: list[dict], track: str = "B") -> dict:
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}
    recent = daily[-5:]
    lows = [d["low"] for d in recent]
    prev_lows = [d["low"] for d in daily[-10:-5]]
    no_new_low = min(lows) >= min(prev_lows) if prev_lows else False

    if track == "A":
        outflows = [d["main_net"] for d in recent if d["main_net"] < 0]
        if len(outflows) < 3:
            return {"triggered": False, "reason": "近期无持续流出"}
        is_decreasing = all(abs(outflows[i]) > abs(outflows[i+1]) for i in range(len(outflows)-1))
        avg_outflow = sum(abs(o) for o in outflows) / len(outflows)
        ratio = abs(outflows[-1]) / avg_outflow if avg_outflow > 0 else 1
        triggered = is_decreasing and ratio < 0.5 and no_new_low
        return {
            "triggered": triggered,
            "signal_name": "F1: 主力流出衰竭",
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
            "triggered": triggered,
            "signal_name": "F1: 卖压衰竭(量价)",
            "strength": "强" if triggered else "弱",
            "meaning": "卖压在减弱，下跌动能衰竭" if triggered else "卖压尚未衰竭，继续观察",
        }


def detect_institution_return(daily: list[dict], track: str = "B") -> dict:
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}
    if track == "A":
        early = daily[-10:-3]; recent = daily[-3:]
        early_inst = sum(d.get("super_net", 0) for d in early)
        recent_inst = sum(d.get("super_net", 0) for d in recent)
        recent_retail = sum(d.get("mid_net", 0) + d.get("small_net", 0) for d in recent)
        triggered = early_inst < 0 and recent_inst > 0 and recent_retail < 0
        return {
            "triggered": triggered,
            "signal_name": "F2: 机构试探回流",
            "strength": "强" if triggered and recent_inst > abs(early_inst) * 0.3 else ("中" if triggered else "弱"),
            "meaning": "机构开始接盘，散户还在恐慌 → 典型底部特征" if triggered else "机构尚未回流",
        }
    else:
        early = daily[-10:-3]; recent = daily[-3:]
        early_decline = sum(d["change_pct"] for d in early) < -3
        avg_vol_early = sum(d["volume"] for d in early) / len(early)
        has_bullish = any(d["change_pct"] > 2 and d["volume"] > avg_vol_early * 1.5 for d in recent)
        triggered = early_decline and has_bullish
        return {
            "triggered": triggered,
            "signal_name": "F2: 放量反弹回流",
            "strength": "强" if triggered else "弱",
            "meaning": "前期下跌后放量反弹，资金回流迹象" if triggered else "未见明确的资金回流信号",
        }


def detect_retail_exhaustion(daily: list[dict], track: str = "B") -> dict:
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}
    if track == "A":
        recent = daily[-5:]
        retail_flows = [d.get("mid_net", 0) + d.get("small_net", 0) for d in recent]
        if not all(f < 0 for f in retail_flows):
            return {"triggered": False, "reason": "散户未持续流出"}
        recent_3 = retail_flows[-3:]
        is_decreasing = all(abs(recent_3[i]) > abs(recent_3[i+1]) for i in range(len(recent_3)-1))
        prices = [d["close"] for d in recent]
        decline_narrowing = False
        if len(prices) >= 2:
            ed = abs((prices[1]-prices[0])/prices[0]*100) if prices[0]>0 else 0
            ld = abs((prices[-1]-prices[-2])/prices[-2]*100) if prices[-2]>0 else 0
            decline_narrowing = ld < ed
        triggered = all(f < 0 for f in retail_flows) and is_decreasing and decline_narrowing
        return {
            "triggered": triggered,
            "signal_name": "F3: 散户恐慌出尽",
            "strength": "强" if triggered else "弱",
            "meaning": "恐慌盘出清，筹码趋于稳定" if triggered else "恐慌盘可能尚未出尽",
        }
    else:
        recent = daily[-5:]
        changes = [d["change_pct"] for d in recent]
        negatives = [c for c in changes if c < 0]
        decline_narrowing = len(negatives) >= 2 and all(abs(negatives[i]) > abs(negatives[i+1]) for i in range(len(negatives)-1))
        vols = [d["volume"] for d in recent]
        avg_vol_recent = sum(vols)/len(vols)
        prev_vols = [d["volume"] for d in daily[-10:-5]]
        avg_vol_prev = sum(prev_vols)/len(prev_vols) if prev_vols else avg_vol_recent
        vol_shrink = avg_vol_recent < avg_vol_prev * 0.6
        triggered = decline_narrowing and vol_shrink
        return {
            "triggered": triggered,
            "signal_name": "F3: 恐慌出尽(缩量止跌)",
            "strength": "强" if triggered else "弱",
            "meaning": "恐慌盘出清，缩量止跌" if triggered else "恐慌盘可能尚未出尽",
        }


def detect_volume_stabilization(daily: list[dict], track: str = "B") -> dict:
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
        "triggered": triggered,
        "signal_name": "F8: 缩量止跌盘整",
        "strength": "强" if triggered else "弱",
        "meaning": "卖压枯竭，底部盘整中 → 下行空间有限" if triggered else "尚未缩量止跌，仍在波动",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 3: 危险信号检测 (双轨)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_accelerating_selling(daily: list[dict], track: str = "B") -> dict:
    if len(daily) < 8:
        return {"triggered": False, "reason": "数据不足"}
    if track == "A":
        recent_3 = daily[-3:]; prev_5 = daily[-8:-3]
        outflows = [d["main_net"] for d in recent_3]
        if not all(f < 0 for f in outflows):
            return {"triggered": False, "reason": "近期非持续流出"}
        accelerating = abs(outflows[0]) < abs(outflows[1]) < abs(outflows[2])
        avg_prev = sum(abs(d["main_net"]) for d in prev_5) / 5 if prev_5 else 1
        surge = abs(outflows[-1]) > avg_prev * 2
        triggered = all(f < 0 for f in outflows) and accelerating and surge
        return {
            "triggered": triggered,
            "signal_name": "F4: 🔴 主力加速流出",
            "danger_level": "高危",
            "meaning": "卖方力量在加速 → 绝对不要抄底！持币观望" if triggered else "主力流出尚未加速",
            "action": "🚫 不买，已持有则考虑减仓" if triggered else "继续观察",
        }
    else:
        recent_3 = daily[-3:]
        changes = [d["change_pct"] for d in recent_3]
        if not all(c < 0 for c in changes):
            return {"triggered": False, "reason": "近期非持续下跌"}
        accelerating = abs(changes[0]) < abs(changes[1]) < abs(changes[2])
        vols = [d["volume"] for d in recent_3]
        vol_expanding = vols[0] < vols[1] < vols[2]
        avg_vol_prev = sum(d["volume"] for d in daily[-8:-3]) / 5
        vol_surge = vols[-1] > avg_vol_prev * 2
        triggered = all(c < 0 for c in changes) and accelerating and vol_expanding and vol_surge
        return {
            "triggered": triggered,
            "signal_name": "F4: 🔴 加速放量下跌",
            "danger_level": "高危",
            "meaning": "恐慌性抛售！放量加速下跌 → 绝对不要抄底！" if triggered else "下跌尚未加速",
            "action": "🚫 不买，持币观望" if triggered else "继续观察",
        }


def detect_top_distribution(daily: list[dict], track: str = "B") -> dict:
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
            "triggered": triggered,
            "signal_name": "F5: 🔴 顶部派发",
            "danger_level": "高危",
            "meaning": "机构在上涨中出货给散户 → 典型的派发结构" if triggered else "无顶部派发信号",
            "action": "🚫 不买，已持有则考虑减仓" if triggered else "继续观察",
        }
    else:
        early = daily[-10:-3]; recent_2 = daily[-2:]
        early_closes = [d["close"] for d in early]
        if len(early_closes) < 2:
            return {"triggered": False}
        early_rise = (early_closes[-1]-early_closes[0])/early_closes[0]*100 if early_closes[0]>0 else 0
        avg_vol_early = sum(d["volume"] for d in early)/len(early) if early else 1
        has_distribution = any(d["change_pct"] < -3 and d["volume"] > avg_vol_early * 2 for d in recent_2)
        triggered = early_rise > 10 and has_distribution
        return {
            "triggered": triggered,
            "signal_name": "F5: 🔴 高位放量逆转",
            "danger_level": "高危",
            "meaning": f"前期涨{early_rise:.0f}%+放量逆转 → 典型的顶部派发信号" if triggered else "无顶部派发信号",
            "action": "🚫 不追高，已持有则考虑减仓" if triggered else "继续观察",
        }


def detect_news_exhausted(daily: list[dict], news: list[dict]) -> dict:
    if not news:
        return {"triggered": False, "reason": "无消息数据"}
    bullish_keywords = ['涨', '走强', '涨停', '利好', '突破', '新高', '订单', '扩产', '预增', '超预期']
    bullish_news = [n for n in news if any(kw in n.get("title","") for kw in bullish_keywords)]
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}
    early = daily[-15:-5] if len(daily) >= 15 else daily[:-5]
    if len(early) < 5:
        return {"triggered": False}
    early_closes = [d["close"] for d in early]
    pre_rise = (early_closes[-1]-early_closes[0])/early_closes[0]*100 if early_closes[0]>0 else 0
    recent = daily[-2:]
    high_open_low_close = any(d["change_pct"] < -3 for d in recent)
    triggered = pre_rise > 10 and high_open_low_close and len(bullish_news) > 0
    return {
        "triggered": triggered,
        "signal_name": "F7: 🔴 利好出尽/高开低走",
        "danger_level": "非常高",
        "meaning": f"前期涨{pre_rise:.0f}%+利好兑现高开低走 → 大概率回调" if triggered else "前期涨幅可接受或未出现利好兑现",
        "action": "🚫 不要追！等回调充分后再评估" if triggered else "",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 4: 企稳确认检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_stabilization(daily: list[dict], track: str = "B") -> dict:
    if len(daily) < 15:
        return {"is_stabilized": False, "reason": "数据不足"}
    recent = daily[-3:]; prev_10 = daily[-15:-3]
    checks = {}
    recent_lows = [d["low"] for d in recent]
    prev_lows = [d["low"] for d in prev_10]
    checks["no_new_low"] = min(recent_lows) >= min(prev_lows)
    checks["narrow_range"] = all(d["amplitude"] < 5 for d in recent)
    if track == "A":
        recent_outflow = abs(sum(d["main_net"] for d in recent if d["main_net"] < 0))
        prev_outflows = [abs(d["main_net"]) for d in prev_10 if d["main_net"] < 0]
        prev_outflow_avg = sum(prev_outflows) / max(len(prev_outflows), 1)
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
    is_stabilized = passed >= 4
    return {
        "is_stabilized": is_stabilized,
        "passed_count": passed, "total_count": 5,
        "checks": checks,
        "meaning": "企稳确认，下行风险大幅降低" if is_stabilized else f"仅通过{passed}/5项，尚未企稳",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 5: 安全评分计算 (V1.4 track-aware + 融资融券+概念板块修正)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_safety_score(safety_signals: dict, danger_signals: dict, daily: list[dict],
                      track: str = "B", margin_data: dict = None, concept_flow: dict = None) -> dict:
    score = 50
    adjustment_details = []

    if track == "A":
        wmap = {
            "f1_exhaustion": (15, "F1 主力流出衰弱"),
            "f2_institution_return": (12, "F2 机构试探回流"),
            "f3_retail_exhaustion": (10, "F3 散户恐慌出尽"),
            "f8_volume_stabilization": (8, "F8 缩量止跌"),
        }
    else:
        wmap = {
            "f1_exhaustion": (12, "F1 卖压衰竭"),
            "f2_institution_return": (10, "F2 放量反弹回流"),
            "f3_retail_exhaustion": (10, "F3 恐慌出尽"),
            "f8_volume_stabilization": (8, "F8 缩量止跌"),
        }
    for key, (w, label) in wmap.items():
        if safety_signals.get(key, {}).get("triggered"):
            score += w
            adjustment_details.append((label, +w))

    if track == "A":
        dwmap = {
            "f4_accelerating": (22, "F4 主力加速流出"),
            "f5_top_distribution": (20, "F5 顶部派发"),
        }
    else:
        dwmap = {
            "f4_accelerating": (20, "F4 加速放量下跌"),
            "f5_top_distribution": (18, "F5 高位放量逆转"),
        }
    for key, (w, label) in dwmap.items():
        if danger_signals.get(key, {}).get("triggered"):
            score -= w
            adjustment_details.append((label, -w))

    if danger_signals.get("f7_news_exhausted", {}).get("triggered"):
        score -= 15
        adjustment_details.append(("F7 利好出尽", -15))

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

    # V1.4: 融资融券修正
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

    # V1.4: 概念板块资金流修正 (B轨)
    if concept_flow and concept_flow.get("available") and track == "B":
        tf = concept_flow.get("target_flow", {})
        total_main = concept_flow.get("total_main_net_yi", 0)
        target_main = tf.get("main_net_yi", 0) if tf else 0
        if total_main < -5:
            score -= 5
            adjustment_details.append((f"概念板块主力大幅流出({total_main:+.1f}亿)", -5))
        if target_main > 0 and concept_flow.get("target_rank", 99) == 1:
            score += 4
            adjustment_details.append(("概念板块龙头+主力流入", +4))

    score = max(0, min(100, score))

    if score >= 75:
        level, can_enter, desc = "🟢 安全区间", True, "下行风险可控，可考虑入场"
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
        "principle": "可以少挣，必须少亏 — 只有 ≥75 分才建议考虑入场",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 6: 买卖时机参考
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_timing(safety_score: dict, daily: list[dict]) -> dict:
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
        {"condition": "🔴 硬止损: 持仓亏损>5% + 主力仍在净流出", "triggered": False, "rule": "亏损的数学是不对称的", "action": "全部离场"},
        {"condition": "🟠 利润保护: 盈利>5% + 主力连续2日净流出", "triggered": False, "rule": "可以少挣，必须少亏", "action": "至少减仓50%"},
        {"condition": "🔴 任何高危信号触发 (F4/F5/F7)", "triggered": neg_count > 0, "rule": "危险信号 > 一切买入信号", "action": "不买，已持有则评估是否离场"},
        {"condition": "🔴 安全评分降至 < 40分", "triggered": safety_score["safety_score"] < 40, "current": f"{safety_score['safety_score']}分", "rule": "危险区间 = 持币观望", "action": "远离，等安全评分回升"},
    ]
    return {
        "entry": {
            "ready": must_met, "ready_enhanced": all_met,
            "conditions": entry_conditions,
            "verdict": (
                "✅ 买入参考条件全部满足，可考虑入场" if all_met else
                ("⚠️ 必要条件满足但增强信号不足，可小仓试探" if must_met else
                 "❌ 买入条件不满足，继续等待")
            ),
        },
        "exit": {
            "any_triggered": any(c["triggered"] for c in exit_conditions),
            "conditions": exit_conditions,
        },
        "principle": "可以少挣，必须少亏 — 宁可错过，不可做错",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Console 打印
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _print_report(report: dict):
    print()
    print("=" * 90)
    print("  🛡️  买入安全区间研判报告 (V1.4)")
    print(f"  标的: {report['target_name']} ({report['target']})")
    print(f"  类型: {report['target_type']} | 信号轨: {report.get('track_label', '')}")
    print(f"  生成: {report['generated_at']} | 原则: 可以少挣，必须少亏")
    print("=" * 90)

    score = report["safety_score"]
    summary = report.get("summary", {})
    print()
    print("━" * 70)
    print("  🎯 Part 1: 核心结论")
    print("━" * 70)
    print(f"  当前价格: {summary['price']:.2f} | "
          f"涨跌: {summary.get('change', 0):+.2f} ({summary.get('change_pct', 0):+.2f}%)")
    print(f"  今开: {summary.get('open', 0):.2f} | 最高: {summary.get('high', 0):.2f} | "
          f"最低: {summary.get('low', 0):.2f}")
    print(f"  换手率: {summary.get('turnover_pct', 0):.2f}% | "
          f"PE(TTM): {summary.get('pe_ttm', 0):.1f} | PB: {summary.get('pb', 0):.1f}")
    print(f"  总市值: {summary.get('mcap_yi', 0):.1f}亿 | 流通市值: {summary.get('float_mcap_yi', 0):.1f}亿")
    print(f"  1周涨跌: {summary.get('change_1w', 0):+.1f}% | "
          f"1月涨跌: {summary.get('change_1m', 0):+.1f}%")

    print_validation_summary(report.get("realtime", {}).get("_validation", {}))
    print(f"  数据来源: 行情[腾讯+新浪交叉验证] | K线[腾讯] | PE/PB[腾讯单源] | 融资融券[东财单源]")

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

    # ━━ Part 2: 近20日日度数据明细 ━━
    print()
    print("━" * 70)
    print("  📋 Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）")
    print("━" * 70)
    daily = report.get("daily", [])
    realtime = report.get("realtime", {})
    track = report.get("track", "B")

    # 2A: 日度量价明细
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
            # 腾讯K线成交量单位是"手"(1手=100股)
            float_shares = realtime.get("float_mcap_yi", 1) / realtime.get("price", 1) * 1e8 if realtime.get("price") else 5e8
            turnover = round(vol * 100 / float_shares * 100, 2) if float_shares > 0 else 0
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
        today = daily[-1] if daily else {}
        today_vol = today.get("volume", 0)
        today_vol_ratio = round(today_vol / avg_vol_20, 1) if avg_vol_20 > 0 else 0
        today_vol_pct = round((today_vol - vol_min) / (vol_max - vol_min) * 100, 0) if vol_max > vol_min else 50
        today_price_pct = round((today.get("close", 0) - price_60l) / (price_60h - price_60l) * 100, 0) if price_60h > price_60l else 50

        print(f"  📊 今日量:{today_vol:,.0f}手 | 量比:{today_vol_ratio:.1f}x | "
              f"量分位:{today_vol_pct:.0f}%(60日) | 价分位:{today_price_pct:.0f}%(60日)")
        print(f"  📊 20日均量:{avg_vol_20:,.0f}手 | "
              f"60日最高价:{price_60h:.2f} | 60日最低价:{price_60l:.2f} | "
              f"距高:{(today.get('close',0)/price_60h-1)*100:+.1f}% | 距低:{(today.get('close',0)/price_60l-1)*100:+.1f}%")

        all_changes = [d["change_pct"] for d in daily[-20:]]
        big_up = sum(1 for c in all_changes if c > 5)
        up = sum(1 for c in all_changes if 2 < c <= 5)
        flat = sum(1 for c in all_changes if -2 <= c <= 2)
        down = sum(1 for c in all_changes if -5 <= c < -2)
        big_down = sum(1 for c in all_changes if c < -5)
        print(f"  📊 近20日涨跌分布: 🔥大涨{big_up}天 📈上涨{up}天 ➖震荡{flat}天 📉下跌{down}天 💧暴跌{big_down}天")

    # 2B: 资金流向详细
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
            concept_data = report.get("concept_flow", {})
            if concept_data and concept_data.get("available"):
                tf = concept_data.get("target_flow", {})
                print(f"  📊 概念板块资金流 (代理指标 — push2his不可用)")
                print(f"  板块: {concept_data.get('board_code','')} | "
                      f"成分股{concept_data.get('stock_count',0)}只")
                print(f"  板块主力净流合计: {concept_data.get('total_main_net_yi',0):+.2f}亿")
                if tf:
                    main_yi = tf.get('main_net_yi', 0)
                    rank = concept_data.get('target_rank', 0)
                    total = concept_data.get('target_rank_total', 0)
                    flow_icon = "🔴" if main_yi < -1 else ("🟢" if main_yi > 1 else "➖")
                    leader_note = ("🔴 板块内主力流出最多" if main_yi < 0 and rank <= 3 else
                                  ("🟢 板块内主力流入龙头" if main_yi > 0 and rank <= 3 else ""))
                    print(f"  {flow_icon} 目标个股: 主力{main_yi:+.2f}亿 | 板块排名 {rank}/{total} | {leader_note}")
                print(f"\n  📋 板块成分股资金流排名(主力净流):")
                print(f"  {'排名':<5s} {'代码':<8s} {'名称':<10s} {'涨跌':>8s} {'主力净流':>10s}")
                print(f"  {'─'*48}")
                sorted_stocks = sorted(concept_data.get("stocks", []), key=lambda x: x['main_net_yi'], reverse=True)
                for i, s in enumerate(sorted_stocks):
                    marker = " ★目标" if s['code'] == report['target'] else ""
                    print(f"  {i+1:<5d} {s['code']:<8s} {s['name']:<10s} {s['change_pct']:>+7.2f}% {s['main_net_yi']:>+8.2f}亿{marker}")
            else:
                print(f"  📊 概念板块资金流: 暂不可取")
                reason = concept_data.get("reason", "") if concept_data else ""
                if reason: print(f"     ({reason})")

    # 2C: 融资融券明细
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
            print(f"\n  📅 近10日融资日度明细:")
            print(f"  {'日期':<12s} {'融资余额':>10s} {'买入额':>10s} {'偿还额':>10s} {'净买卖':>10s}")
            print(f"  {'─'*55}")
            for r in records[:10]:
                net_mark = "🔴" if r['net_yi'] > 1 else ("🟢" if r['net_yi'] < -1 else "  ")
                print(f"  {r['date']:<12s} {r.get('rzye_yi',0):>8.2f}亿 {r.get('rzmre_yi',0):>8.2f}亿 "
                      f"{r.get('rzche_yi',0):>8.2f}亿 {net_mark}{r.get('net_yi',0):>+8.2f}亿")
        else:
            print(f"  (无日度明细记录)")
    else:
        print(f"  融资融券: 数据暂不可取")
        reason = margin_print.get("reason", "") if margin_print else ""
        if reason: print(f"     ({reason})")

    # ━━ Part 3-7 ━━
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
        "flow_normal": "流出/量能正常",
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
    print("  6. 所有分析基于公开数据，不构成投资建议")
    print("=" * 90)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Markdown 保存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _save_markdown(report: dict, path: str):
    score = report["safety_score"]
    summary = report["summary"]
    daily = report["daily"]
    timing = report["timing"]
    track = report.get("track", "B")
    realtime = report.get("realtime", {})

    lines = []
    lines.append(f"# 🛡️ 买入安全区间研判报告")
    lines.append(f"")
    lines.append(f"**标的**: {report['target_name']} ({report['target']}) | **类型**: 个股 | **信号轨**: {report.get('track_label', '')}")
    lines.append(f"**生成时间**: {report['generated_at']}")
    lines.append(f"**核心原则**: 可以少挣，必须少亏。所有判断用数据说话。")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 1: 核心结论")
    lines.append(f"")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 当前价格 | {summary['price']:.2f} |")
    lines.append(f"| 涨跌幅 | {summary.get('change', 0):+.2f} ({summary.get('change_pct', 0):+.2f}%) |")
    lines.append(f"| 换手率 | {summary.get('turnover_pct', 0):.2f}% |")
    lines.append(f"| PE(TTM) | {summary.get('pe_ttm', 0):.1f} |")
    lines.append(f"| PB | {summary.get('pb', 0):.1f} |")
    lines.append(f"| 总市值 | {summary.get('mcap_yi', 0):.1f}亿 |")
    lines.append(f"| 1周涨跌 | {summary.get('change_1w', 0):+.1f}% |")
    lines.append(f"| 1月涨跌 | {summary.get('change_1m', 0):+.1f}% |")
    lines.append(f"| 安全评分 | **{score['safety_score']}/100** → {score['safety_level']} |")
    lines.append(f"| 企稳状态 | {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} ({score['stabilization']['passed_count']}/5项) |")
    lines.append(f"| 能否入场 | {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'} |")

    validation_md_lines = markdown_validation_summary(
        report.get("realtime", {}).get("_validation", {})
    )
    lines.extend(validation_md_lines)
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
    lines.append(f"## Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）")
    lines.append(f"")
    lines.append(f"### 2A: 日度量价明细")
    lines.append(f"")
    if daily:
        vols_20_data = [d["volume"] for d in daily[-25:-5] if d.get("volume")]
        avg_vol_20_md = sum(vols_20_data) / len(vols_20_data) if vols_20_data else 1
        all_vols_md = [d["volume"] for d in daily if d.get("volume")]
        all_prices_md = [d["close"] for d in daily if d.get("close")]
        vol_max_md = max(all_vols_md) if all_vols_md else 1
        vol_min_md = min(all_vols_md) if all_vols_md else 0
        price_60h_md = max(all_prices_md) if all_prices_md else 1
        price_60l_md = min(all_prices_md) if all_prices_md else 0

        if track == "A":
            lines.append(f"| 日期 | 收盘 | 涨跌幅 | 振幅 | 换手率 | 量比 | 主力净流(万) | 走势 |")
            lines.append(f"|------|------|--------|------|--------|------|-------------|------|")
        else:
            lines.append(f"| 日期 | 收盘 | 涨跌幅 | 振幅 | 换手率 | 量比 | 价分位 | 走势 |")
            lines.append(f"|------|------|--------|------|--------|------|--------|------|")

        for d in daily[-20:]:
            date = d.get("date", "")
            close = d.get("close", 0)
            chg = d.get("change_pct", 0)
            amp = d.get("amplitude", 0)
            vol = d.get("volume", 0)
            float_shares_data = realtime.get("float_mcap_yi", 1) / realtime.get("price", 1) * 1e8 if realtime.get("price") else 5e8
            turnover_md = round(vol * 100 / float_shares_data * 100, 2) if float_shares_data > 0 else 0
            vol_ratio_md = round(vol / avg_vol_20_md, 2) if avg_vol_20_md > 0 else 0
            price_pct_md = round((close - price_60l_md) / (price_60h_md - price_60l_md) * 100, 0) if price_60h_md > price_60l_md else 50

            if chg > 5: trend = "🔥大涨"
            elif chg > 2: trend = "📈上涨"
            elif chg > -2: trend = "➖震荡"
            elif chg > -5: trend = "📉下跌"
            else: trend = "💧暴跌"

            if track == "A":
                main_net = d.get("main_net", 0)
                lines.append(f"| {date} | {close:.2f} | {chg:+.2f}% | {amp:.2f}% | {turnover_md:.2f}% | {vol_ratio_md:.1f}x | {main_net:+.0f} | {trend} |")
            else:
                lines.append(f"| {date} | {close:.2f} | {chg:+.2f}% | {amp:.2f}% | {turnover_md:.2f}% | {vol_ratio_md:.1f}x | {price_pct_md:.0f}% | {trend} |")

        today_md = daily[-1] if daily else {}
        today_vol_md = today_md.get("volume", 0)
        today_vol_ratio_md = round(today_vol_md / avg_vol_20_md, 1) if avg_vol_20_md > 0 else 0
        today_vol_pct_md = round((today_vol_md - vol_min_md) / (vol_max_md - vol_min_md) * 100, 0) if vol_max_md > vol_min_md else 50
        today_price_pct_md = round((today_md.get("close", 0) - price_60l_md) / (price_60h_md - price_60l_md) * 100, 0) if price_60h_md > price_60l_md else 50

        lines.append(f"")
        lines.append(f"> **今日量**: {today_vol_md:,.0f}手 | **量比**: {today_vol_ratio_md:.1f}x | **量分位(60日)**: {today_vol_pct_md:.0f}% | **价分位(60日)**: {today_price_pct_md:.0f}%")
        lines.append(f"> **20日均量**: {avg_vol_20_md:,.0f}手 | **60日最高价**: {price_60h_md:.2f} | **60日最低价**: {price_60l_md:.2f}")
    lines.append(f"")

    # 2B
    lines.append(f"### 2B: 资金流向详细")
    lines.append(f"")
    if daily:
        recent_5_md = daily[-5:]
        recent_10_md = daily[-10:]
        if track == "A":
            inst_5d_md = sum(d.get("super_net", 0) for d in recent_5_md)
            hm_5d_md = sum(d.get("large_net", 0) for d in recent_5_md)
            mid_5d_md = sum(d.get("mid_net", 0) for d in recent_5_md)
            small_5d_md = sum(d.get("small_net", 0) for d in recent_5_md)
            main_5d_md = inst_5d_md + hm_5d_md
            lines.append(f"#### 近5日资金组成")
            lines.append(f"")
            lines.append(f"| 类型 | 净额(万元) | 净额(亿元) | 方向 |")
            lines.append(f"|------|-----------|-----------|------|")
            lines.append(f"| 超大单(机构) | {inst_5d_md:+.0f} | {inst_5d_md/1e4:+.2f} | {'流入' if inst_5d_md>0 else '流出'} |")
            lines.append(f"| 大单(游资) | {hm_5d_md:+.0f} | {hm_5d_md/1e4:+.2f} | |")
            lines.append(f"| 中单 | {mid_5d_md:+.0f} | {mid_5d_md/1e4:+.2f} | |")
            lines.append(f"| 小单(散户) | {small_5d_md:+.0f} | {small_5d_md/1e4:+.2f} | |")
            lines.append(f"| **主力合计** | **{main_5d_md:+.0f}** | **{main_5d_md/1e4:+.2f}** | |")
            lines.append(f"")
            if inst_5d_md < -500 and small_5d_md > 100:
                lines.append(f"⚠️ **筹码结构**: 机构卖+散户买 → 派发结构")
            elif inst_5d_md > 500 and small_5d_md < -100:
                lines.append(f"✅ **筹码结构**: 机构买+散户卖 → 吸筹结构")
            lines.append(f"")
            main_10d_md = sum(d.get("super_net", 0) + d.get("large_net", 0) for d in recent_10_md)
            trend_label_md = ("加速流入" if main_5d_md > main_10d_md * 0.7 else
                             ("流出放缓" if main_5d_md > main_10d_md * 0.3 else "趋势一致"))
            lines.append(f"**资金趋势**: 近10日主力 {main_10d_md/1e4:+.2f}亿 | 近5日主力 {main_5d_md/1e4:+.2f}亿 | {trend_label_md}")
            lines.append(f"")
            lines.append(f"#### 近5日每日资金明细(万元)")
            lines.append(f"")
            lines.append(f"| 日期 | 主力净流 | 超大单(机构) | 大单(游资) | 中单 | 小单(散户) |")
            lines.append(f"|------|---------|------------|----------|------|----------|")
            for d in recent_5_md:
                lines.append(f"| {d.get('date','')} | {d.get('main_net',0):+.0f} | {d.get('super_net',0):+.0f} | {d.get('large_net',0):+.0f} | {d.get('mid_net',0):+.0f} | {d.get('small_net',0):+.0f} |")
            lines.append(f"")
        else:
            concept_data_md = report.get("concept_flow", {})
            if concept_data_md and concept_data_md.get("available"):
                lines.append(f"#### 概念板块资金流 (代理指标)")
                lines.append(f"")
                lines.append(f"板块: {concept_data_md.get('board_code','')} | 成分股: {concept_data_md.get('stock_count',0)}只")
                lines.append(f"板块主力净流合计: {concept_data_md.get('total_main_net_yi',0):+.2f}亿")
                tf = concept_data_md.get("target_flow", {})
                if tf:
                    lines.append(f"目标个股: 主力{tf.get('main_net_yi',0):+.2f}亿 | 排名 {concept_data_md.get('target_rank',0)}/{concept_data_md.get('target_rank_total',0)}")
                lines.append(f"")
                lines.append(f"| 排名 | 代码 | 名称 | 涨跌幅 | 主力净流(亿) |")
                lines.append(f"|------|------|------|--------|-------------|")
                sorted_stocks_md = sorted(concept_data_md.get("stocks", []), key=lambda x: x['main_net_yi'], reverse=True)
                for i, s in enumerate(sorted_stocks_md):
                    marker = " **←目标**" if s['code'] == report['target'] else ""
                    lines.append(f"| {i+1} | {s['code']} | {s['name']} | {s['change_pct']:+.1f}% | {s['main_net_yi']:+.2f}{marker} |")
                lines.append(f"")
            else:
                lines.append(f"资金流向: B轨无直接资金流数据，概念板块API也暂不可取")
                lines.append(f"")
    lines.append(f"")

    # 2C
    lines.append(f"### 2C: 融资融券明细")
    lines.append(f"")
    margin_md = report.get("margin_data", {})
    if margin_md and margin_md.get("available"):
        lines.append(f"**最新融资余额**: {margin_md.get('latest_balance_yi', 0):.2f}亿 | **趋势**: {margin_md.get('trend', '')}")
        lines.append(f"**近5日净买卖**: {margin_md.get('net_flow_5d_yi', 0):+.2f}亿 | **近10日**: {margin_md.get('net_flow_10d_yi', 0):+.2f}亿")
        lines.append(f"")
        records_md = margin_md.get("records", [])
        if records_md:
            lines.append(f"| 日期 | 融资余额(亿) | 买入额(亿) | 偿还额(亿) | 净买卖(亿) |")
            lines.append(f"|------|------------|-----------|-----------|-----------|")
            for r in records_md[:10]:
                lines.append(f"| {r.get('date','')} | {r.get('rzye_yi',0):.2f} | {r.get('rzmre_yi',0):.2f} | {r.get('rzche_yi',0):.2f} | {r.get('net_yi',0):+.2f} |")
            lines.append(f"")
    else:
        lines.append(f"融资融券: 数据暂不可取")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 3: 安全信号检测")
    lines.append(f"")
    for key, sig in report["safety_signals"].items():
        triggered = sig.get("triggered", False)
        icon = "🟢" if triggered else "⚪"
        lines.append(f"- {icon} **{sig.get('signal_name', key)}**: {sig.get('meaning', '')}")
    lines.append(f"")

    lines.append(f"## Part 4: 危险信号检测")
    lines.append(f"")
    any_danger_md = False
    for key, sig in report["danger_signals"].items():
        if sig.get("triggered"):
            any_danger_md = True
            lines.append(f"- 🔴 **{sig.get('signal_name', key)}** (危险等级: {sig.get('danger_level', '')})")
            lines.append(f"  - {sig.get('meaning', '')}")
            lines.append(f"  - → {sig.get('action', '')}")
    if not any_danger_md:
        lines.append(f"✅ 未检测到高危信号")
    lines.append(f"")

    lines.append(f"## Part 5: 企稳确认清单 (需 ≥4/5)")
    lines.append(f"")
    checks_md = score["stabilization"]["checks"]
    labels_md = {
        "no_new_low": "不再创新低",
        "narrow_range": "振幅 < 5%",
        "flow_normal": "流出/量能正常",
        "lows_rising": "最低价抬高",
        "above_ma5": "站上5日均线",
    }
    for key, label in labels_md.items():
        ok = checks_md.get(key, False)
        lines.append(f"- {'✅' if ok else '❌'} {label}")
    lines.append(f"")

    lines.append(f"## Part 6: 买入时机参考条件")
    lines.append(f"")
    for cond in timing["entry"]["conditions"]:
        met = cond["met"]
        icon = "✅" if met else "❌"
        lines.append(f"- {icon} [{cond['weight']}] {cond['condition']} — 当前: {cond['current']}")
    lines.append(f"")
    lines.append(f"**综合判断**: {timing['entry']['verdict']}")
    lines.append(f"")

    lines.append(f"## Part 7: 离场/风控参考")
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
        lines.append(f"## Part 8: 近期关键消息")
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
    lines.append(f"6. 所有分析基于公开数据，不构成投资建议")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"🛡️  fund-flow-predictor V1.4 — 京东方A(000725)")
    print(f"═" * 50)

    # Step 1: K线
    print("[1/6] 拉取腾讯日K线(qfq)...")
    daily = fetch_kline_tencent(CODE, days=60)
    print(f"  获取 {len(daily)} 个交易日")

    # Step 2: 实时行情 (腾讯+新浪交叉验证)
    print("[2/6] 拉取实时行情(腾讯+新浪交叉验证)...")
    realtime = fetch_realtime_with_validation(CODE)
    validation = realtime.get("_validation", {})
    print(f"  数据质量: {validation.get('quality', '未知')}")

    # Step 3: 资金流 (push2his, 大概率拦截)
    print("[3/6] 拉取个股资金流(push2his)...")
    fund_flow = fetch_fund_flow(CODE)
    if fund_flow:
        merge_fund_flow(daily, fund_flow)

    # Step 4: 新闻
    print("[4/6] 拉取新闻...")
    keyword = realtime.get("name", "京东方A")
    news = fetch_news(keyword)

    # Step 5: 行业资金流 + 概念板块
    print("[5/6] 拉取概念板块资金流 + 融资融券...")
    industry_flow = fetch_industry_flows()
    concept_flow = fetch_concept_board_flow(CODE)
    if concept_flow.get("available"):
        print(f"  概念板块: {concept_flow.get('board_code')} ({concept_flow.get('stock_count')}只成分股)")
    margin_data = fetch_margin_data(CODE)
    if margin_data.get("available"):
        print(f"  融资余额: {margin_data.get('latest_balance_yi', 0):.2f}亿")
    else:
        print(f"  融资数据: {margin_data.get('reason', '')}")
    print(f"  新闻: {len(news)}条")

    # 确定信号轨
    track = determine_track(daily)
    track_label = "个股轨(资金流+量价)" if track == "A" else "ETF轨(量价+消息面)"
    print(f"[6/6] 信号轨: {track_label}")

    # 安全信号检测
    print()
    print("安全信号检测...")
    safety_signals = {
        "f1_exhaustion": detect_selling_exhaustion(daily, track),
        "f2_institution_return": detect_institution_return(daily, track),
        "f3_retail_exhaustion": detect_retail_exhaustion(daily, track),
        "f8_volume_stabilization": detect_volume_stabilization(daily, track),
    }

    # 危险信号检测
    print("危险信号检测...")
    danger_signals = {
        "f4_accelerating": detect_accelerating_selling(daily, track),
        "f5_top_distribution": detect_top_distribution(daily, track),
        "f7_news_exhausted": detect_news_exhausted(daily, news),
    }

    # 评分
    print("计算安全评分...")
    safety_score = calc_safety_score(safety_signals, danger_signals, daily, track, margin_data, concept_flow)

    # 时机
    timing = generate_timing(safety_score, daily)

    # 更新时间戳
    realtime_update = {
        "price": realtime.get("price", 0),
        "open": realtime.get("open", 0),
        "high": realtime.get("high", 0),
        "low": realtime.get("low", 0),
        "volume": realtime.get("volume", 0),
    }
    # 用实时行情更新最后一天
    if daily:
        last = daily[-1]
        today_str = datetime.now().strftime("%Y-%m-%d")
        if last["date"] == today_str:
            last["close"] = realtime_update["price"]
            last["open"] = realtime_update["open"]
            last["high"] = realtime_update["high"]
            last["low"] = realtime_update["low"]
            last["volume"] = realtime_update["volume"]
            if last["open"] > 0:
                last["change_pct"] = round((last["close"] - last["open"]) / last["open"] * 100, 2)
            if last["low"] > 0:
                last["amplitude"] = round((last["high"] - last["low"]) / last["low"] * 100, 2)

    # 价格摘要
    today_d = daily[-1] if daily else {}
    week_ago = daily[-6] if len(daily) >= 6 else (daily[0] if daily else {})
    month_ago = daily[-22] if len(daily) >= 22 else (daily[0] if daily else {})

    # 构建报告
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": CODE,
        "target_type": "stock",
        "target_name": realtime.get("name", "京东方A"),
        "track": track,
        "track_label": track_label,
        "summary": {
            "price": realtime.get("price", 0),
            "last_close": realtime.get("last_close", 0),
            "change": realtime.get("change_amt", 0),
            "change_pct": realtime.get("change_pct", 0),
            "open": realtime.get("open", 0),
            "high": realtime.get("high", 0),
            "low": realtime.get("low", 0),
            "volume": realtime.get("volume", 0),
            "amount_wan": realtime.get("amount_wan", 0),
            "turnover_pct": realtime.get("turnover_pct", 0),
            "pe_ttm": realtime.get("pe_ttm", 0),
            "pb": realtime.get("pb", 0),
            "mcap_yi": realtime.get("mcap_yi", 0),
            "float_mcap_yi": realtime.get("float_mcap_yi", 0),
            "change_1w": round((today_d.get("close", 0) - week_ago.get("close", 0)) / week_ago.get("close", 1) * 100, 1) if week_ago.get("close", 0) > 0 else 0,
            "change_1m": round((today_d.get("close", 0) - month_ago.get("close", 0)) / month_ago.get("close", 1) * 100, 1) if month_ago.get("close", 0) > 0 else 0,
        },
        "realtime": realtime,
        "daily": daily,
        "industry_flow": industry_flow,
        "concept_flow": concept_flow,
        "margin_data": margin_data,
        "safety_signals": safety_signals,
        "danger_signals": danger_signals,
        "safety_score": safety_score,
        "timing": timing,
        "news": news,
        "principle": "可以少挣，必须少亏。所有判断基于数据，每个信号绑定可验证条件。",
    }

    # 打印报告
    _print_report(report)

    # 保存
    output_dir = f"src/资金预判/{datetime.now().strftime('%Y-%m-%d')}-京东方A-安全评估"
    os.makedirs(output_dir, exist_ok=True)

    # JSON
    json_path = os.path.join(output_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    # Markdown
    md_path = os.path.join(output_dir, "report.md")
    _save_markdown(report, md_path)

    print(f"\n  报告已保存: {output_dir}/")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
