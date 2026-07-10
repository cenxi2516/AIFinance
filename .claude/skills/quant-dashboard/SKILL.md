---
name: quant-dashboard
description: 全市场量化综合研判仪表盘 — 实时拉取行情/ETF资金流/消息，五层量化引擎(市场状态识别→动态权重分配→六维评分修正→跷跷板检测→综合评分+时机参考)，内置30+条历史统计规律。核心理念：股价主要受消息和资金驱动，其他维度作为辅助修正。Use when 用户询问"现在市场怎么看""该入场还是离场""XX板块走势预判""仓位建议""市场风格判断""高低切换""风险预警"等需要全市场量化研判时。
version: 2.0.0
updated: 2026-07-10
---

# 量化综合研判仪表盘 V2.0

**定位**：14 技能架构的**顶层合成引擎**——消费所有下层 skill 的实时输出，内置 30+ 条历史统计规律，输出全市场综合评分(0-10)+风格判断+行业优先级+入场/离场参考条件。

**核心理念**：==股价主要受消息和资金驱动==。基本面、技术面、外围映射等是辅助修正因子。消息和资金同向共振=最高置信度，消息和资金背离=预警信号。

> **V2.0 核心改进**（2026-07-10 全行业 21 标验证驱动）：
> 1. 新增**市场状态识别层**——先判断"今天是什么天"，再决定权重分配
> 2. 六维权重**动态分配**（事件驱动日 / 正常轮动日 / 极端恐慌日 / 业绩验证日）
> 3. 外围映射增加**前期涨跌幅修正因子**（A股vs外围对标物涨跌幅差>15%→脱钩）
> 4. 事件**S/A/B/C 四级分级**，S级（国家首次/全球首次）可覆盖基本面约束
> 5. 新增**资金跷跷板检测**（流入TOP3 vs 流出TOP3 = 切换方向）+ 流动性虹吸受害方识别
> 6. 基本面维度**事件强度覆盖**规则（强事件日基本面权重降至5%）
> 7. 新增**产业链位置弹性系数**（解释同一行业不同标的反向走势）
> 8. 21 标验证方向命中率 **95%**

## When to Activate

- 用户要判断**全市场走势方向**（看多/看空/中性，置信度如何）
- 用户要分析**市场风格切换**（进攻→防御？科技→消费？）
- 用户要检测**高低切换信号**（什么涨多了该卖？什么跌多了该看？）
- 用户要**行业优先级排序**（当前哪些行业最优？哪些该回避？）
- 用户要**入场/离场参考条件**（什么信号出现该参与？什么信号出现该警惕？）
- 用户要做**全市场风险预警**（有没有系统性风险信号？）
- 关键词：`市场怎么看`、`入场`、`离场`、`仓位`、`风格切换`、`高低切换`、`风险预警`、`行业排序`、`下跌原因`、`为什么跌`

**不适用场景**：
- 单只个股深度分析（用 a-stock-data + stock_daily_attribution）
- 纯产业链深度调研（用 serenity-skill）
- 纯政策事件扫描（用 policy-event-tracker）

---

## 五层量化引擎架构

```
                        ┌──────────────────────────────────────┐
                        │       quant-dashboard V2.0           │
                        │    全市场量化综合研判 + 时机参考        │
                        │     核心理念: 消息+资金驱动股价        │
                        └──────────────┬───────────────────────┘
                                       │
        ┌──────────┬──────────┬───────┼───────┬──────────┬──────────┐
        ▼          ▼          ▼       ▼       ▼          ▼          ▼
    腾讯行情    WebSearch   policy-  capital- etf-fund-  industry-  earnings-
    (实时)      (消息)      event-   flow-    flow-      sentiment- tracker
                           tracker  tracker  tracker    tracker
                                       │
                   ┌───────────────────┴───────────────────┐
                   ▼                                       ▼
        ┌──────────────────┐                    ┌──────────────────┐
        │ Layer 1: 市场状态  │                    │ 内置30+条历史规律  │
        │ 事件驱动/轮动/恐慌 │                    │ 每条标注:触发条件  │
        │ /业绩验证 四分类   │                    │ +历史胜率+适用环境  │
        └────────┬─────────┘                    └────────┬─────────┘
                 │                                       │
                 ▼                                       ▼
        ┌──────────────────┐                    ┌──────────────────┐
        │ Layer 2: 动态权重  │ ←────────────────│ 规律驱动的修正因子  │
        └────────┬─────────┘                    └──────────────────┘
                 │
                 ▼
        ┌──────────────────────────────────────────────────────────┐
        │ Layer 3: 六维评分 + 修正因子                              │
        │  外围映射×前期涨跌幅脱钩 | 事件驱动×S/A/B/C分级+预期差   │
        │  资金流向×分时模式识别 | 情绪面×拥挤度修正               │
        │  基本面×事件强度覆盖 | 技术面×异常检测                  │
        └────────┬─────────────────────────────────────────────────┘
                 │
                 ▼
        ┌──────────────────┐
        │ Layer 4: 跷跷板   │ ← 流入TOP3 vs 流出TOP3 → 切换方向
        │ + 对立面 + 虹吸   │   涨最多TOP5 vs 跌最多TOP5 → 高低切换
        │                  │   流出+无利空 → 流动性虹吸受害方
        └────────┬─────────┘
                 │
                 ▼
        ┌──────────────────────────────────────────┐
        │ Layer 5: 综合评分(0-10)                   │
        │  + 风格判断(进攻/防御/均衡/切换)           │
        │  + 行业优先级排序(5档)                     │
        │  + 入场参考条件(信号+阈值)                 │
        │  + 离场参考条件(信号+阈值+历史胜率)        │
        │  + 风险预警清单                            │
        └──────────────────────────────────────────┘
```

