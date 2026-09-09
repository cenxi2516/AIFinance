#!/usr/bin/env python3
"""
数据时效性门控模块 V1.0
========================
用于盘中实时分析时，根据当前时段评估各数据维度的可用性。

核心认知: 不是所有数据在盘中同时可用。
- 腾讯行情: 9:25 集合竞价结束后即刷新
- mootdx 分时: 9:30 开盘后每1分钟刷新
- 东财板块资金流(push2): 通常 9:45-10:00 之间首刷
- 东财市场广度(clist): 通常 10:00 后刷新
- 北向资金(同花顺): 通常 10:30 后才会出现非零数据
- 东财新闻: 全天随时更新，但开盘初期少

使用方式:
    from data_freshness import check_data_freshness, apply_freshness_to_condition

    freshness = check_data_freshness()
    # => {phase: 1, phase_name: "盘初(27min)", ...}

与 intraday-trading-signal 集成:
    在 generate_probability_scenarios() 开头调用 check_data_freshness()，
    每个条件条目用 apply_freshness_to_condition() 包装。
"""

from datetime import datetime


def check_data_freshness() -> dict:
    """
    根据当前盘中时段，评估七维数据的可用性。

    返回:
    - is_trading: 是否在交易时段
    - phase: 时效性阶段 (0=非交易, 1=盘初, 2=早盘过渡, 3=盘中正常, 4=尾盘, 5=已收盘)
    - phase_name: 阶段中文描述
    - minutes_from_open: 距9:30的分钟数
    - freshness: {维度key: {available, weight_multiplier, status, reliability, reason}}
    """
    now = datetime.now()

    # 非交易日检查
    if now.weekday() >= 5:
        return {
            "is_trading": False,
            "phase": 0,
            "phase_name": "非交易日",
            "minutes_from_open": -1,
            "freshness": _all_unavailable("周末/节假日休市"),
        }

    # 距9:30的分钟数
    open_minutes = 9 * 60 + 30
    current_minutes = now.hour * 60 + now.minute
    minutes_from_open = current_minutes - open_minutes

    # 收盘后 (15:00 之后)
    close_minutes = 15 * 60
    if current_minutes >= close_minutes:
        return {
            "is_trading": False,
            "phase": 5,
            "phase_name": "已收盘",
            "minutes_from_open": minutes_from_open,
            "freshness": _all_available("盘后回顾，全部数据可用"),
        }

    # 午间休市 (11:30-13:00)
    if 11 * 60 + 30 <= current_minutes < 13 * 60:
        return {
            "is_trading": False,
            "phase": 0,
            "phase_name": "午间休市",
            "minutes_from_open": minutes_from_open,
            "freshness": _all_available("午间休市，上午数据可用"),
        }

    # 确定阶段
    if minutes_from_open < 0:
        phase = 0
        phase_name = "盘前(数据不可用)"
    elif minutes_from_open <= 30:
        phase = 1
        phase_name = f"盘初({minutes_from_open}min, 数据延迟高发期)"
    elif minutes_from_open <= 90:
        phase = 2
        phase_name = f"早盘过渡({minutes_from_open}min, 板块/北向逐渐刷新)"
    elif minutes_from_open <= 300:
        phase = 3
        phase_name = f"盘中正常({minutes_from_open}min, 全维度可用)"
    else:
        phase = 4
        phase_name = f"尾盘({minutes_from_open}min, 异动监测加强)"

    freshness = _build_freshness(phase, minutes_from_open)

    return {
        "is_trading": phase >= 1,
        "phase": phase,
        "phase_name": phase_name,
        "minutes_from_open": minutes_from_open,
        "freshness": freshness,
    }


