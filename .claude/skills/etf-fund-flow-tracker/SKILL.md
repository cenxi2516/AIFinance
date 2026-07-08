---
name: etf-fund-flow-tracker
description: A股ETF资金走势追踪 — 覆盖宽基/行业/主题/策略/债券/跨境/商品七大类ETF，多周期资金流聚合（今日~1年），宽基风格判断（大盘/中小盘/成长/价值），行业ETF轮动信号检测。核心能力：①ETF全市场资金流扫描 ②宽基ETF风格偏好识别 ③行业/主题ETF轮动热度排名 ④ETF+个股资金流+涨停板+政策事件多维交叉验证盘面分析。适用于大盘风向判断、行业轮动确认、增量资金入市检测、市场风格切换预警。
version: 1.0.0
updated: 2026-07-07
---

# A股ETF资金走势追踪器 V1.0

全市场 ETF 资金流追踪工具——覆盖 7 大类 ETF，多周期资金流聚合，宽基风格识别，行业轮动信号检测。**核心价值：将 ETF 资金流与现有 skill（capital-flow-tracker / limit-up-tracker / policy-event-tracker）进行多维交叉验证，实现盘面全景分析。**

> **设计原则：** 依赖 a-stock-data 的通用 helper（`em_get` / `eastmoney_datacenter`），本 skill 聚焦 ETF 特有的分类体系、资金流聚合、风格判断和跨 skill 盘面分析逻辑。
>
> **与现有 skill 的关系：** capital-flow-tracker 覆盖个股+板块资金流（主力/游资/散户），本 skill 覆盖 ETF 资金流（机构/配置型资金为主），两者互补——ETF 资金流反映中长期配置资金意图，个股资金流反映短期交易情绪。

## When to Activate

- 用户要看**ETF资金流向**（哪些ETF在流入/流出、增量资金是否入场）
- 用户要判断**市场风格**（大盘 vs 中小盘、成长 vs 价值）
- 用户要分析**行业轮动**（芯片/新能源/消费/军工等行业ETF资金轮动）
- 用户要做**盘面综合分析**（ETF资金流 + 板块资金流 + 涨停情绪 + 政策事件 多维验证）
- 用户要检测**增量资金入场信号**（ETF份额持续增加 + 成交放量）
- 关键词：`ETF`、`ETF资金流`、`ETF资金走势`、`宽基ETF`、`行业ETF`、`主题ETF`、`ETF轮动`、`盘面分析`

## Prerequisites

本 skill 依赖 a-stock-data 的通用 helper：

```python
import time, random, requests, json, re
from datetime import datetime, timedelta
from collections import defaultdict

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.5
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15):
    """东财统一请求：自动节流 + Keep-Alive"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last_call[0] = time.time()

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def eastmoney_datacenter(report_name, columns="ALL", filter_str="",
                          page_size=50, sort_columns="", sort_types="-1"):
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
```

---

## ETF 分类体系

### 七大类 ETF

| 类别 | 特征 | 代表ETF | 资金含义 |
|------|------|---------|---------|
| 🏛️ **宽基ETF** | 跟踪大盘指数 | 510050(上证50), 510300(沪深300), 510500(中证500), 588000(科创50), 159915(创业板) | **市场整体风向标**，增量资金最先流入宽基 |
| 🏭 **行业ETF** | 跟踪特定行业 | 512880(证券), 512480(半导体), 159995(芯片), 516160(新能源) | **行业轮动信号**，机构配置方向 |
| 💡 **主题ETF** | 跟踪概念主题 | 515050(5G), 516020(人工智能) | **题材热度指标**，与涨停板情绪互相验证 |
| 📐 **策略ETF** | 红利/低波/质量 | 510880(红利), 512890(红利低波) | **防御型资金**，市场避险情绪指标 |
| 🏦 **债券ETF** | 国债/信用债/可转债 | 511010(国债), 511380(转债) | **固收配置**，股票风险偏好反向指标 |
| 🌍 **跨境ETF** | 港股/美股/日经 | 513050(中概互联), 513100(纳指) | **海外配置**，A股吸引力替代指标 |
| 🥇 **商品ETF** | 黄金/有色/能源 | 518880(黄金), 159980(有色) | **通胀/避险**，与宏观事件相关 |

### 核心 ETF 池

