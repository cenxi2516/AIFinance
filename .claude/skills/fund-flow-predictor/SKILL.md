---
name: fund-flow-predictor
description: 买入安全区间研判器 — 拉取指定标的近30天全维度盘面数据(资金流向+涨跌幅+情绪+消息+融资融券+北向资金+大宗交易+股东户数+限售解禁)，核心回答"现在能不能买？是否已企稳？风险是否降到了安全范围？该不该卖？" 内置15条可验证规则，输出0-100安全评分+企稳确认+买入/离场参考条件。核心原则：可以少挣，必须少亏，所有判断用数据说话。Use when 用户询问"XX能不能买""XX企稳了吗""现在安全吗""什么时候可以入场""要不要卖/离场""风险大不大""下跌空间还有多少""XX回调到位了吗"等需要基于资金面判断买入/卖出时机时。
version: 1.2.0
updated: 2026-07-10
---

# 买入安全区间研判器 V1.2

**定位**：14 技能架构的**风险-机会平衡研判引擎**——聚焦单一标的，融合全维度盘面数据，不预测"能涨多少"，只回答四个问题：

> 1. **能不能买？** → 安全评分 + 企稳确认
> 2. **风险多大？** → 下行风险量化 + 危险信号检测
> 3. **什么时候买？** → 买入参考条件（精确到信号触发日）
> 4. **该不该卖？** → 离场预警 + 利润保护 + 亏损控制

**V1.2 新增**：融资融券 + 北向资金 + 大宗交易 + 股东户数 + 限售解禁 五维辅助验证，与资金流主信号交叉确认。

**核心原则**：==可以少挣，必须少亏。== 亏损的数学是不对称的（亏50%需涨100%回本），因此：
- 买入判断**保守优先**：宁错过，不做错
- 离场判断**敏感优先**：盈利回吐比踏空更痛苦
- 所有判断**数据说话**：每个结论绑定具体信号+历史胜率+样本数

> **与现有 skill 的关系：**
> - `capital-flow-tracker`：告诉你"钱现在在哪" → 本 skill：告诉你"现在安不安全、能不能动"
> - `quant-dashboard`：全市场自上而下研判 → 本 skill：单标的深度安全评估
> - `industry-sentiment-tracker`：行业情绪温度计 → 本 skill：情绪是否到了安全/危险区间
>
> **设计原则：** 依赖 a-stock-data 的通用 helper，聚焦 30 天日度数据 → 安全信号提取 → 买入/卖出时机判断。

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

## 核心框架：安全区间六层研判引擎

```
                        ┌──────────────────────────────────────┐
                        │     fund-flow-predictor V1.2          │
                        │   买入安全区间研判 + 买卖时机参考       │
                        │   核心原则: 可以少挣，必须少亏          │
                        └──────────────┬───────────────────────┘
                                       │
        ┌──────────┬──────────┬───────┼───────┬──────────┐
        ▼          ▼          ▼       ▼       ▼          ▼
    push2his    push2      腾讯    东财新闻  industry-  龙虎榜   融资融券
    日级资金    clist      行情    搜索API  sentiment  (个股)   北向资金
    流K线      板块资金                    情绪快照           大宗交易
                                                           股东户数
                                                           限售解禁
                                       │
                   ┌───────────────────┴───────────────────┐
                   ▼                                       ▼
        ┌──────────────────┐                    ┌──────────────────┐
        │ Layer 1: 30天数据  │                    │ 15条可验证规则     │
        │ 资金+涨跌+情绪+消息│                    │ F1-F8: 企稳/安全   │
        └────────┬─────────┘                    │ F9-F11: 买入时机   │
                 │                               │ F12-F14: 离场/风控 │
                 ▼                               │ F15: 情绪共振      │
        ┌──────────────────┐                    └────────┬─────────┘
        │ Layer 2: 安全信号  │                             │
        │ 卖压衰竭/机构回流  │ ←──────────────────────────┘
        │ 恐慌出尽/缩量止跌  │
        └────────┬─────────┘
                 │
                 ▼
        ┌──────────────────┐
        │ Layer 3: 危险信号  │ → F4 主力加速流出 / F5 顶部派发
        │ (排除法:先确保安全)│ → F6 高位放量滞涨 / F7 利好出尽
        └────────┬─────────┘
                 │
                 ▼
        ┌──────────────────────────────────────────┐
        │ Layer 4: 安全区间评分 (0-100)             │
        │  🟢 ≥75: 安全 — 下行风险可控，可考虑入场  │
        │  🟡 60-74: 接近安全 — 再观察1-2日        │
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

## Prerequisites — 数据拉取全部委托给 a-stock-api

本 skill **不内置数据拉取代码**。所有行情/资金流/新闻/融资融券/大宗交易/股东户数/解禁数据，统一通过项目共享模块 `a_stock_api` 获取。

```python
import sys
sys.path.insert(0, '.claude/skills/_shared')
from a_stock_api import (
    # 行情 & K线（腾讯/mootdx，不封IP）
    tencent_quote,            # 替代内联的 tencent_quote()
    # 资金流（东财独有，已内置限流）
    stock_fund_flow_120d,     # 替代内联的 fund_flow_daily()
    eastmoney_fund_flow_minute,  # 替代内联的 fund_flow_minute()
    # 板块数据
    industry_comparison,      # 替代内联的 concept_sector_flow()
    eastmoney_concept_blocks, # 个股概念板块归属
    # 辅助数据（东财 datacenter）
    em_get,                   # 东财统一请求入口（已内置限流+重试）
    eastmoney_datacenter,     # 数据中心通用查询
    # 新闻
    eastmoney_stock_news,     # 替代内联的 stock_news()
    # 北向/融资/大宗/股东/解禁 — 直接用 em_get + datacenter 调用
    # (具体 reportName 参数见 a-stock-data SKILL.md)
)
```

> **数据源优先级**：① 腾讯(行情)不封IP ② mootdx(K线,TCP)不封IP ③ push2(分钟资金流) ④ push2his(日级资金流) ⑤ 东财search(新闻)
>
> **关键单位提醒**：
> - `stock_fund_flow_120d()` 返回的主力净额已换算为**亿元**
> - `tencent_quote()` 返回的 price/PE/PB/市值 已做类型转换

---

## Layer 1: 数据采集流程

不内置代码，按以下步骤调用上述函数：

```python
def collect_all_data(target: str, target_type: str = "stock") -> dict:
    """
    统一数据采集入口。
    返回: {realtime, kline, fund_flow_minute, fund_flow_daily, news, sector_flow}
    """
    data = {"target": target, "target_type": target_type}
    
    # Step 1: 实时行情（腾讯，不封IP）
    data["realtime"] = tencent_quote([target])
    
    # Step 2: K线数据（腾讯，不封IP）
    data["kline"] = tencent_kline(target, days=40)
    
    # Step 3: 分钟级资金流（东财push2）
    try:
        data["fund_flow_minute"] = fund_flow_minute(target)
    except Exception:
        data["fund_flow_minute"] = []
    
    # Step 4: 日级资金流（东财push2his，可能被代理拦截）
    try:
        data["fund_flow_daily"] = fund_flow_daily(target, limit=60)
    except Exception:
        data["fund_flow_daily"] = []
    
    # Step 5: 新闻
    keyword = target
    if target_type == "etf":
        realtime = data.get("realtime", {}).get(target, {})
        keyword = realtime.get("name", target)
    try:
        data["news"] = stock_news(keyword, count=10)
    except Exception:
        data["news"] = []
    
    # Step 6: 概念板块资金流（市场环境参考）
    try:
        data["sector_flow"] = concept_sector_flow()
    except Exception:
        data["sector_flow"] = []
    
    return data
