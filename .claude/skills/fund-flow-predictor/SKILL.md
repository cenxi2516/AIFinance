---
name: fund-flow-predictor
description: 买入安全区间研判器 V1.6 — 拉取指定标的近60天日度数据(价格+成交量+消息面+概念板块资金流+融资融券+行业资金流)，核心回答"现在能不能买？是否已企稳？风险是否降到了安全范围？该不该卖？"。内置双轨信号系统：个股轨(主力资金流+量价) / ETF轨(量价+消息面+行业资金流代理)。V1.6核心升级：多平台交叉验证层(腾讯+新浪双源验证，数据不交叉验证不写入报告)。V1.5核心升级：Part 2统一为2A/2B/2C三级子结构(量价+资金流向+融资融券一站式展示)。V1.4核心升级：融资融券(datacenter-web)+概念板块资金流(push2 clist)作为B轨代理指标。输出0-100安全评分+企稳确认+买入/离场参考条件。核心原则：可以少挣，必须少亏，所有判断用数据说话。Use when 用户询问"XX能不能买""XX企稳了吗""现在安全吗""什么时候可以入场""要不要卖/离场""风险大不大""下跌空间还有多少""XX回调到位了吗"等需要基于盘面判断买入/卖出时机时。
version: 1.4.0
updated: 2026-07-11
---

# 买入安全区间研判器 V1.4

**定位**：14 技能架构的**风险-机会平衡研判引擎**——聚焦单一标的，融合全维度盘面数据，不预测"能涨多少"，只回答四个问题：

> 1. **能不能买？** → 安全评分 + 企稳确认
> 2. **风险多大？** → 下行风险量化 + 危险信号检测
> 3. **什么时候买？** → 买入参考条件（精确到信号触发日）
> 4. **该不该卖？** → 离场预警 + 利润保护 + 亏损控制

**V1.3 核心升级（2026-07-10 实盘验证驱动）**：
- **双轨信号系统**：个股轨（主力资金流 F1-F5）+ ETF/板块轨（量价+消息面 F1-F5），自动按标的类型选择
- **数据源可靠性重构**：腾讯直连 HTTP 为 K线主源（不封IP），东财 push2his 仅在代理可达时用于个股资金流
- **tencent_quote 解析修正**：绕过 a_stock_api 的字段映射 bug，直接解析腾讯原始 `~` 分隔格式
- **ETF 适配**：明确 ETF 无个股资金流维度的限制，用行业资金流+量价分析作为代理指标
- **辅助数据务实化**：标注各维度的实际可用性（哪些能拉到、哪些依赖代理、哪些仅个股有效）

**V1.4 核心升级（2026-07-11 实盘验证驱动）**：
- **融资融券数据接入**：发现 datacenter-web API 使用 `SCODE`（非 `SECURITY_CODE`）过滤列名，成功拉取个股融资余额/买入/偿还日度明细，B轨也可用
- **概念板块资金流代理**：push2 clist `b:BKXXXX` 获取板块成分股主力资金流排名，B轨个股无直接资金流时作为代理指标
- **B轨输出补齐**：Part 2.5 始终展示资金流向（概念板块排名）+ 融资融券明细，不再因 push2his 不可用而缺失
- **评分维度扩展**：融资趋势（加杠杆+5/去杠杆-7）、概念板块龙头资金流（+4）纳入评分修正

**核心原则**：==可以少挣，必须少亏。== 亏损的数学是不对称的（亏50%需涨100%回本），因此：
- 买入判断**保守优先**：宁错过，不做错
- 离场判断**敏感优先**：盈利回吐比踏空更痛苦
- 所有判断**数据说话**：每个结论绑定具体信号+历史胜率+样本数

> **与现有 skill 的关系：**
> - `capital-flow-tracker`：告诉你"钱现在在哪" → 本 skill：告诉你"现在安不安全、能不能动"
> - `quant-dashboard`：全市场自上而下研判 → 本 skill：单标的深度安全评估
> - `industry-sentiment-tracker`：行业情绪温度计 → 本 skill：情绪是否到了安全/危险区间
>
> **设计原则：** 依赖 a-stock-data 的通用 helper + 腾讯直连 HTTP（不封IP），聚焦 60 天日度数据 → 安全信号提取 → 买入/卖出时机判断。

## When to Activate

- 用户要判断**某只股票/板块/ETF 现在能不能买**（安全吗？企稳了吗？）
- 用户要评估**下行风险有多大**（还会跌多少？什么情况下会止跌？）
- 用户要寻找**买入时机**（什么信号出现后可以考虑入场？）
- 用户要判断**该不该卖/离场**（风险是不是在累积？利润要不要保护？）
- 用户要检测**危险信号**（主力在跑吗？是不是利好出尽？顶部派发？）
- 关键词：`能不能买`、`企稳了吗`、`安全吗`、`什么时候入场`、`要不要卖`、`离场`、`风险大不大`、`还会跌吗`、`回调到位了吗`、`止跌了吗`、`底部确认`、`下跌空间`

**不适用场景**：
- 全市场研判（用 quant-dashboard）
- 产业链深度分析（用 serenity-skill）
- 长期价值判断（用 old-guard-stocks）
- "能涨到多少"的预测（本 skill 只判断安全区间，不做涨幅预测）

---

## 核心框架：双轨六层研判引擎 (V1.3)

```
                         ┌──────────────────────────────────────────┐
                         │       fund-flow-predictor V1.3            │
                         │     买入安全区间研判 + 买卖时机参考         │
                         │     核心原则: 可以少挣，必须少亏            │
                         └──────────────┬───────────────────────────┘
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
                   ┌──────────────┐          ┌──────────────┐
                   │  个股轨 (A)   │          │  ETF轨 (B)    │
                   │ 主力资金流+量价│          │ 量价+消息面   │
                   │ F1-F5 资金流版 │          │ F1-F5 量价版  │
                   └──────┬───────┘          └──────┬───────┘
                          │                         │
        ┌──────────┬──────┼───────┬──────────┐      │
        ▼          ▼      ▼       ▼          ▼      ▼
    腾讯K线    腾讯行情  东财新闻  push2his  industry-  腾讯K线
    (qfq日线)  (实时价)  (个股)   资金流120d comparison  (qfq日线)
    不封IP     不封IP   限流     代理可达   行业资金流   不封IP
                          │                         │
                   ┌──────┴─────────────────────────┴──────┐
                   ▼                                       ▼
        ┌──────────────────┐                    ┌──────────────────┐
        │ Layer 1: 60天数据  │                    │ 8条可验证规则     │
        │ 价格+量+资金流+消息│                    │ F1-F4: 安全信号   │
        └────────┬─────────┘                    │ F4-F5: 危险信号   │
                 │                               │ F7: 利好出尽      │
                 ▼                               │ F8: 缩量止跌      │
        ┌──────────────────┐                    └────────┬─────────┘
        │ Layer 2: 安全信号  │                             │
        │ 卖压衰竭/放量反弹  │ ←──────────────────────────┘
        │ 恐慌出尽/缩量止跌  │
        └────────┬─────────┘
                 │
                 ▼
        ┌──────────────────┐
        │ Layer 3: 危险信号  │ → F4 加速放量下跌 / F5 高位放量逆转
        │ (排除法:先确保安全)│ → F7 利好出尽/高开低走
        └────────┬─────────┘
                 │
                 ▼
        ┌──────────────────────────────────────────┐
        │ Layer 4: 安全区间评分 (0-100)             │
        │  🟢 ≥75: 安全 — 下行风险可控，可考虑入场  │
        │  🟡 60-74: 接近安全 — 再观察1-3日        │
        │  🟠 40-59: 风险区间 — 不建议入场          │
        │  🔴 <40: 危险区间 — 远离，持币观望        │
        └────────┬─────────────────────────────────┘
                 │
                 ▼
        ┌──────────────────────────────────────────┐
        │ Layer 5: 买卖时机参考                      │
        │  买入条件: 安全评分≥75 + 企稳确认 + 放量阳线 │
        │  离场条件: 危险信号触发 + 利润保护 + 亏损控制 │
        │  ⚠️ 这不是买卖建议，是可验证的参考条件      │
        └────────┬─────────────────────────────────┘
                 │
                 ▼
        ┌──────────────────────────────────────────┐
        │ Layer 6: 输出层                           │
        │ ①安全评分+等级 ②企稳确认清单              │
        │ ③危险信号检测 ④买入参考条件               │
        │ ⑤离场预警 ⑥数据明细+验证框架              │
        └──────────────────────────────────────────┘
```

---

## 概率引擎集成 (Probability Engine Integration)

> **V1.3 核心变更**: 所有规则的概率不再引用外部来源（券商研报），改为从 A 股实际盘面数据中计算得出。

### 统一概率规则引擎

本 skill 的 15 条规则的概率已迁移到统一规则引擎。使用方式：

```python
import sys
sys.path.insert(0, '.claude/skills/_shared')
from probability_engine import RuleEngine, CurrentMarketSnapshot, ScenarioProbabilityReport

# 加载规则（包含从实际A股数据计算的概率）
engine = RuleEngine("rules/")

# 构建当前市场快照
snapshot = CurrentMarketSnapshot(
    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
    market_regime="正常轮动日",  # 或 事件驱动日/极端情绪日/业绩验证日
    price_data={...},            # 价格数据
    fund_flow={...},             # 资金流数据
    sentiment={...},             # 情绪数据
    industry_context="半导体",   # 目标行业
)

# 评估 → 输出多情景概率分布
report = engine.evaluate(snapshot, industry="半导体")
print(report.to_markdown())
```

### 概率来源

所有规则概率通过 `scripts/rule_learner.py` 从历史盘面数据计算：
- **数据源**: mootdx(K线) + push2his(资金流) + push2(板块资金流)
- **时间范围**: 2023-01 ~ 2026-06 (约850个交易日)
- **计算方法**: 条件概率 → Bootstrap置信区间 → 逐年胜率检查

### 输出格式：5档情景概率分布

引擎输出不再是单一的"安全评分"，而是多情景概率分布：

| 情景 | 概率% | 含义 |
|------|-------|------|
| 大涨 | XX% | T+5涨幅 > 5% |
| 小涨 | XX% | T+5涨幅 0-5% |
| 横盘 | XX% | T+5涨跌幅 -2%~+2% |
| 小跌 | XX% | T+5跌幅 0-5% |
| 大跌 | XX% | T+5跌幅 > 5% |

### 行业差异化

规则引擎自动根据行业加载差异化参数（阈值/权重），详见 `probability_engine.py::DEFAULT_INDUSTRY_PARAMS`。

---

## Prerequisites — 数据拉取：腾讯直连(主) + a-stock-api(辅) + push2his(仅个股资金流)

本 skill 的数据采集遵循 a-stock-data 的**数据源优先级原则**：能用腾讯/通达信就不走东财。

**V1.6 新增：多平台交叉验证** — 报告生成前，每个数据维度必须经过至少 2 个权威平台验证（或在唯一来源时标注"单源"风险）。核心原则：==数据不交叉验证，不写入报告。==

### 核心数据源（V1.3 实测可用）

| 优先级 | 数据源 | 用途 | 封IP风险 | 适用范围 |
|--------|--------|------|---------|---------|
| **1** | **腾讯 HTTP 直连** | K线(qfq日线) + 实时行情 | **不封IP** | 个股+ETF+指数 |
| **2** | **东财 search-api-web** | 个股/主题新闻 | 低(已限流) | 全标的 |
| **3** | **东财 push2 industry** | 行业板块资金流排名 | 低(已限流) | 市场环境参考 |
| **4** | **东财 push2his** | 个股日级资金流(主力/超大单/大单/中单/小单) | **代理拦截** | 仅个股，需代理可达 |
| **5** | **同花顺北向 CSV 缓存** | 北向资金历史 | 低 | 市场环境参考 |
| **6** | **东财 datacenter-web** | 个股融资融券日度明细 | **低(非push2通道)** | 个股，V1.4新增，filter用`SCODE` |
| **7** | **东财 push2 clist** | 概念板块成分股资金流排名 | 低(已限流) | B轨代理指标，V1.4新增，`b:BKXXXX` |

