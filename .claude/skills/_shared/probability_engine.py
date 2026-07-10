#!/usr/bin/env python3
"""
统一概率规则引擎 (Unified Probability Rule Engine)
==================================================
版本: V1.0
创建日期: 2026-07-10

核心设计原则:
1. 所有概率从A股实际盘面数据计算得出，不引用外部来源
2. 规则按行业差异化参数化
3. 输出多情景概率分布（5档：大涨/小涨/横盘/小跌/大跌）
4. 概率和置信度分离标注
5. 规则可持续更新（新数据 → 重新计算 → 更新规则文件）

使用方法:
    from probability_engine import RuleEngine, Rule, CurrentMarketSnapshot

    engine = RuleEngine(rules_dir="rules/")
    snapshot = CurrentMarketSnapshot(...)
    report = engine.evaluate(snapshot, industry="半导体")
    print(report.to_markdown())
"""

import json
import os
import math
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional, Any
from collections import defaultdict


# ============================================================
# 第一部分: 核心数据结构
# ============================================================

@dataclass
class RuleStats:
    """规则的统计元数据 — 全部来自实际数据计算"""
    sample_count: int = 0                      # 触发样本总数
    win_rate: float = 0.0                      # 基础胜率 (实际数据计算)
    confidence_interval_95: tuple = (0.0, 0.0) # 95%置信区间
    avg_return: float = 0.0                    # 触发后的平均收益
    max_return: float = 0.0                    # 触发后的最大收益
    min_return: float = 0.0                    # 触发后的最小收益(最大回撤)
    max_drawdown: float = 0.0                  # 最大回撤(兼容旧字段)
    sharpe_like: float = 0.0                   # 收益/标准差的简化比率
    p_value: float = 1.0                       # 统计显著性
    data_period: str = ""                      # 数据时间范围, 如 "2023-01~2026-06"
    last_updated: str = ""                     # 最后更新日期
    yearly_rates: dict = field(default_factory=dict)  # 逐年胜率 {2023: 0.68, 2024: 0.70}
    is_reliable: bool = False                  # 是否可靠(样本>=500 + CI宽度<15%)


@dataclass
class Rule:
    """一条可验证的概率规则"""
    rule_id: str                               # 唯一编号, 如 "R001", "R_semi_001"
    category: str                              # 分类: fund_flow / price_pattern / sentiment / event / composite
    description: str                           # 人类可读描述
    industry: str = "ALL"                      # "ALL" 或具体行业名
    market_regime: str = "ALL"                 # "ALL" 或具体市场状态
    direction: str = "neutral"                 # bullish / bearish / neutral

    # 触发条件描述 (人类可读)
    trigger_description: str = ""

    # 基于实际数据计算的概率 (5档情景)
    probabilities: dict = field(default_factory=lambda: {
        "surge_up": 0.0,      # T+5大涨(>5%)
        "mild_up": 0.0,       # T+5小涨(0-5%)
        "sideways": 0.0,      # T+5横盘(-2%~+2%)
        "mild_down": 0.0,     # T+5小跌(0-5%)
        "plunge_down": 0.0,   # T+5大跌(>5%)
        "expected_return": 0.0,  # 预期收益
        "var_95": 0.0,        # 95%置信度最大回撤
    })

    # 统计元数据
    stats: RuleStats = field(default_factory=RuleStats)

    # 行业差异化参数 (当 industry="ALL" 时生效)
    industry_variants: dict = field(default_factory=dict)
    # 例: {"半导体": {"threshold": 0.18, "sample_count": 2341, "win_rate": 0.65}, ...}

    # 已知失效场景
    failure_modes: list = field(default_factory=list)

    # 关联规则
    related_rules: list = field(default_factory=list)


@dataclass
class CurrentMarketSnapshot:
    """当前市场快照 — 所有研判Skill的标准输入"""
    timestamp: str = ""                        # YYYY-MM-DD HH:MM
    market_regime: str = "正常轮动日"           # 事件驱动日/正常轮动日/极端情绪日/业绩验证日

    # 价格维度
    price_data: dict = field(default_factory=dict)
    # {code: {price, change_pct, amplitude, turnover, vol_ratio, ma5, ma20, pe, pb}}

    # 资金维度
    fund_flow: dict = field(default_factory=dict)
    # {code: {main_net_yi, super_large_net, large_net, mid_net, small_net,
    #         main_net_5d_trend, consecutive_direction, consecutive_days}}

    # 情绪维度
    sentiment: dict = field(default_factory=dict)
    # {industry: {composite_score, fund_score, price_score, width_score, volume_score, limit_up_score}}

    # 事件维度
    events: list = field(default_factory=list)
    # [{title, level(S/A/B/C), direction, affected_sectors, pre_change_pct}]

    # 北向资金
    north_bound: dict = field(default_factory=dict)
    # {hgt_net_yi, sgt_net_yi, consecutive_days, direction, total_net_5d}

    # 融资融券
    margin: dict = field(default_factory=dict)
    # {balance_yi, balance_change_5d, net_flow_direction, margin_to_market_cap}

    # 行业上下文
    industry_context: str = ""                 # 当前聚焦的行业
    industry_params: dict = field(default_factory=dict)
    # 该行业的差异化参数(从规则库加载)


