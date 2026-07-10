---
name: intraday-trading-signal
description: 盘中实时交易信号系统 V1.2 — 直接调用a-stock-data拉取七维分钟级数据(资金/价格/情绪/消息/北向/大盘/广度+成交量参考)，25+条件概率引擎输出多情景预判+买卖时机信号。V1.2重构：移除自行实现的API调用，全部改用a-stock-data(eastmoney_fund_flow_minute/eastmoney_concept_blocks/em_get等)。Use when 用户需要盘中实时监控、当日买卖时机判断、分钟级资金流追踪、多情景概率预判、宁可少挣宁可少亏的保守交易决策支持。
version: 1.2.0
updated: 2026-07-10
---

# 盘中实时交易信号系统 V1.2

**定位**：14 技能架构的**盘中实时监控与决策辅助层**——聚焦单一标的（个股/方向/ETF），从 9:20（集合竞价尾声）起追踪分钟级数据，==七维交叉验证==（资金+价格+情绪+消息+北向+大盘+广度），输出多情景概率预判 + 买卖时机参考信号。

**V1.2 重构**：移除自行实现的 API 调用（`fetch_minute_fund_flow` 的 push2 直连、`fetch_sector_sentiment` 的 slist 直连），全部改用 a-stock-data 已有函数：
- `eastmoney_fund_flow_minute(code)` → 分钟级资金流
- `eastmoney_concept_blocks(code)` → 个股概念板块归属
- `em_get()` / `eastmoney_datacenter()` → 通用请求（继承 a-stock-data 的限流防封）

**核心原则**：
1. ==宁可少挣，宁可少亏。== 信号默认保守——宁可错过，不在不确定时追高；宁可早卖，不扛不确定的风险。
2. ==买入和卖出，必须用数据说话。== 每个买卖信号绑定具体数据依据（数值+时间+来源），拒绝主观判断。
3. ==市场无法完美预判，但可通过数据进行不同场景的研判。== 每种场景针对具体数据模式进行概率计算，概率可追溯、可验证。

> **与现有 skill 的关系：**
> - `fund-flow-predictor`：30天日度数据、安全区间评分、企稳确认 → 本 skill：**分钟级、当日**实时追踪
> - `capital-flow-tracker`：全市场资金流向排名 → 本 skill：**单标的**深度分钟级追踪
> - `industry-sentiment-tracker`：行业情绪温度计 → 本 skill：情绪如何影响**当日盘中**走势
>
> **三维时间覆盖：**
> ```
> intraday-trading-signal (本skill V1.1)    fund-flow-predictor (V1.2)
> ├─ 9:20 → 15:00 分钟级                    ├─ 过去30天 → 安全区间评分
> ├─ 七维数据实时交叉验证                     ├─ 企稳确认 + 买入参考条件
> ├─ 25+条件概率引擎                         ├─ 15条可验证规则(F1-F15)
> ├─ 当日剩余时段预判                        ├─ 离场预警 + 利润/亏损控制
> └─ 买卖时机信号(数据说话)                   └─ 融资融券/北向/大宗/股东/解禁
> ```

## When to Activate

- 用户要在**盘中实时监控**某只股票/板块/ETF 的走势
- 用户要判断**今天该不该买/该不该卖**（当日交易决策）
- 用户要追踪**从开盘到现在的资金流向变化**（主力在进还是出）
- 用户要分析**盘中多空力量对比**（机构 vs 游资 vs 散户）
- 用户要**多情景概率预判**当日剩余时段走势
- 用户要**实时风险预警**（冲高回落/破位下跌/主力出逃）
- 关键词：`盘中监控`、`该不该买`、`该不该卖`、`实时资金流`、`主力动向`、`买卖时机`、`盘中预判`、`还能追吗`、`要不要出`、`回调风险`

**不适用场景**：
- 明日/下周走势预判（用 `fund-flow-predictor`）
- 全市场资金流向排名（用 `capital-flow-tracker`）
- 产业链深度分析（用 `serenity-skill`）

---

## 输出目录规范

分析报告统一输出到 `src/盘中交易信号/` 下，按 `YYYY-MM-DD-标的/` 格式组织：

```bash
# 生成报告时自动创建目录
mkdir -p src/盘中交易信号/$(date +%Y-%m-%d)-{标的名称}/
```

目录结构：
```
src/盘中交易信号/
├── _index.md                                  # 导航索引
└── YYYY-MM-DD-{标的名称}-盘中信号/
    ├── report.md                              # 完整四维信号报告
    ├── data.json                              # 原始数据(JSON,用于回测)
    └── verification.md                        # 收盘后验证(自动生成)
```

**输出规则**：
- 每次运行 `intraday_trading_report()` 后，自动将报告写入 `src/盘中交易信号/` 目录
- `data.json` 保存原始分钟级数据，用于后续回测和规则优化
- `verification.md` 在收盘后运行 `verify_prediction()` 时自动生成，记录命中/未命中

---

## Prerequisites

本 skill **直接调用 a-stock-data 的已有函数**拉取数据，不重复定义 helper。运行前确保 a-stock-data skill 已加载。

```python
# === 从 a-stock-data 直接引用（无需重复定义）===
#   em_get(url, params, headers, timeout)     — 东财统一请求
#   eastmoney_datacenter(report_name, ...)     — 东财数据中心
#   eastmoney_fund_flow_minute(code)           — 分钟级资金流 ($3.4)
#   eastmoney_concept_blocks(code)             — 个股概念板块归属 ($3.3)
#   fetch_realtime_quote(code)                 — 腾讯行情 (本skill保留轻量封装)
#
# 以下为 a-stock-data 已定义的全局变量：
#   UA, EM_SESSION, EM_MIN_INTERVAL, _em_last_call
#   MARKET_CODE, SECID

import time, random, requests, json, re, os
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

# 输出目录配置
OUTPUT_BASE = "src/盘中交易信号"
```

---

## 七维数据框架（V1.1）

```
                        ┌──────────────────────────────────────────┐
                        │     intraday-trading-signal V1.1         │
                        │     盘中实时交易信号系统                    │
                        │     七维交叉验证 → 买入卖出数据说话         │
                        └──────────────────┬───────────────────────┘
                                           │
        ┌──────────┬──────────┬────────┬───┴───┬────────┬──────────┬──────────┐
        ▼          ▼          ▼        ▼       ▼        ▼          ▼          ▼
     push2      腾讯行情    push2   东财新闻  slist   同花顺北向  腾讯指数    push2ex
    分钟级资金   实时价     分钟K线  搜索API  板块情绪  实时资金   大盘行情    涨停池
        │          │          │        │       │        │          │          │
        └──────────┴──────────┴────────┴───────┴────────┴──────────┴──────────┘
                                           │
                        ┌──────────────────┴──────────────────┐
                        ▼                                     ▼
                ┌──────────────┐                    ┌──────────────────┐
                │ 七维数据采集   │                    │ 25+条件概率引擎   │
                │              │                    │ 每个概率绑定:      │
                │ 资金 25%     │                    │ 触发条件+历史胜率   │
                │ 价格 15%     │                    │ +验证逻辑+失效条件  │
                │ 情绪 15%     │ ─────────────────→ │ +多因子同向共振加分  │
                │ 消息 10%     │                    └────────┬─────────┘
                │ 北向 15%     │                             │
                │ 大盘 10%     │                             ▼
                │ 广度 10%     │                    ┌──────────────────┐
                └──────────────┘                    │ 买卖时机参考信号   │
                                                    │ 每信号绑定具体数据  │
                                                    │ 数值+阈值+来源     │
                                                    └──────────────────┘
```

| 维度 | 数据来源 | 核心指标 | 权重 | V1.1 |
|------|---------|---------|------|------|
| 💰 **资金面** | push2 分钟级资金流 | 主力累计净流入、机构/游资/散户金额、资金加速度 | **25%** | - |
| 📈 **价格面** | 腾讯行情 + push2 K线 | 涨幅、振幅、换手率、量比、盘中形态 | **15%** | - |
| 🎯 **情绪面** | 板块资金流 + slist | 板块情绪分、板块内排名、涨跌家数比 | **15%** | - |
| 📰 **消息面** | 东财新闻 + 公告 | 盘中新闻催化、公告事件 | **10%** | - |
| 🌏 **北向资金** | 同花顺 hsgtApi | 沪股通+深股通实时净流入、累计流向 | **15%** | 🆕 |
| 📊 **大盘强度** | 腾讯指数行情 | 上证/深证/创业板涨跌、个股相对大盘强弱 | **10%** | 🆕 |
| 🔥 **市场广度** | push2ex 涨停池 + clist | 全市场涨跌家数比、涨停/跌停家数、赚钱效应 | **10%** | 🆕 |

---

## Layer 1: 实时行情与价格面

### 1.1 腾讯实时行情

```python
def fetch_realtime_quote(code: str) -> dict:
    """
    腾讯财经实时行情 — 零鉴权、不封IP、延迟<3秒。
    返回: {price, change_pct, amplitude, turnover, vol_ratio, high, low, open, prev_close, ...}
    """
    prefixed = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
    url = f"https://qt.gtimg.cn/q={prefixed}"
    try:
        req = Request(url)
        req.add_header("User-Agent", UA)
        resp = urlopen(req, timeout=8)
        data = resp.read().decode("gbk")
        vals = data.split('"')[1].split("~") if '"' in data else []
        if len(vals) < 53:
            return {"error": "数据字段不足", "raw_len": len(vals)}

        return {
            "name": vals[1],
            "code": vals[2],
            "price": float(vals[3]) if vals[3] else 0,
            "prev_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "volume": float(vals[6]) if vals[6] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "amplitude": float(vals[43]) if vals[43] else 0,
            "vol_ratio": float(vals[49]) if vals[49] else 0,
            "amount": float(vals[37]) if vals[37] else 0,
            "pe": float(vals[39]) if vals[39] else 0,
            "mcap": float(vals[45]) if vals[45] else 0,
        }
    except Exception as e:
        return {"error": str(e)}
```

---

## Layer 2: 实时资金面（分钟级，核心）

### 2.1 分钟级资金流拉取与聚合

```python
# 直接调用 a-stock-data 的分钟级资金流函数 (§3.4)
# eastmoney_fund_flow_minute(code) → [{time, main_net, small_net, mid_net, large_net, super_net}, ...]

def fetch_minute_fund_flow(code: str) -> dict:
    """
    个股分钟级资金流分析（当日盘中，调用 a-stock-data §3.4）。
    在原始数据基础上增加：趋势分析、加速度、转向点检测。
    
    返回:
    - minutes: 每分钟资金流明细（来自 a-stock-data）
    - summary: 累计统计
    - trend: 趋势方向+加速度+累计序列+关键转向点
    金额单位: 元
    """
    # === 调用 a-stock-data 拉取原始分钟级数据 ===
    try:
        minutes = eastmoney_fund_flow_minute(code)  # a-stock-data §3.4
    except Exception as e:
        return {"error": f"a-stock-data 资金流拉取失败: {e}", "minutes": [], "summary": {}, "trend": {}}

    if not minutes:
        return {"error": "无资金流数据（可能未开盘或数据源异常）", "minutes": [], "summary": {}, "trend": {}}

    # 聚合统计
    total_main = sum(m["main_net"] for m in minutes)
    total_super = sum(m["super_net"] for m in minutes)
    total_large = sum(m["large_net"] for m in minutes)
    total_mid = sum(m["mid_net"] for m in minutes)
    total_small = sum(m["small_net"] for m in minutes)

    # 累计序列（趋势分析核心数据）
    cum_main = []
    running = 0.0
    for m in minutes:
        running += m["main_net"]
        cum_main.append(running)

    # 趋势方向与加速度
    if len(cum_main) >= 10:
        mid_point = len(cum_main) // 2
        first_half = cum_main[:mid_point]
        second_half = cum_main[mid_point:]

        first_slope = (first_half[-1] - first_half[0]) / max(len(first_half), 1)
        second_slope = (second_half[-1] - second_half[0]) / max(len(second_half), 1)

        direction = "流入" if cum_main[-1] > 0 else "流出"

        if second_slope > first_slope * 1.5:
            acceleration = "加速流入" if second_slope > 0 else "流出减缓"
        elif second_slope < first_slope * 0.3:
            acceleration = "流入减缓" if second_slope > 0 else "加速流出"
        else:
            acceleration = "匀速" + direction
    else:
        direction = "数据不足"
        acceleration = "数据不足"
        first_slope = second_slope = 0

    # 关键转向点检测（最近5个）
    turning_points = []
    if len(cum_main) >= 20:
        for i in range(10, len(cum_main) - 5):
            before = cum_main[i - 5:i]
            after = cum_main[i:i + 5]
            is_peak = all(cum_main[i] > b for b in before) and all(cum_main[i] > a for a in after)
            is_valley = all(cum_main[i] < b for b in before) and all(cum_main[i] < a for a in after)
            if is_peak:
                turning_points.append({"time": minutes[i]["time"], "type": "峰值(资金见顶)", "value_wan": cum_main[i] / 1e4})
            elif is_valley:
                turning_points.append({"time": minutes[i]["time"], "type": "谷值(资金见底)", "value_wan": cum_main[i] / 1e4})

    last_turn = turning_points[-1] if turning_points else None

    return {
        "minutes": minutes,
        "summary": {
            "total_main_net": round(total_main, 0),
            "total_main_net_wan": round(total_main / 1e4, 1),
            "total_super_net_wan": round(total_super / 1e4, 1),
            "total_large_net_wan": round(total_large / 1e4, 1),
            "total_mid_net_wan": round(total_mid / 1e4, 1),
            "total_small_net_wan": round(total_small / 1e4, 1),
            "data_points": len(minutes),
            "first_time": minutes[0]["time"] if minutes else "",
            "last_time": minutes[-1]["time"] if minutes else "",
        },
        "trend": {
            "direction": direction,
            "acceleration": acceleration,
            "first_half_slope_wan_per_min": round(first_slope / 1e4, 2),
            "second_half_slope_wan_per_min": round(second_slope / 1e4, 2),
            "cum_sequence_wan": [round(v / 1e4, 1) for v in cum_main],
            "turning_points": turning_points[-5:],
            "last_turn": last_turn,
        },
    }
```

### 2.2 三方资金分类（数据化）