```python
# 核心ETF池（按市值和流动性筛选，2026-07 实测）
CORE_ETFS = {
    # === 宽基ETF ===
    "510050": {"name": "上证50ETF",       "cat": "宽基", "style": "大盘价值"},
    "510300": {"name": "沪深300ETF",      "cat": "宽基", "style": "大盘均衡"},
    "510500": {"name": "中证500ETF",      "cat": "宽基", "style": "中盘成长"},
    "159915": {"name": "创业板ETF",       "cat": "宽基", "style": "成长"},
    "588000": {"name": "科创50ETF",       "cat": "宽基", "style": "硬科技"},
    "510330": {"name": "沪深300ETF华夏",  "cat": "宽基", "style": "大盘均衡"},
    "159845": {"name": "中证1000ETF",     "cat": "宽基", "style": "小盘成长"},
    # === 行业ETF ===
    "512880": {"name": "证券ETF",         "cat": "行业", "style": "券商"},
    "512480": {"name": "半导体ETF",       "cat": "行业", "style": "半导体"},
    "159995": {"name": "芯片ETF",         "cat": "行业", "style": "芯片"},
    "516160": {"name": "新能源ETF",       "cat": "行业", "style": "新能源"},
    "512660": {"name": "军工ETF",         "cat": "行业", "style": "军工"},
    "512690": {"name": "酒ETF",           "cat": "行业", "style": "消费"},
    "512010": {"name": "医药ETF",         "cat": "行业", "style": "医药"},
    "516510": {"name": "云计算ETF",       "cat": "行业", "style": "云计算"},
    "159869": {"name": "游戏ETF",         "cat": "行业", "style": "游戏"},
    # === 策略ETF ===
    "510880": {"name": "红利ETF",         "cat": "策略", "style": "红利防御"},
    "512890": {"name": "红利低波ETF",     "cat": "策略", "style": "红利低波"},
    # === 跨境ETF ===
    "513050": {"name": "中概互联ETF",     "cat": "跨境", "style": "中概互联"},
    "513100": {"name": "纳指ETF",         "cat": "跨境", "style": "纳斯达克"},
    # === 商品ETF ===
    "518880": {"name": "黄金ETF",         "cat": "商品", "style": "黄金避险"},
}

def get_etf_info(code: str) -> dict:
    """查ETF基本信息（优先核心池）"""
    return CORE_ETFS.get(code, {"name": code, "cat": "其他", "style": ""})
```

---

## Layer 1: 全市场 ETF 列表与行情

### 1.1 全部场内 ETF 列表

```python
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

def all_etf_list(sort_by: str = "f20", top_n: int = 200) -> dict:
    """
    全市场场内ETF列表（fs=m:1+t:1）。
    sort_by: 'f20'=总市值, 'f3'=涨跌幅, 'f62'=主力净流入
    返回: {total, etfs: [{code, name, price, change_pct, mcap, main_net, turnover}]}
    """
    params = {
        "pn": "1", "pz": str(min(top_n, 500)), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:1+t:1",
        "fields": "f2,f3,f4,f12,f14,f20,f21,f62,f66,f72,f8,f10",
        "st": sort_by,
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    try:
        r = em_get(PUSH2_CLIST, params=params, headers=headers, timeout=20)
        d = r.json()
    except Exception as e:
        print(f"[WARN] ETF列表请求失败: {e}")
        return {"total": 0, "etfs": []}

    items = d.get("data", {}).get("diff", [])
    total = d.get("data", {}).get("total", 0)
    etfs = []
    for it in items:
        etfs.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "price": it.get("f2", 0),
            "change_pct": it.get("f3", 0),
            "mcap": it.get("f20") or 0,
            "float_mcap": it.get("f21") or 0,
            "main_net": it.get("f62") or 0,
            "super_large_net": it.get("f66") or 0,
            "large_net": it.get("f72") or 0,
            "turnover_pct": it.get("f8", 0),
            "vol_ratio": it.get("f10", 0),
        })
    return {"total": total, "etfs": etfs}
```

### 1.2 腾讯财经 ETF 实时行情（首选，不封IP）