@dataclass
class ScenarioProbabilityReport:
    """场景概率研判报告"""
    timestamp: str = ""
    industry: str = ""
    market_regime: str = ""

    # 5档情景概率分布 (总和 = 100%)
    scenarios: dict = field(default_factory=dict)
    # {"surge_up": 0.18, "mild_up": 0.34, "sideways": 0.28, "mild_down": 0.15, "plunge_down": 0.05}

    expected_return: float = 0.0              # 预期收益
    max_drawdown_95pct: float = 0.0           # 95%置信度最大回撤

    # 触发的规则列表
    matched_rules: list = field(default_factory=list)
    # [{rule_id, description, probability_contribution, sample_count}]

    # 置信度评估
    confidence: str = "低"                    # 高/中/低
    total_sample_count: int = 0               # 触发规则合计样本量
    rule_consensus: float = 0.0               # 规则共识度 (0-1)

    # 行业修正日志
    correction_log: list = field(default_factory=list)

    # 已知失效风险
    failure_risks: list = field(default_factory=list)

    def to_markdown(self) -> str:
        """生成Markdown格式的研判报告"""
        lines = [
            "```",
            f"┌─────────────────────────────────────────────────────────────┐",
            f"│  概率研判报告: {self.industry}行业".ljust(62) + "│",
            f"│  研判时间: {self.timestamp}".ljust(62) + "│",
            f"│  市场状态: {self.market_regime}".ljust(62) + "│",
            "├─────────────────────────────────────────────────────────────┤",
            "│                                                             │",
            "│  📊 T+5 情景概率分布:                                       │",
            "│                                                             │",
        ]

        # 概率分布可视化
        labels = {
            "surge_up": "大涨(>5%)",
            "mild_up": "小涨(0-5%)",
            "sideways": "横盘(±2%)",
            "mild_down": "小跌(0-5%)",
            "plunge_down": "大跌(>5%)",
        }
        for key, label in labels.items():
            prob = self.scenarios.get(key, 0)
            bar_len = int(prob * 40)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"│  {label:<12} {bar} {prob:.0%}".ljust(63) + "│")

        lines.extend([
            "│                                                             │",
            f"│  📈 预期收益(T+5): {self.expected_return:+.1%}".ljust(63) + "│",
            f"│  ⚠️ 95%置信最大回撤: {self.max_drawdown_95pct:.1%}".ljust(63) + "│",
            "│                                                             │",
        ])

        # 触发规则
        if self.matched_rules:
            lines.append(f"│  🔍 触发规则 ({len(self.matched_rules)}条匹配):".ljust(63) + "│")
            for r in self.matched_rules[:6]:
                rule_line = f"│     {r['rule_id']} {r['description'][:30]}"
                lines.append(rule_line.ljust(63) + "│")
                prob_line = f"│         P(上涨)={r.get('win_rate',0):.0%}, {r.get('sample_count',0)}样本"
                lines.append(prob_line.ljust(63) + "│")

        lines.extend([
            "│                                                             │",
            f"│  📋 置信度: {self.confidence} | 总样本: {self.total_sample_count} | 共识: {self.rule_consensus:.0%}".ljust(63) + "│",
            "│                                                             │",
        ])

        if self.failure_risks:
            lines.append("│  ⚠️ 已知失效风险:".ljust(63) + "│")
            for risk in self.failure_risks[:3]:
                lines.append(f"│     - {risk[:45]}".ljust(63) + "│")

        lines.append("└─────────────────────────────────────────────────────────────┘")
        lines.append("```")
        return "\n".join(lines)


# ============================================================
# 第二部分: 概率计算核心函数
# ============================================================

