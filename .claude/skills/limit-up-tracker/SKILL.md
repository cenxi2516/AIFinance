---
name: limit-up-tracker
description: A股涨停板全维度追踪 — 覆盖今日/昨日/前天涨停股票，分析涨停时间、炸板次数、封板金额、连板数、所属行业与概念、行业/概念涨停数排名，支持多日趋势对比与板块轮动研判。适用于涨停板复盘、热点题材追踪、连板情绪监控、板块涨停潮识别、炸板率分析。
version: 1.0.1
updated: 2026-07-02
---

# A股涨停板追踪器 V1.0.1

全维度涨停板分析工具——覆盖 4 个市场（主板/创业板/科创板/北交所），支持 3 日回溯（今日/昨日/前天），逐股分析涨停时间、炸板次数、封板金额、连板数，自动归类行业与概念并统计板块涨停数排名，输出多日趋势对比。

> **2026-07-02 重要更新：东财 push2ex 已失效，新增腾讯+通达信备用方案。**
> 详见下方「API 状态追踪」

## ⚠️ API 状态追踪 (2026-07-02)

| API | 状态 | 返回 | 说明 |
|-----|------|------|------|
| `push2ex.eastmoney.com/getTopicZTPool` | ❌ 失效 | rc=102 data=null | 06-17 至 07-02 全部日期返回空 |
| `push2.eastmoney.com/api/qt/clist/get` | ⚠️ 间歇风控 | 连接重置 | 住宅IP被限(与 a-stock-data 记载一致) |
| `web.sqt.gtimg.cn` (腾讯) | ✅ 正常 | 200 | 批量50只/次，不封IP |
| mootdx TCP:7709 (通达信) | ✅ 正常 | 数据正常 | TCP协议无风控 |

**当前可用方案**：mootdx 获取股票列表 → 腾讯 API 批量获取行情 → 涨幅≥9.5%筛选涨停。

**备用方案的局限**：缺少涨停时间、炸板次数、封单金额、连板数、行业/概念分类。这些字段需东财 API 或替代数据源补充。

## When to Activate

- 用户要看**今日涨停板**（哪些股票涨停了）
- 用户要分析**涨停板质量**（涨停时间、炸板次数、封板金额）
- 用户要看**板块涨停潮**（哪个行业/概念涨停股最多）
- 用户要**连板情绪监控**（2连板/3连板/高连板分布）
- 用户要**多日趋势对比**（涨停数增减、板块轮动方向）
- 用户要**炸板率分析**（哪些股票炸板多、哪些板块炸板率高）
- 用户要做**涨停板复盘**（今日涨停回顾 + 前日对比）
- 关键词：`涨停`、`涨停板`、`炸板`、`封板`、`连板`、`涨停潮`、`涨停复盘`、`打板`、`题材热点`、`板块涨停`、`首板`、`二板`、`高标`

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

## Layer 1: 涨停池数据获取

### 1.1 核心函数：单日全市场涨停扫描