```python
import urllib.request

def tencent_etf_quotes(codes: list[str]) -> dict[str, dict]:
    """
    腾讯财经ETF实时行情——不封IP，放心高频调用。
    返回: {code: {name, price, change_pct, mcap_yi, turnover_pct, vol_ratio, ...}}
    """
    prefixed = []
    for c in codes:
        if c.startswith(("5", "6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode("gbk")

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name":         vals[1],
            "price":        float(vals[3]) if vals[3] else 0,
            "last_close":   float(vals[4]) if vals[4] else 0,
            "open":         float(vals[5]) if vals[5] else 0,
            "change_pct":   float(vals[32]) if vals[32] else 0,
            "high":         float(vals[33]) if vals[33] else 0,
            "low":          float(vals[34]) if vals[34] else 0,
            "amount_wan":   float(vals[37]) if vals[37] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm":       float(vals[39]) if vals[39] else 0,
            "mcap_yi":      float(vals[44]) if vals[44] else 0,
            "vol_ratio":    float(vals[49]) if vals[49] else 0,
        }
    return result


# 用法: 核心宽基ETF实时行情
core_codes = ["510050", "510300", "510500", "588000", "159915", "159845"]
quotes = tencent_etf_quotes(core_codes)
print("核心宽基ETF实时行情:")
for code, q in quotes.items():
    info = CORE_ETFS.get(code, {})
    print(f"  {q['name']:<18s} ({info.get('style',''):<8s}) "
          f"价格={q['price']:<8.3f} 涨跌={q['change_pct']:>+6.2f}% "
          f"市值={q['mcap_yi']:>8.2f}亿 换手={q['turnover_pct']:>5.2f}%")
```

---

## Layer 2: ETF 资金流（分钟级 + 日级 + 多周期）

### 2.1 ETF 分钟级资金流（当日实时）

```python
PUSH2_FFLOW = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"

def etf_fund_flow_minute(code: str) -> list[dict]:
    """
    ETF当日分钟级资金流（与个股使用同一API）。
    返回: [{time, main_net, small_net, mid_net, large_net, super_net}]
    单位: 元
    """
    secid = f"1.{code}" if code.startswith(("5", "6", "9")) else f"0.{code}"
    params = {
        "secid": secid, "klt": "1",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "lmt": "250",
    }
    headers = {"Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    try:
        r = em_get(PUSH2_FFLOW, params=params, headers=headers, timeout=15)
        d = r.json()
    except Exception as e:
        print(f"[WARN] ETF分钟资金流失败 ({code}): {e}")
        return []

    klines = d.get("data", {}).get("klines", []) or []
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append({
                "time": parts[0],
                "main_net": float(parts[1]) if parts[1] != "-" else 0,
                "small_net": float(parts[2]) if parts[2] != "-" else 0,
                "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                "large_net": float(parts[4]) if parts[4] != "-" else 0,
                "super_net": float(parts[5]) if parts[5] != "-" else 0,
            })
    return rows
```

### 2.2 ETF 日级资金流 + 多周期聚合

```python
PUSH2_HIS = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

PERIOD_DAYS = {
    "today": 0, "1w": 5, "2w": 10, "1m": 22, "2m": 44,
    "3m": 66, "4m": 88, "5m": 110, "6m": 125, "1y": 250,
}

def etf_multiperiod_fund_flow(code: str, periods: list[str] = None) -> dict:
    """
    ETF多周期资金流聚合（已验证：510050/159995等ETF可用push2his）。
    periods: 默认 ['today','1w','2w','1m','3m','6m']
    返回: {period: {main_net, super_large_net, large_net, mid_net, small_net, days}}
    """
    if periods is None:
        periods = ["today", "1w", "2w", "1m", "3m", "6m"]

    result = {}

    # 当日数据走分钟级 API
    today_data = etf_fund_flow_minute(code)
    if today_data:
        result["today"] = {
            "main_net": sum(r["main_net"] for r in today_data),
            "super_large_net": sum(r["super_net"] for r in today_data),
            "large_net": sum(r["large_net"] for r in today_data),
            "mid_net": sum(r["mid_net"] for r in today_data),
            "small_net": sum(r["small_net"] for r in today_data),
            "minutes": len(today_data),
        }

    # 历史日级数据
    secid = f"1.{code}" if code.startswith(("5", "6", "9")) else f"0.{code}"
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
    except Exception as e:
        print(f"[WARN] ETF日级资金流失败 ({code}): {e}")
        return result

    if not klines:
        return result

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

    for period in periods:
        if period == "today":
            continue
        days = PERIOD_DAYS.get(period, 22)
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


# 用法: 多ETF多周期对比
for code in ["510050", "510300", "588000", "159915"]:
    flow = etf_multiperiod_fund_flow(code)
    info = CORE_ETFS.get(code, {})
    print(f"\n{code} {info.get('name', '')} ({info.get('style', '')}):")
    for period in ["today", "1w", "1m", "3m"]:
        if period in flow:
            net = flow[period]["main_net"]
            span = flow[period].get("days", flow[period].get("minutes", "?"))
            direction = "⬆️" if net > 0 else "⬇️"
            print(f"  {period:>5s}: {direction} {abs(net)/1e8:.2f}亿 ({span}周期)")
```