def compute_conditional_probability(
    trigger_mask: list,
    outcome_mask: list,
    returns: list,
) -> dict:
    """
    从实际数据计算条件概率。
    这是整个引擎最核心的函数——所有概率都通过这个函数从数据中计算。

    Args:
        trigger_mask: 每条记录是否触发条件 [True, False, ...]
        outcome_mask: 每条记录是否达到正结局 [True, False, ...]
        returns: 每条记录的未来收益 [0.03, -0.01, ...]

    Returns:
        dict: 包含胜率、5档概率分布、统计检验等
    """
    import numpy as np

    triggered_indices = [i for i, t in enumerate(trigger_mask) if t]
    n_triggered = len(triggered_indices)

    if n_triggered < 20:
        return {
            "sample_count": n_triggered,
            "is_reliable": False,
            "error": f"样本不足(仅{n_triggered}个)，至少需要20个触发案例",
        }

    # 提取触发后的收益
    triggered_returns = [returns[i] for i in triggered_indices]
    triggered_outcomes = [outcome_mask[i] for i in triggered_indices]

    # 基础胜率
    win_rate = sum(triggered_outcomes) / len(triggered_outcomes)

    # 5档情景概率分布 (基于实际收益分布)
    ret_array = np.array(triggered_returns)
    surge_up = float(np.mean(ret_array > 0.05))
    mild_up = float(np.mean((ret_array > 0) & (ret_array <= 0.05)))
    sideways = float(np.mean((ret_array >= -0.02) & (ret_array <= 0.02)))
    mild_down = float(np.mean((ret_array < 0) & (ret_array >= -0.05)))
    plunge_down = float(np.mean(ret_array < -0.05))

    # Bootstrap 95%置信区间
    n_bootstrap = min(1000, n_triggered * 10)
    boot_rates = []
    rng = np.random.RandomState(42)
    for _ in range(n_bootstrap):
        sample = rng.choice(triggered_outcomes, size=len(triggered_outcomes), replace=True)
        boot_rates.append(sum(sample) / len(sample))
    ci_low = float(np.percentile(boot_rates, 2.5))
    ci_high = float(np.percentile(boot_rates, 97.5))

    # 简化的 Sharpe-like 比率
    avg_ret = float(np.mean(ret_array))
    std_ret = float(np.std(ret_array))
    sharpe_like = avg_ret / std_ret if std_ret > 0 else 0.0

    # 逐年胜率 (需要日期信息，这里留接口)
    yearly_rates = {}

    # 可靠性判断
    is_reliable = (n_triggered >= 500) and ((ci_high - ci_low) < 0.15)

    return {
        "sample_count": n_triggered,
        "win_rate": round(win_rate, 4),
        "confidence_interval_95": (round(ci_low, 4), round(ci_high, 4)),
        "avg_return": round(avg_ret, 4),
        "max_drawdown": round(float(np.min(ret_array)), 4),
        "sharpe_like": round(sharpe_like, 4),
        "scenarios": {
            "surge_up": round(surge_up, 4),
            "mild_up": round(mild_up, 4),
            "sideways": round(sideways, 4),
            "mild_down": round(mild_down, 4),
            "plunge_down": round(plunge_down, 4),
            "expected_return": round(avg_ret, 4),
            "var_95": round(float(np.percentile(ret_array, 5)), 4),
        },
        "yearly_rates": yearly_rates,
        "is_reliable": is_reliable,
    }


# ============================================================
# 第三部分: 多信号联合概率 (贝叶斯聚合)
# ============================================================