```python
PUSH2EX_URL = "https://push2ex.eastmoney.com/getTopicZTPool"

# 东财 push2ex 返回的原始字段映射（按 data.pool 数组内的位置索引）
# 字段较多，以下标注关键字段：
#   0:  股票代码      1:  股票名称      2:  涨跌幅%
#   3:  最新价        4:  涨停价        5:  成交额(元)
#   6:  换手率%       7:  量比          8:  流通市值(元)
#   9:  总市值(元)    10: 动态PE       11:  涨停时间(HHMMSS)
#  12:  炸板次数      13:  封单金额(元) 14:  封单量(手)
#  15:  最大封单额(元) 16: 最大封单量(手) 17: 连板数
#  18:  首次涨停时间  19:  最后涨停时间  20: 最终涨停时间
#  21:  开盘是否涨停  22:  行业板块      23: 行业板块代码
#  24:  概念板块（|分隔） 25: 概念板块代码（|分隔）
#  26:  所属行业涨停数  27: 所属概念涨停数 28: 连续涨停天数说明
#
# ⚠️ 注意：字段索引可能随东财版本调整，以下代码以 f_xxx 参数名方式传 fields，更稳健

def fetch_limit_up_pool(date: str = None, market_filter: str = None) -> dict:
    """
    获取指定日期的涨停池数据。
    
    Args:
        date: 日期字符串 YYYYMMDD，默认今天
        market_filter: 市场过滤，如 'm:0+t:6'=主板。默认 None=全市场
        
    Returns:
        {
            date: str,
            total: int,           # 涨停总数
            stocks: [{code, name, change_pct, price, limit_price,
                      first_time, last_time, final_time,    # 涨停时间
                      reopen_count,                          # 炸板次数
                      seal_amount, max_seal_amount,          # 封单金额
                      consecutive_days,                      # 连板数
                      turnover_pct, volume_ratio,            # 换手/量比
                      float_mcap, total_mcap,                # 市值
                      industry_name, industry_code,          # 行业
                      concepts: [{name, code}],              # 概念列表
                      }],
            by_market: {market_name: count, ...},
            by_consecutive: {1: count, 2: count, 3: count, '4+': count},
        }
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    
    # 全市场拉取（不传 fs 参数，或分别拉取各市场后合并）
    all_stocks = []
    by_market = {}
    by_consecutive = {"1": 0, "2": 0, "3": 0, "4+": 0}
    
    # 按市场分别拉取（东财涨停池一次只能拉一个市场板块）
    markets = [
        ("主板", "m:0+t:6+f:!50"),
        ("创业板", "m:0+t:7"),
        ("科创板", "m:0+t:80"),
        ("北交所", "m:0+t:81"),
    ]
    
    headers = {"Referer": "https://data.eastmoney.com/"}
    
    for market_name, fs in markets:
        try:
            params = {
                "ut": "7eea3edcaed734bea9c4b5c9e1a5e8a3",
                "Sort": "fbt",
                "fdate": date,
                "fs": fs,
                "fields": "f12,f14,f2,f3,f20,f21,f8,f10,f9,f62,f184,f66,f72,f78,f84",
            }
            r = em_get(PUSH2EX_URL, params=params, headers=headers, timeout=15)
            d = r.json()
            
            pool = d.get("data", {}).get("pool", []) or []
            by_market[market_name] = len(pool)
            
            for item in pool:
                # push2ex 返回的是数组格式，按位置解析
                # 备选：也支持对象格式
                if isinstance(item, dict):
                    code = item.get("c") or item.get("f12", "")
                    name = item.get("n") or item.get("f14", "")
                    change_pct = float(item.get("zdp", item.get("f3", 0)))
                    price = float(item.get("p", item.get("f2", 0)))
                    limit_price = float(item.get("ztp", 0) or 0)
                    first_time = str(item.get("fbt", item.get("t", "")))
                    last_time = str(item.get("lbt", ""))
                    reopen_count = int(item.get("reopen", item.get("f184", 0) or 0))
                    seal_amount = float(item.get("amount", 0) or 0)
                    max_seal_amount = float(item.get("max_amount", 0) or 0)
                    consecutive_days = int(item.get("days", 1) or 1)
                    turnover_pct = float(item.get("hs", item.get("f8", 0)) or 0)
                    volume_ratio = float(item.get("lb", item.get("f10", 0)) or 0)
                    float_mcap = float(item.get("ltz", item.get("f21", 0)) or 0)
                    total_mcap = float(item.get("zsz", item.get("f20", 0)) or 0)
                    industry_name = item.get("hybk", item.get("hy", ""))
                    industry_code = item.get("hycode", "")
                    concept_str = item.get("gnbk", item.get("gn", ""))
                    concept_codes_str = item.get("gncode", "")
                elif isinstance(item, list):
                    # 数组格式：按字段位置解析
                    code = str(item[0]) if len(item) > 0 else ""
                    name = str(item[1]) if len(item) > 1 else ""
                    change_pct = float(item[2] or 0) if len(item) > 2 else 0
                    price = float(item[3] or 0) if len(item) > 3 else 0
                    limit_price = float(item[4] or 0) if len(item) > 4 else 0
                    first_time = str(item[11] or "") if len(item) > 11 else ""
                    reopen_count = int(item[12] or 0) if len(item) > 12 else 0
                    seal_amount = float(item[13] or 0) if len(item) > 13 else 0
                    max_seal_amount = float(item[15] or 0) if len(item) > 15 else 0
                    consecutive_days = int(item[17] or 1) if len(item) > 17 else 1
                    last_time = str(item[19] or "") if len(item) > 19 else ""
                    final_time = str(item[20] or "") if len(item) > 20 else ""
                    turnover_pct = float(item[6] or 0) if len(item) > 6 else 0
                    volume_ratio = float(item[7] or 0) if len(item) > 7 else 0
                    float_mcap = float(item[8] or 0) if len(item) > 8 else 0
                    total_mcap = float(item[9] or 0) if len(item) > 9 else 0
                    industry_name = str(item[22] or "") if len(item) > 22 else ""
                    industry_code = str(item[23] or "") if len(item) > 23 else ""
                    concept_str = str(item[24] or "") if len(item) > 24 else ""
                    concept_codes_str = str(item[25] or "") if len(item) > 25 else ""
                else:
                    continue
                
                # 解析概念列表
                concepts = []
                if concept_str:
                    concept_names = concept_str.split("|") if "|" in concept_str else [concept_str]
                    concept_codes = concept_codes_str.split("|") if concept_codes_str and "|" in concept_codes_str else ([concept_codes_str] if concept_codes_str else [])
                    for i, cn in enumerate(concept_names):
                        cc = concept_codes[i] if i < len(concept_codes) else ""
                        concepts.append({"name": cn.strip(), "code": cc.strip()})
                
                # 涨停时间格式化
                first_time_fmt = _fmt_time(first_time)
                last_time_fmt = _fmt_time(last_time) if last_time else None
                
                # 连板统计
                if consecutive_days >= 4:
                    by_consecutive["4+"] += 1
                else:
                    key = str(consecutive_days)
                    if key in by_consecutive:
                        by_consecutive[key] += 1
                
                all_stocks.append({
                    "code": code,
                    "name": name,
                    "change_pct": change_pct,
                    "price": price,
                    "limit_price": limit_price,
                    "first_time": first_time_fmt,         # 首次涨停时间
                    "last_time": last_time_fmt,            # 最后涨停时间
                    "reopen_count": reopen_count,          # 炸板次数（0=未炸板）
                    "seal_amount": seal_amount,            # 封单金额(元)
                    "max_seal_amount": max_seal_amount,    # 最大封单金额(元)
                    "consecutive_days": consecutive_days,  # 连板天数
                    "turnover_pct": turnover_pct,          # 换手率%
                    "volume_ratio": volume_ratio,          # 量比
                    "float_mcap": float_mcap,              # 流通市值(元)
                    "total_mcap": total_mcap,              # 总市值(元)
                    "industry_name": industry_name,
                    "industry_code": industry_code,
                    "concepts": concepts,
                    "market": market_name,
                })
        except Exception as e:
            by_market[market_name] = f"ERR: {e}"
            continue
    
    return {
        "date": date,
        "total": len(all_stocks),
        "stocks": all_stocks,
        "by_market": by_market,
        "by_consecutive": by_consecutive,
    }


def _fmt_time(t: str) -> str:
    """格式化涨停时间: '093625' → '09:36:25'"""
    t = str(t).strip()
    if len(t) == 6 and t.isdigit():
        return f"{t[:2]}:{t[2:4]}:{t[4:6]}"
    if len(t) == 5 and t.isdigit():
        return f"{t[:1]}:{t[1:3]}:{t[3:5]}"
    return t if t else ""


# ━━━ 用法示例 ━━━
today_data = fetch_limit_up_pool()  # 默认今天
print(f"今日涨停: {today_data['total']} 只")
print(f"  主板: {today_data['by_market'].get('主板', 0)}")
print(f"  创业板: {today_data['by_market'].get('创业板', 0)}")
print(f"  科创板: {today_data['by_market'].get('科创板', 0)}")
print(f"  连板分布: {today_data['by_consecutive']}")
```