### 2.3 核心 ETF 池批量扫描

```python
def core_etf_flow_scan(period: str = "1w") -> list[dict]:
    """
    核心ETF池批量资金流扫描（单周期快速对比）。
    返回: 按主力净流入降序排列
    """
    results = []
    for code, info in CORE_ETFS.items():
        try:
            flow = etf_multiperiod_fund_flow(code, [period])
            if period in flow:
                results.append({
                    "code": code,
                    "name": info["name"],
                    "cat": info["cat"],
                    "style": info.get("style", ""),
                    "main_net": flow[period]["main_net"],
                    "super_large_net": flow[period].get("super_large_net", 0),
                    "days": flow[period].get("days", flow[period].get("minutes", 0)),
                })
        except Exception as e:
            print(f"  [SKIP] {code} {info['name']}: {e}")
        time.sleep(0.3)  # 批量间隔

    results.sort(key=lambda x: x["main_net"], reverse=True)
    return results
```

---

## Layer 3: 宽基ETF 风格判断

### 3.1 四大宽基风格对比

宽基 ETF 的资金流对比揭示市场风格偏好：

| 对比维度 | ETF组合 | 信号含义 |
|----------|---------|---------|
| **大盘 vs 中小盘** | 510050+510300 vs 510500+159845 | 大盘强=防御；中小盘强=进攻 |
| **成长 vs 价值** | 588000+159915 vs 510050+510880 | 成长强=风险偏好高；价值强=避险 |
| **科技 vs 传统** | 588000+159995 vs 510050+512880 | 科技强=产业驱动；传统强=估值修复 |
| **增量资金检测** | 四大宽基全部净流入 | 四线同向=增量入场（最强信号） |

```python
def wide_etf_style_analysis() -> dict:
    """
    宽基ETF风格对比分析。
    返回: {style_groups, incremental_signal, periods}
    """
    periods = ["today", "1w", "1m"]

    groups = {
        "large_cap":  ["510050", "510300"],
        "small_cap":  ["510500", "159845"],
        "growth":     ["588000", "159915"],
        "value":      ["510050", "510880"],
        "tech":       ["588000", "159995", "512480"],
        "traditional":["510050", "512880", "512690"],
    }

    all_codes = list(set(sum(groups.values(), [])))
    all_flows = {}
    for code in all_codes:
        try:
            all_flows[code] = etf_multiperiod_fund_flow(code, periods)
        except Exception:
            all_flows[code] = {}
        time.sleep(0.3)

    analysis = {}
    for group_name, codes in groups.items():
        analysis[group_name] = {}
        for period in periods:
            net = sum(
                all_flows.get(c, {}).get(period, {}).get("main_net", 0)
                for c in codes
            )
            analysis[group_name][period] = net

    # 增量资金检测
    big_four = ["510050", "510300", "510500", "159915"]
    incremental = {}
    for period in periods:
        flows = [all_flows.get(c, {}).get(period, {}).get("main_net", 0) for c in big_four]
        all_in = all(f > 0 for f in flows)
        total = sum(flows)
        incremental[period] = {
            "all_inflow": all_in,
            "total_net": total,
            "signal": "🚀 增量资金入场!" if all_in and total > 1e8
                      else "✅ 正常" if total > 0
                      else "⚠️ 资金流出",
        }

    return {"style_groups": analysis, "incremental_signal": incremental, "periods": periods}


def print_style_analysis(analysis: dict):
    """打印宽基ETF风格分析"""
    print("=" * 70)
    print("  🏛️ 宽基ETF风格对比分析")
    print("=" * 70)
    groups = analysis["style_groups"]

    large = groups["large_cap"]["1w"]
    small = groups["small_cap"]["1w"]
    style = "大盘蓝筹占优 (防御倾向)" if large > small else "中小盘占优 (进攻倾向)"
    print(f"\n  📊 大盘 vs 中小盘 (近1周): 大盘={large/1e8:+.2f}亿 vs 中小盘={small/1e8:+.2f}亿 → {style}")

    growth = groups["growth"]["1w"]
    value = groups["value"]["1w"]
    gv = "成长占优 (风险偏好高)" if growth > value else "价值占优 (避险)"
    print(f"  📊 成长 vs 价值 (近1周): 成长={growth/1e8:+.2f}亿 vs 价值={value/1e8:+.2f}亿 → {gv}")

    tech = groups["tech"]["1w"]
    trad = groups["traditional"]["1w"]
    ts = "科技成长驱动" if tech > trad else "传统估值修复驱动"
    print(f"  📊 科技 vs 传统 (近1周): 科技={tech/1e8:+.2f}亿 vs 传统={trad/1e8:+.2f}亿 → {ts}")

    inc = analysis["incremental_signal"]
    print(f"\n  🚦 增量资金检测:")
    for period in ["today", "1w", "1m"]:
        if period in inc:
            s = inc[period]
            print(f"     {period}: {s['signal']} (四大宽基合计={s['total_net']/1e8:+.2f}亿)")
```