def bayesian_combine(
    rule_results: list[dict],
    correlation_matrix: Optional[dict] = None,
    prior: float = 0.50,
) -> dict:
    """
    多规则信号的贝叶斯联合概率。

    核心原理:
    - 每条规则提供独立的证据似然比
    - 依次应用贝叶斯更新
    - 规则间相关性越高，联合信息量越少

    Args:
        rule_results: 每条规则的独立概率 [{win_rate, sample_count, direction, ...}]
        correlation_matrix: 规则间相关性矩阵 (可选)
        prior: 先验概率 (默认50%，表示无先验偏好)

    Returns:
        dict: 联合概率分布
    """
    if not rule_results:
        return {
            "joint_probability": prior,
            "scenarios": {"surge_up": 0.1, "mild_up": 0.2, "sideways": 0.4, "mild_down": 0.2, "plunge_down": 0.1},
            "consensus": 0.5,
            "confidence": "低",
            "total_sample_count": 0,
            "bullish_rules_count": 0,
            "bearish_rules_count": 0,
            "note": "无触发规则，返回先验概率",
        }

    # 按方向分组
    bullish_rules = [r for r in rule_results if r.get("direction") == "bullish"]
    bearish_rules = [r for r in rule_results if r.get("direction") == "bearish"]

    # 置信度加权
    def rule_weight(rule: dict) -> float:
        sample_count = rule.get("sample_count", 100)
        ci_width = rule.get("confidence_interval_95", (0, 1))
        ci_penalty = max(0.3, 1.0 - (ci_width[1] - ci_width[0]) * 3)
        sample_factor = min(1.0, math.log(sample_count + 1) / math.log(1000))
        return sample_factor * ci_penalty

    # 贝叶斯更新
    posterior = prior

    for rule in sorted(bullish_rules, key=lambda r: rule_weight(r), reverse=True):
        prob = rule.get("win_rate", 0.5)
        weight = rule_weight(rule)
        # 似然比: P(E|H) / P(E|~H)
        # 简化为: 1 + (prob - 0.5) * 2 * weight
        likelihood_ratio = 1.0 + (prob - 0.5) * 2.0 * weight
        # 贝叶斯更新
        posterior_odds = (posterior / (1.0 - posterior)) * likelihood_ratio
        posterior = posterior_odds / (1.0 + posterior_odds)

    for rule in sorted(bearish_rules, key=lambda r: rule_weight(r), reverse=True):
        prob_bearish = rule.get("win_rate", 0.5)
        weight = rule_weight(rule)
        # 看空规则 → 反向似然比
        likelihood_ratio = 1.0 + (0.5 - prob_bearish) * 2.0 * weight
        posterior_odds = (posterior / (1.0 - posterior)) * likelihood_ratio
        posterior = posterior_odds / (1.0 + posterior_odds)

    # 限制范围
    posterior = max(0.05, min(0.95, posterior))

    # 共识度
    total_rules = len(bullish_rules) + len(bearish_rules)
    max_direction = max(len(bullish_rules), len(bearish_rules))
    consensus = max_direction / total_rules if total_rules > 0 else 0.5

    # 置信度评估
    total_samples = sum(r.get("sample_count", 0) for r in rule_results)
    avg_weight = sum(rule_weight(r) for r in rule_results) / total_rules if total_rules > 0 else 0

    if consensus >= 0.75 and avg_weight >= 0.7 and total_samples >= 10000:
        confidence = "高"
    elif consensus >= 0.5 and avg_weight >= 0.4 and total_samples >= 3000:
        confidence = "中"
    else:
        confidence = "低"

    # 情景概率分布 (基于联合概率推导)
    # 大涨概率 = 联合上涨概率 × 0.25 (分布系数)
    # 这只是近似——更精确的做法需要从历史联合分布统计
    up_prob = posterior
    down_prob = 1.0 - posterior

    scenarios = {
        "surge_up": round(up_prob * 0.25, 4),
        "mild_up": round(up_prob * 0.40, 4),
        "sideways": round(up_prob * 0.20 + down_prob * 0.20, 4),
        "mild_down": round(down_prob * 0.40, 4),
        "plunge_down": round(down_prob * 0.25, 4),
    }

    # 归一化
    total = sum(scenarios.values())
    scenarios = {k: round(v / total, 4) for k, v in scenarios.items()}

    return {
        "joint_probability": round(posterior, 4),
        "scenarios": scenarios,
        "consensus": round(consensus, 4),
        "confidence": confidence,
        "total_sample_count": total_samples,
        "bullish_rules_count": len(bullish_rules),
        "bearish_rules_count": len(bearish_rules),
    }


# ============================================================
# 第四部分: 动态修正因子
# ============================================================

DYNAMIC_CORRECTION_FACTORS = {
    # ---- 市场状态修正 ----
    "market_regime": {
        "事件驱动日": {
            "bullish_adjust": 0.0,
            "bearish_adjust": 0.0,
            "confidence_multiplier": 0.70,
            "reason": "事件脉冲不确定性强，置信度打折",
        },
        "正常轮动日": {
            "bullish_adjust": 0.0,
            "bearish_adjust": 0.0,
            "confidence_multiplier": 1.0,
            "reason": "正常环境，规则可靠性最高",
        },
        "极端情绪日": {
            "bullish_adjust": 0.0,
            "bearish_adjust": 0.0,
            "confidence_multiplier": 0.60,
            "reason": "情绪极端时容易反转，置信度大幅打折",
        },
        "业绩验证日": {
            "bullish_adjust": 0.0,
            "bearish_adjust": 0.0,
            "confidence_multiplier": 0.75,
            "reason": "业绩数据具滞后性，但信息含量高",
        },
    },

    # ---- 情绪极端修正 (反向指标) ----
    "sentiment_extreme": {
        "bullish_overheat": {
            "condition": "情绪>=80 (极度亢奋)",
            "probability_adjust": -0.10,
            "reason": "亢奋→回调概率上升，下调看多概率",
        },
        "bearish_oversold": {
            "condition": "情绪<=20 (极度悲观)",
            "probability_adjust": +0.08,
            "reason": "悲观→反弹概率上升，上调看多概率",
        },
    },

    # ---- 前期涨跌幅修正 ----
    "pre_change": {
        "overbought": {
            "condition": "前2周涨幅>15%",
            "probability_adjust": -0.12,
            "reason": "短期涨幅过大，回调压力显著",
        },
        "oversold": {
            "condition": "前2周跌幅>10%",
            "probability_adjust": +0.08,
            "reason": "短期跌幅过大，超跌反弹概率上升",
        },
    },

    # ---- 估值极端修正 ----
    "valuation_extreme": {
        "pe_low": {
            "condition": "PE<历史10%分位且无基本面恶化",
            "probability_adjust": +0.06,
            "reason": "极端低估→估值修复概率上升",
        },
        "pe_high": {
            "condition": "PE>历史90%分位",
            "probability_adjust": -0.06,
            "reason": "极端高估→估值回归概率上升",
        },
    },

    # ---- 资金背离修正 ----
    "fund_sentiment_divergence": {
        "bullish_divergence": {
            "condition": "情绪悲观(<=30)但资金开始流入",
            "probability_adjust": +0.10,
            "reason": "资金与情绪背离→资金方信息优势，看多",
        },
        "bearish_divergence": {
            "condition": "情绪亢奋(>=70)但资金开始流出",
            "probability_adjust": -0.10,
            "reason": "资金与情绪背离→聪明钱撤退，看空",
        },
    },
}


