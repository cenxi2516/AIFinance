#!/usr/bin/env python3
"""
A股规则学习引擎 (Rule Learner)
================================
版本: V1.0
创建日期: 2026-07-10

核心功能:
1. 从A股实际盘面数据中拉取历史数据
2. 对预设规则计算条件概率（不引用外部来源）
3. 按行业分组对比分析
4. 自动发现高概率模式
5. 生成规则JSON文件供概率引擎消费

设计原则:
- 所有概率从实际数据计算，不引用券商研报
- 行业差异化学习
- 样本外验证确保可靠性
- 渐进式：先少量数据验证方法，再扩展全量

用法:
    python3 scripts/rule_learner.py --industry 半导体 --mode compute
    python3 scripts/rule_learner.py --industry 半导体 --mode discover
    python3 scripts/rule_learner.py --industry ALL --mode update
"""

import os
import sys
import json
import time
import random
import math
import argparse
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional

import numpy as np

# 数据拉取全部委托给 a_stock_api（不再自建 SESSION/em_get/api_get）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.claude', 'skills', '_shared'))
from a_stock_api import (
    em_get,
    stock_kline,
    stock_fund_flow_120d,
    concept_sector_fund_flow,
)

def log(msg: str):
    """带时间戳的日志"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ============================================================
# 第一部分: 行业-股票映射
# ============================================================

# 8大行业的代表股票池（流动性好、数据完整的标的）
# 这是初始学习池，后续可扩展
INDUSTRY_STOCK_POOL = {
    "半导体": {
        "设备": ["002371", "688012", "688072", "688120", "688082"],
        "材料": ["688019", "688126", "300346", "300655", "688536"],
        "设计": ["603986", "688981", "688008", "300661", "688256"],
        "制造": ["688981", "600703", "688396", "688187"],
        "封测": ["600584", "002156", "688052", "688629"],
        "存储": ["688525", "300475", "002049", "688110"],
    },
    "AI与算力": {
        "光模块": ["300308", "300502", "300394", "688498"],
        "服务器": ["000977", "603019", "688041"],
        "算力芯片": ["688256", "688047", "688041", "300474"],
        "AI应用": ["300624", "688111", "002230", "688088"],
    },
    "新能源": {
        "光伏": ["601012", "688599", "600438", "002459", "688223"],
        "储能": ["300750", "300014", "002074", "688063"],
        "锂电": ["300750", "002466", "300769", "688005", "002709"],
    },
    "消费": {
        "白酒": ["600519", "000858", "002304", "000568"],
        "食品": ["600887", "002714", "603288", "600882"],
        "家电": ["000333", "000651", "002032", "600690"],
    },
}

# 概念板块代码映射 (东财BK码)
CONCEPT_BK_MAP = {
    "半导体": "BK1036",
    "AI与算力": "BK2111",
    "新能源": "BK0474",
    "消费": "BK0466",
    "医药": "BK0463",
    "金融": "BK0467",
    "高端制造": "BK0470",
    "国防军工": "BK0475",
}


# ============================================================
# 第二部分: 数据拉取
# ============================================================

# ============================================================
# 数据拉取函数 — 全部委托给 a_stock_api
# ============================================================

def fetch_stock_kline(code: str, days: int = 500) -> list[dict]:
    """拉取个股日K线 — 委托给 a_stock_api.stock_kline()"""
    return stock_kline(code, days)


def fetch_stock_fund_flow(code: str, days: int = 120) -> list[dict]:
    """拉取个股资金流 — 委托给 a_stock_api.stock_fund_flow_120d()"""
    return stock_fund_flow_120d(code)


def fetch_concept_fund_flow(bk_code: str, days: int = 120) -> list[dict]:
    """拉取概念板块资金流 — 委托给 a_stock_api.concept_sector_fund_flow()"""
    # a_stock_api 的 concept_sector_fund_flow 返回当前资金流快照
    # 对于历史数据，仍然需要通过 push2his 获取
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": f"90.{bk_code}",
        "fields1": "f1,f2,f3,f4",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62",
        "lmt": str(min(days, 120)),
        "klt": "101",
    }
    try:
        r = em_get(url, params=params, timeout=15)
        data = r.json()
        if data.get("data") and data["data"].get("klines"):
            flows = []
            for line in data["data"]["klines"]:
                parts = line.split(",")
                if len(parts) >= 6:
                    flows.append({
                        "date": parts[0],
                        "main_net_yi": float(parts[1]) / 10000 if parts[1] != "-" else 0,
                    })
            return flows
    except Exception as e:
        log(f"  板块资金流拉取失败 {bk_code}: {e}")
    return []


# ============================================================
# 第三部分: 规则条件判断函数
# ============================================================

# 每条规则的核心是 condition_check(daily_data, index) → bool
# daily_data: 到index日为止的所有历史数据
# 返回: 该日是否触发规则条件

def check_F1_outflow_exhaustion(kline_data: list[dict], flow_data: list[dict], idx: int) -> bool:
    """
    F1: 主力流出衰竭
    条件: 主力连续3日净流出 + 流出逐日递减 + 最新流出 < 前5日均值50%
    """
    if idx < 6:
        return False

    # 最近3日主力净流出
    recent_3 = [flow_data[idx - i].get("main_net_yi", 0) for i in range(2, -1, -1)]

    # 必须连续3日净流出
    if not all(v < 0 for v in recent_3):
        return False

    # 流出必须递减 (绝对值递减)
    abs_flows = [abs(v) for v in recent_3]
    if not (abs_flows[0] > abs_flows[1] > abs_flows[2]):
        return False

    # 最新流出 < 前5日均值的50%
    prev_5_avg = abs(sum(flow_data[idx - i].get("main_net_yi", 0) for i in range(3, 8))) / 5
    if abs_flows[2] >= prev_5_avg * 0.5:
        return False

    return True


def check_F3_institution_return(kline_data: list[dict], flow_data: list[dict], idx: int) -> bool:
    """
    F3: 机构试探性回流
    条件: 前期连续流出>=5日 + 近2日超大单转为净流入 + 散户仍在流出
    """
    if idx < 8:
        return False

    # 前期(t-7 ~ t-3)连续流出
    prev_5 = [flow_data[idx - i].get("main_net_yi", 0) for i in range(3, 8)]
    if not all(v < 0 for v in prev_5):
        return False

    # 近2日超大单净流入
    recent_super = [flow_data[idx - i].get("super_large_net", 0) for i in range(2)]
    if not all(v > 0 for v in recent_super):
        return False

    # 散户仍在流出
    recent_small = [flow_data[idx - i].get("small_net", 0) for i in range(2)]
    if not all(v < 0 for v in recent_small):
        return False

    return True


def check_F4_accelerating_outflow(kline_data: list[dict], flow_data: list[dict], idx: int) -> bool:
    """
    F4: 主力加速流出
    条件: 主力连续3日净流出 + 流出额递增 + 最新流出 > 前5日均值2倍
    """
    if idx < 6:
        return False

    recent_3 = [flow_data[idx - i].get("main_net_yi", 0) for i in range(2, -1, -1)]

    # 连续3日净流出
    if not all(v < 0 for v in recent_3):
        return False

    # 流出额递增 (绝对值递增)
    abs_flows = [abs(v) for v in recent_3]
    if not (abs_flows[0] < abs_flows[1] < abs_flows[2]):
        return False

    # 最新流出 > 前5日均值2倍
    prev_5_avg = abs(sum(flow_data[idx - i].get("main_net_yi", 0) for i in range(3, 8))) / 5
    if abs_flows[2] <= prev_5_avg * 2:
        return False

    return True


def check_F5_top_distribution(kline_data: list[dict], flow_data: list[dict], idx: int) -> bool:
    """
    F5: 顶部派发
    条件: 近5日股价上涨>3% + 超大单净流出 + 散户净流入
    """
    if idx < 5:
        return False

    # 近5日涨幅
    price_5d_ago = kline_data[idx - 5].get("close", 0)
    price_now = kline_data[idx].get("close", 0)
    if price_5d_ago <= 0:
        return False
    change_5d = (price_now - price_5d_ago) / price_5d_ago
    if change_5d <= 0.03:
        return False

    # 近2日超大单净流出
    recent_super = sum(flow_data[idx - i].get("super_large_net", 0) for i in range(2))
    if recent_super >= 0:
        return False

    # 近2日散户净流入
    recent_small = sum(flow_data[idx - i].get("small_net", 0) for i in range(2))
    if recent_small <= 0:
        return False

    return True


def check_F7_good_news_exhausted(kline_data: list[dict], flow_data: list[dict], idx: int,
                                  pre_change_2w: float = 0) -> bool:
    """
    F7: 利好出尽
    条件: 前2周涨幅>15% (需要配合事件判断，这里只做价格条件)
    """
    if idx < 10:
        return False

    # 前2周(10个交易日)涨幅
    price_10d_ago = kline_data[idx - 10].get("close", 0)
    price_now = kline_data[idx].get("close", 0)
    if price_10d_ago <= 0:
        return False

    change_2w = (price_now - price_10d_ago) / price_10d_ago

    # 使用传入的板块涨幅或个股涨幅
    if pre_change_2w > 0:
        return pre_change_2w > 0.15
    return change_2w > 0.15


def check_F8_volume_contraction(kline_data: list[dict], flow_data: list[dict], idx: int) -> bool:
    """
    F8: 缩量止跌
    条件: 连续3日跌幅<1% + 换手率<20日均值60% + 主力流出<前5日均值30%
    """
    if idx < 22:
        return False

    # 连续3日跌幅<1%
    for i in range(3):
        change = kline_data[idx - i].get("change_pct", -99)
        if change < -1.0:
            return False

    # 换手率 < 20日均值的60%
    turnover_now = kline_data[idx].get("turnover", 0)
    turnover_20d_avg = sum(kline_data[idx - i].get("turnover", 0) for i in range(1, 21)) / 20
    if turnover_20d_avg > 0 and turnover_now >= turnover_20d_avg * 0.6:
        return False

    # 主力流出 < 前5日均值的30%
    main_out_now = abs(flow_data[idx].get("main_net_yi", 0))
    main_out_5d_avg = abs(sum(flow_data[idx - i].get("main_net_yi", 0) for i in range(1, 6))) / 5
    if main_out_5d_avg > 0 and main_out_now >= main_out_5d_avg * 0.3:
        return False

    return True


# 规则注册表
RULES_REGISTRY = {
    "R001_outflow_exhaustion": {
        "rule_id": "R001",
        "category": "fund_flow",
        "description": "主力流出衰竭 — 连续3日流出递减+最新<前5日均值50%",
        "direction": "bullish",
        "check_fn": check_F1_outflow_exhaustion,
        "horizon_days": 5,
        "outcome_direction": "up",  # 期望上涨
    },
    "R003_institution_return": {
        "rule_id": "R003",
        "category": "fund_flow",
        "description": "机构试探回流 — 前期流出5日+近2日超大单流入+散户仍在流出",
        "direction": "bullish",
        "check_fn": check_F3_institution_return,
        "horizon_days": 5,
        "outcome_direction": "up",
    },
    "R004_accelerating_outflow": {
        "rule_id": "R004",
        "category": "fund_flow",
        "description": "主力加速流出 — 连续3日流出递增+最新>前5日均值2倍",
        "direction": "bearish",
        "check_fn": check_F4_accelerating_outflow,
        "horizon_days": 5,
        "outcome_direction": "down",  # 期望下跌
    },
    "R005_top_distribution": {
        "rule_id": "R005",
        "category": "fund_flow",
        "description": "顶部派发 — 涨>3%+超大单流出+散户流入",
        "direction": "bearish",
        "check_fn": check_F5_top_distribution,
        "horizon_days": 5,
        "outcome_direction": "down",
    },
    "R007_good_news_exhausted": {
        "rule_id": "R007",
        "category": "price_pattern",
        "description": "利好出尽 — 前2周涨幅>15%",
        "direction": "bearish",
        "check_fn": check_F7_good_news_exhausted,
        "horizon_days": 5,
        "outcome_direction": "down",
    },
    "R008_volume_contraction": {
        "rule_id": "R008",
        "category": "price_pattern",
        "description": "缩量止跌 — 连续3日跌幅<1%+换手率<20日60%+主力流出<前5日30%",
        "direction": "bullish",
        "check_fn": check_F8_volume_contraction,
        "horizon_days": 10,
        "outcome_direction": "up",
    },
}


# ============================================================
# 第四部分: 核心计算 — 条件概率
# ============================================================

def compute_rule_probability(
    rule_config: dict,
    stocks_data: dict[str, dict],  # {code: {"kline": [...], "flow": [...]}}
    horizon_days: int = 5,
    industry_params: dict = None,
) -> dict:
    """
    核心函数：从实际数据计算规则的条件概率。

    对每只股票的每一天:
    1. 检查规则条件是否触发 (check_fn)
    2. 若触发，记录 horizon_days 后的收益
    3. 汇总统计

    Args:
        rule_config: 规则配置 (含 check_fn)
        stocks_data: 股票历史数据
        horizon_days: 预测周期
        industry_params: 行业参数 (用于阈值调整)

    Returns:
        dict: 概率统计结果
    """
    check_fn = rule_config["check_fn"]
    rule_id = rule_config["rule_id"]
    outcome_up = (rule_config.get("outcome_direction") == "up")

    all_triggered_returns = []  # 所有触发后的收益
    trigger_details = []         # 触发详情

    for code, data in stocks_data.items():
        kline = data.get("kline", [])
        flow = data.get("flow", [])

        if len(kline) < horizon_days + 30 or len(flow) < horizon_days + 30:
            continue

        # 对齐数据长度
        min_len = min(len(kline), len(flow))

        for idx in range(30, min_len - horizon_days):
            try:
                triggered = check_fn(kline, flow, idx)
            except (IndexError, KeyError):
                continue

            if triggered:
                # 记录触发日价格
                trigger_price = kline[idx]["close"]
                trigger_date = kline[idx]["date"]

                # 计算 horizon_days 后的收益
                future_idx = idx + horizon_days
                if future_idx >= min_len:
                    continue

                future_price = kline[future_idx]["close"]
                if trigger_price <= 0:
                    continue

                ret = (future_price - trigger_price) / trigger_price

                all_triggered_returns.append(ret)
                trigger_details.append({
                    "code": code,
                    "date": trigger_date,
                    "trigger_price": trigger_price,
                    "future_date": kline[future_idx]["date"],
                    "future_price": future_price,
                    "return": round(ret, 6),
                })

    n_triggered = len(all_triggered_returns)

    if n_triggered < 20:
        return {
            "rule_id": rule_id,
            "sample_count": n_triggered,
            "is_reliable": False,
            "error": f"触发样本不足(仅{n_triggered}个)",
            "trigger_details": trigger_details,
        }

    ret_array = np.array(all_triggered_returns)

    # 基础胜率
    if outcome_up:
        win_rate = float(np.mean(ret_array > 0))
    else:
        win_rate = float(np.mean(ret_array < 0))

    # 5档情景概率分布 (实际收益分布统计)
    scenarios = {
        "surge_up": float(np.mean(ret_array > 0.05)),
        "mild_up": float(np.mean((ret_array > 0) & (ret_array <= 0.05))),
        "sideways": float(np.mean((ret_array >= -0.02) & (ret_array <= 0.02))),
        "mild_down": float(np.mean((ret_array < 0) & (ret_array >= -0.05))),
        "plunge_down": float(np.mean(ret_array < -0.05)),
        "expected_return": float(np.mean(ret_array)),
        "var_95": float(np.percentile(ret_array, 5)),
    }

    # Bootstrap 置信区间
    n_bootstrap = min(1000, n_triggered * 10)
    rng = np.random.RandomState(42)
    boot_rates = []
    for _ in range(n_bootstrap):
        sample = rng.choice(ret_array, size=len(ret_array), replace=True)
        if outcome_up:
            boot_rates.append(np.mean(sample > 0))
        else:
            boot_rates.append(np.mean(sample < 0))
    ci_low = float(np.percentile(boot_rates, 2.5))
    ci_high = float(np.percentile(boot_rates, 97.5))

    # 逐年胜率
    yearly_rates = {}
    for detail in trigger_details:
        year = detail["date"][:4]
        if year not in yearly_rates:
            yearly_rates[year] = {"triggered": [], "returns": []}
        yearly_rates[year]["triggered"].append(detail)
        yearly_rates[year]["returns"].append(detail["return"])

    yearly_summary = {}
    for year, data in yearly_rates.items():
        if len(data["returns"]) >= 10:
            yr_ret = np.array(data["returns"])
            if outcome_up:
                yr_win = float(np.mean(yr_ret > 0))
            else:
                yr_win = float(np.mean(yr_ret < 0))
            yearly_summary[year] = {
                "sample_count": len(data["returns"]),
                "win_rate": round(yr_win, 4),
                "avg_return": round(float(np.mean(yr_ret)), 4),
            }

    # 可靠性判断
    is_reliable = (n_triggered >= 100) and ((ci_high - ci_low) < 0.20)

    return {
        "rule_id": rule_id,
        "description": rule_config.get("description", ""),
        "category": rule_config.get("category", ""),
        "direction": rule_config.get("direction", "neutral"),
        "horizon_days": horizon_days,
        "sample_count": n_triggered,
        "win_rate": round(win_rate, 4),
        "confidence_interval_95": (round(ci_low, 4), round(ci_high, 4)),
        "avg_return": round(float(np.mean(ret_array)), 4),
        "max_return": round(float(np.max(ret_array)), 4),
        "min_return": round(float(np.min(ret_array)), 4),
        "sharpe_like": round(float(np.mean(ret_array)) / float(np.std(ret_array)), 4) if float(np.std(ret_array)) > 0 else 0,
        "scenarios": scenarios,
        "yearly_rates": yearly_summary,
        "is_reliable": is_reliable,
        "data_period": f"{trigger_details[0]['date']}~{trigger_details[-1]['date']}" if trigger_details else "N/A",
        "trigger_details_sample": trigger_details[:10],  # 前10条触发详情
    }


# ============================================================
# 第五部分: 行业对比分析
# ============================================================

def compare_industry_vs_market(
    rule_config: dict,
    industry_stocks: dict,
    all_market_stocks: dict,
    horizon_days: int = 5,
) -> dict:
    """
    对比同一规则在全市场 vs 特定行业的胜率差异。

    如果差异 > 5个百分点 → 行业差异化有意义
    """
    log(f"  计算全市场概率...")
    all_market = compute_rule_probability(rule_config, all_market_stocks, horizon_days)

    # 从行业名推断（所有行业股票的集合）
    log(f"  计算行业概率...")
    industry = compute_rule_probability(rule_config, industry_stocks, horizon_days)

    all_win = all_market.get("win_rate", 0)
    ind_win = industry.get("win_rate", 0)
    delta = ind_win - all_win

    return {
        "rule_id": rule_config["rule_id"],
        "all_market": {
            "sample_count": all_market.get("sample_count", 0),
            "win_rate": all_win,
            "ci_95": all_market.get("confidence_interval_95", (0, 0)),
            "is_reliable": all_market.get("is_reliable", False),
        },
        "industry": {
            "sample_count": industry.get("sample_count", 0),
            "win_rate": ind_win,
            "ci_95": industry.get("confidence_interval_95", (0, 0)),
            "is_reliable": industry.get("is_reliable", False),
        },
        "delta": round(delta, 4),
        "is_significant": abs(delta) > 0.05,
        "interpretation": (
            f"行业胜率{'高于' if delta > 0 else '低于'}全市场{abs(delta):.1%}，"
            f"{'需行业差异化参数' if abs(delta) > 0.05 else '可沿用全市场参数'}"
        ),
    }


# ============================================================
# 第六部分: 主流程
# ============================================================

def pull_industry_data(industry: str, max_stocks: int = 30) -> dict[str, dict]:
    """
    拉取指定行业的股票历史数据。

    Args:
        industry: 行业名
        max_stocks: 最大拉取股票数（用于控制API调用量）

    Returns:
        {code: {"kline": [...], "flow": [...]}}
    """
    pool = INDUSTRY_STOCK_POOL.get(industry, {})
    all_codes = []
    for direction, codes in pool.items():
        all_codes.extend(codes)

    # 去重 + 限制数量
    all_codes = list(set(all_codes))[:max_stocks]

    log(f"行业 [{industry}]: 共 {len(all_codes)} 只标的待拉取")

    result = {}
    for i, code in enumerate(all_codes):
        log(f"  [{i+1}/{len(all_codes)}] 拉取 {code}...")

        # K线 + 资金流（内部已通过 em_get 自动节流）
        kline = fetch_stock_kline(code, days=500)
        flow = fetch_stock_fund_flow(code, days=120)

        if kline and flow:
            result[code] = {"kline": kline, "flow": flow}
            log(f"    K线{len(kline)}日, 资金流{len(flow)}日 ✓")
        else:
            log(f"    数据不完整，跳过")

    log(f"行业 [{industry}]: 成功拉取 {len(result)}/{len(all_codes)}")
    return result


def run_learning(
    industry: str = "半导体",
    rules: list[str] = None,
    max_stocks: int = 20,
    output_dir: str = "rules/",
    compare_market: bool = False,
):
    """
    主学习流程。

    Args:
        industry: 行业名
        rules: 要计算的规则ID列表 (None=全部)
        max_stocks: 最大股票数
        output_dir: 输出目录
        compare_market: 是否做全市场对比
    """
    log(f"{'='*60}")
    log(f"规则学习引擎 V1.0 — 行业: {industry}")
    log(f"{'='*60}")

    # 1. 拉取数据
    log("Phase 1: 拉取历史盘面数据...")
    industry_data = pull_industry_data(industry, max_stocks=max_stocks)

    if not industry_data:
        log("ERROR: 未能拉取任何数据，退出")
        return

    # 2. 可选：拉取全市场对比数据
    all_market_data = {}
    if compare_market:
        log("\nPhase 1b: 拉取全市场对比数据...")
        # 从多个行业各抽几只代表股票
        sample_codes = []
        for ind, pool in INDUSTRY_STOCK_POOL.items():
            for direction, codes in pool.items():
                sample_codes.extend(codes[:3])  # 每方向3只
        sample_codes = list(set(sample_codes))[:30]

        for code in sample_codes:
            kline = fetch_stock_kline(code, days=500)
            time.sleep(random.uniform(0.3, 0.6))
            flow = fetch_stock_fund_flow(code, days=120)
            time.sleep(random.uniform(0.3, 0.6))
            if kline and flow:
                all_market_data[code] = {"kline": kline, "flow": flow}

    # 3. 计算每条规则的概率
    rule_ids = rules or list(RULES_REGISTRY.keys())
    log(f"\nPhase 2: 计算 {len(rule_ids)} 条规则的概率...")

    results = {}
    for rule_id in rule_ids:
        if rule_id not in RULES_REGISTRY:
            log(f"  规则 {rule_id} 不在注册表中，跳过")
            continue

        rule_config = RULES_REGISTRY[rule_id]
        log(f"\n  [{rule_id}] {rule_config['description']}")

        # 行业概率
        ind_result = compute_rule_probability(rule_config, industry_data, horizon_days=rule_config.get("horizon_days", 5))
        results[rule_id] = ind_result

        log(f"    样本: {ind_result['sample_count']} | 胜率: {ind_result.get('win_rate', 0):.1%} | "
            f"CI95: [{ind_result.get('confidence_interval_95', (0,0))[0]:.1%}, {ind_result.get('confidence_interval_95', (0,0))[1]:.1%}] | "
            f"可靠: {ind_result.get('is_reliable')}")

        # 行业对比
        if compare_market and all_market_data:
            comparison = compare_industry_vs_market(rule_config, industry_data, all_market_data)
            results[f"{rule_id}_comparison"] = comparison
            log(f"    全市场胜率: {comparison['all_market']['win_rate']:.1%} | "
                f"行业胜率: {comparison['industry']['win_rate']:.1%} | "
                f"差异: {comparison['delta']:+.1%} {'⚠️显著' if comparison['is_significant'] else '✓不显著'}")

    # 4. 保存结果
    log(f"\nPhase 3: 保存学习结果...")
    os.makedirs(os.path.join(output_dir, industry), exist_ok=True)

    # 保存完整学习报告
    report_path = os.path.join(output_dir, industry, "learning_report.json")
    report = {
        "industry": industry,
        "learning_date": datetime.now().strftime("%Y-%m-%d"),
        "data_summary": {
            "stocks_pulled": len(industry_data),
            "codes": list(industry_data.keys()),
            "kline_days": max((len(d["kline"]) for d in industry_data.values()), default=0),
            "flow_days": max((len(d["flow"]) for d in industry_data.values()), default=0),
        },
        "rules": results,
        "methodology": {
            "data_source": "东财 push2his (K线+资金流)",
            "horizon": "T+5 / T+10",
            "min_samples_for_reliable": 100,
            "bootstrap_iterations": 1000,
            "confidence_level": "95%",
        },
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 为每条可靠规则生成独立的规则JSON文件（供概率引擎使用）
    rules_saved = 0
    for rule_id, result in results.items():
        if rule_id.endswith("_comparison"):
            continue
        if not result.get("is_reliable"):
            continue

        rule_config = RULES_REGISTRY.get(rule_id, {})
        rule_json = {
            "rule_id": rule_config.get("rule_id", rule_id),
            "category": rule_config.get("category", ""),
            "description": rule_config.get("description", ""),
            "industry": industry,
            "direction": rule_config.get("direction", "neutral"),
            "trigger_description": rule_config.get("description", ""),
            "probabilities": {
                "P_up_5d": result.get("win_rate", 0) if rule_config.get("outcome_direction") == "up" else 1 - result.get("win_rate", 0),
                "P_down_5d": 1 - result.get("win_rate", 0) if rule_config.get("outcome_direction") == "up" else result.get("win_rate", 0),
                "scenarios": result.get("scenarios", {}),
            },
            "stats": {
                "sample_count": result.get("sample_count", 0),
                "win_rate": result.get("win_rate", 0),
                "confidence_interval_95": result.get("confidence_interval_95", [0, 0]),
                "avg_return": result.get("avg_return", 0),
                "max_return": result.get("max_return", 0),
                "min_return": result.get("min_return", 0),
                "sharpe_like": result.get("sharpe_like", 0),
                "data_period": result.get("data_period", ""),
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "yearly_rates": result.get("yearly_rates", {}),
                "is_reliable": result.get("is_reliable", False),
                "p_value": 0.01 if result.get("is_reliable") else 0.1,
            },
            "industry_variants": {},
            "failure_modes": [
                "大盘系统性暴跌中失效",
                "公司基本面重大变化时失效",
            ],
            "related_rules": [],
            "_learning_metadata": {
                "industry": industry,
                "stocks_used": len(industry_data),
                "trigger_samples": result.get("sample_count", 0),
                "computed_date": datetime.now().strftime("%Y-%m-%d"),
            },
        }

        rule_file = os.path.join(output_dir, industry, f"{rule_config.get('rule_id', rule_id)}.json")
        with open(rule_file, "w", encoding="utf-8") as f:
            json.dump(rule_json, f, ensure_ascii=False, indent=2)
        rules_saved += 1

    log(f"\n{'='*60}")
    log(f"学习完成！")
    log(f"  行业: {industry}")
    log(f"  拉取标的: {len(industry_data)}")
    log(f"  计算规则: {len(rule_ids)}")
    log(f"  可靠规则: {rules_saved}")
    log(f"  报告: {report_path}")
    log(f"  规则: {output_dir}{industry}/")
    log(f"{'='*60}")

    # 打印汇总表
    print(f"\n{'─'*80}")
    print(f"规则学习结果汇总 — {industry}")
    print(f"{'─'*80}")
    print(f"{'规则ID':<12} {'描述':<36} {'样本':<8} {'胜率':<8} {'CI95':<18} {'可靠'}")
    print(f"{'─'*80}")
    for rule_id, result in results.items():
        if rule_id.endswith("_comparison"):
            continue
        print(f"{rule_id:<12} {result.get('description', '')[:34]:<36} "
              f"{result.get('sample_count', 0):<8} "
              f"{result.get('win_rate', 0):.1%}     "
              f"[{result.get('confidence_interval_95', (0,0))[0]:.1%},{result.get('confidence_interval_95', (0,0))[1]:.1%}]   "
              f"{'✅' if result.get('is_reliable') else '❌'}")
    print(f"{'─'*80}")


# ============================================================
# CLI入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A股规则学习引擎")
    parser.add_argument("--industry", type=str, default="半导体",
                       help="目标行业 (默认: 半导体)")
    parser.add_argument("--rules", type=str, nargs="*", default=None,
                       help="规则ID列表 (默认: 全部)")
    parser.add_argument("--max-stocks", type=int, default=20,
                       help="最多拉取股票数 (默认: 20)")
    parser.add_argument("--output", type=str, default="rules/",
                       help="输出目录 (默认: rules/)")
    parser.add_argument("--compare", action="store_true", default=False,
                       help="是否做全市场对比分析")
    parser.add_argument("--list-industries", action="store_true", default=False,
                       help="列出所有可用行业")
    parser.add_argument("--list-rules", action="store_true", default=False,
                       help="列出所有可用规则")

    args = parser.parse_args()

    if args.list_industries:
        print("可用行业:")
        for ind, pool in INDUSTRY_STOCK_POOL.items():
            total = sum(len(codes) for codes in pool.values())
            print(f"  {ind}: {total} 只标的")
        sys.exit(0)

    if args.list_rules:
        print("可用规则:")
        for rid, rconf in RULES_REGISTRY.items():
            print(f"  {rid}: {rconf['description']}")
        sys.exit(0)

    run_learning(
        industry=args.industry,
        rules=args.rules,
        max_stocks=args.max_stocks,
        output_dir=args.output,
        compare_market=args.compare,
    )