```

**数据合并与输出**：将 K线价格数据与资金流数据合并，生成统一 `daily` 列表供后续信号分析使用：

```python
def merge_daily_data(kline: list[dict], fund_flow: list[dict], realtime: dict) -> list[dict]:
    """合并K线+资金流+实时行情 → 统一日度数据"""
    # 建立日期→资金流映射
    flow_map = {f["date"]: f for f in fund_flow}
    
    daily = []
    for k in kline:
        d = dict(k)
        # 合并资金流
        if k["date"] in flow_map:
            f = flow_map[k["date"]]
            d["main_net"] = f["main_net"] / 1e4  # 元→万元
            d["super_net"] = f["super_net"] / 1e4
            d["large_net"] = f["large_net"] / 1e4
            d["mid_net"] = f["mid_net"] / 1e4
            d["small_net"] = f["small_net"] / 1e4
        
        # 换手率估算 (需要流通份额, 从总市值/价格反推)
        d["turnover_est"] = round(k.get("vol_yifen",0) / (realtime.get("mcap_yi",1)/k["close"]) * 100, 1)
        daily.append(d)
    
    return daily
```

---

## Layer 2: 安全信号提取 —— 回答"企稳了吗？"

安全信号是买入的前提。没有安全信号 = 不能买，无论涨得多好。

### 2.1 卖压衰竭检测 (F1)

```python
def detect_selling_exhaustion(daily: list[dict]) -> dict:
    """
    F1: 主力流出衰竭检测 —— 最核心的企稳信号。
    
    判断逻辑:
    1. 近5日主力净流出额逐日递减
    2. 最新一日净流出 < 前5日均流出额的50%
    3. 股价不再创新低（近3日最低价 ≥ 前5日最低价）
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}
    
    recent = daily[-5:]
    outflows = [d["main_net"] for d in recent if d["main_net"] < 0]
    
    if len(outflows) < 3:
        return {"triggered": False, "reason": "近期无持续流出，不需判断衰竭"}
    
    # 检查流出是否递减
    is_decreasing = all(
        abs(outflows[i]) > abs(outflows[i+1])
        for i in range(len(outflows) - 1)
    )
    
    # 最新流出 vs 均值
    avg_outflow = sum(abs(o) for o in outflows) / len(outflows)
    latest_outflow = abs(outflows[-1])
    
    # 价格是否企稳
    lows = [d.get("low", d.get("price", 0)) for d in recent if d.get("low") or d.get("price")]
    new_low = min(lows[-3:]) < min(lows[:2]) if len(lows) >= 5 else True
    
    ratio = latest_outflow / avg_outflow if avg_outflow > 0 else 1
    
    triggered = is_decreasing and ratio < 0.5 and not new_low
    
    return {
        "triggered": triggered,
        "signal_name": "F1: 主力流出衰竭",
        "decreasing": is_decreasing,
        "latest_vs_avg_ratio": round(ratio, 2),
        "new_low": new_low,
        "strength": "强" if triggered and ratio < 0.3 else ("中" if triggered else "弱"),
        "meaning": "卖方力量在减弱，卖压接近衰竭" if triggered else "卖压尚未衰竭，继续观察",
    }
```

### 2.2 机构试探回流检测 (F2)

```python
def detect_institution_return(daily: list[dict]) -> dict:
    """
    F2: 机构试探性回流 —— 底部形成的领先信号。
    
    判断逻辑:
    1. 前期(前5-10日)机构(超大单)持续流出
    2. 近2日机构转为净流入
    3. 散户仍在净流出（说明恐慌盘还在出，但机构在接）
    """
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}
    
    # 前期5日机构流向
    early = daily[-10:-3]
    recent = daily[-3:]
    
    early_inst = sum(d.get("super_net", d.get("super_large_net", 0)) for d in early)
    recent_inst = sum(d.get("super_net", d.get("super_large_net", 0)) for d in recent)
    recent_retail = sum(
        (d.get("mid_net", 0) or 0) + (d.get("small_net", 0) or 0)
        for d in recent
    )
    
    triggered = early_inst < 0 and recent_inst > 0 and recent_retail < 0
    
    return {
        "triggered": triggered,
        "signal_name": "F2: 机构试探回流",
        "early_institution_net_wan": round(early_inst / 1e4, 1),
        "recent_institution_net_wan": round(recent_inst / 1e4, 1),
        "recent_retail_net_wan": round(recent_retail / 1e4, 1),
        "strength": "强" if triggered and recent_inst > abs(early_inst) * 0.3 else ("中" if triggered else "弱"),
        "meaning": "机构开始接盘，散户还在恐慌 → 典型底部特征" if triggered else "机构尚未回流",
    }
```

### 2.3 散户恐慌出尽检测 (F3)

```python
def detect_retail_exhaustion(daily: list[dict]) -> dict:
    """
    F3: 散户恐慌出尽 —— 不坚定的筹码已经走完了。
    
    判断逻辑:
    1. 散户(中小单)连续5日净流出
    2. 近3日流出额逐日递减
    3. 股价跌幅在收窄
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}
    
    recent = daily[-5:]
    retail_flows = [
        (d.get("mid_net", 0) or 0) + (d.get("small_net", 0) or 0)
        for d in recent
    ]
    
    all_outflow = all(f < 0 for f in retail_flows)
    if not all_outflow:
        return {"triggered": False, "reason": "散户未持续流出"}
    
    # 流出递减
    recent_3 = retail_flows[-3:]
    is_decreasing = all(
        abs(recent_3[i]) > abs(recent_3[i+1])
        for i in range(len(recent_3) - 1)
    )
    
    # 跌幅收窄
    prices = [d.get("price", 0) for d in recent if d.get("price", 0) > 0]
    if len(prices) >= 5:
        early_decline = abs((prices[1] - prices[0]) / prices[0] * 100) if prices[0] > 0 else 0
        late_decline = abs((prices[-1] - prices[-2]) / prices[-2] * 100) if prices[-2] > 0 else 0
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
```

### 2.4 缩量止跌检测 (F8)

```python
def detect_volume_stabilization(daily: list[dict]) -> dict:
    """
    F8: 缩量止跌 —— 没人卖了，也没人急着买，底部盘整中。
    
    判断逻辑:
    1. 股价连续3日涨跌幅在 ±1% 以内
    2. 换手率降至近20日均值的60%以下
    3. 主力净流出 < 前5日均流出额的30%
    """
    if len(daily) < 20:
        return {"triggered": False, "reason": "数据不足（需20日）"}
    
    recent_3 = daily[-3:]
    prev_20 = daily[-20:]
    
    # 价格窄幅震荡
    changes = [abs(d.get("change_pct", 0)) for d in recent_3 if d.get("change_pct") is not None]
    narrow_range = all(c < 1.0 for c in changes) if changes else False
    
    # 换手率萎缩
    turnovers = [d.get("turnover_pct", 0) for d in prev_20 if d.get("turnover_pct") is not None]
    recent_turnover = sum(d.get("turnover_pct", 0) for d in recent_3) / 3 if recent_3 else 0
    avg_turnover_20 = sum(turnovers) / len(turnovers) if turnovers else 1
    volume_shrink = recent_turnover < avg_turnover_20 * 0.6 if avg_turnover_20 > 0 else False
    
    # 主力流出大幅减少
    recent_main = sum(d["main_net"] for d in recent_3)
    prev_5_main = sum(d["main_net"] for d in daily[-8:-3])
    avg_prev_main = abs(prev_5_main) / 5 if prev_5_main != 0 else 1
    outflow_shrink = abs(recent_main) / 3 < avg_prev_main * 0.3 if avg_prev_main > 0 else False
    
    triggered = narrow_range and volume_shrink and outflow_shrink
    
    return {
        "triggered": triggered,
        "signal_name": "F8: 缩量止跌",
        "narrow_range": narrow_range,
        "volume_shrink": volume_shrink,
        "outflow_shrink": outflow_shrink,
        "avg_turnover_20": round(avg_turnover_20, 2),
        "recent_turnover_3": round(recent_turnover, 2),
        "strength": "强" if triggered else "弱",
        "meaning": "卖压枯竭，底部盘整中 → 下行空间有限" if triggered else "尚未缩量止跌",
    }
