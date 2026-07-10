---
name: hard-tech-dashboard
description: A股硬科技走势综合研判仪表盘 — 整合六维数据(外围股市映射/全球政策事件/产业链趋势/A股资金面/A股情绪面/业绩验证)，输出硬科技板块全景研判报告。核心能力：①全球科技股→A股硬科技传导分析 ②出口管制/技术封锁政策冲击量化 ③产业链稀缺环节定位与国产替代弹性评估 ④六维共振检测(多维度同向=高置信度) ⑤子板块(半导体/AI算力/高端制造/新材料/航空航天)优先级排序。触发词："硬科技""科技板块走势""半导体/AI/芯片 行情研判""国产替代 机会""科技股 还能不能涨""全球科技 对A股影响""费城半导体/纳指 对A股科技影响""科技赛道 配置"。
version: 1.0.0
updated: 2026-07-09
---

# A股硬科技走势研判仪表盘 V1.0

整合外围股市、全球政策、产业链趋势、A股内部资金/情绪/业绩多维数据，对 A 股硬科技板块进行全景式走势研判。**核心价值：将分散的 skill 输出 + 外部全球数据合成为统一研判结论，回答"硬科技现在能不能做、做哪个方向、风险在哪里"。**

> **设计原则：** 本 skill 是**编排/合成层**，不直接拉取原始数据。数据获取委托给 a-stock-data 及各专项 skill，本 skill 聚焦于多维数据的交叉验证、传导逻辑推演和综合评分。
>
> **与现有 skill 的关系：**
> - **数据输入方**（7 个 skill 提供原始分析）：policy-event-tracker（政策事件）、serenity-skill（产业链瓶颈）、moat-hunter（企业壁垒）、capital-flow-tracker（板块资金流）、etf-fund-flow-tracker（ETF资金流）、limit-up-tracker（涨停情绪）、earnings-tracker（业绩趋势）、industry-sentiment-tracker（行业情绪指数）
> - **本 skill**（合成输出方）：将以上输入 + 外围股市/全球政策数据，合成为硬科技走势研判
> - **stock-pick**（下游消费方）：可基于本 skill 的子板块优先级排序，聚焦选股

---

## When to Activate

- 用户要判断**硬科技板块整体走势**（看多/看空/中性，置信度如何）
- 用户要分析**外围科技股对 A 股科技的传导影响**（美股 SOX 跌了→A 股半导体跟不跟？）
- 用户要评估**全球政策冲击**（新出口管制/技术封锁→利好国产替代还是利空供应链？）
- 用户要识别**硬科技内部的子板块优先级**（半导体 vs AI 算力 vs 高端制造 vs 新材料）
- 用户要做**科技赛道配置决策**（增配/减配/观望，哪个细分方向最优）
- 用户要检测**多维共振信号**（外部+政策+资金+情绪+业绩是否同向？）
- 关键词：`硬科技`、`科技板块走势`、`半导体/AI/芯片 行情研判`、`国产替代 机会`、`科技股 还能不能涨`、`全球科技 对A股影响`、`费城半导体/纳指 对A股科技影响`、`科技赛道 配置`、`硬科技 风险`

**不适用场景**：
- 单只个股分析（用 a-stock-data + stock_daily_attribution）
- 纯产业链深度调研（用 serenity-skill）
- 纯政策事件扫描（用 policy-event-tracker）
- 纯资金流向跟踪（用 capital-flow-tracker）

---

## 硬科技定义与覆盖范围

### 五大子板块

| 子板块 | 核心环节 | A股代表性环节 | 全球对标 |
|--------|---------|-------------|---------|
| 🔷 **半导体** | 设计/制造/设备/材料/封测 | 设备(刻蚀/薄膜/检测)、材料(硅片/气体/光刻胶)、先进封装 | 费城半导体 SOX、台积电、三星、东京电子 |
| 🔶 **AI 算力** | 算力芯片/光模块/服务器/数据中心 | AI 芯片(寒武纪/海光)、光模块(中际旭创/新易盛)、服务器(浪潮) | NVIDIA、AMD、Broadcom |
| 🔹 **高端制造** | 工业母机/机器人/精密仪器 | 数控机床、减速器、伺服系统、激光设备 | 发那科、ABB、基恩士 |
| 🔸 **新材料** | 电子化学品/特种气体/先进陶瓷/碳纤维 | 电子特气、光刻胶、靶材、碳化硅 | 信越化学、SUMCO、JSR |
| 🔹 **航空航天** | 商业航天/卫星互联网/无人机 | 火箭/卫星制造、地面终端、无人机链 | SpaceX(未上市)、雷神、洛克希德马丁 |

### 硬科技核心标的池

详见 [references/hard-tech-universe.md](references/hard-tech-universe.md)。快速参考：

```python
# 硬科技五大子板块 → 东财概念板块 BK 码映射
HARD_TECH_BK_MAP = {
    "半导体":   ["BK1036", "BK0873", "BK0888", "BK1168", "BK1137"],  # 半导体概念/芯片/光刻机(胶)/先进封装/存储芯片
    "AI算力":   ["BK1134", "BK1185", "BK1151", "BK0800", "BK1180"],  # 算力概念/CPO概念/液冷/AI芯片/HBM
    "高端制造": ["BK0809", "BK1176", "BK0880", "BK0596"],             # 工业母机/人形机器人/机器人概念/高端装备
    "新材料":   ["BK0643", "BK1096", "BK0653", "BK0457"],             # 小金属/电子化学品/碳纤维/稀土永磁
    "航空航天": ["BK0801", "BK0901", "BK0705", "BK0603"],             # 航天概念/大飞机/军民融合/军工
}
```