### 1.2 三日数据批量拉取

```python
def fetch_limit_up_3days() -> dict:
    """
    拉取今日、昨日、前日三天的涨停数据。
    
    Returns:
        {date_str: pool_data, ...}  键为 YYYYMMDD
    """
    from datetime import datetime, timedelta
    
    dates = []
    today = datetime.now()
    for offset in [0, 1, 2]:
        d = today - timedelta(days=offset)
        dates.append(d.strftime("%Y%m%d"))
    
    result = {}
    for d in dates:
        print(f"  拉取 {d} ...")
        result[d] = fetch_limit_up_pool(date=d)
    
    return result


# 用法
data_3day = fetch_limit_up_3days()
for date_key, data in data_3day.items():
    print(f"\n{date_key}: 涨停={data['total']}只  "
          f"首板={data['by_consecutive'].get('1',0)} "
          f"2连板={data['by_consecutive'].get('2',0)} "
          f"3连板={data['by_consecutive'].get('3',0)} "
          f"高标={data['by_consecutive'].get('4+',0)}")
```

---

## Layer 2: 行业与概念聚合分析

### 2.1 行业涨停数排名

```python
def industry_limit_up_ranking(pool_data: dict, top_n: int = 20) -> dict:
    """
    统计各行业的涨停股票数量排名。
    
    Returns:
        {ranking: [{industry_name, industry_code, count, stocks: [...], 
                    avg_seal_money, avg_consecutive, reopen_rate}],
         total_industries: int}
    """
    from collections import defaultdict
    
    industry_map = defaultdict(list)
    
    for stock in pool_data["stocks"]:
        ind_name = stock.get("industry_name", "")
        if ind_name:
            industry_map[ind_name].append(stock)
    
    ranking = []
    for ind_name, stocks in industry_map.items():
        count = len(stocks)
        avg_seal = sum(s["seal_amount"] for s in stocks) / count if count > 0 else 0
        avg_days = sum(s["consecutive_days"] for s in stocks) / count if count > 0 else 0
        reopen_total = sum(1 for s in stocks if s["reopen_count"] > 0)
        reopen_rate = reopen_total / count * 100 if count > 0 else 0
        
        ranking.append({
            "industry_name": ind_name,
            "industry_code": stocks[0].get("industry_code", ""),
            "count": count,
            "stocks": sorted(stocks, key=lambda x: x["consecutive_days"], reverse=True),
            "avg_seal_amount": avg_seal,
            "avg_consecutive_days": round(avg_days, 1),
            "reopen_rate_pct": round(reopen_rate, 1),
        })
    
    # 按涨停数降序排列
    ranking.sort(key=lambda x: x["count"], reverse=True)
    
    return {
        "date": pool_data["date"],
        "total_industries": len(ranking),
        "ranking": ranking[:top_n],
    }


# 用法
ind_rank = industry_limit_up_ranking(today_data)
print(f"\n🏭 行业涨停数排名 TOP 15:")
for i, ind in enumerate(ind_rank["ranking"][:15]):
    bar = "█" * min(ind["count"], 20)
    print(f"  {i+1:2d}. {ind['industry_name']:<12s} {bar} {ind['count']}只  "
          f"均封单={ind['avg_seal_amount']/1e8:.1f}亿  "
          f"均连板={ind['avg_consecutive_days']}天  "
          f"炸板率={ind['reopen_rate_pct']:.0f}%")
```

### 2.2 概念涨停数排名

```python
def concept_limit_up_ranking(pool_data: dict, top_n: int = 30) -> dict:
    """
    统计各概念的涨停股票数量排名（一只股票可属于多个概念）。
    
    Returns:
        {ranking: [{concept_name, concept_code, count, stocks: [...]}],
         total_concepts: int}
    """
    from collections import defaultdict
    
    concept_map = defaultdict(list)
    
    for stock in pool_data["stocks"]:
        for concept in stock.get("concepts", []):
            cn = concept.get("name", "")
            if cn:
                concept_map[cn].append(stock)
    
    ranking = []
    for cn_name, stocks in concept_map.items():
        count = len(stocks)
        avg_seal = sum(s["seal_amount"] for s in stocks) / count if count > 0 else 0
        reopen_total = sum(1 for s in stocks if s["reopen_count"] > 0)
        reopen_rate = reopen_total / count * 100 if count > 0 else 0
        
        ranking.append({
            "concept_name": cn_name,
            "concept_code": stocks[0].get("concepts", [{}])[0].get("code", "") if stocks[0].get("concepts") else "",
            "count": count,
            "stocks": sorted(stocks, key=lambda x: x["consecutive_days"], reverse=True),
            "avg_seal_amount": avg_seal,
            "reopen_rate_pct": round(reopen_rate, 1),
        })
    
    ranking.sort(key=lambda x: x["count"], reverse=True)
    
    return {
        "date": pool_data["date"],
        "total_concepts": len(ranking),
        "ranking": ranking[:top_n],
    }


# 用法
concept_rank = concept_limit_up_ranking(today_data)
print(f"\n🔥 概念涨停数排名 TOP 20:")
for i, c in enumerate(concept_rank["ranking"][:20]):
    bar = "█" * min(c["count"], 15)
    print(f"  {i+1:2d}. {c['concept_name']:<14s} {bar} {c['count']}只  "
          f"均封单={c['avg_seal_amount']/1e8:.1f}亿")
```

---

## Layer 3: 涨停质量分析

### 3.1 涨停时间分布（判断强弱）