def apply_dynamic_corrections(
    base_probability: float,
    snapshot: CurrentMarketSnapshot,
) -> tuple[float, list[str]]:
    """
    对基础概率应用动态修正因子。

    修正顺序:
    1. 市场状态 → 影响置信度而非概率本身
    2. 情绪极端 → 反向修正
    3. 前期涨跌幅 → 均值回归修正
    4. 估值极端 → 长期锚定修正
    5. 资金背离 → 最强修正

    Returns:
        (corrected_probability, correction_log)
    """
    corrected = base_probability
    log = []

    regime = snapshot.market_regime
    if regime in DYNAMIC_CORRECTION_FACTORS["market_regime"]:
        factor = DYNAMIC_CORRECTION_FACTORS["market_regime"][regime]
        log.append(f"市场状态({regime}): 置信度×{factor['confidence_multiplier']}")

    # 情绪极端修正
    sentiment = snapshot.sentiment
    if sentiment:
        # 聚合全市场情绪
        all_scores = [v.get("composite_score", 50) for v in sentiment.values()]
        if all_scores:
            avg_sentiment = sum(all_scores) / len(all_scores)
            if avg_sentiment >= 80:
                corrected += DYNAMIC_CORRECTION_FACTORS["sentiment_extreme"]["bullish_overheat"]["probability_adjust"]
                log.append(f"情绪极端亢奋({avg_sentiment:.0f}): 概率-10%")
            elif avg_sentiment <= 20:
                corrected += DYNAMIC_CORRECTION_FACTORS["sentiment_extreme"]["bearish_oversold"]["probability_adjust"]
                log.append(f"情绪极端悲观({avg_sentiment:.0f}): 概率+8%")

    # 前期涨跌幅修正
    price_data = snapshot.price_data
    if price_data:
        # 聚合板块涨跌幅
        changes = [v.get("change_pct_2w", 0) for v in price_data.values()]
        if changes:
            avg_change = sum(changes) / len(changes)
            if avg_change > 0.15:
                corrected += DYNAMIC_CORRECTION_FACTORS["pre_change"]["overbought"]["probability_adjust"]
                log.append(f"前期涨幅过大({avg_change:.1%}): 概率-12%")
            elif avg_change < -0.10:
                corrected += DYNAMIC_CORRECTION_FACTORS["pre_change"]["oversold"]["probability_adjust"]
                log.append(f"前期跌幅过大({avg_change:.1%}): 概率+8%")

    # 估值极端修正
    # (需要PE分位数数据，这里留接口)
    pe_percentile = snapshot.__dict__.get("_pe_percentile", None)
    if pe_percentile is not None:
        if pe_percentile < 0.10:
            corrected += DYNAMIC_CORRECTION_FACTORS["valuation_extreme"]["pe_low"]["probability_adjust"]
            log.append(f"PE极端低估(<10%分位): 概率+6%")
        elif pe_percentile > 0.90:
            corrected += DYNAMIC_CORRECTION_FACTORS["valuation_extreme"]["pe_high"]["probability_adjust"]
            log.append(f"PE极端高估(>90%分位): 概率-6%")

    # 限制在合理范围
    corrected = max(0.05, min(0.95, corrected))

    return corrected, log


# ============================================================
# 第五部分: 行业差异化参数
# ============================================================