---

## Layer 4: 行业/主题ETF 轮动信号

### 4.1 行业ETF资金流排名

```python
def industry_etf_rotation(period: str = "1w") -> dict:
    """
    行业/主题ETF资金轮动热力图。
    返回: {top_inflow, top_outflow, rotation_signal}
    """
    industry_codes = [
        c for c, info in CORE_ETFS.items() if info["cat"] in ("行业", "主题")
    ]

    flows = []
    for code in industry_codes:
        try:
            f = etf_multiperiod_fund_flow(code, [period])
            if period in f:
                flows.append({
                    "code": code,
                    "name": CORE_ETFS[code]["name"],
                    "style": CORE_ETFS[code].get("style", ""),
                    "main_net": f[period]["main_net"],
                    "days": f[period].get("days", 0),
                })
        except Exception:
            continue
        time.sleep(0.3)

    flows.sort(key=lambda x: x["main_net"], reverse=True)

    inflow_count = sum(1 for f in flows if f["main_net"] > 0)
    if inflow_count >= len(flows) * 0.7:
        rotation = "🔥 行业全面流入——情绪高涨"
    elif inflow_count <= len(flows) * 0.3:
        rotation = "❄️ 行业全面流出——情绪低迷"
    else:
        top3 = [f["name"] for f in flows[:3]]
        bot3 = [f["name"] for f in flows[-3:]]
        rotation = f"🔄 轮动分化: {', '.join(bot3)} → {', '.join(top3)}"

    return {
        "period": period,
        "total_etfs": len(flows),
        "top_inflow": flows[:5],
        "top_outflow": flows[-5:][::-1],
        "rotation_signal": rotation,
    }
```

### 4.2 ETF 与板块资金流交叉验证

```python
# ETF行业 → 概念板块映射
ETF_TO_CONCEPT = {
    "芯片":   ["半导体概念", "芯片概念", "存储芯片", "先进封装"],
    "半导体": ["半导体概念", "芯片概念", "光刻机(胶)"],
    "新能源": ["新能源", "光伏", "锂电池", "储能"],
    "军工":   ["军工", "军民融合", "大飞机"],
    "消费":   ["酿酒概念", "食品饮料", "新零售"],
    "医药":   ["医药", "创新药", "医疗器械"],
    "云计算": ["算力概念", "云计算", "大数据"],
    "游戏":   ["云游戏", "网络游戏", "元宇宙"],
    "券商":   ["券商概念", "互联金融"],
}

def cross_validate_with_capital_flow(etf_rotation: dict, sector_flow: dict) -> list[dict]:
    """
    ETF行业轮动 + 概念板块资金流 交叉验证。
    
    验证规则:
    - ETF流入 + 对应板块流入 → ✅ 双确认（最高置信度）
    - ETF流入 + 对应板块流出 → ⚠️ 背离（机构买、游资未跟）
    - ETF流出 + 对应板块流入 → ⚠️ 游资炒作（机构未跟）
    
    sector_flow: 来自 capital-flow-tracker 的 concept_sector_fund_flow() 结果
    """
    validations = []
    for etf in etf_rotation.get("top_inflow", []) + etf_rotation.get("top_outflow", []):
        style = etf.get("style", "")
        etf_name = etf.get("name", "")
        etf_net = etf.get("main_net", 0)
        etf_dir = "流入" if etf_net > 0 else "流出"

        concepts = ETF_TO_CONCEPT.get(style, [])
        if not concepts:
            for key, vals in ETF_TO_CONCEPT.items():
                if key in etf_name or key in style:
                    concepts = vals
                    break

        same_dir = []
        opp_dir = []
        for s in sector_flow.get("sectors", []):
            for concept in concepts:
                if concept in s.get("name", ""):
                    if (s.get("main_net", 0) > 0) == (etf_net > 0):
                        same_dir.append(s["name"])
                    else:
                        opp_dir.append(s["name"])

        if same_dir and not opp_dir:
            confidence = "✅ 双确认"
        elif same_dir and opp_dir:
            confidence = "⚠️ 部分背离"
        elif opp_dir and not same_dir:
            confidence = "❌ 背离（ETF与板块反向）"
        else:
            confidence = "➖ 数据不足"

        validations.append({
            "etf": etf_name,
            "etf_direction": etf_dir,
            "same_dir_sectors": same_dir,
            "opp_dir_sectors": opp_dir,
            "confidence": confidence,
        })

    return validations
```