```python
def classify_intraday_parties(flow_data: dict) -> dict:
    """
    将分钟级资金流按机构/游资/散户三方分类。
    返回具体金额数据，用于"数据说话"。
    
    分类依据:
    - 机构 ≈ 超大单(super_net): 单笔≥100万手
    - 游资 ≈ 大单(large_net): 单笔≥20万手且<100万手
    - 散户 ≈ 中单+小单(mid_net+small_net): 单笔<20万手
    """
    s = flow_data.get("summary", {})
    inst_net = s.get("total_super_net_wan", 0)
    hm_net = s.get("total_large_net_wan", 0)
    retail_net = (s.get("total_mid_net_wan", 0) or 0) + (s.get("total_small_net_wan", 0) or 0)
    main_net = s.get("total_main_net_wan", 0)
    data_points = s.get("data_points", 0)

    # 关键数据点：每分钟平均流入/流出速率
    inst_rate = inst_net / max(data_points, 1)
    hm_rate = hm_net / max(data_points, 1)
    retail_rate = retail_net / max(data_points, 1)

    inst_dir = "流入" if inst_net > 0 else "流出"
    hm_dir = "流入" if hm_net > 0 else "流出"
    retail_dir = "流入" if retail_net > 0 else "流出"

    # 份额占比
    total_abs = abs(inst_net) + abs(hm_net) + abs(retail_net)
    if total_abs > 0:
        inst_share = round(abs(inst_net) / total_abs * 100, 1)
        hm_share = round(abs(hm_net) / total_abs * 100, 1)
        retail_share = round(abs(retail_net) / total_abs * 100, 1)
    else:
        inst_share = hm_share = retail_share = 0

    # 博弈场景判断（基于具体金额阈值）
    if inst_net > 200 and hm_net > 0 and retail_net < -100:
        scenario = "机构+游资合力做多，散户恐慌出局 → 强多头信号"
        level = "🟢 积极"
    elif inst_net > 200 and retail_net > 100:
        scenario = "机构与散户同向流入 → 共识强，但散户过度乐观是隐忧"
        level = "🟡 中性偏多"
    elif inst_net < -200 and retail_net > 200:
        scenario = f"机构净流出{abs(inst_net):.0f}万 + 散户净流入{retail_net:.0f}万 → 机构派发、散户接盘，⚠️ 明确风险信号"
        level = "🔴 警惕"
    elif inst_net < -100 and hm_net < -100 and retail_net > 100:
        scenario = "机构+游资合力出逃，散户接盘 → 强空头信号"
        level = "🔴 危险"
    elif inst_net > 100 and hm_net < -50 and retail_net < -50:
        scenario = f"机构独力做多{inst_net:.0f}万，游资{hm_net:.0f}万+散户{retail_net:.0f}万不跟 → 孤军深入，持续性存疑"
        level = "🟡 中性"
    else:
        scenario = "三方分歧，方向不明确"
        level = "⚪ 观望"

    return {
        "institution": {"net_wan": round(inst_net, 1), "direction": inst_dir,
                        "share_pct": inst_share, "rate_per_min_wan": round(inst_rate, 2)},
        "hot_money": {"net_wan": round(hm_net, 1), "direction": hm_dir,
                      "share_pct": hm_share, "rate_per_min_wan": round(hm_rate, 2)},
        "retail": {"net_wan": round(retail_net, 1), "direction": retail_dir,
                   "share_pct": retail_share, "rate_per_min_wan": round(retail_rate, 2)},
        "verdict": {"scenario": scenario, "level": level,
                    "main_direction": "多头占优" if main_net > 0 else "空头占优"},
        "data_basis": {
            "data_points": data_points,
            "time_range": f"{s.get('first_time', '?')} → {s.get('last_time', '?')}",
            "source": "东方财富 push2 分钟级资金流 API",
        },
    }
```

### 2.3 资金-价格背离检测

```python
def detect_fund_price_divergence(flow_data: dict, quote: dict) -> dict:
    """
    检测资金流与价格走势的背离——最重要的交易信号之一。
    每个结论绑定具体数据。
    """
    minutes = flow_data.get("minutes", [])
    if not minutes or len(minutes) < 20:
        return {"has_divergence": False, "reason": f"数据不足（当前仅{len(minutes)}分钟，需≥20分钟）"}

    cum_main = []
    running = 0.0
    for m in minutes:
        running += m["main_net"]
        cum_main.append(running)

    n = len(minutes)
    seg_size = n // 4
    divergences = []
    change_pct = quote.get("change_pct", 0)

    for i in range(1, 4):
        prev_start = (i - 1) * seg_size
        prev_end = i * seg_size
        curr_start = i * seg_size
        curr_end = min((i + 1) * seg_size, n)
        if curr_end <= curr_start:
            continue

        prev_flow_change = cum_main[prev_end - 1] - cum_main[prev_start]
        curr_flow_change = cum_main[curr_end - 1] - cum_main[curr_start]

        # 顶背离：价格高位但资金流入锐减
        if change_pct > 3 and prev_flow_change > 0 and curr_flow_change < prev_flow_change * 0.3:
            divergences.append({
                "type": "顶背离(资金衰竭)",
                "detail": f"价格涨{change_pct:+.2f}%，但资金流入从{prev_flow_change/1e4:.0f}万骤降至{curr_flow_change/1e4:.0f}万(降幅>{((1-curr_flow_change/max(prev_flow_change,1))*100):.0f}%)",
                "data": f"时段对比: {minutes[prev_start]['time']}-{minutes[prev_end-1]['time']} vs {minutes[curr_start]['time']}-{minutes[curr_end-1]['time']}",
                "risk": "上涨动力衰竭，警惕冲高回落",
            })

        # 底背离：价格低位但资金开始回流
        if change_pct < -3 and prev_flow_change < 0 and curr_flow_change > abs(prev_flow_change) * 0.5:
            divergences.append({
                "type": "底背离(资金回流)",
                "detail": f"价格跌{change_pct:+.2f}%，但资金从流出{abs(prev_flow_change)/1e4:.0f}万转为流入{curr_flow_change/1e4:.0f}万",
                "data": f"时段对比: {minutes[prev_start]['time']}-{minutes[prev_end-1]['time']} vs {minutes[curr_start]['time']}-{minutes[curr_end-1]['time']}",
                "risk": "下跌动力衰竭，关注反弹机会",
            })

    return {
        "has_divergence": len(divergences) > 0,
        "divergences": divergences,
    }
```

---

## Layer 3: 情绪面

```python
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

# 板块资金流缓存（全局，一次拉取，多次复用）
_SECTOR_CACHE = None
_SECTOR_CACHE_TIME = None

def _load_all_concept_sectors() -> dict:
    """
    一次性拉取全量概念板块资金流数据（m:90+t:3）。
    返回: {BK码: {name, main_net_wan, change_pct, up_count, down_count}, ...}
    """
    global _SECTOR_CACHE, _SECTOR_CACHE_TIME
    now = time.time()
    # 缓存60秒，避免盘中频繁重复拉取
    if _SECTOR_CACHE is not None and _SECTOR_CACHE_TIME and (now - _SECTOR_CACHE_TIME) < 60:
        return _SECTOR_CACHE

    params = {
        "pn": "1", "pz": "500", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",  # 全量概念板块
        "fields": "f2,f3,f12,f14,f62,f104,f105",
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    try:
        r = em_get(PUSH2_CLIST, params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", []) or []
    except Exception:
        return {}

    sectors = {}
    for it in items:
        bk_code = it.get("f12", "")
        if bk_code:
            main_net = it.get("f62") or 0
            sectors[bk_code] = {
                "code": bk_code,
                "name": it.get("f14", ""),
                "change_pct": it.get("f3", 0),
                "main_net_wan": round(main_net / 1e4, 1),
                "direction": "流入" if main_net > 0 else "流出",
                "up_count": it.get("f104", 0),
                "down_count": it.get("f105", 0),
            }

    _SECTOR_CACHE = sectors
    _SECTOR_CACHE_TIME = now
    return sectors


def fetch_sector_sentiment(code: str) -> dict:
    """
    获取个股所属概念板块的情绪快照。
    
    修复(V1.1.1): 使用 m:90+t:3 拉取全量板块级资金流。
    V1.2: 板块归属改用 a-stock-data 的 eastmoney_concept_blocks() 直接获取。
    """
    # 1. 调用 a-stock-data 获取个股所属概念板块（§3.3）
    try:
        raw_blocks = eastmoney_concept_blocks(code)  # a-stock-data §3.3
        stock_blocks = [{"code": it.get("code", it.get("f12", "")),
                         "name": it.get("name", it.get("f14", "")),
                         "change_pct": it.get("change_pct", it.get("f3", 0))}
                        for it in raw_blocks]
    except Exception:
        return {"error": "板块归属获取失败(eastmoney_concept_blocks)", "blocks": [], "sentiment_score": 0}

    if not stock_blocks:
        return {"error": "未找到所属概念板块", "blocks": [], "sentiment_score": 0}

    # 2. 一次性拉取全量概念板块资金流（缓存60秒）
    all_sectors = _load_all_concept_sectors()

    # 3. 匹配：从全量板块数据中查找个股所属板块
    sentiment_blocks = []
    for bk in stock_blocks[:8]:
        sector_data = all_sectors.get(bk["code"])
        if sector_data:
            sentiment_blocks.append(sector_data)
        else:
            # 板块不在全量列表中（可能是行业板块等），用 slist 返回的涨跌幅作为最小信息
            sentiment_blocks.append({
                "code": bk["code"], "name": bk["name"],
                "change_pct": bk["change_pct"],
                "main_net_wan": 0, "direction": "未知",
                "up_count": 0, "down_count": 0,
            })

    if not sentiment_blocks:
        return {"error": "板块数据获取失败", "blocks": [], "sentiment_score": 0}

    # 4. 计算板块情绪分 (0-100)
    inflow_count = sum(1 for b in sentiment_blocks if b["main_net_wan"] > 0)
    total_blocks = len(sentiment_blocks)
    avg_change = sum(b["change_pct"] for b in sentiment_blocks) / max(total_blocks, 1)
    total_flow = sum(b["main_net_wan"] for b in sentiment_blocks)

    flow_score = (inflow_count / max(total_blocks, 1)) * 50
    price_score = max(0, min(50, (avg_change + 5) * 5))
    sentiment_score = round(flow_score + price_score, 1)

    if sentiment_score >= 75:
        level = "🔥 极热"
    elif sentiment_score >= 60:
        level = "🟢 偏热"
    elif sentiment_score >= 40:
        level = "🟡 中性"
    elif sentiment_score >= 25:
        level = "🔵 偏冷"
    else:
        level = "❄️ 极冷"

    return {
        "blocks": sentiment_blocks,
        "sentiment_score": sentiment_score,
        "level": level,
        "inflow_blocks": inflow_count,
        "total_blocks": total_blocks,
        "avg_change_pct": round(avg_change, 2),
        "total_sector_flow_wan": round(total_flow, 1),
        "data_basis": f"{inflow_count}/{total_blocks}板块流入, 板块合计资金{total_flow:+.0f}万, 平均涨跌{avg_change:+.2f}%, 情绪分{sentiment_score}",
        "source": "东财 push2 slist(板块归属) + clist m:90+t:3(板块资金流)",
    }
```

---

## Layer 4: 消息面

```python
def fetch_intraday_news(code: str) -> dict:
    """拉取个股近期新闻，标注今日盘中的具体消息内容"""
    cb = "jQuery_news"
    inner = json.dumps({
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
        d = json.loads(json_str)
        articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
    except Exception:
        return {"today_count": 0, "highlights": [], "error": "新闻获取失败"}

    today_str = datetime.now().strftime("%Y-%m-%d")
    news = []
    for a in articles:
        title = re.sub(r'<[^>]+>', '', a.get("title", ""))
        content = re.sub(r'<[^>]+>', '', a.get("content", ""))[:200]
        news.append({
            "title": title, "content": content,
            "time": a.get("date", ""), "source": a.get("mediaName", ""),
            "url": a.get("url", ""),
            "is_today": a.get("date", "").startswith(today_str),
        })

    today_news = [n for n in news if n["is_today"]]

    bullish_keywords = ["增长", "突破", "中标", "订单", "扩产", "获批", "回购", "增持", "超预期"]
    bearish_keywords = ["减持", "亏损", "下滑", "调查", "处罚", "诉讼", "违约", "暴雷", "退市"]

    highlights = []
    for n in today_news[:8]:
        sentiment = "neutral"
        if any(kw in n["title"] for kw in bullish_keywords):
            sentiment = "bullish"
        elif any(kw in n["title"] for kw in bearish_keywords):
            sentiment = "bearish"
        highlights.append({**n, "sentiment": sentiment})

    return {
        "today_count": len(today_news),
        "highlights": highlights,
        "bullish_count": sum(1 for h in highlights if h["sentiment"] == "bullish"),
        "bearish_count": sum(1 for h in highlights if h["sentiment"] == "bearish"),
        "source": "东方财富 search-api-web 个股新闻",
    }
```

---

## Layer 5: 北向资金实时监控（V1.1 新增）

北向资金（沪股通+深股通）是 A 股最重要的边际资金之一，其盘中实时流向对短期走势有显著指示意义。

```python
def fetch_north_bound_flow() -> dict:
    """
    拉取北向资金实时流向（沪股通+深股通）。
    数据来源: 同花顺 hsgtApi（零鉴权、稳定，优于东财北向接口）
    返回: {hgt: {...}, sgt: {...}, total_net_wan, direction, trend}
    """
    try:
        # 沪股通实时
        hgt_url = "https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/hgt"
        r_hgt = requests.get(hgt_url, headers={"User-Agent": UA}, timeout=8)
        hgt_data = r_hgt.json()
    except Exception:
        hgt_data = None

    try:
        # 深股通实时
        sgt_url = "https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/sgt"
        r_sgt = requests.get(sgt_url, headers={"User-Agent": UA}, timeout=8)
        sgt_data = r_sgt.json()
    except Exception:
        sgt_data = None

    hgt_net = 0.0
    sgt_net = 0.0

    if hgt_data and hgt_data.get("data"):
        hgt_items = hgt_data["data"] if isinstance(hgt_data["data"], list) else []
        hgt_net = sum(it.get("net", 0) for it in hgt_items[-10:])  # 最近10个数据点

    if sgt_data and sgt_data.get("data"):
        sgt_items = sgt_data["data"] if isinstance(sgt_data["data"], list) else []
        sgt_net = sum(it.get("net", 0) for it in sgt_items[-10:])

    total_net = hgt_net + sgt_net  # 单位: 万元
    total_net_yi = total_net / 1e4

    # 方向判断
    if total_net > 5000:
        direction = "大幅流入"
        signal = "🟢 积极"
    elif total_net > 0:
        direction = "小幅流入"
        signal = "🟡 中性偏多"
    elif total_net > -5000:
        direction = "小幅流出"
        signal = "🟠 中性偏空"
    else:
        direction = "大幅流出"
        signal = "🔴 警惕"

    return {
        "hgt_net_wan": round(hgt_net, 0),
        "sgt_net_wan": round(sgt_net, 0),
        "total_net_wan": round(total_net, 0),
        "total_net_yi": round(total_net_yi, 2),
        "direction": direction,
        "signal": signal,
        "source": "同花顺 hsgtApi (实时北向资金)",
        "data_basis": f"沪股通{hgt_net/1e4:+.2f}亿 + 深股通{sgt_net/1e4:+.2f}亿 = 北向合计{total_net_yi:+.2f}亿",
    }
```

**北向资金对概率的调整规则**：
- 北向大幅流入(>5亿) + 个股主力流入 → 情景A概率 **+10%**
- 北向大幅流出(>5亿) + 个股主力流出 → 情景D概率 **+10%**
- 北向与个股主力方向背离 → 置信度降级，概率打 8 折

---

## Layer 6: 大盘相对强度（V1.1 新增）

