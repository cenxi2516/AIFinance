# 共享模块索引 (_shared)

> 版本: V1.0 | 创建: 2026-07-10
> 所有研判 Skill 的共享基础设施

## 模块清单

| 模块 | 文件 | 职责 |
|------|------|------|
| **概率规则引擎** | `probability_engine.py` | 统一规则加载、条件匹配、多情景概率计算、贝叶斯聚合、动态修正 |
| **历史规律知识库** | `historical-rules-kb.md` | 所有从A股实际数据学习到的规律集中管理（人去读） |
| **历史规律结构化数据** | `../rules/` 目录 | 机器可读的规则JSON文件（程序去读） |
| **行业参数配置** | `probability_engine.py::DEFAULT_INDUSTRY_PARAMS` | 8大行业差异化参数 |
| **动态修正因子** | `probability_engine.py::DYNAMIC_CORRECTION_FACTORS` | 市场状态/情绪/估值/资金背离修正 |

## 核心设计原则

1. **所有概率自计算** — 不引用外部来源，全部从A股实际盘面数据计算
2. **行业差异化** — 每个行业有独立的参数和规则变体
3. **多情景输出** — 不是单一数字，而是5档概率分布
4. **可更新** — 新数据 → 重新计算 → 更新规则文件

## 目录结构

```
.claude/skills/_shared/
├── _index.md                    # 本文件
├── probability_engine.py        # 核心引擎
└── historical-rules-kb.md       # 规律知识库（人工维护）

rules/                           # 规则数据（机器读写）
├── _common/                     # 全市场通用规则
│   ├── R001.json                # 每条规则一个JSON
│   └── ...
├── 半导体/                      # 行业特定规则
│   ├── industry_params.json
│   └── ...
└── ...

src/_backtest/                   # 回测验证
├── predictions/                 # 预测记录
├── verifications/               # 验证结果
└── calibration_reports/         # 校准报告
```

## 使用方式

### 在 Python 脚本中使用

```python
import sys
sys.path.insert(0, '.claude/skills/_shared')
from probability_engine import RuleEngine, CurrentMarketSnapshot, quick_evaluate

# 方式1: 完整接口
engine = RuleEngine("rules/")
snapshot = CurrentMarketSnapshot(...)
report = engine.evaluate(snapshot, industry="半导体")

# 方式2: 快速接口
report = quick_evaluate(snapshot_dict, industry="半导体")

# 输出Markdown
print(report.to_markdown())
```

### 在 Skill 的 SKILL.md 中引用

Skill 在执行研判时，应调用本引擎进行概率计算，而非使用硬编码或外部引用的概率数字。

## 当前状态

- [x] 概率引擎核心框架
- [x] 贝叶斯聚合机制
- [x] 动态修正因子体系
- [x] 行业差异化参数（初始默认值）
- [ ] Phase 1: 半导体行业数据学习 → 填充真实概率
- [ ] Phase 1: 8条核心规则的规则JSON文件
- [ ] Phase 2: 引擎集成到 quant-dashboard
- [ ] Phase 2: 引擎集成到 fund-flow-predictor