---

## 六维研判框架

### 框架总览

```
                          ┌────────────────────────────────────┐
                          │       硬科技走势综合研判             │
                          │    Hard Tech Trend Dashboard       │
                          │         综合评分 (1-10)             │
                          └──────────────┬─────────────────────┘
                                         │
       ┌─────────────┬──────────────┬────┴───────┬──────────────┬─────────────┐
       │             │              │            │              │             │
       ▼             ▼              ▼            ▼              ▼             ▼
  ┌─────────┐  ┌─────────┐  ┌───────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
  │🌍外围映射│  │📰全球政策│  │🔗产业链趋势│  │💰A股资金│  │📈A股情绪│  │📊业绩验证│
  │  20%    │  │   25%   │  │    25%    │  │   15%   │  │   10%   │  │   5%    │
  └────┬────┘  └────┬────┘  └─────┬─────┘  └────┬────┘  └────┬────┘  └────┬────┘
       │            │              │              │            │            │
       ▼            ▼              ▼              ▼            ▼            ▼
  WebSearch    policy-event   serenity-skill  capital-flow  limit-up    earnings
  +WebFetch    -tracker       +moat-hunter    -tracker      -tracker    -tracker
  (外围指数)   +WebSearch     (产业链位置)   +etf-fund-    (科技涨停)  (科技业绩)
               (出口管制等)                   flow-tracker              +industry-
                                             (科技ETF)                sentiment
```

### 六维度详解

| # | 维度 | 权重 | 核心问题 | 数据来源 | 分析内容 |
|---|------|------|---------|---------|---------|
| 1 | 🌍 **外围映射** | 20% | 全球科技股在涨还是跌？A 股跟不跟？ | WebSearch（美股 SOX/纳指/费城半导体/台积电 ADR/日经半导体） | 美股科技趋势、SOX 关键位、A股-美股科技相关性变化、脱钩/挂钩判断 |
| 2 | 📰 **全球政策** | 25% | 出口管制在加码还是放松？国产替代逻辑在强化还是弱化？ | policy-event-tracker + WebSearch（BIS 实体清单/荷兰日本设备管制/国内产业政策） | 管制升级→国产替代弹性；管制放松→竞争压力；补贴政策→需求拉动 |
| 3 | 🔗 **产业链** | 25% | 全球科技产业链哪个环节最紧张？A 股在哪个位置？ | serenity-skill + moat-hunter + WebSearch（全球 capex/订单/产能数据） | 产业链稀缺层定位、技术路线变化、A 股在全球链中的位置、供需缺口 |
| 4 | 💰 **A 股资金** | 15% | 机构在买科技还是卖科技？增量资金在进还是出？ | capital-flow-tracker（科技板块资金流）+ etf-fund-flow-tracker（科创50/芯片/半导体 ETF 资金流） | 科技板块主力资金方向、ETF 申购赎回趋势、机构 vs 游资配置意图 |
| 5 | 📈 **A 股情绪** | 10% | 涨停板上科技股多不多？连板高度如何？情绪过热还是冰点？ | limit-up-tracker（科技涨停统计）+ industry-sentiment-tracker（科技行业情绪分） | 科技涨停占比、连板高度趋势、情绪指数(0-100)、极端情绪拐点信号 |
| 6 | 📊 **业绩验证** | 5% | 硬科技公司业绩在改善还是恶化？超预期还是低预期？ | earnings-tracker（硬科技标的业绩扫描） | 业绩预告方向、超预期比例、营收/利润拐点、合同负债趋势 |

> **权重逻辑**：全球政策(25%)和产业链(25%)是结构性驱动因素，决定中长期方向；外围映射(20%)是短期情绪锚；A 股资金(15%)+情绪(10%)是同步验证指标；业绩(5%)是滞后确认指标（季报频率低，但关键时刻一锤定音）。

---

## 传导逻辑链（核心分析引擎）

### 全球科技 → A 股硬科技的 5 条传导路径

