---
name: capital-flow-tracker
description: A股全市场资金流向追踪 — 覆盖概念板块(494个细分概念)+行业板块双维度，10个时间周期(今日~1年)，三类资金(机构/游资/散户)分类统计流入流出与净持仓。核心能力：①板块/个股资金流TOP排名 ②龙虎榜席位三方资金明细(买多少/卖多少/还剩多少) ③个股今日走势归因分析(为什么涨/跌，主因是什么，逻辑需充分验证+权威事实支撑)。适用于板块轮动研判、主力资金方向跟踪、机构游资动向监控、个股涨跌归因。
version: 1.1.0
updated: 2026-07-01
---

# A股资金流向追踪器 V1.1

全市场资金流向追踪工具——按概念板块（494 个细分概念）和行业板块双维度，覆盖 10 个时间周期，三方资金（机构/游资/散户）分类统计，输出板块级资金流向排名 + 板块内个股资金流 TOP 10 + 龙虎榜三方席位明细 + **个股今日走势归因分析（为什么涨/跌）**。

> **设计原则：** 依赖 a-stock-data 的通用 helper（`em_get`/`eastmoney_datacenter`），本 skill 只提供新增的资金流向聚合、席位分析、个股归因逻辑。
>
> **核心新增（V1.1）：** ① 机构/游资/散户三方资金分类 ② 个股今日涨跌归因分析（多维度交叉验证 + 权威事实支撑）

## When to Activate

- 用户要看**全市场资金流向**（哪些板块在流入/流出）
- 用户要看**板块内个股资金流排名**（流入 TOP 10 / 流出 TOP 10）
- 用户要看**机构/游资/散户三方资金动向**（各自流入多少、流出多少、净持仓还剩多少）
- 用户要分析**个股今日为什么涨/跌**（多维度归因：资金面+板块面+消息面+席位面，逻辑需充分验证）
- 用户要**多周期资金流对比**（今日/周/月/半年/年）
- 用户要**板块轮动研判**（资金从哪来、往哪去）
- 关键词：`资金流向`、`主力资金`、`板块轮动`、`机构动向`、`游资`、`散户`、`龙虎榜`、`行业资金流`、`概念资金流`、`主力净流入`、`资金排名`、`为什么涨`、`为什么跌`、`涨跌原因`、`归因分析`

## Prerequisites — 数据拉取全部委托给 a-stock-api

本 skill **不内置数据拉取代码**。所有行情/资金流/新闻/板块/融资融券/龙虎榜数据，统一通过项目共享模块 `a_stock_api` 获取。

```python
import sys
sys.path.insert(0, '.claude/skills/_shared')
from a_stock_api import (
    em_get,                    # 东财统一请求入口（已内置限流+重试）
    eastmoney_datacenter,      # 东财数据中心通用查询
    tencent_quote,             # 腾讯行情（PE/PB/市值/换手率，不封IP）
    stock_fund_flow_120d,      # 个股资金流120日
    eastmoney_fund_flow_minute, # 个股资金流分钟级
    industry_comparison,       # 行业板块排名
    eastmoney_concept_blocks,  # 个股概念板块归属
    eastmoney_stock_news,      # 个股新闻
    concept_sector_fund_flow,  # 概念板块资金流
    em_zt_pool,               # 涨停池
    full_valuation,            # 完整估值
)
```

> 所有 `eastmoney.com` 请求已内置限流（≥1s 间隔 + 随机抖动 + Keep-Alive + 自动重试），无需自行实现。

---

## 时间周期映射

| 周期 | 参数值 | 交易日 | 数据源 | 说明 |
|------|--------|--------|--------|------|
| 今日 | `today` | 实时 | push2 klt=1（分钟级聚合） | 盘中实时 |
| 1周 | `1w` | ~5天 | push2his 日级聚合 | |
| 2周 | `2w` | ~10天 | push2his 日级聚合 | |
| 1月 | `1m` | ~22天 | push2his 日级聚合 | |
| 2月 | `2m` | ~44天 | push2his 日级聚合 | |
| 3月 | `3m` | ~66天 | push2his 日级聚合 | |
| 4月 | `4m` | ~88天 | push2his 日级聚合 | |
| 5月 | `5m` | ~110天 | push2his 日级聚合 | |
| 半年 | `6m` | ~125天 | push2his 日级聚合 | 接近上限 |
| 1年 | `1y` | ~250天 | push2his 日级聚合 | ⚠️ 上限~120天，超限自动截断 |

> **⚠️ 数据上限：** push2his 接口最大返回约 120 个交易日（~6 个月）。1 年周期实际覆盖约 120 天。

```python
PERIOD_MAP = {
    "today": 0,
    "1w": 5, "2w": 10,
    "1m": 22, "2m": 44, "3m": 66,
    "4m": 88, "5m": 110,
    "6m": 125, "1y": 250,
}

def period_to_days(period: str) -> int:
    """周期字符串 → 交易日数量"""
    return PERIOD_MAP.get(period, 22)
```

---

## Layer 1: 板块级资金流向

### 1.1 概念板块资金流向排名（核心）

概念板块（`m:90+t:3`）覆盖 494 个细分概念（CPO、液冷、HBM、人形机器人、小金属、电子纸……），比行业板块（86 个）更精细，是资金流向分析的主力维度。

```python
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

def concept_sector_fund_flow(sort_by: str = "f62", top_n: int = 30) -> dict:
    """
    概念板块资金流向排名。
    sort_by: 'f62'=主力净流入, 'f66'=超大单, 'f72'=大单
    返回: {total, sectors: [{code, name, main_net, super_large_net,
           large_net, mid_net, small_net, change_pct, up_count, down_count}]}
    金额单位: 元
    """
    params = {
        "pn": "1", "pz": str(min(top_n, 500)), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",  # 概念板块
        "fields": "f2,f3,f12,f14,f62,f66,f72,f78,f84,f104,f105,f128",
        "st": sort_by,     # 按资金流排序
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
            "main_net": it.get("f62") or 0,          # 主力净流入
            "super_large_net": it.get("f66") or 0,    # 超大单净流入
            "large_net": it.get("f72") or 0,          # 大单净流入
            "mid_net": it.get("f78") or 0,            # 中单净流入
            "small_net": it.get("f84") or 0,          # 小单净流入
            "change_pct": it.get("f3", 0),            # 涨跌幅
            "up_count": it.get("f104", 0),            # 上涨家数
            "down_count": it.get("f105", 0),          # 下跌家数
            "leader_stock": it.get("f128", ""),       # 领涨股
        })
    return {"total": total, "sectors": sectors}


# 用法
result = concept_sector_fund_flow()
print(f"共 {result['total']} 个概念板块")
print("\n主力净流入 TOP 10:")
for s in result["sectors"][:10]:
    print(f"  {s['name']}: 主力={s['main_net']/1e8:.2f}亿 涨跌={s['change_pct']}% 涨{s['up_count']}跌{s['down_count']}")

# 取主力净流出 TOP 10（反转排序）
outflow = sorted(result["sectors"], key=lambda x: x["main_net"])[:10]
print("\n主力净流出 TOP 10:")
for s in outflow:
    print(f"  {s['name']}: 主力={s['main_net']/1e8:.2f}亿")
```

### 1.2 行业板块资金流向排名（粗粒度）

```python
def industry_sector_fund_flow(top_n: int = 86) -> dict:
    """行业板块资金流向（m:90+t:2，~86个行业）"""
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
            "change_pct": it.get("f3", 0),
        })
    return {"total": len(sectors), "sectors": sectors}
```