涨停时间的早晚是市场对这只股票认可度的重要信号：
- **早盘秒板（09:25-09:35）**：隔夜情绪发酵充分，最强信号
- **早盘板（09:35-10:30）**：主力资金明确做多，较强信号
- **午前板（10:30-11:30）**：有一定资金认可，中等信号
- **午后板（13:00-14:30）**：资金分歧较大，一般信号
- **尾盘偷袭板（14:30-15:00）**：资金信心不足，最弱信号（需警惕次日低开）

```python
def time_distribution_analysis(pool_data: dict) -> dict:
    """
    涨停时间分布分析——按时间段统计涨停股票数量和分布。
    """
    time_slots = {
        "竞价秒板(09:25)": [],
        "早盘强板(09:25-09:35)": [],
        "早盘板(09:35-10:30)": [],
        "午前板(10:30-11:30)": [],
        "午后板(13:00-14:30)": [],
        "尾盘偷袭(14:30-15:00)": [],
        "时间未知": [],
    }
    
    for stock in pool_data["stocks"]:
        ft = stock.get("first_time", "")
        if not ft:
            time_slots["时间未知"].append(stock)
            continue
        
        try:
            h, m, s = ft.split(":")
            minutes = int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            time_slots["时间未知"].append(stock)
            continue
        
        if minutes <= 9 * 60 + 25:
            time_slots["竞价秒板(09:25)"].append(stock)
        elif minutes <= 9 * 60 + 35:
            time_slots["早盘强板(09:25-09:35)"].append(stock)
        elif minutes <= 10 * 60 + 30:
            time_slots["早盘板(09:35-10:30)"].append(stock)
        elif minutes <= 11 * 60 + 30:
            time_slots["午前板(10:30-11:30)"].append(stock)
        elif minutes <= 14 * 60 + 30:
            time_slots["午后板(13:00-14:30)"].append(stock)
        else:
            time_slots["尾盘偷袭(14:30-15:00)"].append(stock)
    
    result = {}
    for slot_name, stocks in time_slots.items():
        if slot_name == "时间未知":
            continue
        count = len(stocks)
        pct = count / max(pool_data["total"], 1) * 100
        had_reopen = sum(1 for s in stocks if s["reopen_count"] > 0)
        reopen_rate = had_reopen / max(count, 1) * 100
        
        result[slot_name] = {
            "count": count,
            "pct": round(pct, 1),
            "reopen_count": had_reopen,
            "reopen_rate_pct": round(reopen_rate, 1),
            "stocks": stocks[:10],  # 只保留前 10 只代表性股票
        }
    
    return {
        "date": pool_data["date"],
        "total": pool_data["total"],
        "distribution": result,
        "unknown_count": len(time_slots["时间未知"]),
    }


# 用法
time_dist = time_distribution_analysis(today_data)
print(f"\n⏰ 涨停时间分布:")
print(f"{'时间段':<25s} {'数量':>4s}  {'占比':>6s}  {'炸板数':>5s}  {'炸板率':>6s}")
print(f"{'─' * 55}")
for slot_name, info in time_dist["distribution"].items():
    print(f"  {slot_name:<23s} {info['count']:>4d}  {info['pct']:>5.1f}%  "
          f"{info['reopen_count']:>5d}  {info['reopen_rate_pct']:>5.1f}%")
```

### 3.2 炸板分析

```python
def reopen_analysis(pool_data: dict) -> dict:
    """
    炸板专项分析——哪些股票炸板最多、炸板集中在哪些板块。
    
    Returns:
        {total_reopened, reopen_rate_pct, most_reopened: [...],
         reopen_by_industry: [...], reopen_by_concept: [...]}
    """
    # 1. 炸板个股
    reopened_stocks = [s for s in pool_data["stocks"] if s["reopen_count"] > 0]
    reopened_stocks.sort(key=lambda x: x["reopen_count"], reverse=True)
    
    total_reopened = len(reopened_stocks)
    reopen_rate = total_reopened / max(pool_data["total"], 1) * 100
    
    # 2. 炸板行业排名
    from collections import defaultdict
    ind_reopen = defaultdict(lambda: {"total": 0, "reopened": 0})
    for s in pool_data["stocks"]:
        ind = s.get("industry_name", "未知")
        ind_reopen[ind]["total"] += 1
        if s["reopen_count"] > 0:
            ind_reopen[ind]["reopened"] += 1
    
    ind_ranking = []
    for ind_name, data in ind_reopen.items():
        if data["total"] >= 3:  # 至少有3只涨停才纳入
            rate = data["reopened"] / data["total"] * 100
            ind_ranking.append({
                "industry_name": ind_name,
                "total": data["total"],
                "reopened": data["reopened"],
                "reopen_rate_pct": round(rate, 1),
            })
    ind_ranking.sort(key=lambda x: x["reopen_rate_pct"], reverse=True)
    
    return {
        "date": pool_data["date"],
        "total_reopened": total_reopened,
        "reopen_rate_pct": round(reopen_rate, 1),
        "most_reopened": [
            {
                "code": s["code"], "name": s["name"],
                "reopen_count": s["reopen_count"],
                "first_time": s["first_time"],
                "industry_name": s["industry_name"],
                "consecutive_days": s["consecutive_days"],
            }
            for s in reopened_stocks[:10]
        ],
        "by_industry": ind_ranking[:10],
    }


# 用法
reopen_rpt = reopen_analysis(today_data)
print(f"\n💥 炸板分析:")
print(f"  炸板股票: {reopen_rpt['total_reopened']}/{reopen_rpt.get('date','')}总计{pools.get(reopen_rpt.get('date',''),{}).get('total','?')}只")
print(f"  炸板率: {reopen_rpt['reopen_rate_pct']}%")
print(f"\n  炸板次数最多的个股:")
for s in reopen_rpt["most_reopened"][:5]:
    print(f"    {s['code']} {s['name']:<8s} 炸板{s['reopen_count']}次 "
          f"首触{s['first_time']} {s['industry_name']} {s['consecutive_days']}连板")
print(f"\n  炸板率最高的行业:")
for ind in reopen_rpt["by_industry"][:5]:
    print(f"    {ind['industry_name']:<12s} {ind['reopened']}/{ind['total']}只 "
          f"炸板率={ind['reopen_rate_pct']}%")
```