---

## Layer 5: 多维盘面综合分析（核心能力）

### 5.1 六维盘面分析框架

```
                    ┌──────────────────────────┐
                    │    ETF资金流（本skill）    │
                    │  机构/配置型资金意图       │
                    └────────────┬─────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ 个股板块资金流 │    │  涨停板情绪    │    │  政策事件催化  │
│ (capital-flow │    │ (limit-up     │    │ (policy-event │
│  -tracker)    │    │  -tracker)    │    │  -tracker)    │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                             ▼
                  ┌───────────────────┐
                  │   盘面综合判断     │
                  │ 风格 + 方向 + 强度 │
                  └───────────────────┘
```

| 维度 | 数据来源 | 分析内容 | 权重 |
|------|---------|---------|------|
| 🏛️ **ETF资金流** | 本skill | 宽基风格、行业轮动、增量信号 | **25%** |
| 💰 **板块资金流** | capital-flow-tracker | 概念板块主力净流入排名 | **25%** |
| 📈 **涨停情绪** | limit-up-tracker | 涨停数、连板高度、炸板率 | **20%** |
| 📰 **政策事件** | policy-event-tracker | 近期政策催化 | **15%** |
| 🔍 **龙虎榜** | capital-flow-tracker | 机构/游资动向 | **10%** |
| 📊 **北向资金** | a-stock-data §3.2 | 外资方向 | **5%** |

> **交叉验证规则:**
> - 4+ 维度同向 → 🟢 高置信度
> - 2-3 维度同向 → 🟡 中等置信度
> - 维度分歧 → 🔴 低置信度（观望）

### 5.2 盘面综合分析实现