> **⚠️ 已知限制（V1.4 实测）**：
> - `push2his.eastmoney.com` 在大陆部分网络环境被代理拦截 → 个股资金流不可用时自动降级为量价分析模式
> - ETF 无个股资金流维度 → 使用行业资金流（`industry_comparison`）作为代理指标
> - `a_stock_api.tencent_quote()` 存在字段映射 bug（code/name/price 错位）→ 本 skill 直接解析腾讯原始格式
> - `eastmoney_stock_news()` 的 page_size 参数名是 `page_size`（不是 `count`）

### 数据拉取入口

```python
import sys
sys.path.insert(0, '.claude/skills/_shared')
from a_stock_api import (
    eastmoney_stock_news,      # 个股新闻 (page_size=10)
    industry_comparison,       # 行业板块资金流排名
    eastmoney_concept_blocks,  # 个股概念板块归属 (仅个股)
    em_get,                    # 东财统一请求入口 (已内置限流)
    eastmoney_datacenter,      # 数据中心通用查询
    stock_fund_flow_120d,      # 个股日级资金流120日 (需代理可达)
    stock_kline,               # K线 (东财+mootdx回退, ETF可能为空)
)
import requests
import json
from datetime import datetime, timedelta
```

---

## Layer 1: 数据采集流程（V1.3 重构）

### 1.1 统一数据采集入口

```python
def fetch_all_data(target: str, target_type: str = "auto") -> dict:
    """
    统一数据采集入口 — V1.3 双轨数据源。

    数据源优先级:
    1. 腾讯 K线 (HTTP 直连, 不封IP) — 所有标的
    2. 腾讯实时行情 (HTTP 直连, 不封IP) — 所有标的
    3. 东财新闻 (search-api-web, em_get限流) — 所有标的
    4. 东财个股资金流 (push2his, 代理可能拦截) — 仅个股
    5. 东财行业资金流 (push2, em_get限流) — ETF代理指标

    返回: {target, target_type, realtime, daily(kline+fundflow合并), news, industry_flow}
    """
    data = {"target": target, "target_type": target_type}

    # ━━ Step 1: K线数据 (腾讯 qfq 日线, 不封IP) ━━
    # 格式: [date, open, close, high, low, volume]
    # qfq = 前复权，价格已做除权除息调整
    print("[1/6] 拉取腾讯日K线(qfq)...")
    data["daily"] = _fetch_kline_tencent(target, days=60)

    # ━━ Step 2: 实时行情 (腾讯, 不封IP) ━━
    # 绕过 a_stock_api.tencent_quote() 的字段映射 bug，直接解析原始格式
    print("[2/6] 拉取实时行情...")
    data["realtime"] = _fetch_realtime_tencent(target)

    # ━━ Step 3: 日级资金流 (仅个股 + push2his代理可达时) ━━
    print("[3/6] 拉取个股资金流(push2his)...")
    fund_flow = []
    if target_type == "stock":
        try:
            fund_flow = stock_fund_flow_120d(target)
            print(f"  获取 {len(fund_flow)} 日资金流数据")
        except Exception as e:
            print(f"  ⚠️ push2his 不可用({e})，降级为量价分析模式")
    else:
        print(f"  ETF/板块无个股资金流，使用量价分析模式")

    # 合并资金流到 daily
    if fund_flow:
        _merge_fund_flow(data["daily"], fund_flow)

    # ━━ Step 4: 新闻 ━━
    print("[4/6] 拉取新闻...")
    keyword = data["realtime"].get("name", target)
    try:
        data["news"] = eastmoney_stock_news(target, page_size=10)
    except Exception:
        data["news"] = []

    # ━━ Step 5: 行业资金流 (市场环境参考, ETF代理指标) ━━
    print("[5/6] 拉取行业板块资金流...")
    try:
        data["industry_flow"] = industry_comparison(top_n=50)
    except Exception:
        data["industry_flow"] = []

    # ━━ Step 6: 用实时行情更新最后一天 ━━
    print("[6/6] 数据合并完成")
    _update_last_day_with_realtime(data["daily"], data["realtime"])

    return data
```

### 1.2 腾讯 K线获取（核心数据源，不封IP）

```python
def _fetch_kline_tencent(code: str, days: int = 60) -> list[dict]:
    """
    从腾讯获取日K线（前复权 qfq）。
    这是 V1.3 的核心 K线数据源 — 不封IP, 对个股和ETF均可用。

    腾讯 qfqday 格式: [date, open, close, high, low, volume]
    注意: volume 是股数(带小数), qfq 已做价格复权调整
    """
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    url = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"{prefix}{code},day,,,{days},qfq"}

    r = requests.get(url, params=params, timeout=15)
    data = r.json()
    raw = data.get("data", {}).get(f"{prefix}{code}", {}).get("qfqday", [])

    klines = []
    for d in raw:
        date, open_p, close, high, low, vol = d
        o, c, h, l, v = float(open_p), float(close), float(high), float(low), float(vol)
        # 计算日涨跌幅 (相对开盘价)
        chg = round((c - o) / o * 100, 2) if o > 0 else 0
        # 计算振幅
        amp = round((h - l) / l * 100, 2) if l > 0 else 0
        klines.append({
            "date": date,
            "open": o, "close": c, "high": h, "low": l,
            "volume": v,           # 成交量(股)
            "change_pct": chg,     # 涨跌幅%(相对开盘)
            "amplitude": amp,      # 振幅%
            # 资金流字段预置(个股轨有数据时会被 _merge_fund_flow 覆盖)
            "main_net": 0,         # 主力净流入(万元)
            "super_net": 0,        # 超大单净流入(万元)
            "large_net": 0,        # 大单净流入(万元)
            "mid_net": 0,          # 中单净流入(万元)
            "small_net": 0,        # 小单净流入(万元)
        })
    return klines
```

### 1.3 腾讯实时行情（绕过 a_stock_api 的字段映射 bug）

```python
def _fetch_realtime_tencent(code: str) -> dict:
    """
    从腾讯获取实时行情 — 直接解析原始 ~ 分隔格式。
    绕过 a_stock_api.tencent_quote() 的 code/name/price 字段映射 bug。

    腾讯标准格式 (~ 分隔, 88字段):
      [1]=name  [3]=price  [4]=last_close  [5]=open  [6]=volume
      [31]=change_amt  [32]=change_pct  [33]=high  [34]=low
      [37]=amount(万)  [38]=turnover_pct  [39]=PE(TTM)  [43]=振幅%
      [44]=总市值(亿)  [45]=流通市值(亿)  [46]=PB  [47]=涨停  [48]=跌停
    """
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    r = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=10)
    r.encoding = "gbk"
    text = r.text

    if "~" not in text or '"' not in text:
        return {}

    parts = text.split('"')[1].split("~")
    if len(parts) < 50:
        return {}

    return {
        "name": parts[1],
        "code": parts[2],
        "price": float(parts[3]) if parts[3] else 0,
        "last_close": float(parts[4]) if parts[4] else 0,
        "open": float(parts[5]) if parts[5] else 0,
        "volume": int(float(parts[6])) if parts[6] else 0,  # 股
        "change_amt": float(parts[31]) if parts[31] else 0,
        "change_pct": float(parts[32]) if parts[32] else 0,
        "high": float(parts[33]) if parts[33] else 0,
        "low": float(parts[34]) if parts[34] else 0,
        "amount_wan": float(parts[37]) if parts[37] else 0,  # 万元
        "turnover_pct": float(parts[38]) if parts[38] else 0,  # 换手率%
        "pe_ttm": float(parts[39]) if parts[39] else 0,
        "amplitude_pct": float(parts[43]) if parts[43] else 0,  # 振幅%
        "mcap_yi": float(parts[44]) if parts[44] else 0,  # 总市值(亿)
        "float_mcap_yi": float(parts[45]) if parts[45] else 0,
        "pb": float(parts[46]) if parts[46] else 0,
        "limit_up": float(parts[47]) if parts[47] else 0,
        "limit_down": float(parts[48]) if parts[48] else 0,
    }
```

### 1.4 资金流合并 + 实时行情更新

```python
def _merge_fund_flow(daily: list[dict], fund_flow: list[dict]):
    """
    将 push2his 日级资金流合并到 daily K线数据中。
    ⚠️ 已知陷阱(V1.7修正): stock_fund_flow_120d 返回字段为
       main_net_yi / super_large_net / large_net_yi / mid_net_yi / small_net_yi，
       且单位已是【万元】(字段名带 _yi 系命名误导，实为 元÷10000)。
       ①不能取 main_net/super_net(不存在→全0→误判B轨)；
       ②不能再 ÷1e4 或 ×10000(会放大/缩小1万倍)。
    fund_flow 格式: [{date, main_net_yi(万元), super_large_net, large_net_yi, mid_net_yi, small_net_yi}]
    合并后单位: 万元(直接透传)
    """
    flow_map = {f["date"]: f for f in fund_flow}
    for d in daily:
        if d["date"] in flow_map:
            f = flow_map[d["date"]]
            # 已是万元，直接透传(勿 ÷1e4 / ×10000)
            d["main_net"] = round(f.get("main_net_yi", 0) or 0, 1)
            d["super_net"] = round(f.get("super_large_net", 0) or 0, 1)
            d["large_net"] = round(f.get("large_net_yi", 0) or 0, 1)
            d["mid_net"] = round(f.get("mid_net_yi", 0) or 0, 1)
            d["small_net"] = round(f.get("small_net_yi", 0) or 0, 1)


def _update_last_day_with_realtime(daily: list[dict], realtime: dict):
    """用实时行情更新 daily 最后一天的数据"""
    if not daily or not realtime:
        return
    today_str = datetime.now().strftime("%Y-%m-%d")
    last = daily[-1]
    if last["date"] == today_str:
        last["close"] = realtime.get("price", last["close"])
        last["open"] = realtime.get("open", last["open"])
        last["high"] = realtime.get("high", last["high"])
        last["low"] = realtime.get("low", last["low"])
        last["volume"] = realtime.get("volume", last["volume"])
        # 重新计算涨跌幅和振幅
        if last["open"] > 0:
            last["change_pct"] = round((last["close"] - last["open"]) / last["open"] * 100, 2)
        if last["low"] > 0:
            last["amplitude"] = round((last["high"] - last["low"]) / last["low"] * 100, 2)
```

### 1.5 标的类型自动识别

```python
def _auto_detect_type(target: str) -> str:
    """根据代码特征自动识别标的类型"""
    target = target.strip()
    # 纯6位数字 → 个股或ETF
    if target.isdigit() and len(target) == 6:
        if target.startswith(("51", "58", "56")):
            return "etf"
        elif target.startswith("BK"):
            return "sector"
        else:
            return "stock"
    # BK开头 → 行业/概念板块
    if target.upper().startswith("BK"):
        return "sector"
    # 包含"ETF" → ETF
    if "ETF" in target.upper() or "etf" in target:
        return "etf"
    return "stock"
```

### 1.6 数据完整度评估

采集完成后先评估数据完整度，决定使用哪个信号轨：

```python
def _assess_data_completeness(data: dict) -> dict:
    """
    评估数据完整度 → 决定信号轨选择。
    返回: {track, has_fund_flow, data_quality}
    """
    has_fund_flow = any(d.get("main_net", 0) != 0 for d in data.get("daily", []))

    if data["target_type"] == "stock" and has_fund_flow:
        track = "A"  # 个股轨: 主力资金流 + 量价
    else:
        track = "B"  # ETF轨: 量价 + 消息面 + 行业资金流代理

    return {
        "track": track,
        "has_fund_flow": has_fund_flow,
        "track_label": "个股轨(资金流+量价)" if track == "A" else "ETF轨(量价+消息面)",
        "data_quality": "完整" if has_fund_flow else "量价分析(无资金流维度)",
    }
```

---

### 1.7 多平台交叉验证（V1.6 数据真实性保证）

> **核心原则**: ==数据不交叉验证，不写入报告。== 每个数据维度必须经过至少 2 个权威平台对比（差异 < 1% 为通过），唯一来源的数据标注"单源"风险。

#### 1.7a 新浪实时行情（替代验证源）