### 3.3 封板强度分析

```python
def seal_strength_analysis(pool_data: dict) -> dict:
    """
    封板强度分析——按封单金额排名，识别最强封板。
    
    封板金额越大 → 买方意愿越强 → 次日溢价概率越高
    但需注意：尾盘封板即使封单大也不如早盘小封单可靠。
    """
    stocks = sorted(pool_data["stocks"], key=lambda x: x["seal_amount"], reverse=True)
    
    # 封单/流通市值比（封板强度系数）
    for s in stocks:
        if s["float_mcap"] > 0:
            s["seal_ratio"] = s["seal_amount"] / s["float_mcap"]  # 封单占流通市值比
        else:
            s["seal_ratio"] = 0
    
    # 按封单金额排名
    by_amount = sorted(stocks, key=lambda x: x["seal_amount"], reverse=True)[:20]
    
    # 按封单占比排名（反映真实的封板力度）
    by_ratio = sorted(stocks, key=lambda x: x["seal_ratio"], reverse=True)[:20]
    
    # 平均封单统计
    total_seal = sum(s["seal_amount"] for s in stocks)
    avg_seal = total_seal / max(len(stocks), 1)
    
    return {
        "date": pool_data["date"],
        "total_seal_amount": total_seal,
        "avg_seal_amount": avg_seal,
        "top_by_amount": [
            {
                "code": s["code"], "name": s["name"],
                "seal_amount": s["seal_amount"],
                "seal_amount_yi": round(s["seal_amount"] / 1e8, 2),
                "first_time": s["first_time"],
                "consecutive_days": s["consecutive_days"],
            }
            for s in by_amount
        ],
        "top_by_ratio": [
            {
                "code": s["code"], "name": s["name"],
                "seal_ratio_pct": round(s["seal_ratio"] * 100, 2),
                "first_time": s["first_time"],
                "float_mcap_yi": round(s["float_mcap"] / 1e8, 1),
            }
            for s in by_ratio if s["seal_ratio"] > 0
        ],
    }


# 用法
seal_rpt = seal_strength_analysis(today_data)
print(f"\n🔒 封板强度分析:")
print(f"  总封单金额: {seal_rpt['total_seal_amount']/1e8:.1f}亿")
print(f"  均封单金额: {seal_rpt['avg_seal_amount']/1e8:.2f}亿")
print(f"\n  封单金额 TOP 10:")
for s in seal_rpt["top_by_amount"][:10]:
    print(f"    {s['code']} {s['name']:<8s} 封单={s['seal_amount_yi']:.2f}亿  "
          f"首触={s['first_time']} {s['consecutive_days']}连板")
```

---

## Layer 4: 多日趋势对比

### 4.1 涨停情绪周期判断

```python
def trend_comparison(data_3day: dict) -> dict:
    """
    三日涨停趋势对比——判断情绪方向（升温/降温/稳定）。
    
    分析维度：
    1. 涨停总数变化
    2. 连板晋级率（1→2, 2→3）
    3. 炸板率变化
    4. 热点板块持续性
    """
    dates = sorted(data_3day.keys(), reverse=True)  # 最新在前
    
    if len(dates) < 2:
        return {"error": "需要至少2天数据做趋势对比"}
    
    # 基础数据
    summary = {}
    for d in dates:
        data = data_3day[d]
        summary[d] = {
            "total": data["total"],
            "by_consecutive": data.get("by_consecutive", {}),
            "by_market": data.get("by_market", {}),
        }
    
    # 涨停数变化
    latest_total = summary[dates[0]]["total"]
    prev_total = summary[dates[1]]["total"]
    if prev_total > 0:
        total_change_pct = (latest_total - prev_total) / prev_total * 100
    else:
        total_change_pct = 0
    
    # 情绪判断
    if total_change_pct > 20:
        mood = "🔥 大幅升温"
    elif total_change_pct > 5:
        mood = "☀️ 温和升温"
    elif total_change_pct > -5:
        mood = "➖ 平稳"
    elif total_change_pct > -20:
        mood = "🌧️ 温和降温"
    else:
        mood = "❄️ 大幅降温"
    
    # 连板晋级率
    promotion = {}
    for i in range(len(dates) - 1):
        curr_date = dates[i]
        prev_date = dates[i + 1]
        prev_1b = set()
        curr_2b = set()
        
        for s in data_3day[prev_date]["stocks"]:
            prev_1b.add(s["code"])
        for s in data_3day[curr_date]["stocks"]:
            if s["consecutive_days"] >= 2:
                curr_2b.add(s["code"])
        
        promoted = prev_1b & curr_2b
        promotion[f"{prev_date}→{curr_date}"] = {
            "prev_1b_count": len(prev_1b),
            "promoted_count": len(promoted),
            "promotion_rate": round(len(promoted) / max(len(prev_1b), 1) * 100, 1),
        }
    
    # 行业持续性（连续出现涨停的行业）
    from collections import defaultdict
    ind_persistence = defaultdict(int)
    for d in dates:
        seen_industries = set()
        for s in data_3day[d]["stocks"]:
            ind = s.get("industry_name", "")
            if ind and ind not in seen_industries:
                ind_persistence[ind] += 1
                seen_industries.add(ind)
    
    persistent_industries = [
        {"name": k, "days": v}
        for k, v in sorted(ind_persistence.items(), key=lambda x: x[1], reverse=True)
        if v >= 2
    ]
    
    return {
        "dates": dates,
        "summary": summary,
        "total_change_pct": round(total_change_pct, 1),
        "mood": mood,
        "promotion": promotion,
        "persistent_industries": persistent_industries[:15],
    }


# 用法
trend = trend_comparison(data_3day)
print(f"\n📈 三日趋势对比:")
print(f"  情绪判断: {trend['mood']}")
print(f"  涨停数变化: {trend['total_change_pct']:+.1f}%")
for d in trend["dates"]:
    s = trend["summary"][d]
    print(f"  {d}: 涨停{s['total']}只  首板{s['by_consecutive'].get('1','?')}  "
          f"2连板{s['by_consecutive'].get('2','?')}  3连板{s['by_consecutive'].get('3','?')}  "
          f"高标{s['by_consecutive'].get('4+','?')}")

print(f"\n  连板晋级率:")
for period, info in trend.get("promotion", {}).items():
    print(f"    {period}: 首板{info['prev_1b_count']}→晋级{info['promoted_count']} "
          f"({info['promotion_rate']}%)")

print(f"\n  持续活跃行业 (>1天):")
for ind in trend["persistent_industries"][:10]:
    bar = "█" * ind["days"]
    print(f"    {ind['name']:<14s} {bar} {ind['days']}天")
```

