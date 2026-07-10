# CLAUDE.md

本文件为 Claude Code 在此项目中工作时提供指导。

## 项目定位

**投资研究与分析平台** — 基于产业链瓶颈方法论，对投资主题进行可行性、收益和风险分析。

**核心原则**：
- **风险优先**：先看风险，再看机遇。亏损的数学是不对称的（亏 50% 需涨 100% 回本）
- **数据驱动**：所有结论基于可验证的公开数据，不做无来源推测
- **闭环迭代**：初始研判 → 假设设定 → 跟踪验证 → 复盘修正

**研究边界**（严禁越线）：
- ✅ 提供：研究优先级、证据分析、产业链推理、风险下行评估、情景推演和时机参考条件
- ❌ 严禁：明确买卖指令、承诺收益、精确价格预测、低流动性炒作、依赖传闻/匿名来源、编造数据
- ⚠️ 情景推演中的"参考区间"是研究框架产出，不是精确预测；"参考条件"不是交易指令

## 风险优先原则

**风险分析铁律**（每条风险必须满足）：
- 绑定具体触发条件（"当 X 发生时，风险 Y 兑现"），禁止"市场风险"等空泛表述
- 覆盖 5 层：宏观 / 政策 / 产业链 / 公司 / 市场行为
- 标注：影响程度（颠覆/重度/中度/轻度）+ 当前概率与依据 + 前置信号
- 风险交互分析：2 个以上风险同时兑现最危险

**流程位置**：风险映射 → 物理约束检查 → 产业链分析 → 机遇判断 → 候选筛选（每次季报后定期刷新）

**风险地图**：见 `src/_templates/risk-map.md`（每季度更新，每次新分析必须先对照）

## 多维分析框架

### 纵向：宏观 → 中观 → 微观

三层信号同向共振 → 最高置信度。单层信号仅作线索。

```
宏观（经济周期/政策/地缘/流动性）→ 中观（产业链稀缺层/行业格局/技术路线）→ 微观（公司估值/在手订单/合同负债/财务质量）
```

### 横向：基本面 → 估值 → 技术 → 资金

四维交叉验证规则：
- 基本面↑ + 估值合理 + 技术↑ + 资金↑ → 置信度最高
- 基本面↑ + 估值偏高 + 技术↓ + 资金↓ → 入场时机问题，等待技术修复
- 基本面↑ + 估值合理 + 技术↓ + 资金↓ → 可能错杀，但不逆势，等待转强

**常见背离信号**：
- 基本面改善但北向持续流出 → 可能有未知风险
- 技术面走好但融资余额异常高 → 杠杆驱动不牢固
- 估值低但技术面持续走弱 → 可能有基本面恶化先行信息

> 技术面/估值面详细参考框架见 `src/_templates/scenario-analysis.md`

## 数据与来源要求

**引用规范**：每个关键声称标注来源（文件+章节+日期），区分"事实"与"推测"，数据不足时说"待验证"。

| 等级 | 证据强度 | 来源类型 | 用途 |
|------|---------|---------|------|
| **一级** | Strong | 交易所公告/年报季报/官方政策文件/官方订单/专利/标准/电话会记录 | 高置信度结论，可直接引用 |
| **二级** | Medium | 券商研报/行业白皮书/权威媒体/公司 IR/协会数据 | 可交叉验证，不可单独驱动强结论 |
| **严禁** | Weak/不可用 | 社交媒体/论坛/KOL/匿名来源/AI 生成内容 | 仅作线索，不可引用 |

**二级来源必须**：核实发布者身份 → 尝试一级来源交叉验证 → 标注"已验证/待验证"。

> 完整白名单见 `src/_templates/authoritative-sources.md`

## 核心方法论

### 十五技能协作架构