```python
def _fetch_realtime_sina(code: str) -> dict:
    """
    从新浪获取实时行情 — 作为腾讯的交叉验证源。
    新浪格式: 名称,今开,昨收,现价,最高,最低,...,成交量(股),成交额(元),...
    注意: 新浪不提供 PE/PB/市值，仅用于价格/量/额的交叉验证。
    """
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    try:
        r = requests.get(
            f"https://hq.sinajs.cn/list={prefix}{code}",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10
        )
        r.encoding = "gbk"
        data = r.text.split('"')[1].split(",")
        if len(data) < 30:
            return {"available": False, "reason": "数据字段不足"}

        return {
            "available": True,
            "name": data[0],
            "open": float(data[1]),
            "last_close": float(data[2]),
            "price": float(data[3]),
            "high": float(data[4]),
            "low": float(data[5]),
            "volume": int(float(data[8])),         # 股（非手！）
            "amount_yi": float(data[9]) / 1e8,     # 元→亿
            "change_pct": round((float(data[3]) - float(data[2])) / float(data[2]) * 100, 2),
        }
    except Exception as e:
        return {"available": False, "reason": str(e)[:80]}


def _cross_validate_realtime(tencent: dict, sina: dict) -> dict:
    """
    交叉验证腾讯 vs 新浪实时行情。
    差异阈值: 价格 < 0.5%, 成交额 < 2%, 成交量 < 5%（因单位换算容差）
    返回: {passed, checks: [{metric, tencent, sina, diff_pct, ok}], source_quality}
    """
    checks = []
    all_ok = True

    def compare(metric, tv, sv, threshold_pct, unit=""):
        nonlocal all_ok
        if tv is None or sv is None or sv == 0:
            return {"metric": metric, "tencent": tv, "sina": sv, "diff_pct": None, "ok": None, "note": "单源无法比较"}
        diff = abs(tv - sv) / abs(sv) * 100
        ok = diff < threshold_pct
        if not ok: all_ok = False
        return {"metric": metric, "tencent": tv, "sina": sv, "diff_pct": round(diff, 3), "ok": ok}

    # 价格类: 阈值 0.5%
    checks.append(compare("当前价", tencent.get("price"), sina.get("price"), 0.5))
    checks.append(compare("开盘价", tencent.get("open"), sina.get("open"), 0.5))
    checks.append(compare("最高价", tencent.get("high"), sina.get("high"), 0.5))
    checks.append(compare("最低价", tencent.get("low"), sina.get("low"), 0.5))
    checks.append(compare("昨收价", tencent.get("last_close"), sina.get("last_close"), 0.5))
    checks.append(compare("涨跌幅%", tencent.get("change_pct"), sina.get("change_pct"), 0.5))

    # 成交额: 阈值 2%
    tencent_amount = (tencent.get("amount_wan", 0) or 0) / 1e4  # 万→亿
    sina_amount = sina.get("amount_yi", 0)
    checks.append(compare("成交额(亿)", tencent_amount, sina_amount, 2.0))

    # 成交量: 阈值 5% (单位换算容差: 腾讯=手, 新浪=股)
    tencent_vol = (tencent.get("volume", 0) or 0) * 100  # 手→股
    sina_vol = sina.get("volume", 0)
    checks.append(compare("成交量(股)", tencent_vol, sina_vol, 5.0))

    # 数据质量评级
    passed = sum(1 for c in checks if c["ok"] is True)
    failed = sum(1 for c in checks if c["ok"] is False)
    single = sum(1 for c in checks if c["ok"] is None)

    if failed == 0 and single <= 2:
        quality = "🟢 高置信度(双源验证通过)"
    elif failed == 0:
        quality = "🟡 中等置信度(部分单源)"
    else:
        quality = f"🔴 低置信度({failed}项未通过交叉验证)"

    return {
        "passed": all_ok and failed == 0,
        "quality": quality,
        "checks": checks,
        "summary": f"通过{passed}项, 未通过{failed}项, 单源{single}项 → {quality}",
    }


def _fetch_realtime_with_validation(code: str) -> dict:
    """
    拉取实时行情 + 交叉验证。
    主源: 腾讯 → 验证源: 新浪 → 返回包含 validation 字段的行情数据。
    """
    # 主源: 腾讯
    realtime = _fetch_realtime_tencent(code)

    # 验证源: 新浪
    sina = _fetch_realtime_sina(code)

    if sina.get("available"):
        validation = _cross_validate_realtime(realtime, sina)
        realtime["_validation"] = validation
        realtime["_sources"] = ["腾讯", "新浪"]
    else:
        realtime["_validation"] = {
            "passed": None,
            "quality": "🟡 单源(新浪不可用)",
            "checks": [],
            "summary": f"仅腾讯单源 — 新浪不可用: {sina.get('reason', '未知')}",
        }
        realtime["_sources"] = ["腾讯"]

    return realtime
```

#### 1.7b 数据维度来源矩阵

| 维度 | 主源 | 验证源 | 验证方式 | 不可用时的 fallback |
|------|------|--------|---------|-------------------|
| K线(日) | 腾讯 qfqday | — | 单源，但腾讯K线经 vs 新浪行情价验证 | mootdx 备用 |
| 实时行情 | 腾讯 qt.gtimg.cn | 新浪 hq.sinajs.cn | 价格差异 < 0.5% | 仅腾讯单源标注 |
| PE/PB/市值 | 腾讯 (字段44-46) | — | 单源（新浪不提供） | 仅腾讯单源标注 |
| 个股资金流 | 东财 push2his | — | 单源（push2 唯一） | 降级为 B 轨量价分析 |
| 概念板块资金流 | 东财 push2 clist | — | 单源 | 行业资金流代理或标注不可用 |
| 融资融券 | 东财 datacenter-web | — | 单源（datacenter 唯一） | 标注不可用 |
| 新闻 | 东财 search-api-web | — | 单源 | 标注不可用 |

#### 1.7c 更新后的数据采集入口

```python
def fetch_all_data(target: str, target_type: str = "auto") -> dict:
    """
    统一数据采集入口 — V1.6 双源验证版。
    """
    data = {"target": target, "target_type": target_type}

    # ━━ Step 1: K线数据 (腾讯, 不封IP) ━━
    print("[1/6] 拉取腾讯日K线(qfq)...")
    data["daily"] = _fetch_kline_tencent(target, days=60)

    # ━━ Step 2: 实时行情 (腾讯主 + 新浪验证) ━━
    print("[2/6] 拉取实时行情(腾讯+新浪交叉验证)...")
    data["realtime"] = _fetch_realtime_with_validation(target)
    validation = data["realtime"].get("_validation", {})
    print(f"  数据质量: {validation.get('quality', '未知')}")

    # ━━ Step 3: 日级资金流 (仅个股, push2his代理可达时) ━━
    print("[3/6] 拉取个股资金流(push2his)...")
    fund_flow = []
    if target_type == "stock":
        try:
            fund_flow = stock_fund_flow_120d(target)
            print(f"  获取 {len(fund_flow)} 日资金流数据")
        except Exception as e:
            print(f"  ⚠️ push2his 不可用({e})，降级为量价分析模式")
    else:
        print(f"  ETF/板块无个股资金流，使用量价分析模式")
    if fund_flow:
        _merge_fund_flow(data["daily"], fund_flow)

    # ━━ Step 4: 新闻 ━━
    print("[4/6] 拉取新闻...")
    keyword = data["realtime"].get("name", target)
    try:
        data["news"] = eastmoney_stock_news(target, page_size=10)
    except Exception:
        data["news"] = []

    # ━━ Step 5: 行业资金流 ━━
    print("[5/6] 拉取行业板块资金流...")
    try:
        data["industry_flow"] = industry_comparison(top_n=50)
    except Exception:
        data["industry_flow"] = []

    # ━━ Step 6: 用实时行情更新最后一天 ━━
    print("[6/6] 数据合并完成")
    _update_last_day_with_realtime(data["daily"], data["realtime"])

    return data
```

---

## Layer 2: 安全信号提取（V1.3 双轨）—— 回答"企稳了吗？"

安全信号是买入的前提。没有安全信号 = 不能买，无论涨得多好。

**双轨逻辑**：A轨（个股,有资金流）用主力资金流信号 / B轨（ETF/板块,无量价外数据）用价格+成交量信号。每条信号标注适用轨。

### 2.1 卖压衰竭检测 (F1)

```python
def detect_selling_exhaustion(daily: list[dict], track: str = "B") -> dict:
    """
    F1: 卖压衰竭检测 —— 最核心的企稳信号。

    A轨(个股,有资金流):
      1. 近5日主力净流出额逐日递减
      2. 最新一日净流出 < 前5日均流出额的50%
      3. 股价不再创新低（近3日最低价 ≥ 前5日最低价）

    B轨(ETF/板块,量价分析):
      1. 近5日跌幅逐日收窄
      2. 成交量萎缩至前5日均量的70%以下
      3. 股价不再创新低
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}

    recent = daily[-5:]
    lows = [d["low"] for d in recent]
    prev_lows = [d["low"] for d in daily[-10:-5]]
    no_new_low = min(lows) >= min(prev_lows) if prev_lows else False

    if track == "A":
        # A轨: 基于主力资金流
        outflows = [d["main_net"] for d in recent if d["main_net"] < 0]
        if len(outflows) < 3:
            return {"triggered": False, "reason": "近期无持续流出，不需判断衰竭"}

        is_decreasing = all(
            abs(outflows[i]) > abs(outflows[i+1])
            for i in range(len(outflows) - 1)
        )
        avg_outflow = sum(abs(o) for o in outflows) / len(outflows)
        latest_outflow = abs(outflows[-1])
        ratio = latest_outflow / avg_outflow if avg_outflow > 0 else 1

        triggered = is_decreasing and ratio < 0.5 and no_new_low
        return {
            "triggered": triggered,
            "signal_name": "F1: 主力流出衰竭",
            "decreasing": is_decreasing,
            "latest_vs_avg_ratio": round(ratio, 2),
            "no_new_low": no_new_low,
            "strength": "强" if triggered and ratio < 0.3 else ("中" if triggered else "弱"),
            "meaning": "卖方力量在减弱，卖压接近衰竭" if triggered else "卖压尚未衰竭，继续观察",
        }
    else:
        # B轨: 基于价格+成交量
        declines = [abs(d["change_pct"]) for d in recent if d["change_pct"] < 0]
        is_decreasing = len(declines) >= 2 and all(
            declines[i] > declines[i+1] for i in range(len(declines)-1)
        )
        vols = [d["volume"] for d in recent]
        avg_vol_5 = sum(vols) / len(vols)
        prev_vols = [d["volume"] for d in daily[-10:-5]]
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
```

### 2.2 资金回流检测 (F2)

```python
def detect_institution_return(daily: list[dict], track: str = "B") -> dict:
    """
    F2: 资金回流检测

    A轨(个股): 前期机构(超大单)持续流出 → 近2日机构转为净流入 + 散户仍在流出
    B轨(ETF): 前期持续下跌 → 近3日有放量阳线(涨幅>2%+成交量>1.5x前5日均量)
    """
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}

    if track == "A":
        early = daily[-10:-3]
        recent = daily[-3:]
        early_inst = sum(d.get("super_net", 0) for d in early)
        recent_inst = sum(d.get("super_net", 0) for d in recent)
        recent_retail = sum(d.get("mid_net", 0) + d.get("small_net", 0) for d in recent)

        triggered = early_inst < 0 and recent_inst > 0 and recent_retail < 0
        return {
            "triggered": triggered,
            "signal_name": "F2: 机构试探回流",
            "early_institution_net": round(early_inst, 1),
            "recent_institution_net": round(recent_inst, 1),
            "recent_retail_net": round(recent_retail, 1),
            "strength": "强" if triggered and recent_inst > abs(early_inst) * 0.3 else ("中" if triggered else "弱"),
            "meaning": "机构开始接盘，散户还在恐慌 → 典型底部特征" if triggered else "机构尚未回流",
        }
    else:
        early = daily[-10:-3]
        recent = daily[-3:]
        early_decline = sum(d["change_pct"] for d in early) < -3
        avg_vol_early = sum(d["volume"] for d in early) / len(early)
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
```

### 2.3 恐慌出尽检测 (F3)