def apply_freshness_to_condition(condition_text: str, threshold, actual, met: bool,
                                  weight: float, dimension: str,
                                  freshness: dict) -> dict:
    """
    对单个条件条目应用时效性门控。

    参数:
    - condition_text: 条件描述
    - threshold: 阈值文本
    - actual: 当前值文本
    - met: 条件是否满足 (bool)
    - weight: 原始权重
    - dimension: 维度key ('quote'|'minute_flow'|'sector'|'news'|'north_bound'|'market'|'breadth')
    - freshness: check_data_freshness() 的返回字典

    返回:
    - 条件条目 dict，met 可能是 True/False/'PENDING'
    - 权重已根据时效性调整
    """
    fd = freshness.get("freshness", {})
    dim_info = fd.get(dimension,
        {"available": True, "weight_multiplier": 1.0, "status": "ready",
         "reliability": 80, "reason": "未知维度"})

    available = dim_info.get("available", True)
    wm = dim_info.get("weight_multiplier", 1.0)
    status = dim_info.get("status", "ready")
    reason = dim_info.get("reason", "")

    if not available:
        # 数据不可用 → 标记为 PENDING，权重归零
        return {
            "condition": condition_text,
            "threshold": threshold,
            "actual": str(actual) + f" [未就绪:{reason[:30]}]",
            "met": "PENDING",
            "weight": 0.0,
            "original_weight": weight,
            "dimension": dimension,
            "freshness_status": "unavailable",
            "freshness_reason": reason,
        }
    elif status == "delayed":
        # 数据延迟 → 权重打折
        effective_weight = weight * wm
        return {
            "condition": condition_text,
            "threshold": threshold,
            "actual": str(actual) + f" [延迟:{reason[:25]}]",
            "met": met,
            "weight": effective_weight,
            "original_weight": weight,
            "dimension": dimension,
            "freshness_status": "delayed",
            "freshness_reason": reason,
        }
    else:
        # 数据正常
        return {
            "condition": condition_text,
            "threshold": threshold,
            "actual": str(actual),
            "met": met,
            "weight": weight,
            "original_weight": weight,
            "dimension": dimension,
            "freshness_status": "ready",
            "freshness_reason": reason,
        }


def get_phase_weight_matrix(phase: int) -> dict:
    """返回指定阶段的七维权重矩阵（百分制，总和=100）"""
    matrices = {
        # Phase 1: 盘初 — 仅行情+分时可靠
        1: {
            "quote":       25,
            "minute_flow": 50,
            "sector":       5,
            "news":         5,
            "north_bound":  0,
            "market":      15,
            "breadth":      0,
        },
        # Phase 2: 早盘过渡 — 板块/涨停池首批到达
        2: {
            "quote":       20,
            "minute_flow": 35,
            "sector":      12,
            "news":         8,
            "north_bound":  5,
            "market":      12,
            "breadth":      8,
        },
        # Phase 3: 盘中正常 — 全维度均衡
        3: {
            "quote":       15,
            "minute_flow": 25,
            "sector":      15,
            "news":        10,
            "north_bound": 15,
            "market":      10,
            "breadth":     10,
        },
        # Phase 4: 尾盘 — 异动监测加强
        4: {
            "quote":       15,
            "minute_flow": 30,
            "sector":      12,
            "news":        10,
            "north_bound": 13,
            "market":      10,
            "breadth":     10,
        },
    }
    return matrices.get(phase, matrices[3])


def format_freshness_report(freshness: dict) -> str:
    """生成时效性报告的多行文本，可直接嵌入 Markdown 或 Console 输出"""
    phase = freshness.get("phase", -1)
    phase_name = freshness.get("phase_name", "未知")
    fd = freshness.get("freshness", {})

    dim_names = {
        "quote": "行情", "minute_flow": "分时", "sector": "板块",
        "news": "消息", "north_bound": "北向", "market": "大盘", "breadth": "广度",
    }

    lines = [
        f"**数据时效性**: Phase {phase} — {phase_name}",
        "",
        "| 维度 | 状态 | 可靠度 | 说明 |",
        "|------|------|--------|------|",
    ]
    for dim_key, dim_info in fd.items():
        name = dim_names.get(dim_key, dim_key)
        status_icon = {"ready": "✅", "delayed": "⚡", "unavailable": "❌"}.get(
            dim_info.get("status", ""), "❓")
        rel = dim_info.get("reliability", 0)
        reason = dim_info.get("reason", "")[:40]
        lines.append(f"| {name} | {status_icon} {dim_info.get('status', '')} | {rel}% | {reason} |")

    if phase >= 1:
        weights = get_phase_weight_matrix(phase)
        lines.append("")
        lines.append(f"**Phase {phase} 动态权重**: "
                     f"分时{weights['minute_flow']}% | 行情{weights['quote']}% | "
                     f"板块{weights['sector']}% | 北向{weights['north_bound']}% | "
                     f"大盘{weights['market']}% | 广度{weights['breadth']}% | 消息{weights['news']}%")

    return "\n".join(lines)


# ============================================================
# 内部辅助函数
# ============================================================