```

---

## Layer 2.5: 辅助盘面数据维度 —— 多维交叉验证（V1.2 新增）

资金流是主信号，但需要其他盘面数据维度交叉验证，避免单一维度误判。以下 5 个维度来自 a-stock-data 的 10 层数据架构，**不独立做判断，只作为安全评分的修正因子**。

### 2.5.1 融资融券 —— 杠杆水位检测

融资余额的变化反映市场杠杆水平。融资快速上升 = 杠杆资金涌入 = 助涨也助跌。

```python
def fetch_margin_data(code: str, days: int = 30) -> dict:
    """
    拉取个股融资融券明细。
    数据源: 东财 datacenter RPTA_MARGIN_TRADING
    """
    filter_str = f"(SECURITY_CODE='{code}')"
    raw = eastmoney_datacenter(
        "RPTA_MARGIN_TRADING",
        filter_str=filter_str,
        page_size=days, sort_columns="TRADE_DATE", sort_types="-1",
    )
    if not raw:
        return {"available": False, "reason": "无融资融券数据"}
    
    records = []
    for row in raw[:days]:
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "rzye": (row.get("RZYE") or 0) / 1e8,      # 融资余额(亿)
            "rzmre": (row.get("RZMRE") or 0) / 1e8,     # 融资买入额(亿)
            "rzche": (row.get("RZCHE") or 0) / 1e8,     # 融资偿还额(亿)
            "rqye": (row.get("RQYE") or 0) / 1e8,       # 融券余额(亿)
        })
    
    # 趋势分析
    if len(records) >= 10:
        recent_5 = sum(r["rzye"] for r in records[:5]) / 5
        prev_5 = sum(r["rzye"] for r in records[5:10]) / 5
        margin_trend = "上升" if recent_5 > prev_5 * 1.05 else ("下降" if recent_5 < prev_5 * 0.95 else "平稳")
        # 融资买入 vs 偿还
        total_buy = sum(r["rzmre"] for r in records[:5])
        total_pay = sum(r["rzche"] for r in records[:5])
        net_margin = total_buy - total_pay
    else:
        margin_trend = "数据不足"
        net_margin = 0
    
    return {
        "available": True,
        "records": records,
        "latest_margin_balance_yi": records[0]["rzye"] if records else 0,
        "margin_trend": margin_trend,
        "net_margin_flow_5d_yi": round(net_margin, 2),
        # 安全解读
        "safety_impact": (
            "negative" if margin_trend == "下降" and net_margin < 0
            else "positive" if margin_trend == "上升" and net_margin > 0
            else "neutral"
        ),
    }


def margin_safety_adjustment(margin_data: dict) -> int:
    """
    融资融券对安全评分的修正 (-8 到 +5):
    - 融资余额快速下降 + 净偿还 > 0.5亿 → -8 (去杠杆中，危险)
    - 融资余额平稳/微降 → 0 (无影响)
    - 融资余额温和上升 + 净买入 > 0.3亿 → +5 (杠杆资金看涨)
    - 融资余额暴涨(>10%增幅) → -5 (杠杆过高，助跌风险)
    """
    if not margin_data.get("available"):
        return 0
    
    trend = margin_data.get("margin_trend", "")
    net_flow = margin_data.get("net_margin_flow_5d_yi", 0)
    
    if trend == "下降" and net_flow < -0.5:
        return -8  # 去杠杆
    elif trend == "上升" and net_flow > 0.3:
        # 检查是否暴涨
        records = margin_data.get("records", [])
        if len(records) >= 10:
            old_avg = sum(r["rzye"] for r in records[5:10]) / 5
            new_avg = sum(r["rzye"] for r in records[:5]) / 5
            if old_avg > 0 and (new_avg - old_avg) / old_avg > 0.10:
                return -5  # 杠杆过高
        return +5  # 温和加杠杆
    elif trend == "下降":
        return -3  # 轻微去杠杆
    
    return 0