### 4.2 板块爆发检测

```python
def sector_breakout_detect(data_3day: dict, threshold: int = 5) -> dict:
    """
    检测板块涨停爆发信号。
    
    判断标准：
    - 当日板块涨停数 >= threshold → 板块涨停潮
    - 板块涨停数较前日翻倍 → 爆发启动
    - 板块涨停数连续增长 → 持续发酵
    """
    dates = sorted(data_3day.keys(), reverse=True)
    
    # 统计每日概念涨停数
    from collections import defaultdict
    concept_daily = {}
    for d in dates:
        concept_daily[d] = concept_limit_up_ranking(data_3day[d], top_n=500)
    
    # 检测当日爆发板块
    latest_concepts = concept_daily.get(dates[0], {}).get("ranking", [])
    prev_concepts_map = {}
    if len(dates) >= 2:
        for c in concept_daily.get(dates[1], {}).get("ranking", []):
            prev_concepts_map[c["concept_name"]] = c["count"]
    
    breakouts = []
    for c in latest_concepts:
        count = c["count"]
        prev_count = prev_concepts_map.get(c["concept_name"], 0)
        
        signal = None
        if count >= threshold * 2:
            signal = "🚨 超级涨停潮"
        elif count >= threshold:
            if prev_count == 0:
                signal = "🆕 新题材爆发"
            elif count >= prev_count * 2:
                signal = "📈 爆发加速"
            elif count >= prev_count * 1.3:
                signal = "🔥 持续升温"
            else:
                signal = "✅ 持续活跃"
        elif prev_count == 0 and count >= 3:
            signal = "👀 初次异动"
        
        if signal:
            breakouts.append({
                "concept_name": c["concept_name"],
                "count": count,
                "prev_count": prev_count,
                "signal": signal,
                "top_stocks": [
                    {"code": s["code"], "name": s["name"], "consecutive_days": s["consecutive_days"]}
                    for s in c["stocks"][:5]
                ],
            })
    
    return {
        "date": dates[0],
        "threshold": threshold,
        "breakouts": breakouts,
    }


# 用法
breakout = sector_breakout_detect(data_3day, threshold=5)
print(f"\n🎯 板块爆发信号 ({breakout['date']}):")
for b in breakout["breakouts"]:
    prev_info = f"(前日{b['prev_count']}只)" if b['prev_count'] > 0 else "(新题材)"
    print(f"  {b['signal']} {b['concept_name']}: {b['count']}只涨停 {prev_info}")
    print(f"    代表股: {', '.join(s['name'] for s in b['top_stocks'][:3])}")
```

---

## Layer 5: 综合报告生成

### 5.1 一键涨停全景报告