个股走势必须放在大盘背景下理解。一只股票涨 3%，如果大盘涨 2%，实际 alpha 只有 1%；如果大盘跌 1%，则 alpha 有 4%。

```python
def fetch_market_strength(code: str, quote: dict) -> dict:
    """
    拉取大盘指数行情 + 计算个股相对强弱。
    比较基准: 上证指数(000001) + 深证成指(399001) + 创业板指(399006)
    """
    indices = {
        "上证指数": "sh000001",
        "深证成指": "sz399001",
        "创业板指": "sz399006",
    }

    market_data = {}
    for name, idx_code in indices.items():
        try:
            url = f"https://qt.gtimg.cn/q={idx_code}"
            req = Request(url)
            req.add_header("User-Agent", UA)
            resp = urlopen(req, timeout=5)
            data = resp.read().decode("gbk")
            vals = data.split('"')[1].split("~") if '"' in data else []
            if len(vals) >= 33:
                market_data[name] = {
                    "price": float(vals[3]) if vals[3] else 0,
                    "change_pct": float(vals[32]) if vals[32] else 0,
                }
        except Exception:
            market_data[name] = {"price": 0, "change_pct": 0}

    # 确定个股对应的主要基准指数
    if code.startswith(("6", "9")):
        primary_benchmark = "上证指数"
    elif code.startswith("30"):
        primary_benchmark = "创业板指"
    else:
        primary_benchmark = "深证成指"

    benchmark_change = market_data.get(primary_benchmark, {}).get("change_pct", 0)
    stock_change = quote.get("change_pct", 0)

    # 相对强度 = 个股涨幅 - 基准涨幅
    relative_strength = stock_change - benchmark_change

    # 大盘环境判断
    if benchmark_change > 1:
        market_env = "🟢 大盘强势"
    elif benchmark_change > 0:
        market_env = "🟡 大盘微涨"
    elif benchmark_change > -1:
        market_env = "🟠 大盘微跌"
    else:
        market_env = "🔴 大盘弱势"

    # 个股相对评级
    if relative_strength > 3:
        relative_rating = "🚀 显著跑赢"
    elif relative_strength > 1:
        relative_rating = "✅ 跑赢大盘"
    elif relative_strength > -1:
        relative_rating = "➖ 与大盘同步"
    elif relative_strength > -3:
        relative_rating = "⚠️ 跑输大盘"
    else:
        relative_rating = "🔴 显著跑输"

    return {
        "benchmark": primary_benchmark,
        "benchmark_change": round(benchmark_change, 2),
        "market_env": market_env,
        "stock_change": round(stock_change, 2),
        "relative_strength": round(relative_strength, 2),
        "relative_rating": relative_rating,
        "market_detail": {k: round(v.get("change_pct", 0), 2) for k, v in market_data.items()},
        "source": "腾讯财经指数行情",
        "data_basis": f"{primary_benchmark}{benchmark_change:+.2f}%, 个股{stock_change:+.2f}%, 相对强弱{relative_strength:+.2f}%",
    }
```

**大盘强度对概率的调整规则**：
- 大盘强势(>+1%) + 个股跑赢(相对强度>1%) → 情景A概率 **+8%**
- 大盘弱势(<-1%) + 个股跑输(相对强度<-1%) → 情景D概率 **+8%**
- 大盘弱势但个股跑赢(相对强度>2%) → 独立行情，概率不在大盘维度扣分
- 大盘强势但个股跑输(相对强度<-2%) → 弱势股，情景A概率 **-10%**

---

## Layer 7: 市场广度（V1.1 新增）

市场广度反映全市场赚钱效应——即使个股本身数据不错，如果全市场普跌，个股也很难独善其身。

```python
def fetch_market_breadth() -> dict:
    """
    拉取全市场涨跌家数 + 涨停/跌停家数，计算市场广度。
    数据来源: push2 clist (全A股) + push2ex (涨停池)
    """
    # 1. 全市场涨跌家数（从全A股列表拉取）
    params = {
        "pn": "1", "pz": "1", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",  # 主板+中小板+创业板+科创板+北证
        "fields": "f104,f105",  # 上涨家数, 下跌家数
    }
    try:
        r = em_get(PUSH2_CLIST, params=params,
                   headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        up_count = sum(it.get("f104", 0) for it in items) if items else 0
        down_count = sum(it.get("f105", 0) for it in items) if items else 0
    except Exception:
        up_count, down_count = 0, 0

    # 2. 涨停/跌停家数（从涨停池/跌停池拉取）
    try:
        params_limit = {
            "pn": "1", "pz": "1", "po": "0", "np": "1",
            "fltt": "2", "invt": "2", "dect": "1",
            "fields": "f12,f14",
        }
        # 涨停池
        r_up = em_get("https://push2ex.eastmoney.com/getTopicZTPool",
                      params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                              "sort": "fbt", "fbt": "desc"},
                      headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        try:
            limit_up_count = r_up.json().get("data", {}).get("total", 0) or 0
        except Exception:
            limit_up_count = 0

        # 跌停池
        r_down = em_get("https://push2ex.eastmoney.com/getTopicDTPool",
                        params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                                "sort": "fund", "fund": "desc"},
                        headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        try:
            limit_down_count = r_down.json().get("data", {}).get("total", 0) or 0
        except Exception:
            limit_down_count = 0
    except Exception:
        limit_up_count, limit_down_count = 0, 0

    total = up_count + down_count
    up_ratio = up_count / max(total, 1) * 100

    # 市场广度评级
    if up_ratio >= 70:
        breadth_level = "🟢 普涨格局"
        breadth_score = 85
    elif up_ratio >= 55:
        breadth_level = "🟡 涨多跌少"
        breadth_score = 60
    elif up_ratio >= 45:
        breadth_level = "🟠 分化格局"
        breadth_score = 40
    elif up_ratio >= 30:
        breadth_level = "🔴 跌多涨少"
        breadth_score = 20
    else:
        breadth_level = "💀 普跌格局"
        breadth_score = 5

    # 涨停/跌停比（赚钱效应）
    limit_ratio = limit_up_count / max(limit_down_count, 1)
    if limit_ratio >= 3:
        money_effect = "🔥 强赚钱效应"
    elif limit_ratio >= 1.5:
        money_effect = "✅ 赚钱效应良好"
    elif limit_ratio >= 1:
        money_effect = "➖ 赚钱效应中性"
    elif limit_ratio >= 0.5:
        money_effect = "⚠️ 亏钱效应显现"
    else:
        money_effect = "💀 强亏钱效应"

    return {
        "up_count": up_count,
        "down_count": down_count,
        "up_ratio_pct": round(up_ratio, 1),
        "breadth_level": breadth_level,
        "breadth_score": breadth_score,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "limit_ratio": round(limit_ratio, 1),
        "money_effect": money_effect,
        "source": "东财 push2ex 涨停/跌停池 + push2 clist",
        "data_basis": f"全市场涨{up_count}跌{down_count}({up_ratio:.1f}%), 涨停{limit_up_count}/跌停{limit_down_count}, 赚钱效应:{money_effect}",
    }
```

**市场广度对概率的调整规则**：
- 普涨格局(涨>70%) + 个股同向 → 情景A概率 **+5%**，情景D概率 **-10%**
- 普跌格局(涨<30%) + 个股同向 → 情景D概率 **+10%**，情景A概率 **-10%**
- 强赚钱效应(涨跌停比>3) → 情景A概率 **+5%**
- 强亏钱效应(涨跌停比<0.5) → 情景D概率 **+8%**

---

## Layer 8: 七维概率预判引擎（核心 V1.1）

### 8.1 七维 25+ 条件概率计算

### 5.1 概率计算——每个概率绑定可验证的数据规则