### 1.3 BK 码查找器

概念板块的 BK 码不是固定的，需要从全列表搜索：

```python
# 模块级缓存：全量概念板块列表
_CONCEPT_CACHE = None

def _load_concept_list(force_refresh: bool = False) -> list[dict]:
    """加载全量概念板块列表（含 BK 码），自动缓存"""
    global _CONCEPT_CACHE
    if _CONCEPT_CACHE is not None and not force_refresh:
        return _CONCEPT_CACHE
    params = {
        "pn": "1", "pz": "500", "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",
        "fields": "f12,f14",
    }
    r = em_get(PUSH2_CLIST, params=params,
               headers={"Referer": "https://data.eastmoney.com/"}, timeout=15)
    d = r.json()
    _CONCEPT_CACHE = [
        {"code": it.get("f12", ""), "name": it.get("f14", "")}
        for it in (d.get("data", {}).get("diff", []) or [])
    ]
    return _CONCEPT_CACHE


def find_concept_code(keyword: str) -> list[dict]:
    """
    按关键字搜索概念板块 BK 码。
    例: find_concept_code('CPO') → [{'code': 'BK1185', 'name': 'CPO概念'}, ...]
    """
    all_concepts = _load_concept_list()
    keyword_lower = keyword.lower()
    return [
        c for c in all_concepts
        if keyword_lower in c["name"].lower()
    ]


# 用法
matches = find_concept_code("液冷")
for m in matches:
    print(f"  [{m['code']}] {m['name']}")
# → [BK1151] 液冷概念
```

---

## Layer 2: 板块内个股资金流向排名

### 2.1 概念板块内个股资金流 TOP N

```python
def sector_stock_fund_flow(bk_code: str, top_n: int = 10) -> dict:
    """
    指定概念板块内个股资金流向排名。
    bk_code: BK码，如 'BK1185'=CPO概念, 'BK1036'=半导体概念
    返回: {total, inflow_top10: [...], outflow_top10: [...]}
    金额单位: 元
    """
    # 流入 TOP N
    params_in = {
        "pn": "1", "pz": str(top_n), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": f"b:{bk_code}+f:!50",  # 该板块内，排除ST
        "fields": "f2,f3,f4,f8,f10,f12,f14,f20,f21,f62,f66,f72",
        "st": "f62",  # 按主力净流入降序
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    r_in = em_get(PUSH2_CLIST, params=params_in, headers=headers, timeout=15)
    d_in = r_in.json()
    total = d_in.get("data", {}).get("total", 0)
    inflow = _parse_stock_fund_flow(d_in)

    # 流出 TOP N（反转排序）
    params_out = {**params_in, "st": "f62", "po": "1"}  # po=1 升序 = 最小(最负)在前
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
            "main_net": it.get("f62") or 0,          # 主力净流入(元)
            "super_large_net": it.get("f66") or 0,    # 超大单净流入
            "large_net": it.get("f72") or 0,          # 大单净流入
            "change_pct": it.get("f3", 0),            # 涨跌幅%
            "price": it.get("f2", 0),                 # 最新价
            "turnover_pct": it.get("f8", 0),          # 换手率%
            "volume_ratio": it.get("f10", 0),         # 量比
            "mcap": it.get("f20") or 0,               # 总市值(元)
            "float_mcap": it.get("f21") or 0,         # 流通市值(元)
        })
    return stocks


# 用法
result = sector_stock_fund_flow("BK1036")  # 半导体概念
print(f"半导体概念共 {result['total']} 只个股")
print("\n主力净流入 TOP 10:")
for s in result["inflow_top10"]:
    print(f"  {s['code']} {s['name']}: 主力={s['main_net']/1e4:.0f}万 涨跌={s['change_pct']}% 换手={s['turnover_pct']}%")
print("\n主力净流出 TOP 10:")
for s in result["outflow_top10"]:
    print(f"  {s['code']} {s['name']}: 主力={s['main_net']/1e4:.0f}万")
```

---

## Layer 3: 多周期资金流聚合

### 3.1 个股多周期资金流

```python
PUSH2_HIS = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

def stock_multiperiod_fund_flow(code: str, periods: list[str] = None) -> dict:
    """
    个股多周期资金流聚合。
    periods: 周期列表，默认 ['today','1w','2w','1m','3m','6m','1y']
    返回: {period: {main_net, super_large_net, large_net, mid_net, small_net}}
    金额单位: 元
    """
    if periods is None:
        periods = ["today", "1w", "2w", "1m", "3m", "6m", "1y"]

    # 当日数据走分钟级 API
    result = {}
    today_data = _fetch_today_fund_flow(code)
    if today_data:
        result["today"] = today_data

    # 历史日级数据
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "lmt": "250",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(PUSH2_HIS, params=params, headers=headers, timeout=20)
        d = r.json()
        klines = d.get("data", {}).get("klines", []) or []
    except Exception:
        klines = []

    if not klines:
        return result

    # 解析日级数据
    daily = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 7:
            daily.append({
                "date": parts[0],
                "main_net": float(parts[1]) if parts[1] != "-" else 0,
                "small_net": float(parts[2]) if parts[2] != "-" else 0,
                "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                "large_net": float(parts[4]) if parts[4] != "-" else 0,
                "super_net": float(parts[5]) if parts[5] != "-" else 0,
            })

    # 按周期聚合
    for period in periods:
        if period == "today":
            continue
        days = period_to_days(period)
        window = daily[-min(days, len(daily)):] if days <= len(daily) else daily
        result[period] = {
            "main_net": sum(d["main_net"] for d in window),
            "super_large_net": sum(d["super_net"] for d in window),
            "large_net": sum(d["large_net"] for d in window),
            "mid_net": sum(d["mid_net"] for d in window),
            "small_net": sum(d["small_net"] for d in window),
            "days": len(window),
        }

    return result


def _fetch_today_fund_flow(code: str) -> dict | None:
    """获取今日分钟级资金流并聚合"""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    params = {
        "secid": secid, "klt": "1",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "lmt": "250",
    }
    headers = {"Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
                   params=params, headers=headers, timeout=15)
        d = r.json()
        klines = d.get("data", {}).get("klines", []) or []
    except Exception:
        return None

    if not klines:
        return None

    main_net = 0.0
    super_net = 0.0
    large_net = 0.0
    mid_net = 0.0
    small_net = 0.0
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 6:
            main_net += float(parts[1]) if parts[1] != "-" else 0
            small_net += float(parts[2]) if parts[2] != "-" else 0
            mid_net += float(parts[3]) if parts[3] != "-" else 0
            large_net += float(parts[4]) if parts[4] != "-" else 0
            super_net += float(parts[5]) if parts[5] != "-" else 0

    return {
        "main_net": main_net, "super_large_net": super_net,
        "large_net": large_net, "mid_net": mid_net, "small_net": small_net,
        "minutes": len(klines),
    }


# 用法
flow = stock_multiperiod_fund_flow("300339")
for period, data in flow.items():
    print(f"{period}: 主力={data['main_net']/1e4:.0f}万 ({data.get('days', data.get('minutes', '?'))}个周期)")
```

### 3.2 板块多周期资金流聚合