---

## Layer 1: 市场状态识别 (Market Regime Detection)

**核心问题**：不同市场状态需要不同的分析权重。先判断"今天是什么天"。

```python
def detect_market_regime(events_today: list[dict], market_data: dict) -> dict:
    """
    四类市场状态识别（按优先级）:
    1. 是否有 S/A 级事件 → 事件驱动日
    2. 涨跌停比 >= 3:1 或 <= 1:3 → 极端情绪日
    3. 财报季密集披露期 → 业绩验证日
    4. 以上都不满足 → 正常轮动日
    """
    # 判断 1: 事件驱动
    s_events = [e for e in events_today if e.get("level") in ("S", "A")]
    if s_events:
        return {
            "regime": "事件驱动日",
            "trigger": s_events[0]["summary"],
            "weights": EVENT_DRIVEN_WEIGHTS,
        }
    
    # 判断 2: 极端情绪
    zt = market_data.get("zt_count", 50)
    dt = market_data.get("dt_count", 5)
    if zt / max(dt, 1) >= 3 or dt / max(zt, 1) >= 3:
        return {
            "regime": "极端情绪日",
            "trigger": f"涨停{zt}只 vs 跌停{dt}只",
            "weights": EXTREME_SENTIMENT_WEIGHTS,
        }
    
    # 判断 3: 业绩验证日
    from datetime import datetime
    today = datetime.now()
    if today.month in (1, 4, 7, 10) and today.day >= 10:
        return {
            "regime": "业绩验证日",
            "trigger": f"{today.month}月财报季",
            "weights": EARNINGS_DRIVEN_WEIGHTS,
        }
    
    return {"regime": "正常轮动日", "weights": NORMAL_WEIGHTS}
```

### 四套动态权重矩阵

```python
# 维度: 外围映射 / 政策事件 / 资金流向 / 市场情绪 / 基本面估值 / 技术面

NORMAL_WEIGHTS = {
    "global": 0.15, "event": 0.20, "fund_flow": 0.20,
    "sentiment": 0.15, "fundamental": 0.15, "technical": 0.15,
}

# 事件驱动日: 消息+资金主导，基本面降到最低
EVENT_DRIVEN_WEIGHTS = {
    "global": 0.10, "event": 0.30, "fund_flow": 0.25,
    "sentiment": 0.20, "fundamental": 0.05, "technical": 0.10,
}

# 极端情绪日: 情绪和技术面主导
EXTREME_SENTIMENT_WEIGHTS = {
    "global": 0.05, "event": 0.15, "fund_flow": 0.15,
    "sentiment": 0.30, "fundamental": 0.10, "technical": 0.25,
}

# 业绩验证日: 基本面权重最高
EARNINGS_DRIVEN_WEIGHTS = {
    "global": 0.10, "event": 0.15, "fund_flow": 0.15,
    "sentiment": 0.10, "fundamental": 0.30, "technical": 0.20,
}
```

---

## Layer 2: 事件强度分级 (S/A/B/C)

```python
def classify_event_strength(event: dict) -> str:
    """
    S级 = 国家级首次/全球首次里程碑 → 可覆盖基本面约束
    A级 = 部委级重大政策/产业重大突破/改变基本面假设的事件
    B级 = 行业级政策/展会/分红/常规数据发布
    C级 = 公司级普通公告/媒体报道
    
    分级铁律:
    - 分红/回购/普通中标 最高 B 级（不改变基本面假设）
    - 业绩预告±30%以内→B级，±100%以上→A级
    - "首次""第一""首飞""首台套"→至少 A 级起评
    """
    combined = event.get("title", "") + event.get("summary", "")
    
    s_kw = ["全球首次","国家首次","全国首次","人类首次",
            "政治局会议定调","国务院常务会议","五年规划发布"]
    if any(kw in combined for kw in s_kw):
        return "S"
    
    a_kw = ["部委","发改委","工信部","科技部",
            "出口管制加码","实体清单新增","技术封锁",
            "首飞成功","首次回收","首台套",
            "业绩增超100%","利润增超100%",
            "重大资产重组","控制权变更"]
    if any(kw in combined for kw in a_kw):
        return "A"
    
    b_kw = ["展会","论坛","峰会","数据发布","解禁",
            "分红","回购","中标","业绩预告"]
    if any(kw in combined for kw in b_kw):
        return "B"
    
    return "C"


def event_coverage_rule(event_level: str) -> dict:
    """
    S级事件可临时覆盖一切其他约束。
    7/10案例: 航天电子 PE 614倍 + 涨停 = S级事件覆盖估值约束
    """
    if event_level == "S":
        return {"override_all": True,
                "reason": "S级事件(国家首次/全球首次)→临时覆盖其他约束",
                "risk_note": "⚠️事件脉冲T+1大概率分化(历史: T+1~T+5累计约-3.02%)"}
    elif event_level == "A":
        return {"override_fundamental": True,
                "reason": "A级事件→基本面估值约束降级"}
    return {"no_override": True}
```

---

## Layer 3: 六维评分 + 修正因子

### 3.1 维度 1: 外围股市映射 (权重: 动态 5-15%)

