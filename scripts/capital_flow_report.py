#!/usr/bin/env python3
"""
A股资金流向全景扫描脚本 V1.1
覆盖: 概念板块资金流 + 行业板块资金流 + 个股资金流TOP10 + 龙虎榜 + 机构/游资分析
"""
import time
import random
import requests
import json
import os
import sys
from datetime import datetime, timedelta

# ============================================================
# 通用 helper（继承自 a-stock-data）
# ============================================================
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.5
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15, max_retries=3):
    """东财统一请求：自动节流 + Keep-Alive + 重试"""
    if headers is None:
        headers = {}
    headers.setdefault("Referer", "https://data.eastmoney.com/")

    last_err = None
    for attempt in range(max_retries):
        wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))
        try:
            resp = EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
            return resp
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ReadTimeout) as e:
            last_err = e
            if attempt < max_retries - 1:
                wait_s = (attempt + 1) * 3
                print(f"  ⚠️ 连接错误，{wait_s}s后重试({attempt+1}/{max_retries})...")
                time.sleep(wait_s)
                continue
            raise
        finally:
            _em_last_call[0] = time.time()
    raise last_err

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def eastmoney_datacenter(report_name, columns="ALL", filter_str="",
                          page_size=50, sort_columns="", sort_types="-1"):
    """东财数据中心统一查询"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []

PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

PERIOD_MAP = {
    "today": 0, "1w": 5, "2w": 10, "1m": 22, "2m": 44,
    "3m": 66, "4m": 88, "5m": 110, "6m": 125, "1y": 250,
}

# ============================================================
# Layer 1: 板块级资金流向
# ============================================================
def _safe_float(val, default=0.0):
    """安全转换为 float，处理 '-' 等非数值字符串"""
    if val is None or val == "-" or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def concept_sector_fund_flow(sort_by="f62", top_n=50):
    """概念板块资金流向排名"""
    params = {
        "pn": "1", "pz": str(min(top_n, 500)), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",
        "fields": "f2,f3,f12,f14,f62,f66,f72,f78,f84,f104,f105,f128",
        "st": sort_by,
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    r = em_get(PUSH2_CLIST, params=params, headers=headers, timeout=15)
    d = r.json()
    items = d.get("data", {}).get("diff", [])
    total = d.get("data", {}).get("total", 0)
    sectors = []
    for it in items:
        sectors.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": _safe_float(it.get("f62")),
            "super_large_net": _safe_float(it.get("f66")),
            "large_net": _safe_float(it.get("f72")),
            "mid_net": _safe_float(it.get("f78")),
            "small_net": _safe_float(it.get("f84")),
            "change_pct": _safe_float(it.get("f3")),
            "up_count": int(_safe_float(it.get("f104"))),
            "down_count": int(_safe_float(it.get("f105"))),
            "leader_stock": it.get("f128", ""),
        })
    # 二次排序确保（API 排序可能不稳定）
    sectors.sort(key=lambda x: x.get("main_net", 0), reverse=True)
    return {"total": total, "sectors": sectors}


def industry_sector_fund_flow(top_n=86):
    """行业板块资金流向"""
    params = {
        "pn": "1", "pz": str(top_n), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f12,f14,f62,f66,f72,f78,f84,f104,f105",
        "st": "f62",
    }
    r = em_get(PUSH2_CLIST, params=params,
               headers={"Referer": "https://data.eastmoney.com/"}, timeout=15)
    d = r.json()
    items = d.get("data", {}).get("diff", [])
    sectors = []
    for it in items:
        sectors.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": _safe_float(it.get("f62")),
            "super_large_net": _safe_float(it.get("f66")),
            "large_net": _safe_float(it.get("f72")),
            "mid_net": _safe_float(it.get("f78")),
            "small_net": _safe_float(it.get("f84")),
            "change_pct": _safe_float(it.get("f3")),
            "up_count": int(_safe_float(it.get("f104"))),
            "down_count": int(_safe_float(it.get("f105"))),
        })
    sectors.sort(key=lambda x: x["main_net"], reverse=True)
    return {"total": len(sectors), "sectors": sectors}


# ============================================================
# Layer 2: 板块内个股资金流向
# ============================================================
def sector_stock_fund_flow(bk_code, top_n=10):
    """概念板块内个股资金流向 TOP N"""
    params_in = {
        "pn": "1", "pz": str(top_n), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": f"b:{bk_code}+f:!50",
        "fields": "f2,f3,f4,f8,f10,f12,f14,f20,f21,f62,f66,f72",
        "st": "f62",
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    r_in = em_get(PUSH2_CLIST, params=params_in, headers=headers, timeout=15)
    d_in = r_in.json()
    total = d_in.get("data", {}).get("total", 0)
    inflow = _parse_stock_fund_flow(d_in)

    params_out = {**params_in, "st": "f62", "po": "1"}
    r_out = em_get(PUSH2_CLIST, params=params_out, headers=headers, timeout=15)
    d_out = r_out.json()
    outflow = _parse_stock_fund_flow(d_out)

    return {"total": total, "inflow_top10": inflow[:top_n], "outflow_top10": outflow[:top_n]}


def _parse_stock_fund_flow(d):
    items = d.get("data", {}).get("diff", []) or []
    stocks = []
    for it in items:
        stocks.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": _safe_float(it.get("f62")),
            "super_large_net": _safe_float(it.get("f66")),
            "large_net": _safe_float(it.get("f72")),
            "change_pct": _safe_float(it.get("f3")),
            "price": _safe_float(it.get("f2")),
            "turnover_pct": _safe_float(it.get("f8")),
            "volume_ratio": _safe_float(it.get("f10")),
            "mcap": _safe_float(it.get("f20")),
            "float_mcap": _safe_float(it.get("f21")),
        })
    return stocks


# ============================================================
# Layer 3: 龙虎榜
# ============================================================
def daily_dragon_tiger_scan(date=None, min_net_buy_wan=0):
    """全市场龙虎榜扫描"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{date}')(TRADE_DATE<='{date}')",
        page_size=500,
        sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    stocks = []
    for row in data:
        net_buy = _safe_float(row.get("BILLBOARD_NET_AMT")) / 10000
        if net_buy < min_net_buy_wan:
            continue
        stocks.append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "reason": row.get("EXPLANATION", ""),
            "close": _safe_float(row.get("CLOSE_PRICE")),
            "change_pct": round(_safe_float(row.get("CHANGE_RATE")), 2),
            "net_buy_wan": round(net_buy, 1),
            "buy_wan": round(_safe_float(row.get("BILLBOARD_BUY_AMT")) / 10000, 1),
            "sell_wan": round(_safe_float(row.get("BILLBOARD_SELL_AMT")) / 10000, 1),
            "turnover_pct": round(_safe_float(row.get("TURNOVERRATE")), 2),
        })
    return {"date": date, "total": len(stocks), "stocks": stocks}