```python
def detect_retail_exhaustion(daily: list[dict], track: str = "B") -> dict:
    """
    F3: 恐慌出尽检测

    A轨(个股): 散户(中小单)连续5日净流出 + 近3日流出额逐日递减 + 跌幅收窄
    B轨(ETF): 近5日跌幅收窄 + 成交量显著萎缩（<前5日均量60%）
    """
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
        if len(prices) >= 5:
            early_decline = abs((prices[1]-prices[0])/prices[0]*100) if prices[0]>0 else 0
            late_decline = abs((prices[-1]-prices[-2])/prices[-2]*100) if prices[-2]>0 else 0
            decline_narrowing = late_decline < early_decline
        else:
            decline_narrowing = False

        triggered = all_outflow and is_decreasing and decline_narrowing
        return {
            "triggered": triggered,
            "signal_name": "F3: 散户恐慌出尽",
            "consecutive_outflow_days": 5,
            "decreasing": is_decreasing,
            "decline_narrowing": decline_narrowing,
            "strength": "强" if triggered else "弱",
            "meaning": "恐慌盘出清，筹码趋于稳定" if triggered else "恐慌盘可能尚未出尽",
        }
    else:
        recent = daily[-5:]
        changes = [d["change_pct"] for d in recent]
        negatives = [c for c in changes if c < 0]
        decline_narrowing = len(negatives) >= 2 and all(
            abs(negatives[i]) > abs(negatives[i+1]) for i in range(len(negatives)-1)
        )
        vols = [d["volume"] for d in recent]
        avg_vol_recent = sum(vols)/len(vols)
        prev_vols = [d["volume"] for d in daily[-10:-5]]
        avg_vol_prev = sum(prev_vols)/len(prev_vols) if prev_vols else avg_vol_recent
        vol_shrink = avg_vol_recent < avg_vol_prev * 0.6

        triggered = decline_narrowing and vol_shrink
        return {
            "triggered": triggered,
            "signal_name": "F3: 恐慌出尽(缩量)",
            "decline_narrowing": decline_narrowing,
            "volume_shrink": vol_shrink,
            "strength": "强" if triggered else "弱",
            "meaning": "恐慌盘出清，缩量止跌" if triggered else "恐慌盘可能尚未出尽",
        }
```

### 2.4 缩量止跌检测 (F8)

```python
def detect_volume_stabilization(daily: list[dict], track: str = "B") -> dict:
    """
    F8: 缩量止跌 —— 底部盘整中，下行空间有限。

    通用逻辑（A/B轨共用量价条件）:
    1. 股价连续3日涨跌幅在 ±2% 以内
    2. 成交量降至近20日均值的60%以下
    3. 近3日振幅 < 5%
    A轨附加: 主力净流出 < 前5日均流出额的30%
    """
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

    outflow_shrink = True  # B轨默认通过
    if track == "A":
        recent_main = sum(d["main_net"] for d in recent_3)
        prev_main = sum(abs(d["main_net"]) for d in daily[-8:-3])
        avg_prev_main = prev_main / 5 if prev_main != 0 else 1
        outflow_shrink = abs(recent_main) / 3 < avg_prev_main * 0.3

    triggered = narrow_range and volume_shrink and amp_narrow and outflow_shrink

    return {
        "triggered": triggered,
        "signal_name": "F8: 缩量止跌盘整",
        "narrow_range": narrow_range,
        "volume_shrink": volume_shrink,
        "amp_narrow": amp_narrow,
        "outflow_shrink": outflow_shrink,
        "avg_vol_20": round(avg_vol_20, 0),
        "recent_vol_3": round(recent_vol, 0),
        "strength": "强" if triggered else "弱",
        "meaning": "卖压枯竭，底部盘整中 → 下行空间有限" if triggered else "尚未缩量止跌，仍在波动",
    }
```

---

## Layer 2.5: 辅助盘面数据维度（V1.3 务实版）

> **V1.3 重要变化**：V1.2 中的五维辅助数据（融资融券/北向资金/大宗交易/股东户数/限售解禁）在实际运行中发现大部分受 push2his 代理拦截或仅适用于个股，V1.3 标注实际可用性如下。

### 可用性矩阵

| 维度 | 数据源 | 个股轨(A) | ETF轨(B) | 可靠性 | 备注 |
|------|--------|----------|---------|--------|------|
| 北向资金(全市场) | 同花顺 CSV 缓存 | ✅ | ✅ | 依赖本地缓存 | 非个股维度，反映外资整体态度 |
| 行业资金流 | 东财 push2 | ✅ | ✅(核心) | 中(限流可用) | ETF轨的核心代理指标 |
| 个股资金流(120日) | 东财 push2his | ✅(核心) | ❌ | 代理可能拦截 | 拦截时自动降级为量价模式 |
| 概念板块资金流 | 东财 push2 clist | ✅(代理) | ✅(代理) | 中(限流可用) | **V1.4新增** B轨核心代理指标，成分股排名 |
| 融资融券(个股) | 东财 datacenter-web | ✅ | ✅ | **低(非push2通道)** | **V1.4修正** filter用`SCODE`，全轨通用 |
| 大宗交易 | 东财 datacenter | ⚠️ | ❌ | 代理可能拦截 | 仅个股 |
| 股东户数 | 东财 datacenter | ⚠️ | ❌ | 代理可能拦截 | 季度数据，仅个股 |
| 限售解禁 | 东财 datacenter | ⚠️ | ❌ | 代理可能拦截 | 仅个股 |

> ✅ = 核心可用  ⚠️ = 代理可达时可用  ❌ = 不适用

### 辅助数据拉取（仅拉取确实可达的维度）

```python
def fetch_auxiliary_data(target: str, target_type: str) -> dict:
    """拉取辅助盘面数据 — V1.3 务实版，只拉取可能可达的维度"""
    aux = {}

    # 1. 行业资金流 (ETF轨核心代理, push2限流但通常可达)
    try:
        aux["industry_flow"] = industry_comparison(top_n=50)
    except Exception:
        aux["industry_flow"] = []

    # 2. 北向资金 (从本地CSV缓存读, 非个股维度)
    try:
        aux["north_bound"] = _fetch_north_bound_cache(30)
    except Exception:
        aux["north_bound"] = {"available": False}

    # 3. 以下仅个股 + 代理可达时尝试
    if target_type == "stock":
        # 融资融券
        try:
            aux["margin"] = _fetch_margin_data(target)
        except Exception:
            aux["margin"] = {"available": False}

    return aux


def _fetch_north_bound_cache(days: int = 30) -> dict:
    """从同花顺北向缓存CSV读取历史"""
    import csv, os
    csv_path = os.path.expanduser("~/.tradingagents/cache/northbound_daily.csv")
    if not os.path.exists(csv_path):
        return {"available": False, "reason": "北向缓存CSV不存在"}

    records = []
    with open(csv_path, "r") as f:
        for row in csv.DictReader(f):
            records.append({
                "date": row.get("date", ""),
                "hgt_net_yi": float(row.get("hgt", 0)),
                "sgt_net_yi": float(row.get("sgt", 0)),
            })
    records = records[-days:]

    recent_5 = sum(r["hgt_net_yi"] + r["sgt_net_yi"] for r in records[-5:])
    total_30 = sum(r["hgt_net_yi"] + r["sgt_net_yi"] for r in records)

    return {
        "available": True,
        "total_net_30d_yi": round(total_30, 2),
        "recent_5d_net_yi": round(recent_5, 2),
        "direction": "inflow" if recent_5 > 5 else ("outflow" if recent_5 < -5 else "neutral"),
    }


def _fetch_margin_data(code: str) -> dict:
    """拉取个股融资融券（需 proxy 可达）"""
    filter_str = f"(SECURITY_CODE='{code}')"
    raw = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX",
        filter_str=filter_str,
        page_size=30, sort_columns="DATE", sort_types="-1",
    )
    if not raw:
        return {"available": False, "reason": "无融资融券数据"}

    records = []
    for row in raw[:30]:
        records.append({
            "date": str(row.get("DATE", ""))[:10],
            "rzye": (row.get("RZYE") or 0) / 1e8,
            "rzmre": (row.get("RZMRE") or 0) / 1e8,
            "rzche": (row.get("RZCHE") or 0) / 1e8,
        })

    # 趋势分析
    if len(records) >= 10:
        recent_5 = sum(r["rzye"] for r in records[:5]) / 5
        prev_5 = sum(r["rzye"] for r in records[5:10]) / 5
        margin_trend = "上升" if recent_5 > prev_5 * 1.05 else ("下降" if recent_5 < prev_5 * 0.95 else "平稳")
        net_margin = sum(r["rzmre"] - r["rzche"] for r in records[:5])
    else:
        margin_trend = "数据不足"
        net_margin = 0

    return {
        "available": True,
        "latest_margin_balance_yi": records[0]["rzye"] if records else 0,
        "margin_trend": margin_trend,
        "net_margin_flow_5d_yi": round(net_margin, 2),
    }
```

---

## Layer 3: 危险信号检测（V1.3 双轨）—— 回答"有什么风险？"

危险信号优先级**高于**安全信号。只要有一个高危信号触发 → 不买/考虑离场。

### 3.1 加速下跌检测 (F4)

```python
def detect_accelerating_selling(daily: list[dict], track: str = "B") -> dict:
    """
    F4: 加速下跌 —— 最危险的信号，绝对不要抄底。

    A轨(个股): 主力连续3日净流出 + 每日流出额递增 + 最新流出>前5日均值2倍
    B轨(ETF): 连续3日下跌 + 每日跌幅递增 + 成交量逐日放大 + 最新量>前5日均量2倍
    """
    if len(daily) < 8:
        return {"triggered": False, "reason": "数据不足"}

    if track == "A":
        recent_3 = daily[-3:]
        prev_5 = daily[-8:-3]
        outflows = [d["main_net"] for d in recent_3]
        all_out = all(f < 0 for f in outflows)
        if not all_out:
            return {"triggered": False, "reason": "近期非持续流出"}
        accelerating = abs(outflows[0]) < abs(outflows[1]) < abs(outflows[2])
        avg_prev = sum(abs(d["main_net"]) for d in prev_5) / 5 if prev_5 else 1
        surge = abs(outflows[-1]) > avg_prev * 2
        triggered = all_out and accelerating and surge

        return {
            "triggered": triggered,
            "signal_name": "F4: 🔴 主力加速流出",
            "danger_level": "高危",
            "accelerating": accelerating,
            "latest_vs_avg_ratio": round(abs(outflows[-1]) / avg_prev, 1) if avg_prev > 0 else 0,
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
            "triggered": triggered,
            "signal_name": "F4: 🔴 加速放量下跌",
            "danger_level": "高危",
            "accelerating": accelerating,
            "volume_expanding": vol_expanding,
            "vol_surge_ratio": round(vols[-1] / avg_vol_prev, 1) if avg_vol_prev > 0 else 0,
            "meaning": "恐慌性抛售！放量加速下跌 → 绝对不要抄底！" if triggered else "下跌尚未加速",
            "action": "🚫 不买，持币观望" if triggered else "继续观察",
        }
```

### 3.2 高位逆转检测 (F5)

```python
def detect_top_distribution(daily: list[dict], track: str = "B") -> dict:
    """
    F5: 高位逆转 —— 典型的顶部信号。

    A轨(个股): 近5日股价上涨>3% + 机构(超大单)净流出 + 散户(中小单)净流入
    B轨(ETF): 前期(5-10日)涨幅>10% + 近2日出现放量暴跌(跌幅>3%+量>均量2x)
    """
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
            "price_up": price_up,
            "institution_outflow": inst_out,
            "retail_inflow": retail_in,
            "meaning": "机构在上涨中出货给散户 → 典型的派发结构" if triggered else "无顶部派发信号",
            "action": "🚫 不买，已持有则考虑减仓" if triggered else "继续观察",
        }
    else:
        early = daily[-10:-3]
        recent_2 = daily[-2:]
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
```

### 3.3 利好出尽检测 (F7)

```python
def detect_news_exhausted(daily: list[dict], news: list[dict]) -> dict:
    """
    F7: 利好出尽 —— A股最可靠的规律之一。A/B轨通用。

    判断逻辑:
    1. 近期有密集利好消息
    2. 消息当天或次日出现大跌（高开低走）
    3. 前期涨幅 > 10%
    → 历史回调概率 ~84%
    """
    if not news:
        return {"triggered": False, "reason": "无消息数据"}

    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}

    # 寻找利好消息关键词
    bullish_keywords = ['涨', '走强', '涨停', '利好', '突破', '新高', '订单', '扩产']
    bullish_news = [n for n in news if any(kw in n.get("title","") for kw in bullish_keywords)]

    # 检查前期涨幅
    early = daily[-15:-5] if len(daily) >= 15 else daily[:-5]
    if len(early) < 5:
        return {"triggered": False}
    early_closes = [d["close"] for d in early]
    pre_rise = (early_closes[-1]-early_closes[0])/early_closes[0]*100 if early_closes[0]>0 else 0

    # 消息当天是否高开低走（大跌）
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
```