```python
def sector_multiperiod_fund_flow(bk_code: str, periods: list[str] = None) -> dict:
    """
    板块多周期资金流 — 汇总板块内所有个股的资金流。
    返回: {period: {main_net, stock_count, top_inflow: [...], top_outflow: [...]}}
    ⚠️ 批量拉取，耗时会较长（每只个股需一次请求）
    """
    if periods is None:
        periods = ["today", "1w", "2w", "1m", "3m", "6m"]

    # 1. 获取板块内所有个股
    params = {
        "pn": "1", "pz": "200", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": f"b:{bk_code}+f:!50",
        "fields": "f12,f14,f62",
        "st": "f62",
    }
    r = em_get(PUSH2_CLIST, params=params,
               headers={"Referer": "https://data.eastmoney.com/"}, timeout=15)
    d = r.json()
    all_stocks = [
        {"code": it.get("f12", ""), "name": it.get("f14", ""),
         "today_main_net": it.get("f62") or 0}
        for it in (d.get("data", {}).get("diff", []) or [])
    ]

    # 2. 对每只个股拉历史资金流并聚合
    results = {p: {"main_net": 0, "stocks": []} for p in periods}
    for stock in all_stocks:
        code = stock["code"]
        try:
            flow = stock_multiperiod_fund_flow(code, periods)
            for p in periods:
                if p in flow:
                    net = flow[p]["main_net"]
                    results[p]["main_net"] += net
                    results[p]["stocks"].append({
                        "code": code, "name": stock["name"],
                        "main_net": net,
                    })
        except Exception:
            continue

    # 3. 每个周期内排序取 TOP/BOTTOM
    for p in periods:
        stocks_sorted = sorted(results[p]["stocks"], key=lambda x: x["main_net"], reverse=True)
        results[p]["inflow_top10"] = stocks_sorted[:10]
        results[p]["outflow_top10"] = stocks_sorted[-10:][::-1]
        results[p]["stock_count"] = len(stocks_sorted)

    return results
```

> **⚠️ 批量拉取提醒：** 板块内可能有几十上百只个股，每只需一次 push2his 请求。按 2 秒间隔计算，100 只个股约需 3-4 分钟。建整使用今日数据（单次请求即可）做快速扫描，历史多周期只在深度分析时使用。

---

## Layer 4: 龙虎榜机构/游资追踪

### 4.1 个股龙虎榜席位分析

判断谁是买入主力——机构 vs 游资，以及各自的净持仓（还剩多少）。

```python
def dragon_tiger_seat_analysis(code: str, lookback_days: int = 30) -> dict:
    """
    个股龙虎榜席位追踪 —— 识别机构和游资动向。
    返回: {records, institution, hot_money}
    
    机构识别规则: OPERATEDEPT_CODE == '0' → 机构专用席位
    游资识别规则: 非机构席位 → 营业部席位（游资）
    "流入多少" = 席位买入金额
    "还剩多少" = 席位买入 - 席位卖出 = 净持仓(万元)
    """
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    # 1. 上榜记录
    records = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start_date}')(TRADE_DATE<='{end_date}')(SECURITY_CODE='{code}')",
        page_size=50,
        sort_columns="TRADE_DATE", sort_types="-1",
    )

    # 2. 席位明细（按日期逐条查，取最近上榜日）
    institution = {"buy_total": 0, "sell_total": 0, "net_total": 0, "seats": []}
    hot_money = {"buy_total": 0, "sell_total": 0, "net_total": 0, "seats": []}

    for record in records[:5]:  # 只查最近5次上榜
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
                buy_amt = (row.get("BUY") or 0) / 10000  # 万元
                sell_amt = (row.get("SELL") or 0) / 10000
                net_amt = (row.get("NET") or 0) / 10000

                seat_info = {
                    "name": seat_name,
                    "date": trade_date,
                    "buy_wan": round(buy_amt, 1),
                    "sell_wan": round(sell_amt, 1),
                    "net_wan": round(net_amt, 1),  # ← "还剩多少"
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

    # 汇总取整
    for cat in [institution, hot_money]:
        for k in ["buy_total", "sell_total", "net_total"]:
            cat[k] = round(cat[k], 1)
        # 去重合并同席位多日数据
        cat["seats"] = _merge_seat_positions(cat["seats"])

    return {
        "code": code,
        "records_count": len(records),
        "institution": institution,
        "hot_money": hot_money,
    }


def _merge_seat_positions(seats: list[dict]) -> list[dict]:
    """合并同一席位多日数据，汇总净持仓"""
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
    # 按净持仓排序
    result = list(merged.values())
    result.sort(key=lambda x: x["net_wan"], reverse=True)
    # 取整
    for s in result:
        s["buy_wan"] = round(s["buy_wan"], 1)
        s["sell_wan"] = round(s["sell_wan"], 1)
        s["net_wan"] = round(s["net_wan"], 1)
    return result


# 用法
analysis = dragon_tiger_seat_analysis("000988")
print(f"近30日上榜 {analysis['records_count']} 次")
print(f"\n机构动向:")
print(f"  累计买入: {analysis['institution']['buy_total']:.0f}万")
print(f"  累计卖出: {analysis['institution']['sell_total']:.0f}万")
print(f"  净持仓:   {analysis['institution']['net_total']:.0f}万  ← 还剩多少")
for s in analysis["institution"]["seats"][:5]:
    print(f"  {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")
print(f"\n游资动向:")
print(f"  累计买入: {analysis['hot_money']['buy_total']:.0f}万")
print(f"  累计卖出: {analysis['hot_money']['sell_total']:.0f}万")
print(f"  净持仓:   {analysis['hot_money']['net_total']:.0f}万")
for s in analysis["hot_money"]["seats"][:5]:
    print(f"  {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")
```

### 4.2 全市场龙虎榜扫描

```python
def daily_dragon_tiger_scan(date: str = None, min_net_buy_wan: float = 0) -> dict:
    """
    全市场龙虎榜扫描。
    date: YYYY-MM-DD，默认最新
    min_net_buy_wan: 净买入下限(万元)
    返回: {date, total, stocks: [{code, name, reason, net_buy_wan, change_pct}]}
    """
    if date is None:
        date = __import__('datetime').datetime.now().strftime("%Y-%m-%d")

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
```

---

## Layer 5: 综合报告生成

### 5.1 一键资金流向全景报告