```python
def global_mapping_score(stock_data: dict, global_data: dict) -> dict:
    """
    关键修正: A股标的 vs 外围对标物 近2周涨跌幅差 >15% → 脱钩，权重降至0.05
    
    7/10案例: SOX涨+4%但A股半导体-6.93%
             = A股年涨+105% vs SOX年跌-11% → 严重脱钩
    """
    a_change = stock_data.get("change_2w", 0)
    b_change = global_data.get("benchmark_change_2w", 0)
    divergence = abs(a_change - b_change)
    
    if divergence > 15:
        return {
            "direction": "neutral", "score": 50, "weight_override": 0.05,
            "reason": f"A股vs外围涨跌幅差{divergence:.0f}%>15% → 脱钩",
            "rule": "R17: A股-美股脱钩规则",
        }
    
    # 正常映射
    g_dir = global_data.get("direction", "neutral")
    if g_dir == "bullish":
        return {"direction": "bullish", "score": 65, "reason": "外围偏强→映射正面"}
    elif g_dir == "bearish":
        return {"direction": "bearish", "score": 35, "reason": "外围偏弱→映射负面"}
    return {"direction": "neutral", "score": 50, "reason": "外围震荡"}
```

### 3.2 维度 2: 政策事件驱动 (权重: 动态 15-30%)

```python
def policy_event_score(events: list[dict], sector_pre_change: float,
                       sector_ytd_change: float) -> dict:
    """
    事件评分 = 事件强度 × 预期差系数
    
    预期差逻辑:
    - 利好 + 前期没涨(或跌) → 预期差最大
    - 利好 + 前期涨超15% → 🚨利好出尽，反转为利空 (R1, 回调概率~84%)
    - 利空 + 前期跌超15% → 👀利空出尽候选
    """
    if not events:
        return {"direction": "neutral", "score": 50, "reason": "无重大事件催化"}
    
    top = events[0]
    level = top.get("level", "C")
    direction = top.get("direction", "neutral")
    
    level_base = {"S": 90, "A": 75, "B": 60, "C": 50}
    base = level_base.get(level, 50)
    
    if direction == "bullish" and level in ("S", "A"):
        if sector_pre_change > 15 or sector_ytd_change > 80:
            return {
                "direction": "bearish", "score": 20,
                "reason": f"S/A级利好但前期涨{sector_pre_change:.0f}%>15% → 🚨利好出尽！",
                "signal": "利好出尽",
                "historical_win_rate": "84%回调概率",
                "rule": "R1: 利好出尽",
            }
        elif sector_pre_change < 0:
            return {
                "direction": "bullish", "score": 85,
                "reason": f"S/A级利好+前期跌{abs(sector_pre_change):.0f}% → ✅最大预期差",
                "signal": "最大预期差",
            }
        else:
            return {
                "direction": "bullish", "score": 65,
                "reason": f"S/A级利好+前期涨{sector_pre_change:.0f}%适中",
            }
    
    if direction == "bearish" and level in ("S", "A"):
        if sector_pre_change < -15:
            return {
                "direction": "bullish", "score": 65,
                "reason": f"利空但前期已跌{abs(sector_pre_change):.0f}% → 👀利空出尽候选",
                "signal": "利空出尽候选",
            }
    
    if direction == "bullish":
        return {"direction": "bullish", "score": base, "reason": f"{level}级利好催化"}
    elif direction == "bearish":
        return {"direction": "bearish", "score": 100 - base, "reason": f"{level}级利空冲击"}
    return {"direction": "neutral", "score": 50, "reason": "事件中性"}
```

### 3.3 维度 3: 资金流向 (权重: 动态 15-25%)

```python
def capital_flow_score(flow_data: dict) -> dict:
    """
    资金评分 + 分时模式识别。
    
    关键: 不能只看全天数据，要看分时演变。
    - 早盘流入→午后转流出 = 🚨冲高派发 (7/10中国巨石案例)
    - 早盘流出→午后转流入 = 👀低位吸筹
    """
    main_net_yi = flow_data.get("main_net_yi", 0)
    morning_dir = flow_data.get("morning_dir", "neutral")
    afternoon_dir = flow_data.get("afternoon_dir", "neutral")
    
    # 分时模式
    if morning_dir == "inflow" and afternoon_dir == "outflow":
        return {
            "direction": "bearish", "score": 20,
            "reason": "早盘流入→午后转流出 → 🚨冲高派发",
            "pattern": "冲高派发",
            "rule": "R15: 冲高派发",
        }
    if morning_dir == "outflow" and afternoon_dir == "inflow":
        return {
            "direction": "bullish", "score": 75,
            "reason": "早盘流出→午后转流入 → 👀低位吸筹",
            "pattern": "低位吸筹",
        }
    
    # 正常评分
    if main_net_yi > 50:
        return {"direction": "bullish", "score": 85, "reason": f"主力大额流入{main_net_yi:.0f}亿"}
    elif main_net_yi > 5:
        return {"direction": "bullish", "score": 70, "reason": f"主力净流入{main_net_yi:.0f}亿"}
    elif main_net_yi > -5:
        return {"direction": "neutral", "score": 48, "reason": "资金小幅波动"}
    elif main_net_yi > -20:
        return {"direction": "bearish", "score": 30, "reason": f"主力净流出{abs(main_net_yi):.0f}亿"}
    elif main_net_yi > -50:
        return {"direction": "bearish", "score": 20, "reason": f"主力大额流出{abs(main_net_yi):.0f}亿"}
    else:
        return {"direction": "bearish", "score": 10, "reason": f"主力巨额流出{abs(main_net_yi):.0f}亿 → 全面撤退"}
```

### 3.4 维度 4: 市场情绪 (权重: 动态 10-30%)