```

### 2.5.2 北向资金 —— 外资smart money方向

北向资金（沪股通+深股通）是A股重要的边际定价资金。持续流出是危险信号。

```python
def fetch_north_bound_flow(days: int = 30) -> dict:
    """
    拉取北向资金近N日流向。
    数据源: 同花顺 hsgtApi (本地CSV缓存 + 实时拉取)
    
    注: 东财北向数据自2024-08后净买额字段异常，
    优先使用同花顺接口。如果无法获取，返回空。
    """
    import csv, os
    
    csv_path = os.path.expanduser("~/.claude/cache/north_bound_history.csv")
    
    records = []
    if os.path.exists(csv_path):
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append({
                    "date": row.get("date", ""),
                    "hgt_net_yi": float(row.get("hgt_net", 0)),
                    "sgt_net_yi": float(row.get("sgt_net", 0)),
                })
        records = records[-days:]
    
    if not records:
        return {"available": False, "reason": "北向缓存为空，需先运行 north_bound 数据采集"}
    
    total_net = sum(r["hgt_net_yi"] + r["sgt_net_yi"] for r in records)
    recent_5 = sum(r["hgt_net_yi"] + r["sgt_net_yi"] for r in records[-5:])
    
    continuous_in = 0
    continuous_out = 0
    for r in reversed(records):
        net = r["hgt_net_yi"] + r["sgt_net_yi"]
        if net > 1:
            if continuous_out == 0: continuous_in += 1
            else: break
        elif net < -1:
            if continuous_in == 0: continuous_out += 1
            else: break
        else:
            break
    
    return {
        "available": True,
        "total_net_30d_yi": round(total_net, 2),
        "recent_5d_net_yi": round(recent_5, 2),
        "consecutive_inflow_days": continuous_in,
        "consecutive_outflow_days": continuous_out,
        "direction": "inflow" if recent_5 > 5 else ("outflow" if recent_5 < -5 else "neutral"),
    }


def north_bound_safety_adjustment(nb_data: dict) -> int:
    """
    北向资金对安全评分的修正 (-8 到 +8):
    - 北向连续5日流出 → -8 (外资撤退)
    - 北向近5日净流出 > 10亿 → -5
    - 北向连续3日流入 → +5 (外资看涨)
    - 北向近5日净流入 > 10亿 → +8
    """
    if not nb_data.get("available"):
        return 0
    
    net_5d = nb_data.get("recent_5d_net_yi", 0)
    consec_out = nb_data.get("consecutive_outflow_days", 0)
    consec_in = nb_data.get("consecutive_inflow_days", 0)
    
    if consec_out >= 5:
        return -8
    elif net_5d < -10:
        return -5
    elif net_5d < -5:
        return -3
    elif consec_in >= 3 and net_5d > 10:
        return +8
    elif consec_in >= 3:
        return +5
    elif net_5d > 5:
        return +3
    
    return 0
```

### 2.5.3 大宗交易 —— 折价抛售检测

大宗交易如果频繁折价成交，可能是大股东/机构在减持。

```python
def fetch_block_trades(code: str, days: int = 30) -> dict:
    """
    拉取个股大宗交易记录。
    数据源: 东财 datacenter RPT_BLOCKTRADE
    """
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    filter_str = (
        f"(TRADE_DATE>='{start_date}')"
        f"(TRADE_DATE<='{end_date}')"
        f"(SECURITY_CODE='{code}')"
    )
    raw = eastmoney_datacenter(
        "RPT_BLOCKTRADE",
        filter_str=filter_str,
        page_size=50, sort_columns="TRADE_DATE", sort_types="-1",
    )
    
    if not raw:
        return {"available": True, "has_recent_trades": False, "trades": []}
    
    trades = []
    total_discount_amt = 0
    for row in raw:
        price = row.get("DEAL_PRICE") or 0
        amount = row.get("DEAL_AMOUNT") or 0
        # 折溢价（负值=折价）
        premium = row.get("PREMIUM_RATE") or 0
        trades.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "price": price,
            "amount_wan": round(amount / 1e4, 1),
            "premium_rate": round(float(premium), 2),
            "buyer": row.get("BUYER_NAME", ""),
            "seller": row.get("SELLER_NAME", ""),
        })
        if float(premium) < -5:
            total_discount_amt += amount
    
    return {
        "available": True,
        "has_recent_trades": len(trades) > 0,
        "trade_count": len(trades),
        "total_discount_amount_yi": round(total_discount_amt / 1e8, 2),
        "trades": trades[:10],
        "is_selling_signal": total_discount_amt > 1e8,  # 折价成交>1亿=减持信号
    }


def block_trade_safety_adjustment(bt_data: dict) -> int:
    """
    大宗交易对安全评分的修正 (-5 到 0):
    - 近30日折价>5%的大宗成交 > 1亿 → -5 (减持信号)
    - 近30日有折价大宗但 < 1亿 → -2
    - 无大宗或溢价成交 → 0
    """
    if not bt_data.get("available") or not bt_data.get("has_recent_trades"):
        return 0
    
    discount_amt = bt_data.get("total_discount_amount_yi", 0)
    if discount_amt > 1:
        return -5
    elif discount_amt > 0.3:
        return -2
    
    return 0
```

### 2.5.4 股东户数 —— 筹码集中度

股东户数下降 = 筹码在集中（有人在收集）。股东户数上升 = 筹码在分散（有人在派发）。

```python
def fetch_shareholder_count(code: str) -> dict:
    """
    拉取股东户数变化（季度数据）。
    数据源: 东财 datacenter RPT_F10_FINANCE_SHAREHOLDER
    """
    raw = eastmoney_datacenter(
        "RPT_F10_FINANCE_SHAREHOLDER",
        filter_str=f"(SECURITY_CODE='{code}')",
        page_size=5, sort_columns="END_DATE", sort_types="-1",
    )
    
    if not raw:
        return {"available": False, "reason": "无股东户数数据"}
    
    records = []
    for row in raw[:4]:
        holder_count = row.get("HOLDER_NUM") or 0
        records.append({
            "date": str(row.get("END_DATE", ""))[:10],
            "holder_count": holder_count,
            "avg_holding": (row.get("AVG_HOLDING") or 0),
        })
    
    # 计算变化趋势
    if len(records) >= 2:
        latest = records[0]["holder_count"]
        prev = records[1]["holder_count"]
        if prev > 0:
            change_pct = round((latest - prev) / prev * 100, 2)
            # 股东户数下降 = 筹码集中 = 利好
            concentration = "集中" if change_pct < -3 else ("分散" if change_pct > 3 else "稳定")
        else:
            change_pct = 0
            concentration = "未知"
    else:
        change_pct = 0
        concentration = "数据不足"
    
    return {
        "available": True,
        "records": records,
        "latest_holder_count": records[0]["holder_count"] if records else 0,
        "change_pct": change_pct,
        "concentration": concentration,
    }