```python
def capital_flow_report(top_sectors: int = 10, seats_top_n: int = 5) -> dict:
    """
    资金流向全景报告。
    包含: 概念板块资金流 TOP/BOTTOM + 前3板块内个股资金流 TOP10 +
          全市场龙虎榜 + 重点个股机构/游资分析
    """
    report = {}

    # 1. 概念板块资金流排名
    print("[1/5] 拉取概念板块资金流...")
    sectors = concept_sector_fund_flow(top_n=top_sectors * 2)  # 多拉一些做排序
    inflow_sectors = sectors["sectors"][:top_sectors]
    outflow_sectors = sorted(sectors["sectors"], key=lambda x: x["main_net"])[:top_sectors]
    report["top_inflow_sectors"] = inflow_sectors
    report["top_outflow_sectors"] = outflow_sectors

    # 2. 前 3 流入板块的个股 TOP10
    report["sector_stock_detail"] = {}
    for i, sec in enumerate(inflow_sectors[:3]):
        print(f"[2.{i+1}/5] 分析 {sec['name']}({sec['code']}) 个股...")
        detail = sector_stock_fund_flow(sec["code"], top_n=10)
        report["sector_stock_detail"][sec["code"]] = {
            "sector_name": sec["name"],
            **detail,
        }

    # 3. 全市场龙虎榜
    print("[3/5] 拉取全市场龙虎榜...")
    report["dragon_tiger"] = daily_dragon_tiger_scan(min_net_buy_wan=5000)

    # 4. 重点个股席位分析（取龙虎榜净买入前 5）
    report["seat_analysis"] = {}
    top_stocks = report["dragon_tiger"]["stocks"][:seats_top_n]
    for i, stock in enumerate(top_stocks):
        print(f"[4.{i+1}/5] 分析 {stock['name']}({stock['code']}) 席位...")
        try:
            report["seat_analysis"][stock["code"]] = dragon_tiger_seat_analysis(
                stock["code"], lookback_days=30
            )
        except Exception as e:
            report["seat_analysis"][stock["code"]] = {"error": str(e)}

    print("[5/5] 报告生成完成!")
    return report


def print_capital_flow_report(report: dict):
    """打印资金流向全景报告（中文友好格式）"""
    print("=" * 80)
    print("  A股资金流向全景报告")
    now = __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"  生成时间: {now}")
    print("=" * 80)

    # 概念板块 TOP 流入
    print(f"\n{'─' * 60}")
    print("  📊 概念板块主力净流入 TOP 10")
    print(f"{'─' * 60}")
    for i, s in enumerate(report["top_inflow_sectors"][:10]):
        emoji = "🔥" if i < 3 else "  "
        print(f"  {emoji} {i+1:2d}. {s['name']:<10s} 主力={s['main_net']/1e8:>8.2f}亿  "
              f"涨跌={s['change_pct']:>6.2f}%  涨{s['up_count']}跌{s['down_count']}")

    # 概念板块 TOP 流出
    print(f"\n{'─' * 60}")
    print("  📉 概念板块主力净流出 TOP 10")
    print(f"{'─' * 60}")
    for i, s in enumerate(report["top_outflow_sectors"][:10]):
        emoji = "⚠️" if i < 3 else "  "
        print(f"  {emoji} {i+1:2d}. {s['name']:<10s} 主力={s['main_net']/1e8:>8.2f}亿")

    # 前3板块个股 TOP10
    for bk_code, detail in list(report.get("sector_stock_detail", {}).items())[:3]:
        sec_name = detail.get("sector_name", bk_code)
        print(f"\n{'─' * 60}")
        print(f"  🏭 {sec_name} — 个股资金流 TOP 10")
        print(f"{'─' * 60}")
        print(f"  {'代码':<8s} {'名称':<10s} {'主力净流入':>12s}  {'涨跌幅':>8s}  {'换手率':>8s}")
        print(f"  {'─' * 50}")
        for s in detail.get("inflow_top10", [])[:10]:
            print(f"  {s['code']:<8s} {s['name']:<10s} {s['main_net']/1e4:>10.0f}万  "
                  f"{s['change_pct']:>7.2f}%  {s['turnover_pct']:>7.2f}%")

        # 流出 TOP 5
        print(f"\n  主力净流出 TOP 5:")
        for s in detail.get("outflow_top10", [])[:5]:
            print(f"  {s['code']:<8s} {s['name']:<10s} {s['main_net']/1e4:>10.0f}万")

    # 龙虎榜
    dt = report.get("dragon_tiger", {})
    print(f"\n{'─' * 60}")
    print(f"  🐉 全市场龙虎榜 ({dt.get('date', '')}) — 共{dt.get('total', 0)}条")
    print(f"{'─' * 60}")
    for s in dt.get("stocks", [])[:10]:
        print(f"  {s['code']} {s['name']:<8s} 净买={s['net_buy_wan']:.0f}万  "
              f"涨跌={s['change_pct']}%  {s['reason'][:30]}")

    # 重点个股席位分析
    print(f"\n{'─' * 60}")
    print("  🏦 重点个股机构 vs 游资分析")
    print(f"{'─' * 60}")
    for code, analysis in report.get("seat_analysis", {}).items():
        if "error" in analysis:
            continue
        stock_name = ""
        for s in dt.get("stocks", []):
            if s["code"] == code:
                stock_name = s["name"]
                break
        print(f"\n  【{code} {stock_name}】(近30日上榜{analysis['records_count']}次)")
        inst = analysis["institution"]
        hm = analysis["hot_money"]
        print(f"  🔴 机构: 买{inst['buy_total']:.0f}万 卖{inst['sell_total']:.0f}万  "
              f"净持仓={inst['net_total']:.0f}万(还剩)")
        for s in inst["seats"][:3]:
            print(f"      {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")
        print(f"  🟡 游资: 买{hm['buy_total']:.0f}万 卖{hm['sell_total']:.0f}万  "
              f"净持仓={hm['net_total']:.0f}万(还剩)")
        for s in hm["seats"][:3]:
            print(f"      {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")

    print(f"\n{'=' * 80}")
    print("  ⚠️ 研究声明: 以上数据基于公开API，仅供参考。不构成任何投资建议。")
    print(f"{'=' * 80}")


# 用法
# report = capital_flow_report(top_sectors=10)
# print_capital_flow_report(report)
```

---

## 三方资金分类体系（机构 / 游资 / 散户）

资金流向分析的核心是把资金按参与主体拆开，理解**谁在买、谁在卖、各自意图是什么**。

### 分类标准

| 资金类型 | 数据来源 | 识别依据 | 交易特征 | 意图判断 |
|----------|---------|---------|---------|---------|
| 🔴 **机构资金** | push2 超大单(f66) + 龙虎榜机构席位 | 单笔≥100万手 / 席位代码="0" | 大额、集中、有节奏 | 中长期配置、产业逻辑 |
| 🟡 **游资资金** | push2 大单(f72) + 龙虎榜营业部席位 | 单笔≥20万手且<100万手 / 席位代码≠"0" | 快进快出、追涨杀跌 | 短期套利、题材炒作 |
| 🟢 **散户资金** | push2 中单(f78) + 小单(f84) | 单笔<20万手 | 分散、情绪化、追高 | 跟随、情绪驱动 |

### 三方资金净额计算