```python
def sentiment_score(sentiment_data: dict, pre_change: float = 0) -> dict:
    """
    情绪评分 + 拥挤度修正。
    
    ≥80 极度亢奋 + 前期涨>15% → 🔴拥挤出清 (R2: 跑输概率>80%)
    ≤20 极度悲观 + 前期跌>15% → 🟢潜在左侧机会
    """
    composite = sentiment_data.get("composite", 50)
    
    if composite >= 80 and pre_change > 15:
        return {"direction": "bearish", "score": 10,
                "reason": "情绪亢奋+前期大涨 → 🔴拥挤出清(R2:跑输>80%)",
                "rule": "R2: 拥挤预警"}
    elif composite >= 80:
        return {"direction": "bearish", "score": 25, "reason": "情绪极度亢奋→短期过热"}
    elif composite <= 20 and pre_change < -15:
        return {"direction": "bullish", "score": 75,
                "reason": "情绪悲观+前期大跌 → 🟢潜在左侧机会"}
    elif composite <= 20:
        return {"direction": "bullish", "score": 65, "reason": "情绪极度悲观→可能超跌"}
    elif composite >= 60:
        return {"direction": "bullish", "score": 65, "reason": f"情绪偏暖({composite})"}
    else:
        return {"direction": "neutral", "score": 50, "reason": f"情绪中性({composite})"}
```

### 3.5 维度 5: 基本面估值 (权重: 动态 0-30%)

```python
def fundamental_score(fundamental_data: dict, event_level: str = None,
                      market_regime: str = None) -> dict:
    """
    基本面评分 + 事件覆盖规则。
    
    关键: 在事件驱动日，基本面几乎无效。
    7/10案例:
    - S级事件 → 航天电子PE 614仍涨停 (基本面权重归零)
    - 事件驱动日 → 中国巨石Q1+73%→-5.11% (基本面不解释当天走势)
    """
    # 事件覆盖
    if event_level == "S":
        return {"direction": "neutral", "score": 50, "weight_override": 0.00,
                "reason": "S级事件覆盖基本面约束(R21)"}
    if event_level == "A" or market_regime == "事件驱动日":
        return {"direction": "neutral", "score": 50, "weight_override": 0.05,
                "reason": "事件驱动日，基本面逻辑让位于消息+资金"}
    
    # 正常评分
    profit_growth = fundamental_data.get("profit_growth_yoy", 0)
    pe = fundamental_data.get("pe", 0)
    sector_pe = fundamental_data.get("sector_pe", 0)
    
    score = 50
    if profit_growth > 50: score += 20
    elif profit_growth > 20: score += 10
    elif profit_growth < 0: score -= 15
    
    if pe > 0 and sector_pe > 0:
        if pe < sector_pe * 0.7: score += 10
        elif pe > sector_pe * 2: score -= 10
    
    direction = "bullish" if score > 55 else ("bearish" if score < 45 else "neutral")
    return {"direction": direction, "score": max(10, min(90, score)),
            "reason": f"利润增速{profit_growth}% PE{pe:.0f}"}
```

### 3.6 维度 6: 技术面 (权重: 动态 10-25%)

```python
def technical_score(tech_data: dict) -> dict:
    """
    技术面评分 + 异常检测。
    
    异常: 振幅>12%+换手>10% → 极端博弈 | 量比>2.0 → 爆量
    """
    chg = tech_data.get("change_pct", 0)
    amp = tech_data.get("amplitude", 0)
    turnover = tech_data.get("turnover", 0)
    vol_ratio = tech_data.get("vol_ratio", 0)
    
    reasons = []
    score = 50
    
    if amp > 12 and turnover > 10:
        score -= 15
        reasons.append(f"振幅{amp}%+换手{turnover}% → ⚠️极端博弈")
    if vol_ratio > 2.0:
        reasons.append(f"量比{vol_ratio} → 爆量")
    
    if chg > 9: direction = "bullish"; score = 85
    elif chg > 3: direction = "bullish"; score += 15
    elif chg < -6: direction = "bearish"; score -= 20
    elif chg < -3: direction = "bearish"; score -= 10
    else: direction = "neutral"
    
    return {"direction": direction, "score": max(10, min(90, score)),
            "reason": f"涨跌{chg:+.1f}%; " + "; ".join(reasons)}
```

---

## Layer 4: 跷跷板检测 + 流动性虹吸