def shareholder_safety_adjustment(sh_data: dict) -> int:
    """
    股东户数对安全评分的修正 (-5 到 +5):
    - 股东户数下降 > 5% → +5 (筹码快速集中)
    - 股东户数下降 3-5% → +3
    - 股东户数上升 > 5% → -5 (筹码快速分散)
    - 股东户数上升 3-5% → -3
    """
    if not sh_data.get("available"):
        return 0
    
    change = sh_data.get("change_pct", 0)
    if change < -5:
        return +5
    elif change < -3:
        return +3
    elif change > 5:
        return -5
    elif change > 3:
        return -3
    
    return 0
```

### 2.5.5 限售解禁 —— 潜在抛压

近期有大量解禁 = 潜在卖盘增加。

```python
def fetch_lockup_expiry(code: str, lookahead_days: int = 90) -> dict:
    """
    查询限售解禁计划。
    数据源: 东财 datacenter RPT_LIFT_STOCK
    """
    from datetime import datetime, timedelta
    today = datetime.now()
    end_date = (today + timedelta(days=lookahead_days)).strftime("%Y-%m-%d")
    start_date = today.strftime("%Y-%m-%d")
    
    filter_str = (
        f"(LIFT_DATE>='{start_date}')"
        f"(LIFT_DATE<='{end_date}')"
        f"(SECURITY_CODE='{code}')"
    )
    raw = eastmoney_datacenter(
        "RPT_LIFT_STOCK",
        filter_str=filter_str,
        page_size=20, sort_columns="LIFT_DATE", sort_types="1",
    )
    
    if not raw:
        return {"available": True, "has_upcoming": False, "expiries": []}
    
    expiries = []
    total_lift_shares = 0
    total_float_mcap = 0
    for row in raw:
        lift_shares = row.get("LIFT_SHARES") or 0
        float_mcap = row.get("FREE_SHARES") or 1
        expiries.append({
            "date": str(row.get("LIFT_DATE", ""))[:10],
            "shares_wan": round(lift_shares / 1e4, 1),
            "ratio_of_float": round(lift_shares / float_mcap * 100, 2) if float_mcap > 0 else 0,
            "reason": row.get("LIFT_REASON", ""),
        })
        total_lift_shares += lift_shares
        # 取最新流通股本
        if total_float_mcap == 0:
            total_float_mcap = float_mcap
    
    # 判断解禁压力
    total_ratio = round(total_lift_shares / total_float_mcap * 100, 2) if total_float_mcap > 0 else 0
    
    return {
        "available": True,
        "has_upcoming": len(expiries) > 0,
        "total_lift_ratio_pct": total_ratio,
        "expiries": expiries,
        "is_pressure": total_ratio > 5,  # 解禁>流通盘5%=显著压力
    }


def lockup_safety_adjustment(lu_data: dict) -> int:
    """
    限售解禁对安全评分的修正 (-8 到 0):
    - 未来90天解禁 > 流通盘10% → -8 (巨大抛压)
    - 未来90天解禁 > 流通盘5% → -5
    - 未来90天解禁 > 流通盘2% → -2
    - 无解禁 → 0
    """
    if not lu_data.get("available") or not lu_data.get("has_upcoming"):
        return 0
    
    ratio = lu_data.get("total_lift_ratio_pct", 0)
    if ratio > 10:
        return -8
    elif ratio > 5:
        return -5
    elif ratio > 2:
        return -2
    
    return 0
```

---

## Layer 3: 危险信号检测 —— 回答"有什么风险？"

危险信号优先级**高于**安全信号。只要有一个高危信号触发 → 不买/考虑离场。

### 3.1 主力加速流出 (F4)

```python
def detect_accelerating_outflow(daily: list[dict]) -> dict:
    """
    F4: 主力加速流出 —— 最危险的信号，不要抄底。
    
    判断逻辑:
    1. 主力连续3日净流出
    2. 每日流出额递增
    3. 最新流出额 > 前5日均值的2倍
    """
    if len(daily) < 8:
        return {"triggered": False, "reason": "数据不足"}
    
    recent_3 = daily[-3:]
    prev_5 = daily[-8:-3]
    
    outflows = [d["main_net"] for d in recent_3]
    all_outflow = all(f < 0 for f in outflows)
    
    if not all_outflow:
        return {"triggered": False, "reason": "近期非持续流出"}
    
    accelerating = abs(outflows[0]) < abs(outflows[1]) < abs(outflows[2])
    avg_prev = sum(abs(d["main_net"]) for d in prev_5) / 5 if prev_5 else 1
    surge = abs(outflows[-1]) > avg_prev * 2
    
    triggered = all_outflow and accelerating and surge
    
    return {
        "triggered": triggered,
        "signal_name": "F4: 🔴 主力加速流出",
        "danger_level": "高危",
        "accelerating": accelerating,
        "latest_vs_avg_ratio": round(abs(outflows[-1]) / avg_prev, 1) if avg_prev > 0 else 0,
        "meaning": "卖方力量在加速 → 绝对不要抄底！持币观望" if triggered else "主力流出尚未加速",
        "action": "🚫 不买，已持有则考虑减仓" if triggered else "继续观察",
    }