```python
def classify_fund_flow(stock_fund_flow_data: dict, dragon_tiger_data: dict = None) -> dict:
    """
    将个股资金流按机构/游资/散户三方分类。
    
    数据来源：
    - push2 分钟级/日级资金流: f66(超大单) / f72(大单) / f78(中单) / f84(小单)
    - 龙虎榜席位明细: 机构专用席位(OPERATEDEPT_CODE="0") vs 营业部席位
    
    返回: {
        institution: {inflow, outflow, net, ...},  # 机构
        hot_money:   {inflow, outflow, net, ...},  # 游资
        retail:      {inflow, outflow, net, ...},  # 散户
    }
    
    ⚠️ 注意：
    - push2 的超大单/大单/中单/小单是净流入（流入-流出），不区分买卖方向
    - 龙虎榜席位给出的是具体买卖金额，可区分买卖方向
    - 两者结合才能做完整的三方分类
    """
    flow = stock_fund_flow_data
    result = {
        "institution": {
            "net_flow": flow.get("super_large_net", 0),  # 超大单净流入 ≈ 机构净流向
            "source": "push2 超大单(f66)",
        },
        "hot_money": {
            "net_flow": flow.get("large_net", 0),  # 大单净流入 ≈ 游资净流向
            "source": "push2 大单(f72)",
        },
        "retail": {
            "mid_net": flow.get("mid_net", 0),      # 中单净流入
            "small_net": flow.get("small_net", 0),  # 小单净流入
            "net_flow": (flow.get("mid_net", 0) or 0) + (flow.get("small_net", 0) or 0),
            "source": "push2 中单(f78)+小单(f84)",
        },
    }
    
    # 如果有龙虎榜数据，用席位明细精修机构/游资数据
    if dragon_tiger_data:
        inst = dragon_tiger_data.get("institution", {})
        hm = dragon_tiger_data.get("hot_money", {})
        result["institution"]["dragon_tiger_buy"] = inst.get("buy_total", 0)  # 万元
        result["institution"]["dragon_tiger_sell"] = inst.get("sell_total", 0)
        result["institution"]["dragon_tiger_net"] = inst.get("net_total", 0)
        result["institution"]["dragon_tiger_seats"] = inst.get("seats", [])[:5]
        result["hot_money"]["dragon_tiger_buy"] = hm.get("buy_total", 0)
        result["hot_money"]["dragon_tiger_sell"] = hm.get("sell_total", 0)
        result["hot_money"]["dragon_tiger_net"] = hm.get("net_total", 0)
        result["hot_money"]["dragon_tiger_seats"] = hm.get("seats", [])[:5]
    
    # 计算各方的"还剩多少"（净持仓）
    for party in ["institution", "hot_money"]:
        dt = result[party]
        if "dragon_tiger_net" in dt:
            dt["remaining_position_wan"] = dt["dragon_tiger_net"]  # 龙虎榜净额 = 剩余仓位
        else:
            dt["remaining_position_wan"] = "无龙虎榜明细数据，仅能参考净流向方向"
    
    result["retail"]["remaining_position_wan"] = "散户持仓分散，不适用单席位追踪"
    
    return result


def print_three_party_analysis(analysis: dict, stock_name: str = ""):
    """打印三方资金分析（中文友好）"""
    print(f"\n{'─' * 60}")
    print(f"  💰 {stock_name} 三方资金分析")
    print(f"{'─' * 60}")
    
    inst = analysis["institution"]
    hm = analysis["hot_money"]
    retail = analysis["retail"]
    
    # 机构
    inst_net = inst["net_flow"]
    inst_dir = "⬆️流入" if inst_net > 0 else "⬇️流出"
    print(f"  🔴 机构资金: 净{inst_dir} {abs(inst_net)/1e4:.0f}万")
    print(f"     数据来源: {inst['source']}")
    if "dragon_tiger_buy" in inst:
        print(f"     龙虎榜: 买{inst['dragon_tiger_buy']:.0f}万 卖{inst['dragon_tiger_sell']:.0f}万 "
              f"净持仓={inst['dragon_tiger_net']:.0f}万(还剩)")
    
    # 游资
    hm_net = hm["net_flow"]
    hm_dir = "⬆️流入" if hm_net > 0 else "⬇️流出"
    print(f"  🟡 游资资金: 净{hm_dir} {abs(hm_net)/1e4:.0f}万")
    print(f"     数据来源: {hm['source']}")
    if "dragon_tiger_buy" in hm:
        print(f"     龙虎榜: 买{hm['dragon_tiger_buy']:.0f}万 卖{hm['dragon_tiger_sell']:.0f}万 "
              f"净持仓={hm['dragon_tiger_net']:.0f}万(还剩)")
    
    # 散户
    retail_net = retail["net_flow"]
    retail_dir = "⬆️流入" if retail_net > 0 else "⬇️流出"
    print(f"  🟢 散户资金: 净{retail_dir} {abs(retail_net)/1e4:.0f}万")
    print(f"     数据来源: {retail['source']}")
    
    # 三方合力判断
    inst_sign = 1 if inst_net > 0 else (-1 if inst_net < 0 else 0)
    hm_sign = 1 if hm_net > 0 else (-1 if hm_net < 0 else 0)
    retail_sign = 1 if retail_net > 0 else (-1 if retail_net < 0 else 0)
    signs = [inst_sign, hm_sign, retail_sign]
    
    if all(s > 0 for s in signs):
        verdict = "✅ 三方同向流入 → 最强信号，共识度高"
    elif all(s < 0 for s in signs):
        verdict = "❌ 三方同向流出 → 最弱信号，全面出逃"
    elif inst_sign > 0 and retail_sign < 0:
        verdict = "🔍 机构流入+散户流出 → 机构吸筹，散户恐慌出局（潜在机会）"
    elif inst_sign < 0 and retail_sign > 0:
        verdict = "⚠️ 机构流出+散户流入 → 机构派发，散户接盘（潜在风险）"
    elif hm_sign > 0 and inst_sign < 0:
        verdict = "🎯 游资拉升+机构出货 → 题材炒作，需警惕"
    else:
        verdict = "➖ 三方分歧，方向不明确"
    
    print(f"\n  📊 合力判断: {verdict}")
```

---

## Layer 6: 个股今日走势归因分析

### 6.1 归因分析框架

个股"为什么涨/跌"需要从**五个维度**交叉验证，单维度信号只能作为线索，多维度同向才能形成置信度结论。

| 维度 | 数据来源 | 分析内容 | 权重 |
|------|---------|---------|------|
| 💰 **资金面** | push2 分钟级/push2his 日级 | 三方资金（机构/游资/散户）流向方向和力度 | **30%** |
| 🏭 **板块面** | concept_sector_fund_flow | 所属概念板块整体资金流方向、板块涨跌家数 | **20%** |
| 📰 **消息面** | 东财个股新闻 + 巨潮公告 | 当日新闻催化、公告事件 | **25%** |
| 🐉 **席位面** | 龙虎榜上榜原因 + 席位明细 | 是否有龙虎榜触发、机构/游资席位买卖 | **15%** |
| 📈 **技术面** | 腾讯行情(push2) + 换手/量比 | 涨幅、换手率、量比、振幅 | **10%** |

> **归因逻辑铁律：**
> 1. 每个结论必须绑定具体数据依据（来源+数值+时间），严禁"可能是"等模糊表述
> 2. 至少 2 个维度同向 → 中等置信度，3+ 维度同向 → 高置信度
> 3. 消息面优先使用一级来源（公司公告、官方政策），二级来源（新闻）仅作线索
> 4. 如无明确主因，明确说"多因素交织，待进一步验证"，不强行归因

### 6.2 个股今日归因分析实现