```
a-stock-data（数据获取层）
    │
    ├── policy-event-tracker（事件催化层）    → "最近有什么催化剂"
    ├── serenity-skill（产业链瓶颈层）        → "哪个环节最稀缺"
    ├── moat-hunter（企业壁垒验证层）         → "谁真正卡住了瓶颈"
    ├── cross-sector-ma-tracker（跨界并购筛选层） → "哪些传统企业在跨界科技"
    ├── old-guard-stocks（质量+错杀筛选层）    → "哪些好公司被错杀了"
    ├── earnings-tracker（业绩追踪层）         → "业绩好不好，有没有超预期"
    ├── capital-flow-tracker（资金流向追踪层）  → "资金在往哪流"
    ├── etf-fund-flow-tracker（ETF资金走势层）  → "ETF资金在流向哪"
    ├── limit-up-tracker（涨停板情绪层）       → "市场在追捧什么"
    ├── industry-sentiment-tracker（行业情绪聚合层） → "各行业情绪是热还是冷"
    ├── fund-flow-predictor（买入安全区间研判层） → "现在能不能买、安不安全、该不该卖"
    └── stock-pick（选股层）                 → "具体选哪只"

hard-tech-dashboard（硬科技研判合成层）← 消费以上全部 skill 输出
    → "硬科技现在能不能做、做哪个方向、风险在哪里"

quant-dashboard（全市场量化研判顶层 ★V2.0）← 消费全部下层 skill + 内置30+条历史规律
    → "全市场怎么看、该入场还是离场、风险在哪里"
```

| 维度 | a-stock-data | policy-event-tracker | serenity-skill | moat-hunter | cross-sector-ma-tracker | old-guard-stocks | earnings-tracker | capital-flow-tracker | etf-fund-flow-tracker | limit-up-tracker | industry-sentiment-tracker | fund-flow-predictor | hard-tech-dashboard | stock-pick |
|------|-------------|---------------------|---------------|-------------|------------------------|-----------------|-----------------|---------------------|----------------------|------------------|---------------------------|--------------------|--------------------|------------|
| 职责 | 数据获取与清洗 | 政策事件追踪与影响分析 | 产业链基本面分析 | 企业不可替代性验证 | 传统企业跨界科技并购追踪 | 质量价值筛选+错杀识别 | 业绩预告+财务指标+拐点识别+超预期分析 | 资金流向监控+个股涨跌归因 | ETF资金流+风格判断+盘面分析 | 涨停板复盘+板块情绪分析 | 行业情绪聚合+五维加权+趋势追踪 | 买入安全区间研判+企稳确认+买卖时机参考 | 六维合成研判(外围+政策+产业链+资金+情绪+业绩) | 多策略选股筛选 |
| 输入 | 股票代码 / 查询条件 | 时间窗口 / 行业关键词 | 产业链知识 + 财报/公告 | 目标公司 + 产业链位置 | 时间窗口 / 传统行业范围 / 科技方向 | 行业范围 + 财报/估值数据 | 股票代码 / 报告期 / 行业 | 概念板块/行业板块/龙虎榜 | 宽基/行业/主题ETF代码 | 日期 / 市场板块 | 行业→概念板块映射表 | 股票代码/概念板块/ETF + 30天盘面数据 | 8个skill输出 + 外围股市 + 全球政策 | 全市场/板块行情数据 |
| 输出 | 结构化行情/估值/资金/研报/公告数据 | 按重要性排序的事件+行业/标的映射 | 稀缺层判断 + 标的优先级 | 不可替代性评级(S/A/B/C) + 供需验证 | S/A/B/C四级跨界信号清单 + 重点案例深度分析 | 老登股清单(核心/优质/观察) + 错杀程度评分 | 业绩预告全类型+财务序列+拐点信号+超预期幅度 | 板块资金流排名+三方资金分类+个股归因 | ETF全景报告+风格判断+行业轮动+多维交叉验证 | 涨停全景报告+行业/概念排名+炸板分析+封板强度+连板追踪 | 三级情绪指数(全市场/行业/细分方向)+热力图+信号检测 | 0-100安全评分+企稳确认清单+买入/离场参考条件+15条可验证规则 | 六维雷达+综合评分(1-10)+传导路径+子板块优先级+风险矩阵 | 通过/拒绝分层清单 |
| **quant-dashboard** | **全市场量化研判(五层引擎+动态权重+30+条历史规律)** | **全部下层skill输出+实时行情+ETF+消息** | **综合评分(0-10)+风格+行业排序+入场/离场参考条件+风险预警** | — | — | — | — | — | — | — | — | — | — | — |