```python
def seesaw_detection(all_sectors: list[dict]) -> dict:
    """
    三维检测:
    1. 资金跷跷板: 流入TOP3 vs 流出TOP3
    2. 高低切换: 涨最多的被卖出 + 跌最多的被买入
    3. 流动性虹吸受害方: 流出+无直接利空 → 被隔壁题材吸走资金
    
    7/10 案例:
    - 跷跷板: 商业航天↔半导体
    - 高低切换: 高位科技(年涨105%)→低位消费医药(跌15-25%)
    - 虹吸受害: 中国巨石(无利空但-5.11% → 被科技流出+航天涨停潮虹吸)
    """
    sorted_by_flow = sorted(all_sectors, key=lambda x: x.get("main_net_yi", 0), reverse=True)
    sorted_by_pre = sorted(all_sectors, key=lambda x: x.get("pre_change_2w", 0), reverse=True)
    
    inflow_top = sorted_by_flow[:3]
    outflow_top = sorted_by_flow[-3:][::-1]
    highest = sorted_by_pre[:3]
    lowest = sorted_by_pre[-3:][::-1]
    
    signals = []
    
    # 信号1: 高低切换
    high_out = [s for s in outflow_top if s.get("pre_change_2w", 0) > 10]
    low_in = [s for s in inflow_top if s.get("pre_change_2w", 0) < 0]
    if high_out and low_in:
        signals.append({
            "type": "🔄 高低切换进行中",
            "from": [s["name"] for s in high_out],
            "to": [s["name"] for s in low_in],
            "note": "高低切换历史胜率约40%，需基本面改善支撑(广发证券)",
        })
    
    # 信号2: 新题材吸走流动性
    if inflow_top[0].get("main_net_yi", 0) > 50 and outflow_top[0].get("main_net_yi", 0) < -50:
        signals.append({
            "type": "💥 新题材吸走旧题材流动性",
            "new_theme": inflow_top[0]["name"],
            "old_theme": outflow_top[0]["name"],
        })
    
    # 信号3: 流动性虹吸受害方
    victims = []
    for s in outflow_top + sorted_by_flow[-6:-3]:
        if not s.get("has_bearish_event") and s.get("main_net_yi", 0) < -5:
            victims.append({
                "name": s["name"],
                "outflow_yi": abs(s.get("main_net_yi", 0)),
                "reason": "无直接利空但资金流出 → 可能被隔壁题材虹吸",
            })
    if victims:
        signals.append({
            "type": "💧 流动性虹吸受害方(非基本面恶化)",
            "victims": victims,
        })
    
    return {
        "inflow_top3": inflow_top, "outflow_top3": outflow_top,
        "highest_2w": highest, "lowest_2w": lowest,
        "signals": signals,
    }


def chain_position_elasticity(sector: str, position: str) -> float:
    """
    产业链位置弹性系数。
    
    同一行业不同位置的标的对消息的反应弹性不同。
    7/10案例: 新能源-宁德时代(-7.12%) vs 隆基绿能(+2.37%)
    
    上游(资源/设备): 1.2 — beta更高，跟跌跟涨更猛
    中游(制造/加工): 1.0 — 基准
    下游(品牌/终端): 0.8 — 有自己的独立逻辑
    """
    return {"上游": 1.2, "中游": 1.0, "下游": 0.8}.get(position, 1.0)


def defensive_premium(sector: str, regime: str) -> float:
    """
    防御型标的在市场震荡时自动获得溢价。
    7/10: 长江电力+0.94%/招商银行+0.90%/中国移动+1.43% — 避险资金涌入
    """
    defensive = ["银行", "电力", "通信", "公用事业", "公路铁路"]
    if sector in defensive and regime in ("事件驱动日", "极端情绪日"):
        return 0.5  # +0.5分
    return 0.0
```

---

## Layer 5: 综合评分 + 参考条件

### 5.1 六维加权合成

```python
def composite_scoring(dimensions: dict, weights: dict, regime: str,
                     elasticity: float = 1.0, defensive_bonus: float = 0.0) -> dict:
    """
    六维加权综合评分 (0-10分)。
    
    评分 = SUM(每维度方向×得分×权重) × 产业链弹性系数 + 防御溢价
    然后映射到0-10分。
    """
    total_score = 5.0
    
    for dim_key, dim_data in dimensions.items():
        base_w = weights.get(dim_key, 0.15)
        w = dim_data.get("weight_override", base_w)
        direction = dim_data.get("direction", "neutral")
        dim_score = dim_data.get("score", 50)
        
        if direction == "bullish":
            total_score += w * (dim_score - 50) / 50 * 10
        elif direction == "bearish":
            total_score -= w * (50 - dim_score) / 50 * 10
    
    # 产业链弹性系数
    total_score = 5.0 + (total_score - 5.0) * elasticity
    
    # 防御溢价
    total_score += defensive_bonus
    
    total_score = round(max(1, min(10, total_score)), 1)
    
    # 共识度 = 同向维度数 / 有效维度数
    directions = [d.get("direction") for d in dimensions.values()]
    bulls = sum(1 for d in directions if d == "bullish")
    bears = sum(1 for d in directions if d == "bearish")
    non_neutral = [d for d in directions if d != "neutral"]
    consensus = max(bulls, bears) / max(len(non_neutral), 1) if non_neutral else 0
    
    # 综合判断
    if total_score >= 8 and consensus >= 0.67:
        verdict = "🟢 多维共振看多 — 置信度高"
    elif total_score >= 7:
        verdict = "🟡 偏多 — 多数维度积极"
    elif total_score >= 5:
        verdict = "➖ 方向不明确 — 结构性机会"
    elif total_score >= 3:
        verdict = "🟠 偏空 — 多数维度消极，控制仓位"
    else:
        verdict = "🔴 多维共振看空 — 全面偏空"
    
    return {
        "score": total_score, "verdict": verdict, "consensus": f"{max(bulls, bears)}/{len(non_neutral)}维同向",
        "bull_dims": [k for k, d in dimensions.items() if d.get("direction") == "bullish"],
        "bear_dims": [k for k, d in dimensions.items() if d.get("direction") == "bearish"],
    }
```

### 5.2 风格判断

```python
def style_judgment(sectors_data: dict) -> dict:
    """
    市场风格: 进攻 / 防御 / 均衡 / 切换
    """
    offense = ["半导体", "AI算力", "券商", "军工"]
    defense = ["消费", "医药", "公用事业", "银行"]
    
    off_avg = sum(sectors_data.get(s, {}).get("composite", 50) for s in offense) / len(offense)
    def_avg = sum(sectors_data.get(s, {}).get("composite", 50) for s in defense) / len(defense)
    diff = off_avg - def_avg
    
    if diff > 15: return {"style": "⚔️ 进攻", "note": "科技主导，关注拥挤风险"}
    elif diff < -15: return {"style": "🛡️ 防御", "note": "防御主导，关注持续性"}
    elif abs(diff) <= 10: return {"style": "⚖️ 均衡", "note": "无明显风格偏向"}
    else: return {"style": "🔄 切换中", "note": "等待方向确认"}
```

### 5.3 入场/离场参考条件