```python
def stock_daily_attribution(code: str) -> dict:
    """
    个股今日走势归因分析 —— 回答"为什么涨/跌"。
    
    五维度交叉验证：
    1. 资金面 → push2 分钟级三方资金净流向
    2. 板块面 → 所属概念板块资金流排名
    3. 消息面 → 近7日个股新闻/公告
    4. 席位面 → 龙虎榜上榜原因 + 机构游资买卖
    5. 技术面 → 涨跌幅/换手率/量比/振幅
    
    每个结论绑定具体数据依据，区分"事实"与"推测"。
    """
    from datetime import datetime, timedelta
    
    attribution = {
        "code": code,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dimensions": {},
        "verdict": {},
    }
    
    market_code = 1 if code.startswith("6") else 0
    secid = f"{market_code}.{code}"
    
    # ━━━ 维度1: 资金面 ━━━
    today_flow = _fetch_today_fund_flow(code)
    if today_flow:
        inst_net = today_flow.get("super_large_net", 0)
        hm_net = today_flow.get("large_net", 0)
        retail_net = (today_flow.get("mid_net", 0) or 0) + (today_flow.get("small_net", 0) or 0)
        
        main_dir = "流入" if today_flow["main_net"] > 0 else "流出"
        
        attribution["dimensions"]["fund_flow"] = {
            "main_net_wan": round(today_flow["main_net"] / 1e4, 1),
            "direction": main_dir,
            "institution_net_wan": round(inst_net / 1e4, 1),
            "hot_money_net_wan": round(hm_net / 1e4, 1),
            "retail_net_wan": round(retail_net / 1e4, 1),
            "data_points": today_flow.get("minutes", 0),
            "source": f"push2 分钟级资金流 ({today_flow.get('minutes', 0)}个时间点)",
            "fact": f"主力净{main_dir} {abs(today_flow['main_net'])/1e4:.0f}万, "
                    f"机构(超大单)净{inst_net/1e4:.0f}万, "
                    f"游资(大单)净{hm_net/1e4:.0f}万, "
                    f"散户(中单+小单)净{retail_net/1e4:.0f}万",
        }
    
    # ━━━ 维度2: 板块面 ━━━
    # 获取个股所属概念板块
    try:
        blocks_data = _get_stock_concept_blocks(code)
        blocks_fund_flow = []
        for bk in blocks_data[:5]:  # 只分析前5个概念板块
            try:
                params = {
                    "pn": "1", "pz": "1", "po": "0", "np": "1",
                    "fltt": "2", "invt": "2",
                    "fs": f"b:{bk['code']}+f:!50",
                    "fields": "f2,f3,f62",
                }
                r = em_get(PUSH2_CLIST, params=params,
                           headers={"Referer": "https://data.eastmoney.com/"}, timeout=10)
                d = r.json()
                items = d.get("data", {}).get("diff", [])
                if items:
                    bk_flow = (items[0].get("f62") or 0) if isinstance(items, list) else 0
                    blocks_fund_flow.append({
                        "name": bk["name"],
                        "code": bk["code"],
                        "main_net_wan": round(bk_flow / 1e4, 1),
                        "direction": "流入" if bk_flow > 0 else "流出",
                    })
            except Exception:
                continue
        
        if blocks_fund_flow:
            inflow_blocks = [b for b in blocks_fund_flow if b["main_net_wan"] > 0]
            outflow_blocks = [b for b in blocks_fund_flow if b["main_net_wan"] < 0]
            attribution["dimensions"]["sector"] = {
                "blocks": blocks_fund_flow,
                "inflow_count": len(inflow_blocks),
                "outflow_count": len(outflow_blocks),
                "source": "东财 push2 概念板块资金流",
                "fact": f"所属{len(blocks_fund_flow)}个概念板块中, "
                        f"{len(inflow_blocks)}个流入/{len(outflow_blocks)}个流出",
            }
    except Exception:
        attribution["dimensions"]["sector"] = {"error": "板块数据获取失败"}
    
    # ━━━ 维度3: 消息面 ━━━
    try:
        news = _fetch_stock_news(code, days=7)
        if news:
            # 按日期分组，找今日新闻
            today_str = datetime.now().strftime("%Y-%m-%d")
            today_news = [n for n in news if n.get("time", "").startswith(today_str)]
            recent_news = news[:10]  # 近7日全部
            
            attribution["dimensions"]["news"] = {
                "today_count": len(today_news),
                "recent_count": len(news),
                "today_highlights": [
                    {"title": n["title"], "time": n["time"], "source": n["source"]}
                    for n in today_news[:5]
                ],
                "recent_highlights": [
                    {"title": n["title"], "time": n["time"], "source": n["source"]}
                    for n in recent_news[:5]
                ],
                "source": "东财个股新闻 (search-api-web)",
                "fact": f"近7日共{len(news)}条新闻, 今日{len(today_news)}条",
            }
    except Exception:
        attribution["dimensions"]["news"] = {"today_count": 0, "error": "新闻数据获取失败"}
    
    # ━━━ 维度4: 席位面(龙虎榜) ━━━
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        dt_data = eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f"(TRADE_DATE='{today_str}')(SECURITY_CODE='{code}')",
            page_size=5,
        )
        if dt_data:
            row = dt_data[0]
            attribution["dimensions"]["dragon_tiger"] = {
                "on_board": True,
                "reason": row.get("EXPLANATION", ""),
                "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 1e4, 1),
                "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
                "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
                "source": "东财龙虎榜 (RPT_DAILYBILLBOARD_DETAILSNEW)",
                "fact": f"今日上榜: {row.get('EXPLANATION', '')}, 净买{(row.get('BILLBOARD_NET_AMT') or 0)/1e4:.0f}万",
            }
            # 获取席位明细
            try:
                seat_analysis = dragon_tiger_seat_analysis(code, lookback_days=1)
                attribution["dimensions"]["dragon_tiger"]["seats"] = seat_analysis
            except Exception:
                pass
        else:
            attribution["dimensions"]["dragon_tiger"] = {
                "on_board": False,
                "fact": "今日未上龙虎榜",
            }
    except Exception:
        attribution["dimensions"]["dragon_tiger"] = {"on_board": False, "error": "龙虎榜数据获取失败"}
    
    # ━━━ 维度5: 技术面 ━━━
    try:
        from urllib.request import Request, urlopen
        prefixed = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
        url = f"https://qt.gtimg.cn/q={prefixed}"
        req = Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
        vals = data.split('"')[1].split("~") if '"' in data else []
        if len(vals) >= 53:
            change_pct = float(vals[32]) if vals[32] else 0
            turnover = float(vals[38]) if vals[38] else 0
            vol_ratio = float(vals[49]) if vals[49] else 0
            amplitude = float(vals[43]) if vals[43] else 0
            price = float(vals[3]) if vals[3] else 0
            attribution["dimensions"]["technical"] = {
                "price": price,
                "change_pct": change_pct,
                "turnover_pct": turnover,
                "vol_ratio": vol_ratio,
                "amplitude_pct": amplitude,
                "source": "腾讯财经行情 (qt.gtimg.cn)",
                "fact": f"涨跌{change_pct:+.2f}% 换手{turnover}% 量比{vol_ratio} 振幅{amplitude}%",
            }
    except Exception:
        attribution["dimensions"]["technical"] = {"error": "行情数据获取失败"}
    
    # ━━━ 综合归因判断 ━━━
    attribution["verdict"] = _generate_attribution_verdict(attribution["dimensions"])
    
    return attribution


def _get_stock_concept_blocks(code: str) -> list[dict]:
    """获取个股所属概念板块（复用 a-stock-data §3.3 逻辑）"""
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3", "pi": "0", "pz": "200", "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/slist/get",
                   params=params, headers=headers, timeout=10)
        d = r.json()
        diff = (d.get("data") or {}).get("diff") or {}
        items = diff.values() if isinstance(diff, dict) else diff
        return [
            {"code": it.get("f12", ""), "name": it.get("f14", ""),
             "change_pct": it.get("f3", 0), "leader": it.get("f128", "")}
            for it in items
        ]
    except Exception:
        return []


def _fetch_stock_news(code: str, days: int = 7) -> list[dict]:
    """获取个股近期新闻"""
    import json as _json, re as _re
    cb = "jQuery_news"
    inner = _json.dumps({
        "uid": "", "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {
            "searchScope": "default", "sort": "default",
            "pageIndex": 1, "pageSize": 20, "preTag": "", "postTag": "",
        }},
    }, separators=(',', ':'))
    params = {"cb": cb, "param": inner}
    headers = {"Referer": "https://so.eastmoney.com/"}
    try:
        r = em_get("https://search-api-web.eastmoney.com/search/jsonp",
                   params=params, headers=headers, timeout=10)
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = _json.loads(json_str)
        articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
        news = []
        for a in articles:
            news.append({
                "title": _re.sub(r'<[^>]+>', '', a.get("title", "")),
                "content": _re.sub(r'<[^>]+>', '', a.get("content", ""))[:200],
                "time": a.get("date", ""),
                "source": a.get("mediaName", ""),
                "url": a.get("url", ""),
            })
        return news
    except Exception:
        return []


def _generate_attribution_verdict(dims: dict) -> dict:
    """
    综合五维度数据，生成归因结论。
    
    归因规则（按优先级）:
    1. 龙虎榜上榜 + 机构大额买入 → 机构主导行情
    2. 消息面有明确催化 + 主力同向流入 → 消息驱动行情
    3. 板块资金流同向 + 个股跟涨/跟跌 → 板块联动行情
    4. 主力vs散户反向 → 筹码转移（机构吸筹或派发）
    5. 无明确主因 → 多因素交织
    """
    verdict = {
        "primary_cause": "",
        "confidence": "",  # 高/中/低
        "supporting_evidence": [],
        "counter_evidence": [],  # 反方证据
        "uncertainties": [],
    }
    
    fund = dims.get("fund_flow", {})
    sector = dims.get("sector", {})
    news = dims.get("news", {})
    dt = dims.get("dragon_tiger", {})
    tech = dims.get("technical", {})
    
    change_pct = tech.get("change_pct", 0)
    direction = "涨" if change_pct > 0 else "跌"
    
    causes = []
    
    # Rule 1: 龙虎榜驱动
    if dt.get("on_board"):
        net_buy = dt.get("net_buy_wan", 0)
        reason = dt.get("reason", "")
        if net_buy > 5000 and change_pct > 5:
            causes.append({
                "cause": f"龙虎榜机构大额买入驱动{direction}停",
                "confidence": "高",
                "evidence": f"龙虎榜净买入{net_buy:.0f}万, 上榜原因: {reason}",
                "source": "东财龙虎榜 (一级来源)",
            })
        elif abs(net_buy) > 1000:
            causes.append({
                "cause": f"龙虎榜资金博弈驱动波动",
                "confidence": "中",
                "evidence": f"龙虎榜净买卖{net_buy:.0f}万",
                "source": "东财龙虎榜 (一级来源)",
            })
    
    # Rule 2: 消息面驱动
    if news.get("today_count", 0) > 0:
        highlights = news.get("today_highlights", [])
        if highlights:
            causes.append({
                "cause": f"消息面催化: {highlights[0]['title'][:60]}",
                "confidence": "中",
                "evidence": f"今日{news['today_count']}条新闻, 来源: {highlights[0]['source']}",
                "source": "东财个股新闻 (二级来源, 需交叉验证)",
            })
    
    # Rule 3: 主力资金方向
    if fund:
        main_dir = fund.get("direction", "")
        inst_net = fund.get("institution_net_wan", 0)
        hm_net = fund.get("hot_money_net_wan", 0)
        retail_net = fund.get("retail_net_wan", 0)
        
        if abs(inst_net) > abs(hm_net) and abs(inst_net) > abs(retail_net):
            causes.append({
                "cause": f"机构资金主导{direction}势",
                "confidence": "中",
                "evidence": f"机构(超大单)净{inst_net:.0f}万, 游资净{hm_net:.0f}万, 散户净{retail_net:.0f}万",
                "source": "push2 分钟级资金流 (二级来源)",
            })
        elif abs(hm_net) > abs(inst_net) and abs(hm_net) > abs(retail_net):
            causes.append({
                "cause": f"游资主导炒作{direction}势",
                "confidence": "中",
                "evidence": f"游资(大单)净{hm_net:.0f}万, 机构净{inst_net:.0f}万",
                "source": "push2 分钟级资金流 (二级来源)",
            })
        
        # 机构vs散户反向
        if inst_net > 0 and retail_net < 0:
            causes.append({
                "cause": "机构吸筹中, 散户恐慌出局",
                "confidence": "中",
                "evidence": f"机构净流入{inst_net:.0f}万 vs 散户净流出{abs(retail_net):.0f}万, 筹码从散户向机构转移",
                "source": "push2 分钟级资金流",
            })
        elif inst_net < 0 and retail_net > 0:
            causes.append({
                "cause": "机构派发中, 散户接盘",
                "confidence": "中",
                "evidence": f"机构净流出{abs(inst_net):.0f}万 vs 散户净流入{retail_net:.0f}万, 筹码从机构向散户转移",
                "source": "push2 分钟级资金流",
            })
    
    # Rule 4: 板块联动
    if sector and "blocks" in sector:
        blocks = sector.get("blocks", [])
        if blocks:
            same_dir = [b for b in blocks 
                       if (b["direction"] == "流入" and change_pct > 0) or 
                          (b["direction"] == "流出" and change_pct < 0)]
            if len(same_dir) >= len(blocks) * 0.6:  # 60%+板块同向
                causes.append({
                    "cause": f"板块联动效应: {len(same_dir)}/{len(blocks)}个概念板块同向",
                    "confidence": "中",
                    "evidence": f"所属板块: {', '.join(b['name'] for b in same_dir[:3])}同向",
                    "source": "东财 push2 概念板块资金流",
                })
    
    # 整理结论
    if causes:
        # 取置信度最高的为主因
        high_conf = [c for c in causes if c["confidence"] == "高"]
        if high_conf:
            main = high_conf[0]
        else:
            main = causes[0]
        
        verdict["primary_cause"] = main["cause"]
        verdict["confidence"] = main["confidence"]
        verdict["supporting_evidence"] = [
            {"dimension": c["cause"], "fact": c["evidence"], "source": c["source"]}
            for c in causes
        ]
    else:
        verdict["primary_cause"] = f"多因素交织, 无单一明确主因, 建议持续跟踪"
        verdict["confidence"] = "低"
        verdict["uncertainties"].append("五维度中无显著信号, 可能为正常市场波动")
    
    # 添加反方证据
    if fund and sector and "blocks" in sector:
        blocks = sector.get("blocks", [])
        main_dir = fund.get("direction", "")
        rev_blocks = [b for b in blocks if b["direction"] != ("流入" if change_pct > 0 else "流出")]
        if rev_blocks:
            verdict["counter_evidence"].append(
                f"反方: 所属板块中 {len(rev_blocks)}个板块反向: "
                f"{', '.join(b['name'] for b in rev_blocks[:3])}"
            )
    
    # 标注不确定因素
    if not dt.get("on_board"):
        verdict["uncertainties"].append("未上龙虎榜, 席位级别数据缺失, 无法确认具体机构/游资操作")
    if not news.get("today_count", 0):
        verdict["uncertainties"].append("今日无明确消息催化, 可能为纯技术面或资金面驱动")
    
    return verdict
```