```
路径1: 美股科技涨跌 → 估值锚定 → A股科技估值重定价
  机制: SOX/纳指下跌 → 全球科技股 PE 中枢下移 → A 股科技股估值承压
  关键观察: A股科技 vs SOX 的 20日相关性系数变化
  脱钩条件: 国产替代逻辑强化 + 国内流动性宽松 → 相关性下降

路径2: 出口管制加码 → 供应链断裂风险 + 国产替代加速
  机制: BIS 新实体清单 → 设备/EDA/IP 断供 → 短期利空(停产风险) + 中长期利好(替代需求)
  关键判断: 管制范围（是否覆盖成熟制程/是否涉及关键设备）
  弹性最大环节: 半导体设备 > 材料 > EDA > 制造

路径3: 全球 AI capex → 算力需求 → A 股光模块/服务器/PCB 订单
  机制: 北美云厂商 capex 指引↑ → 光模块/服务器订单↑ → 业绩兑现
  关键数据: Microsoft/Google/Amazon/Meta capex 季报
  弹性最大环节: 光模块 > AI 服务器组装 > PCB > 散热

路径4: 全球半导体周期 → 价格/出货量 → A 股设计/制造/封测景气度
  机制: 全球半导体销售额↑ + 库存天数↓ → 涨价 → 设计公司毛利↑ → 制造封测产能利用率↑
  关键指标: SIA 全球半导体销售、DRAM/NAND 现货价、台积电月度营收
  周期位置判断: 复苏初期/景气上行/高位筑顶/下行初期/底部磨底

路径5: 国内产业政策 → 需求创造 → A 股硬科技订单/收入
  机制: 大基金/产业补贴/政府采购 → 国产设备/材料/芯片导入 → 收入增长
  关键政策: 大基金(一/二/三期)、集成电路增值税减免、首台套政策
  弹性最大环节: 半导体设备(国产化率最低) > 材料 > 制造
```

### 传导路径分析实现

```python
def analyze_transmission_paths(
    global_data: dict,      # 外围市场数据
    policy_data: dict,      # 政策事件数据
    chain_data: dict,       # 产业链数据
) -> list[dict]:
    """
    分析全球科技 → A股硬科技的 5 条传导路径状态。
    每条路径返回: 方向(利多/利空/中性)、强度(强/中/弱)、置信度(高/中/低)、核心逻辑
    """
    paths = []

    # 路径1: 估值锚定传导
    sox_change = global_data.get("sox_change_1m", 0)  # SOX 近1月涨跌幅
    nasdaq_change = global_data.get("nasdaq_change_1m", 0)
    if sox_change > 5:
        paths.append({
            "path": "估值锚定传导", "direction": "利多", "strength": "强" if sox_change > 10 else "中",
            "confidence": "高", "trigger": f"SOX月涨{sox_change:.1f}%",
            "logic": "全球科技估值中枢上移 → A股科技估值修复",
            "key_watch": "A股-美股科技相关性是否下降(脱钩信号)",
        })
    elif sox_change < -5:
        paths.append({
            "path": "估值锚定传导", "direction": "利空", "strength": "强" if sox_change < -10 else "中",
            "confidence": "高", "trigger": f"SOX月跌{abs(sox_change):.1f}%",
            "logic": "全球科技估值中枢下移 → A股科技估值承压",
            "key_watch": "国产替代/国内流动性是否能形成对冲(脱钩条件)",
        })

    # 路径2: 出口管制传导
    export_controls = policy_data.get("export_controls", [])
    if export_controls:
        latest = export_controls[0]
        paths.append({
            "path": "出口管制传导",
            "direction": "短期利空/中长期利多" if latest.get("scope") == "advanced" else "利空",
            "strength": "强" if latest.get("severity") == "high" else "中",
            "confidence": "高",
            "trigger": latest.get("summary", ""),
            "logic": "管制加码 → 短期供应链风险 + 中长期国产替代加速",
            "elastic_sectors": ["半导体设备", "半导体材料", "EDA"],
            "key_watch": "管制范围是否涉及成熟制程、国内设备验证进度",
        })

    # 路径3: AI capex 传导
    ai_capex = global_data.get("ai_capex_trend", "")
    if ai_capex == "expanding":
        paths.append({
            "path": "AI capex传导", "direction": "利多", "strength": "强",
            "confidence": "高", "trigger": "北美云厂商 capex 持续上调",
            "logic": "AI算力需求↑ → 光模块/服务器/PCB订单↑ → 业绩兑现",
            "elastic_sectors": ["光模块", "AI服务器", "PCB", "散热"],
            "key_watch": "北美云厂商季报 capex 指引、中际旭创/新易盛在手订单",
        })

    # 路径4: 半导体周期传导
    semi_cycle = global_data.get("semi_cycle_position", "")
    cycle_map = {
        "复苏初期": ("利多", "中", "全球半导体销售触底回升 → 设计/封测先行受益"),
        "景气上行": ("利多", "强", "量价齐升 → 全产业链受益"),
        "高位筑顶": ("中性偏空", "中", "增速放缓 → 估值收缩风险"),
        "下行初期": ("利空", "强", "库存积压 → 设计/制造承压"),
        "底部磨底": ("中性", "弱", "方向不明 → 等待右侧信号"),
    }
    if semi_cycle in cycle_map:
        d, s, logic = cycle_map[semi_cycle]
        paths.append({
            "path": "半导体周期传导", "direction": d, "strength": s,
            "confidence": "中", "trigger": f"全球半导体周期: {semi_cycle}",
            "logic": logic,
            "key_watch": "SIA月度销售、DRAM现货价、台积电月度营收",
        })

    # 路径5: 国内产业政策传导
    domestic_policy = policy_data.get("domestic_tech_policy", [])
    if domestic_policy:
        latest = domestic_policy[0]
        paths.append({
            "path": "国内产业政策传导", "direction": "利多",
            "strength": "强" if latest.get("level") in ("国务院", "中央") else "中",
            "confidence": "中",
            "trigger": latest.get("summary", ""),
            "logic": "政策创造需求 → 国产设备/材料导入加速 → 收入增长",
            "elastic_sectors": ["半导体设备(国产化率最低)", "半导体材料"],
            "key_watch": "大基金三期投向、设备招标中标公告",
        })

    return paths
```