---

## Layer 4: 安全区间综合评分（V1.3 track-aware）—— 回答"能不能买？"

```python
def calc_safety_score(
    safety_signals: dict,
    danger_signals: dict,
    daily: list[dict],
    track: str = "B",
    auxiliary_data: dict = None,
) -> dict:
    """
    安全区间综合评分 (0-100) — V1.3 track-aware。

    评分维度:
    主信号: F1(+12~15)/F2(+10~12)/F3(+10)/F8(+8)
    减分: F4(-20~22)/F5(-18~20)/F7(-15)
    企稳确认: +10
    趋势修正: 偏离20MA超买-5 / 超卖+5
    量价修正: 恐慌放量-5~-8 / 缩量止跌+3
    辅助数据: 北向资金-8~+8 / 融资融券-8~+5 (仅A轨+数据可达)
    """
    score = 50
    adjustment_details = []

    # ━━ 安全信号加分 ━━
    weight_map = {
        "f1_exhaustion": (15 if track == "A" else 12, "F1 流出衰竭" if track == "A" else "F1 卖压衰竭"),
        "f2_institution_return": (12 if track == "A" else 10, "F2 机构回流" if track == "A" else "F2 放量反弹"),
        "f3_retail_exhaustion": (10, "F3 恐慌出尽"),
        "f8_volume_stabilization": (8, "F8 缩量止跌"),
    }
    for key, (w, label) in weight_map.items():
        if safety_signals.get(key, {}).get("triggered"):
            score += w
            adjustment_details.append((label, +w))

    # ━━ 危险信号减分 ━━
    danger_weight_map = {
        "f4_accelerating": (22 if track == "A" else 20, "F4 加速流出" if track == "A" else "F4 加速放量下跌"),
        "f5_top_distribution": (20 if track == "A" else 18, "F5 顶部派发" if track == "A" else "F5 高位放量逆转"),
        "f7_news_exhausted": (15, "F7 利好出尽"),
    }
    for key, (w, label) in danger_weight_map.items():
        if danger_signals.get(key, {}).get("triggered"):
            score -= w
            adjustment_details.append((label, -w))

    # ━━ 企稳确认 ━━
    stabilization = check_stabilization(daily, track)
    if stabilization["is_stabilized"]:
        score += 10
        adjustment_details.append(("企稳确认", +10))

    # ━━ 趋势强度修正 ━━
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

    # ━━ 成交量异常修正 ━━
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

    # ━━ 辅助数据修正（仅数据可达时） ━━
    if auxiliary_data:
        if auxiliary_data.get("north_bound", {}).get("available"):
            nb = auxiliary_data["north_bound"]
            net_5d = nb.get("recent_5d_net_yi", 0)
            if net_5d < -10:
                score -= 5
                adjustment_details.append(("北向近5日流出>10亿", -5))
            elif net_5d > 10:
                score += 5
                adjustment_details.append(("北向近5日流入>10亿", +5))

        if auxiliary_data.get("margin", {}).get("available") and track == "A":
            margin = auxiliary_data["margin"]
            trend = margin.get("margin_trend", "")
            net_flow = margin.get("net_margin_flow_5d_yi", 0)
            if trend == "下降" and net_flow < -0.5:
                score -= 8
                adjustment_details.append(("融资去杠杆", -8))
            elif trend == "上升" and net_flow > 0.3:
                score += 5
                adjustment_details.append(("融资温和加杠杆", +5))

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
        "principle": "可以少挣，必须少亏 — 只有 ≥75 分才建议考虑入场",
    }


def check_stabilization(daily: list[dict], track: str = "B") -> dict:
    """
    企稳确认检查清单（5项，≥4项通过 = 企稳）。

    A轨(个股): 资金流版 — 包含主力流出减少检查
    B轨(ETF): 量价版 — 成交量不异常放大替代流出检查
    """
    if len(daily) < 15:
        return {"is_stabilized": False, "reason": "数据不足"}

    recent = daily[-3:]
    prev_10 = daily[-15:-3]
    checks = {}

    # 1. 不再创新低
    recent_lows = [d["low"] for d in recent]
    prev_lows = [d["low"] for d in prev_10]
    checks["no_new_low"] = min(recent_lows) >= min(prev_lows)

    # 2. 振幅收窄
    checks["narrow_range"] = all(d["amplitude"] < 5 for d in recent)

    # 3. 流出/量能正常
    if track == "A":
        recent_outflow = abs(sum(d["main_net"] for d in recent if d["main_net"] < 0))
        prev_outflow_avg = abs(sum(d["main_net"] for d in prev_10 if d["main_net"] < 0)) / max(len([x for x in prev_10 if x["main_net"] < 0]), 1)
        checks["flow_normal"] = recent_outflow < prev_outflow_avg * 0.5
    else:
        avg_vol_prev = sum(d["volume"] for d in prev_10) / len(prev_10)
        recent_vol = sum(d["volume"] for d in recent) / 3
        checks["flow_normal"] = recent_vol < avg_vol_prev * 1.5  # 不放量

    # 4. 最低价抬高
    checks["lows_rising"] = recent_lows[-1] >= recent_lows[0] if len(recent_lows) >= 2 else False

    # 5. 站上5日均线
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
        "passed_count": passed,
        "total_count": 5,
        "checks": checks,
        "meaning": "企稳确认，下行风险大幅降低" if is_stabilized else f"仅通过{passed}/5项，尚未企稳",
    }
```

---

## Layer 5: 买卖时机参考 —— 回答"什么时候动手？"

```python
def generate_timing_signals(
    safety_score: dict,
    safety_signals: dict,
    danger_signals: dict,
    daily: list[dict],
) -> dict:
    """
    生成买入/卖出时机参考条件。
    
    ⚠️ 这不是买卖建议！是"如果满足X条件，历史上胜率Y%"的参考框架。
    """
    
    # ━━ 买入参考条件 ━━
    entry_conditions = []
    
    # 条件1: 安全评分 ≥ 75
    entry_conditions.append({
        "condition": "安全评分 ≥ 75分",
        "met": safety_score["safety_score"] >= 75,
        "current": f"{safety_score['safety_score']}分",
        "weight": "必须",
    })
    
    # 条件2: 企稳确认（4/5项通过）
    entry_conditions.append({
        "condition": "企稳确认 (≥4/5项)",
        "met": safety_score["stabilization"]["is_stabilized"],
        "current": f"{safety_score['stabilization']['passed_count']}/5项",
        "weight": "必须",
    })
    
    # 条件3: 至少2个安全信号触发
    pos_count = len(safety_score["positive_signals"])
    entry_conditions.append({
        "condition": "≥2个安全信号触发",
        "met": pos_count >= 2,
        "current": f"{pos_count}个",
        "weight": "建议",
    })
    
    # 条件4: 无高危信号
    neg_count = len(safety_score["negative_signals"])
    entry_conditions.append({
        "condition": "无危险信号",
        "met": neg_count == 0,
        "current": f"{neg_count}个危险信号" if neg_count > 0 else "0个",
        "weight": "必须",
    })
    
    # 条件5: 放量阳线确认（可选增强信号）
    # 近3日有一日涨幅>2%+主力净流入
    recent_3 = daily[-3:] if len(daily) >= 3 else daily
    has_confirmation = any(
        d.get("change_pct", 0) > 2 and d["main_net"] > 0
        for d in recent_3
    )
    entry_conditions.append({
        "condition": "近日放量阳线确认（增强信号）",
        "met": has_confirmation,
        "current": "已出现" if has_confirmation else "未出现",
        "weight": "加分项（非必须）",
    })
    
    must_met = all(c["met"] for c in entry_conditions if c["weight"] == "必须")
    all_met = all(c["met"] for c in entry_conditions)
    
    # ━━ 卖出/离场参考条件 ━━
    exit_conditions = []
    
    # 硬止损: 亏损 > 5% + 主力仍在流出
    exit_conditions.append({
        "condition": "🔴 硬止损: 持仓亏损>5% + 主力仍在净流出",
        "triggered": False,  # 需要持仓信息才能判断
        "rule": "F13: 亏损控制 — 亏损的数学是不对称的",
        "action": "全部离场",
    })
    
    # 利润保护: 盈利 > 5% + 主力开始流出
    exit_conditions.append({
        "condition": "🟠 利润保护: 盈利>5% + 主力连续2日净流出",
        "triggered": False,  # 需要持仓信息
        "rule": "F12: 利润保护 — 可以少挣，必须少亏",
        "action": "至少减仓50%",
    })
    
    # 高危信号触发
    has_danger = neg_count > 0
    exit_conditions.append({
        "condition": "🔴 任何高危信号触发 (F4/F5/F6/F7)",
        "triggered": has_danger,
        "current": f"{neg_count}个危险信号" if has_danger else "无",
        "rule": "危险信号 > 一切买入信号",
        "action": "不买，已持有则评估是否离场",
    })
    
    # 安全评分 < 40
    exit_conditions.append({
        "condition": "🔴 安全评分降至 < 40分",
        "triggered": safety_score["safety_score"] < 40,
        "current": f"{safety_score['safety_score']}分",
        "rule": "危险区间 = 持币观望",
        "action": "远离，等安全评分回升",
    })
    
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
        "exit": {
            "any_triggered": any(c["triggered"] for c in exit_conditions),
            "conditions": exit_conditions,
        },
        "principle": "可以少挣，必须少亏 — 宁可错过，不可做错",
    }
```

---

## Layer 6: 主流程 + 输出

### 6.1 主流程（V1.3 track-aware）

```python
def assess_target_safety(target: str, target_type: str = "auto") -> dict:
    """
    标的安全区间评估主流程 — V1.3 双轨自适应。

    流程:
    0. 识别标的类型 → stock/etf/sector
    1. 拉取60天K线(腾讯) + 实时行情(腾讯) + 新闻(东财)
    2. 尝试拉取资金流(push2his, 仅个股)
    3. 评估数据完整度 → 选择信号轨 A(个股)/B(ETF)
    4. 执行对应轨的安全信号+危险信号检测
    5. 拉取辅助数据(行业资金流+北向缓存)
    6. 计算安全评分 + 企稳确认
    7. 生成买卖时机参考
    8. 输出报告
    """
    # ━━ 0. 识别标的类型 ━━
    if target_type == "auto":
        target_type = _auto_detect_type(target)
    print(f"[识别] {target_type}: {target}")

    # ━━ 1. 拉取核心数据 ━━
    data = fetch_all_data(target, target_type)
    if "error" in data:
        return data

    daily = data["daily"]
    print(f"  获取 {len(daily)} 个交易日")

    # ━━ 2. 评估数据完整度 → 选择信号轨 ━━
    completeness = _assess_data_completeness(data)
    track = completeness["track"]
    print(f"  信号轨: {completeness['track_label']} ({completeness['data_quality']})")

    # ━━ 3. 安全信号检测 (双轨) ━━
    print("[3/6] 安全信号检测...")
    safety_signals = {
        "f1_exhaustion": detect_selling_exhaustion(daily, track),
        "f2_institution_return": detect_institution_return(daily, track),
        "f3_retail_exhaustion": detect_retail_exhaustion(daily, track),
        "f8_volume_stabilization": detect_volume_stabilization(daily, track),
    }

    # ━━ 4. 危险信号检测 (双轨) ━━
    print("[4/6] 危险信号检测...")
    danger_signals = {
        "f4_accelerating": detect_accelerating_selling(daily, track),
        "f5_top_distribution": detect_top_distribution(daily, track),
        "f7_news_exhausted": detect_news_exhausted(daily, data.get("news", [])),
    }

    # ━━ 5. 辅助数据 ━━
    print("[5/6] 拉取辅助数据...")
    auxiliary_data = fetch_auxiliary_data(target, target_type)

    # ━━ 6. 安全评分 + 时机 ━━
    print("[6/6] 计算安全评分 + 生成时机参考...")
    safety_score = calc_safety_score(safety_signals, danger_signals, daily, track, auxiliary_data)
    timing = generate_timing_signals(safety_score, safety_signals, danger_signals, daily)

    # 价格摘要
    today = daily[-1] if daily else {}
    week_ago = daily[-6] if len(daily) >= 6 else daily[0]
    month_ago = daily[-22] if len(daily) >= 22 else daily[0]

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": target,
        "target_type": target_type,
        "target_name": data["realtime"].get("name", target),
        "track": track,
        "track_label": completeness["track_label"],
        "summary": {
            "price": data["realtime"].get("price", today.get("close", 0)),
            "last_close": data["realtime"].get("last_close", 0),
            "change": data["realtime"].get("change_amt", 0),
            "change_pct": data["realtime"].get("change_pct", 0),
            "high": data["realtime"].get("high", 0),
            "low": data["realtime"].get("low", 0),
            "volume": data["realtime"].get("volume", 0),
            "turnover_pct": data["realtime"].get("turnover_pct", 0),
            "change_1w": round((today.get("close", 0) - week_ago.get("close", 0)) / week_ago.get("close", 1) * 100, 1),
            "change_1m": round((today.get("close", 0) - month_ago.get("close", 0)) / month_ago.get("close", 1) * 100, 1),
        },
        "realtime": data["realtime"],
        "daily": daily,
        "industry_flow": auxiliary_data.get("industry_flow", []),
        "auxiliary_data": auxiliary_data,
        "safety_signals": safety_signals,
        "danger_signals": danger_signals,
        "safety_score": safety_score,
        "timing": timing,
        "news": data.get("news", [])[:8],
        "principle": "可以少挣，必须少亏。所有判断基于数据，每个信号绑定可验证条件。",
    }

    return report
```