### 各 Skill 说明

- **a-stock-data**：7 层 / 27 端点，覆盖行情→研报→信号→资金→新闻→基础数据→公告。触发词："查数据""行情""研报""公告""资金流"。详见 `.claude/skills/a-stock-data/SKILL.md`
  - 数据源优先级（防封）：① mootdx+腾讯（不封 IP）② 同花顺/新浪/巨潮 ③ 东财（仅独有数据，已内置限流）
- **serenity-skill**：产业链瓶颈猎人方法。触发词："产业链""瓶颈""稀缺层""深度调研""用 Serenity 的方式看"。详见 `.claude/skills/serenity-skill/SKILL.md`
- **moat-hunter**：产业链不可替代性分析——识别在产业链关键环节中具备稀缺性、壁垒和不可替代性的企业，验证供需关系。触发词："护城河分析""稀缺性分析""不可替代""产业链卡位""竞争壁垒""供需关系验证""订单/产能/毛利率验证"。详见 `.claude/skills/moat-hunter/SKILL.md`
- **policy-event-tracker**：政策事件追踪与影响分析，按重要性排序。触发词："最近有什么政策""这周有什么大事""市场催化剂""事件驱动""政策影响"。详见 `.claude/skills/policy-event-tracker/SKILL.md`
- **cross-sector-ma-tracker**：传统企业跨界科技并购追踪——多信号融合（公告+新闻+研报+Web），S/A/B/C 四级信号分级，识别传统行业企业向科技/新能源领域的收购、重组、投资行为。触发词："跨界并购""传统企业转型科技""收购科技公司""重组转型""跨界投资""传统行业+科技标的""产业转型升级"。详见 `.claude/skills/cross-sector-ma-tracker/SKILL.md`
- **old-guard-stocks**：老登股筛选——寻找持续盈利不亏损、有护城河、但估值被错杀的优质公司。核心逻辑："好公司遇到了坏价格"。触发词："老登股""蓝筹筛选""行业龙头筛选""被错杀的龙头""好公司低估值""质量价值筛选"。详见 `.claude/skills/old-guard-stocks/SKILL.md`
- **capital-flow-tracker**：A股全市场资金流向追踪——概念板块+行业板块双维度，10个时间周期，机构/游资/散户三方资金分类，龙虎榜席位分析，个股涨跌归因。触发词："资金流向""主力资金""板块轮动""机构动向""游资""龙虎榜""为什么涨""为什么跌""归因分析"。详见 `.claude/skills/capital-flow-tracker/SKILL.md`
- **etf-fund-flow-tracker**：A股ETF资金走势追踪——覆盖宽基/行业/主题/策略/债券/跨境/商品七大类ETF，多周期资金流聚合，宽基风格判断(大盘vs中小盘/成长vs价值)，行业ETF轮动信号，增量资金检测，与capital-flow-tracker/limit-up-tracker/policy-event-tracker多维交叉验证盘面分析。触发词："ETF""ETF资金流""宽基ETF""行业ETF""ETF轮动""大盘风向""市场风格""增量资金""盘面分析"。详见 `.claude/skills/etf-fund-flow-tracker/SKILL.md`
- **limit-up-tracker**：A股涨停板全维度追踪——覆盖今日/昨日/前天涨停股票，分析涨停时间、炸板次数、封板金额、连板数、所属行业与概念、行业/概念涨停数排名，支持多日趋势对比与板块爆发检测。触发词："涨停""涨停板""炸板""封板""连板""涨停潮""涨停复盘""打板""题材热点""板块涨停""首板""二板""高标"。详见 `.claude/skills/limit-up-tracker/SKILL.md`
- **earnings-tracker**：A股业绩全景追踪——覆盖业绩预告(预增/预减/扭亏/首亏等9类)、业绩报表(单季/累计多期对比)、F10主要财务指标(80+字段含全量增长率)、业绩拐点识别(营收+利润双拐点)、实际vs一致预期差异分析。触发词："业绩""业绩预告""预增""财报""季报""EPS""净利润""营收""ROE""超预期""业绩拐点""业绩对比"。详见 `.claude/skills/earnings-tracker/SKILL.md`
- **industry-sentiment-tracker**：A股行业情绪指数追踪——覆盖全市场/8大行业/细分方向三级情绪指数，五维度加权合成(资金面25%+价格面20%+宽度面20%+量能面15%+涨停面20%)，输出0-100量化情绪分，支持情绪趋势追踪和极端信号检测。与capital-flow-tracker/limit-up-tracker/etf-fund-flow-tracker多维交叉验证。触发词："情绪指数""行业情绪""市场情绪""情绪温度""半导体情绪""板块热度""市场热度"。详见 `.claude/skills/industry-sentiment-tracker/SKILL.md`
- **hard-tech-dashboard**：A股硬科技走势综合研判仪表盘——整合六维数据(外围股市映射/全球政策事件/产业链趋势/A股资金面/A股情绪面/业绩验证)，输出硬科技板块全景研判报告（综合评分1-10分 + 5条传导路径 + 5大子板块优先级排序 + 风险矩阵）。触发词："硬科技""科技板块走势""半导体/AI/芯片 行情研判""国产替代 机会""科技股 还能不能涨""全球科技 对A股影响""费城半导体/纳指 对A股科技影响""科技赛道 配置"。详见 `.claude/skills/hard-tech-dashboard/SKILL.md`
- **quant-dashboard** ★V2.0：全市场量化综合研判仪表盘——五层量化引擎(市场状态识别→动态权重分配→六维评分修正→跷跷板检测→综合评分+时机参考)，内置30+条历史统计规律(每条标注触发条件+历史胜率+来源)，实时拉取行情(腾讯API)+ETF资金流+具备实质影响的关键消息。核心创新：①四类市场状态 × 四套动态权重矩阵 ②事件S/A/B/C四级分级，S级可覆盖基本面约束 ③外围映射×前期涨跌幅脱钩修正(差>15%→脱钩) ④资金跷跷板+高低切换检测。输出：综合评分(0-10)+风格判断(进攻/防御/均衡/切换)+行业优先级排序(5档)+入场/离场参考条件+风险预警清单。**2026-07-10 全行业18标的实盘验证驱动开发**。触发词："市场怎么看""入场""离场""仓位建议""风格切换""高低切换""风险预警""为什么跌""还能不能涨""行业排序"。详见 `.claude/skills/quant-dashboard/SKILL.md`
- **stock-pick**：LLM 驱动多策略选股，7 阶段流水线。触发词："选股""筛选""帮我找"。详见 `.claude/skills/stock-pick/SKILL.md`
- **fund-flow-predictor**：买入安全区间研判器——拉取近30天全维度盘面数据（资金流向+涨跌幅+情绪+消息+融资融券+北向+大宗交易+股东户数+解禁），输出0-100安全评分+企稳确认+买入/离场参考条件。核心原则：可以少挣，必须少亏。触发词："能不能买""企稳了吗""安全吗""什么时候入场""要不要卖""离场""风险大不大""回调到位了吗"。详见 `.claude/skills/fund-flow-predictor/SKILL.md`
- **clean-old-analysis**：旧分析目录清理——安全清理 `src/` 下超过指定天数的旧分析目录，dry-run 预览后确认删除。触发词："清理旧分析""删除旧报告""清理目录""释放空间"。详见 `.claude/skills/clean-old-analysis/SKILL.md`