---

## Layer 1: 外围股市映射（权重 20%）

### 1.1 全球科技关键指数

| 指数 | 代码 | 覆盖 | 对 A 股硬科技的影响 |
|------|------|------|-------------------|
| **费城半导体** | SOX | 全球 30 大半导体股 | **最强锚** — A 股半导体板块与之相关性最高 |
| **纳斯达克综合** | IXIC | 美国科技股 | 风险偏好指标 — 纳指大跌→全球科技 risk-off |
| **台积电 ADR** | TSM | 全球半导体制造龙头 | 半导体周期最权威信号 |
| **英伟达** | NVDA | AI 算力风向标 | AI 产业链景气度最敏感指标 |
| **日经半导体** | — | 日本半导体设备/材料 | 设备/材料环节的直接对标 |
| **ASML** | ASML | 光刻机垄断者 | 半导体 capex 领先指标 |
| **费城半导体 vs A 股芯片 ETF** | SOX vs 159995 | 相关性监测 | 相关性↑=跟跌跟涨，相关性↓=脱钩 |

### 1.2 外围映射分析

```python
def global_tech_mapping_analysis() -> dict:
    """
    分析外围科技股对 A 股硬科技的映射关系。
    
    ⚠️ 本函数依赖 WebSearch 获取最新指数数据，不可硬编码数值。
    实际执行时使用 WebSearch 搜索各指数最新行情和趋势。
    """
    # 搜索模板（实际执行时使用 WebSearch 工具）:
    # "费城半导体指数 SOX 2026年7月 走势 涨跌幅"
    # "纳斯达克指数 2026年7月 走势 分析"
    # "NVIDIA NVDA 2026年7月 股价 走势"
    # "台积电 ADR TSM 2026年7月 走势"
    # "SOX semiconductor index July 2026 performance"
    # "ASML stock July 2026"

    mapping = {
        "sox": {"name": "费城半导体指数", "value": None, "change_1w": None, "change_1m": None,
                "trend": "", "key_level": "", "a_stock_link": "A股半导体板块最强锚"},
        "nasdaq": {"name": "纳斯达克综合", "value": None, "change_1w": None, "change_1m": None,
                   "trend": "", "a_stock_link": "科技风险偏好指标"},
        "nvda": {"name": "NVIDIA", "value": None, "change_1w": None, "change_1m": None,
                 "trend": "", "a_stock_link": "AI算力产业链景气度"},
        "tsm": {"name": "台积电ADR", "value": None, "change_1w": None, "change_1m": None,
                "trend": "", "a_stock_link": "全球半导体周期权威信号"},
        "asml": {"name": "ASML", "value": None, "change_1w": None, "change_1m": None,
                 "trend": "", "a_stock_link": "半导体capex领先指标"},
    }

    # 综合分析
    return {
        "indices": mapping,
        "analysis_time": "",  # 填入实际时间
    }


def print_global_mapping(analysis: dict):
    """打印外围映射分析"""
    print("=" * 70)
    print("  🌍 维度1: 外围股市映射 (权重20%)")
    print("=" * 70)
    for key, idx in analysis.get("indices", {}).items():
        chg = idx.get("change_1w", 0) or 0
        direction = "🟢" if chg > 0 else "🔴"
        print(f"  {direction} {idx['name']}: 周涨跌={chg:+.2f}% | 趋势={idx.get('trend','')}")
        print(f"     → A股映射: {idx.get('a_stock_link', '')}")

    # 脱钩/挂钩判断
    # 当 SOX 跌但 A 股科技 ETF 不跟跌 → 脱钩信号（国产替代逻辑强化）
```

---

## Layer 2: 全球政策事件（权重 25%）

### 2.1 出口管制/技术封锁监测框架

```python
# 出口管制关键监测维度
EXPORT_CONTROL_MONITOR = {
    "美国BIS实体清单": {
        "最新动态": "WebSearch: 'BIS entity list China semiconductor 2026-07'",
        "影响范围": "新增企业数量、是否涉及关键环节(设备/制造/设计)",
        "A股传导": "被列入→短期利空(供应链风险)、未列入的国产替代标的→中期利好",
    },
    "荷兰/日本设备管制": {
        "最新动态": "WebSearch: '荷兰日本 半导体设备 出口管制 2026'",
        "影响范围": "光刻机(ASML)/刻蚀(TEL)/沉积设备是否进一步受限",
        "A股传导": "管制加码→国产设备导入加速、管制放松→竞争压力增大",
    },
    "先进计算芯片管制": {
        "最新动态": "WebSearch: 'US AI chip export control China 2026'",
        "影响范围": "NVIDIA H/B系列、AMD MI系列是否进一步受限",
        "A股传导": "管制加码→国产AI芯片(寒武纪/海光)替代逻辑强化",
    },
    "EDA软件管制": {
        "最新动态": "WebSearch: 'EDA software export control China 2026'",
        "影响范围": "GAA/先进制程EDA是否被禁",
        "A股传导": "管制加码→国产EDA(华大九天/概伦电子)关注度提升",
    },
}

# 国内产业政策监测框架
DOMESTIC_POLICY_MONITOR = {
    "大基金": {
        "最新动态": "WebSearch: '国家大基金 三期 2026'",
        "影响": "大基金投资方向=政策最重视环节、实际投资金额=落地速度",
    },
    "集成电路政策": {
        "最新动态": "WebSearch: '集成电路 增值税 企业所得税 优惠政策 2026'",
        "影响": "税率优惠→直接增厚利润、覆盖面变化→受益范围变化",
    },
    "首台套/采购政策": {
        "最新动态": "WebSearch: '首台套 国产设备 采购 政策 2026'",
        "影响": "政府采购/央企采购国产化率要求→直接创造需求",
    },
}
```