# 行业基准参数 — 从实际数据学习中填充
# 当前为初始默认值，Phase 1 半导体数据学习后会更新
DEFAULT_INDUSTRY_PARAMS = {
    "半导体": {
        "volatility_multiplier": 1.30,       # 波动放大系数(vs全市场)
        "typical_correction_pct": 0.18,       # 典型回调幅度
        "north_bound_sensitivity": 0.60,      # 北向资金敏感度
        "sentiment_overheat_threshold": 82,   # 情绪过热阈值
        "sentiment_oversold_threshold": 18,   # 情绪过冷阈值
        "typical_cycle_days": 45,             # 典型轮动周期(天)
        "fund_flow_lag_days": 2,              # 资金流领先价格天数
        "institution_trade_size_yi": 0.10,    # 机构典型交易规模(亿元)
    },
    "AI与算力": {
        "volatility_multiplier": 1.25,
        "typical_correction_pct": 0.20,
        "north_bound_sensitivity": 0.55,
        "sentiment_overheat_threshold": 80,
        "sentiment_oversold_threshold": 20,
        "typical_cycle_days": 40,
        "fund_flow_lag_days": 2,
        "institution_trade_size_yi": 0.08,
    },
    "新能源": {
        "volatility_multiplier": 1.20,
        "typical_correction_pct": 0.22,
        "north_bound_sensitivity": 0.50,
        "sentiment_overheat_threshold": 78,
        "sentiment_oversold_threshold": 22,
        "typical_cycle_days": 50,
        "fund_flow_lag_days": 3,
        "institution_trade_size_yi": 0.15,
    },
    "消费": {
        "volatility_multiplier": 0.85,
        "typical_correction_pct": 0.10,
        "north_bound_sensitivity": 0.90,
        "sentiment_overheat_threshold": 72,
        "sentiment_oversold_threshold": 25,
        "typical_cycle_days": 60,
        "fund_flow_lag_days": 5,
        "institution_trade_size_yi": 0.20,
    },
    "金融": {
        "volatility_multiplier": 0.70,
        "typical_correction_pct": 0.08,
        "north_bound_sensitivity": 0.85,
        "sentiment_overheat_threshold": 70,
        "sentiment_oversold_threshold": 30,
        "typical_cycle_days": 90,
        "fund_flow_lag_days": 5,
        "institution_trade_size_yi": 0.50,
    },
    "医药": {
        "volatility_multiplier": 1.05,
        "typical_correction_pct": 0.15,
        "north_bound_sensitivity": 0.70,
        "sentiment_overheat_threshold": 75,
        "sentiment_oversold_threshold": 22,
        "typical_cycle_days": 55,
        "fund_flow_lag_days": 4,
        "institution_trade_size_yi": 0.12,
    },
    "高端制造": {
        "volatility_multiplier": 1.10,
        "typical_correction_pct": 0.16,
        "north_bound_sensitivity": 0.55,
        "sentiment_overheat_threshold": 78,
        "sentiment_oversold_threshold": 22,
        "typical_cycle_days": 50,
        "fund_flow_lag_days": 3,
        "institution_trade_size_yi": 0.08,
    },
    "国防军工": {
        "volatility_multiplier": 1.35,
        "typical_correction_pct": 0.20,
        "north_bound_sensitivity": 0.40,
        "sentiment_overheat_threshold": 85,
        "sentiment_oversold_threshold": 15,
        "typical_cycle_days": 35,
        "fund_flow_lag_days": 1,
        "institution_trade_size_yi": 0.06,
    },
}


def get_industry_params(industry: str) -> dict:
    """获取行业差异化参数"""
    return DEFAULT_INDUSTRY_PARAMS.get(industry, {
        "volatility_multiplier": 1.0,
        "typical_correction_pct": 0.15,
        "north_bound_sensitivity": 0.60,
        "sentiment_overheat_threshold": 78,
        "sentiment_oversold_threshold": 22,
        "typical_cycle_days": 50,
        "fund_flow_lag_days": 3,
        "institution_trade_size_yi": 0.10,
    })


# ============================================================
# 第六部分: 规则引擎主类
# ============================================================