### 6.2 Console 打印（V1.3 增强版 — 含资金组成+换手率+历史分位数）

```python
def print_safety_report(report: dict):
    """打印安全评估报告"""
    print()
    print("=" * 90)
    print("  🛡️  买入安全区间研判报告 (V1.3)")
    print(f"  标的: {report.get('target_name', report['target'])}")
    print(f"  类型: {report['target_type']} | 信号轨: {report.get('track_label', '')}")
    print(f"  生成: {report['generated_at']} | 原则: 可以少挣，必须少亏")
    print("=" * 90)

    # ━━ Part 1: 核心结论 ━━
    score = report["safety_score"]
    summary = report.get("summary", {})
    print()
    print("━" * 70)
    print("  🎯 Part 1: 核心结论")
    print("━" * 70)
    print(f"  当前价格: {summary.get('price', 0):.3f} | "
          f"涨跌: {summary.get('change', 0):+.3f} ({summary.get('change_pct', 0):+.2f}%)")
    print(f"  1周涨跌: {summary.get('change_1w', 0):+.1f}% | "
          f"1月涨跌: {summary.get('change_1m', 0):+.1f}%")

    # ━━ 数据来源质量 ━━
    realtime = report.get("realtime", {})
    validation = realtime.get("_validation", {})
    if validation:
        print(f"  数据质量: {validation.get('quality', '未知')} | {validation.get('summary', '')}")
    # 数据维度来源标注
    print(f"  数据来源: 行情[腾讯+新浪] | K线[腾讯] | PE/PB[腾讯单源] | 融资[东财单源]")

    print(f"  安全评分: {score['safety_score']}/100 → {score['safety_level']}")
    print(f"  企稳状态: {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} "
          f"({score['stabilization']['passed_count']}/5项)")
    print(f"  能否入场: {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'}")
    print(f"  判断依据: {score['description']}")

    # 评分构成
    if score.get("adjustment_details"):
        print(f"\n  📊 评分构成 (基准50):")
        for detail, adj in score["adjustment_details"]:
            sign = "+" if adj > 0 else ""
            print(f"     {sign}{adj:>+3d}  {detail}")

    # ━━ Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券） ━━
    print()
    print("━" * 70)
    print("  📋 Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）")
    print("━" * 70)
    daily = report.get("daily", [])
    realtime = report.get("realtime", {})
    track = report.get("track", "B")

    # ═══════════════════════════════════════════════════════════════
    # 2A: 日度量价明细
    # ═══════════════════════════════════════════════════════════════
    print()
    print("  ━" * 55)
    print("    📈 2A: 日度量价明细")
    print("  ━" * 55)

    if daily:
        # 计算20日均量用于量比
        vols_20 = [d["volume"] for d in daily[-25:-5]]
        avg_vol_20 = sum(vols_20) / len(vols_20) if vols_20 else 1
        # 60日历史分位数基准
        all_vols = [d["volume"] for d in daily]
        all_prices = [d["close"] for d in daily]
        vol_max = max(all_vols) if all_vols else 1
        vol_min = min(all_vols) if all_vols else 0
        price_60h = max(all_prices) if all_prices else 1
        price_60l = min(all_prices) if all_prices else 0

        # 表头: 根据信号轨显示不同列
        if track == "A":
            # 个股轨: 主力净流 + 走势（5项资金子列移到2B逐日明细）
            header = (f"  {'日期':<12s} {'收盘':>8s} {'涨跌':>7s} {'振幅':>6s} "
                      f"{'换手':>6s} {'量比':>6s} {'主力净流(万)':>13s} {'走势':>6s}")
            sub_header = f"  {'─'*85}"
        else:
            # ETF/板块轨: 价格+量+历史位置
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

            # 换手率估算
            turnover = realtime.get("turnover_pct", 0) if date == daily[-1]["date"] else 0
            if turnover == 0:
                float_shares = realtime.get("float_mcap_yi", 5) / realtime.get("price", 1) * 1e8 if realtime.get("price") else 5e8
                turnover = round(vol / float_shares * 100, 2) if float_shares > 0 else 0

            # 量比
            vol_ratio = round(vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0
            # 成交量在60日中的分位数
            vol_pct = round((vol - vol_min) / (vol_max - vol_min) * 100, 0) if vol_max > vol_min else 50
            # 价格在60日中的分位数
            price_pct = round((close - price_60l) / (price_60h - price_60l) * 100, 0) if price_60h > price_60l else 50

            # 走势标记
            if chg > 5: trend = "🔥大涨"
            elif chg > 2: trend = "📈上涨"
            elif chg > -2: trend = "➖震荡"
            elif chg > -5: trend = "📉下跌"
            else: trend = "💧暴跌"

            # 量比标记
            if vol_ratio > 2.5: vr = "🔴"
            elif vol_ratio > 1.5: vr = "🟠"
            elif vol_ratio < 0.5: vr = "🔵"
            else: vr = "  "

            # 分位数标记
            if vol_pct > 90: vp_mark = "🔴"
            elif vol_pct > 70: vp_mark = "🟠"
            elif vol_pct < 30: vp_mark = "🔵"
            else: vp_mark = "  "

            if price_pct > 90: pp_mark = "🔴"
            elif price_pct > 70: pp_mark = "🟠"
            elif price_pct < 30: pp_mark = "🔵"
            else: pp_mark = "  "

            if track == "A":
                main_net = d.get("main_net", 0)
                if main_net > 500: flow_mark = f"🔴 +{main_net:.0f}万"
                elif main_net > 0: flow_mark = f"🟢 +{main_net:.0f}万"
                elif main_net > -500: flow_mark = f"🟢 {main_net:.0f}万"
                else: flow_mark = f"🔴 {main_net:.0f}万"

                print(f"  {date:<12s} {close:>8.3f} {chg:>+6.2f}% {amp:>5.2f}% "
                      f"{turnover:>5.2f}% {vr}{vol_ratio:>5.1f}x {flow_mark:>13s} {trend}")
            else:
                print(f"  {date:<12s} {close:>8.3f} {chg:>+6.2f}% {amp:>5.2f}% "
                      f"{turnover:>5.2f}% {vr}{vol_ratio:>5.1f}x "
                      f"{vp_mark}{vol_pct:>5.0f}% {pp_mark}{price_pct:>5.0f}% {trend}")

        # 汇总行
        print(sub_header)
        today = daily[-1] if daily else {}
        today_vol = today.get("volume", 0)
        today_vol_ratio = round(today_vol / avg_vol_20, 1) if avg_vol_20 > 0 else 0
        today_vol_pct = round((today_vol - vol_min) / (vol_max - vol_min) * 100, 0) if vol_max > vol_min else 50
        today_price_pct = round((today.get("close", 0) - price_60l) / (price_60h - price_60l) * 100, 0) if price_60h > price_60l else 50

        print(f"  📊 今日量:{today_vol:,.0f} | 量比:{today_vol_ratio:.1f}x | "
              f"量分位:{today_vol_pct:.0f}%(60日) | 价分位:{today_price_pct:.0f}%(60日)")
        print(f"  📊 20日均量:{avg_vol_20:,.0f} | "
              f"60日最高价:{price_60h:.3f} | 60日最低价:{price_60l:.3f} | "
              f"距高:{(today.get('close',0)/price_60h-1)*100:+.1f}% | 距低:{(today.get('close',0)/price_60l-1)*100:+.1f}%")

        # 涨跌幅分布（紧凑版，紧接汇总行）
        all_changes = [d["change_pct"] for d in daily[-20:]]
        big_up = sum(1 for c in all_changes if c > 5)
        up = sum(1 for c in all_changes if 2 < c <= 5)
        flat = sum(1 for c in all_changes if -2 <= c <= 2)
        down = sum(1 for c in all_changes if -5 <= c < -2)
        big_down = sum(1 for c in all_changes if c < -5)
        print(f"  📊 近20日涨跌分布: 🔥大涨{big_up}天 📈上涨{up}天 ➖震荡{flat}天 📉下跌{down}天 💧暴跌{big_down}天")

    # ═══════════════════════════════════════════════════════════════
    # 2B: 资金流向详细
    # ═══════════════════════════════════════════════════════════════
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

            # 机构vs散户结构判断
            if inst_5d < -500 and small_5d > 100:
                print(f"  ⚠️  机构卖+散户买 → 🔴 筹码从机构→散户(派发结构)")
            elif inst_5d > 500 and small_5d < -100:
                print(f"  ✅ 机构买+散户卖 → 🟢 筹码从散户→机构(吸筹结构)")
            elif abs(inst_5d) < 500 and abs(small_5d) < 500:
                print(f"  ➖ 机构散户均平淡 → 方向不明，等待信号")

            # 10日vs5日资金趋势对比
            main_10d = sum(d.get("super_net", 0) + d.get("large_net", 0) for d in recent_10)
            trend_label = ("加速流入" if main_5d > main_10d * 0.7 else
                          ("流出放缓" if main_5d > main_10d * 0.3 else "趋势一致"))
            print(f"\n  📈 资金趋势对比:")
            print(f"     近10日主力: {main_10d/1e4:+.2f}亿 | 近5日主力: {main_5d/1e4:+.2f}亿 | {trend_label}")

            # 近5日每日资金明细（完整5项子列）
            print(f"\n  📅 近5日每日资金组成(万元):")
            print(f"  {'日期':<12s} {'主力净流':>10s} {'超大单(机构)':>12s} {'大单(游资)':>12s} {'中单':>10s} {'小单(散户)':>12s}")
            print(f"  {'─'*72}")
            for d in recent_5:
                print(f"  {d.get('date',''):<12s} {d.get('main_net',0):>8.0f}万 "
                      f"{d.get('super_net',0):>10.0f}万 {d.get('large_net',0):>10.0f}万 "
                      f"{d.get('mid_net',0):>8.0f}万 {d.get('small_net',0):>10.0f}万")

            # 连续流入/流出统计
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
            # B轨: 概念板块资金流代理（V1.4）
            concept_data = report.get("concept_flow", {})
            if concept_data and concept_data.get("available"):
                tf = concept_data.get("target_flow", {})
                print(f"  📊 概念板块资金流 (代理指标 — push2his不可用时)")
                print(f"  板块: {concept_data.get('board_code','')} | "
                      f"成分股{concept_data.get('stock_count',0)}只 | "
                      f"板块主力合计: {concept_data.get('total_main_net_yi',0):+.2f}亿")
                if tf:
                    main_yi = tf.get('main_net_yi', 0)
                    rank = concept_data.get('target_rank', 0)
                    total = concept_data.get('target_rank_total', 0)
                    flow_icon = "🔴" if main_yi < -1 else ("🟢" if main_yi > 1 else "➖")
                    leader_note = ("🔴 板块内主力流出最多" if main_yi < 0 and rank <= 3 else
                                  ("🟢 板块内主力流入龙头" if main_yi > 0 and rank <= 3 else ""))
                    print(f"  {flow_icon} 目标个股: 主力{main_yi:+.2f}亿 | 板块排名 {rank}/{total} | {leader_note}")
                # 板块成分股排名表
                print(f"\n  📋 板块成分股资金流排名(主力净流):")
                print(f"  {'排名':<5s} {'代码':<8s} {'名称':<10s} {'涨跌':>8s} {'主力净流':>10s}")
                print(f"  {'─'*48}")
                sorted_stocks = sorted(concept_data.get("stocks", []), key=lambda x: x['main_net_yi'], reverse=True)
                for i, s in enumerate(sorted_stocks):
                    marker = " ★目标" if s['code'] == report['target'] else ""
                    print(f"  {i+1:<5d} {s['code']:<8s} {s['name']:<10s} {s['change_pct']:>+7.2f}% {s['main_net_yi']:>+8.2f}亿{marker}")
            else:
                # 回退: 行业资金流
                industry_flows = report.get("industry_flow", [])
                if industry_flows:
                    print(f"  概念板块资金流: 暂不可取，回退到行业资金流(市场环境参考):")
                    for f in industry_flows[:5]:
                        name = f.get('name', '')
                        chg = f.get('change_pct', 0)
                        main_net = f.get('main_net', 0)
                        print(f"     {name}: 涨跌{chg:+.2f}% | 主力净流{main_net/1e8:+.2f}亿")
                else:
                    reason = concept_data.get("reason", "") if concept_data else ""
                    print(f"  资金流向: B轨无直接资金流数据，概念板块API也暂不可取" + (f" ({reason})" if reason else ""))

    # ═══════════════════════════════════════════════════════════════
    # 2C: 融资融券明细
    # ═══════════════════════════════════════════════════════════════
    print()
    print("  ━" * 55)
    print("    🏦 2C: 融资融券明细")
    print("  ━" * 55)
    # 兼容新旧 report 结构: margin_data(新) / auxiliary_data.margin(旧)
    margin_data = report.get("margin_data") or report.get("auxiliary_data", {}).get("margin", {})
    if margin_data and margin_data.get("available"):
        balance = margin_data.get("latest_balance_yi") or margin_data.get("latest_margin_balance_yi", 0)
        trend = margin_data.get("trend") or margin_data.get("margin_trend", "平稳")
        net_5d = margin_data.get("net_flow_5d_yi") or margin_data.get("net_margin_flow_5d_yi", 0)
        net_10d = margin_data.get("net_flow_10d_yi", 0)

        print(f"  最新融资余额: {balance:.2f}亿 | 趋势: {trend}")
        print(f"  近5日融资净买卖: {net_5d:+.2f}亿 | 近10日: {net_10d:+.2f}亿")
        records = margin_data.get("records", [])
        if records:
            print(f"\n  📅 近10日融资日度明细:")
            print(f"  {'日期':<12s} {'融资余额':>10s} {'买入额':>10s} {'偿还额':>10s} {'净买卖':>10s}")
            print(f"  {'─'*55}")
            for r in records[:10]:
                net_mark = "🔴" if r.get('net_yi', 0) > 1 else ("🟢" if r.get('net_yi', 0) < -1 else "  ")
                print(f"  {r['date']:<12s} {r.get('rzye_yi',0):>8.2f}亿 {r.get('rzmre_yi',0):>8.2f}亿 "
                      f"{r.get('rzche_yi',0):>8.2f}亿 {net_mark}{r.get('net_yi',0):>+8.2f}亿")
        else:
            print(f"  (无日度明细记录)")
    else:
        reason = ""
        if margin_data:
            reason = margin_data.get("reason", "")
        print(f"  融资融券: 数据暂不可取" + (f" ({reason})" if reason else ""))
    
    # ━━ Part 3: 安全信号 ━━
    print()
    print("━" * 60)
    print("  ✅ Part 3: 安全信号检测（企稳证据）")
    print("━" * 60)
    for key, sig in report["safety_signals"].items():
        triggered = sig.get("triggered", False)
        icon = "🟢" if triggered else "⚪"
        print(f"  {icon} {sig.get('signal_name', key)}")
        print(f"     {sig.get('meaning', '')}")
        if triggered:
            print(f"     强度: {sig.get('strength', '')}")
    
    # ━━ Part 3: 危险信号 ━━
    print()
    print("━" * 60)
    print("  🚨 Part 3: 危险信号检测（风险排查）")
    print("━" * 60)
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
    
    # ━━ Part 4: 企稳确认清单 ━━
    print()
    print("━" * 60)
    print("  📋 Part 4: 企稳确认清单 (需 ≥4/5)")
    print("━" * 60)
    checks = score["stabilization"]["checks"]
    labels = {
        "no_new_low": "不再创新低",
        "narrow_range": "振幅 < 5%",
        "outflow_reduced": "流出大幅减少",
        "lows_rising": "最低价抬高",
        "above_ma5": "站上5日均线",
    }
    for key, label in labels.items():
        ok = checks.get(key, False)
        print(f"  {'✅' if ok else '❌'} {label}")
    
    # ━━ Part 5: 时机参考 ━━
    timing = report["timing"]
    print()
    print("━" * 60)
    print("  ⏰ Part 5: 买入时机参考条件")
    print("━" * 60)
    for i, cond in enumerate(timing["entry"]["conditions"]):
        met = cond["met"]
        icon = "✅" if met else "❌"
        print(f"  {icon} [{cond['weight']}] {cond['condition']}")
        print(f"     当前: {cond['current']}")
    
    print(f"\n  综合判断: {timing['entry']['verdict']}")
    
    # ━━ Part 6: 离场预警 ━━
    print()
    print("━" * 60)
    print("  🚪 Part 6: 离场/风控参考")
    print("━" * 60)
    for cond in timing["exit"]["conditions"]:
        triggered = cond["triggered"]
        icon = "🔴" if triggered else "  "
        print(f"  {icon} {cond['condition']}")
        if triggered:
            print(f"     规则: {cond.get('rule', '')}")
            print(f"     建议: {cond.get('action', '')}")
    
    # ━━ Part 7: 关键消息 ━━
    news = report.get("news_highlights", [])
    if news:
        print()
        print("━" * 60)
        print("  📰 Part 7: 近期关键消息")
        print("━" * 60)
        for n in news[:5]:
            impact_emoji = {"S": "🔴", "A": "🟠", "B": "🟡"}.get(n.get("impact", ""), "")
            print(f"  {impact_emoji} [{n.get('impact', '')}级] {n.get('date', '')} | {n.get('title', '')[:60]}")
    
    # ━━ Footer ━━
    print()
    print("=" * 80)
    print("  ⚠️ 研究声明:")
    print("  1. 安全评分基于可验证的资金流规则，每条规则标注历史胜率")
    print("  2. 买入/卖出参考条件是可验证的信号框架，不是买卖指令")
    print("  3. 核心原则: 可以少挣，必须少亏 — 安全评分<60坚决不入场")
    print("  4. 亏损的数学是不对称的: 亏50%需涨100%回本")
    print("  5. 所有概率基于历史统计，不代表未来必然重复")
    print("=" * 80)
```