### 2.2 政策冲击量化

```python
def quantify_policy_impact(policy_events: list) -> dict:
    """
    量化全球政策对 A 股硬科技各子板块的冲击方向和程度。
    
    policy_events: 来自 policy-event-tracker 的输出 + WebSearch 补充的全球政策
    返回: {sub_sector: {direction, magnitude, logic, confidence}}
    """
    SUB_SECTORS = ["半导体设备", "半导体材料", "半导体制造", "芯片设计",
                   "AI算力", "光模块", "高端制造", "新材料", "航空航天"]

    impact = {}
    for sector in SUB_SECTORS:
        # 初始化
        score = 0  # 正=利好，负=利空
        logics = []

        # 对每个政策事件评估对该子板块的影响
        for event in policy_events:
            event_sector_impact = _assess_event_sector_impact(event, sector)
            score += event_sector_impact.get("score", 0)
            if event_sector_impact.get("logic"):
                logics.append(event_sector_impact["logic"])

        direction = "🟢强利好" if score >= 2 else ("🟡弱利好" if score > 0 else
                   ("🔴强利空" if score <= -2 else ("🟠弱利空" if score < 0 else "⚪中性")))

        impact[sector] = {
            "direction": direction, "score": score,
            "logics": logics,
            "confidence": "高" if abs(score) >= 2 else "中",
        }

    return impact


def _assess_event_sector_impact(event: dict, sector: str) -> dict:
    """
    评估单个政策事件对特定子板块的影响。
    需结合事件的具体内容（管制范围、政策层级、影响环节）判断。
    
    ⚠️ 这是分析框架，实际执行时需要基于事件的真实内容做判断，
    不可模板化套用。以下为分析逻辑参考。
    """
    # 分析逻辑（示意，执行时需替换为真实推理）:
    # 1. 出口管制涉及先进制程设备 → 半导体设备: score+1(国产替代)
    # 2. 出口管制涉及成熟制程 → 半导体制造: score-1(直接冲击)
    # 3. 国内大基金投资设备 → 半导体设备: score+2(直接利好)
    # 4. AI芯片管制加码 → AI算力: score-1(短期), score+1(长期国产替代)
    # ...
    return {"score": 0, "logic": ""}
```

---

## Layer 3: 产业链趋势（权重 25%）

### 3.1 调用 serenity-skill + moat-hunter

本维度通过调用 serenity-skill（产业链瓶颈定位）和 moat-hunter（企业壁垒验证），回答三个核心问题：

1. **全球科技产业链中，哪个环节最紧张？** → 调用 serenity-skill
2. **A 股在哪个环节有真正的竞争力？** → 调用 moat-hunter
3. **供需缺口在扩大还是收敛？** → 全球产能数据 + A 股公司订单/合同负债

```python
def industry_chain_analysis() -> dict:
    """
    产业链趋势分析 —— 调用 serenity-skill + moat-hunter + WebSearch。
    
    分析流程:
    1. 调用 serenity-skill 定位全球硬科技产业链稀缺环节
    2. 调用 moat-hunter 验证 A 股公司在稀缺环节的不可替代性
    3. WebSearch 搜索全球产能/订单/ capex 数据
    4. 交叉验证形成产业链研判
    """
    return {
        "scarce_layers": [],       # 来自 serenity-skill: 全球产业链稀缺环节排名
        "a_stock_position": [],    # 来自 moat-hunter: A股在各环节的不可替代性评级
        "supply_demand_gap": [],   # 来自 WebSearch: 全球供需缺口数据
        "tech_route_changes": [],  # 技术路线变化(如 Chiplet/硅光/玻璃基板)
        "verdict": "",             # 综合产业链研判
    }
```

### 3.2 全球半导体周期位置判断