```python
def limit_up_daily_report(date: str = None) -> dict:
    """
    涨停板全景日报。
    
    包含：
    - 全市场涨停概览（数量/市场分布/连板分布）
    - 涨停时间分布（早盘/午前/午后/尾盘）
    - 行业涨停数排名 TOP 20
    - 概念涨停数排名 TOP 30
    - 炸板专项分析
    - 封板强度排名
    - 连板高标追踪
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    
    print(f"[1/6] 拉取涨停池数据...")
    pool = fetch_limit_up_pool(date=date)
    print(f"  → {pool['total']} 只涨停")
    
    print("[2/6] 行业涨停排名...")
    ind_rank = industry_limit_up_ranking(pool)
    
    print("[3/6] 概念涨停排名...")
    concept_rank = concept_limit_up_ranking(pool)
    
    print("[4/6] 涨停时间分布...")
    time_dist = time_distribution_analysis(pool)
    
    print("[5/6] 炸板分析...")
    reopen_rpt = reopen_analysis(pool)
    
    print("[6/6] 封板强度分析...")
    seal_rpt = seal_strength_analysis(pool)
    
    # 高标股列表（3连板及以上）
    high_mark = [s for s in pool["stocks"] if s["consecutive_days"] >= 3]
    high_mark.sort(key=lambda x: x["consecutive_days"], reverse=True)
    
    return {
        "pool": pool,
        "industry_ranking": ind_rank,
        "concept_ranking": concept_rank,
        "time_distribution": time_dist,
        "reopen_analysis": reopen_rpt,
        "seal_strength": seal_rpt,
        "high_mark_stocks": high_mark,
    }


def print_limit_up_report(report: dict):
    """打印涨停板全景报告（中文友好格式）"""
    pool = report["pool"]
    
    print("=" * 80)
    print(f"  📊 A股涨停板全景报告 — {pool['date']}")
    print(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)
    
    # ━━ 概览 ━━
    print(f"\n{'─' * 80}")
    print(f"  📋 全市场涨停概览")
    print(f"{'─' * 80}")
    print(f"  涨停总数: {pool['total']} 只")
    for mkt, count in pool.get("by_market", {}).items():
        if isinstance(count, int):
            print(f"    {mkt}: {count} 只")
    
    print(f"\n  连板分布:")
    for key, count in pool.get("by_consecutive", {}).items():
        label = f"{key}连板" if key.isdigit() else "高标(4+)"
        print(f"    {label}: {count} 只")
    
    # ━━ 涨停时间分布 ━━
    print(f"\n{'─' * 80}")
    print(f"  ⏰ 涨停时间分布")
    print(f"{'─' * 80}")
    print(f"  {'时间段':<25s} {'数量':>5s} {'占比':>6s} {'炸板率':>7s}  {'信号'}")
    print(f"  {'─' * 55}")
    for slot_name, info in report["time_distribution"]["distribution"].items():
        signal = ""
        if "秒板" in slot_name or "早盘强" in slot_name:
            signal = "🔥最强"
        elif "早盘板" in slot_name:
            signal = "💪较强"
        elif "午前" in slot_name:
            signal = "➖中等"
        elif "午后" in slot_name:
            signal = "⚠️一般"
        elif "尾盘" in slot_name:
            signal = "🔻最弱"
        print(f"  {slot_name:<23s} {info['count']:>5d} {info['pct']:>5.1f}% "
              f"{info['reopen_rate_pct']:>6.1f}%  {signal}")
    
    # ━━ 行业排名 TOP 15 ━━
    print(f"\n{'─' * 80}")
    print(f"  🏭 行业涨停数排名 TOP 15")
    print(f"{'─' * 80}")
    for i, ind in enumerate(report["industry_ranking"]["ranking"][:15]):
        bar = "█" * min(ind["count"], 25)
        print(f"  {i+1:2d}. {ind['industry_name']:<14s} {bar} {ind['count']}只"
              f"  均封单={ind['avg_seal_amount']/1e8:.1f}亿"
              f"  炸板率={ind['reopen_rate_pct']:.0f}%")
    
    # ━━ 概念排名 TOP 20 ━━
    print(f"\n{'─' * 80}")
    print(f"  🔥 概念涨停数排名 TOP 20")
    print(f"{'─' * 80}")
    for i, c in enumerate(report["concept_ranking"]["ranking"][:20]):
        bar = "█" * min(c["count"], 20)
        print(f"  {i+1:2d}. {c['concept_name']:<16s} {bar} {c['count']}只"
              f"  均封单={c['avg_seal_amount']/1e8:.1f}亿")
    
    # ━━ 高标追踪 ━━
    print(f"\n{'─' * 80}")
    print(f"  🏆 连板高标追踪 (3连板及以上)")
    print(f"{'─' * 80}")
    if report["high_mark_stocks"]:
        print(f"  {'代码':<8s} {'名称':<10s} {'连板':>4s} {'封单(亿)':>8s} {'首触':>10s} {'行业':<14s} {'炸板':>4s}")
        print(f"  {'─' * 65}")
        for s in report["high_mark_stocks"]:
            print(f"  {s['code']:<8s} {s['name']:<10s} {s['consecutive_days']:>4d}天 "
                  f"{s['seal_amount']/1e8:>7.2f} {s['first_time']:>10s} "
                  f"{s['industry_name']:<14s} {s['reopen_count']:>4d}次")
    else:
        print(f"  (无3连板及以上高标)")
    
    # ━━ 炸板分析 ━━
    print(f"\n{'─' * 80}")
    print(f"  💥 炸板专项分析")
    print(f"{'─' * 80}")
    ra = report["reopen_analysis"]
    print(f"  炸板股票: {ra['total_reopened']}/{pool['total']} 只 ({ra['reopen_rate_pct']}%)")
    if ra["most_reopened"]:
        print(f"\n  炸板最多的个股:")
        for s in ra["most_reopened"][:5]:
            print(f"    {s['code']} {s['name']:<8s} 炸板{s['reopen_count']}次 "
                  f"首触{s['first_time']} {s['industry_name']} {s['consecutive_days']}连板")
    
    # ━━ 封板强度 TOP 10 ━━
    print(f"\n{'─' * 80}")
    print(f"  🔒 封板强度 TOP 10（按封单金额）")
    print(f"{'─' * 80}")
    for i, s in enumerate(report["seal_strength"]["top_by_amount"][:10]):
        print(f"  {i+1:2d}. {s['code']} {s['name']:<8s} 封单{s['seal_amount_yi']:.2f}亿 "
              f"{s['first_time']} {s['consecutive_days']}连板")
    
    # ━━ 声明 ━━
    print(f"\n{'=' * 80}")
    print(f"  ⚠️ 研究声明: 以上数据基于公开API，仅供参考。涨停板分析不构成任何投资建议。")
    print(f"     打板有风险，追高需谨慎。涨停板次日走势受多重因素影响，")
    print(f"     历史规律不保证未来结果。")
    print(f"{'=' * 80}")


# ━━━ 完整用法 ━━━
# report = limit_up_daily_report()  # 默认今天
# print_limit_up_report(report)
#
# # 三日趋势分析
# data_3day = fetch_limit_up_3days()
# trend = trend_comparison(data_3day)
# print(f"\n三日情绪: {trend['mood']}")
# breakout = sector_breakout_detect(data_3day)
# for b in breakout["breakouts"]:
#     print(f"  {b['signal']} {b['concept_name']}: {b['count']}只涨停")
```

---

## 快速参考

### 输出目录

分析报告统一输出到 `src/涨停分析/` 下：

```bash
mkdir -p src/涨停分析/$(date +%Y-%m-%d)-涨停复盘/
```

目录结构：
```
src/涨停分析/
├── _index.md                       # 导航索引
└── YYYY-MM-DD-涨停复盘/
    ├── report.md                   # 涨停全景报告
    ├── trend-comparison.md         # 三日趋势对比
    ├── sector-detail.md            # 热点板块个股明细
    └── high-mark-tracking.md       # 连板高标追踪
```

### 常用调用组合

