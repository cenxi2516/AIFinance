#!/usr/bin/env python3
"""
A股近3日资金流向全景扫描
使用 capital-flow-tracker skill 的函数，分析概念板块+行业板块+龙虎榜
"""

import time, random, requests, json
from datetime import datetime, timedelta

# ============================================================
# 通用 helper
# ============================================================
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_MIN_INTERVAL = 2.0  # 增加到2秒，push2接口更敏感
_em_last_call = [0.0]

def _create_session():
    """每次请求创建新 session，避免 Keep-Alive 被服务端断开"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "close",  # 不保持长连接，减少被断概率
    })
    return s

def em_get(url, params=None, headers=None, timeout=20, max_retries=3):
    """东财统一请求：自动节流 + 重试 + 每次新建session"""
    merged_headers = {
        "User-Agent": UA,
        "Referer": "https://data.eastmoney.com/",
    }
    if headers:
        merged_headers.update(headers)

    for attempt in range(max_retries):
        wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.3, 1.0))

        session = _create_session()
        try:
            resp = session.get(url, params=params, headers=merged_headers, timeout=timeout)
            _em_last_call[0] = time.time()
            return resp
        except Exception as e:
            _em_last_call[0] = time.time()
            session.close()
            if attempt < max_retries - 1:
                backoff = (attempt + 1) * 3 + random.uniform(0, 2)
                print(f"    ⚠️ 请求失败({type(e).__name__})，{backoff:.1f}秒后重试({attempt+2}/{max_retries})...")
                time.sleep(backoff)
            else:
                raise

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

# ============================================================
# Layer 1: 板块级资金流向
# ============================================================

def concept_sector_fund_flow(sort_by: str = "f62", top_n: int = 50) -> dict:
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
            "main_net": it.get("f62") or 0,
            "super_large_net": it.get("f66") or 0,
            "large_net": it.get("f72") or 0,
            "mid_net": it.get("f78") or 0,
            "small_net": it.get("f84") or 0,
            "change_pct": it.get("f3", 0),
            "up_count": it.get("f104", 0),
            "down_count": it.get("f105", 0),
            "leader_stock": it.get("f128", ""),
        })
    return {"total": total, "sectors": sectors}


def industry_sector_fund_flow(top_n: int = 86) -> dict:
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
            "main_net": it.get("f62") or 0,
            "super_large_net": it.get("f66") or 0,
            "large_net": it.get("f72") or 0,
            "mid_net": it.get("f78") or 0,
            "small_net": it.get("f84") or 0,
            "change_pct": it.get("f3", 0),
        })
    return {"total": len(sectors), "sectors": sectors}


def sector_stock_fund_flow(bk_code: str, top_n: int = 10) -> dict:
    """指定概念板块内个股资金流向排名"""
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

    return {
        "total": total,
        "inflow_top10": inflow[:top_n],
        "outflow_top10": outflow[:top_n],
    }


def _parse_stock_fund_flow(d: dict) -> list[dict]:
    """解析 push2 clist 返回的个股资金流数据"""
    items = d.get("data", {}).get("diff", []) or []
    stocks = []
    for it in items:
        stocks.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": it.get("f62") or 0,
            "super_large_net": it.get("f66") or 0,
            "large_net": it.get("f72") or 0,
            "change_pct": it.get("f3", 0),
            "price": it.get("f2", 0),
            "turnover_pct": it.get("f8", 0),
            "volume_ratio": it.get("f10", 0),
            "mcap": it.get("f20") or 0,
            "float_mcap": it.get("f21") or 0,
        })
    return stocks

# ============================================================
# Layer 2: 龙虎榜扫描
# ============================================================

def daily_dragon_tiger_scan(date: str = None, min_net_buy_wan: float = 0) -> dict:
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
        net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
        if net_buy < min_net_buy_wan:
            continue
        stocks.append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "reason": row.get("EXPLANATION", ""),
            "close": row.get("CLOSE_PRICE") or 0,
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
            "net_buy_wan": round(net_buy, 1),
            "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
            "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
        })
    return {"date": date, "total": len(stocks), "stocks": stocks}

# ============================================================
# Layer 3: 综合报告
# ============================================================

def generate_report():
    """生成近3日资金流向全景报告"""
    lines = []
    now = datetime.now()
    lines.append("=" * 80)
    lines.append(f"  A股近3日资金流向全景报告")
    lines.append(f"  生成时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 80)

    # ─── 1. 概念板块资金流 TOP 20 ───
    print("[1/5] 拉取概念板块资金流向...")
    lines.append(f"\n{'─' * 60}")
    lines.append("  一、概念板块主力净流入 TOP 20（今日实时）")
    lines.append(f"{'─' * 60}")
    concept_data = concept_sector_fund_flow(top_n=50)
    inflow = concept_data["sectors"][:20]
    outflow = sorted(concept_data["sectors"], key=lambda x: x["main_net"])[:20]

    lines.append(f"\n  【🔥 主力净流入 TOP 20】")
    lines.append(f"  {'排名':<4} {'板块名称':<12} {'主力净流入(亿)':<14} {'超大单(亿)':<12} {'大单(亿)':<10} {'涨跌幅%':<8} {'涨跌比'}")
    lines.append(f"  {'─' * 70}")
    for i, s in enumerate(inflow):
        lines.append(f"  {i+1:<4} {s['name']:<12} {s['main_net']/1e8:>10.2f}     "
                     f"{s['super_large_net']/1e8:>8.2f}   {s['large_net']/1e8:>7.2f}  "
                     f"{s['change_pct']:>+7.2f}  {s['up_count']}/{s['down_count']}")

    lines.append(f"\n  【📉 主力净流出 TOP 20】")
    lines.append(f"  {'排名':<4} {'板块名称':<12} {'主力净流出(亿)':<14} {'超大单(亿)':<12} {'涨跌幅%':<8} {'涨跌比'}")
    lines.append(f"  {'─' * 62}")
    for i, s in enumerate(outflow):
        lines.append(f"  {i+1:<4} {s['name']:<12} {s['main_net']/1e8:>10.2f}     "
                     f"{s['super_large_net']/1e8:>8.2f}   {s['change_pct']:>+7.2f}  "
                     f"{s['up_count']}/{s['down_count']}")

    # ─── 2. 行业板块资金流 ───
    print("[2/5] 拉取行业板块资金流向...")
    lines.append(f"\n{'─' * 60}")
    lines.append("  二、行业板块主力净流入排名（全部 86 个行业）")
    lines.append(f"{'─' * 60}")
    industry_data = industry_sector_fund_flow()
    ind_inflow = sorted(industry_data["sectors"], key=lambda x: x["main_net"], reverse=True)[:15]
    ind_outflow = sorted(industry_data["sectors"], key=lambda x: x["main_net"])[:15]

    lines.append(f"\n  【行业主力净流入 TOP 15】")
    lines.append(f"  {'排名':<4} {'行业名称':<12} {'主力净流入(亿)':<14} {'超大单(亿)':<12} {'大单(亿)':<10} {'涨跌幅%':<8}")
    lines.append(f"  {'─' * 60}")
    for i, s in enumerate(ind_inflow):
        lines.append(f"  {i+1:<4} {s['name']:<12} {s['main_net']/1e8:>10.2f}     "
                     f"{s['super_large_net']/1e8:>8.2f}   {s['large_net']/1e8:>7.2f}  "
                     f"{s['change_pct']:>+7.2f}")

    lines.append(f"\n  【行业主力净流出 TOP 15】")
    lines.append(f"  {'排名':<4} {'行业名称':<12} {'主力净流出(亿)':<14} {'涨跌幅%':<8}")
    lines.append(f"  {'─' * 40}")
    for i, s in enumerate(ind_outflow):
        lines.append(f"  {i+1:<4} {s['name']:<12} {s['main_net']/1e8:>10.2f}     {s['change_pct']:>+7.2f}")

    # ─── 3. 重点板块个股资金流 ───
    print("[3/5] 拉取重点板块个股资金流...")
    lines.append(f"\n{'─' * 60}")
    lines.append("  三、重点概念板块个股资金流 TOP 10")
    lines.append(f"{'─' * 60}")

    # 取前5个流入板块和前3个流出板块做个股分析
    top_inflow_sectors = inflow[:5]
    top_outflow_sectors = outflow[:3]

    for sec in top_inflow_sectors:
        try:
            detail = sector_stock_fund_flow(sec["code"], top_n=10)
        except Exception as e:
            lines.append(f"  ⚠️ {sec['name']}({sec['code']})个股数据获取失败: {e}")
            continue

        lines.append(f"\n  【{sec['name']} — 共{detail['total']}只个股】")
        lines.append(f"  板块主力净流入: {sec['main_net']/1e8:.2f}亿 | 涨跌: {sec['change_pct']:+.2f}%")
        lines.append(f"  {'代码':<8} {'名称':<10} {'主力净流入(万)':<14} {'涨跌幅%':<8} {'换手率%':<8} {'量比':<6}")
        lines.append(f"  {'─' * 56}")
        for s in detail.get("inflow_top10", [])[:10]:
            lines.append(f"  {s['code']:<8} {s['name']:<10} {s['main_net']/1e4:>12.0f}  "
                         f"{s['change_pct']:>+7.2f}  {s['turnover_pct']:>7.2f}  {s['volume_ratio']:>5.2f}")
        # 流出TOP5
        if detail.get("outflow_top10"):
            lines.append(f"  主力净流出 TOP5:")
            for s in detail["outflow_top10"][:5]:
                lines.append(f"    {s['code']} {s['name']}: {s['main_net']/1e4:.0f}万")

    # 流出板块个股
    for sec in top_outflow_sectors:
        try:
            detail = sector_stock_fund_flow(sec["code"], top_n=10)
        except Exception:
            continue

        lines.append(f"\n  【⚠️ {sec['name']} — 共{detail['total']}只个股（主力净流出板块）】")
        lines.append(f"  板块主力净流出: {sec['main_net']/1e8:.2f}亿 | 涨跌: {sec['change_pct']:+.2f}%")
        lines.append(f"  主力净流出最大个股 TOP5:")
        for s in detail.get("outflow_top10", [])[:5]:
            lines.append(f"    {s['code']} {s['name']}: {s['main_net']/1e4:.0f}万 涨跌{s['change_pct']:+.2f}%")

    # ─── 4. 近3日龙虎榜 ───
    print("[4/5] 拉取龙虎榜数据（近3日）...")
    lines.append(f"\n{'─' * 60}")
    lines.append("  四、近3日全市场龙虎榜扫描")
    lines.append(f"{'─' * 60}")

    for day_offset in [2, 1, 0]:
        date = (now - timedelta(days=day_offset)).strftime("%Y-%m-%d")
        try:
            dt = daily_dragon_tiger_scan(date=date, min_net_buy_wan=3000)
        except Exception as e:
            lines.append(f"  ⚠️ {date} 龙虎榜数据获取失败: {e}")
            continue

        lines.append(f"\n  【{date}】上榜 {dt['total']} 条（筛选净买入≥3000万）")
        if dt["stocks"]:
            lines.append(f"  {'代码':<8} {'名称':<10} {'净买入(万)':<12} {'买入(万)':<12} {'卖出(万)':<12} {'涨跌幅%':<8} {'上榜原因'}")
            lines.append(f"  {'─' * 80}")
            for s in dt["stocks"][:15]:
                lines.append(f"  {s['code']:<8} {s['name']:<10} {s['net_buy_wan']:>10.0f}  "
                             f"{s['buy_wan']:>10.0f}  {s['sell_wan']:>10.0f}  "
                             f"{s['change_pct']:>+7.2f}  {s['reason'][:35]}")
        else:
            lines.append(f"  （净买入≥3000万的标的为0，或该日为非交易日）")

    # ─── 5. 关键板块资金对比表 ───
    print("[5/5] 生成板块资金对比表...")
    lines.append(f"\n{'─' * 60}")
    lines.append("  五、关键板块资金流向一览（近1月 vs 近3月 多周期对比）")
    lines.append(f"{'─' * 60}")
    lines.append(f"\n  注：以下为今日单日数据，多周期历史数据需逐板块逐个股权重聚合。")
    lines.append(f"  建议关注：")
    lines.append(f"  - 持续流入板块：观察主力是否连续3日以上净流入")
    lines.append(f"  - 资金转向板块：前几日流出今突然流入 → 可能拐点")
    lines.append(f"  - 资金出逃板块：前几日流入今突然流出 → 可能短期见顶")

    # 总结
    lines.append(f"\n{'─' * 60}")
    lines.append("  六、核心发现总结")
    lines.append(f"{'─' * 60}")

    # 三方资金分析
    total_inflow_inst = sum(s["super_large_net"] for s in concept_data["sectors"]) / 1e8
    total_inflow_hm = sum(s["large_net"] for s in concept_data["sectors"]) / 1e8
    total_inflow_mid = sum(s["mid_net"] for s in concept_data["sectors"]) / 1e8
    total_inflow_small = sum(s["small_net"] for s in concept_data["sectors"]) / 1e8

    lines.append(f"\n  全市场概念板块资金汇总：")
    lines.append(f"  - 机构(超大单): {total_inflow_inst:+.2f}亿")
    lines.append(f"  - 游资(大单):   {total_inflow_hm:+.2f}亿")
    lines.append(f"  - 中单散户:     {total_inflow_mid:+.2f}亿")
    lines.append(f"  - 小单散户:     {total_inflow_small:+.2f}亿")

    # 判断主力方向
    main_sum = total_inflow_inst + total_inflow_hm
    retail_sum = total_inflow_mid + total_inflow_small
    if main_sum > 0 and retail_sum < 0:
        lines.append(f"  📊 资金面信号：主力净流入({main_sum:+.2f}亿)，散户净流出({retail_sum:+.2f}亿)")
        lines.append(f"     → 主力吸筹，筹码从散户向机构转移")
    elif main_sum < 0 and retail_sum > 0:
        lines.append(f"  ⚠️ 资金面信号：主力净流出({main_sum:+.2f}亿)，散户净流入({retail_sum:+.2f}亿)")
        lines.append(f"     → 主力派发，筹码从机构向散户转移")
    else:
        lines.append(f"  ➖ 资金面信号：主力({main_sum:+.2f}亿)与散户({retail_sum:+.2f}亿)方向一致")

    lines.append(f"\n{'=' * 80}")
    lines.append("  ⚠️ 研究声明:")
    lines.append("  1. 以上数据基于东方财富公开API，数据延迟3-5秒")
    lines.append("  2. 资金流向数据为净流向，不区分买卖方向")
    lines.append("  3. '机构/游资/散户'基于订单大小分类，不完全等同实际身份")
    lines.append("  4. 所有数据仅供参考，不构成投资建议")
    lines.append(f"{'=' * 80}")

    return "\n".join(lines)

# ============================================================
# 执行
# ============================================================
if __name__ == "__main__":
    start = time.time()
    print("开始生成A股近3日资金流向全景报告...\n")
    report = generate_report()
    print(report)

    # 保存
    output_path = "/Users/lishunxiang/Cenxi/learn/Finance/src/资金流向/2026-07-03-资金流向扫描/capital_flow_report.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    elapsed = time.time() - start
    print(f"\n⏱ 总耗时: {elapsed:.0f}秒")
    print(f"报告已保存至: {output_path}")