```

### 3.2 顶部派发 (F5)

```python
def detect_top_distribution(daily: list[dict]) -> dict:
    """
    F5: 顶部派发 —— 机构在涨势中把筹码倒给散户。
    
    判断逻辑:
    1. 近5日股价上涨 > 3%
    2. 机构(超大单)净流出
    3. 散户(中小单)净流入
    """
    if len(daily) < 5:
        return {"triggered": False, "reason": "数据不足"}
    
    recent = daily[-5:]
    prices = [d.get("price", 0) for d in recent if d.get("price", 0) > 0]
    
    if len(prices) < 2:
        return {"triggered": False}
    
    price_up = (prices[-1] - prices[0]) / prices[0] * 100 > 3 if prices[0] > 0 else False
    inst_out = sum(d.get("super_net", d.get("super_large_net", 0)) for d in recent) < 0
    retail_in = sum(
        (d.get("mid_net", 0) or 0) + (d.get("small_net", 0) or 0)
        for d in recent
    ) > 0
    
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
```

### 3.3 利好出尽 (F7)

```python
def detect_good_news_exhausted(daily: list[dict], news_data: dict = None) -> dict:
    """
    F7: 利好出尽 —— A股最可靠的规律之一。
    
    判断逻辑:
    1. 存在 A/B 级利好
    2. 前期2周涨幅 > 15%
    → 历史回调概率 84%
    """
    if not news_data or not news_data.get("highlights"):
        return {"triggered": False, "reason": "无消息数据"}
    
    top_news = news_data["highlights"][0] if news_data["highlights"] else None
    if not top_news or top_news.get("impact") not in ("S", "A", "B"):
        return {"triggered": False, "reason": "无重要利好消息"}
    
    # 计算前2周涨幅
    if len(daily) < 10:
        return {"triggered": False, "reason": "数据不足"}
    
    prices = [d.get("price", 0) for d in daily[-10:] if d.get("price", 0) > 0]
    if len(prices) < 2:
        return {"triggered": False}
    
    pre_change = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] > 0 else 0
    
    triggered = pre_change > 15 and top_news["impact"] in ("S", "A")
    
    return {
        "triggered": triggered,
        "signal_name": "F7: 🔴 利好出尽",
        "danger_level": "非常高 (历史胜率84%)",
        "pre_change_2w": round(pre_change, 1),
        "news_impact": top_news.get("impact", ""),
        "news_title": top_news.get("title", "")[:60],
        "meaning": f"前期涨{pre_change:.0f}%+利好 → 84%概率回调" if triggered else "前期涨幅可接受",
        "action": "🚫 不要追！等回调后再评估" if triggered else "",
    }
```

---

## Layer 4: 安全区间综合评分 —— 回答"能不能买？"

```python
def calc_safety_score(
    safety_signals: dict,
    danger_signals: dict,
    daily: list[dict],
    sentiment_data: dict = None,
    auxiliary_data: dict = None,  # V1.2: 辅助盘面数据
) -> dict:
    """
    安全区间综合评分 (0-100)。
    
    主信号 (资金流):
    加分: F1流出衰竭+15 / F2机构回流+12 / F3恐慌出尽+10 / F8缩量止跌+8
    减分: F4加速流出-20 / F5顶部派发-18 / F7利好出尽-15
    
    企稳确认: +10
    情绪面: ±5
    
    V1.2 辅助盘面数据修正:
    融资融券(-8~+5) / 北向资金(-8~+8) / 大宗交易(-5~0) / 股东户数(-5~+5) / 限售解禁(-8~0)
    """
    score = 50
    adjustment_details = []
    
    # ━━ 安全信号加分 ━━
    if safety_signals.get("f1_exhaustion", {}).get("triggered"):
        score += 15; adjustment_details.append(("F1 流出衰竭", +15))
    if safety_signals.get("f2_institution_return", {}).get("triggered"):
        score += 12; adjustment_details.append(("F2 机构回流", +12))
    if safety_signals.get("f3_retail_exhaustion", {}).get("triggered"):
        score += 10; adjustment_details.append(("F3 恐慌出尽", +10))
    if safety_signals.get("f8_volume_stabilization", {}).get("triggered"):
        score += 8; adjustment_details.append(("F8 缩量止跌", +8))
    
    # ━━ 危险信号减分 ━━
    if danger_signals.get("f4_accelerating_outflow", {}).get("triggered"):
        score -= 20; adjustment_details.append(("F4 加速流出", -20))
    if danger_signals.get("f5_top_distribution", {}).get("triggered"):
        score -= 18; adjustment_details.append(("F5 顶部派发", -18))
    if danger_signals.get("f7_news_exhausted", {}).get("triggered"):
        score -= 15; adjustment_details.append(("F7 利好出尽", -15))
    
    # ━━ 企稳确认 ━━
    stabilization = check_stabilization(daily)
    if stabilization["is_stabilized"]:
        score += 10; adjustment_details.append(("企稳确认", +10))
    
    # ━━ 情绪面修正 ━━
    if sentiment_data:
        sent = sentiment_data.get("composite", 50)
        if sent <= 20: score += 5; adjustment_details.append((f"情绪悲观({sent})", +5))
        elif sent >= 80: score -= 5; adjustment_details.append((f"情绪亢奋({sent})", -5))
    
    # ━━ V1.2: 辅助盘面数据交叉验证 ━━
    if auxiliary_data:
        for key, adj_fn, label in [
            ("margin", margin_safety_adjustment, "融资融券"),
            ("north_bound", north_bound_safety_adjustment, "北向资金"),
            ("block_trades", block_trade_safety_adjustment, "大宗交易"),
            ("shareholders", shareholder_safety_adjustment, "股东户数"),
            ("lockup", lockup_safety_adjustment, "限售解禁"),
        ]:
            data = auxiliary_data.get(key, {})
            adj = adj_fn(data)
            if adj != 0:
                score += adj
                detail = data.get("margin_trend", data.get("direction", data.get("concentration", "")))
                adjustment_details.append((f"{label}({detail})", adj))
    
    score = max(0, min(100, score))
    
    # ━━ 安全等级 ━━
    if score >= 75:
        level = "🟢 安全区间"
        can_enter = True
        description = "下行风险可控，可考虑入场（配合买入参考条件）"
    elif score >= 60:
        level = "🟡 接近安全"
        can_enter = False
        description = "部分条件满足，再等1-2日确认"
    elif score >= 40:
        level = "🟠 风险区间"
        can_enter = False
        description = "安全信号不足或有危险信号，不建议入场"
    else:
        level = "🔴 危险区间"
        can_enter = False
        description = "存在高危信号，远离，持币观望"
    
    # ━━ 汇总正负信号 ━━
    positive = []
    negative = []
    for key, sig in safety_signals.items():
        if sig.get("triggered"):
            positive.append(sig.get("signal_name", key))
    for key, sig in danger_signals.items():
        if sig.get("triggered"):
            negative.append(sig.get("signal_name", key))
    
    return {
        "safety_score": score,
        "safety_level": level,
        "can_enter": can_enter,
        "description": description,
        "positive_signals": positive,
        "negative_signals": negative,
        "adjustment_details": adjustment_details,
        "stabilization": stabilization,
        "principle": "可以少挣，必须少亏 — 只有 ≥75 分才建议考虑入场",
    }