```python
# 半导体周期关键指标
SEMI_CYCLE_INDICATORS = {
    "leading": {  # 领先指标（3-6个月提前）
        "北美半导体设备出货额": "WebSearch: 'North America semiconductor equipment billings 2026'",
        "台积电 capex 指引": "WebSearch: 'TSMC capex 2026 guidance'",
        "DRAM 现货价": "WebSearch: 'DRAM DDR5 spot price 2026'",
    },
    "coincident": {  # 同步指标
        "全球半导体销售额": "WebSearch: 'SIA global semiconductor sales June 2026'",
        "台积电月度营收": "WebSearch: 'TSMC June 2026 revenue'",
        "晶圆厂产能利用率": "WebSearch: 'semiconductor fab utilization rate 2026'",
    },
    "lagging": {  # 滞后指标
        "半导体公司库存天数": "WebSearch: 'semiconductor inventory days 2026'",
        "封测厂营收": "WebSearch: 'OSAT revenue 2026'",
    },
}


def determine_semi_cycle_position(indicators: dict) -> dict:
    """
    基于领先/同步/滞后指标判断全球半导体周期位置。
    
    周期位置: 复苏初期 / 景气上行 / 高位筑顶 / 下行初期 / 底部磨底
    """
    # 判断逻辑:
    # 复苏初期: 领先指标↑ + 同步指标企稳 + 滞后指标仍弱
    # 景气上行: 领先↑ + 同步↑ + 滞后开始改善
    # 高位筑顶: 领先开始走弱 + 同步仍在高位 + 滞后仍在改善
    # 下行初期: 领先↓ + 同步开始↓ + 滞后仍好
    # 底部磨底: 领先企稳 + 同步底部 + 滞后仍差

    return {
        "position": "",        # 周期位置
        "leading_signals": [], # 领先信号
        "confidence": "",      # 置信度
        "a_stock_implication": "", # 对A股硬科技的启示
    }
```

---

## Layer 4: A 股资金面（权重 15%）

### 4.1 科技板块资金流向

```python
def tech_sector_capital_flow_analysis() -> dict:
    """
    A股硬科技板块资金流向分析。
    调用 capital-flow-tracker + etf-fund-flow-tracker。
    
    分析内容:
    1. 硬科技概念板块资金流排名（capital-flow-tracker §1.1 概念板块）
    2. 核心科技 ETF 资金流（etf-fund-flow-tracker §2.3 核心池扫描）
    3. 科创50/芯片/半导体 ETF 多周期资金流
    """
    # 关键 ETF 代码:
    # 588000 科创50ETF — 硬科技整体风向标
    # 159995 芯片ETF — 芯片产业链
    # 512480 半导体ETF — 半导体
    # 588200 科创芯片ETF — 科创板芯片
    # 516160 新能源ETF — 新能源(对比参考)

    return {
        "tech_sector_flow": {},      # 科技板块资金流入/流出排名
        "tech_etf_flow": {},         # 科技ETF资金流多周期
        "institutional_intent": "",  # 机构配置意图(增配/减配)
        "incremental_signal": "",    # 增量资金信号
    }
```

### 4.2 科技资金面与全市场对比

```python
def tech_vs_market_capital_flow() -> dict:
    """
    科技板块资金流 vs 全市场资金流对比。
    
    关键判断:
    - 科技流入 > 全市场平均 → 资金在向科技集中(超配信号)
    - 科技流入 < 全市场平均 → 资金在从科技流出(低配信号)
    - 科技ETF持续申购 + 板块资金流入 → 机构+散户共识(最强信号)
    """
    return {}
```

---

## Layer 5: A 股情绪面（权重 10%）

### 5.1 科技涨停情绪

```python
def tech_sentiment_analysis() -> dict:
    """
    A股硬科技情绪面分析。
    调用 limit-up-tracker + industry-sentiment-tracker。
    
    分析内容:
    1. 科技板块涨停数/占比（limit-up-tracker 行业/概念涨停排名）
    2. 科技连板高度（最高标的是几板、什么方向）
    3. 科技行业情绪指数（industry-sentiment-tracker 五维度加权）
    4. 情绪极端检测（过热 >80 / 冰点 <20）
    """
    # industry-sentiment-tracker 的科技相关行业:
    # - 半导体(设备/材料/存储/CPU/通信/芯片等细分方向)
    # - 算力/AI
    # - 高端制造/机器人

    return {
        "tech_limit_up_count": 0,
        "tech_limit_up_ratio": 0,       # 科技涨停占全市场比例
        "max_consecutive_boards": 0,     # 科技最高连板
        "tech_sentiment_score": 50,      # 科技行业情绪分(0-100)
        "sentiment_signal": "",          # 过热/偏热/正常/偏冷/冰点
        "sentiment_trend": "",           # 情绪趋势(上升/下降/持平)
    }
```

### 5.2 情绪与资金背离检测

| 场景 | 资金面 | 情绪面 | 信号含义 |
|------|--------|--------|---------|
| 机构布局期 | ETF 持续流入 | 涨停稀少、情绪低迷 | 机构悄悄吸筹，蓄力阶段 |
| 共识上涨期 | ETF 流入 + 板块流入 | 涨停活跃、情绪高涨 | 多方共振，趋势健康 |
| 游资炒作期 | ETF 流出/持平 | 涨停活跃、情绪过热 | 游资主导，机构撤退(风险) |
| 全面退潮期 | ETF 流出 + 板块流出 | 涨停稀少、情绪冰点 | 全面撤退，等待企稳 |

---

## Layer 6: 业绩验证（权重 5%）

```python
def tech_earnings_verification() -> dict:
    """
    硬科技业绩验证 —— 调用 earnings-tracker。
    
    分析内容:
    1. 硬科技标的业绩预告方向统计(预增/预减/扭亏/首亏等)
    2. 超预期 vs 低预期比例
    3. 关键公司合同负债趋势(半导体设备最重要的领先指标)
    4. 营收/利润拐点信号
    """
    # 关键观察:
    # 半导体设备: 合同负债增速(领先收入1-2季度)
    # 芯片设计: 毛利率趋势(涨价能力)
    # 光模块: 在手订单/800G/1.6T出货量
    # 制造/封测: 产能利用率

    return {
        "earnings_direction": {},    # 业绩方向统计
        "beat_ratio": 0,            # 超预期比例
        "contract_liability_trend": "", # 合同负债趋势
        "revenue_profit_inflection": [], # 拐点信号
    }
```