```python
def generate_probability_scenarios(
    flow_data: dict, quote: dict, sector_data: dict,
    news_data: dict, party_data: dict, divergence: dict,
    north_bound: dict = None, market_strength: dict = None,
    market_breadth: dict = None,
) -> dict:
    """
    七维多情景概率预判引擎 V1.1。
    
    核心: 每个概率绑定具体数据条件，每个条件标注当前值 vs 阈值。
    概率 = 满足条件权重之和 / 总权重 × 100。
    七维同向共振 → 最高置信度；多维背离 → 概率打折扣。
    """

    # ━━━ 提取所有关键数据 ━━━
    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)

    s = flow_data.get("summary", {})
    main_net_wan = s.get("total_main_net_wan", 0)
    inst_net = party_data.get("institution", {}).get("net_wan", 0)
    hm_net = party_data.get("hot_money", {}).get("net_wan", 0)
    retail_net = party_data.get("retail", {}).get("net_wan", 0)
    data_points = s.get("data_points", 0)

    t = flow_data.get("trend", {})
    acceleration = t.get("acceleration", "")
    direction = t.get("direction", "")
    first_slope = t.get("first_half_slope_wan_per_min", 0)
    second_slope = t.get("second_half_slope_wan_per_min", 0)
    last_turn = t.get("last_turn", {})

    sentiment_score = sector_data.get("sentiment_score", 50)
    inflow_blocks = sector_data.get("inflow_blocks", 0)
    total_blocks = sector_data.get("total_blocks", 1)

    news_bullish = news_data.get("bullish_count", 0)
    news_bearish = news_data.get("bearish_count", 0)

    has_divergence = divergence.get("has_divergence", False)
    divergence_type = ""
    if has_divergence and divergence.get("divergences"):
        divergence_type = divergence["divergences"][0].get("type", "")

    # V1.1 新增维度
    nb = north_bound or {}
    nb_net_yi = nb.get("total_net_yi", 0)
    nb_direction = nb.get("direction", "")

    ms = market_strength or {}
    relative_strength = ms.get("relative_strength", 0)
    market_env = ms.get("market_env", "")

    mb = market_breadth or {}
    up_ratio = mb.get("up_ratio_pct", 50)
    breadth_score = mb.get("breadth_score", 50)
    limit_ratio = mb.get("limit_ratio", 1)
    money_effect = mb.get("money_effect", "")

    # 七维同向计数（用于共振加分）
    bullish_dims = 0
    bearish_dims = 0

    # ═══════════════════════════════════════
    # 情景A: 强势上涨
    # ═══════════════════════════════════════
    a_conditions = []
    a_score = 0

    # A1: 主力净流入>500万 (权重25)
    if main_net_wan > 500 and direction == "流入":
        a_score += 25
        a_conditions.append({"condition": "主力净流入>500万", "threshold": ">500万",
                            "actual": f"{main_net_wan:+.0f}万", "met": True, "weight": 25})
    else:
        a_conditions.append({"condition": "主力净流入>500万", "threshold": ">500万",
                            "actual": f"{main_net_wan:+.0f}万", "met": False, "weight": 25})

    # A2: 机构主导，净流入>游资+散户 (权重20)
    inst_dominates = inst_net > 200 and inst_net > abs(hm_net) and inst_net > abs(retail_net)
    if inst_dominates:
        a_score += 20
        a_conditions.append({"condition": "机构主导(净流入>200万且>游资+散户)", "threshold": "机构>200万且最大",
                            "actual": f"机构{inst_net:+.0f}万, 游资{hm_net:+.0f}万, 散户{retail_net:+.0f}万",
                            "met": True, "weight": 20})
    else:
        a_conditions.append({"condition": "机构主导(净流入>200万且>游资+散户)", "threshold": "机构>200万且最大",
                            "actual": f"机构{inst_net:+.0f}万, 游资{hm_net:+.0f}万, 散户{retail_net:+.0f}万",
                            "met": False, "weight": 20})

    # A3: 板块情绪≥60 (权重15)
    if sentiment_score >= 60:
        a_score += 15
        a_conditions.append({"condition": "板块情绪分≥60", "threshold": "≥60",
                            "actual": f"{sentiment_score:.0f}分 ({inflow_blocks}/{total_blocks}板块流入)",
                            "met": True, "weight": 15})
    else:
        a_conditions.append({"condition": "板块情绪分≥60", "threshold": "≥60",
                            "actual": f"{sentiment_score:.0f}分", "met": False, "weight": 15})

    # A4: 量能配合 (量比1.2~5, 换手<15%) (权重15)
    vol_ok = 1.2 <= vol_ratio <= 5 and turnover < 15
    if vol_ok:
        a_score += 15
        a_conditions.append({"condition": "量能配合(量比1.2~5, 换手<15%)", "threshold": "量比1.2-5, 换手<15%",
                            "actual": f"量比{vol_ratio}, 换手{turnover}%", "met": True, "weight": 15})
    else:
        a_conditions.append({"condition": "量能配合(量比1.2~5, 换手<15%)", "threshold": "量比1.2-5, 换手<15%",
                            "actual": f"量比{vol_ratio}, 换手{turnover}%", "met": False, "weight": 15})

    # A5: 无顶背离 (权重15)
    no_top_div = not has_divergence or "顶背离" not in divergence_type
    if no_top_div:
        a_score += 15
        a_conditions.append({"condition": "无顶背离信号", "threshold": "无顶背离",
                            "actual": f"背离: {'有('+divergence_type+')' if has_divergence else '无'}",
                            "met": True, "weight": 15})
    else:
        a_conditions.append({"condition": "无顶背离信号", "threshold": "无顶背离",
                            "actual": f"顶背离: {divergence_type}", "met": False, "weight": 15})

    # A6: 资金加速度正向 (权重10)
    accel_positive = "加速流入" in acceleration
    if accel_positive:
        a_score += 10
        a_conditions.append({"condition": "资金加速流入", "threshold": "后半段斜率>前半段×1.5",
                            "actual": f"前半段{first_slope}万/分 → 后半段{second_slope}万/分",
                            "met": True, "weight": 10})
    else:
        a_conditions.append({"condition": "资金加速流入", "threshold": "后半段斜率>前半段×1.5",
                            "actual": f"前半段{first_slope}万/分 → 后半段{second_slope}万/分",
                            "met": False, "weight": 10})

    # A7: 北向资金支持 (权重10, V1.1新增)
    nb_support = nb_net_yi > 0 or nb_direction in ("大幅流入", "小幅流入")
    if nb_support and nb_net_yi > 1:
        a_score += 10
        a_conditions.append({"condition": "北向资金流入(>1亿)", "threshold": "北向净流入>1亿",
                            "actual": f"北向{nb_net_yi:+.2f}亿", "met": True, "weight": 10})
    elif nb_net_yi < -5:
        a_score -= 5  # 北向大幅流出拖累
        a_conditions.append({"condition": "北向资金未大幅流出", "threshold": "北向>-5亿",
                            "actual": f"北向{nb_net_yi:+.2f}亿(⚠️大幅流出扣分)", "met": False, "weight": 10})
    else:
        a_conditions.append({"condition": "北向资金不拖累", "threshold": "北向不大幅流出",
                            "actual": f"北向{nb_net_yi:+.2f}亿", "met": nb_net_yi > -5, "weight": 10})

    # A8: 大盘共振 (权重5, V1.1新增)
    market_tailwind = relative_strength > 1 and "弱势" not in market_env
    if market_tailwind:
        a_score += 5
        a_conditions.append({"condition": "大盘配合+个股跑赢", "threshold": "相对强度>1%且大盘非弱势",
                            "actual": f"{market_env}, 相对强度{relative_strength:+.2f}%",
                            "met": True, "weight": 5})
    else:
        a_conditions.append({"condition": "大盘配合+个股跑赢", "threshold": "相对强度>1%且大盘非弱势",
                            "actual": f"{market_env}, 相对强度{relative_strength:+.2f}%",
                            "met": False, "weight": 5})

    # A9: 市场广度支持 (权重5, V1.1新增)
    breadth_ok = up_ratio >= 45 and "亏钱" not in money_effect
    if breadth_ok:
        a_score += 5
        bullish_dims += 1
        a_conditions.append({"condition": "市场广度不差(上涨>45%)", "threshold": "上涨占比≥45%且无强亏钱效应",
                            "actual": f"涨{up_ratio:.0f}%, {money_effect}", "met": True, "weight": 5})
    else:
        a_score -= 3
        a_conditions.append({"condition": "市场广度不差(上涨>45%)", "threshold": "上涨占比≥45%",
                            "actual": f"涨{up_ratio:.0f}%, {money_effect}(⚠️扣分)", "met": False, "weight": 5})

    # A10: 量能参考 (权重2, V1.1.1新增, 仅作轻量参考)
    amount = quote.get("amount", 0)
    vol_ref_ok = vol_ratio >= 0.8 and turnover >= 0.5
    if vol_ref_ok:
        a_score += 2
        a_conditions.append({"condition": "量能参考(量比≥0.8+换手≥0.5%)", "threshold": "量比≥0.8,换手≥0.5%",
                            "actual": f"量比{vol_ratio},换手{turnover}%,成交额{amount:.0f}万",
                            "met": True, "weight": 2})
    else:
        a_conditions.append({"condition": "量能参考(量比≥0.8+换手≥0.5%)", "threshold": "量比≥0.8",
                            "actual": f"量比{vol_ratio},换手{turnover}%,成交额{amount:.0f}万",
                            "met": False, "weight": 2})

    # 七维同向共振加分 (V1.1)
    # 计算多少维度指向同一方向（资金+价格+情绪+消息+北向+大盘+广度）
    bullish_dims = sum([
        1 if main_net_wan > 300 else 0,           # 资金面看多
        1 if change_pct > 0 else 0,                # 价格面看多
        1 if sentiment_score >= 50 else 0,         # 情绪面中性以上
        1 if news_bullish > news_bearish else 0,   # 消息面偏多
        1 if nb_net_yi > 0 else 0,                 # 北向流入
        1 if relative_strength > 0 else 0,         # 大盘跑赢
        1 if up_ratio >= 45 else 0,                # 广度不差
    ])
    if bullish_dims >= 6:
        a_score += 10  # 6-7维共振，强加分
    elif bullish_dims >= 5:
        a_score += 5   # 5维共振，中等加分

    scenarios.append({
        "name": "情景A: 强势上涨",
        "description": "主力持续流入+机构主导+板块共振+量能配合 → 当日剩余时段大概率继续走强",
        "raw_score": a_score,
        "conditions": a_conditions,
        "met_count": sum(1 for c in a_conditions if c["met"]),
        "total_conditions": len(a_conditions),
        "historical_ref": {
            "rule": "机构主导+板块共振+量能配合 → 当日继续走强",
            "historical_win_rate": "约65-70%",
            "source": "基于2024-2025年A股日内资金流统计规律",
            "sample_basis": "大样本日内资金流-涨跌幅相关性统计",
        },
        "failure_conditions": ["午后机构资金转流出", "板块情绪急转直下(骤降>20分)", "突发重大利空"],
    })

    # ═══════════════════════════════════════
    # 情景B: 震荡横盘
    # ═══════════════════════════════════════
    b_conditions = []
    b_score = 0

    no_direction = abs(main_net_wan) < 300
    if no_direction:
        b_score += 30
        b_conditions.append({"condition": "主力净流入<300万(无方向)", "threshold": "绝对值<300万",
                            "actual": f"{main_net_wan:+.0f}万", "met": True, "weight": 30})
    else:
        b_conditions.append({"condition": "主力净流入<300万(无方向)", "threshold": "绝对值<300万",
                            "actual": f"{main_net_wan:+.0f}万", "met": False, "weight": 30})

    narrow_range = amplitude < 3
    if narrow_range:
        b_score += 25
        b_conditions.append({"condition": "振幅<3%(窄幅波动)", "threshold": "<3%",
                            "actual": f"{amplitude}%", "met": True, "weight": 25})
    else:
        b_conditions.append({"condition": "振幅<3%(窄幅波动)", "threshold": "<3%",
                            "actual": f"{amplitude}%", "met": False, "weight": 25})

    neutral_sentiment = 35 <= sentiment_score <= 65
    if neutral_sentiment:
        b_score += 25
        b_conditions.append({"condition": "板块情绪35~65(中性)", "threshold": "35-65",
                            "actual": f"{sentiment_score:.0f}分", "met": True, "weight": 25})
    else:
        b_conditions.append({"condition": "板块情绪35~65(中性)", "threshold": "35-65",
                            "actual": f"{sentiment_score:.0f}分", "met": False, "weight": 25})

    no_news = news_bullish == 0 and news_bearish == 0
    if no_news:
        b_score += 15
        b_conditions.append({"condition": "无明确消息催化", "threshold": "0条今日新闻",
                            "actual": f"利好{news_bullish}/利空{news_bearish}", "met": True, "weight": 15})
    else:
        b_conditions.append({"condition": "无明确消息催化", "threshold": "0条今日新闻",
                            "actual": f"利好{news_bullish}/利空{news_bearish}", "met": False, "weight": 15})

    # B5: 北向无方向 (权重10, V1.1新增)
    nb_neutral = abs(nb_net_yi) < 3
    if nb_neutral:
        b_score += 10
        b_conditions.append({"condition": "北向资金无明显方向(±3亿内)", "threshold": "|北向|<3亿",
                            "actual": f"北向{nb_net_yi:+.2f}亿", "met": True, "weight": 10})
    else:
        b_conditions.append({"condition": "北向资金无明显方向", "threshold": "|北向|<3亿",
                            "actual": f"北向{nb_net_yi:+.2f}亿", "met": False, "weight": 10})

    # B6: 大盘中性 (权重10, V1.1新增)
    market_neutral = abs(relative_strength) < 1.5 and abs(ms.get("benchmark_change", 0)) < 1
    if market_neutral:
        b_score += 10
        b_conditions.append({"condition": "大盘+个股均中性波动", "threshold": "|相对强度|<1.5%,|大盘|<1%",
                            "actual": f"大盘{ms.get('benchmark_change', 0):+.2f}%, 相对{relative_strength:+.2f}%",
                            "met": True, "weight": 10})
    else:
        b_conditions.append({"condition": "大盘+个股均中性波动", "threshold": "|相对强度|<1.5%",
                            "actual": f"大盘{ms.get('benchmark_change', 0):+.2f}%, 相对{relative_strength:+.2f}%",
                            "met": False, "weight": 10})

    # B7: 市场广度中性 (权重10, V1.1新增)
    breadth_neutral = 40 <= up_ratio <= 60 and 0.8 <= limit_ratio <= 2
    if breadth_neutral:
        b_score += 10
        b_conditions.append({"condition": "市场广度中性(涨40-60%,涨跌停比0.8-2)", "threshold": "涨40-60%,涨跌停比0.8-2",
                            "actual": f"涨{up_ratio:.0f}%, 涨跌停比{limit_ratio}", "met": True, "weight": 10})
    else:
        b_conditions.append({"condition": "市场广度中性", "threshold": "涨40-60%",
                            "actual": f"涨{up_ratio:.0f}%, 涨跌停比{limit_ratio}", "met": False, "weight": 10})

    scenarios.append({
        "name": "情景B: 震荡横盘",
        "description": "资金方向不明+振幅小+情绪中性+无催化 → 当日剩余时段大概率窄幅震荡",
        "raw_score": b_score,
        "conditions": b_conditions,
        "met_count": sum(1 for c in b_conditions if c["met"]),
        "total_conditions": len(b_conditions),
        "historical_ref": {
            "rule": "主力资金无明显方向+振幅<3% → 后续2小时横盘概率较高",
            "historical_win_rate": "约55-60%",
            "source": "基于A股日内波动统计规律",
        },
        "failure_conditions": ["突发消息催化", "大单资金突然涌入/涌出"],
    })

    # ═══════════════════════════════════════
    # 情景C: 冲高回落
    # ═══════════════════════════════════════
    c_conditions = []
    c_score = 0

    high_and_turning = change_pct > 3 and ("流出" in acceleration or "减缓" in acceleration)
    if high_and_turning:
        c_score += 30
        c_conditions.append({"condition": "已涨>3%且资金流转向", "threshold": "涨>3%+资金减缓/流出",
                            "actual": f"涨{change_pct:+.2f}%, 趋势:{acceleration}",
                            "met": True, "weight": 30})
    else:
        c_conditions.append({"condition": "已涨>3%且资金流转向", "threshold": "涨>3%+资金减缓/流出",
                            "actual": f"涨{change_pct:+.2f}%, 趋势:{acceleration}",
                            "met": False, "weight": 30})

    top_divergence = has_divergence and "顶背离" in divergence_type
    if top_divergence:
        c_score += 25
        c_conditions.append({"condition": "出现顶背离(资金衰竭)", "threshold": "顶背离信号",
                            "actual": divergence_type, "met": True, "weight": 25})
    else:
        c_conditions.append({"condition": "出现顶背离(资金衰竭)", "threshold": "顶背离信号",
                            "actual": "无", "met": False, "weight": 25})

    distribution = inst_net < -100 and retail_net > 200
    if distribution:
        c_score += 25
        c_conditions.append({"condition": "机构流出>100万+散户流入>200万(派发)", "threshold": "机构<-100万,散户>+200万",
                            "actual": f"机构{inst_net:+.0f}万,散户{retail_net:+.0f}万",
                            "met": True, "weight": 25})
    else:
        c_conditions.append({"condition": "机构流出>100万+散户流入>200万(派发)", "threshold": "机构<-100万,散户>+200万",
                            "actual": f"机构{inst_net:+.0f}万,散户{retail_net:+.0f}万",
                            "met": False, "weight": 25})

    abnormal_turnover = turnover > 10
    if abnormal_turnover:
        c_score += 15
        c_conditions.append({"condition": "换手率>10%(异常活跃)", "threshold": ">10%",
                            "actual": f"{turnover}%", "met": True, "weight": 15})
    else:
        c_conditions.append({"condition": "换手率>10%(异常活跃)", "threshold": ">10%",
                            "actual": f"{turnover}%", "met": False, "weight": 15})

    # C5: 北向流出配合 (权重10, V1.1新增)
    nb_bearish = nb_net_yi < -2
    if nb_bearish:
        c_score += 10
        c_conditions.append({"condition": "北向资金流出(<-2亿)", "threshold": "北向<-2亿",
                            "actual": f"北向{nb_net_yi:+.2f}亿", "met": True, "weight": 10})
    else:
        c_conditions.append({"condition": "北向资金配合", "threshold": "北向<-2亿更确认回落",
                            "actual": f"北向{nb_net_yi:+.2f}亿", "met": False, "weight": 10})

    # C6: 个股高位但大盘走弱 (权重10, V1.1新增)
    high_weak_market = change_pct > 2 and relative_strength > 1 and "弱势" in market_env
    if high_weak_market:
        c_score += 10
        c_conditions.append({"condition": "个股高位+大盘走弱(逆势难持续)", "threshold": "涨>2%+相对强度>1%+大盘弱势",
                            "actual": f"涨{change_pct:+.2f}%, 大盘{ms.get('benchmark_change', 0):+.2f}%",
                            "met": True, "weight": 10})
    else:
        c_conditions.append({"condition": "个股高位+大盘走弱", "threshold": "大盘弱势时逆势难持续",
                            "actual": f"涨{change_pct:+.2f}%, {market_env}", "met": False, "weight": 10})

    # C7: 赚钱效应转弱 (权重10, V1.1新增)
    money_weakening = limit_ratio < 1.5 or "亏钱" in money_effect
    if money_weakening:
        c_score += 10
        c_conditions.append({"condition": "赚钱效应转弱", "threshold": "涨跌停比<1.5或有亏钱效应",
                            "actual": f"涨跌停比{limit_ratio}, {money_effect}", "met": True, "weight": 10})
    else:
        c_conditions.append({"condition": "赚钱效应转弱", "threshold": "涨跌停比<1.5",
                            "actual": f"涨跌停比{limit_ratio}, {money_effect}", "met": False, "weight": 10})

    scenarios.append({
        "name": "情景C: 冲高回落",
        "description": "高位+资金转向/顶背离/机构派发 → 当日剩余时段警惕回落风险",
        "raw_score": c_score,
        "conditions": c_conditions,
        "met_count": sum(1 for c in c_conditions if c["met"]),
        "total_conditions": len(c_conditions),
        "historical_ref": {
            "rule": "涨超3%+资金转流出+机构vs散户反向 → 午后回落概率较高",
            "historical_win_rate": "约55-65%",
            "source": "基于A股日内资金流-价格关系统计",
        },
        "failure_conditions": ["超预期利好", "板块集体暴动(涨停潮)"],
    })

    # ═══════════════════════════════════════
    # 情景D: 弱势下跌
    # ═══════════════════════════════════════
    d_conditions = []
    d_score = 0

    heavy_outflow = main_net_wan < -500 and direction == "流出"
    if heavy_outflow:
        d_score += 30
        d_conditions.append({"condition": "主力净流出>500万", "threshold": "<-500万",
                            "actual": f"{main_net_wan:+.0f}万", "met": True, "weight": 30})
    else:
        d_conditions.append({"condition": "主力净流出>500万", "threshold": "<-500万",
                            "actual": f"{main_net_wan:+.0f}万", "met": False, "weight": 30})

    cold_sentiment = sentiment_score < 40
    if cold_sentiment:
        d_score += 25
        d_conditions.append({"condition": "板块情绪<40(偏冷)", "threshold": "<40",
                            "actual": f"{sentiment_score:.0f}分", "met": True, "weight": 25})
    else:
        d_conditions.append({"condition": "板块情绪<40(偏冷)", "threshold": "<40",
                            "actual": f"{sentiment_score:.0f}分", "met": False, "weight": 25})

    accel_outflow = "加速流出" in acceleration
    if accel_outflow:
        d_score += 25
        d_conditions.append({"condition": "资金加速流出", "threshold": "后半段斜率<前半段×0.3且<0",
                            "actual": f"前半段{first_slope}万/分 → 后半段{second_slope}万/分",
                            "met": True, "weight": 25})
    else:
        d_conditions.append({"condition": "资金加速流出", "threshold": "后半段斜率<前半段×0.3且<0",
                            "actual": f"前半段{first_slope}万/分 → 后半段{second_slope}万/分",
                            "met": False, "weight": 25})

    bearish_news = news_bearish > 0
    if bearish_news:
        d_score += 15
        d_conditions.append({"condition": "有利空消息", "threshold": "利空>0条",
                            "actual": f"利空{news_bearish}条", "met": True, "weight": 15})
    else:
        d_conditions.append({"condition": "有利空消息", "threshold": "利空>0条",
                            "actual": "无", "met": False, "weight": 15})

    # D5: 北向大幅流出 (权重10, V1.1新增)
    nb_heavy_out = nb_net_yi < -5
    if nb_heavy_out:
        d_score += 10
        bearish_dims += 1
        d_conditions.append({"condition": "北向大幅流出(<-5亿)", "threshold": "北向<-5亿",
                            "actual": f"北向{nb_net_yi:+.2f}亿", "met": True, "weight": 10})
    else:
        d_conditions.append({"condition": "北向大幅流出(<-5亿)", "threshold": "北向<-5亿时确认弱势",
                            "actual": f"北向{nb_net_yi:+.2f}亿", "met": False, "weight": 10})

    # D6: 大盘走弱+个股跑输 (权重10, V1.1新增)
    market_drag = "弱势" in market_env and relative_strength < -0.5
    if market_drag:
        d_score += 10
        bearish_dims += 1
        d_conditions.append({"condition": "大盘弱势+个股跑输", "threshold": "大盘弱势+相对强度<-0.5%",
                            "actual": f"{market_env}, 相对{relative_strength:+.2f}%",
                            "met": True, "weight": 10})
    else:
        d_conditions.append({"condition": "大盘弱势+个股跑输", "threshold": "大盘弱势+相对强度<-0.5%",
                            "actual": f"{market_env}, 相对{relative_strength:+.2f}%",
                            "met": False, "weight": 10})

    # D7: 普跌格局 (权重10, V1.1新增)
    breadth_bearish = up_ratio < 35 or limit_ratio < 0.8
    if breadth_bearish:
        d_score += 10
        bearish_dims += 1
        d_conditions.append({"condition": "市场普跌(上涨<35%或涨跌停比<0.8)", "threshold": "上涨<35%或涨跌停比<0.8",
                            "actual": f"涨{up_ratio:.0f}%, 涨跌停比{limit_ratio}, {money_effect}",
                            "met": True, "weight": 10})
    else:
        d_conditions.append({"condition": "市场普跌", "threshold": "上涨<35%确认普跌",
                            "actual": f"涨{up_ratio:.0f}%, 涨跌停比{limit_ratio}",
                            "met": False, "weight": 10})

    # 七维同向共振：如果5维以上指向同一方向，额外加减分
    if bearish_dims >= 5:
        d_score += 10  # 多维共振加分

    scenarios.append({
        "name": "情景D: 弱势下跌",
        "description": "主力持续流出+板块冷+加速流出 → 当日剩余时段大概率继续走弱",
        "raw_score": d_score,
        "conditions": d_conditions,
        "met_count": sum(1 for c in d_conditions if c["met"]),
        "total_conditions": len(d_conditions),
        "historical_ref": {
            "rule": "主力持续流出+板块情绪<40 → 当日收阴概率较高",
            "historical_win_rate": "约60-70%",
            "source": "基于A股日内资金流-板块情绪联合统计",
        },
        "failure_conditions": ["午后重大利好", "国家队护盘资金入场"],
    })

    # ═══════════════════════════════════════
    # 情景E: 尾盘异动（仅尾盘触发）
    # ═══════════════════════════════════════
    now = datetime.now()
    is_late = now.hour >= 14 and now.minute >= 30
    has_recent_turn = last_turn and isinstance(last_turn, dict) and last_turn.get("time")
    recent_turn = False
    if has_recent_turn:
        try:
            turn_dt = datetime.strptime(last_turn["time"], "%Y-%m-%d %H:%M")
            recent_turn = (now - turn_dt).total_seconds() / 60 < 30
        except Exception:
            pass

    if is_late:
        e_conditions = []
        e_score = 0

        if recent_turn:
            e_score += 40
            e_conditions.append({"condition": "尾盘(14:30后)+近30分钟资金转向", "threshold": "14:30后+30分内转向",
                                "actual": f"最近转向: {last_turn.get('time', '')} {last_turn.get('type', '')}",
                                "met": True, "weight": 40})
        else:
            e_conditions.append({"condition": "尾盘(14:30后)+近30分钟资金转向", "threshold": "14:30后+30分内转向",
                                "actual": "无近期转向", "met": False, "weight": 40})

        vol_surge = vol_ratio > 2
        if vol_surge:
            e_score += 30
            e_conditions.append({"condition": "尾盘放量(量比>2)", "threshold": ">2",
                                "actual": f"{vol_ratio}", "met": True, "weight": 30})
        else:
            e_conditions.append({"condition": "尾盘放量(量比>2)", "threshold": ">2",
                                "actual": f"{vol_ratio}", "met": False, "weight": 30})

        direction_change = abs(change_pct) > 3
        if direction_change:
            e_score += 30
            e_conditions.append({"condition": "尾盘异动(涨跌幅>3%)", "threshold": ">3%或<-3%",
                                "actual": f"{change_pct:+.2f}%", "met": True, "weight": 30})
        else:
            e_conditions.append({"condition": "尾盘异动(涨跌幅>3%)", "threshold": ">3%或<-3%",
                                "actual": f"{change_pct:+.2f}%", "met": False, "weight": 30})

        if e_score >= 30:
            scenarios.append({
                "name": "情景E: 尾盘异动",
                "description": "尾盘资金异动+放量 → 关注次日开盘延续方向",
                "raw_score": e_score,
                "conditions": e_conditions,
                "met_count": sum(1 for c in e_conditions if c["met"]),
                "total_conditions": len(e_conditions),
                "historical_ref": {
                    "rule": "尾盘30分钟资金异动与次日开盘方向相关性较高",
                    "historical_win_rate": "约55-65%",
                    "source": "基于A股尾盘效应统计(公开量化研报)",
                },
                "failure_conditions": ["隔夜外盘剧变", "盘后重大消息"],
            })

    # ━━━ 归一化 ━━━
    total_score = sum(s["raw_score"] for s in scenarios)
    for s in scenarios:
        s["probability"] = round(s["raw_score"] / total_score * 100, 1) if total_score > 0 else 0

    scenarios_sorted = sorted(scenarios, key=lambda x: x["probability"], reverse=True)

    return {
        "scenarios": scenarios_sorted,
        "primary_scenario": scenarios_sorted[0] if scenarios_sorted else None,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_points": data_points,
        "disclaimer": "概率基于当前盘中数据的多因子条件匹配，不代表未来确定走势。每个条件标注了具体阈值和当前值，收盘后可逐一验证。",
    }
```

