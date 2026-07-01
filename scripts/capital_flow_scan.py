#!/usr/bin/env python3
"""
A股资金流向全景扫描脚本 V2.0
数据来源: 东财 data.eastmoney.com 官方 API (非 push2, 不封IP)
用法: python3 scripts/capital_flow_scan.py
"""
import requests, json, os, time, random, re
from datetime import datetime, timedelta

# ============================================================
# 基础工具
# ============================================================
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})
MIN_INTERVAL = 1.0
_last_call = [0.0]

def api_get(url, params=None, timeout=15):
    """统一请求：自动节流"""
    wait = MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.3))
    try:
        return SESSION.get(url, params=params, timeout=timeout,
                          headers={"Referer": "https://data.eastmoney.com/"})
    finally:
        _last_call[0] = time.time()

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
BKZJ_URL = "https://data.eastmoney.com/dataapi/bkzj/getbkzj"

# ============================================================
# Layer 1: 板块级资金流向
# ============================================================

def concept_sector_fund_flow():
    """概念板块资金流向（494个概念），返回按主力净流入降序排列"""
    r = api_get(BKZJ_URL, params={"code": "m:90+t:3", "key": "f62"}, timeout=20)
    d = r.json()
    if d.get("rc") != 0:
        raise Exception(f"API error: rc={d.get('rc')}")
    diff = d["data"]["diff"]
    sectors = []
    for it in diff:
        sectors.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": it.get("f62") or 0,  # 主力净流入(元)
        })
    return {"total": d["data"]["total"], "sectors": sectors}


def industry_sector_fund_flow():
    """行业板块资金流向（~86个行业）"""
    r = api_get(BKZJ_URL, params={"code": "m:90+t:2", "key": "f62"}, timeout=20)
    d = r.json()
    if d.get("rc") != 0:
        raise Exception(f"API error: rc={d.get('rc')}")
    diff = d["data"]["diff"]
    sectors = []
    for it in diff:
        sectors.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": it.get("f62") or 0,
        })
    return {"total": d["data"]["total"], "sectors": sectors}


def get_sector_change_pct(bk_codes: list[str]) -> dict:
    """批量获取概念板块涨跌幅（key=f3）"""
    # 一次拉取全部概念板块的涨跌幅，再过滤
    r = api_get(BKZJ_URL, params={"code": "m:90+t:3", "key": "f3"}, timeout=20)
    d = r.json()
    if d.get("rc") != 0:
        return {}
    result = {}
    for it in d["data"]["diff"]:
        code = it.get("f12", "")
        if code in bk_codes:
            result[code] = it.get("f3", 0)
    return result


def get_sector_super_large(bk_codes: list[str]) -> dict:
    """批量获取概念板块超大单净流入（key=f66）"""
    r = api_get(BKZJ_URL, params={"code": "m:90+t:3", "key": "f66"}, timeout=20)
    d = r.json()
    if d.get("rc") != 0:
        return {}
    result = {}
    for it in d["data"]["diff"]:
        code = it.get("f12", "")
        if code in bk_codes:
            result[code] = it.get("f66", 0)
    return result


# ============================================================
# Layer 2: 板块内个股资金流
# ============================================================

def sector_stock_fund_flow(bk_code: str) -> dict:
    """指定概念板块内个股资金流向（全部个股）"""
    r = api_get(BKZJ_URL, params={
        "code": f"b:{bk_code}+f:!50",  # 排除ST
        "key": "f62",
    }, timeout=20)
    d = r.json()
    if d.get("rc") != 0:
        return {"total": 0, "stocks": []}
    diff = d["data"]["diff"]
    stocks = []
    for it in diff:
        stocks.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": it.get("f62") or 0,
        })
    # 按主力净流入降序
    stocks.sort(key=lambda x: x["main_net"], reverse=True)
    return {"total": d["data"]["total"], "stocks": stocks}


# ============================================================
# Layer 3: 龙虎榜
# ============================================================