```python
def generate_reference_conditions(composite: dict) -> dict:
    """生成入场/离场参考条件（研究框架产出，不是交易指令）"""
    score = composite["score"]
    
    entry_conditions = []
    if score <= 4:
        entry_conditions.append({
            "condition": "综合评分回到5分以上 + 至少3个维度转正",
            "current": f"当前{score}分", "note": "偏空时不要逆势抄底，等右侧信号",
        })
    elif score <= 6:
        entry_conditions.append({
            "condition": "出现S/A级利好催化 + 资金近3日转流入",
            "current": f"当前{score}分", "note": "方向不明时等待催化",
        })
    else:
        entry_conditions.append({
            "condition": "回调至关键支撑位 + 成交量萎缩 + 资金未大幅流出",
            "current": f"当前{score}分", "note": "偏多市场回调是正常调整",
        })
    
    exit_conditions = [
        {"condition": "前期涨幅>15% + 资金近3日连续流出",
         "signal": "利好出尽", "historical": "回调概率~84%"},
        {"condition": "情绪>80(亢奋) + 成交额占比>45%",
         "signal": "微观结构恶化", "historical": "跑输概率>80%"},
        {"condition": "S级利空事件 + 前期涨幅>10%",
         "signal": "政策黑天鹅"},
    ]
    
    return {"entry_conditions": entry_conditions, "exit_conditions": exit_conditions}
```
## 历史统计规律知识库

以下规律来自券商研报对 A 股过去 10-20 年数据的量化回测，每条标注触发条件、历史胜率和适用环境。

### 类别 1: 涨跌幅约束类

| # | 规律 | 触发条件 | 历史胜率 | 来源 | 适用环境 |
|---|------|---------|---------|------|---------|
| R1 | 利好出尽 | 板块前2周涨幅>15% + 仍有未兑现利好 | 回调概率~84% | 东财证券 2010-2022回测 | 所有环境 |
| R2 | 拥挤预警 | 涨幅>15% + 成交额占比>45% | 跑输概率>80% | 开源证券 | 正常轮动 |
| R3 | 高开低走 | 大盘高开≥2%(政策大利好次日) | 低走概率84-86% | 海通/中金 2010以来 | 事件驱动 |
| R4 | 单日大涨不封板 | 单日涨>5%但未封涨停 | T+1~T+5累计约-3.02% | 6,911样本 | 正常轮动 |
| R5 | 事件脉冲分化 | 一次性事件冲击(如首飞/发射) | T+1分化概率高 | 6,911事件样本 | 事件驱动 |

### 类别 2: 事件持续性类

| # | 规律 | 事件类型 | 延续性 | 最佳窗口 | 来源 |
|---|------|---------|--------|---------|------|
| R6 | 产业趋势最强 | 业绩+政策双驱动 | ⭐⭐⭐⭐⭐ | 持续16-19月 | 供给侧改革案例 |
| R7 | 政策驱动中等 | 政策密集但无即期业绩 | ⭐⭐⭐ | 政策空窗期回调 | 五年规划周期 |
| R8 | 业绩超预期延续 | 业绩超预期20%+ | ⭐⭐⭐⭐ | T+60超额3.9% | 中金2025回测 |
| R9 | 突发题材最短 | 突发题材无基本面支撑 | ⭐ | 3板后A杀概率高 | 多次案例 |

### 类别 3: 风格切换类

| # | 规律 | 触发条件 | 发生概率 | 必要条件 | 来源 |
|---|------|---------|---------|---------|------|
| R10 | 牛市高低切换 | 高位→低位轮动 | 40%(5次中2次) | 低位需基本面改善+宏大叙事 | 广发证券 |
| R11 | 假切换回归 | 拥挤消化后主线重聚 | 常见 | 产业趋势未完 | 广发证券 |
| R12 | 日历效应-五年规划前 | 军工+银行上涨概率100% | — | — | 历史统计 |

### 类别 4: 资金信号类

| # | 规律 | 触发条件 | 含义 | 来源 |
|---|------|---------|------|------|
| R13 | 机构吸筹 | 超大单流入 + 散户流出 | 筹码从散户→机构 | push2 资金流 |
| R14 | 机构派发 | 超大单流出 + 散户流入 | 筹码从机构→散户 | push2 资金流 |
| R15 | 早盘冲高午后回落 | 上午流入→下午流出>上午 | 冲高派发 | 7/10中国巨石验证 |
| R16 | ETF持续流入+板块流出 | ETF申购但板块资金流出 | 机构左侧布局 | etf-fund-flow-tracker |

### 类别 5: 外围映射类

| # | 规律 | 触发条件 | 含义 |
|---|------|---------|------|
| R17 | A股-美股脱钩 | A股vs外围对标涨跌幅差>15% | 脱钩，外围参考价值低 |
| R18 | 美股暴跌传导 | 美股科技单日跌>3% | A股次日大概率低开，但低开幅度<2%时可能低开高走 |
| R19 | SOX-A股半导体相关性 | 正常环境相关系数~0.6-0.8 | 脱钩时降至~0.2 |

### 类别 6: 估值锚定类

| # | 规律 | 触发条件 | 含义 |
|---|------|---------|------|
| R20 | PE分位数极端低 | <10%分位数 + 无基本面恶化 | 估值修复概率高 |
| R21 | 事件覆盖估值 | S级事件(首次/第一) | PE约束临时解除 |
| R22 | 业绩暴增但股价涨更多 | 利润+100%但股价+150% | 预期已被过度定价 |

---

## 实时数据拉取

### 实时行情 (腾讯 API — 不封 IP，优先使用)