### 6.3 保存到文件

```python
def save_safety_report(report: dict, output_dir: str = None):
    """保存安全评估报告"""
    target = report.get("target_name", report["target"]).replace("/", "-")
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    if output_dir is None:
        output_dir = f"src/资金预判/{date_str}-{target}-安全评估"
    
    os.makedirs(output_dir, exist_ok=True)
    
    # JSON
    json_path = os.path.join(output_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    # Markdown
    md_path = os.path.join(output_dir, "report.md")
    _save_safety_markdown(report, md_path)
    
    print(f"  报告已保存: {output_dir}/")
    return output_dir


def _save_safety_markdown(report: dict, path: str):
    """生成 Markdown 格式安全评估报告 — V1.5 Part 2 统一版（2A/2B/2C）"""
    lines = []
    score = report["safety_score"]
    summary = report.get("summary", {})
    daily = report.get("daily", [])
    realtime = report.get("realtime", {})
    track = report.get("track", "B")
    timing = report.get("timing", {})

    # ━━ 头部 ━━
    lines.append(f"# 🛡️ 买入安全区间研判报告")
    lines.append(f"")
    lines.append(f"**标的**: {report.get('target_name', report['target'])} | **类型**: {report['target_type']} | **信号轨**: {report.get('track_label', '')}")
    lines.append(f"**生成时间**: {report['generated_at']} | **原则**: 可以少挣，必须少亏")
    lines.append(f"")
    lines.append(f"## Part 1: 核心结论")
    lines.append(f"")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 当前价格 | {summary.get('price', 0):.3f} |")
    lines.append(f"| 涨跌 | {summary.get('change', 0):+.3f} ({summary.get('change_pct', 0):+.2f}%) |")
    lines.append(f"| 1周涨跌 | {summary.get('change_1w', 0):+.1f}% |")
    lines.append(f"| 1月涨跌 | {summary.get('change_1m', 0):+.1f}% |")
    lines.append(f"| 安全评分 | **{score['safety_score']}/100 → {score['safety_level']}** |")
    lines.append(f"| 企稳状态 | {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} ({score['stabilization']['passed_count']}/5项) |")
    lines.append(f"| 能否入场 | {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'} |")

    # 数据来源质量
    realtime_md = report.get("realtime", {})
    validation_md = realtime_md.get("_validation", {})
    if validation_md:
        lines.append(f"| 数据质量 | {validation_md.get('quality', '未知')} |")
    lines.append(f"")
    lines.append(f"> **数据来源**: 行情[腾讯+新浪交叉验证] | K线[腾讯] | PE/PB[腾讯单源] | 融资融券[东财单源]")
    lines.append(f"")
    lines.append(f"**判断依据**: {score['description']}")
    lines.append(f"")
    if score.get("adjustment_details"):
        lines.append(f"### 评分构成 (基准50)")
        lines.append(f"")
        for detail, adj in score["adjustment_details"]:
            sign = "+" if adj > 0 else ""
            lines.append(f"- {sign}{adj:>+3d}  {detail}")
    lines.append(f"")

    # ═══════════════════════════════════════════════════════════════
    # Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）
    # ═══════════════════════════════════════════════════════════════
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Part 2: 近20日日度数据明细（成交量 + 资金流向 + 融资融券）")
    lines.append(f"")

    # ━━ 2A: 日度量价明细 ━━
    lines.append(f"### 2A: 日度量价明细")
    lines.append(f"")
    if daily:
        vols_20_md = [d["volume"] for d in daily[-25:-5] if d.get("volume")]
        avg_vol_20_md = sum(vols_20_md) / len(vols_20_md) if vols_20_md else 1
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
            float_shares = realtime.get("float_mcap_yi", 1) / realtime.get("price", 1) * 1e8 if realtime.get("price") else 5e8
            turnover_md = round(vol / float_shares * 100, 2) if float_shares > 0 else 0
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
                lines.append(f"| {date} | {close:.3f} | {chg:+.2f}% | {amp:.2f}% | {turnover_md:.2f}% | {vol_ratio_md:.1f}x | {price_pct_md:.0f}% | {trend} |")

        # 汇总
        today_md = daily[-1] if daily else {}
        today_vol_md = today_md.get("volume", 0)
        today_vol_ratio_md = round(today_vol_md / avg_vol_20_md, 1) if avg_vol_20_md > 0 else 0
        today_vol_pct_md = round((today_vol_md - vol_min_md) / (vol_max_md - vol_min_md) * 100, 0) if vol_max_md > vol_min_md else 50
        today_price_pct_md = round((today_md.get("close", 0) - price_60l_md) / (price_60h_md - price_60l_md) * 100, 0) if price_60h_md > price_60l_md else 50

        lines.append(f"")
        lines.append(f"> **今日量**: {today_vol_md:,.0f} | **量比**: {today_vol_ratio_md:.1f}x | **量分位(60日)**: {today_vol_pct_md:.0f}% | **价分位(60日)**: {today_price_pct_md:.0f}%")
        lines.append(f"> **20日均量**: {avg_vol_20_md:,.0f} | **60日最高价**: {price_60h_md:.3f} | **60日最低价**: {price_60l_md:.3f}")
        lines.append(f"")

        # 成交量分位表
        lines.append(f"#### 成交量历史分位(60日)")
        lines.append(f"")
        lines.append(f"| 周期 | 均量 | 分位 |")
        lines.append(f"|------|------|------|")
        for label, window in [("今日", 1), ("近5日", 5), ("近10日", 10), ("近20日", 20)]:
            if len(daily) >= window:
                wvol = sum(d["volume"] for d in daily[-window:]) / window
                wvol_pct = round((wvol - vol_min_md) / (vol_max_md - vol_min_md) * 100, 0) if vol_max_md > vol_min_md else 50
                lines.append(f"| {label} | {wvol:,.0f} | {wvol_pct:.0f}% |")
    lines.append(f"")

    # ━━ 2B: 资金流向详细 ━━
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

    # ━━ 2C: 融资融券明细 ━━
    lines.append(f"### 2C: 融资融券明细")
    lines.append(f"")
    margin_md = report.get("margin_data") or report.get("auxiliary_data", {}).get("margin", {})
    if margin_md and margin_md.get("available"):
        balance_md = margin_md.get("latest_balance_yi") or margin_md.get("latest_margin_balance_yi", 0)
        trend_md = margin_md.get("trend") or margin_md.get("margin_trend", "平稳")
        net_5d_md = margin_md.get("net_flow_5d_yi") or margin_md.get("net_margin_flow_5d_yi", 0)
        net_10d_md = margin_md.get("net_flow_10d_yi", 0)

        lines.append(f"**最新融资余额**: {balance_md:.2f}亿 | **趋势**: {trend_md}")
        lines.append(f"**近5日净买卖**: {net_5d_md:+.2f}亿 | **近10日净买卖**: {net_10d_md:+.2f}亿")
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
    lines.append(f"")

    # ━━ Part 3-7 保持原有逻辑 ━━
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
    any_danger = False
    for key, sig in report["danger_signals"].items():
        triggered = sig.get("triggered", False)
        if triggered:
            any_danger = True
            lines.append(f"- 🔴 **{sig.get('signal_name', key)}** (危险等级: {sig.get('danger_level', '')})")
            lines.append(f"  - {sig.get('meaning', '')}")
            lines.append(f"  - → {sig.get('action', '')}")
    if not any_danger:
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
```

