#!/usr/bin/env python3
"""
fund-flow-predictor 完整分析脚本
标的: 铖昌科技 (001270)
日期: 2026-07-16
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

CODE = "001270"
NAME = "铖昌科技"

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
    """尝试拉取个股日级资金流 (push2his)

    注意: stock_fund_flow_120d 返回字段为 main_net_yi / super_large_net /
    large_net_yi / mid_net_yi / small_net_yi，单位已是【万元】(字段名带_yi 系命名误导，
    实为 元÷10000)。本脚 daily 内部统一用【万元】，直接透传即可。
    （V1.4 修正: ①原用不匹配字段名 main_net/super_net 全取0→误判B轨;
      ②原误以为返回是亿元又×10000，导致数值放大1万倍）
    """
    try:
        from a_stock_api import stock_fund_flow_120d
        raw = stock_fund_flow_120d(code)
        flows = []
        for item in raw:
            flows.append({
                "date": str(item.get("date", ""))[:10],
                "main_net": item.get("main_net_yi") or 0,        # 已是万元
                "super_net": item.get("super_large_net") or 0,
                "large_net": item.get("large_net_yi") or 0,
                "mid_net": item.get("mid_net_yi") or 0,
                "small_net": item.get("small_net_yi") or 0,
            })
        return flows
    except Exception as e:
        print(f"  ⚠️ push2his 不可用({e})，降级为量价分析模式")
        return []


def merge_fund_flow(daily: list[dict], fund_flow: list[dict]):
    """将资金流合并到 daily K线数据中"""
    flow_map = {f["date"]: f for f in fund_flow}
    merged = 0
    for d in daily:
        if d["date"] in flow_map:
            f = flow_map[d["date"]]
            d["main_net"] = round(f["main_net"], 1)
            d["super_net"] = round(f["super_net"], 1)
            d["large_net"] = round(f["large_net"], 1)
            d["mid_net"] = round(f["mid_net"], 1)
            d["small_net"] = round(f["small_net"], 1)
            merged += 1
    return merged


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

STOCK_CONCEPT_MAP = {
    "001270": "BK0492",  # 铖昌科技 → 半导体概念
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
    """获取个股所属概念板块的成分股资金流排名"""
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
    """获取个股融资融券数据"""
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
            "total_records": d.get('result', {}).get('count', 0) if d and d.get('result') else 0,
        }
    except Exception as e:
        return {"available": False, "reason": f"融资融券API异常: {e}"}


def determine_track(daily: list[dict]) -> str:
    """判断使用哪个信号轨"""
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
            "no_new_low": no_new_low,
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
            "triggered": triggered, "signal_name": "F2: 机构试探回流",
            "early_institution_net": round(early_inst, 1),
            "recent_institution_net": round(recent_inst, 1),
            "recent_retail_net": round(recent_retail, 1),
            "strength": "强" if triggered and recent_inst > abs(early_inst)*0.3 else ("中" if triggered else "弱"),
            "meaning": "机构开始接盘，散户还在恐慌 → 典型底部特征" if triggered else "机构尚未回流",
        }
    else:
        early = daily[-10:-3]; recent = daily[-3:]
        early_changes = [d["change_pct"] for d in early]
        early_decline = sum(early_changes) < -3
        avg_vol_early = sum(d["volume"] for d in early) / len(early)
        has_bullish = any(d["change_pct"] > 2 and d["volume"] > avg_vol_early*1.5 for d in recent)
        triggered = early_decline and has_bullish
        return {
            "triggered": triggered, "signal_name": "F2: 放量反弹回流",
            "early_decline": early_decline, "has_bullish_volume": has_bullish,
            "strength": "强" if triggered else "弱",
            "meaning": "前期下跌后放量反弹，资金回流迹象" if triggered else "未见明确的资金回流信号",
        }


def detect_retail_exhaustion(daily: list[dict], track: str = "B") -> dict:
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
        if len(prices) >= 2:
            early_decline = abs((prices[1]-prices[0])/prices[0]*100) if prices[0]>0 else 0
            late_decline = abs((prices[-1]-prices[-2])/prices[-2]*100) if prices[-2]>0 else 0
            decline_narrowing = late_decline < early_decline
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
        decline_narrowing = len(negatives) >= 2 and all(abs(negatives[i]) > abs(negatives[i+1]) for i in range(len(negatives)-1))
        vols = [d["volume"] for d in recent]
        avg_vol_recent = sum(vols)/len(vols)
        prev_vols = [d["volume"] for d in daily[-10:-5]]
        avg_vol_prev = sum(prev_vols)/len(prev_vols) if prev_vols else avg_vol_recent
        vol_shrink = avg_vol_recent < avg_vol_prev * 0.6
        triggered = decline_narrowing and vol_shrink
        return {
            "triggered": triggered, "signal_name": "F3: 恐慌出尽(缩量止跌)",
            "decline_narrowing": decline_narrowing, "volume_shrink": vol_shrink,
            "strength": "强" if triggered else "弱",
            "meaning": "恐慌盘出清，缩量止跌" if triggered else "恐慌盘可能尚未出尽",
        }


def detect_volume_stabilization(daily: list[dict], track: str = "B") -> dict:
    if len(daily) < 20:
        return {"triggered": False, "reason": "数据不足（需20日）"}
    recent_3 = daily[-3:]; prev_20 = daily[-20:]
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 3: 危险信号检测 (双轨)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_accelerating_selling(daily: list[dict], track: str = "B") -> dict:
    if len(daily) < 8:
        return {"triggered": False, "reason": "数据不足"}
    if track == "A":
        recent_3 = daily[-3:]; prev_5 = daily[-8:-3]
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
            "latest_vs_avg_ratio": round(abs(outflows[-1])/avg_prev, 1) if avg_prev > 0 else 0,
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
            "vol_surge_ratio": round(vols[-1]/avg_vol_prev, 1) if avg_vol_prev > 0 else 0,
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
            "triggered": triggered, "signal_name": "F5: 🔴 顶部派发",
            "danger_level": "高危", "price_up": price_up,
            "institution_outflow": inst_out, "retail_inflow": retail_in,
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
        has_distribution = any(d["change_pct"] < -3 and d["volume"] > avg_vol_early*2 for d in recent_2)
        triggered = early_rise > 10 and has_distribution
        return {
            "triggered": triggered, "signal_name": "F5: 🔴 高位放量逆转",
            "danger_level": "高危", "early_rise_pct": round(early_rise, 1),
            "has_distribution": has_distribution,
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
        "triggered": triggered, "signal_name": "F7: 🔴 利好出尽/高开低走",
        "danger_level": "非常高", "pre_rise_2w": round(pre_rise, 1),
        "latest_news": bullish_news[0].get("title", "")[:60] if bullish_news else "",
        "meaning": f"前期涨{pre_rise:.0f}%+利好兑现高开低走 → 大概率回调" if triggered else "前期涨幅可接受或未出现利好兑现",
        "action": "🚫 不要追！等回调充分后再评估" if triggered else "",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Layer 4: 企稳确认检查 + 安全评分 + 买卖时机
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
        "is_stabilized": is_stabilized, "passed_count": passed, "total_count": 5,
        "checks": checks,
        "meaning": "企稳确认，下行风险大幅降低" if is_stabilized else f"仅通过{passed}/5项，尚未企稳",
    }


def calc_safety_score(safety_signals: dict, danger_signals: dict, daily: list[dict],
                      track: str = "B", margin_data: dict = None, concept_flow: dict = None) -> dict:
    score = 50
    adjustment_details = []

    if track == "A":
        if safety_signals.get("f1_exhaustion", {}).get("triggered"): score += 15; adjustment_details.append(("F1 主力流出衰竭", +15))
        if safety_signals.get("f2_institution_return", {}).get("triggered"): score += 12; adjustment_details.append(("F2 机构试探回流", +12))
        if safety_signals.get("f3_retail_exhaustion", {}).get("triggered"): score += 10; adjustment_details.append(("F3 散户恐慌出尽", +10))
        if safety_signals.get("f8_volume_stabilization", {}).get("triggered"): score += 8; adjustment_details.append(("F8 缩量止跌", +8))
    else:
        if safety_signals.get("f1_exhaustion", {}).get("triggered"): score += 12; adjustment_details.append(("F1 卖压衰竭", +12))
        if safety_signals.get("f2_institution_return", {}).get("triggered"): score += 10; adjustment_details.append(("F2 放量反弹回流", +10))
        if safety_signals.get("f3_retail_exhaustion", {}).get("triggered"): score += 10; adjustment_details.append(("F3 恐慌出尽", +10))
        if safety_signals.get("f8_volume_stabilization", {}).get("triggered"): score += 8; adjustment_details.append(("F8 缩量止跌", +8))

    if track == "A":
        if danger_signals.get("f4_accelerating", {}).get("triggered"): score -= 22; adjustment_details.append(("F4 主力加速流出", -22))
        if danger_signals.get("f5_top_distribution", {}).get("triggered"): score -= 20; adjustment_details.append(("F5 顶部派发", -20))
    else:
        if danger_signals.get("f4_accelerating", {}).get("triggered"): score -= 20; adjustment_details.append(("F4 加速放量下跌", -20))
        if danger_signals.get("f5_top_distribution", {}).get("triggered"): score -= 18; adjustment_details.append(("F5 高位放量逆转", -18))
    if danger_signals.get("f7_news_exhausted", {}).get("triggered"): score -= 15; adjustment_details.append(("F7 利好出尽", -15))

    stabilization = check_stabilization(daily, track)
    if stabilization["is_stabilized"]: score += 10; adjustment_details.append(("企稳确认", +10))

    if len(daily) >= 20:
        ma20 = sum(d["close"] for d in daily[-20:]) / 20
        current = daily[-1]["close"]
        deviation = (current - ma20) / ma20 * 100
        if deviation > 15: score -= 5; adjustment_details.append((f"偏离20MA+{deviation:.0f}%(超买)", -5))
        elif deviation < -10: score += 5; adjustment_details.append((f"偏离20MA{deviation:.0f}%(超卖)", +5))

    if len(daily) >= 20:
        avg_vol_20 = sum(d["volume"] for d in daily[-20:]) / 20
        today_vol = daily[-1]["volume"]
        vol_ratio = today_vol / avg_vol_20
        if vol_ratio > 3.0 and daily[-1]["change_pct"] < -3: score -= 8; adjustment_details.append((f"恐慌放量({vol_ratio:.1f}x均量+大跌)", -8))
        elif vol_ratio > 2.0 and daily[-1]["change_pct"] < -2: score -= 5; adjustment_details.append((f"放量下跌({vol_ratio:.1f}x均量)", -5))
        elif vol_ratio < 0.4 and abs(daily[-1]["change_pct"]) < 1: score += 3; adjustment_details.append(("缩量止跌企稳", +3))

    if margin_data and margin_data.get("available"):
        trend = margin_data.get("trend", "")
        net_5d = margin_data.get("net_flow_5d_yi", 0)
        if trend == "下降" and net_5d < -1: score -= 7; adjustment_details.append((f"融资去杠杆(近5日{net_5d:+.1f}亿)", -7))
        elif trend == "下降" and net_5d < 0: score -= 4; adjustment_details.append((f"融资温和下降(近5日{net_5d:+.1f}亿)", -4))
        elif trend == "上升" and net_5d > 2: score += 5; adjustment_details.append((f"融资加杠杆(近5日+{net_5d:.1f}亿)", +5))
        elif trend == "上升" and net_5d > 0: score += 3; adjustment_details.append((f"融资温和上升(近5日+{net_5d:.1f}亿)", +3))

    if concept_flow and concept_flow.get("available") and track == "B":
        tf = concept_flow.get("target_flow", {})
        total_main = concept_flow.get("total_main_net_yi", 0)
        target_main = tf.get("main_net_yi", 0) if tf else 0
        if total_main < -5: score -= 5; adjustment_details.append((f"概念板块主力大幅流出({total_main:+.1f}亿)", -5))
        if target_main > 0 and concept_flow.get("target_rank", 99) == 1: score += 4; adjustment_details.append(("概念板块龙头+主力流入", +4))

    score = max(0, min(100, score))

    if score >= 75: level, can_enter, desc = "🟢 安全区间", True, "下行风险可控，可考虑入场（配合买入参考条件）"
    elif score >= 60: level, can_enter, desc = "🟡 接近安全", False, "部分条件满足，再等1-3日确认"
    elif score >= 40: level, can_enter, desc = "🟠 风险区间", False, "安全信号不足或有危险信号，不建议入场"
    else: level, can_enter, desc = "🔴 危险区间", False, "存在高危信号，远离，持币观望"

    positive = [sig.get("signal_name", key) for key, sig in safety_signals.items() if sig.get("triggered")]
    negative = [sig.get("signal_name", key) for key, sig in danger_signals.items() if sig.get("triggered")]

    return {
        "safety_score": score, "safety_level": level, "can_enter": can_enter,
        "description": desc, "positive_signals": positive, "negative_signals": negative,
        "adjustment_details": adjustment_details, "stabilization": stabilization,
        "principle": "可以少挣，必须少亏 — 只有 ≥75 分才建议考虑入场",
    }


def generate_timing(safety_score: dict, daily: list[dict]) -> dict:
    entry_conditions = []
    entry_conditions.append({"condition": "安全评分 ≥ 75分", "met": safety_score["safety_score"] >= 75, "current": f"{safety_score['safety_score']}分", "weight": "必须"})
    entry_conditions.append({"condition": "企稳确认 (≥4/5项)", "met": safety_score["stabilization"]["is_stabilized"], "current": f"{safety_score['stabilization']['passed_count']}/5项", "weight": "必须"})
    pos_count = len(safety_score["positive_signals"])
    entry_conditions.append({"condition": "≥2个安全信号触发", "met": pos_count >= 2, "current": f"{pos_count}个", "weight": "建议"})
    neg_count = len(safety_score["negative_signals"])
    entry_conditions.append({"condition": "无危险信号", "met": neg_count == 0, "current": f"{neg_count}个危险信号" if neg_count > 0 else "0个", "weight": "必须"})
    recent_3 = daily[-3:] if len(daily) >= 3 else daily
    has_confirmation = any(d["change_pct"] > 2 for d in recent_3)
    entry_conditions.append({"condition": "近日放量阳线确认（增强信号）", "met": has_confirmation, "current": "已出现" if has_confirmation else "未出现", "weight": "加分项（非必须）"})
    must_met = all(c["met"] for c in entry_conditions if c["weight"] == "必须")
    all_met = all(c["met"] for c in entry_conditions)

    exit_conditions = []
    exit_conditions.append({"condition": "🔴 硬止损: 持仓亏损>5% + 主力仍在净流出", "triggered": False, "rule": "F13: 亏损控制", "action": "全部离场"})
    exit_conditions.append({"condition": "🟠 利润保护: 盈利>5% + 主力连续2日净流出", "triggered": False, "rule": "F12: 利润保护", "action": "至少减仓50%"})
    exit_conditions.append({"condition": "🔴 任何高危信号触发 (F4/F5/F7)", "triggered": neg_count > 0, "current": f"{neg_count}个危险信号" if neg_count > 0 else "无", "rule": "危险信号 > 一切买入信号", "action": "不买，已持有则评估是否离场"})
    exit_conditions.append({"condition": "🔴 安全评分降至 < 40分", "triggered": safety_score["safety_score"] < 40, "current": f"{safety_score['safety_score']}分", "rule": "危险区间 = 持币观望", "action": "远离，等安全评分回升"})

    return {
        "entry": {"ready": must_met, "ready_enhanced": all_met, "conditions": entry_conditions,
            "verdict": ("✅ 买入参考条件全部满足，可考虑入场" if all_met else ("⚠️ 必要条件满足但增强信号不足，可小仓试探" if must_met else "❌ 买入条件不满足，继续等待"))},
        "exit": {"any_triggered": any(c["triggered"] for c in exit_conditions), "conditions": exit_conditions},
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

    # ━━ Part 2: 2A 日度量价 ━━
    print()
    print("━" * 70)
    print("  📋 Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）")
    print("━" * 70)
    daily = report.get("daily", [])
    realtime = report.get("realtime", {})
    track = report.get("track", "B")

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
            header = f"  {'日期':<12s} {'收盘':>8s} {'涨跌':>7s} {'振幅':>6s} {'换手':>6s} {'量比':>6s} {'主力净流(万)':>13s} {'走势':>6s}"
        else:
            header = f"  {'日期':<12s} {'收盘':>8s} {'涨跌':>7s} {'振幅':>6s} {'换手':>6s} {'量比':>6s} {'量分位':>7s} {'价分位':>7s} {'走势':>6s}"
        sub_h = f"  {'─'*85}"

        print(header)
        print(sub_h)
        for d in daily[-20:]:
            date = d.get("date", ""); close = d.get("close", 0)
            chg = d.get("change_pct", 0); amp = d.get("amplitude", 0)
            vol = d.get("volume", 0)
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
            vp_m = "🔴" if vol_pct > 90 else ("🟠" if vol_pct > 70 else ("🔵" if vol_pct < 30 else "  "))
            pp_m = "🔴" if price_pct > 90 else ("🟠" if price_pct > 70 else ("🔵" if price_pct < 30 else "  "))

            if track == "A":
                main_net = d.get("main_net", 0)
                if main_net > 500: fm = f"🔴 +{main_net:.0f}万"
                elif main_net > 0: fm = f"🟢 +{main_net:.0f}万"
                elif main_net > -500: fm = f"🟢 {main_net:.0f}万"
                else: fm = f"🔴 {main_net:.0f}万"
                print(f"  {date:<12s} {close:>8.2f} {chg:>+6.2f}% {amp:>5.2f}% {turnover:>5.2f}% {vr}{vol_ratio:>5.1f}x {fm:>13s} {trend}")
            else:
                print(f"  {date:<12s} {close:>8.2f} {chg:>+6.2f}% {amp:>5.2f}% {turnover:>5.2f}% {vr}{vol_ratio:>5.1f}x {vp_m}{vol_pct:>5.0f}% {pp_m}{price_pct:>5.0f}% {trend}")

        print(sub_h)
        today = daily[-1] if daily else {}
        today_vol = today.get("volume", 0)
        today_vr = round(today_vol / avg_vol_20, 1) if avg_vol_20 > 0 else 0
        today_vp = round((today_vol - vol_min) / (vol_max - vol_min) * 100, 0) if vol_max > vol_min else 50
        today_pp = round((today.get("close", 0) - price_60l) / (price_60h - price_60l) * 100, 0) if price_60h > price_60l else 50

        print(f"  📊 今日量:{today_vol:,.0f}手 | 量比:{today_vr:.1f}x | "
              f"量分位:{today_vp:.0f}%(60日) | 价分位:{today_pp:.0f}%(60日)")
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

    # ━━ 2B: 资金流向 ━━
    print()
    print("  ━" * 55)
    print("    💰 2B: 资金流向详细")
    print("  ━" * 55)
    if daily:
        recent_5 = daily[-5:]; recent_10 = daily[-10:]
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
            if inst_5d < -500 and small_5d > 100: print(f"  ⚠️  机构卖+散户买 → 🔴 筹码从机构→散户(派发结构)")
            elif inst_5d > 500 and small_5d < -100: print(f"  ✅ 机构买+散户卖 → 🟢 筹码从散户→机构(吸筹结构)")
            elif abs(inst_5d) < 500 and abs(small_5d) < 500: print(f"  ➖ 机构散户均平淡 → 方向不明，等待信号")
            main_10d = sum(d.get("super_net", 0) + d.get("large_net", 0) for d in recent_10)
            tl = ("加速流入" if main_5d > main_10d * 0.7 else ("流出放缓" if main_5d > main_10d * 0.3 else "趋势一致"))
            print(f"\n  📈 资金趋势对比:")
            print(f"     近10日主力: {main_10d/1e4:+.2f}亿 | 近5日主力: {main_5d/1e4:+.2f}亿 | {tl}")
            print(f"\n  📅 近5日每日资金组成(万元):")
            print(f"  {'日期':<12s} {'主力净流':>10s} {'超大单(机构)':>12s} {'大单(游资)':>12s} {'中单':>10s} {'小单(散户)':>12s}")
            print(f"  {'─'*72}")
            for d in recent_5:
                print(f"  {d.get('date',''):<12s} {d.get('main_net',0):>8.0f}万 {d.get('super_net',0):>10.0f}万 {d.get('large_net',0):>10.0f}万 {d.get('mid_net',0):>8.0f}万 {d.get('small_net',0):>10.0f}万")
            ci = 0; co = 0
            for d in reversed(daily):
                mn = d.get("main_net", 0)
                if mn > 0:
                    if co == 0: ci += 1
                    else: break
                elif mn < 0:
                    if ci == 0: co += 1
                    else: break
                else: break
            print(f"\n  🔄 连续流入: {ci}日 | 连续流出: {co}日")
        else:
            concept_data = report.get("concept_flow", {})
            if concept_data and concept_data.get("available"):
                tf = concept_data.get("target_flow", {})
                print(f"  📊 概念板块资金流 (代理指标 — push2his不可用)")
                print(f"  板块: {concept_data.get('board_code','')} | 成分股{concept_data.get('stock_count',0)}只")
                print(f"  板块主力净流合计: {concept_data.get('total_main_net_yi',0):+.2f}亿")
                if tf:
                    myi = tf.get('main_net_yi', 0); rank = concept_data.get('target_rank', 0)
                    total = concept_data.get('target_rank_total', 0)
                    fi = "🔴" if myi < -1 else ("🟢" if myi > 1 else "➖")
                    ln = ("🔴 板块内主力流出最多" if myi < 0 and rank <= 3 else ("🟢 板块内主力流入龙头" if myi > 0 and rank <= 3 else ""))
                    print(f"  {fi} 目标个股: 主力{myi:+.2f}亿 | 板块排名 {rank}/{total} | {ln}")
                print(f"\n  📋 板块成分股资金流排名(主力净流):")
                print(f"  {'排名':<5s} {'代码':<8s} {'名称':<10s} {'涨跌':>8s} {'主力净流':>10s}")
                print(f"  {'─'*48}")
                ss = sorted(concept_data.get("stocks", []), key=lambda x: x['main_net_yi'], reverse=True)
                for i, s in enumerate(ss):
                    mk = " ★目标" if s['code'] == report['target'] else ""
                    print(f"  {i+1:<5d} {s['code']:<8s} {s['name']:<10s} {s['change_pct']:>+7.2f}% {s['main_net_yi']:>+8.2f}亿{mk}")
            else:
                print(f"  📊 概念板块资金流: 暂不可取")
                if concept_data:
                    print(f"     ({concept_data.get('reason', '')})")

    # ━━ 2C: 融资融券 ━━
    print()
    print("  ━" * 55)
    print("    🏦 2C: 融资融券明细")
    print("  ━" * 55)
    mgn = report.get("margin_data", {})
    if mgn and mgn.get("available"):
        print(f"  最新融资余额: {mgn.get('latest_balance_yi', 0):.2f}亿 | 趋势: {mgn.get('trend', '')}")
        print(f"  近5日融资净买卖: {mgn.get('net_flow_5d_yi', 0):+.2f}亿 | 近10日: {mgn.get('net_flow_10d_yi', 0):+.2f}亿")
        records = mgn.get('records', [])
        if records:
            print(f"\n  📅 近10日融资日度明细:")
            print(f"  {'日期':<12s} {'融资余额':>10s} {'买入额':>10s} {'偿还额':>10s} {'净买卖':>10s}")
            print(f"  {'─'*55}")
            for r in records[:10]:
                nm = "🔴" if r['net_yi'] > 1 else ("🟢" if r['net_yi'] < -1 else "  ")
                print(f"  {r['date']:<12s} {r.get('rzye_yi',0):>8.2f}亿 {r.get('rzmre_yi',0):>8.2f}亿 {r.get('rzche_yi',0):>8.2f}亿 {nm}{r.get('net_yi',0):>+8.2f}亿")
    else:
        print(f"  融资融券: 数据暂不可取")
        if mgn: print(f"     ({mgn.get('reason', '')})")

    # ━━ Part 3-7 ━━
    print()
    print("━" * 70)
    print("  ✅ Part 3: 安全信号检测（企稳证据）")
    print("━" * 70)
    for key, sig in report["safety_signals"].items():
        t = sig.get("triggered", False); ic = "🟢" if t else "⚪"
        print(f"  {ic} {sig.get('signal_name', key)}")
        print(f"     {sig.get('meaning', '')}")
        if t: print(f"     强度: {sig.get('strength', '')}")

    print()
    print("━" * 70)
    print("  🚨 Part 3b: 危险信号检测（风险排查）")
    print("━" * 70)
    ad = False
    for key, sig in report["danger_signals"].items():
        t = sig.get("triggered", False)
        if t:
            ad = True
            print(f"  🔴 {sig.get('signal_name', key)}")
            print(f"     危险等级: {sig.get('danger_level', '')}")
            print(f"     {sig.get('meaning', '')}")
            print(f"     → {sig.get('action', '')}")
    if not ad: print(f"  ✅ 未检测到高危信号")

    print()
    print("━" * 70)
    print("  📋 Part 4: 企稳确认清单 (需 ≥4/5)")
    print("━" * 70)
    lbl = {"no_new_low": "不再创新低", "narrow_range": "振幅 < 5%", "flow_normal": "流出/量能正常", "lows_rising": "最低价抬高", "above_ma5": "站上5日均线"}
    for k, v in lbl.items():
        ok = score["stabilization"]["checks"].get(k, False)
        print(f"  {'✅' if ok else '❌'} {v}")

    timing = report["timing"]
    print()
    print("━" * 70)
    print("  ⏰ Part 5: 买入时机参考条件")
    print("━" * 70)
    for cd in timing["entry"]["conditions"]:
        mt = cd["met"]; ic2 = "✅" if mt else "❌"
        print(f"  {ic2} [{cd['weight']}] {cd['condition']}"); print(f"     当前: {cd['current']}")
    print(f"\n  综合判断: {timing['entry']['verdict']}")

    print()
    print("━" * 70)
    print("  🚪 Part 6: 离场/风控参考")
    print("━" * 70)
    for cd in timing["exit"]["conditions"]:
        t2 = cd.get("triggered", False); ic3 = "🔴" if t2 else "  "
        print(f"  {ic3} {cd['condition']}")
        if t2: print(f"     规则: {cd.get('rule', '')}"); print(f"     建议: {cd.get('action', '')}")

    news = report.get("news", [])
    if news:
        print()
        print("━" * 70)
        print("  📰 Part 7: 近期关键消息")
        print("━" * 70)
        for n in news[:6]:
            print(f"  [{n.get('date', '')[:10]}] {n.get('title', '')[:80]}")
            if n.get('summary', '')[:80]: print(f"         {n.get('summary', '')[:100]}")

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


def _save_markdown(report: dict, path: str):
    """保存 Markdown 报告"""
    score = report["safety_score"]; summary = report["summary"]
    daily = report["daily"]; timing = report["timing"]
    track = report.get("track", "B"); realtime = report.get("realtime", {})

    lines = [
        f"# 🛡️ 买入安全区间研判报告", "",
        f"**标的**: {report['target_name']} ({report['target']}) | **类型**: 个股 | **信号轨**: {report.get('track_label', '')}",
        f"**生成时间**: {report['generated_at']} | **原则**: 可以少挣，必须少亏", "",
        f"## Part 1: 核心结论", "",
        f"| 指标 | 数值 |", f"|------|------|",
        f"| 当前价格 | {summary['price']:.2f} |",
        f"| 涨跌幅 | {summary.get('change', 0):+.2f} ({summary.get('change_pct', 0):+.2f}%) |",
        f"| 换手率 | {summary.get('turnover_pct', 0):.2f}% |",
        f"| PE(TTM) | {summary.get('pe_ttm', 0):.1f} |",
        f"| PB | {summary.get('pb', 0):.1f} |",
        f"| 总市值 | {summary.get('mcap_yi', 0):.1f}亿 |",
        f"| 1周涨跌 | {summary.get('change_1w', 0):+.1f}% |",
        f"| 1月涨跌 | {summary.get('change_1m', 0):+.1f}% |",
        f"| 安全评分 | **{score['safety_score']}/100** → {score['safety_level']} |",
        f"| 企稳状态 | {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} ({score['stabilization']['passed_count']}/5项) |",
        f"| 能否入场 | {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'} |",
    ]
    lines.extend(markdown_validation_summary(report.get("realtime", {}).get("_validation", {})))
    lines.extend(["", f"**判断依据**: {score['description']}", "", f"### 评分构成", ""])
    for detail, adj in score["adjustment_details"]:
        sign = "+" if adj > 0 else ""
        lines.append(f"- {sign}{adj:>+3d}  {detail}")

    # Part 2: 2A/2B/2C
    lines.extend(["", "---", "", "## Part 2: 近20日日度数据明细", "", "### 2A: 日度量价明细", ""])
    if daily:
        v20 = [d["volume"] for d in daily[-25:-5] if d.get("volume")]
        av20 = sum(v20) / len(v20) if v20 else 1
        alv = [d["volume"] for d in daily if d.get("volume")]; alp = [d["close"] for d in daily if d.get("close")]
        vmx = max(alv) if alv else 1; vmn = min(alv) if alv else 0
        ph = max(alp) if alp else 1; pl = min(alp) if alp else 0
        if track == "A":
            lines.append(f"| 日期 | 收盘 | 涨跌幅 | 振幅 | 换手率 | 量比 | 主力净流(万) | 走势 |")
            lines.append(f"|------|------|--------|------|--------|------|-------------|------|")
        else:
            lines.append(f"| 日期 | 收盘 | 涨跌幅 | 振幅 | 换手率 | 量比 | 价分位 | 走势 |")
            lines.append(f"|------|------|--------|------|--------|------|--------|------|")
        for d in daily[-20:]:
            date, close, chg, amp = d.get("date",""), d.get("close",0), d.get("change_pct",0), d.get("amplitude",0)
            vol = d.get("volume", 0)
            fs = realtime.get("float_mcap_yi",1)/realtime.get("price",1)*1e8 if realtime.get("price") else 5e8
            tn = round(vol*100/fs*100,2) if fs>0 else 0
            vr = round(vol/av20,2) if av20>0 else 0
            pp = round((close-pl)/(ph-pl)*100,0) if ph>pl else 50
            if chg>5: td="🔥大涨"
            elif chg>2: td="📈上涨"
            elif chg>-2: td="➖震荡"
            elif chg>-5: td="📉下跌"
            else: td="💧暴跌"
            if track=="A":
                mn = d.get("main_net",0); lines.append(f"| {date} | {close:.2f} | {chg:+.2f}% | {amp:.2f}% | {tn:.2f}% | {vr:.1f}x | {mn:+.0f} | {td} |")
            else:
                lines.append(f"| {date} | {close:.2f} | {chg:+.2f}% | {amp:.2f}% | {tn:.2f}% | {vr:.1f}x | {pp:.0f}% | {td} |")
        tm = daily[-1] if daily else {}
        tv = tm.get("volume",0); tvr = round(tv/av20,1) if av20>0 else 0
        tvp = round((tv-vmn)/(vmx-vmn)*100,0) if vmx>vmn else 50
        tpp = round((tm.get("close",0)-pl)/(ph-pl)*100,0) if ph>pl else 50
        lines.extend(["", f'> **今日量**: {tv:,.0f}手 | **量比**: {tvr:.1f}x | **量分位(60日)**: {tvp:.0f}% | **价分位(60日)**: {tpp:.0f}%',
            f'> **20日均量**: {av20:,.0f}手 | **60日最高价**: {ph:.2f} | **60日最低价**: {pl:.2f}'])

    # 2B
    lines.extend(["", "### 2B: 资金流向详细", ""])
    if daily:
        r5 = daily[-5:]; r10 = daily[-10:]
        if track == "A":
            i5 = sum(d.get("super_net",0) for d in r5); h5 = sum(d.get("large_net",0) for d in r5)
            m5 = sum(d.get("mid_net",0) for d in r5); s5 = sum(d.get("small_net",0) for d in r5); mn5 = i5+h5
            lines.extend(["#### 近5日资金组成", "",
                f"| 类型 | 净额(万元) | 净额(亿元) | 方向 |", f"|------|-----------|-----------|------|",
                f"| 超大单(机构) | {i5:+.0f} | {i5/1e4:+.2f} | {'流入' if i5>0 else '流出'} |",
                f"| 大单(游资) | {h5:+.0f} | {h5/1e4:+.2f} | |",
                f"| 中单 | {m5:+.0f} | {m5/1e4:+.2f} | |",
                f"| 小单(散户) | {s5:+.0f} | {s5/1e4:+.2f} | |",
                f"| **主力合计** | **{mn5:+.0f}** | **{mn5/1e4:+.2f}** | |", ""])
            if i5<-500 and s5>100: lines.append(f"⚠️ **筹码结构**: 机构卖+散户买 → 派发结构")
            elif i5>500 and s5<-100: lines.append(f"✅ **筹码结构**: 机构买+散户卖 → 吸筹结构")
            lines.append("")
            mn10 = sum(d.get("super_net",0)+d.get("large_net",0) for d in r10)
            tlm = ("加速流入" if mn5>mn10*0.7 else ("流出放缓" if mn5>mn10*0.3 else "趋势一致"))
            lines.append(f"**资金趋势**: 近10日主力 {mn10/1e4:+.2f}亿 | 近5日主力 {mn5/1e4:+.2f}亿 | {tlm}")
            lines.extend(["", "#### 近5日每日资金明细(万元)", "",
                f"| 日期 | 主力净流 | 超大单(机构) | 大单(游资) | 中单 | 小单(散户) |",
                f"|------|---------|------------|----------|------|----------|"])
            for d in r5:
                lines.append(f"| {d.get('date','')} | {d.get('main_net',0):+.0f} | {d.get('super_net',0):+.0f} | {d.get('large_net',0):+.0f} | {d.get('mid_net',0):+.0f} | {d.get('small_net',0):+.0f} |")
        else:
            cd2 = report.get("concept_flow", {})
            if cd2 and cd2.get("available"):
                lines.extend([f"#### 概念板块资金流 (代理指标)", "",
                    f"板块: {cd2.get('board_code','')} | 成分股: {cd2.get('stock_count',0)}只",
                    f"板块主力净流合计: {cd2.get('total_main_net_yi',0):+.2f}亿"])
                tf2 = cd2.get("target_flow", {})
                if tf2: lines.append(f"目标个股: 主力{tf2.get('main_net_yi',0):+.2f}亿 | 排名 {cd2.get('target_rank',0)}/{cd2.get('target_rank_total',0)}")
                lines.extend(["", f"| 排名 | 代码 | 名称 | 涨跌幅 | 主力净流(亿) |",
                    f"|------|------|------|--------|-------------|"])
                ss2 = sorted(cd2.get("stocks", []), key=lambda x: x['main_net_yi'], reverse=True)
                for i2, s2 in enumerate(ss2):
                    mk2 = " **←目标**" if s2['code']==report['target'] else ""
                    lines.append(f"| {i2+1} | {s2['code']} | {s2['name']} | {s2['change_pct']:+.1f}% | {s2['main_net_yi']:+.2f}{mk2} |")
        lines.append("")

    # 2C
    lines.extend(["### 2C: 融资融券明细", ""])
    mgn2 = report.get("margin_data", {})
    if mgn2 and mgn2.get("available"):
        lines.extend([
            f"**最新融资余额**: {mgn2.get('latest_balance_yi',0):.2f}亿 | **趋势**: {mgn2.get('trend','')}",
            f"**近5日净买卖**: {mgn2.get('net_flow_5d_yi',0):+.2f}亿 | **近10日净买卖**: {mgn2.get('net_flow_10d_yi',0):+.2f}亿", "",
            f"| 日期 | 融资余额(亿) | 买入额(亿) | 偿还额(亿) | 净买卖(亿) |",
            f"|------|------------|-----------|-----------|-----------|"])
        for r in mgn2.get('records', [])[:10]:
            lines.append(f"| {r.get('date','')} | {r.get('rzye_yi',0):.2f} | {r.get('rzmre_yi',0):.2f} | {r.get('rzche_yi',0):.2f} | {r.get('net_yi',0):+.2f} |")
    else:
        lines.append("融资融券: 数据暂不可取")
    lines.append("")

    # Part 3-7
    lines.extend([f"## Part 3: 安全信号检测", ""])
    for key, sig in report["safety_signals"].items():
        t = sig.get("triggered", False); ic = "🟢" if t else "⚪"
        lines.append(f"- {ic} **{sig.get('signal_name', key)}**: {sig.get('meaning', '')}")
    lines.extend(["", f"## Part 4: 危险信号检测", ""])
    ad_md = False
    for key, sig in report["danger_signals"].items():
        if sig.get("triggered"):
            ad_md = True
            lines.append(f"- 🔴 **{sig.get('signal_name', key)}** (危险等级: {sig.get('danger_level', '')})")
            lines.append(f"  - {sig.get('meaning', '')}"); lines.append(f"  - → {sig.get('action', '')}")
    if not ad_md: lines.append(f"✅ 未检测到高危信号")

    lines.extend(["", f"## Part 5: 企稳确认清单 (需 ≥4/5)", ""])
    labels_md = {"no_new_low": "不再创新低", "narrow_range": "振幅 < 5%", "flow_normal": "流出/量能正常", "lows_rising": "最低价抬高", "above_ma5": "站上5日均线"}
    for k, v in labels_md.items():
        ok = score["stabilization"]["checks"].get(k, False)
        lines.append(f"- {'✅' if ok else '❌'} {v}")

    lines.extend(["", f"## Part 6: 买入时机参考条件", ""])
    for cd in timing["entry"]["conditions"]:
        mt = cd["met"]; ic2 = "✅" if mt else "❌"
        lines.append(f"- {ic2} [{cd['weight']}] {cd['condition']} — 当前: {cd['current']}")
    lines.extend(["", f"**综合判断**: {timing['entry']['verdict']}", ""])

    lines.extend([f"## Part 7: 离场/风控参考", ""])
    for cd in timing["exit"]["conditions"]:
        t2 = cd.get("triggered", False); ic3 = "🔴" if t2 else "  "
        lines.append(f"- {ic3} {cd['condition']}")
        if t2: lines.append(f"  - 规则: {cd.get('rule', '')}"); lines.append(f"  - 建议: {cd.get('action', '')}")

    news2 = report.get("news", [])
    if news2:
        lines.extend(["", f"## Part 8: 近期关键消息", ""])
        for n in news2[:6]:
            lines.append(f"- [{n.get('date','')[:10]}] {n.get('title','')}")
            if n.get('summary',''): lines.append(f"  - {n.get('summary','')[:120]}")

    lines.extend(["", "---", "", "## ⚠️ 研究声明", "",
        "1. 安全评分基于可验证的价格/成交量/资金流/消息面规则",
        "2. 买入/卖出参考条件是可验证的信号框架，不是买卖指令",
        "3. 核心原则: 可以少挣，必须少亏 — 安全评分<60坚决不入场",
        "4. 亏损的数学是不对称的: 亏50%需涨100%回本",
        f"5. 信号轨: {report.get('track_label', '')}",
        "6. 所有分析基于公开数据，不构成投资建议"])

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    print("=" * 60)
    print(f"  fund-flow-predictor V1.4 — {NAME}({CODE})")
    print("=" * 60)

    # 1. 拉取K线 (腾讯, 不封IP)
    print("[1/6] 拉取腾讯日K线(qfq)...")
    daily = fetch_kline_tencent(CODE, days=60)
    print(f"  获取 {len(daily)} 个交易日")

    # 2. 拉取行情 (腾讯+新浪交叉验证)
    print("[2/6] 拉取实时行情(腾讯+新浪交叉验证)...")
    realtime = _fetch_realtime_with_validation_wrapper()
    print(f"  数据质量: {realtime.get('_validation', {}).get('quality', '未知')}")

    # 3. 拉取资金流 (push2his)
    print("[3/6] 拉取个股资金流(push2his)...")
    fund_flow = fetch_fund_flow(CODE)
    if fund_flow:
        merged = merge_fund_flow(daily, fund_flow)
        print(f"  合并 {merged} 日资金流数据")

    # 判断信号轨
    track = determine_track(daily)
    track_label = f"{track}轨({'资金流+量价' if track == 'A' else '量价+消息面'})"
    print(f"  信号轨: {track_label}")

    # 4. 新闻
    print("[4/6] 拉取新闻...")
    news = fetch_news(CODE)

    # 5. 行业资金流
    print("[5/6] 拉取行业板块资金流...")
    industry_flows = fetch_industry_flows()

    # 6. 概念板块+融资融券
    print("[6/6] 拉取辅助数据(概念板块+融资融券)...")
    concept_flow = fetch_concept_board_flow(CODE)
    margin_data = fetch_margin_data(CODE)
    if concept_flow.get("available"): print(f"  概念板块: {concept_flow.get('board_code')} ({concept_flow.get('stock_count')}只)")
    else: print(f"  概念板块: {concept_flow.get('reason', '不可取')}")
    if margin_data.get("available"): print(f"  融资融券: {margin_data.get('latest_balance_yi',0):.2f}亿, 趋势{margin_data.get('trend','')}")
    else: print(f"  融资融券: {margin_data.get('reason', '不可取')}")

    # 更新最后一天行情
    if daily and realtime:
        today_str = datetime.now().strftime("%Y-%m-%d")
        last = daily[-1]
        if last["date"] == today_str:
            last["close"] = realtime.get("price", last["close"])
            last["open"] = realtime.get("open", last["open"])
            last["high"] = realtime.get("high", last["high"])
            last["low"] = realtime.get("low", last["low"])
            last["volume"] = realtime.get("volume", last["volume"])
            if last["open"] > 0: last["change_pct"] = round((last["close"] - last["open"]) / last["open"] * 100, 2)
            if last["low"] > 0: last["amplitude"] = round((last["high"] - last["low"]) / last["low"] * 100, 2)

    # 信号检测
    print("\n[信号检测] ...")
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

    # 评分
    print("[评分] ...")
    safety_score = calc_safety_score(safety_signals, danger_signals, daily, track, margin_data, concept_flow)

    # 时机
    print("[时机] ...")
    timing = generate_timing(safety_score, daily)

    # 构建 report
    today_d = daily[-1] if daily else {}
    week_ago = daily[-6] if len(daily) >= 6 else daily[0]
    month_ago = daily[-22] if len(daily) >= 22 else daily[0]

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": CODE,
        "target_type": "stock",
        "target_name": realtime.get("name", NAME),
        "track": track,
        "track_label": track_label,
        "summary": {
            "price": realtime.get("price", today_d.get("close", 0)),
            "last_close": realtime.get("last_close", 0),
            "change": realtime.get("change_amt", 0),
            "change_pct": realtime.get("change_pct", 0),
            "open": realtime.get("open", 0),
            "high": realtime.get("high", 0),
            "low": realtime.get("low", 0),
            "turnover_pct": realtime.get("turnover_pct", 0),
            "pe_ttm": realtime.get("pe_ttm", 0),
            "pb": realtime.get("pb", 0),
            "mcap_yi": realtime.get("mcap_yi", 0),
            "float_mcap_yi": realtime.get("float_mcap_yi", 0),
            "change_1w": round((today_d.get("close", 0) - week_ago.get("close", 0)) / week_ago.get("close", 1) * 100, 1),
            "change_1m": round((today_d.get("close", 0) - month_ago.get("close", 0)) / month_ago.get("close", 1) * 100, 1),
        },
        "realtime": realtime,
        "daily": daily,
        "industry_flow": industry_flows,
        "concept_flow": concept_flow,
        "margin_data": margin_data,
        "safety_signals": safety_signals,
        "danger_signals": danger_signals,
        "safety_score": safety_score,
        "timing": timing,
        "news": news,
    }

    # 打印+保存
    _print_report(report)
    output_dir = f"src/资金预判/{datetime.now().strftime('%Y-%m-%d')}-{NAME}-安全评估"
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    _save_markdown(report, os.path.join(output_dir, "report.md"))
    print(f"\n  报告已保存: {output_dir}/")
    return report


# V1.6 交叉验证 wrapper
def _fetch_realtime_with_validation_wrapper():
    return fetch_realtime_with_validation(CODE)


if __name__ == "__main__":
    main()