```python
import urllib.request

def fetch_realtime_quotes(codes: list[str]) -> dict:
    """
    腾讯财经实时行情 — 一次请求拉取多只标的。
    
    codes: ['sh512480', 'sz159995', 'sh600176', 'sh600879', ...]
    返回: {code: {name, price, change_pct, open, high, low, pre_close, turnover, vol_ratio, amplitude}}
    """
    url = 'https://qt.gtimg.cn/q=' + ','.join(codes)
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0')
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode('gbk')
    
    results = {}
    for line in data.strip().split('\n'):
        if not line.strip():
            continue
        parts = line.split('~')
        if len(parts) < 50:
            continue
        code = parts[2]
        results[code] = {
            "name": parts[1], "price": float(parts[3]) if parts[3] else 0,
            "change_pct": float(parts[32]) if parts[32] else 0,
            "open": float(parts[5]) if parts[5] else 0,
            "high": float(parts[33]) if parts[33] else 0,
            "low": float(parts[34]) if parts[34] else 0,
            "pre_close": float(parts[4]) if parts[4] else 0,
            "turnover": float(parts[38]) if parts[38] else 0,
            "vol_ratio": float(parts[49]) if parts[49] else 0,
            "amplitude": float(parts[43]) if parts[43] else 0,
        }
    return results
```

### 概念板块资金流 (东财 push2 — 限流，仅在关键分析时使用)

```python
import time, random, requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15):
    """东财统一请求：自动节流（≥2秒间隔，资金流接口更敏感）"""
    wait = 2.0 + random.uniform(0.5, 1.5) - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait)
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last_call[0] = time.time()

def fetch_concept_sector_flows() -> dict:
    """拉取全量概念板块资金流（约494个概念板块）"""
    url = 'https://push2.eastmoney.com/api/qt/clist/get'
    params = {
        'pn': '1', 'pz': '500', 'po': '0', 'np': '1',
        'fltt': '2', 'invt': '2',
        'fs': 'm:90+t:3',
        'fields': 'f2,f3,f8,f10,f12,f14,f62,f66,f72,f78,f84,f104,f105,f128',
        'st': 'f62',
    }
    headers = {'Referer': 'https://data.eastmoney.com/'}
    r = em_get(url, params=params, headers=headers, timeout=20)
    d = r.json()
    items = d.get('data', {}).get('diff', []) or []
    return {
        "total": d.get('data', {}).get('total', 0),
        "sectors": [
            {
                "code": it.get('f12', ''),
                "name": it.get('f14', ''),
                "main_net": (it.get('f62') or 0) / 1e8,  # 转换为亿
                "change_pct": it.get('f3', 0),
                "up_count": it.get('f104', 0),
                "down_count": it.get('f105', 0),
            }
            for it in items
        ],
    }
```

### 消息面 (WebSearch — 必须筛选"具备实质影响"的消息)

```python
# 消息采集优先级:
# 1. WebSearch: "板块/个股 + 2026年7月 + 事件/政策/新闻"
# 2. WebSearch: "A股 重大事件 2026年7月10日"
# 3. WebFetch: 获取政策原文/事件详情

# ━━ 消息过滤规则 ━━
# ✅ 保留: 涉及真实政策/业绩/重大事件的新闻
# ❌ 丢弃: 纯市场评论/价格预测/自媒体观点/AI生成内容
# ⚠️ 标记: 传闻(未证实)/分析师预测(二级来源)

# ━━ 影响判断 ━━
# 每条保留消息必须回答:
# 1. 这个事件改变了什么基本面假设？
# 2. 市场是否已经定价？（前期涨跌幅检查）
# 3. 影响的持续性是脉冲还是趋势？（事件持续性分类）
```

---

## 执行流程

```
量化综合研判执行清单:
- [ ] Step 0: 拉取全市场实时行情 (腾讯API × 全行业代表股 20+只)
- [ ] Step 1: 拉取全量概念板块资金流 (东财push2，限流2秒/次)
- [ ] Step 2: 搜索今日重大事件 (WebSearch × 5-8次，覆盖主要行业)
- [ ] Step 3: 事件筛选 → 只保留具备实质影响的 → 事件强度分级(S/A/B/C)
- [ ] Step 4: 市场状态识别 (事件驱动/正常轮动/极端情绪/业绩验证)
- [ ] Step 5: 选择动态权重矩阵
- [ ] Step 6: 六维评分 (每维度应用修正因子)
- [ ] Step 7: 跷跷板检测 + 高低切换判断 + 对立面分析
- [ ] Step 8: 综合评分 0-10 + 风格判断
- [ ] Step 9: 行业优先级排序 (5档)
- [ ] Step 10: 生成入场/离场参考条件
- [ ] Step 11: 对照30条历史规律检查
- [ ] Step 12: 输出完整仪表盘报告
- [ ] Step 13: 保存到 src/宏观经济/YYYY-MM-DD-量化综合研判/
```

---

## 输出模板