### 完整分析流程

```
Phase 1: 风险映射（risk-register.md，对照 risk-map.md）
    ↓
Phase 2: 产业链分析（调用 serenity-skill，定位稀缺环节）
    ↓
Phase 3: 企业壁垒验证（调用 moat-hunter，验证候选公司的不可替代性）
    ↓
Phase 4: 机遇判断（opportunity-register.md）
    ↓
Phase 5: 候选筛选 + 估值分析（comparison.md，用 a-stock-data 拉取实时数据）
    ↓
Phase 6: 情景推演 + 时机参考（scenario-analysis.md，整合基本面+资金面+情绪面+ETF资金流，调用 capital-flow-tracker + etf-fund-flow-tracker + industry-sentiment-tracker；若聚焦硬科技方向，调用 hard-tech-dashboard 进行六维综合研判）
    ↓
Phase 7: 假设设定（hypothesis-register.md）
    ↓
Phase 8: 跟踪验证（tracking-indicators.md + evidence-tracker.md）
    ↓
Phase 9: 复盘修正（review-loop.md）→ 回到 Phase 1
```

### 物理世界约束

- **认证/导入周期**：半导体设备 12-24 月、材料 6-18 月、汽车电子 24-36 月
- **扩产周期**：晶圆厂 2-3 年、封测厂 1-2 年、材料产能 12-24 月
- **上下游传导时滞**：下游 capex → 设备订单 3-6 月 → 设备收入 3-6 月 → 材料消耗 6-12 月
- **合同负债领先收入 1-2 季**（A 股最重要的领先指标之一）