def check_stabilization(daily: list[dict]) -> dict:
    """
    企稳确认检查清单（5项，必须全部通过才算企稳）:
    ✅ 1. 近3日不再创新低
    ✅ 2. 近3日振幅 < 5%
    ✅ 3. 近3日主力净流出 < 前10日均流出额的50%
    ✅ 4. 近3日最低价逐步抬高（或持平）
    ✅ 5. 近3日收盘价站稳5日均线上方
    """
    if len(daily) < 10:
        return {"is_stabilized": False, "reason": "数据不足"}
    
    recent = daily[-3:]
    prev_10 = daily[-10:-3]
    
    checks = {}
    
    # 检查1: 不再创新低
    recent_lows = [d.get("low", d.get("price", 0)) for d in recent]
    prev_lows = [d.get("low", d.get("price", 0)) for d in prev_10]
    checks["no_new_low"] = min(recent_lows) >= min(prev_lows) if prev_lows else False
    
    # 检查2: 振幅收窄
    amplitudes = []
    for d in recent:
        high = d.get("high", d.get("price", 0))
        low = d.get("low", d.get("price", 0))
        if high > 0 and low > 0:
            amplitudes.append((high - low) / low * 100)
    checks["narrow_range"] = all(a < 5 for a in amplitudes) if amplitudes else False
    
    # 检查3: 流出大幅减少
    recent_outflow = abs(sum(d["main_net"] for d in recent if d["main_net"] < 0))
    prev_outflow_avg = abs(sum(d["main_net"] for d in prev_10 if d["main_net"] < 0)) / max(len([x for x in prev_10 if x["main_net"] < 0]), 1)
    checks["outflow_reduced"] = recent_outflow < prev_outflow_avg * 0.5
    
    # 检查4: 最低价抬高
    checks["lows_rising"] = recent_lows[-1] >= recent_lows[0] if len(recent_lows) >= 2 else False
    
    # 检查5: 站上5日均线
    prices = [d.get("price", 0) for d in daily[-8:] if d.get("price", 0) > 0]
    if len(prices) >= 5:
        ma5 = sum(prices[-6:-1]) / 5
        checks["above_ma5"] = prices[-1] > ma5
    else:
        checks["above_ma5"] = False
    
    passed = sum(1 for v in checks.values() if v)
    is_stabilized = passed >= 4  # 5项中至少4项通过
    
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

### 6.1 主流程

```python
def assess_target_safety(
    target: str,
    target_type: str = "auto",
) -> dict:
    """
    标的安全区间评估主流程。
    
    返回: 完整安全评估报告 dict
    """
    # ━━ 0. 识别标的类型 ━━
    if target_type == "auto":
        target_type = _auto_detect_type(target)
    
    print(f"[识别] {target_type}: {target}")
    
    # ━━ 1. 拉取30天数据 ━━
    print("[1/5] 拉取30天日度数据...")
    if target_type == "stock":
        data = fetch_stock_30d_daily(target)
    elif target_type == "sector":
        bk_code = target if target.startswith("BK") else _find_bk_code(target)
        data = fetch_sector_30d_daily(bk_code)
    elif target_type == "etf":
        data = fetch_etf_30d_daily(target)
    else:
        return {"error": f"不支持的类型: {target_type}"}
    
    if "error" in data:
        return data
    
    daily = data["daily"]
    print(f"  获取 {len(daily)} 个交易日")
    
    # ━━ 2. 安全信号检测 ━━
    print("[2/5] 安全信号检测...")
    safety_signals = {
        "f1_exhaustion": detect_selling_exhaustion(daily),
        "f2_institution_return": detect_institution_return(daily),
        "f3_retail_exhaustion": detect_retail_exhaustion(daily),
        "f8_volume_stabilization": detect_volume_stabilization(daily),
    }
    
    # ━━ 3. 危险信号检测 ━━
    print("[3/5] 危险信号检测...")
    news_data = fetch_30d_news(target, target_type)
    danger_signals = {
        "f4_accelerating_outflow": detect_accelerating_outflow(daily),
        "f5_top_distribution": detect_top_distribution(daily),
        "f7_news_exhausted": detect_good_news_exhausted(daily, news_data),
    }
    
    # ━━ 3.5. 辅助盘面数据（V1.2 多维交叉验证） ━━
    print("[3.5/6] 拉取辅助盘面数据...")
    auxiliary_data = {}
    
    # 融资融券
    try:
        auxiliary_data["margin"] = fetch_margin_data(target)
    except Exception:
        auxiliary_data["margin"] = {"available": False}
    
    # 北向资金
    try:
        auxiliary_data["north_bound"] = fetch_north_bound_flow(30)
    except Exception:
        auxiliary_data["north_bound"] = {"available": False}
    
    # 大宗交易 / 股东户数 / 限售解禁（仅个股）
    if target_type == "stock":
        for key, fn in [("block_trades", fetch_block_trades),
                         ("shareholders", fetch_shareholder_count),
                         ("lockup", fetch_lockup_expiry)]:
            try:
                auxiliary_data[key] = fn(target)
            except Exception:
                auxiliary_data[key] = {"available": False}
    
    print(f"  辅助数据: 融资融券={'✓' if auxiliary_data.get('margin',{}).get('available') else '✗'} | "
          f"北向={'✓' if auxiliary_data.get('north_bound',{}).get('available') else '✗'} | "
          f"大宗={'✓' if auxiliary_data.get('block_trades',{}).get('available') else '✗'} | "
          f"股东={'✓' if auxiliary_data.get('shareholders',{}).get('available') else '✗'} | "
          f"解禁={'✓' if auxiliary_data.get('lockup',{}).get('available') else '✗'}")
    
    # ━━ 4. 安全评分 ━━
    print("[4/6] 计算安全评分（含全维度盘面数据交叉验证）...")
    safety_score = calc_safety_score(safety_signals, danger_signals, daily, auxiliary_data=auxiliary_data)
    
    # ━━ 5. 买卖时机 ━━
    print("[5/6] 生成时机参考...")
    timing = generate_timing_signals(safety_score, safety_signals, danger_signals, daily)
    
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": target,
        "target_type": target_type,
        "target_name": data.get("name", target),
        "summary": data["summary"],
        "daily": daily,
        "safety_signals": safety_signals,
        "danger_signals": danger_signals,
        "safety_score": safety_score,
        "timing": timing,
        "news_highlights": news_data.get("highlights", [])[:8] if news_data else [],
        "principle": "可以少挣，必须少亏。所有判断基于数据，每个信号绑定历史胜率。",
    }
    
    return report
```

### 6.2 Console 打印