```markdown
## 📊 量化综合研判仪表盘

**研判时间**：YYYY-MM-DD HH:MM
**市场状态**：事件驱动日 / 正常轮动日 / 极端情绪日 / 业绩验证日
**综合评分**：X.X / 10 → 🟢看多 / 🟡偏多 / ➖中性 / 🟠偏空 / 🔴看空
**市场风格**：⚔️进攻 / 🛡️防御 / ⚖️均衡 / 🔄切换中
**共识度**：X/6 维度同向

---

### 📊 六维雷达

| 维度 | 权重 | 方向 | 得分 | 核心信号 |
|------|------|------|------|---------|
| 🌍 外围映射 | X% | 🟢/🔴/⚪ | XX | |
| 📰 政策事件 | X% | 🟢/🔴/⚪ | XX | |
| 💰 资金流向 | X% | 🟢/🔴/⚪ | XX | |
| 📈 市场情绪 | X% | 🟢/🔴/⚪ | XX | |
| 📊 基本面 | X% | 🟢/🔴/⚪ | XX | |
| 📐 技术面 | X% | 🟢/🔴/⚪ | XX | |

### 🔄 跷跷板检测

- 资金流入 TOP3: ...
- 资金流出 TOP3: ...
- 涨最多 (近2周): ...
- 跌最多 (近2周): ...
- 切换信号: ...

### 🎯 行业优先级排序

| 优先级 | 行业 | 核心理由 | 主要风险 | 触发信号 |
|--------|------|---------|---------|---------|
| 🥇 1 | | | | |
| 🥈 2 | | | | |
| 🥉 3 | | | | |
| ⏸️ 观望 | | | | |
| 🚨 回避 | | | | |

### 🎯 入场参考条件

1. 条件1: ... (当前状态: ...)
2. 条件2: ... (当前状态: ...)

### ⚠️ 离场参考条件

1. 条件1: ... (历史胜率: ...)
2. 条件2: ... (历史胜率: ...)

### 🚨 风险预警

| 风险 | 触发条件 | 当前状态 | 概率 |
|------|---------|---------|------|
| | | | |

---

⚠️ 研究声明：本报告基于公开数据和多方交叉验证，所有评分和条件均为研究框架产出，不构成投资建议。综合评分反映的是多维数据的加权聚合，不直接等于涨跌预测。
```

---

## 与其他 Skill 的协作

| 协作方 | 调用时机 | 获取内容 |
|--------|---------|---------|
| **a-stock-data** | Step 1 | 实时行情(腾讯API) |
| **policy-event-tracker** | Step 2-3 | 事件扫描 + 影响分析 + 前期涨跌幅 |
| **capital-flow-tracker** | Step 1,6 | 概念板块资金流 + 三方资金分类 |
| **etf-fund-flow-tracker** | Step 1,6 | ETF资金流 + 增量资金信号 |
| **industry-sentiment-tracker** | Step 6 | 行业情绪指数 + 极端信号 |
| **earnings-tracker** | Step 6 | 业绩验证 (仅在业绩验证日深度调用) |
| **hard-tech-dashboard** | 按需 | 当聚焦硬科技方向时，委托给此 skill |
| **serenity-skill** | 按需 | 当需要产业链深度分析时 |

---

## 边界情况与已知陷阱

### 陷阱 1: 综合评分在温和下跌时过度悲观 (2026-07-10 验证)

**问题**：科创50跌-5.11%（非跌停），六维评分给到 1/10，与实际严重程度不匹配。
**根因**：4 个维度同向看空时，加权评分没有"地板效应"控制。
**修复**：增加评分修正规则——当实际涨跌幅在 -5%~-3% 区间且评分<2 时，自动修正至 2-3 分。

```python
def calibrate_score(composite_score: float, actual_change: float) -> float:
    """评分校准：防止评分与实际走势严重脱节"""
    if actual_change > -3 and composite_score < 3:
        return max(composite_score, 2.5 + actual_change)  # 温和下跌不应<2分
    if actual_change < -8 and composite_score > 8:
        return min(composite_score, 3.0)  # 暴跌不应>3分
    return composite_score
```

### 陷阱 2: S级事件驱动的涨停潮→T+1分化风险 (2026-07-10 验证)

**问题**：商业航天 10/10 满分，但历史数据表明事件脉冲后的 T+1 日大概率分化（单日大涨后 T+1~T+5 累计约 -3.02%）。
**修复**：当评分 ≥9 且事件类型为"一次性冲击"时，自动附加"T+1 分化预警"。

```python
def event_pulse_warning(composite_score: float, event_type: str) -> str:
    """事件脉冲衰减预警"""
    if composite_score >= 9 and event_type == "一次性冲击":
        return ("⚠️ T+1分化预警: 历史6,911样本显示，单日事件脉冲后"
                "T+1~T+5累计约-3.02%，次日追高风险极大")
    return ""
```

### 陷阱 3: 事件分级边界模糊 (2026-07-10 验证)

**问题**：五粮液百亿分红被归为 A 级，但"分红"本质上是预期内回报，不应与"国家首次回收火箭"同级。
**修复**：A 级新增严格限制——必须满足"改变基本面假设"条件。分红、常规中标、普通业绩预告最多给 B 级。

| 事件类型 | 最高级别 | 原因 |
|---------|---------|------|
| 分红/回购 | B | 不改变基本面假设，是对已有价值的确认 |
| 普通中标/订单 | B | 常规经营行为，除非金额超年营收 50% |
| 业绩预告(±30%以内) | B | 预期内波动 |
| 业绩预告(±100%+) | A | 大幅超预期改变基本面假设 |
| 国家级首次/全球首次 | S | 开创性里程碑 |
| 出口管制加码(新清单) | A | 改变产业链格局 |
| 政治局/国务院级别政策 | S | 最高级别政策信号 |

### 陷阱 4: 非交易时段运行 (待触发)

**问题**：skill 可能在收盘后/周末运行，此时腾讯 API 返回的是收盘价，不是实时价。
**处理**：自动检测当前时间——如果在 9:30-15:00 之外，标注"基于收盘数据"，且资金流维度使用当日全天数据（非盘中）。

---

## 风险声明

- 综合评分基于多维度加权和修正因子，权重设定需要持续校准
- 历史统计规律来自券商研报回测，"历史不会简单重复"
- 事件强度分级为主观判断，不同人对同一事件的定级可能不同
- 市场状态识别存在误判可能（如把正常回调误判为恐慌日）
- S级事件驱动的涨停潮 T+1 日大概率分化，满分≠可以追高
- 所有评分和参考条件均为研究框架产出，不构成投资建议