```python
def market_panorama_analysis(
    etf_flow: dict = None,
    sector_flow: dict = None,
    limit_up_data: dict = None,
    policy_events: list = None,
) -> dict:
    """
    多维盘面综合分析。
    各参数可由其他skill获取后传入，None则跳过该维度。
    返回: {dimensions, consensus, risks, verdict}
    """
    analysis = {
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dimensions": {},
        "consensus": {},
        "risks": [],
    }

    # ━━━ 维度1: ETF资金流 ━━━
    etf_signals = {"direction": "neutral", "strength": "弱", "details": []}
    if etf_flow:
        wide = etf_flow.get("style_groups", {})
        total_wide = wide.get("large_cap", {}).get("1w", 0) + wide.get("small_cap", {}).get("1w", 0)
        if total_wide > 5e8:
            etf_signals = {"direction": "bullish", "strength": "强",
                "details": [f"宽基ETF周净流入 {total_wide/1e8:.1f}亿"]}
        elif total_wide > 0:
            etf_signals = {"direction": "bullish", "strength": "中",
                "details": [f"宽基ETF周净流入 {total_wide/1e8:.1f}亿"]}
        elif total_wide < -5e8:
            etf_signals = {"direction": "bearish", "strength": "强",
                "details": [f"宽基ETF周净流出 {abs(total_wide)/1e8:.1f}亿"]}
        else:
            etf_signals["details"].append("资金流微弱，方向不明")
        inc = etf_flow.get("incremental_signal", {})
        if inc.get("1w", {}).get("all_inflow"):
            etf_signals["details"].append("🚀 四大宽基同向流入，增量入场信号")
    analysis["dimensions"]["etf_flow"] = etf_signals

    # ━━━ 维度2: 板块资金流 ━━━
    sector_signals = {"direction": "neutral", "details": []}
    if sector_flow:
        sectors = sector_flow.get("sectors", [])
        if sectors:
            inflow = sum(s.get("main_net", 0) for s in sectors[:10] if s.get("main_net", 0) > 0)
            outflow = sum(abs(s.get("main_net", 0)) for s in sectors[-10:] if s.get("main_net", 0) < 0)
            if inflow > outflow * 1.5:
                sector_signals = {"direction": "bullish",
                    "details": [f"板块流入占优 (入={inflow/1e8:.1f}亿 vs 出={outflow/1e8:.1f}亿)"]}
            elif outflow > inflow * 1.5:
                sector_signals = {"direction": "bearish",
                    "details": [f"板块流出占优"]}
            else:
                sector_signals["details"].append("板块资金均衡")
    analysis["dimensions"]["sector_flow"] = sector_signals

    # ━━━ 维度3: 涨停情绪 ━━━
    limit_up_signals = {"direction": "neutral", "details": []}
    if limit_up_data:
        zt = limit_up_data.get("zt_count", 0)
        br = limit_up_data.get("break_rate", 0)
        mh = limit_up_data.get("max_height", 0)
        if zt >= 80 and br < 30:
            limit_up_signals = {"direction": "bullish",
                "details": [f"涨停{zt}只 炸板率{br}% 高标{mh}板——情绪旺盛"]}
        elif zt < 30 and br > 50:
            limit_up_signals = {"direction": "bearish",
                "details": [f"涨停仅{zt}只 炸板率{br}%——情绪低迷"]}
        else:
            limit_up_signals["details"].append(f"涨停{zt}只 炸板率{br}% 高标{mh}板")
    analysis["dimensions"]["limit_up"] = limit_up_signals

    # ━━━ 维度4: 政策事件 ━━━
    policy_signals = {"direction": "neutral", "details": []}
    if policy_events:
        high = [e for e in policy_events if e.get("impact", "") in ("高", "颠覆")]
        if high:
            policy_signals["details"].append(f"高影响事件{len(high)}个: {high[0].get('title','')[:50]}")
        else:
            policy_signals["details"].append("近期无高影响政策事件")
    analysis["dimensions"]["policy"] = policy_signals

    # ━━━ 综合共识 ━━━
    dirs = [etf_signals["direction"], sector_signals["direction"], limit_up_signals["direction"]]
    bull = sum(1 for d in dirs if d == "bullish")
    bear = sum(1 for d in dirs if d == "bearish")

    if bull >= 3:
        analysis["consensus"] = {"direction": "bullish", "confidence": "高",
            "summary": "🟢 三维共振看多——ETF+板块+情绪同向"}
    elif bull >= 2:
        analysis["consensus"] = {"direction": "bullish", "confidence": "中",
            "summary": "🟡 偏多——多数维度看多，关注分歧"}
    elif bear >= 3:
        analysis["consensus"] = {"direction": "bearish", "confidence": "高",
            "summary": "🔴 三维共振看空——资金离场+情绪低迷"}
    elif bear >= 2:
        analysis["consensus"] = {"direction": "bearish", "confidence": "中",
            "summary": "🟠 偏空——多数维度看空，控制仓位"}
    else:
        analysis["consensus"] = {"direction": "neutral", "confidence": "低",
            "summary": "➖ 方向不明确——各维度分歧，观望"}

    # 风险提示
    if etf_signals["direction"] == "bearish" and limit_up_signals["direction"] == "bullish":
        analysis["risks"].append("⚠️ ETF流出+涨停活跃→游资炒作，机构撤退")
    if sector_signals["direction"] == "bullish" and etf_signals["direction"] == "bearish":
        analysis["risks"].append("⚠️ 板块流入但ETF流出→游资主导，配置资金未跟")

    return analysis
```

---

## Layer 6: 综合报告生成

### 6.1 一键 ETF 资金流全景报告

```python
def etf_flow_report(top_n: int = 20, period: str = "1w") -> dict:
    """ETF资金流全景报告"""
    report = {}
    print("[1/3] 宽基ETF风格分析...")
    report["style_analysis"] = wide_etf_style_analysis()
    print("[2/3] 行业ETF轮动扫描...")
    report["rotation"] = industry_etf_rotation(period)
    print("[3/3] 核心ETF资金流排名...")
    report["core_ranking"] = core_etf_flow_scan(period)
    return report


def print_etf_flow_report(report: dict):
    """打印ETF资金流全景报告"""
    print("=" * 80)
    print("  📊 A股ETF资金流全景报告")
    print(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    # 1. 宽基风格
    print_style_analysis(report["style_analysis"])

    # 2. 行业轮动
    rot = report["rotation"]
    print(f"\n{'─' * 60}")
    print(f"  🏭 行业ETF轮动 ({rot['period']})")
    print(f"{'─' * 60}")
    print(f"  信号: {rot['rotation_signal']}")
    print(f"\n  🔥 流入 TOP 5:")
    for etf in rot["top_inflow"]:
        print(f"    {etf['name']:<14s} ({etf['style']}): {etf['main_net']/1e8:+.2f}亿")
    print(f"\n  💧 流出 TOP 5:")
    for etf in rot["top_outflow"]:
        print(f"    {etf['name']:<14s} ({etf['style']}): {etf['main_net']/1e8:+.2f}亿")

    # 3. 核心ETF排名
    ranking = report["core_ranking"]
    print(f"\n{'─' * 60}")
    print(f"  🏆 核心ETF资金流排名 TOP 10")
    print(f"{'─' * 60}")
    for i, etf in enumerate(ranking[:10]):
        direction = "🔥" if etf["main_net"] > 0 else "💧"
        print(f"  {i+1:2d}. {direction} [{etf['cat']}] {etf['name']:<16s} "
              f"{etf['main_net']/1e8:>+8.2f}亿 ({etf['days']}天)")

    print(f"\n{'=' * 80}")
    print("  ⚠️ 研究声明: 数据基于公开API，仅供参考，不构成投资建议。")
    print(f"{'=' * 80}")
```