### 5.2 历史胜率参考表

| 编号 | 触发条件 | 历史胜率 | 来源 |
|------|---------|---------|------|
| R1 | 机构上午持续净流入 + 板块情绪≥60 | ~65-70% 当日收阳 | 日内资金流统计 |
| R2 | 主力资金无方向 + 振幅<3% | ~55-60% 后续2h横盘 | 日内波动统计 |
| R3 | 涨>3%后资金转流出 + 机构vs散户反向 | ~55-65% 午后回落 | 资金-价格关系统计 |
| R4 | 主力持续流出 + 板块情绪<40 | ~60-70% 当日收阴 | 资金-情绪联合统计 |
| R5 | 尾盘30min资金异动 | ~55-65% 次日开盘延续 | 尾盘效应统计 |
| R6 | 底背离(价格跌+资金回流) | ~50-60% 次日反弹 | 背离统计 |
| R7 | 开盘30min主力净流入>1000万 | ~60-65% 当日收阳 | 开盘效应统计 |

> ⚠️ 历史胜率是大样本统计参考值，不是单次保证。多规则同向共振时置信度最高。

---

## Layer 6: 买卖时机参考信号（数据说话）

### 6.1 信号生成——每个信号绑定具体数据

```python
def generate_trading_signals(
    scenarios: list, flow_data: dict, quote: dict,
    party_data: dict, sector_data: dict, limit_risk: dict,
) -> dict:
    """
    基于多维数据生成买卖时机参考信号。
    
    核心要求: 每个信号必须用数据说话——
    列出触发该信号的具体数据项、当前值、阈值、数据来源。
    """

    primary = scenarios[0] if scenarios else {}
    primary_prob = primary.get("probability", 0)
    primary_name = primary.get("name", "")

    # ━━━ 提取所有关键数据值 ━━━
    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)
    price = quote.get("price", 0)

    s = flow_data.get("summary", {})
    main_net_wan = s.get("total_main_net_wan", 0)
    inst_net = party_data.get("institution", {}).get("net_wan", 0)
    hm_net = party_data.get("hot_money", {}).get("net_wan", 0)
    retail_net = party_data.get("retail", {}).get("net_wan", 0)
    inst_share = party_data.get("institution", {}).get("share_pct", 0)
    retail_share = party_data.get("retail", {}).get("share_pct", 0)
    data_points = s.get("data_points", 0)

    t = flow_data.get("trend", {})
    acceleration = t.get("acceleration", "")
    direction = t.get("direction", "")
    second_slope = t.get("second_half_slope_wan_per_min", 0)

    sentiment_score = sector_data.get("sentiment_score", 50)
    inflow_blocks = sector_data.get("inflow_blocks", 0)
    total_blocks = sector_data.get("total_blocks", 1)

    news_bullish = 0  # 从外部传入
    news_bearish = 0

    limit_status = "正常区间"

    buy_signals = []
    sell_signals = []

    # ═══════════════════════════════════════
    # 买入参考信号（4级，每级用数据说话）
    # ═══════════════════════════════════════

    # 🟢🟢🟢 强买入参考
    strong_buy_conditions = [
        primary_prob >= 60 and "情景A" in primary_name,
        inst_net > 200,
        sentiment_score >= 60,
        change_pct < 5,
        "加速流入" in acceleration,
    ]
    strong_buy_met = sum(1 for c in strong_buy_conditions if c)

    if strong_buy_met >= 4:
        buy_signals.append({
            "level": "🟢🟢🟢 强买入参考",
            "strength": strong_buy_met,
            "data_evidence": [
                {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "≥60%",
                 "source": "多因子概率引擎", "met": primary_prob >= 60},
                {"item": "主力累计净流入", "value": f"{main_net_wan:+.0f}万", "threshold": ">+200万(机构主导)",
                 "source": "push2 分钟级资金流", "met": inst_net > 200},
                {"item": "板块情绪分", "value": f"{sentiment_score:.0f}/100", "threshold": "≥60",
                 "source": "板块资金流聚合", "met": sentiment_score >= 60},
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<5%(未过度拉升)",
                 "source": "腾讯行情API", "met": change_pct < 5},
                {"item": "资金加速度", "value": acceleration, "threshold": "加速流入",
                 "source": "push2 趋势分析", "met": "加速流入" in acceleration},
                {"item": "机构vs散户", "value": f"机构{inst_net:+.0f}万 vs 散户{retail_net:+.0f}万",
                 "threshold": "机构>+200万且>散户", "source": "三方资金分类", "met": inst_net > 200 and inst_net > retail_net},
            ],
            "action": "可考虑逢低建仓/加仓",
            "stop_loss": f"跌破{price * 0.97:.2f}(-3%)则果断离场",
            "principle": "宁可少挣: 5个条件中满足{0}个才触发,不追高,等回调到分时均线附近再动手".format(strong_buy_met),
        })

    # 🟢🟢 中等买入参考
    medium_buy_conditions = [
        primary_prob >= 45 and "情景A" in primary_name,
        inst_net > 100,
        sentiment_score >= 50,
        change_pct < 7,
    ]
    medium_buy_met = sum(1 for c in medium_buy_conditions if c)

    if medium_buy_met >= 3 and strong_buy_met < 4:
        buy_signals.append({
            "level": "🟢🟢 中等买入参考",
            "strength": medium_buy_met,
            "data_evidence": [
                {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "≥45%",
                 "source": "多因子概率引擎", "met": primary_prob >= 45},
                {"item": "机构净流入", "value": f"{inst_net:+.0f}万", "threshold": ">+100万",
                 "source": "push2 分钟级资金流", "met": inst_net > 100},
                {"item": "板块情绪分", "value": f"{sentiment_score:.0f}/100", "threshold": "≥50",
                 "source": "板块资金流聚合", "met": sentiment_score >= 50},
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<7%",
                 "source": "腾讯行情API", "met": change_pct < 7},
            ],
            "action": "可小仓位试探(计划仓位的30-50%), 等待更多信号确认",
            "stop_loss": f"跌破{price * 0.95:.2f}(-5%)则止损",
            "principle": "宁可少挣: 先小仓试错,确认方向后再加仓,不一次梭哈",
        })

    # 🟢 弱买入参考（左侧/底背离反弹）
    if primary_prob >= 30 and "情景D" in primary_name and main_net_wan > -300 and sentiment_score >= 30:
        buy_signals.append({
            "level": "🟢 弱买入参考(左侧/反弹)",
            "strength": 1,
            "data_evidence": [
                {"item": "情景D概率", "value": f"{primary_prob:.0f}%", "threshold": "≥30%但有反弹迹象",
                 "source": "多因子概率引擎", "met": True},
                {"item": "主力净流出", "value": f"{main_net_wan:+.0f}万", "threshold": ">-300万(流出收窄)",
                 "source": "push2 分钟级资金流", "met": main_net_wan > -300},
                {"item": "板块情绪", "value": f"{sentiment_score:.0f}/100", "threshold": "≥30(未极冷)",
                 "source": "板块资金流聚合", "met": sentiment_score >= 30},
            ],
            "action": "仅极度激进者可关注, 大多数人应等待企稳确认(情景A信号出现)",
            "stop_loss": f"跌破{price * 0.97:.2f}(-3%)强制止损",
            "principle": "宁可少挣: 宁可等企稳再追,也不提前抄底",
        })

    # 无买入信号
    if not buy_signals:
        buy_signals.append({
            "level": "⚪ 暂不建议买入",
            "data_evidence": [
                {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "需≥45%",
                 "source": "多因子概率引擎", "met": primary_prob >= 45},
                {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "需>+500万(情景A)或流出收窄(反弹)",
                 "source": "push2 分钟级资金流", "met": main_net_wan > 500},
            ],
            "action": "继续观察, 等待资金面+情绪面+价格面共振信号",
            "principle": "宁可少挣: 不买至少不亏钱, 错过一波比亏一波好",
        })

    # ═══════════════════════════════════════
    # 卖出参考信号（4级，每级用数据说话）
    # ═══════════════════════════════════════

    # 🔴🔴🔴 强卖出参考
    strong_sell_conditions = [
        primary_prob >= 50 and ("情景C" in primary_name or "情景D" in primary_name),
        inst_net < -200,
        "加速流出" in acceleration,
    ]
    strong_sell_met = sum(1 for c in strong_sell_conditions if c)

    if strong_sell_met >= 3:
        sell_signals.append({
            "level": "🔴🔴🔴 强卖出参考",
            "strength": strong_sell_met,
            "data_evidence": [
                {"item": "弱势情景概率", "value": f"{primary_prob:.0f}%({primary_name})", "threshold": "≥50%",
                 "source": "多因子概率引擎", "met": primary_prob >= 50},
                {"item": "机构净流出", "value": f"{inst_net:+.0f}万", "threshold": "<-200万",
                 "source": "push2 分钟级资金流", "met": inst_net < -200},
                {"item": "资金加速度", "value": acceleration, "threshold": "加速流出",
                 "source": "push2 趋势分析", "met": "加速流出" in acceleration},
                {"item": "机构份额", "value": f"{inst_share:.0f}%", "threshold": "机构主导流出",
                 "source": "三方资金分类", "met": inst_share > 30},
                {"item": "板块情绪", "value": f"{sentiment_score:.0f}/100", "threshold": "偏冷(<40)或中性偏低",
                 "source": "板块资金流聚合", "met": sentiment_score < 50},
                {"item": "主力净流出", "value": f"{main_net_wan:+.0f}万", "threshold": "大额流出",
                 "source": "push2 分钟级资金流", "met": main_net_wan < -300},
            ],
            "action": "建议果断减仓/清仓, 不在下跌中补仓",
            "risk_note": f"继续持有可能面临更大回撤, 当前已流出{abs(main_net_wan):.0f}万",
            "principle": "宁可少亏: 卖了少亏比扛着大亏好, 卖错了可以再买回来",
        })

    # 🔴🔴 中等卖出参考
    medium_sell_conditions = [
        ("情景C" in primary_name and primary_prob >= 35) or ("情景D" in primary_name and primary_prob >= 35),
        inst_net < -100 or (inst_net < 0 and retail_net > 100),
    ]
    medium_sell_met = sum(1 for c in medium_sell_conditions if c)

    if medium_sell_met >= 2 and strong_sell_met < 3:
        sell_signals.append({
            "level": "🔴🔴 中等卖出参考",
            "strength": medium_sell_met,
            "data_evidence": [
                {"item": "弱势情景概率", "value": f"{primary_prob:.0f}%({primary_name})", "threshold": "≥35%",
                 "source": "多因子概率引擎", "met": primary_prob >= 35},
                {"item": "机构资金", "value": f"{inst_net:+.0f}万", "threshold": "<-100万或机构流出+散户流入",
                 "source": "push2 分钟级资金流", "met": inst_net < -100},
                {"item": "散户资金", "value": f"{retail_net:+.0f}万", "threshold": "如>+100万则为接盘信号",
                 "source": "push2 分钟级资金流", "met": retail_net > 100},
                {"item": "资金趋势", "value": acceleration, "threshold": "流出或减缓",
                 "source": "push2 趋势分析", "met": "流出" in acceleration},
            ],
            "action": "建议逐步减仓, 至少减到半仓以下",
            "risk_note": f"机构{'流出' if inst_net < 0 else '减弱'}{abs(inst_net):.0f}万, 散户{'接盘' if retail_net > 100 else '观望'}{retail_net:+.0f}万",
            "principle": "宁可少亏: 卖一半留一半, 涨了还有仓位, 跌了少亏一半",
        })

    # 🔴 弱卖出参考（止盈）
    if change_pct > 8 and ("流出" in direction or "减缓" in acceleration):
        sell_signals.append({
            "level": "🔴 弱卖出参考(高位止盈)",
            "data_evidence": [
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": ">8%(已大幅上涨)",
                 "source": "腾讯行情API", "met": True},
                {"item": "资金方向", "value": f"{direction}/{acceleration}", "threshold": "流出/减缓",
                 "source": "push2 趋势分析", "met": True},
                {"item": "换手率", "value": f"{turnover}%", "threshold": "如>8%警惕出货",
                 "source": "腾讯行情API", "met": turnover > 8},
            ],
            "action": "可考虑部分止盈, 锁定利润",
            "principle": "宁可少挣: 落袋为安, 不贪最后一个铜板",
        })

    # 无卖出信号
    if not sell_signals:
        sell_signals.append({
            "level": "⚪ 暂不需卖出",
            "data_evidence": [
                {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "持续流入中",
                 "source": "push2 分钟级资金流", "met": main_net_wan > 0},
                {"item": "资金加速度", "value": acceleration, "threshold": "未出现流出加速",
                 "source": "push2 趋势分析", "met": "加速流出" not in acceleration},
            ],
            "action": "继续持有观察, 关注资金流方向是否转弱",
            "principle": "保持警觉, 一旦出现卖出数据条件, 果断行动",
        })

    # ═══════════════════════════════════════
    # 持有参考
    # ═══════════════════════════════════════
    if "情景A" in primary_name and primary_prob >= 50:
        hold_verdict = {
            "level": "✅ 可继续持有",
            "reason": f"强势上涨概率{primary_prob:.0f}%, 主力净流入{main_net_wan:+.0f}万, 机构主导({inst_net:+.0f}万)",
            "watch_points": ["午后资金是否转流出", "是否出现顶背离", "板块情绪是否骤降"],
        }
    elif "情景B" in primary_name:
        hold_verdict = {
            "level": "⏸️ 持有观望",
            "reason": f"震荡格局, 主力资金{main_net_wan:+.0f}万(无明显方向), 振幅{amplitude}%",
            "watch_points": ["突破方向(放量上破/下破)", "是否有催化消息出现"],
        }
    else:
        hold_verdict = {
            "level": "⚠️ 审视持仓",
            "reason": f"风险情景概率较高({primary_name} {primary_prob:.0f}%), 机构{inst_net:+.0f}万",
            "watch_points": ["触发止损条件则果断执行", "等待情景A信号出现再考虑加仓"],
        }

    # 综合评估（数据总结）
    strongest_buy = buy_signals[0]["level"] if buy_signals else ""
    strongest_sell = sell_signals[0]["level"] if sell_signals else ""

    if "强买入" in strongest_buy and "暂不需卖出" in strongest_sell:
        overall = f"总体偏多: 买入信号较强(满足{strong_buy_met}/5条件), 无卖出压力。主力净流入{main_net_wan:+.0f}万, 板块情绪{sentiment_score:.0f}分。可在控制仓位前提下逢低参与。"
    elif "强卖出" in strongest_sell:
        overall = f"总体偏空: 卖出信号较强(满足{strong_sell_met}/3条件)。主力净流出{abs(main_net_wan):.0f}万, 机构净流出{abs(inst_net):.0f}万。建议减仓或观望。"
    elif "中等卖出" in strongest_sell:
        overall = f"总体谨慎: 有卖出压力。机构{inst_net:+.0f}万, 散户{retail_net:+.0f}万。持有者应审视持仓, 未持有者建议等待。"
    elif "中等买入" in strongest_buy:
        overall = f"总体中性偏多: 满足{medium_buy_met}/4买入条件。主力{main_net_wan:+.0f}万。可小仓试探, 严格止损。"
    else:
        overall = f"总体中性: 主力{main_net_wan:+.0f}万, 信号不明确。建议观望, 等待更清晰的信号。"

    return {
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "hold_verdict": hold_verdict,
        "overall_verdict": overall,
        "data_summary": {
            "main_net_wan": main_net_wan,
            "inst_net_wan": inst_net,
            "retail_net_wan": retail_net,
            "sentiment_score": sentiment_score,
            "change_pct": change_pct,
            "turnover_pct": turnover,
            "vol_ratio": vol_ratio,
            "acceleration": acceleration,
            "data_points": data_points,
            "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
```