def _dim(avail: bool, wm: float, status: str, reliability: int, reason: str) -> dict:
    return {
        "available": avail,
        "weight_multiplier": wm,
        "status": status,
        "reliability": reliability,
        "reason": reason,
    }


def _all_unavailable(reason: str) -> dict:
    return {k: _dim(False, 0.0, "unavailable", 0, reason)
            for k in ["quote", "minute_flow", "sector", "news",
                      "north_bound", "market", "breadth"]}


def _all_available(reason: str) -> dict:
    return {k: _dim(True, 1.0, "ready", 90, reason)
            for k in ["quote", "minute_flow", "sector", "news",
                      "north_bound", "market", "breadth"]}


def _build_freshness(phase: int, minutes_from_open: int) -> dict:
    """构建各阶段七维时效性"""

    if phase == 1:
        # 盘初: 仅行情+分时可信
        return {
            "quote":       _dim(True,  1.0, "ready",   95, "腾讯行情 9:25起实时刷新"),
            "minute_flow": _dim(True,  1.0, "ready",   90, "mootdx 9:30起每分钟刷新"),
            "sector":      _dim(False, 0.0, "unavailable", 10,
                                "板块push2统计通常10:00后才首刷，当前全0概率>80%"),
            "news":        _dim(True,  0.6, "delayed", 50,
                                "新闻全天更新，但盘初极少有新消息"),
            "north_bound": _dim(False, 0.0, "unavailable",  5,
                                "同花顺北向API通常10:30后才出现非零数据"),
            "market":      _dim(True,  1.0, "ready",   90, "腾讯指数行情实时刷新"),
            "breadth":     _dim(False, 0.0, "unavailable",  5,
                                "clist全市场统计+涨停池通常10:00后刷新"),
        }

    elif phase == 2:
        # 早盘过渡: 板块/涨停池首批数据到达，北向仍不可靠
        return {
            "quote":       _dim(True,  1.0, "ready",   95, "腾讯行情实时"),
            "minute_flow": _dim(True,  1.0, "ready",   90, "mootdx实时"),
            "sector":      _dim(True,  0.7, "delayed", 60,
                                "板块push2首刷已完成，但数据样本较少"),
            "news":        _dim(True,  0.8, "ready",   70, "早盘新闻开始出现"),
            "north_bound": _dim(True,  0.3, "delayed", 25,
                                "北向可能有首笔数据，但仍可能为0"),
            "market":      _dim(True,  1.0, "ready",   90, "腾讯指数"),
            "breadth":     _dim(True,  0.5, "delayed", 40,
                                "涨跌家数/涨停池首刷完成，但盘中波动未完全反映"),
        }

    elif phase == 3:
        # 盘中正常: 全维度可用
        return {
            "quote":       _dim(True, 1.0, "ready", 95, "正常"),
            "minute_flow": _dim(True, 1.0, "ready", 90, "正常"),
            "sector":      _dim(True, 1.0, "ready", 85, "盘中多次刷新"),
            "news":        _dim(True, 1.0, "ready", 80, "全天更新"),
            "north_bound": _dim(True, 1.0, "ready", 80, "北向数据稳定刷新"),
            "market":      _dim(True, 1.0, "ready", 90, "正常"),
            "breadth":     _dim(True, 1.0, "ready", 80, "正常"),
        }

    elif phase == 4:
        # 尾盘: 全维度 + 异动权重提升
        return {
            "quote":       _dim(True, 1.0, "ready", 95, "尾盘正常"),
            "minute_flow": _dim(True, 1.2, "ready", 90, "尾盘异动监测权重+20%"),
            "sector":      _dim(True, 1.0, "ready", 85, "正常"),
            "news":        _dim(True, 1.0, "ready", 80, "全天更新"),
            "north_bound": _dim(True, 1.0, "ready", 80, "正常"),
            "market":      _dim(True, 1.0, "ready", 90, "正常"),
            "breadth":     _dim(True, 1.0, "ready", 80, "正常"),
        }

    else:
        # phase == 0 盘前
        return _all_unavailable("盘前时段，数据未开始刷新")


# ============================================================
# 自测
# ============================================================
if __name__ == "__main__":
    result = check_data_freshness()
    print(f"阶段: {result['phase_name']}")
    print(f"距开盘: {result['minutes_from_open']}min")
    print(f"盘中: {result['is_trading']}")
    print()
    print(format_freshness_report(result))