---

## 盘面分析典型场景

### 场景1: 判断市场方向
```
1. 四大宽基ETF近1周资金流 → 全部流入/流出/分歧？
2. 增量信号: 四线同向流入 = 增量入场
3. 风格: 大盘 vs 中小盘 → 防御/进攻
```

### 场景2: 确认行业轮动
```
1. 行业ETF TOP流入 vs 概念板块 TOP流入 → 是否一致？
2. 一致 → 轮动高置信度
3. 背离 → 游资炒作，机构未跟
```

### 场景3: 风格切换预警
```
1. 大盘 vs 中小盘资金流对比
2. 成长 vs 价值资金流对比
3. 近1周 vs 近1月趋势 → 是否切换？
```

### 场景4: 情绪背离检测
```
1. ETF流入 + 涨停低迷 → 机构布局，游资休息（蓄力期）
2. ETF流出 + 涨停活跃 → 游资炒作，机构撤退（风险）
3. 两维同向 → 共振确认
```

---

## 常用调用组合

| 场景 | 调用链 |
|------|--------|
| 市场风向判断 | `wide_etf_style_analysis()` → 看增量信号+风格对比 |
| 行业轮动扫描 | `industry_etf_rotation("1w")` → 流入/流出TOP5 |
| 核心ETF排名 | `core_etf_flow_scan("1w")` → 主力净流入排名 |
| ETF实时行情 | `tencent_etf_quotes(codes)` → 涨跌幅+换手+市值 |
| 单ETF深度分析 | `etf_multiperiod_fund_flow(code)` → 6周期聚合 |
| 盘面综合分析 | `market_panorama_analysis(etf, sector, limit_up, policy)` |
| 完整报告 | `etf_flow_report()` → `print_etf_flow_report()` |
| ETF+板块双确认 | `cross_validate_with_capital_flow(rotation, sector_flow)` |

## 核心ETF代码速查

| 代码 | 名称 | 类别 | 跟踪指数 |
|------|------|------|---------|
| 510300 | 沪深300ETF | 宽基 | 沪深300 |
| 588000 | 科创50ETF | 宽基 | 科创50 |
| 510500 | 中证500ETF | 宽基 | 中证500 |
| 159915 | 创业板ETF | 宽基 | 创业板指 |
| 510050 | 上证50ETF | 宽基 | 上证50 |
| 159995 | 芯片ETF | 行业 | 国证芯片 |
| 159845 | 中证1000ETF | 宽基 | 中证1000 |
| 512880 | 证券ETF | 行业 | 证券公司 |
| 512480 | 半导体ETF | 行业 | 半导体 |
| 510880 | 红利ETF | 策略 | 红利指数 |
| 518880 | 黄金ETF | 商品 | 黄金 |

## ETF 资金流解读原则

| 现象 | 含义 | 置信度 |
|------|------|--------|
| 四大宽基同向净流入 | 增量资金入场 | 高 |
| 宽基流入 + 行业流出 | 先铺底仓，轮动未开始 | 中 |
| 宽基流出 + 个别行业流入 | 存量博弈，结构性行情 | 中 |
| 行业ETF+概念板块双流入 | 轮动确认 | 高 |
| ETF流入 + 涨停低迷 | 机构布局，游资休息 | 中 |
| ETF流出 + 涨停活跃 | 游资主导，机构撤退（风险） | 高 |

## 风险声明

- ETF 资金流数据基于东方财富公开 API（push2/push2his），数据延迟 3-5 秒
- 主力/超大单/大单分类基于单笔成交规模阈值，不完全等同于机构/游资分类
- 所有分析仅供参考，不构成投资建议