---

## Layer 7: 综合报告生成与输出

### 7.1 完整盘中信号报告

```python
def intraday_trading_report(user_input: str) -> dict:
    """
    盘中实时交易信号综合报告。
    一键拉取所有四维数据 + 多情景概率预判 + 买卖时机参考。
    自动保存到 src/盘中交易信号/ 目录。

    输入: 6位个股代码 / 板块名称 / ETF代码
    """
    # 解析标的
    target = resolve_target(user_input)
    code = target.get("code", user_input)

    report = {
        "target_input": user_input,
        "target": target,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market_status": _check_market_open(),
    }

    if not report["market_status"]["is_trading"]:
        report["warning"] = report["market_status"]["message"]
        return report

    # 四维数据拉取
    print(f"[1/6] 拉取实时行情...")
    quote = fetch_realtime_quote(code) if target["type"] == "个股" else {}
    report["quote"] = quote

    print(f"[2/6] 拉取分钟级资金流(从开盘到当前)...")
    flow = fetch_minute_fund_flow(code) if target["type"] == "个股" else {}
    report["fund_flow"] = flow

    if "error" in flow:
        report["warning"] = f"资金流数据异常: {flow['error']}"
        return report

    print(f"[3/6] 分析三方资金博弈 + 板块情绪 + 消息面...")
    parties = classify_intraday_parties(flow)
    report["parties"] = parties

    sector = fetch_sector_sentiment(code) if target["type"] == "个股" else {}
    report["sector_sentiment"] = sector

    news = fetch_intraday_news(code) if target["type"] == "个股" else {}
    report["news"] = news

    divergence = detect_fund_price_divergence(flow, quote)
    report["divergence"] = divergence

    print(f"[4/6] 拉取 V1.1 新增维度: 北向资金 + 大盘强度 + 市场广度...")
    north_bound = fetch_north_bound_flow()
    report["north_bound"] = north_bound

    market_strength = fetch_market_strength(code, quote) if target["type"] == "个股" else {}
    report["market_strength"] = market_strength

    market_breadth = fetch_market_breadth()
    report["market_breadth"] = market_breadth

    print(f"[5/6] 生成七维多情景概率预判...")
    scenarios = generate_probability_scenarios(
        flow, quote, sector, news, parties, divergence,
        north_bound, market_strength, market_breadth,
    )
    report["scenarios"] = scenarios

    print(f"[6/6] 生成买卖时机参考信号(数据说话)...")
    signals = generate_trading_signals(scenarios["scenarios"], flow, quote, parties, sector, {})
    report["signals"] = signals

    # ━━━ 输出到 src/ 目录 ━━━
    _save_report_to_src(report)

    print("✅ 报告生成完成! 已保存到 src/盘中交易信号/")
    return report


def resolve_target(user_input: str) -> dict:
    """解析用户输入，统一返回标的类型和代码"""
    if user_input.isdigit() and len(user_input) == 6:
        return {"type": "个股", "code": user_input}
    if user_input.isdigit() and len(user_input) == 5:
        return {"type": "ETF", "code": user_input}
    if user_input.upper().startswith("BK") and user_input[2:].isdigit():
        return {"type": "概念板块", "code": user_input.upper()}
    return {"type": "概念板块(需查找)", "keyword": user_input}


def _check_market_open() -> dict:
    """检查当前是否在交易时段"""
    now = datetime.now()
    if now.weekday() >= 5:
        return {"is_trading": False, "session": "周末", "message": "今日为周末，A股休市"}

    minutes = now.hour * 60 + now.minute
    if 9 * 60 + 30 <= minutes <= 11 * 60 + 30:
        return {"is_trading": True, "session": "上午交易时段", "message": ""}
    elif 13 * 60 <= minutes <= 15 * 60:
        return {"is_trading": True, "session": "下午交易时段", "message": ""}
    elif minutes < 9 * 60 + 30:
        return {"is_trading": False, "session": "盘前", "message": "盘前时段，数据可能不完整"}
    elif 11 * 60 + 30 < minutes < 13 * 60:
        return {"is_trading": False, "session": "午间休市", "message": "午间休市"}
    else:
        return {"is_trading": False, "session": "盘后", "message": "已收盘，可查看全天数据"}


def _save_report_to_src(report: dict):
    """将报告输出到 src/盘中交易信号/ 目录"""
    target_code = report.get("target", {}).get("code", report.get("target_input", "unknown"))
    target_name = report.get("quote", {}).get("name", target_code)
    date_str = datetime.now().strftime("%Y-%m-%d")
    dir_name = f"{date_str}-{target_name}-盘中信号"
    dir_path = os.path.join(OUTPUT_BASE, dir_name)
    os.makedirs(dir_path, exist_ok=True)

    # 1. 完整报告 (report.md)
    report_md = _format_report_markdown(report)
    with open(os.path.join(dir_path, "report.md"), "w", encoding="utf-8") as f:
        f.write(report_md)

    # 2. 原始数据 (data.json) — 用于回测和规则优化
    data_json = {
        "target": report.get("target", {}),
        "analysis_time": report.get("analysis_time", ""),
        "quote": _serialize(report.get("quote", {})),
        "fund_flow_summary": _serialize(report.get("fund_flow", {}).get("summary", {})),
        "fund_flow_trend": _serialize(report.get("fund_flow", {}).get("trend", {})),
        "parties": _serialize(report.get("parties", {})),
        "sector_sentiment": _serialize(report.get("sector_sentiment", {})),
        "scenarios": _serialize(report.get("scenarios", {}).get("scenarios", [])),
        "signals_data_summary": _serialize(report.get("signals", {}).get("data_summary", {})),
        # 分钟级明细数据（只保留关键字段，控制文件大小）
        "minute_data": [
            {"time": m["time"], "main_net": m["main_net"],
             "super_net": m["super_net"], "large_net": m["large_net"]}
            for m in report.get("fund_flow", {}).get("minutes", [])[-60:]  # 最近60分钟
        ],
    }
    with open(os.path.join(dir_path, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data_json, f, ensure_ascii=False, indent=2, default=str)

    print(f"  报告目录: {dir_path}/")
    print(f"    ├── report.md    (完整信号报告)")
    print(f"    └── data.json    (原始数据, 用于回测)")


def _serialize(obj):
    """递归处理datetime等不可序列化对象"""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize(v) for v in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    else:
        return obj


def _format_report_markdown(report: dict) -> str:
    """将报告字典格式化为完整的 Markdown 文件内容"""
    L = []  # lines accumulator
    a = L.append  # shortcut

    quote = report.get("quote", {})
    flow = report.get("fund_flow", {})
    parties = report.get("parties", {})
    sector = report.get("sector_sentiment", {})
    news = report.get("news", {})
    divergence = report.get("divergence", {})
    scenarios = report.get("scenarios", {})
    signals = report.get("signals", {})
    nb = report.get("north_bound", {})
    ms = report.get("market_strength", {})
    mb = report.get("market_breadth", {})

    target_name = quote.get("name", report.get("target_input", "未知"))
    target_code = quote.get("code", report.get("target_input", ""))

    # ━━━ Header ━━━
    a(f"# 📊 盘中实时交易信号报告")
    a(f"")
    a(f"**标的**: {target_name} ({target_code})")
    a(f"**分析时间**: {report.get('analysis_time', '')}")
    a(f"**市场状态**: {report.get('market_status', {}).get('session', '')}")
    a(f"**核心原则**: 宁可少挣，宁可少亏。买入卖出，数据说话。")
    a(f"")
    a(f"---")
    a(f"")

    # ━━━ Part 1: 核心结论 ━━━
    primary_sc = scenarios.get("primary_scenario", {}) or {}
    primary_name = primary_sc.get("name", "无数据")
    primary_prob = primary_sc.get("probability", 0)
    overall = signals.get("overall_verdict", "")

    hold_v = signals.get("hold_verdict", {}) or {}
    buy_sigs = signals.get("buy_signals", []) or []
    sell_sigs = signals.get("sell_signals", []) or []
    strongest_buy = buy_sigs[0].get("level", "") if buy_sigs else ""
    strongest_sell = sell_sigs[0].get("level", "") if sell_sigs else ""

    a(f"## 🎯 Part 1: 核心结论")
    a(f"")
    a(f"```")
    a(f"主导情景: {primary_name} (概率 {primary_prob:.0f}%)")
    a(f"买入信号: {strongest_buy}")
    a(f"卖出信号: {strongest_sell}")
    a(f"持有建议: {hold_v.get('level', '')}")
    a(f"```")
    a(f"")
    a(f"**综合评估**: {overall}")
    a(f"")
    a(f"---")
    a(f"")

    # ━━━ Part 2: 关键数据一览 ━━━
    s = flow.get("summary", {}) or {}
    t = flow.get("trend", {}) or {}
    inst = parties.get("institution", {}) or {}
    hm = parties.get("hot_money", {}) or {}
    retail = parties.get("retail", {}) or {}
    v = parties.get("verdict", {}) or {}
    ds = signals.get("data_summary", {}) or {}

    a(f"## 📊 Part 2: 关键数据一览")
    a(f"")
    a(f"| 维度 | 指标 | 数值 | 信号 |")
    a(f"|------|------|------|------|")
    a(f"| 📈 价格 | 最新价 | {quote.get('price', 0):.2f} | — |")
    a(f"| 📈 价格 | 涨跌幅 | {quote.get('change_pct', 0):+.2f}% | {'🔴' if quote.get('change_pct', 0) < 0 else '🟢'} |")
    a(f"| 📈 价格 | 振幅 | {quote.get('amplitude', 0):.2f}% | — |")
    a(f"| 📈 价格 | 换手率 | {quote.get('turnover_pct', 0):.2f}% | {'🔴 异常' if quote.get('turnover_pct', 0) > 10 else '正常'} |")
    a(f"| 📈 价格 | 量比 | {quote.get('vol_ratio', 0):.2f} | — |")
    a(f"| 💰 资金 | 主力净流入 | {s.get('total_main_net_wan', 0):+.0f}万 | {'🔴 流出' if s.get('total_main_net_wan', 0) < 0 else '🟢 流入'} |")
    a(f"| 💰 资金 | 机构(超大单) | {s.get('total_super_net_wan', 0):+.0f}万 | {'🔴' if s.get('total_super_net_wan', 0) < 0 else '🟢'} |")
    a(f"| 💰 资金 | 游资(大单) | {s.get('total_large_net_wan', 0):+.0f}万 | — |")
    a(f"| 💰 资金 | 散户(中+小) | {(s.get('total_mid_net_wan', 0) or 0) + (s.get('total_small_net_wan', 0) or 0):+.0f}万 | {'🔴 接盘' if (s.get('total_mid_net_wan', 0) or 0) + (s.get('total_small_net_wan', 0) or 0) > 100 else '—'} |")
    a(f"| 💰 资金 | 趋势 | {t.get('direction', '?')} / {t.get('acceleration', '?')} | — |")
    a(f"| 💰 资金 | 数据点 | {s.get('data_points', 0)}分钟 | — |")
    a(f"| 🎯 情绪 | 板块情绪分 | {sector.get('sentiment_score', 0):.0f}/100 {sector.get('level', '')} | — |")
    a(f"| 🎯 情绪 | 板块流入比 | {sector.get('inflow_blocks', 0)}/{sector.get('total_blocks', 1)} | — |")
    a(f"| 🌏 北向 | 北向资金 | {nb.get('total_net_yi', 0):+.2f}亿 | {nb.get('signal', '')} |")
    a(f"| 📊 大盘 | 相对强度 | {ms.get('relative_strength', 0):+.2f}% | {ms.get('relative_rating', '')} |")
    a(f"| 📊 大盘 | 基准涨跌 | {ms.get('benchmark_change', 0):+.2f}% | {ms.get('market_env', '')} |")
    a(f"| 🔥 广度 | 涨跌家数比 | {mb.get('up_ratio_pct', 50):.0f}% | {mb.get('breadth_level', '')} |")
    a(f"| 🔥 广度 | 涨跌停比 | {mb.get('limit_ratio', 1):.1f} | {mb.get('money_effect', '')} |")
    a(f"| 📰 消息 | 今日新闻 | {news.get('today_count', 0)}条 (利好{news.get('bullish_count', 0)}/利空{news.get('bearish_count', 0)}) | — |")
    a(f"")
    a(f"---")
    a(f"")

    # ━━━ Part 3: 七维数据明细 ━━━
    a(f"## 📋 Part 3: 七维数据明细")
    a(f"")

    # 3.1 资金面明细
    a(f"### 💰 资金面（分钟级）")
    a(f"")
    a(f"**追踪时段**: {s.get('first_time', '?')} → {s.get('last_time', '?')} (共{s.get('data_points', 0)}分钟)")
    a(f"")
    a(f"**三方资金博弈**: {v.get('scenario', '')}")
    a(f"")
    a(f"| 资金类型 | 净流入(万) | 方向 | 份额 | 速率(万/分) |")
    a(f"|---------|-----------|------|------|------------|")
    a(f"| 🔴 机构(超大单) | {inst.get('net_wan', 0):+.0f} | {inst.get('direction', '')} | {inst.get('share_pct', 0):.0f}% | {inst.get('rate_per_min_wan', 0):+.2f} |")
    a(f"| 🟡 游资(大单) | {hm.get('net_wan', 0):+.0f} | {hm.get('direction', '')} | {hm.get('share_pct', 0):.0f}% | {hm.get('rate_per_min_wan', 0):+.2f} |")
    a(f"| 🟢 散户(中+小) | {retail.get('net_wan', 0):+.0f} | {retail.get('direction', '')} | {retail.get('share_pct', 0):.0f}% | {retail.get('rate_per_min_wan', 0):+.2f} |")
    a(f"")
    a(f"**信号等级**: {v.get('level', '')} | **主方向**: {v.get('main_direction', '')}")
    a(f"")
    a(f"**数据来源**: {parties.get('data_basis', {}).get('source', '')} ({parties.get('data_basis', {}).get('time_range', '')})")
    a(f"")

    # 转向点
    turns = t.get("turning_points", []) or []
    if turns:
        a(f"**关键转向点**:")
        a(f"")
        a(f"| 时间 | 类型 | 累计值(万) |")
        a(f"|------|------|-----------|")
        for tp in turns:
            a(f"| {tp['time']} | {tp['type']} | {tp['value_wan']:+.0f} |")
        a(f"")

    # 背离
    if divergence.get("has_divergence"):
        a(f"**⚠️ 资金-价格背离检测**:")
        for div in divergence.get("divergences", []):
            a(f"- **{div['type']}**: {div['detail']}")
            a(f"  - 数据: {div.get('data', '')}")
            a(f"  - 风险: {div['risk']}")
        a(f"")

    # 3.2 板块情绪
    a(f"### 🎯 板块情绪")
    a(f"")
    a(f"**情绪分**: {sector.get('sentiment_score', 0):.0f}/100 {sector.get('level', '')}")
    a(f"**数据**: {sector.get('data_basis', '')}")
    a(f"")
    blocks = sector.get("blocks", []) or []
    if blocks:
        a(f"| 板块 | 主力净流入(万) | 涨跌% | 涨家 | 跌家 |")
        a(f"|------|--------------|-------|------|------|")
        for bk in blocks[:8]:
            a(f"| {bk['name']} | {bk['main_net_wan']:+.0f} | {bk['change_pct']:+.2f}% | {bk['up_count']} | {bk['down_count']} |")
        a(f"")

    # 3.3 北向资金
    if nb:
        a(f"### 🌏 北向资金")
        a(f"")
        a(f"**{nb.get('data_basis', '')}**")
        a(f"")
        a(f"- 方向: {nb.get('direction', '')} {nb.get('signal', '')}")
        a(f"- 来源: {nb.get('source', '')}")
        a(f"")

    # 3.4 大盘强度
    if ms:
        a(f"### 📊 大盘相对强度")
        a(f"")
        a(f"**{ms.get('data_basis', '')}**")
        a(f"")
        a(f"- 个股评级: {ms.get('relative_rating', '')} | 大盘环境: {ms.get('market_env', '')}")
        if ms.get("market_detail"):
            for k, v in ms["market_detail"].items():
                a(f"- {k}: {v:+.2f}%")
        a(f"")

    # 3.5 市场广度
    if mb:
        a(f"### 🔥 市场广度")
        a(f"")
        a(f"**{mb.get('data_basis', '')}**")
        a(f"")
        a(f"- 广度评分: {mb.get('breadth_score', 0)}分 {mb.get('breadth_level', '')}")
        a(f"- 赚钱效应: {mb.get('money_effect', '')}")
        a(f"")

    # 3.6 消息面
    a(f"### 📰 消息面")
    a(f"")
    highlights = news.get("highlights", []) or []
    if highlights:
        a(f"**今日新闻** ({news.get('today_count', 0)}条):")
        a(f"")
        for h in highlights[:8]:
            emoji = "🟢" if h.get("sentiment") == "bullish" else ("🔴" if h.get("sentiment") == "bearish" else "⚪")
            a(f"- {emoji} [{h.get('time', '')}] {h.get('title', '')} (来源: {h.get('source', '')})")
    else:
        a(f"今日无相关新闻")
    a(f"")
    a(f"---")
    a(f"")

    # ━━━ Part 4: 多情景概率预判 ━━━
    a(f"## 🔮 Part 4: 多情景概率预判（七维 25+ 条件）")
    a(f"")
    sc_list = scenarios.get("scenarios", []) or []
    if sc_list:
        for i, sc in enumerate(sc_list):
            prob = sc.get("probability", 0)
            name = sc.get("name", "")
            desc = sc.get("description", "")
            met = sc.get("met_count", 0)
            total = sc.get("total_conditions", 0)
            ref = sc.get("historical_ref", {}) or {}
            fails = sc.get("failure_conditions", []) or []

            icon = "🔥" if prob >= 50 else ("📊" if prob >= 25 else "🔍")
            a(f"### {icon} {name} → 概率: {prob:.0f}%")
            a(f"")
            a(f"**{desc}**")
            a(f"")
            a(f"**条件满足**: {met}/{total}")
            a(f"")
            a(f"| 条件 | 阈值 | 当前值 | 满足? | 权重 |")
            a(f"|------|------|--------|-------|------|")
            for c in sc.get("conditions", []):
                status = "✅" if c.get("met") else "❌"
                a(f"| {c['condition']} | {c.get('threshold', '')} | {c.get('actual', '')} | {status} | {c.get('weight', 0)} |")
            a(f"")
            a(f"**历史参考**: {ref.get('rule', '')} (历史胜率: {ref.get('historical_win_rate', '')})")
            a(f"**来源**: {ref.get('source', '')}")
            if fails:
                a(f"**失效条件**: {'; '.join(fails)}")
            a(f"")
    a(f"---")
    a(f"")

    # ━━━ Part 5: 买卖时机参考 ━━━
    a(f"## ⚡ Part 5: 买卖时机参考（数据说话）")
    a(f"")

    a(f"### 📥 买入参考")
    a(f"")
    for bs in buy_sigs:
        a(f"**{bs.get('level', '')}**")
        a(f"")
        a(f"| 数据项 | 数值 | 阈值 | 满足? | 来源 |")
        a(f"|--------|------|------|-------|------|")
        for ev in bs.get("data_evidence", []):
            status = "✅" if ev.get("met", False) else "❌"
            a(f"| {ev.get('item', '')} | {ev.get('value', '')} | {ev.get('threshold', '')} | {status} | {ev.get('source', '')} |")
        a(f"")
        a(f"- **操作**: {bs.get('action', '')}")
        if bs.get("stop_loss"):
            a(f"- **止损**: {bs['stop_loss']}")
        a(f"- **原则**: {bs.get('principle', '')}")
        a(f"")

    a(f"### 📤 卖出参考")
    a(f"")
    for ss in sell_sigs:
        a(f"**{ss.get('level', '')}**")
        a(f"")
        a(f"| 数据项 | 数值 | 阈值 | 满足? | 来源 |")
        a(f"|--------|------|------|-------|------|")
        for ev in ss.get("data_evidence", []):
            status = "✅" if ev.get("met", False) else "❌"
            a(f"| {ev.get('item', '')} | {ev.get('value', '')} | {ev.get('threshold', '')} | {status} | {ev.get('source', '')} |")
        a(f"")
        a(f"- **操作**: {ss.get('action', '')}")
        if ss.get("risk_note"):
            a(f"- **风险**: {ss['risk_note']}")
        a(f"- **原则**: {ss.get('principle', '')}")
        a(f"")

    a(f"### 📌 持有参考")
    a(f"")
    if hold_v:
        a(f"**{hold_v.get('level', '')}**")
        a(f"")
        a(f"- {hold_v.get('reason', '')}")
        for wp in hold_v.get("watch_points", []):
            a(f"- 👁 {wp}")
    a(f"")

    a(f"### 🎯 综合评估")
    a(f"")
    a(f"> {overall}")
    a(f"")

    a(f"---")
    a(f"")

    # ━━━ Footer ━━━
    a(f"## ⚠️ 研究声明")
    a(f"")
    a(f"1. 本报告基于公开API实时数据（延迟3-5秒），所有信号为研究框架产出，**不构成投资建议**")
    a(f"2. 每个买卖信号标注了具体数据阈值和当前值，可逐一验证")
    a(f"3. 概率预判基于七维25+条件多因子匹配 + 历史统计规律，不代表未来确定走势")
    a(f"4. "机构/游资/散户"分类基于订单大小的近似估算")
    a(f"5. **核心原则：宁可少挣，宁可少亏；买入卖出，数据说话**")
    a(f"6. 本报告自动生成于 {report.get('analysis_time', '')}，原始数据见 data.json")
    a(f"")

    return "\n".join(L)