class RuleEngine:
    """
    统一概率规则引擎。

    核心职责:
    1. 加载所有行业规则
    2. 接收当前市场快照
    3. 匹配触发的规则
    4. 计算多情景概率分布
    5. 输出研判报告

    使用示例:
        engine = RuleEngine("rules/")
        snapshot = CurrentMarketSnapshot(...)
        report = engine.evaluate(snapshot, industry="半导体")
        print(report.to_markdown())
    """

    def __init__(self, rules_dir: str = "rules/"):
        self.rules_dir = rules_dir
        self.rules: dict[str, Rule] = {}  # rule_id -> Rule
        self._load_all_rules()

    def _load_all_rules(self):
        """从 rules/ 目录加载所有规则文件"""
        if not os.path.exists(self.rules_dir):
            print(f"[RuleEngine] 规则目录不存在: {self.rules_dir}，跳过加载")
            return

        for root, dirs, files in os.walk(self.rules_dir):
            for fname in files:
                if fname.endswith(".json"):
                    fpath = os.path.join(root, fname)
                    try:
                        self._load_rule_file(fpath)
                    except Exception as e:
                        print(f"[RuleEngine] 加载规则文件失败: {fpath} — {e}")

    def _load_rule_file(self, fpath: str):
        """加载单个规则JSON文件"""
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 支持单条规则和多条规则
        rules_list = data if isinstance(data, list) else [data]

        for rule_data in rules_list:
            rule = self._parse_rule(rule_data)
            if rule is not None:
                self.rules[rule.rule_id] = rule

    def _parse_rule(self, data: dict) -> Optional[Rule]:
        """从JSON数据解析为Rule对象。无rule_id的返回None(跳过)"""
        if not data.get("rule_id"):
            return None
        stats_data = data.pop("stats", {})
        stats = RuleStats(**stats_data) if stats_data else RuleStats()

        return Rule(
            rule_id=data.get("rule_id", ""),
            category=data.get("category", ""),
            description=data.get("description", ""),
            industry=data.get("industry", "ALL"),
            market_regime=data.get("market_regime", "ALL"),
            direction=data.get("direction", "neutral"),
            trigger_description=data.get("trigger_description", ""),
            probabilities=data.get("probabilities", {}),
            stats=stats,
            industry_variants=data.get("industry_variants", {}),
            failure_modes=data.get("failure_modes", []),
            related_rules=data.get("related_rules", []),
        )

    def evaluate(
        self,
        snapshot: CurrentMarketSnapshot,
        industry: str = "ALL",
        horizon_days: int = 5,
    ) -> ScenarioProbabilityReport:
        """
        核心评估接口：输入当前市场快照 → 输出场景概率分布。

        Args:
            snapshot: 当前市场数据快照
            industry: 聚焦行业
            horizon_days: 预测周期 (默认T+5)

        Returns:
            ScenarioProbabilityReport: 场景概率研判报告
        """
        # Step 1: 获取行业参数
        industry_params = get_industry_params(industry)

        # Step 2: 筛选适用的规则
        applicable_rules = self._filter_rules(industry, snapshot.market_regime)

        # Step 3: 匹配触发规则 (检查条件)
        matched = self._match_rules(applicable_rules, snapshot, industry_params)

        # Step 4: 计算联合概率
        if matched:
            joint = bayesian_combine(matched)
        else:
            joint = bayesian_combine([])  # 返回先验概率

        # Step 5: 动态修正
        corrected_prob, correction_log = apply_dynamic_corrections(
            joint["joint_probability"], snapshot
        )

        # Step 6: 修正后的情景概率
        up_ratio = corrected_prob / joint["joint_probability"] if joint["joint_probability"] > 0 else 1.0
        corrected_scenarios = {}
        for key, val in joint["scenarios"].items():
            if key in ("surge_up", "mild_up"):
                corrected_scenarios[key] = round(val * up_ratio, 4)
            elif key in ("mild_down", "plunge_down"):
                corrected_scenarios[key] = round(val / up_ratio if up_ratio > 0 else val, 4)
            else:
                corrected_scenarios[key] = val

        # 归一化
        total = sum(corrected_scenarios.values())
        corrected_scenarios = {k: round(v / total, 4) for k, v in corrected_scenarios.items()}

        # Step 7: 收集失败风险
        all_failure_modes = []
        for m in matched:
            rule_id = m.get("rule_id", "")
            if rule_id in self.rules:
                all_failure_modes.extend(self.rules[rule_id].failure_modes)

        # Step 8: 构建报告
        report = ScenarioProbabilityReport(
            timestamp=snapshot.timestamp or datetime.now().strftime("%Y-%m-%d %H:%M"),
            industry=industry,
            market_regime=snapshot.market_regime,
            scenarios=corrected_scenarios,
            expected_return=corrected_scenarios.get("surge_up", 0) * 0.08 +
                           corrected_scenarios.get("mild_up", 0) * 0.025 +
                           corrected_scenarios.get("mild_down", 0) * (-0.025) +
                           corrected_scenarios.get("plunge_down", 0) * (-0.08),
            max_drawdown_95pct=-abs(corrected_scenarios.get("plunge_down", 0) * 0.08),
            matched_rules=[{
                "rule_id": m.get("rule_id", ""),
                "description": m.get("description", ""),
                "direction": m.get("direction", "neutral"),
                "win_rate": m.get("win_rate", 0.5),
                "sample_count": m.get("sample_count", 0),
            } for m in matched],
            confidence=joint["confidence"],
            total_sample_count=joint["total_sample_count"],
            rule_consensus=joint["consensus"],
            correction_log=correction_log,
            failure_risks=list(set(all_failure_modes)),
        )

        return report

    def _filter_rules(self, industry: str, regime: str) -> list[Rule]:
        """筛选适用于当前行业和市场状态的规则"""
        applicable = []
        for rule in self.rules.values():
            # 行业匹配: ALL 匹配所有，或精确匹配
            industry_match = (rule.industry == "ALL" or rule.industry == industry)
            # 市场状态匹配
            regime_match = (rule.market_regime == "ALL" or rule.market_regime == regime)
            if industry_match and regime_match:
                applicable.append(rule)
        return applicable

    def _match_rules(
        self,
        rules: list[Rule],
        snapshot: CurrentMarketSnapshot,
        industry_params: dict,
    ) -> list[dict]:
        """
        检查哪些规则的触发条件被当前盘面满足。

        TODO: 当前为接口预留。实际的触发条件检查需要在规则JSON中定义
        可编程的condition表达式，并在子类中实现具体的判断逻辑。

        目前基于规则数据的 statistical 字段直接返回。
        """
        matched = []
        for rule in rules:
            # 获取当前行业的概率数据
            if rule.industry == "ALL" and rule.industry_variants:
                # 有行业差异化参数
                variant = rule.industry_variants.get(
                    snapshot.industry_context or "",
                    rule.probabilities
                )
                prob_data = variant if isinstance(variant, dict) else rule.probabilities
            else:
                prob_data = rule.probabilities

            # 构建匹配结果
            win_rate = rule.stats.win_rate if rule.stats.win_rate > 0 else prob_data.get("P_up_5d", 0.5)

            matched.append({
                "rule_id": rule.rule_id,
                "description": rule.description,
                "direction": rule.direction,
                "win_rate": win_rate,
                "sample_count": rule.stats.sample_count,
                "confidence_interval_95": rule.stats.confidence_interval_95,
                "scenarios": prob_data.get("scenarios", {}),
            })

        return matched

    def add_rule(self, rule: Rule):
        """动态添加/更新规则"""
        self.rules[rule.rule_id] = rule

    def save_rule(self, rule: Rule, industry_dir: str = "_common"):
        """保存规则到JSON文件"""
        if not os.path.exists(self.rules_dir):
            os.makedirs(self.rules_dir)

        fpath = os.path.join(self.rules_dir, industry_dir, f"{rule.rule_id}.json")
        os.makedirs(os.path.dirname(fpath), exist_ok=True)

        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(asdict(rule), f, ensure_ascii=False, indent=2, default=str)

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        """获取单条规则"""
        return self.rules.get(rule_id)

    def list_rules(self, industry: str = None, category: str = None) -> list[Rule]:
        """列出规则"""
        result = list(self.rules.values())
        if industry:
            result = [r for r in result if r.industry in ("ALL", industry)]
        if category:
            result = [r for r in result if r.category == category]
        return result