---

## 综合研判输出

### 六维共振评分

```python
def hard_tech_composite_score(dimensions: dict) -> dict:
    """
    六维度加权综合评分 (1-10分)。
    
    评分规则:
    - 每个维度方向: bullish=+1, bearish=-1, neutral=0
    - 乘以该维度权重 → 加权分
    - 所有维度加权分求和 → 映射到 1-10 分
    
    1-3分: 看空    (🔴 全面撤退)
    4-5分: 偏空    (🟠 防御为主)
    6-7分: 中性    (🟡 结构机会)
    8-9分: 偏多    (🟢 积极参与)
    10分:  看多    (🚀 全力做多，极少出现)
    """
    WEIGHTS = {
        "global_mapping": 0.20,   # 外围映射
        "global_policy":  0.25,   # 全球政策
        "industry_chain": 0.25,   # 产业链趋势
        "capital_flow":   0.15,   # A股资金
        "sentiment":      0.10,   # A股情绪
        "earnings":       0.05,   # 业绩验证
    }

    total_score = 5.0  # 中性基准
    for dim, weight in WEIGHTS.items():
        dim_data = dimensions.get(dim, {})
        direction = dim_data.get("direction", "neutral")
        strength = dim_data.get("strength", 0)  # 0-1 信号强度
        if direction == "bullish":
            total_score += weight * 10 * strength
        elif direction == "bearish":
            total_score -= weight * 10 * strength

    total_score = max(1, min(10, round(total_score, 1)))

    # 共识度 = 同向维度数 / 有效维度数
    directions = [
        dimensions.get(d, {}).get("direction", "neutral")
        for d in WEIGHTS
    ]
    bull_count = sum(1 for d in directions if d == "bullish")
    bear_count = sum(1 for d in directions if d == "bearish")
    total_dims = len([d for d in directions if d != "neutral"])
    consensus = max(bull_count, bear_count) / max(total_dims, 1) if total_dims > 0 else 0

    verdict = ""
    if total_score >= 8 and consensus >= 0.67:
        verdict = "🟢 多维共振看多 — 外部+政策+产业链+资金+情绪同向，置信度高"
    elif total_score >= 7:
        verdict = "🟡 偏多 — 多数维度积极，关注分歧维度的风险"
    elif total_score >= 5:
        verdict = "➖ 方向不明确 — 多空交织，结构性机会为主"
    elif total_score >= 3:
        verdict = "🟠 偏空 — 多数维度消极，控制仓位等待转机"
    else:
        verdict = "🔴 多维共振看空 — 外部+政策+产业链+资金+情绪全面偏空"

    return {
        "score": total_score,
        "verdict": verdict,
        "consensus": f"{max(bull_count, bear_count)}/{total_dims}维同向",
        "bull_dimensions": [d for d in WEIGHTS if dimensions.get(d, {}).get("direction") == "bullish"],
        "bear_dimensions": [d for d in WEIGHTS if dimensions.get(d, {}).get("direction") == "bearish"],
    }
```

### 子板块优先级排序

```python
def rank_sub_sectors(dimensions: dict) -> list[dict]:
    """
    基于六维数据对五大硬科技子板块排序。
    
    排序因子:
    1. 产业链稀缺性 (serenity-skill输出)
    2. 政策利好程度 (政策冲击量化)
    3. 资金流入强度 (capital-flow-tracker)
    4. 业绩确定性 (earnings-tracker)
    5. 外部映射弹性 (外围相关性)
    """
    SUB_SECTORS = [
        {"name": "半导体设备/材料", "key": "semi_equipment"},
        {"name": "AI算力/光模块", "key": "ai_computing"},
        {"name": "高端制造/机器人", "key": "advanced_mfg"},
        {"name": "芯片设计", "key": "chip_design"},
        {"name": "航空航天/卫星", "key": "aerospace"},
    ]

    # 各维度打分 (示意，实际基于真实数据)
    ranked = []
    for sector in SUB_SECTORS:
        ranked.append({
            "name": sector["name"],
            "priority": "",     # 🥇🥈🥉 or 观望
            "score": 0,         # 综合评分
            "key_logic": "",    # 核心理由
            "risk": "",         # 主要风险
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked
```

---

## 研判报告模板

### 标准输出格式

执行硬科技走势研判时，按以下模板输出完整报告：