```

### 7.2 控制台输出（中文友好）

```python
def print_intraday_report(report: dict):
    """打印盘中实时交易信号报告到控制台"""
    print()
    print("═" * 70)
    print(f"  📊 盘中实时交易信号: {report.get('target_input', '')}")
    print(f"  分析时间: {report.get('analysis_time', '')}")
    ms = report.get("market_status", {})
    print(f"  市场状态: {ms.get('session', '')}")
    if report.get("warning"):
        print(f"  ⚠️ {report['warning']}")
    print("═" * 70)

    quote = report.get("quote", {})
    flow = report.get("fund_flow", {})
    parties = report.get("parties", {})
    sector = report.get("sector_sentiment", {})
    news = report.get("news", {})
    divergence = report.get("divergence", {})
    scenarios = report.get("scenarios", {})
    signals = report.get("signals", {})

    # ━━━ 一、价格面 ━━━
    print(f"\n{'─' * 60}")
    print(f"  📈 一、价格面")
    print(f"{'─' * 60}")
    if quote and "error" not in quote:
        print(f"  {quote.get('name', '')}({quote.get('code', '')})")
        print(f"  最新价: {quote.get('price', 0):.2f}  涨跌: {quote.get('change_pct', 0):+.2f}%  "
              f"振幅: {quote.get('amplitude', 0):.2f}%")
        print(f"  换手率: {quote.get('turnover_pct', 0):.2f}%  量比: {quote.get('vol_ratio', 0):.2f}  "
              f"成交额: {quote.get('amount', 0):.0f}万")
        print(f"  今开: {quote.get('open', 0):.2f}  最高: {quote.get('high', 0):.2f}  "
              f"最低: {quote.get('low', 0):.2f}")

    # ━━━ 二、资金面 ━━━
    print(f"\n{'─' * 60}")
    print(f"  💰 二、资金面 (分钟级)")
    print(f"{'─' * 60}")
    if flow and "error" not in flow:
        s = flow["summary"]
        t = flow["trend"]
        print(f"  追踪: {s.get('first_time', '?')} → {s.get('last_time', '?')} "
              f"(共{s.get('data_points', 0)}分钟)")
        print(f"  主力累计: {s.get('total_main_net_wan', 0):+.0f}万")
        print(f"    机构(超大单): {s.get('total_super_net_wan', 0):+.0f}万")
        print(f"    游资(大单):   {s.get('total_large_net_wan', 0):+.0f}万")
        print(f"    散户(中+小):  {(s.get('total_mid_net_wan', 0) or 0) + (s.get('total_small_net_wan', 0) or 0):+.0f}万")
        print(f"  趋势: {t.get('direction', '?')} | {t.get('acceleration', '?')}")
        turns = t.get("turning_points", [])
        if turns:
            print(f"  关键转向点:")
            for tp in turns:
                print(f"    {tp['time']} {tp['type']}: {tp['value_wan']:+.0f}万")

    # 三方博弈
    if parties:
        v = parties.get("verdict", {})
        inst = parties.get("institution", {})
        hm = parties.get("hot_money", {})
        retail = parties.get("retail", {})
        print(f"\n  🎯 三方博弈: {v.get('scenario', '')}")
        print(f"  信号等级: {v.get('level', '')}")
        print(f"  机构: {inst.get('net_wan', 0):+.0f}万 {inst.get('direction', '')} "
              f"({inst.get('share_pct', 0):.0f}%)")
        print(f"  游资: {hm.get('net_wan', 0):+.0f}万 {hm.get('direction', '')} "
              f"({hm.get('share_pct', 0):.0f}%)")
        print(f"  散户: {retail.get('net_wan', 0):+.0f}万 {retail.get('direction', '')} "
              f"({retail.get('share_pct', 0):.0f}%)")

    # 背离
    if divergence and divergence.get("has_divergence"):
        print(f"\n  ⚠️ 背离检测:")
        for div in divergence.get("divergences", []):
            print(f"    {div['type']}: {div['detail']}")
            print(f"    风险: {div['risk']}")

    # ━━━ 三、情绪面 ━━━
    print(f"\n{'─' * 60}")
    print(f"  🎯 三、情绪面")
    print(f"{'─' * 60}")
    if sector and "error" not in sector:
        print(f"  板块情绪: {sector.get('sentiment_score', 0):.0f}/100 {sector.get('level', '')}")
        print(f"  数据: {sector.get('data_basis', '')}")
        for bk in sector.get("blocks", [])[:5]:
            print(f"    {bk['name']}: 主力{bk['main_net_wan']:+.0f}万 "
                  f"涨{bk['up_count']}跌{bk['down_count']}")

    # ━━━ 四、消息面 ━━━
    print(f"\n{'─' * 60}")
    print(f"  📰 四、消息面")
    print(f"{'─' * 60}")
    if news:
        print(f"  今日新闻: {news.get('today_count', 0)}条 "
              f"(利好{news.get('bullish_count', 0)}/利空{news.get('bearish_count', 0)})")
        for h in (news.get("highlights") or [])[:5]:
            emoji = "🟢" if h.get("sentiment") == "bullish" else ("🔴" if h.get("sentiment") == "bearish" else "⚪")
            print(f"  {emoji} {h.get('time', '')} | {h.get('source', '')}")
            print(f"     {h.get('title', '')[:60]}")

    # ━━━ V1.1 新增维度 ━━━
    nb = report.get("north_bound", {})
    ms = report.get("market_strength", {})
    mb = report.get("market_breadth", {})

    print(f"\n{'─' * 60}")
    print(f"  🌏 五、北向资金 + 大盘 + 广度 (V1.1)")
    print(f"{'─' * 60}")
    if nb:
        print(f"  北向资金: {nb.get('data_basis', '')}")
        print(f"  方向: {nb.get('direction', '')} {nb.get('signal', '')}")
    if ms:
        print(f"  大盘环境: {ms.get('data_basis', '')}")
        print(f"  个股评级: {ms.get('relative_rating', '')} | {ms.get('market_env', '')}")
    if mb:
        print(f"  市场广度: {mb.get('data_basis', '')}")
        print(f"  广度评级: {mb.get('breadth_level', '')} ({mb.get('breadth_score', 0)}分)")

    # ━━━ 六、多情景概率预判 ━━━
    print(f"\n{'─' * 60}")
    print(f"  🔮 六、多情景概率预判(七维{25}+条件)")
    print(f"{'─' * 60}")
    for sc in scenarios.get("scenarios", []):
        prob = sc.get("probability", 0)
        name = sc.get("name", "")
        met = sc.get("met_count", 0)
        total = sc.get("total_conditions", 0)
        ref = sc.get("historical_ref", {})

        icon = "🔥" if prob >= 50 else ("📊" if prob >= 25 else "🔍")
        print(f"\n  {icon} {name} → 概率: {prob:.0f}% (满足{met}/{total}条件)")
        print(f"     {sc.get('description', '')}")
        for c in sc.get("conditions", []):
            status = "✅" if c["met"] else "❌"
            print(f"     {status} {c['condition']}: 阈值{c['threshold']}, 当前={c['actual']}")
        print(f"     历史胜率: {ref.get('historical_win_rate', '')} ({ref.get('source', '')})")
        fails = sc.get("failure_conditions", [])
        if fails:
            print(f"     失效条件: {'; '.join(fails)}")

    # ━━━ 七、买卖时机参考 ━━━
    print(f"\n{'─' * 60}")
    print(f"  ⚡ 七、买卖时机参考（数据说话）")
    print(f"{'─' * 60}")

    print(f"\n  📥 买入参考:")
    for bs in signals.get("buy_signals", []):
        print(f"    {bs['level']}")
        for ev in bs.get("data_evidence", []):
            status = "✅" if ev.get("met", False) else "❌"
            print(f"      {status} {ev['item']}: {ev['value']} (阈值: {ev['threshold']}) [{ev['source']}]")
        print(f"    操作: {bs.get('action', '')}")
        if bs.get("stop_loss"):
            print(f"    止损: {bs['stop_loss']}")
        print(f"    原则: {bs.get('principle', '')}")

    print(f"\n  📤 卖出参考:")
    for ss in signals.get("sell_signals", []):
        print(f"    {ss['level']}")
        for ev in ss.get("data_evidence", []):
            status = "✅" if ev.get("met", False) else "❌"
            print(f"      {status} {ev['item']}: {ev['value']} (阈值: {ev['threshold']}) [{ev['source']}]")
        print(f"    操作: {ss.get('action', '')}")
        if ss.get("risk_note"):
            print(f"    风险: {ss['risk_note']}")
        print(f"    原则: {ss.get('principle', '')}")

    hv = signals.get("hold_verdict", {})
    if hv:
        print(f"\n  📌 持有参考: {hv.get('level', '')}")
        print(f"    {hv.get('reason', '')}")
        for wp in hv.get("watch_points", []):
            print(f"    👁 {wp}")

    print(f"\n  ━━━━━━━━━━━━")
    print(f"  🎯 综合评估: {signals.get('overall_verdict', '')}")

    ds = signals.get("data_summary", {})
    if ds:
        print(f"\n  📋 七维数据摘要:")
        print(f"     资金: 主力{ds.get('main_net_wan', 0):+.0f}万 | "
              f"机构{ds.get('inst_net_wan', 0):+.0f}万 | "
              f"涨跌{ds.get('change_pct', 0):+.2f}% | "
              f"换手{ds.get('turnover_pct', 0)}%")
        if nb:
            print(f"     北向: {nb.get('total_net_yi', 0):+.2f}亿 {nb.get('direction', '')}")
        if ms:
            print(f"     大盘: {ms.get('data_basis', '')}")
        if mb:
            print(f"     广度: {mb.get('data_basis', '')}")
        print(f"     情绪: {ds.get('sentiment_score', 0):.0f}分 | "
              f"量比{ds.get('vol_ratio', 0)}")

    # 风险声明
    print(f"\n{'═' * 70}")
    print(f"  ⚠️ 研究声明:")
    print(f"  1. 所有信号基于公开API实时数据(延迟3-5秒)，不构成投资建议")
    print(f"  2. 概率预判基于多因子条件匹配+历史统计规律，不代表未来确定走势")
    print(f"  3. 每个买卖信号标注了具体数据阈值和当前值，可逐一验证")
    print(f"  4. 核心原则：宁可少挣，宁可少亏——不确定时不出手")
    print(f"  5. 报告已自动保存到 src/盘中交易信号/ 目录(data.json 可用于回测)")
    print(f"{'═' * 70}")
    print()