> 详细数据参考 `src/_templates/physical-constraints.md`

## 目录结构

按**行业 → 方向 → 日期**三级组织，行业目录按需创建（新增分析时 `mkdir -p`）。

### `src/` 分析文档

```
src/
├── _index.md                    # 根导航（6 个行业索引）
└── _templates/                  # 通用模板（12 个）
    ├── risk-map.md              # 真实世界风险地图 ★（每季度更新）
    ├── risk-register.md         # 风险注册表
    ├── scenario-analysis.md     # 情景推演 + 时机参考 ★
    ├── authoritative-sources.md # 权威来源白名单 ★
    ├── thesis-template.md       # 研究论点（风险前置）
    ├── opportunity-register.md  # 机遇注册表
    ├── hypothesis-register.md   # 可验证假设注册表
    ├── evidence-tracker.md      # 证据追踪表
    ├── comparison-matrix.md     # 标的对比矩阵
    ├── tracking-indicators.md   # 关键跟踪指标
    ├── review-loop.md           # 闭环复盘模板
    └── physical-constraints.md  # 物理世界约束参考
```

行业目录（按需创建，参见 `src/_index.md`）：

| 行业 | 覆盖方向 |
|------|---------|
| AI 半导体 | 产业链扫描、设备、材料、互连、封测、算力芯片、光模块 |
| 有色金属 | 黄金铜矿 |
| 新能源 | 光伏、储能、锂电 |
| 商业航天 | 产业链扫描 |
| 通信 | 产业链深度调研 |
| 宏观经济 | 周期跟踪、政策解读 |
| 资金流向 | 资金流向全景扫描 |
| 行业情绪 | 行业情绪指数扫描 |
| 资金预判 | 买入安全区间研判 |

### `.claude/skills/` 技能包

```
.claude/skills/
├── a-stock-data/                # A股全栈数据工具包 ★ (28端点/13数据源)
│   ├── SKILL.md / README.md / CHANGELOG.md / LICENSE
│   └── assets/
├── earnings-tracker/             # A股业绩全景追踪 ★
│   ├── SKILL.md
│   └── references/
├── etf-fund-flow-tracker/        # A股ETF资金走势追踪 ★
│   └── SKILL.md
├── industry-sentiment-tracker/     # A股行业情绪指数追踪 ★
│   ├── SKILL.md
│   └── references/
├── policy-event-tracker/        # 政策事件追踪与影响分析 ★
│   ├── SKILL.md
│   └── references/
├── serenity-skill/              # 产业链瓶颈分析
│   ├── SKILL.md / README.md / CHANGELOG.md
│   ├── references/              # 8 个参考文档（risk-and-compliance 等）
│   ├── assets/ / examples/ / evals/ / agents/
│   └── scripts/serenity_scorecard.py
├── stock-pick/                  # 多策略选股
│   ├── SKILL.md
│   ├── assets/ / examples/ / references/ / scripts/
│   └── scripts/outputs/         # 选股输出数据
├── fund-flow-predictor/         # 买入安全区间研判
│   ├── SKILL.md
│   └── references/
│       └── historical-rules.md  # 15条可验证规则库
└── clean-old-analysis/          # 旧分析目录清理
    └── SKILL.md
```