```markdown
## 🛰️ A股硬科技走势研判报告

**研判时间**：YYYY-MM-DD HH:MM
**综合评分**：X.X / 10
**方向判断**：🟢看多 / 🟡偏多 / ➖中性 / 🟠偏空 / 🔴看空
**置信度**：高 / 中 / 低（X/6 维度同向）

---

### 📊 六维雷达

| 维度 | 方向 | 强度 | 核心信号 |
|------|------|------|---------|
| 🌍 外围映射 | | | |
| 📰 全球政策 | | | |
| 🔗 产业链 | | | |
| 💰 A股资金 | | | |
| 📈 A股情绪 | | | |
| 📊 业绩验证 | | | |

---

### 🔗 关键传导路径

1. **路径X（方向，强度，置信度）**：核心逻辑...
2. ...

---

### 🎯 子板块优先级

| 优先级 | 子板块 | 核心理由 | 主要风险 |
|--------|--------|---------|---------|
| 🥇 | | | |
| 🥈 | | | |
| 🥉 | | | |
| ⏸️ 观望 | | | |

---

### ⚠️ 风险矩阵

| 风险 | 触发条件 | 影响程度 | 当前概率 | 前置信号 |
|------|---------|---------|---------|---------|
| | | | | |

---

### 🔍 关键观察指标（未来 1-4 周）

1. ...
2. ...
3. ...

---

### 📝 情景推演

**基准情景（概率 ~XX%）**：
**乐观情景（概率 ~XX%）**：
**悲观情景（概率 ~XX%）**：

---

⚠️ 研究声明：本报告基于公开数据和多方交叉验证，所有结论均为研究框架产出，不构成投资建议。硬科技受多重因素影响（全球政策/技术路线/产业周期），单一研判无法覆盖所有尾部风险。
```

---

## 执行流程

```
硬科技走势研判执行清单：
- [ ] Step 1: 外围映射 — WebSearch 拉取SOX/纳指/NVDA/TSM/ASML最新走势
- [ ] Step 2: 全球政策 — 调用 policy-event-tracker + WebSearch 搜索出口管制/产业政策
- [ ] Step 3: 产业链 — 调用 serenity-skill 定位稀缺环节 + moat-hunter 验证A股卡位
- [ ] Step 4: A股资金 — 调用 capital-flow-tracker(科技概念板块) + etf-fund-flow-tracker(科技ETF)
- [ ] Step 5: A股情绪 — 调用 limit-up-tracker(科技涨停) + industry-sentiment-tracker(科技情绪分)
- [ ] Step 6: 业绩验证 — 调用 earnings-tracker(硬科技标的业绩扫描)
- [ ] Step 7: 传导分析 — 运行 5 条传导路径状态分析
- [ ] Step 8: 综合评分 — 六维加权评分 + 子板块排序
- [ ] Step 9: 输出报告 — 按研判报告模板输出 + 风险矩阵 + 情景推演
- [ ] Step 10: 保存报告 — 输出到 src/宏观经济/YYYY-MM-DD-硬科技走势研判/
```

---

## 常用场景速查

| 用户问法 | 聚焦维度 | 深度 |
|---------|---------|------|
| "硬科技现在怎么看" | 六维全扫描 | 标准 |
| "美股科技大跌对A股半导体影响" | 外围映射(40%) + 全球政策(30%) + A股资金(20%) | 深度 |
| "新的出口管制出来了吗，利好哪些" | 全球政策(50%) + 产业链(30%) + 资金(20%) | 深度 |
| "半导体周期现在什么位置" | 产业链(50%) + 外围映射(30%) + 业绩验证(20%) | 深度 |
| "科技赛道哪些方向最值得看" | 六维全扫描 + 子板块深度排序 | 深度 |
| "科技股涨了很多，还能追吗" | 情绪面(30%) + 资金面(25%) + 外围映射(20%) + 风险矩阵 | 标准 |

---

## 与其他 Skill 的协作

| 协作方 | 调用时机 | 获取内容 |
|--------|---------|---------|
| **policy-event-tracker** | Step 2 | 近一周政策事件 + 未来事件日历 + 影响分析 |
| **serenity-skill** | Step 3 | 硬科技产业链稀缺环节排名 + 候选标的池 |
| **moat-hunter** | Step 3 | 候选标的的不可替代性评级 + 供需验证 |
| **capital-flow-tracker** | Step 4 | 硬科技概念板块资金流 + 板块内个股TOP10 + 龙虎榜 |
| **etf-fund-flow-tracker** | Step 4 | 科创50/芯片/半导体ETF多周期资金流 + 风格判断 |
| **limit-up-tracker** | Step 5 | 科技行业涨停统计 + 连板高度 + 板块涨停潮 |
| **industry-sentiment-tracker** | Step 5 | 半导体/AI等科技行业情绪指数(0-100) + 趋势 |
| **earnings-tracker** | Step 6 | 硬科技标的业绩预告方向 + 超预期比例 + 合同负债 |
| **a-stock-data** | 按需 | 个股行情/估值/研报/公告等底层数据 |
| **stock-pick** | 研判后 | 基于本skill的子板块优先级，聚焦选股 |

---

## 风险声明

- 硬科技走势受全球政治（出口管制/技术封锁/地缘冲突）、技术路线变革（如 Chiplet 替代 SoC）、产业周期（半导体周期/资本开支周期）多重因素影响，单一研判框架无法覆盖所有尾部风险
- 外围映射分析基于历史相关性，脱钩/挂钩关系可能随时变化
- 政策分析基于公开信息，未公开的政策讨论不在分析范围内
- 所有评分和方向判断均为研究框架产出，不构成投资建议
- 建议至少每周更新一次研判，重大事件（新出口管制/大政策/财报季）后立即更新
