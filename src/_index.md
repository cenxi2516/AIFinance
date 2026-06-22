# 分析目录索引

> 按 **行业 → 方向 → 日期** 三级组织，行业目录按需创建。

## 行业索引

| 行业 | 路径 | 覆盖方向 |
|------|------|---------|
| AI 半导体 | `./AI半导体/` | 产业链扫描、设备、材料、互连、封测、算力芯片、光模块 |
| 有色金属 | `./有色金属/` | 黄金铜矿 |
| 新能源 | `./新能源/` | 光伏、储能、锂电 |
| 商业航天 | `./商业航天/` | 产业链扫描 |
| 通信 | `./通信/` | 产业链深度调研 |
| 宏观经济 | `./宏观经济/` | 周期跟踪、政策解读 |

> 以上行业目录按需创建，首次分析时通过 `mkdir -p` 生成。

## 模板

通用分析模板位于 [`./_templates/`](./_templates/)（12 个），必含：

| 模板 | 用途 | 阶段 |
|------|------|------|
| `risk-map.md` | 真实世界风险地图（每季度更新） | Phase 1 前置对照 |
| `risk-register.md` | 风险注册表 | Phase 1 风险映射 |
| `opportunity-register.md` | 机遇注册表 | Phase 3 机遇判断 |
| `thesis-template.md` | 研究论点（风险前置） | Phase 3-4 论点构建 |
| `comparison-matrix.md` | 标的对比矩阵 | Phase 4 候选筛选 |
| `scenario-analysis.md` | 情景推演 + 时机参考 | Phase 5b 情景推演 |
| `hypothesis-register.md` | 可验证假设注册表 | Phase 6 假设设定 |
| `evidence-tracker.md` | 证据追踪表 | Phase 7 跟踪验证 |
| `tracking-indicators.md` | 关键跟踪指标 | Phase 7 持续跟踪 |
| `review-loop.md` | 闭环复盘模板 | Phase 8 复盘修正 |
| `authoritative-sources.md` | 权威来源白名单 | 全程引用参考 |
| `physical-constraints.md` | 物理世界约束参考 | Phase 2 产业链分析 |

## 新增分析

1. 确定行业归属和方向
2. `mkdir -p src/{行业}/{方向}/YYYY-MM-DD-主题名`
3. 从 `_templates/` 复制模板（必含 risk-register.md + scenario-analysis.md）
4. 对照 `risk-map.md` 完成风险映射
5. 更新对应行业的 `_index.md` 添加新条目