def datacenter_get(report_name, filter_str="", page_size=50,
                    sort_columns="", sort_types="-1"):
    """东财数据中心查询"""
    params = {
        "reportName": report_name, "columns": "ALL",
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = api_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


def daily_dragon_tiger_scan(date=None, min_net_buy_wan=0):
    """全市场龙虎榜扫描"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    data = datacenter_get(
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


def dragon_tiger_seat_analysis(code, lookback_days=30):
    """个股龙虎榜机构/游资席位分析"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    records = datacenter_get(
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
            detail = datacenter_get(
                report_name,
                filter_str=f"(TRADE_DATE='{trade_date}')(SECURITY_CODE='{code}')",
                page_size=20,
                sort_columns="BUY" if side == "buy" else "SELL",
                sort_types="-1",
            )
            for row in detail:
                seat_code = str(row.get("OPERATEDEPT_CODE", ""))
                seat_name = row.get("OPERATEDEPT_NAME", "")
                buy_amt = (row.get("BUY") or 0) / 10000
                sell_amt = (row.get("SELL") or 0) / 10000
                net_amt = (row.get("NET") or 0) / 10000

                seat_info = {
                    "name": seat_name, "date": trade_date,
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
        cat["seats"] = _merge_seats(cat["seats"])

    return {
        "code": code, "records_count": len(records),
        "institution": institution, "hot_money": hot_money,
    }


def _merge_seats(seats):
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
# 综合报告
# ============================================================

def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    today_str = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'=' * 80}")
    print(f"  A股资金流向全景扫描")
    print(f"  生成时间: {now_str}")
    print(f"  数据来源: 东方财富 data.eastmoney.com 官方API")
    print(f"{'=' * 80}")

    # ━━━ 1. 概念板块资金流 ━━━
    print("\n[1/5] 拉取概念板块资金流...")
    concept_data = concept_sector_fund_flow()
    all_sectors = concept_data["sectors"]
    inflow_top10 = all_sectors[:10]  # 已按主力净流入降序
    outflow_top10 = all_sectors[-10:][::-1]  # 取最后10个反转

    # 补全涨跌幅和超大单数据
    print("  补全涨跌幅和超大单数据...")
    top_codes = {s["code"] for s in all_sectors[:20]} | {s["code"] for s in all_sectors[-20:]}
    pct_map = get_sector_change_pct(top_codes)
    super_map = get_sector_super_large(top_codes)

    for s in inflow_top10 + outflow_top10:
        s["change_pct"] = pct_map.get(s["code"], 0)
        s["super_large_net"] = super_map.get(s["code"], 0)

    print(f"\n{'─' * 70}")
    print(f"  📊 概念板块主力净流入 TOP 10（共 {concept_data['total']} 个板块）")
    print(f"{'─' * 70}")
    for i, s in enumerate(inflow_top10):
        emoji = "🔥" if i < 3 else "  "
        pct = s.get("change_pct", 0)
        print(f"  {emoji} {i+1:2d}. {s['name']:<12s} 主力={s['main_net']/1e8:>8.2f}亿  "
              f"涨跌={pct:>+6.2f}%  超大单={s.get('super_large_net',0)/1e8:.2f}亿")

    print(f"\n{'─' * 70}")
    print(f"  📉 概念板块主力净流出 TOP 10")
    print(f"{'─' * 70}")
    for i, s in enumerate(outflow_top10):
        emoji = "⚠️" if i < 3 else "  "
        pct = s.get("change_pct", 0)
        print(f"  {emoji} {i+1:2d}. {s['name']:<12s} 主力={s['main_net']/1e8:>8.2f}亿  "
              f"涨跌={pct:>+6.2f}%")

    # ━━━ 2. 行业板块资金流 ━━━
    print("\n[2/5] 拉取行业板块资金流...")
    ind_data = industry_sector_fund_flow()
    ind_sectors = ind_data["sectors"]
    ind_inflow = ind_sectors[:10]
    ind_outflow = ind_sectors[-10:][::-1]

    print(f"\n{'─' * 70}")
    print(f"  🏢 行业板块主力净流入 TOP 10（共 {ind_data['total']} 个行业）")
    print(f"{'─' * 70}")
    for i, s in enumerate(ind_inflow):
        emoji = "🔥" if i < 3 else "  "
        print(f"  {emoji} {i+1:2d}. {s['name']:<12s} 主力={s['main_net']/1e8:>8.2f}亿")

    print(f"\n{'─' * 70}")
    print(f"  📉 行业板块主力净流出 TOP 10")
    print(f"{'─' * 70}")
    for i, s in enumerate(ind_outflow):
        emoji = "⚠️" if i < 3 else "  "
        print(f"  {emoji} {i+1:2d}. {s['name']:<12s} 主力={s['main_net']/1e8:>8.2f}亿")

    # ━━━ 3. 前3流入板块内个股 TOP10 ━━━
    print("\n[3/5] 拉取前3流入板块个股资金流...")
    for rank, sec in enumerate(inflow_top10[:3]):
        print(f"  分析 {sec['name']}({sec['code']}) 个股...")
        detail = sector_stock_fund_flow(sec["code"])
        top10 = detail["stocks"][:10]
        bottom5 = detail["stocks"][-5:][::-1]

        print(f"\n{'─' * 70}")
        print(f"  🏭 {sec['name']} — 个股主力净流入 TOP 10（共 {detail['total']} 只）")
        print(f"{'─' * 70}")
        print(f"  {'排名':<4s} {'代码':<8s} {'名称':<10s} {'主力净流入':>14s}")
        print(f"  {'─' * 42}")
        for i, s in enumerate(top10):
            print(f"  {i+1:2d}.  {s['code']:<8s} {s['name']:<10s} {s['main_net']/1e4:>12.0f}万")

        print(f"\n  📉 主力净流出 TOP 5:")
        for i, s in enumerate(bottom5):
            print(f"  {i+1}.  {s['code']:<8s} {s['name']:<10s} {s['main_net']/1e4:>12.0f}万")

    # ━━━ 4. 龙虎榜 ━━━
    print("\n[4/5] 拉取全市场龙虎榜...")
    dt = daily_dragon_tiger_scan(date=today_str, min_net_buy_wan=3000)

    print(f"\n{'─' * 70}")
    print(f"  🐉 全市场龙虎榜 ({dt['date']}) — 共 {dt['total']} 条（净买≥3000万）")
    print(f"{'─' * 70}")
    if dt["stocks"]:
        for i, s in enumerate(dt["stocks"][:15]):
            emoji = "🔴" if s['net_buy_wan'] > 10000 else "🟡"
            print(f"  {emoji} {i+1:2d}. {s['code']} {s['name']:<8s} 净买={s['net_buy_wan']:>8.0f}万  "
                  f"涨跌={s['change_pct']:>+7.2f}%  换手={s['turnover_pct']}%")
            print(f"       上榜原因: {s['reason'][:60]}")
    else:
        print(f"  ⚠️ 今日暂无符合条件的龙虎榜数据（可能市场未触发涨跌停/振幅异常等条件）")

    # ━━━ 5. 重点个股机构/游资席位分析 ━━━
    print("\n[5/5] 重点个股席位分析...")
    top_dt = dt["stocks"][:5]
    if top_dt:
        print(f"\n{'─' * 70}")
        print(f"  🏦 重点龙虎榜个股机构 vs 游资席位分析")
        print(f"{'─' * 70}")
        for stock in top_dt:
            try:
                analysis = dragon_tiger_seat_analysis(stock["code"], lookback_days=30)
                print(f"\n  【{stock['code']} {stock['name']}】")
                print(f"    龙虎榜净买: {stock['net_buy_wan']:.0f}万 | 涨跌: {stock['change_pct']:+.2f}%")
                print(f"    上榜原因: {stock['reason'][:60]}")
                print(f"    近30日上榜 {analysis['records_count']} 次")

                inst = analysis["institution"]
                hm = analysis["hot_money"]

                if inst["seats"]:
                    print(f"    🔴 机构: 买{inst['buy_total']:.0f}万 卖{inst['sell_total']:.0f}万 "
                          f"净持仓={inst['net_total']:.0f}万(还剩)")
                    for s in inst["seats"][:3]:
                        print(f"       {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")
                else:
                    print(f"    🔴 机构: 近30日无机构专用席位参与")

                if hm["seats"]:
                    print(f"    🟡 游资: 买{hm['buy_total']:.0f}万 卖{hm['sell_total']:.0f}万 "
                          f"净持仓={hm['net_total']:.0f}万(还剩)")
                    for s in hm["seats"][:5]:
                        print(f"       {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")
                else:
                    print(f"    🟡 游资: 近30日无游资营业部数据")
            except Exception as e:
                print(f"\n  【{stock['code']} {stock['name']}】席位分析失败: {e}")

    # ━━━ 板块轮动速览 ━━━
    print(f"\n{'─' * 70}")
    print(f"  🔄 板块轮动速览")
    print(f"{'─' * 70}")

    inflowing = [s["name"] for s in inflow_top10[:5]]
    outflowing = [s["name"] for s in outflow_top10[:5]]

    total_in = sum(s["main_net"] for s in inflow_top10)
    total_out = sum(s["main_net"] for s in outflow_top10)

    print(f"  💰 资金主要流入方向: {', '.join(inflowing)}")
    print(f"  💸 资金主要流出方向: {', '.join(outflowing)}")

    if total_in > abs(total_out):
        print(f"  📊 倾向: 主力资金整体偏积极 "
              f"(TOP10流入 {total_in/1e8:.0f}亿 vs 流出 {abs(total_out)/1e8:.0f}亿)")
    else:
        print(f"  📊 倾向: 主力资金整体偏谨慎 "
              f"(TOP10流入 {total_in/1e8:.0f}亿 vs 流出 {abs(total_out)/1e8:.0f}亿)")

    # 热门概念交叉分析
    top5_names = {s["name"] for s in inflow_top10[:5]}
    tech_themes = [n for n in top5_names if any(kw in n for kw in
        ["AI", "芯片", "半导体", "算力", "数据", "软件", "机器人", "智能", "互联", "通信",
         "5G", "6G", "光刻", "存储", "封装", "CPO", "液冷", "鸿蒙", "华为"])]
    finance_themes = [n for n in top5_names if any(kw in n for kw in
        ["金融", "证券", "银行", "保险", "券商", "地产"])]
    if tech_themes:
        print(f"  🖥️  科技方向活跃: {', '.join(tech_themes)}")
    if finance_themes:
        print(f"  💳 金融方向活跃: {', '.join(finance_themes)}")

    # ━━━ 风险声明 ━━━
    print(f"\n{'=' * 80}")
    print(f"  ⚠️ 研究声明")
    print(f"{'=' * 80}")
    print(f"  1. 数据来源: 东方财富 data.eastmoney.com 官方API，延迟约3-5秒")
    print(f"  2. 龙虎榜仅覆盖触发涨跌停/振幅异常/换手异常的交易日")
    print(f"  3. 机构/游资分类基于龙虎榜席位代码(OPERATEDEPT_CODE)，不完全精确")
    print(f"  4. 概念板块涨跌幅/超大单数据为补充拉取，与主力净流入非同一查询")
    print(f"  5. 所有数据仅供参考，不构成任何投资建议")
    print(f"  6. 资金流向 ≠ 未来涨跌方向，需结合基本面+估值综合判断")
    print(f"{'=' * 80}")

    # ━━━ 保存报告 ━━━
    report_dir = f"src/资金流向/{today_str}-资金流向扫描"
    os.makedirs(report_dir, exist_ok=True)

    report = {
        "scan_time": now_str,
        "concept_total": concept_data["total"],
        "top_inflow_sectors": inflow_top10,
        "top_outflow_sectors": outflow_top10,
        "industry_total": ind_data["total"],
        "industry_inflow": ind_inflow,
        "industry_outflow": ind_outflow,
        "dragon_tiger": dt,
    }
    report_path = os.path.join(report_dir, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 报告已保存至: {report_path}")

    # 更新 _index.md
    index_path = "src/资金流向/_index.md"
    os.makedirs("src/资金流向", exist_ok=True)
    index_entry = f"- [{today_str}-资金流向扫描]({today_str}-资金流向扫描/report.json) — 概念板块{concept_data['total']}个 + 行业{ind_data['total']}个"
    if not os.path.exists(index_path):
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(f"# 资金流向分析\n\n{index_entry}\n")
    else:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        if index_entry not in content:
            with open(index_path, "a", encoding="utf-8") as f:
                f.write(f"\n{index_entry}")
    print(f"📁 索引已更新: {index_path}")

    return report


if __name__ == "__main__":
    main()