### 6.3 归因分析输出示例

```python
def print_attribution_report(attribution: dict):
    """打印个股归因分析报告"""
    dims = attribution["dimensions"]
    verdict = attribution["verdict"]
    code = attribution["code"]
    
    print(f"\n{'=' * 70}")
    print(f"  📊 个股走势归因分析: {code}")
    print(f"  分析时间: {attribution['analysis_time']}")
    print(f"{'=' * 70}")
    
    # 五维度数据
    for dim_key, dim_label in [
        ("fund_flow", "💰 资金面"),
        ("sector", "🏭 板块面"),
        ("news", "📰 消息面"),
        ("dragon_tiger", "🐉 席位面"),
        ("technical", "📈 技术面"),
    ]:
        dim = dims.get(dim_key, {})
        print(f"\n  {dim_label}")
        print(f"  {'─' * 50}")
        if dim.get("error"):
            print(f"    ⚠️ 数据获取失败: {dim['error']}")
        elif dim.get("fact"):
            print(f"    📌 {dim['fact']}")
            print(f"    📎 来源: {dim.get('source', '未知')}")
            # 额外细节
            if dim_key == "fund_flow":
                print(f"       机构(超大单): {dim.get('institution_net_wan', 0):.0f}万")
                print(f"       游资(大单):   {dim.get('hot_money_net_wan', 0):.0f}万")
                print(f"       散户(中+小):  {dim.get('retail_net_wan', 0):.0f}万")
            elif dim_key == "news" and dim.get("today_highlights"):
                for n in dim["today_highlights"][:3]:
                    print(f"       📰 {n['time']} | {n['source']} | {n['title'][:50]}")
            elif dim_key == "dragon_tiger" and dim.get("on_board"):
                print(f"       上榜原因: {dim.get('reason', '')}")
                print(f"       龙虎榜净买: {dim.get('net_buy_wan', 0):.0f}万")
    
    # 综合归因结论
    print(f"\n{'=' * 70}")
    print(f"  🎯 归因结论")
    print(f"{'=' * 70}")
    print(f"  主因: {verdict['primary_cause']}")
    print(f"  置信度: {verdict['confidence']}")
    
    print(f"\n  ✅ 支撑证据 ({len(verdict['supporting_evidence'])}条):")
    for i, ev in enumerate(verdict["supporting_evidence"]):
        print(f"    {i+1}. [{ev['dimension']}] {ev['fact']}")
        print(f"       来源: {ev['source']}")
    
    if verdict.get("counter_evidence"):
        print(f"\n  ⚠️ 反方证据 ({len(verdict['counter_evidence'])}条):")
        for ev in verdict["counter_evidence"]:
            print(f"    • {ev}")
    
    if verdict.get("uncertainties"):
        print(f"\n  ❓ 不确定因素 ({len(verdict['uncertainties'])}条):")
        for u in verdict["uncertainties"]:
            print(f"    • {u}")
    
    print(f"\n{'─' * 70}")
    print(f"  ⚠️ 研究声明: 以上分析基于公开数据。'主因'为多维度交叉验证后的")
    print(f"     最大概率推断，不构成投资建议。行情受多重因素影响，")
    print(f"     单一归因无法覆盖所有可能。")
    print(f"{'─' * 70}")


# 用法
# attr = stock_daily_attribution("300339")
# print_attribution_report(attr)
```