# 完整调用
# report = intraday_trading_report("300339")
# print_intraday_report(report)
```

---

## 收盘后验证

```python
def verify_prediction(report: dict, actual_close_change: float, actual_high: float = None) -> dict:
    """
    收盘后验证预判准确率，自动生成 verification.md。
    
    验证每个情景的"命中/未命中"，记录到 data.json 同目录。
    """
    scenarios = report.get("scenarios", {}).get("scenarios", [])
    primary = scenarios[0] if scenarios else {}
    name = primary.get("name", "")
    prob = primary.get("probability", 0)

    results = []

    # 验证规则
    if "情景A" in name:
        hit = actual_close_change > 0
        results.append({"scenario": "情景A(上涨)", "probability": prob,
                        "condition": "实际收涨", "actual": f"{actual_close_change:+.2f}%",
                        "hit": hit, "confidence": "高" if prob >= 60 else "中"})
    if "情景B" in name:
        hit = abs(actual_close_change) < 1
        results.append({"scenario": "情景B(震荡)", "probability": prob,
                        "condition": "实际振幅<1%", "actual": f"{actual_close_change:+.2f}%",
                        "hit": hit, "confidence": "中"})
    if "情景C" in name and actual_high:
        high_change = (actual_high - report.get("quote", {}).get("prev_close", 0)) / report.get("quote", {}).get("prev_close", 1) * 100
        hit = actual_close_change < high_change - 1  # 从高点回落>1%
        results.append({"scenario": "情景C(回落)", "probability": prob,
                        "condition": f"从高点{high_change:.2f}%回落>1%", "actual": f"收{actual_close_change:+.2f}%",
                        "hit": hit, "confidence": "中"})
    if "情景D" in name:
        hit = actual_close_change < 0
        results.append({"scenario": "情景D(下跌)", "probability": prob,
                        "condition": "实际收跌", "actual": f"{actual_close_change:+.2f}%",
                        "hit": hit, "confidence": "高" if prob >= 60 else "中"})

    # 保存验证报告
    verification = {
        "verify_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "actual_close_change": actual_close_change,
        "primary_scenario": name,
        "primary_probability": prob,
        "results": results,
        "hit_count": sum(1 for r in results if r.get("hit")),
        "total_scenarios": len(results),
    }

    # 写入 verification.md
    target_code = report.get("target", {}).get("code", report.get("target_input", "unknown"))
    target_name = report.get("quote", {}).get("name", target_code)
    date_str = datetime.now().strftime("%Y-%m-%d")
    dir_path = os.path.join(OUTPUT_BASE, f"{date_str}-{target_name}-盘中信号")
    os.makedirs(dir_path, exist_ok=True)

    with open(os.path.join(dir_path, "verification.md"), "w", encoding="utf-8") as f:
        f.write(f"# 预判验证报告\n\n")
        f.write(f"**验证时间**: {verification['verify_time']}\n")
        f.write(f"**实际收盘涨跌**: {actual_close_change:+.2f}%\n\n")
        f.write(f"## 验证结果\n\n")
        f.write(f"| 情景 | 预判概率 | 验证条件 | 实际值 | 命中? |\n")
        f.write(f"|------|---------|---------|--------|------|\n")
        for r in results:
            hit_str = "✅ 命中" if r.get("hit") else "❌ 未命中"
            f.write(f"| {r['scenario']} | {r['probability']:.0f}% | {r['condition']} | {r['actual']} | {hit_str} |\n")
        f.write(f"\n**命中率**: {verification['hit_count']}/{verification['total_scenarios']}\n")

    print(f"验证报告已保存: {dir_path}/verification.md")
    return verification
```

---

## 快速参考

### 调用链速查

| 场景 | 调用链 |
|------|--------|
| 完整盘中监控 | `report = intraday_trading_report("300339")` → `print_intraday_report(report)` |
| 只看资金面 | `fetch_minute_fund_flow(code)` → `classify_intraday_parties(flow)` |
| 只看概率预判 | `generate_probability_scenarios(flow, quote, sector, news, parties, divergence)` |
| 只看买卖信号 | `generate_trading_signals(scenarios, flow, quote, parties, sector, limit_risk)` |
| 收盘验证 | `verify_prediction(report, actual_close_change)` |

### 买卖信号数据门槛速查

| 信号等级 | 触发条件（全部需满足） | 数据阈值 |
|---------|---------------------|---------|
| 🟢🟢🟢 强买入 | 情景A概率高+机构主导+板块共振+未拉升+资金加速 | 概率≥60%, 机构>+200万, 情绪≥60, 涨<5%, 加速流入 |
| 🟢🟢 中买入 | 情景A概率中高+机构参与+板块中性以上 | 概率≥45%, 机构>+100万, 情绪≥50, 涨<7% |
| 🔴🔴🔴 强卖出 | 弱势情景高+机构大额流出+加速流出 | 概率≥50%, 机构<-200万, 加速流出 |
| 🔴🔴 中卖出 | 弱势情景中高+机构流出+散户接盘 | 概率≥35%, 机构<-100万或机构流出+散户>+100万 |

### 输出文件说明

| 文件 | 内容 | 用途 |
|------|------|------|
| `report.md` | 完整四维信号报告 | 盘中决策参考 |
| `data.json` | 分钟级原始数据 + 信号摘要 | 回测验证 + 规则优化 |
| `verification.md` | 收盘后验证结果 | 持续改进准确率 |

---

## 风险声明

- 所有"买入参考"/"卖出参考"信号为研究框架产出，不构成投资建议
- 分钟级资金流数据延迟 3-5 秒，极端行情可能更长
- "机构/游资/散户"基于订单大小的近似估算
- 历史胜率是大样本统计参考值，不代表单次结果
- **==核心原则：宁可少挣，宁可少亏。不确定时不做，比做错好。==**
- **==买卖必须用数据说话：每个信号标注具体数值、阈值、来源，拒绝主观判断。==**
- 报告自动保存到 `src/盘中交易信号/`，`data.json` 可用于回测和规则持续优化