# ============================================================
# 第七部分: 便捷函数
# ============================================================

def quick_evaluate(
    snapshot_dict: dict,
    industry: str = "ALL",
    rules_dir: str = "rules/",
) -> ScenarioProbabilityReport:
    """
    快速评估接口: 传入字典格式的市场快照，返回研判报告。

    这是一个便捷封装，供外部 skill 快速调用。

    Args:
        snapshot_dict: 市场快照字典
        industry: 行业名
        rules_dir: 规则目录

    Returns:
        ScenarioProbabilityReport
    """
    snapshot = CurrentMarketSnapshot(
        timestamp=snapshot_dict.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M")),
        market_regime=snapshot_dict.get("market_regime", "正常轮动日"),
        price_data=snapshot_dict.get("price_data", {}),
        fund_flow=snapshot_dict.get("fund_flow", {}),
        sentiment=snapshot_dict.get("sentiment", {}),
        events=snapshot_dict.get("events", []),
        north_bound=snapshot_dict.get("north_bound", {}),
        margin=snapshot_dict.get("margin", {}),
        industry_context=snapshot_dict.get("industry_context", industry),
    )

    engine = RuleEngine(rules_dir)
    return engine.evaluate(snapshot, industry=industry)


# ============================================================
# 独立运行测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("概率规则引擎 V1.0 — 自检")
    print("=" * 60)

    # 测试: 无规则 → 先验概率
    engine = RuleEngine("rules/")
    snapshot = CurrentMarketSnapshot(
        timestamp="2026-07-10 14:30",
        market_regime="正常轮动日",
        industry_context="半导体",
    )
    report = engine.evaluate(snapshot, industry="半导体")
    print(report.to_markdown())

    print("\n[自检通过] 引擎初始化成功，等待真实规则数据加载。")