| 场景 | 调用链 |
|------|--------|
| 今日涨停全景 | `limit_up_daily_report()` → `print_limit_up_report()` |
| 查看某概念涨停股 | `concept_limit_up_ranking(pool)` → 找对应概念 |
| 判断打板情绪 | `time_distribution_analysis(pool)` → 看早盘板占比 |
| 找连板高标 | `pool["stocks"]` 筛选 `consecutive_days >= 3` |
| 三日趋势对比 | `fetch_limit_up_3days()` → `trend_comparison()` |
| 板块爆发检测 | `fetch_limit_up_3days()` → `sector_breakout_detect()` |
| 炸板率异常排查 | `reopen_analysis(pool)` → 看炸板率高的行业 |
| 每日复盘 | `limit_up_daily_report()` 完整流程 |

### 涨停质量评估速查

| 维度 | 强信号 ✅ | 中等信号 ➖ | 弱信号 ⚠️ |
|------|----------|-----------|----------|
| **涨停时间** | 竞价秒板/早盘强板 | 早盘板/午前板 | 午后板/尾盘偷袭 |
| **炸板次数** | 0次（一封到底） | 1-2次回封 | 3次以上反复开板 |
| **封单金额** | >1亿（主板）/ >5000万（创业板） | 5000万-1亿 | <3000万 |
| **封单/流通市值** | >5% | 1%-5% | <1% |
| **连板数** | 首板/2板（低位启动） | 3-4板（中位接力） | 5板+（高位博弈） |
| **换手率** | 5%-15%（充分换手） | 15%-25%（分歧加大） | >25%（过度换手）或 <2%（无换手一字） |
| **板块涨停数** | 板块≥5只涨停（板块效应强） | 板块3-4只涨停 | 独立涨停无板块支撑 |

### 涨停健康度评分（快速参考）

对单只涨停板股票打分（满分 10 分）：

```python
def quick_score(stock: dict) -> int:
    """快速评估涨停质量（0-10分）"""
    score = 0
    
    # 涨停时间（0-3分）
    ft = stock.get("first_time", "")
    if ft:
        try:
            h, m, s = ft.split(":")
            minutes = int(h) * 60 + int(m)
            if minutes <= 9 * 60 + 35:    score += 3  # 竞价秒板/早盘强板
            elif minutes <= 10 * 60 + 30: score += 2  # 早盘板
            elif minutes <= 14 * 60:      score += 1  # 午前/午后板
        except: pass
    
    # 炸板（0-2分）
    rc = stock.get("reopen_count", 0)
    if rc == 0:         score += 2
    elif rc <= 2:        score += 1
    # rc > 2: 不加分
    
    # 封单金额（0-2分）
    seal = stock.get("seal_amount", 0)
    if seal > 1e8:      score += 2
    elif seal > 5e7:    score += 1
    
    # 连板位置（0-2分）
    days = stock.get("consecutive_days", 1)
    if days <= 2:       score += 2  # 首板/2板最安全
    elif days <= 4:     score += 1  # 3-4板尚可
    # days > 4: 不加分（高位风险大）
    
    # 换手率（0-1分）
    turnover = stock.get("turnover_pct", 0)
    if 5 <= turnover <= 20: score += 1  # 充分换手但不极端
    
    return score
```

### 盘中动态字段 vs 历史字段

| 字段 | 当日盘中 | 历史回溯 |
|------|---------|---------|
| 涨停时间（first_time） | ✅ 实时 | ⚠️ 可能为空 |
| 炸板次数（reopen_count） | ✅ 实时 | ⚠️ 可能为空 |
| 封单金额（seal_amount） | ✅ 实时快照 | ❌ 一般不可查 |
| 涨跌幅% | ✅ | ✅ |
| 连板数 | ✅ | ✅ |
| 行业/概念 | ✅ | ✅ |
| 换手率/量比 | ✅ | ✅ |

> **建议：** 盘中动态指标（涨停时间/炸板/封单）以**当日拉取**为准；历史回溯时重点关注数量变化、行业分布、连板晋级等宏观指标。

---

## 常见问题

### Q: push2ex 涨停池和龙虎榜有什么区别？
A: 涨停池覆盖所有涨停股票（无论是否上龙虎榜），龙虎榜只覆盖触发异常波动的股票（涨跌幅偏离7%/换手率>20%等条件）。涨停池数量远大于龙虎榜，是日常复盘的主力工具。

### Q: 为什么历史日期的涨停时间和炸板数据为空？
A: push2ex 接口在历史日期查询时，返回的是"收盘后的最终封板清单"，盘中动态字段（首次涨停时间、炸板次数、封单变化等）是实时快照数据，不在历史快照中保留。

### Q: 如何判断一个板块是否在"爆发"？
A: 三个标准：① 当日板块涨停数 ≥5 只（涨停潮阈值）；② 较前日翻倍（加速）；③ 连续3天保持≥3只涨停（持续性）。三个条件满足任一即为异动。

### Q: 涨停板分析能预测次日走势吗？
A: **不能**。涨停板复盘是对当日市场情绪的归纳，不是对次日走势的预测。但可以通过"涨停质量"评估（时间+封单+板块效应）辅助判断"哪些涨停次日更可能有溢价"，这是一个概率框架而非预测。

### Q: 和 capital-flow-tracker 的关系？
A: 互补关系。`capital-flow-tracker` 从资金流向维度看市场（谁在买/卖/还剩多少），`limit-up-tracker` 从涨停板维度看市场（哪些股票被追捧到极致、哪些板块在爆发）。两者结合使用效果最佳——资金流看趋势，涨停板看情绪。

---

## 风险声明

- 涨停板数据基于东方财富公开 API（push2ex），数据延迟通常 1-3 秒
- 历史日期的盘中动态字段（涨停时间、炸板次数、封单金额）可能不完整或为空
- 行业/概念分类基于东财自有分类体系，与其他平台（同花顺/申万）可能略有差异
- 涨停质量评估是归纳性框架，不构成对任何个股次日走势的预测
- "打板"是高风险交易行为，涨停板次日可能高开高走，也可能低开低走甚至跌停
- 所有分析仅供参考，不构成投资建议