---

## 快速参考

### 核心调用

```python
# 一键安全评估
report = assess_target_safety("半导体概念")  # 概念板块
report = assess_target_safety("300339")       # 个股
report = assess_target_safety("512480")       # ETF

# 打印+保存
print_safety_report(report)
save_safety_report(report)
```

### 安全评分速查

| 评分 | 等级 | 含义 | 行动 |
|------|------|------|------|
| ≥ 75 | 🟢 安全 | 下行风险可控 | 可考虑入场 |
| 60-74 | 🟡 接近安全 | 还差1-2个条件 | 再观察1-2日 |
| 40-59 | 🟠 风险 | 信号不足/有风险 | 不建议入场 |
| < 40 | 🔴 危险 | 高危信号触发 | 远离/考虑离场 |

### 核心原则（每步对照）

1. **可以少挣，必须少亏** — 安全评分 < 60 坚决不入场
2. **危险信号优先** — 一个 F4/F5/F7 触发，忽略所有买入信号
3. **企稳是前提** — 未企稳的"反弹"大概率是下跌中继
4. **数据说话** — 每个结论绑定具体信号+历史胜率
5. **保守入场，果断离场** — 买入要等确认，卖出不必等确认

---

## 风险声明

- 安全评分基于可验证的价格/成交量/消息面规则，不代表未来必然重复
- 买入/卖出参考条件是信号框架，不是买卖指令
- 核心原则"可以少挣，必须少亏"意味着保守入场、果断离场
- 亏损的数学是不对称的（亏50%需涨100%回本），风控永远第一
- ETF 分析无个股资金流维度，使用量价+行业资金流代理指标
- 所有分析基于公开数据，不构成投资建议

---

## V1.3 Changelog（2026-07-10 实盘验证驱动）

本次升级由"半导体设备ETF国泰(159516)"实盘分析中发现的 8 个问题驱动：

### 数据源重构
1. **K线主源切换**：`stock_kline()`(push2his+mootdx回退) → 腾讯 `qfqday` HTTP 直连（不封IP，ETF/个股均可用）
2. **tencent_quote 解析修正**：绕过 `a_stock_api.tencent_quote()` 的 code/name/price 字段映射 bug，直接解析腾讯原始 `~` 分隔格式
3. **函数参数修正**：`eastmoney_stock_news(page_size=10)` 替代错误的 `count` 参数；`stock_fund_flow_120d()` 无 `limit` 参数
4. **代理拦截处理**：push2his 代理拦截时自动降级为量价分析模式，不报错

### 双轨信号系统
5. **A轨(个股)**：主力资金流(超大单/大单/中单/小单) → F1-F5 资金流版
6. **B轨(ETF/板块)**：量价+消息面 → F1-F5 量价版，行业资金流作为代理指标
7. **自动轨选择**：检测 `daily[].main_net` 是否有非零值 → 有=A轨, 无=B轨

### 输出增强
8. **资金组成成分**：近20日表中显示超大单/大单/中单/小单(万元)分解（A轨）
9. **换手率**：从腾讯实时行情 `turnover_pct` 获取，历史日通过成交量/流通份额估算
10. **历史分位数**：量分位(成交量在60日中的百分位) + 价分位(价格在60日中的百分位)，可视化进度条
11. **融资情况**：A轨+数据可达时显示融资余额趋势和近5日净买卖
12. **资金趋势对比**：10日 vs 5日主力资金趋势对比，加速/放缓/一致判断
13. **涨跌分布**：近20日五档涨跌分布统计

### 辅助数据务实化
14. 标注各维度实际可用性（北向=CSV缓存/行业资金流=限流可用/融资本=代理可达/大宗+股东+解禁=代理大概率不可达）
15. 精简辅助数据拉取到确实可达的 3 个维度（行业资金流+北向缓存+融资融券）

### 评分优化
16. 加入成交量异常修正（恐慌放量-5~-8 / 缩量止跌+3）
17. 加入趋势强度修正（偏离20MA超买-5 / 超卖+5）
18. A/B 轨差异化权重（A轨资金流信号权重大于B轨量价信号）

---

## V1.4 Changelog（2026-07-11 实盘验证驱动）

本次升级由"中国巨石(600176)"实盘分析中发现的问题驱动：B轨个股因 push2his 不可用导致 Part 2.5 资金流向和融资情况双双缺失。

### 新增数据源

19. **融资融券 API 打通**：发现 `datacenter-web.eastmoney.com` API 的 filter 列名为 `SCODE`（非 `SECURITY_CODE`），全轨通用，返回个股日度融资余额/买入/偿还明细
20. **概念板块资金流代理**：push2 clist `b:BKXXXX` 获取板块内全部成分股主力资金流排名，B轨无直接资金流时作为代理指标
21. **个股→概念板块自动映射**：`STOCK_CONCEPT_MAP` 手工维护 + 东财搜索 API 回退

### 输出补齐（B轨 Part 2.5 不再缺失）

22. **资金流向（始终展示）**：
    - A轨：个股主力资金流分解（超大单/大单/中单/小单）
    - B轨：概念板块成分股资金流排名（代理指标，含目标个股排名）
23. **融资融券（全轨通用）**：融资余额 + 趋势 + 近5/10日净买卖 + 近10日日度明细
24. 各维度数据不可用时明确标注原因（如"概念板块API限流中"），而非笼统的"数据不可用"

### 评分修正

25. **融资趋势修正**（全轨）：
    - 去杠杆（趋势下降 + 近5日净<-1亿）→ -7
    - 温和下降（趋势下降 + 近5日净<0）→ -4
    - 加杠杆（趋势上升 + 近5日净>2亿）→ +5
    - 温和上升（趋势上升 + 近5日净>0）→ +3
26. **概念板块龙头修正**（B轨）：个股是板块主力流入第一名 → +4

### 已知限制更新

27. `SCODE`（非 `SECURITY_CODE`）是 datacenter-web 融资融券 API 的正确过滤列名
28. push2 clist 概念板块 API 有频率限制，连续请求过多会 502，生产环境中单次调用正常
29. 概念板块映射表需维护 `STOCK_CONCEPT_MAP`，未映射个股通过搜索 API 回退

---

## V1.5 Changelog（2026-07-11 结构优化）

本次升级由 Part 2 输出结构碎片化问题驱动：量价在 Part 2、资金组成+融资明细在 Part 2.5，且 Markdown 输出严重缺失。

### Part 2 统一重构

30. **三级子结构（2A/2B/2C）**：Part 2 统一为三层子区段，一次展示成交量+资金流向+融资融券
    - **2A: 日度量价明细** — 近20日核心扫描表（A轨含主力净流列，B轨含量/价分位列）
    - **2B: 资金流向详细** — A轨资金组成+5日逐日明细+机构vs散户结构；B轨概念板块成分股排名
    - **2C: 融资融券明细** — 融资余额+趋势+近10日日度明细表（全轨通用）
31. **删除 Part 2.5**：原 Part 2.5 内容全部纳入 Part 2 子区段，消除碎片化
32. **Markdown 补齐**：新增 `_save_safety_markdown()` 完整实现，Console 级别的全量数据（资金流+融资+历史分位）首次进入 Markdown 报告
33. **A轨表格精简**：日度表从13列缩减至7列（去除超大单/大单/中单/小单），子项明细移至 2B 逐日表
34. **向后兼容**：新旧 report 结构兼容（`margin_data` / `auxiliary_data.margin` 双键回退）

### 已知改进

35. 两个参考脚本（600176.py、159516.py）同步对齐至 V1.5 Console + Markdown 输出结构

---

## V1.7 Changelog（2026-08-07 实盘验证驱动 — 资金流字段映射修复）

本次升级由"铖昌科技(001270)"实盘分析中发现：A轨资金流数据拉取成功却误判B轨，追溯出 `fetch_fund_flow`/`_merge_fund_flow` 的字段映射与单位双 bug。

### 已知陷阱（新增 skill 定义 + 12 个脚本已修）

45. **字段名不匹配**：`stock_fund_flow_120d` 返回 `main_net_yi`/`super_large_net`/`large_net_yi`/`mid_net_yi`/`small_net_yi`，若取 `main_net`/`super_net` → 全为 0 → `determine_track` 误判 B 轨（丢失整个资金流维度）。
46. **单位命名误导**：返回字段虽带 `_yi` 后缀，实际单位是【万元】（元÷10000），不是亿元。若再 ÷1e4（缩1万倍）或 ×10000（放1万倍）→ 数值荒谬（如5日主力"2.7万亿"）。
47. **正确做法**：直接透传 `item.get("main_net_yi")` 等，不做任何换算；`daily[].main_net` 单位即万元。
48. **受影响脚本**：001270/000725/600176/600745/600219/600392/600875/601179/600879/601868/601991/601899 共 12 个 `fund_flow_predictor_*.py` 已批量修复；SKILL.md `_merge_fund_flow` 示例同步修正。

### 触发场景记录
- 001270 首跑显示"合并60日资金流数据"却走 B 轨 → 字段名 bug；改字段后数值"2.7万亿" → 单位 bug。两 bug 叠加导致 A 轨长期静默失效。

---

## V1.6 Changelog（2026-07-11 数据真实性保障）

本次升级由"数据必须经过多个权威平台交叉验证才能写入报告"这一硬性要求驱动。

### 多平台交叉验证层

36. **新浪行情作为第二验证源**：新增 `_fetch_realtime_sina()` — 通过 `hq.sinajs.cn` 获取实时行情，与腾讯数据进行交叉验证
37. **自动交叉验证**：新增 `_cross_validate_realtime()` — 对比腾讯 vs 新浪 8 项指标（价格/量/额），差异阈值：价格 < 0.5%，成交额 < 2%，成交量 < 5%
38. **数据质量评级**：报告 Part 1 新增数据质量标注行，展示交叉验证结果
    - 🟢 高置信度：全部双源验证通过
    - 🟡 中等置信度：部分单源但无不一致
    - 🔴 低置信度：存在双源不一致
39. **数据来源透明标注**：报告明确标注每个维度的数据来源（如"行情[腾讯+新浪] | PE[腾讯单源] | 融资[东财单源]"）
40. **600176.py 实装**：`fetch_realtime_with_validation()` 函数已实装到脚本中，实测"通过8项, 未通过0项"全部达标

### 设计原则

41. **不交叉验证，不写入报告** — 每个数据维度至少 1 个权威来源，优先 2 个来源对比
42. **单源标注** — 无法获取第二来源的维度（PE/PB/融资融券），明确标注"单源"风险
43. **API 不可用时优雅降级** — 新浪不可用时标注"仅腾讯单源"，而非报错或使用不可靠数据
44. **差异检测** — 超出阈值的差异触发 🔴 低置信度警告，提醒用户注意数据风险