### `scripts/` 工具

```
scripts/
├── print_conclusion.py          # 统一结论打印工具（3 种模式）
└── clean_old_analysis.py        # 旧分析目录清理（dry-run + 确认删除）
```

## 新增分析操作步骤

1. 确定分析主题和市场范围
2. `mkdir -p src/{行业}/{方向}/YYYY-MM-DD-主题名`
3. 从 `src/_templates/` 复制模板（必含 risk-register.md + scenario-analysis.md）
4. **先完成风险映射**（对照 `risk-map.md` + 5 类风险逐项检查）
5. 调用 serenity-skill 执行产业链分析
6. 完成机遇判断 → 候选筛选 + 估值分析 → 情景推演（基于真实数据）
7. 设定假设和跟踪指标，设定复盘日期和风险审查日期
8. 更新行业 `_index.md`（添加新分析条目）
9. **打印最终结论到控制台**（强制）：必须包含风险定级、核心判断、候选标的优先级、研究边界声明
10. 季报后：更新跟踪指标 + 刷新风险地图 + 复盘

## 分析质量检查清单

交付前逐项确认：

**风险**（最先检查）：5 类风险映射完成？每条绑定了触发条件+前置信号+影响程度？做了风险交互分析？

**层次**：宏观/中观/微观三层同向？基本面/估值/技术/资金四维交叉验证？

**数据**：关键数据来自一级或二级来源？每个数字标注了出处？区分了事实与推测？

**逻辑**：需求波→系统变化→稀缺层推理链完整？先排产业链层级再排公司？

**时机**：做了多情景推演（基准/乐观/悲观/极端）？情景绑定了触发条件？技术/资金/估值数据为真实数据？

**闭环**：设定了复盘日期和风险审查日期？考虑了物理延迟？关键假设设了验证窗口？

**输出**：最终结论已打印到控制台？包含风险定级+核心判断+候选标的优先级+研究边界声明？

## 工作约定

- **回复语言**：简体中文
- **输出风格**：先判断再理由，先产业链层级再公司，正常对话语言避免研报腔，必须含反方理由和验证路径
- **数据优先**：弱证据不可驱动强结论，技术面/资金面/估值面数据必须是真实数据
- **研究边界**：提供触发条件和参考框架，不提供买卖指令
- **确认机制**：破坏性操作前使用 `AskUserQuestion` 提供预设选项
- **结论输出**：分析过程写文件，**最终结论必须打印到控制台**（可用 `scripts/print_conclusion.py`）
- **风险边界**：参考 `.claude/skills/serenity-skill/references/risk-and-compliance.md`
- **市场数据来源**：参考 `.claude/skills/serenity-skill/references/market-source-playbook.md`

## Python 环境

```bash
python3 -m venv .venv && source .venv/bin/activate
# a-stock-data 依赖
pip install mootdx requests pandas stockstats
```

> **日常使用**：每次新会话需先 `source .venv/bin/activate`，否则 mootdx 等库不可用。

## 常见故障排查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| mootdx 连接超时 | 通达信服务器不稳定 | 重试或切换 `ext.hq` 参数到备用服务器 |
| 东财接口返回 403 | IP 被限流/封禁 | a-stock-data 已内置限流；若仍被封，切换到腾讯/mootdx 数据源 |
| `ModuleNotFoundError` | 未激活 venv | 执行 `source .venv/bin/activate` |
| stockstats 安装失败 | 依赖冲突 | 尝试 `pip install stockstats --no-deps` 后手动补装缺失依赖 |

## 结论输出工具

`scripts/print_conclusion.py` — 三种模式：

```bash
python3 scripts/print_conclusion.py --auto src/YYYY-MM-DD-主题名/     # 自动发现
python3 scripts/print_conclusion.py --file src/xxx/thesis.md         # 从 markdown 提取
python3 scripts/print_conclusion.py --text "核心判断: ..." --title "标题"  # 直接文本
```