```python
def print_safety_report(report: dict):
    """打印安全评估报告"""
    print()
    print("=" * 80)
    print("  🛡️  买入安全区间研判报告")
    print(f"  标的: {report.get('target_name', report['target'])}")
    print(f"  类型: {report['target_type']} | {report['generated_at']}")
    print(f"  原则: 可以少挣，必须少亏。所有判断用数据说话。")
    print("=" * 80)
    
    # ━━ Part 1: 核心结论 ━━
    score = report["safety_score"]
    print()
    print("━" * 60)
    print("  🎯 Part 1: 核心结论")
    print("━" * 60)
    print(f"  安全评分: {score['safety_score']}/100 → {score['safety_level']}")
    print(f"  企稳状态: {'✅ 已企稳' if score['stabilization']['is_stabilized'] else '❌ 未企稳'} "
          f"({score['stabilization']['passed_count']}/5项)")
    print(f"  能否入场: {'🟢 可考虑入场' if score['can_enter'] else '🔴 不建议入场'}")
    print(f"  判断依据: {score['description']}")
    
    # ━━ Part 2: 日度数据明细（成交量+换手率+量比+走势） ━━
    print()
    print("━" * 60)
    print("  📋 Part 2: 近20日日度数据明细（成交量/换手率/量比/走势）")
    print("━" * 60)
    daily = report.get("daily", [])
    if daily:
        # 计算20日均量用于量比
        vols_20 = [d.get("vol_wan", d.get("vol_wanfen", 0)) for d in daily[-25:-5] if d.get("vol_wan") or d.get("vol_wanfen")]
        avg_vol_20 = sum(vols_20) / len(vols_20) if vols_20 else 1
        # 流通份额(从换手率反推，或从实时行情获取)
        float_shares = report.get("float_shares_yi", 5.0) * 1e4  # 亿份→万份
        
        print(f"  {'日期':<12s} {'收盘':>7s} {'涨跌幅':>8s} {'振幅':>7s} {'成交量':>10s} {'成交额':>9s} {'换手率':>8s} {'量比':>7s} {'主力净流':>10s} {'走势':>8s}")
        print(f"  {'─'*95}")
        for d in daily[-20:]:
            date = d.get("date", "")
            close = d.get("price", d.get("close", 0))
            chg = d.get("change_pct", 0)
            amp = d.get("amplitude", d.get("amp", 0))
            vol = d.get("vol_wan", d.get("vol_wanfen", 0))
            amt = d.get("amount_yi", d.get("amt_yi", 0))
            main_net = d.get("main_net", 0)  # 主力净流入(万元)
            
            est_turnover = round(vol / float_shares * 100, 1) if float_shares > 0 else 0
            vol_ratio = round(vol / avg_vol_20, 1) if avg_vol_20 > 0 else 0
            
            if chg > 5: trend = "🔥大涨"
            elif chg > 2: trend = "📈上涨"
            elif chg > -2: trend = "➖震荡"
            elif chg > -5: trend = "📉下跌"
            else: trend = "💧暴跌"
            
            vr_mark = "🔴" if vol_ratio > 2.5 else ("🟠" if vol_ratio > 1.5 else ("🔵" if vol_ratio < 0.5 else ""))
            
            # 主力资金方向标记
            if main_net > 500: flow_mark = f"🔴+{main_net:.0f}万"
            elif main_net > 0: flow_mark = f"🟢+{main_net:.0f}万"
            elif main_net > -500: flow_mark = f"🟢{main_net:.0f}万"
            else: flow_mark = f"🔴{main_net:.0f}万"
            
            print(f"  {date:<12s} {close:>7.3f} {chg:>+7.2f}% {amp:>6.2f}% "
                  f"{vol:>8.0f}万 {amt:>7.2f}亿 {est_turnover:>7.1f}% {vr_mark}{vol_ratio:>5.1f}倍 "
                  f"{flow_mark:>10s} {trend}")
        
        # 汇总行
        today = daily[-1] if daily else {}
        today_vol = today.get("vol_wan", today.get("vol_wanfen", 0))
        avg_vol_recent = sum(d.get("vol_wan", d.get("vol_wanfen", 0)) for d in daily[-20:]) / max(len(daily[-20:]), 1)
        print(f"  {'─'*85}")
        print(f"  今日量是20日均量的 {today_vol/avg_vol_recent:.1f}倍 | "
              f"流通份额≈{float_shares/1e4:.1f}亿份")
    
    # ━━ Part 2.5: 资金流向详细分析 ━━
    print()
    print("━" * 60)
    print("  💰 Part 2.5: 资金流向详细分析")
    print("━" * 60)
    daily = report.get("daily", [])
    if daily:
        recent_5 = daily[-5:]
        inst_5d = sum(d.get("super_net", d.get("super_large_net", 0)) for d in recent_5)
        hm_5d = sum(d.get("large_net", 0) for d in recent_5)
        mid_5d = sum(d.get("mid_net", 0) or 0 for d in recent_5)
        small_5d = sum(d.get("small_net", 0) for d in recent_5)
        main_5d = sum(d.get("main_net", 0) for d in recent_5)
        
        print(f"\n  近5日三方资金分类汇总:")
        print(f"  🔴 超大单(机构): {inst_5d:+.0f}万 | {'流入' if inst_5d>0 else '流出'}中")
        print(f"  🟡 大单(游资):   {hm_5d:+.0f}万")
        print(f"  🟢 中单:         {mid_5d:+.0f}万")
        print(f"  🟢 小单(散户):   {small_5d:+.0f}万")
        print(f"  ─────────────────────────────")
        print(f"  📊 主力合计:     {main_5d:+.0f}万 = {main_5d/1e4:+.2f}亿")
        
        # 机构vs散户
        if inst_5d < -500 and small_5d > 100:
            print(f"  ⚠️ 机构卖+散户买 → 🔴 筹码从机构→散户(派发)")
        elif inst_5d > 500 and small_5d < -100:
            print(f"  ✅ 机构买+散户卖 → 🟢 筹码从散户→机构(吸筹)")
        
        # 连续流入/流出
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
        print(f"\n  📈 连续流入: {consec_in}日 | 连续流出: {consec_out}日")
        
        # 近5日每日资金明细
        print(f"\n  近5日每日资金明细:")
        print(f"  {'日期':<12s} {'主力净流':>10s} {'超大单(机构)':>12s} {'大单(游资)':>12s} {'中单':>10s} {'小单(散户)':>12s}")
        print(f"  {'─'*72}")
        for d in recent_5:
            print(f"  {d.get('date',''):<12s} {d.get('main_net',0):>8.0f}万 "
                  f"{d.get('super_net', d.get('super_large_net',0)):>10.0f}万 "
                  f"{d.get('large_net',0):>10.0f}万 "
                  f"{d.get('mid_net',0) or 0:>8.0f}万 "
                  f"{d.get('small_net',0):>10.0f}万")
    
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

- 安全评分基于可验证的资金流规则和历史统计，不代表未来必然重复
- 买入/卖出参考条件是信号框架，不是买卖指令
- 核心原则"可以少挣，必须少亏"意味着保守入场、果断离场
- 亏损的数学是不对称的（亏50%需涨100%回本），风控永远第一
- 所有分析基于公开数据，不构成投资建议