---

## Layer 7: 增强版全景报告（含归因分析）

```python
def enhanced_capital_flow_report(
    top_sectors: int = 10,
    analyze_top_stocks: int = 5,
    include_attribution: bool = True,
) -> dict:
    """
    增强版资金流向全景报告。
    在 Layer 5 基础上增加：
    - 三方资金分类（机构/游资/散户）
    - 重点个股归因分析（为什么涨/跌）
    """
    report = capital_flow_report(top_sectors=top_sectors, seats_top_n=analyze_top_stocks)
    
    # 对龙虎榜前5个股做归因分析
    if include_attribution:
        print("\n[扩展] 个股归因分析...")
        report["attributions"] = {}
        top_codes = [s["code"] for s in report["dragon_tiger"]["stocks"][:analyze_top_stocks]]
        for i, code in enumerate(top_codes):
            print(f"  [{i+1}/{len(top_codes)}] 分析 {code} 走势归因...")
            try:
                report["attributions"][code] = stock_daily_attribution(code)
            except Exception as e:
                report["attributions"][code] = {"error": str(e)}
    
    return report
```

---

## 快速参考

### 输出目录

分析报告统一输出到 `src/资金流向/` 下，按 `YYYY-MM-DD-主题/` 格式组织：

```bash
# 示例：生成报告时自动创建目录
mkdir -p src/资金流向/$(date +%Y-%m-%d)-资金流向扫描/
```

目录结构：
```
src/资金流向/
├── _index.md                              # 导航索引
└── YYYY-MM-DD-资金流向全景扫描/
    ├── report.md                          # 资金流向全景报告
    ├── sector-detail.md                   # 重点板块个股明细
    └── attribution/                       # 个股归因分析
        ├── {code}-{name}-归因分析.md
        └── ...
```

### 常用调用组合

| 场景 | 调用链 |
|------|--------|
| 今日哪些概念板块在涨？ | `concept_sector_fund_flow()` → 看 top_sectors |
| 半导体板块哪些个股在流入？ | `find_concept_code('半导体')` → `sector_stock_fund_flow(bk_code)` |
| 某只股票主力在进还是出？ | `stock_multiperiod_fund_flow(code, ['today','1w','1m'])` |
| 机构在买什么？ | `daily_dragon_tiger_scan(min_net_buy_wan=5000)` → 逐个分析 |
| 某只股票机构和游资持仓？ | `dragon_tiger_seat_analysis(code)` → 看 net_total |
| 完整扫描 | `capital_flow_report()` → 全景报告 |

### 字段速查

**概念板块 (f62/f66/f72/f78/f84):**
| 字段 | 含义 | 单位 |
|------|------|------|
| f62 | 主力净流入 = 超大单+大单 | 元 |
| f66 | 超大单净流入 (≥100万手) | 元 |
| f72 | 大单净流入 (≥20万手) | 元 |
| f78 | 中单净流入 (≥4万手) | 元 |
| f84 | 小单净流入 (<4万手) | 元 |

**龙虎榜席位分类:**
| 席位代码 | 类型 | 特征 |
|----------|------|------|
| OPERATEDEPT_CODE = "0" | 机构专用席位 | 基金/保险/券商自营等 |
| 其他 | 营业部席位(游资) | 券商营业部，游资活跃 |

### 常见概念板块 BK 码速查

（以下为 2026-06 实测码，东财可能调整，建议用 `find_concept_code()` 动态查找）

| 概念 | BK 码 | 概念 | BK 码 |
|------|-------|------|-------|
| 半导体概念 | BK1036 | CPO概念 | BK1185 |
| 芯片概念 | BK0873 | 液冷概念 | BK1151 |
| 小金属 | BK0643 | 电子纸概念 | BK1160 |
| 人形机器人 | BK1176 | 存储芯片 | BK1137 |
| 先进封装 | BK1168 | 光刻机(胶) | BK0888 |
| 算力概念 | BK1134 | HBM | BK1180 |

---

## 常见问题

### Q: 为什么 push2his 只有 ~120 天数据？
A: push2his 接口设计的最大返回值是 120 个交易日。半年以内的周期完全覆盖，1 年周期只能覆盖约 6 个月。

### Q: 如何区分机构和游资？
A: 龙虎榜中 `OPERATEDEPT_CODE == "0"` 的席位是**机构专用席位**（基金/保险/券商自营等）。非 0 的席位是**券商营业部**，一般归为游资。

### Q: "还剩多少"是什么意思？
A: 龙虎榜席位买入金额 - 卖出金额 = **净持仓**。这个净额就是该席位在该股票上的当前持仓头寸（基于公开披露数据估算）。

### Q: 批量拉取为什么慢？
A: 板块内个股逐个拉历史资金流，每只约需 1.5-2 秒（含限流）。100 只个股约需 3-4 分钟。建议：先用板块级 API（1 次请求）快速扫描，只在深度分析时拉取个股历史。

### Q: 东财 API 被限流怎么办？
A: 已内置 `em_get()` 限流（≥1.5s 间隔 + 随机抖动）。如果仍然被封：调大 `EM_MIN_INTERVAL` 到 2.0-3.0，或换网络环境。

---

## 风险声明

- 资金流向数据基于东方财富公开 API，数据延迟通常 3-5 秒
- 龙虎榜席位数据仅覆盖触发龙虎榜的交易日（涨跌停/振幅异常/换手异常），非日常全覆盖
- "游资"和"机构"的区分基于龙虎榜席位代码，可能不完全准确（部分机构也可能使用营业部席位）
- 所有数据仅供参考，不构成投资建议