def dragon_tiger_seat_analysis(code, lookback_days=30):
    """个股龙虎榜席位分析 —— 识别机构和游资动向"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    records = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start_date}')(TRADE_DATE<='{end_date}')(SECURITY_CODE='{code}')",
        page_size=50,
        sort_columns="TRADE_DATE", sort_types="-1",
    )

    institution = {"buy_total": 0, "sell_total": 0, "net_total": 0, "seats": []}
    hot_money = {"buy_total": 0, "sell_total": 0, "net_total": 0, "seats": []}

    for record in records[:5]:
        trade_date = str(record.get("TRADE_DATE", ""))[:10]
        for side, report_name in [("buy", "RPT_BILLBOARD_DAILYDETAILSBUY"),
                                   ("sell", "RPT_BILLBOARD_DAILYDETAILSSELL")]:
            detail = eastmoney_datacenter(
                report_name,
                filter_str=f"(TRADE_DATE='{trade_date}')(SECURITY_CODE='{code}')",
                page_size=20,
                sort_columns="BUY" if side == "buy" else "SELL",
                sort_types="-1",
            )
            for row in detail:
                seat_code = str(row.get("OPERATEDEPT_CODE", ""))
                seat_name = row.get("OPERATEDEPT_NAME", "")
                buy_amt = _safe_float(row.get("BUY")) / 10000
                sell_amt = _safe_float(row.get("SELL")) / 10000
                net_amt = _safe_float(row.get("NET")) / 10000

                seat_info = {
                    "name": seat_name,
                    "date": trade_date,
                    "buy_wan": round(buy_amt, 1),
                    "sell_wan": round(sell_amt, 1),
                    "net_wan": round(net_amt, 1),
                }

                if seat_code == "0":
                    institution["buy_total"] += buy_amt
                    institution["sell_total"] += sell_amt
                    institution["net_total"] += net_amt
                    institution["seats"].append(seat_info)
                else:
                    hot_money["buy_total"] += buy_amt
                    hot_money["sell_total"] += sell_amt
                    hot_money["net_total"] += net_amt
                    hot_money["seats"].append(seat_info)

    for cat in [institution, hot_money]:
        for k in ["buy_total", "sell_total", "net_total"]:
            cat[k] = round(cat[k], 1)
        cat["seats"] = _merge_seat_positions(cat["seats"])

    return {
        "code": code,
        "records_count": len(records),
        "institution": institution,
        "hot_money": hot_money,
    }


def _merge_seat_positions(seats):
    merged = {}
    for s in seats:
        key = s["name"]
        if key not in merged:
            merged[key] = {**s, "dates": [s["date"]]}
        else:
            merged[key]["buy_wan"] += s["buy_wan"]
            merged[key]["sell_wan"] += s["sell_wan"]
            merged[key]["net_wan"] += s["net_wan"]
            merged[key]["dates"].append(s["date"])
    result = list(merged.values())
    result.sort(key=lambda x: x["net_wan"], reverse=True)
    for s in result:
        s["buy_wan"] = round(s["buy_wan"], 1)
        s["sell_wan"] = round(s["sell_wan"], 1)
        s["net_wan"] = round(s["net_wan"], 1)
    return result


# ============================================================
# Layer 4: 综合报告生成
# ============================================================
def fmt_yi(val):
    """格式化金额为亿，保留2位小数"""
    v = _safe_float(val, 0.0)
    return f"{v/1e8:.2f}"

def fmt_wan(val):
    """格式化金额为万，保留0位小数"""
    v = _safe_float(val, 0.0)
    return f"{v/1e4:.0f}"


def generate_report():
    """生成完整资金流向全景报告"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    def w(s=""):
        lines.append(s)

    w(f"# A股资金流向全景报告")
    w(f"\n> 生成时间: {now_str} | 数据来源: 东方财富公开API")
    w(f"> 覆盖: 概念板块(494个) + 行业板块 + 龙虎榜 + 机构/游资分析")

    # ==================== 一、概念板块资金流 ====================
    w(f"\n## 一、概念板块资金流向 TOP 20")
    w(f"\n> 概念板块维度比行业板块更精细（494 vs 86），是资金流分析的主力维度。\n")
    print("[1/6] 拉取概念板块资金流...")
    concept_data = concept_sector_fund_flow(top_n=50)
    all_sectors = concept_data["sectors"]
    inflow_top20 = all_sectors[:20]
    outflow_top20 = sorted(all_sectors, key=lambda x: x["main_net"])[:20]

    # 全市场汇总
    total_main_net = sum(s["main_net"] for s in all_sectors)
    total_super_large = sum(s["super_large_net"] for s in all_sectors)
    total_large = sum(s["large_net"] for s in all_sectors)
    total_mid = sum(s["mid_net"] for s in all_sectors)
    total_small = sum(s["small_net"] for s in all_sectors)
    inflow_count = sum(1 for s in all_sectors if s["main_net"] > 0)
    outflow_count = sum(1 for s in all_sectors if s["main_net"] < 0)

    w(f"### 全市场概览")
    w(f"\n| 指标 | 数值 |")
    w(f"|------|------|")
    w(f"| 覆盖概念板块数 | {len(all_sectors)} |")
    w(f"| 主力净流入板块数 | {inflow_count} |")
    w(f"| 主力净流出板块数 | {outflow_count} |")
    w(f"| 全市场主力净流入 | {fmt_yi(total_main_net)}亿 |")
    w(f"| 超大单净流入(机构) | {fmt_yi(total_super_large)}亿 |")
    w(f"| 大单净流入(游资) | {fmt_yi(total_large)}亿 |")
    w(f"| 中单净流入 | {fmt_yi(total_mid)}亿 |")
    w(f"| 小单净流入(散户) | {fmt_yi(total_small)}亿 |")

    w(f"\n### 🔥 主力净流入 TOP 20")
    w(f"\n| 排名 | 板块名称 | 主力净流入(亿) | 超大单(亿) | 大单(亿) | 涨跌幅% | 涨/跌家数 | 领涨股 |")
    w(f"|------|---------|---------------|-----------|---------|---------|----------|--------|")
    for i, s in enumerate(inflow_top20):
        emoji = "🔥" if i < 3 else ("📈" if i < 10 else "  ")
        w(f"| {emoji} {i+1} | {s['name']} | **{fmt_yi(s['main_net'])}** | {fmt_yi(s['super_large_net'])} | {fmt_yi(s['large_net'])} | {s['change_pct']:+.2f}% | {s['up_count']}/{s['down_count']} | {s['leader_stock']} |")

    w(f"\n### ⚠️ 主力净流出 TOP 20")
    w(f"\n| 排名 | 板块名称 | 主力净流出(亿) | 超大单(亿) | 大单(亿) | 涨跌幅% | 涨/跌家数 |")
    w(f"|------|---------|---------------|-----------|---------|---------|----------|")
    for i, s in enumerate(outflow_top20):
        emoji = "⚠️" if i < 3 else "  "
        w(f"| {emoji} {i+1} | {s['name']} | **{fmt_yi(s['main_net'])}** | {fmt_yi(s['super_large_net'])} | {fmt_yi(s['large_net'])} | {s['change_pct']:+.2f}% | {s['up_count']}/{s['down_count']} |")

    # ==================== 二、行业板块资金流 ====================
    w(f"\n## 二、行业板块资金流向 TOP 20")
    w(f"\n> 行业板块（86个）粗粒度视角，与概念板块交叉验证。\n")
    print("[2/6] 拉取行业板块资金流...")
    industry_data = industry_sector_fund_flow()
    ind_sectors = industry_data["sectors"]
    ind_inflow = ind_sectors[:20]
    ind_outflow = sorted(ind_sectors, key=lambda x: x["main_net"])[:20]

    w(f"### 🔥 行业板块主力净流入 TOP 20")
    w(f"\n| 排名 | 行业名称 | 主力净流入(亿) | 超大单(亿) | 大单(亿) | 涨跌幅% |")
    w(f"|------|---------|---------------|-----------|---------|---------|")
    for i, s in enumerate(ind_inflow):
        emoji = "🔥" if i < 3 else "  "
        w(f"| {emoji} {i+1} | {s['name']} | **{fmt_yi(s['main_net'])}** | {fmt_yi(s['super_large_net'])} | {fmt_yi(s['large_net'])} | {s['change_pct']:+.2f}% |")

    w(f"\n### ⚠️ 行业板块主力净流出 TOP 20")
    w(f"\n| 排名 | 行业名称 | 主力净流出(亿) | 涨跌幅% |")
    w(f"|------|---------|---------------|---------|")
    for i, s in enumerate(ind_outflow):
        emoji = "⚠️" if i < 3 else "  "
        w(f"| {emoji} {i+1} | {s['name']} | **{fmt_yi(s['main_net'])}** | {s['change_pct']:+.2f}% |")

    # ==================== 三、重点板块个股明细 ====================
    w(f"\n## 三、重点流入板块 — 个股资金流 TOP 10")
    print("[3/6] 分析重点板块个股资金流...")
    top3_sectors = inflow_top20[:3]
    for sec_idx, sec in enumerate(top3_sectors):
        print(f"  [{sec_idx+1}/3] {sec['name']}({sec['code']})...")
        try:
            detail = sector_stock_fund_flow(sec["code"], top_n=10)
            w(f"\n### {sec_idx+1}. {sec['name']}（{sec['code']}）")
            w(f"\n> 板块主力净流入: **{fmt_yi(sec['main_net'])}亿** | 涨跌: {sec['change_pct']:+.2f}% | 涨{sec['up_count']}跌{sec['down_count']} | 领涨: {sec['leader_stock']}")
            w(f"\n#### 主力净流入 TOP 10")
            w(f"\n| 排名 | 代码 | 名称 | 主力净流入(万) | 超大单(万) | 涨跌幅% | 换手率% | 量比 |")
            w(f"|------|------|------|---------------|-----------|---------|---------|------|")
            for i, s in enumerate(detail.get("inflow_top10", [])):
                w(f"| {i+1} | {s['code']} | {s['name']} | **{fmt_wan(s['main_net'])}** | {fmt_wan(s['super_large_net'])} | {s['change_pct']:+.2f}% | {s['turnover_pct']:.2f}% | {s['volume_ratio']:.2f} |")

            w(f"\n#### 主力净流出 TOP 5")
            w(f"\n| 排名 | 代码 | 名称 | 主力净流出(万) | 涨跌幅% |")
            w(f"|------|------|------|---------------|---------|")
            for i, s in enumerate(detail.get("outflow_top10", [])[:5]):
                w(f"| {i+1} | {s['code']} | {s['name']} | **{fmt_wan(s['main_net'])}** | {s['change_pct']:+.2f}% |")
        except Exception as e:
            w(f"\n> ⚠️ 获取失败: {e}")

    # ==================== 四、龙虎榜扫描 ====================
    w(f"\n## 四、全市场龙虎榜扫描")
    print("[4/6] 拉取全市场龙虎榜...")
    dt_data = daily_dragon_tiger_scan(min_net_buy_wan=0)
    w(f"\n> 📅 {dt_data['date']} | 共 **{dt_data['total']}** 只个股上榜\n")

    if dt_data["stocks"]:
        w(f"### 龙虎榜净买入 TOP 20")
        w(f"\n| 排名 | 代码 | 名称 | 净买入(万) | 买入(万) | 卖出(万) | 涨跌幅% | 换手% | 上榜原因 |")
        w(f"|------|------|------|-----------|---------|---------|---------|-------|---------|")
        for i, s in enumerate(dt_data["stocks"][:20]):
            w(f"| {i+1} | {s['code']} | {s['name']} | **{s['net_buy_wan']:.0f}** | {s['buy_wan']:.0f} | {s['sell_wan']:.0f} | {s['change_pct']:+.2f}% | {s['turnover_pct']:.2f}% | {s['reason'][:25]} |")
    else:
        w(f"> 今日暂无龙虎榜数据")

    # ==================== 五、重点个股机构/游资分析 ====================
    w(f"\n## 五、重点个股 — 机构 vs 游资 席位分析")
    print("[5/6] 分析重点个股席位...")
    top_dt_stocks = dt_data["stocks"][:5] if dt_data["stocks"] else []
    for sec_idx, stock in enumerate(top_dt_stocks):
        print(f"  [{sec_idx+1}/{len(top_dt_stocks)}] {stock['name']}({stock['code']})...")
        try:
            analysis = dragon_tiger_seat_analysis(stock["code"], lookback_days=30)
            w(f"\n### {stock['code']} {stock['name']}")
            w(f"\n> 近30日上榜 **{analysis['records_count']}** 次 | 今日净买: {stock['net_buy_wan']:.0f}万 | 涨跌: {stock['change_pct']:+.2f}%")
            w(f"\n| 资金类型 | 累计买入(万) | 累计卖出(万) | 净持仓(万) | 解读 |")
            w(f"|---------|------------|------------|-----------|------|")
            inst = analysis["institution"]
            hm = analysis["hot_money"]
            inst_verdict = "机构看多" if inst["net_total"] > 0 else "机构减仓"
            hm_verdict = "游资做多" if hm["net_total"] > 0 else "游资出逃"
            w(f"| 🔴 机构 | {inst['buy_total']:.0f} | {inst['sell_total']:.0f} | **{inst['net_total']:.0f}** | {inst_verdict} |")
            w(f"| 🟡 游资 | {hm['buy_total']:.0f} | {hm['sell_total']:.0f} | **{hm['net_total']:.0f}** | {hm_verdict} |")

            if inst["seats"]:
                w(f"\n**机构席位 TOP 3:**")
                for s in inst["seats"][:3]:
                    w(f"- {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")
            if hm["seats"]:
                w(f"\n**游资席位 TOP 3:**")
                for s in hm["seats"][:3]:
                    w(f"- {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")
        except Exception as e:
            w(f"\n> ⚠️ 分析失败: {e}")

    # ==================== 六、资金流向综合研判 ====================
    w(f"\n## 六、资金流向综合研判")
    print("[6/6] 生成综合研判...")
    w(f"\n### 核心发现")
    w(f"\n1. **全市场资金面**: 全市场 {inflow_count}/{outflow_count} 个概念板块获主力净流入，整体主力净流向 **{fmt_yi(total_main_net)}亿**，市场资金面偏{'强' if total_main_net > 0 else '弱'}。")
    w(f"2. **机构 vs 散户**: 超大单(机构)={fmt_yi(total_super_large)}亿 vs 小单(散户)={fmt_yi(total_small)}亿，{'机构主导买入，散户流出→筹码集中，偏多' if total_super_large > 0 and total_small < 0 else '机构与散户方向一致' if (total_super_large > 0) == (total_small > 0) else '机构流出、散户接盘→需警惕'}。")

    # 前5流入概念总结
    top5_names = [s['name'] for s in inflow_top20[:5]]
    w(f"3. **资金主攻方向**: {', '.join(top5_names)}——为今日资金集中流入的概念板块。")
    top5_out_names = [s['name'] for s in outflow_top20[:5]]
    w(f"4. **资金撤离方向**: {', '.join(top5_out_names)}——为今日资金集中流出的概念板块。")

    # 风险提示
    w(f"\n### ⚠️ 风险提示")
    w(f"\n- 以上数据基于东方财富公开API，数据延迟通常3-5秒")
    w(f"- 龙虎榜席位仅覆盖触发涨跌停/振幅异常/换手异常的交易日，非日常全覆盖")
    w(f"- \"游资\"和\"机构\"的区分基于龙虎榜席位代码，可能不完全准确")
    w(f"- **所有数据仅供参考，不构成投资建议**")

    w(f"\n---\n*报告由 capital-flow-tracker V1.1 自动生成*")

    return "\n".join(lines)


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "src", "资金流向", f"{today_str}-资金流向全景扫描")
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("  A股资金流向全景扫描 V1.1")
    print(f"  日期: {today_str}")
    print("=" * 60)

    report = generate_report()

    # 保存报告
    report_path = os.path.join(output_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n✅ 报告已保存: {report_path}")

    # 同时输出到控制台
    print("\n" + report)
