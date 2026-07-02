#!/usr/bin/env python3
"""
老登股全市场筛选脚本
====================
实现 old-guard-stocks skill 的完整筛选漏斗：
持续盈利 → 护城河判断 → 财报可信度 → 毛利率验证 → 估值错杀识别 → 综合评分

用法: python3 scripts/old_guard_screener.py
"""

import urllib.request
import requests
import json
import time
import re
import sys
import os
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# 配置
# ============================================================
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

TODAY = datetime.now().strftime("%Y-%m-%d")

# 候选池：各行业龙头 + 知名蓝筹（手动精选 ~50 只）
CANDIDATE_POOL = {
    "白酒": {
        "industry_avg_gross_margin": 70.0,  # 行业平均毛利率参考
        "stocks": ["600519", "000858", "000568", "002304", "000596"],
    },
    "保险": {
        "industry_avg_gross_margin": None,  # 金融行业不用毛利率
        "stocks": ["601318", "601628", "601601", "601336"],
    },
    "银行": {
        "industry_avg_gross_margin": None,
        "stocks": ["601398", "601939", "601288", "600036", "000001", "601166"],
    },
    "家电": {
        "industry_avg_gross_margin": 28.0,
        "stocks": ["000333", "000651", "600690"],
    },
    "医药": {
        "industry_avg_gross_margin": 55.0,
        "stocks": ["600276", "000538", "300760", "000963"],
    },
    "新能源": {
        "industry_avg_gross_margin": 25.0,
        "stocks": ["300750", "601012", "002594"],
    },
    "食品饮料": {
        "industry_avg_gross_margin": 38.0,
        "stocks": ["600887", "603288", "000895"],
    },
    "煤炭": {
        "industry_avg_gross_margin": 35.0,
        "stocks": ["601088", "601225", "600188"],
    },
    "电力": {
        "industry_avg_gross_margin": 40.0,
        "stocks": ["600900", "003816", "601985"],
    },
    "通信": {
        "industry_avg_gross_margin": 30.0,
        "stocks": ["600941", "601728"],
    },
    "有色": {
        "industry_avg_gross_margin": 18.0,
        "stocks": ["601899", "600362"],
    },
    "化工": {
        "industry_avg_gross_margin": 25.0,
        "stocks": ["600309"],
    },
    "建材": {
        "industry_avg_gross_margin": 28.0,
        "stocks": ["600585"],
    },
    "汽车": {
        "industry_avg_gross_margin": 15.0,
        "stocks": ["600104"],
    },
}

# ============================================================
# 数据层：复用 a-stock-data 的核心函数
# ============================================================

def tencent_quote(codes: list) -> dict:
    """批量拉取腾讯财经实时行情"""
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")): prefixed.append(f"sh{c}")
        elif c.startswith("8"): prefixed.append(f"bj{c}")
        else: prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode("gbk")

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line: continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53: continue
        code = key[2:]
        result[code] = {
            "name":         vals[1],
            "price":        float(vals[3]) if vals[3] else 0,
            "last_close":   float(vals[4]) if vals[4] else 0,
            "open":         float(vals[5]) if vals[5] else 0,
            "change_pct":   float(vals[32]) if vals[32] else 0,
            "high_52w":     float(vals[41]) if vals[41] else 0,   # 52周最高
            "low_52w":      float(vals[42]) if vals[42] else 0,   # 52周最低
            "pe_ttm":       float(vals[39]) if vals[39] else 0,
            "pb":           float(vals[46]) if vals[46] else 0,
            "mcap":         float(vals[45]) if vals[45] else 0,   # 市值(亿)
            "volume":       float(vals[6]) if vals[6] else 0,
            "turnover":     float(vals[38]) if vals[38] else 0,
        }
    return result


def sina_financial_report(code: str, report_type: str = "lrb", num: int = 8) -> list:
    """
    新浪财报三表
    report_type: "lrb"(利润表) / "fzb"(资产负债表) / "llb"(现金流量表)
    """
    prefix = "sh" if code.startswith("6") else "sz"
    paper_code = f"{prefix}{code}"
    url = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
    params = {
        "paperCode": paper_code,
        "source": report_type,
        "type": "0",
        "page": "1",
        "num": str(num),
    }
    headers = {"User-Agent": UA}
    r = requests.get(url, params=params, headers=headers, timeout=15)
    report_list = r.json().get("result", {}).get("data", {}).get("report_list", {}) or {}

    rows = []
    for period in sorted(report_list.keys(), reverse=True)[:num]:
        obj = report_list[period]
        rec = {"报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
        for it in obj.get("data", []) or []:
            title = it.get("item_title", "")
            if not title or it.get("item_value") is None: continue
            rec[title] = it.get("item_value")
            tongbi = it.get("item_tongbi")
            if tongbi not in (None, ""):
                rec[title + "_同比"] = tongbi
        rows.append(rec)
    return rows


# ============================================================
# 维度一：持续盈利能力验证（硬门槛）
# ============================================================

def check_sustained_profitability(code: str, industry: str = "") -> tuple:
    """
    四项硬门槛，全部通过返回 (True, detail_dict)，否则 (False, fail_reason)
    """
    detail = {}
    try:
        lrb = sina_financial_report(code, "lrb", num=8)
        if len(lrb) < 8:
            return False, {"fail": f"仅{len(lrb)}期利润表数据"}

        # 1. 净利润连续性：8季全部 > 0
        net_profits = []
        for p in lrb:
            np_val = float(p.get("净利润", 0))
            net_profits.append((p["报告期"], np_val))

        all_positive = all(np > 0 for _, np in net_profits)
        detail["net_profits"] = net_profits
        detail["all_positive"] = all_positive
        if not all_positive:
            return False, {**detail, "fail": "存在季度净利润≤0"}

        # 2. 营收稳定性：无连续3季同比下降且平均降幅>10%（金融行业放宽至连续5季）
        rev_yoy_list = []
        for p in lrb:
            yoy = p.get("营业收入_同比")
            if yoy is None or yoy == "":
                # 尝试"营业总收入_同比"作为备选
                yoy = p.get("营业总收入_同比")
            if yoy not in (None, ""):
                rev_yoy_list.append(float(yoy))  # 新浪原始是小数（0.05=5%）

        max_consecutive_decline = 0
        current_decline = 0
        current_decline_vals = []
        for yoy in rev_yoy_list:
            if yoy < -0.05:  # 同比下降超过5%才算（排除微幅波动）
                current_decline += 1
                current_decline_vals.append(yoy)
                max_consecutive_decline = max(max_consecutive_decline, current_decline)
            else:
                current_decline = 0
                current_decline_vals = []
        detail["rev_yoy_list"] = [round(v*100,1) for v in rev_yoy_list]  # 转百分比便于阅读
        detail["max_consecutive_decline"] = max_consecutive_decline
        if max_consecutive_decline >= 4:
            return False, {**detail, "fail": f"连续{max_consecutive_decline}季营收同比降幅>5%"}

        # 3. 经营现金流：最近 4 季累计 > 0
        llb = sina_financial_report(code, "llb", num=4)
        total_oper_cf = sum(float(p.get("经营活动产生的现金流量净额", 0)) for p in llb)
        detail["total_oper_cf"] = total_oper_cf
        detail["oper_cf_positive"] = total_oper_cf > 0
        if total_oper_cf <= 0:
            return False, {**detail, "fail": "近4季累计经营现金流≤0"}

        # 4. ROE（用近4季净利润 / 最新净资产 近似估算）
        fzb = sina_financial_report(code, "fzb", num=4)
        latest_equity = 0
        for p in fzb:
            # 金融行业可能用不同科目名，尝试多个键
            for key in ("归属于母公司股东权益合计", "归属于母公司所有者权益合计",
                         "股东权益合计", "所有者权益合计"):
                eq = float(p.get(key, 0))
                if eq > 0:
                    latest_equity = eq
                    break
            if latest_equity > 0:
                break

        if latest_equity > 0:
            annual_np = sum(np for _, np in net_profits[:4])
            roe = annual_np / latest_equity * 100
            detail["roe"] = round(roe, 1)
            # 金融行业 ROE 门槛提高到 10%，其他行业 8%
            min_roe = 10 if industry in ("保险", "银行") else 8
            detail["roe_pass"] = roe > min_roe
            if roe <= min_roe:
                return False, {**detail, "fail": f"ROE={roe:.1f}%≤{min_roe}%"}
        else:
            # 无法计算 ROE → 用净利润绝对值和趋势替代判断
            # 只要8季全部盈利 + 近4季净利润 > 10亿，视为通过
            annual_np_approx = sum(np for _, np in net_profits[:4])
            if annual_np_approx > 10e8:  # >10亿
                detail["roe"] = None
                detail["roe_pass"] = True  # 大额盈利替代ROE判断
            else:
                detail["roe"] = None
                detail["roe_pass"] = False
                return False, {**detail, "fail": "无法计算ROE且净利润规模不足"}

        return True, detail

    except Exception as e:
        return False, {"fail": f"数据拉取异常: {str(e)}"}


# ============================================================
# 维度二：护城河快速判断（依赖后续毛利率+WebSearch）
# ============================================================

def quick_moat_assess(code: str, name: str, industry: str, quotes_data: dict,
                       gross_margin_detail: dict, industry_stocks: list) -> dict:
    """
    5类护城河快速判断，返回 {类型: "强"/"中"/"弱", reason: str}
    依赖已在前面步骤计算好的毛利率、行情数据
    """
    moat = {}
    industry_avg_margin = CANDIDATE_POOL.get(industry, {}).get("industry_avg_gross_margin")

    # 1. 品牌壁垒 → 毛利率是否持续高于行业平均
    if industry_avg_margin and gross_margin_detail.get("avg_margin"):
        avg_m = gross_margin_detail["avg_margin"]
        if avg_m > industry_avg_margin + 15:  # 显著高于行业
            moat["品牌壁垒"] = ("强", f"毛利率{avg_m:.0f}% vs 行业{industry_avg_margin:.0f}%，溢价+{avg_m-industry_avg_margin:.0f}pp")
        elif avg_m > industry_avg_margin + 5:
            moat["品牌壁垒"] = ("中", f"毛利率{avg_m:.0f}% vs 行业{industry_avg_margin:.0f}%，有一定溢价")
        else:
            moat["品牌壁垒"] = ("弱", f"毛利率{avg_m:.0f}% vs 行业{industry_avg_margin:.0f}%，无显著溢价")
    else:
        moat["品牌壁垒"] = ("弱", "无行业毛利率参考（金融行业不适用）")

    # 2. 规模壁垒 → 市值在行业中排名
    all_mcaps = []
    for s in industry_stocks:
        if s in quotes_data:
            all_mcaps.append((s, quotes_data[s].get("mcap", 0)))
    all_mcaps.sort(key=lambda x: x[1], reverse=True)
    rank = next((i+1 for i, (s, _) in enumerate(all_mcaps) if s == code), len(all_mcaps)+1)
    if rank == 1:
        moat["规模壁垒"] = ("强", f"行业市值第{rank}（{all_mcaps[0][1]:.0f}亿）")
    elif rank <= 3:
        moat["规模壁垒"] = ("中", f"行业市值第{rank}")
    else:
        moat["规模壁垒"] = ("弱", f"行业市值第{rank}，非头部")

    # 3-5. 技术/牌照/客户粘性 → 占位，后续 WebSearch 补充
    # 默认先给"弱"，实际应通过 WebSearch 验证
    info = f"{name}({code})"
    moat["技术壁垒"] = ("待查", "通过WebSearch验证核心专利/技术优势")
    moat["牌照壁垒"] = ("待查", "通过WebSearch验证牌照/准入限制")
    moat["客户粘性"] = ("待查", "通过WebSearch验证客户绑定深度")

    return moat


# ============================================================
# 辅助排查：财报可信度（6 项红旗）
# ============================================================

def check_red_flags(code: str, lrb_data: list) -> tuple:
    """
    检查 6 项红旗，返回 (红旗数, [红旗详情])
    注意：部分红旗（大股东质押、审计意见）需 WebSearch，此处标记为待查
    """
    flags = []

    try:
        fzb = sina_financial_report(code, "fzb", num=4)
        llb = sina_financial_report(code, "llb", num=4)

        # 1. 应收/营收比 > 60%
        latest_receivables = 0
        latest_revenue = 0
        for p in fzb:
            recv = float(p.get("应收账款", 0))
            if recv > 0:
                latest_receivables = recv
                break
        for p in lrb_data:
            rev = float(p.get("营业收入", 0))
            if rev > 0:
                latest_revenue = rev
                break
        if latest_revenue > 0:
            ratio = latest_receivables / latest_revenue * 100
            if ratio > 60:
                flags.append(f"🔴 应收/营收比={ratio:.1f}% > 60%")

        # 2. 经营现金流背离（连续4季净利润>0但经营现金流<0）
        net_profits_ok = all(float(p.get("净利润", 0)) > 0 for p in lrb_data[:4])
        oper_cf_negative = sum(float(p.get("经营活动产生的现金流量净额", 0)) for p in llb[:4]) < 0
        if net_profits_ok and oper_cf_negative:
            flags.append("🔴 连续4季盈利但经营现金流为负（纸面富贵）")

        # 3. 存货异常膨胀
        inventories = []
        for p in fzb[:4]:
            inv = float(p.get("存货", 0))
            rev_q = float(lrb_data[len(inventories)].get("营业收入", 0)) if len(inventories) < len(lrb_data) else 0
            if inv > 0:
                inventories.append((p["报告期"], inv))
        if len(inventories) >= 3:
            inv_growth = (inventories[0][1] - inventories[-1][1]) / inventories[-1][1] * 100
            rev_growth = 0
            rev_first = float(lrb_data[0].get("营业收入", 0))
            rev_last = float(lrb_data[min(len(inventories)-1, len(lrb_data)-1)].get("营业收入", 0))
            if rev_last > 0:
                rev_growth = (rev_first - rev_last) / rev_last * 100
            if inv_growth > rev_growth * 2 and inv_growth > 20:
                flags.append(f"🔴 存货增速{inv_growth:.0f}% > 营收增速{rev_growth:.0f}%×2")

        # 4. 商誉/净资产 > 50%
        goodwill = 0
        equity = 0
        for p in fzb:
            gw = float(p.get("商誉", 0))
            eq = float(p.get("归属于母公司股东权益合计", 0))
            if gw > 0: goodwill = gw
            if eq > 0: equity = eq
            if goodwill > 0 and equity > 0: break
        if equity > 0 and goodwill / equity > 0.5:
            flags.append(f"🔴 商誉/净资产={(goodwill/equity*100):.1f}% > 50%（减值风险）")

        # 5-6. 大股东质押 + 审计意见 → WebSearch 待查（暂不标记）
        flags.append("🟡 大股东质押比例+审计意见需WebSearch验证")

    except Exception as e:
        flags.append(f"⚠️ 红旗检查异常: {str(e)}")

    red_count = len([f for f in flags if f.startswith("🔴")])
    return red_count, flags


# ============================================================
# 辅助验证：毛利率趋势
# ============================================================

def analyze_gross_margin(lrb_data: list, industry_avg: float | None) -> dict:
    """分析 8 季毛利率趋势"""
    margins = []
    for p in lrb_data:
        rev = float(p.get("营业收入", 0))
        cost = float(p.get("营业成本", 0))
        if rev > 0:
            m = (rev - cost) / rev * 100
            margins.append((p["报告期"], round(m, 1)))

    if not margins:
        return {"avg_margin": None, "trend": "无数据", "stability": "无数据", "quality": "不合格"}

    values = [m[1] for m in margins]
    avg_margin = sum(values) / len(values)
    trend_dir = "上升" if values[0] > values[-1] else ("下降" if values[0] < values[-1] else "稳定")
    volatility = max(values) - min(values)

    if industry_avg:
        if avg_margin > industry_avg + 5 and volatility < 3:
            quality = "优质"
        elif avg_margin >= industry_avg and volatility < 5:
            quality = "合格"
        else:
            quality = "不合格"
    else:
        # 金融行业：不适用毛利率
        quality = "不适用(金融)"

    return {
        "avg_margin": round(avg_margin, 1),
        "trend": trend_dir,
        "volatility": round(volatility, 1),
        "quality": quality,
        "quarterly": margins,
    }


# ============================================================
# 核心：估值错杀识别
# ============================================================

def evaluate_mispricing(code: str, name: str, quotes_data: dict,
                         net_profits: list, industry: str) -> dict:
    """估值压缩程度 + 盈利-估值背离度"""
    q = quotes_data.get(code, {})
    pe = q.get("pe_ttm", 0)
    pb = q.get("pb", 0)
    mcap = q.get("mcap", 0)
    price = q.get("price", 0)
    high_52w = q.get("high_52w", 0)

    # 股价回撤
    if high_52w > 0:
        drawdown = (high_52w - price) / high_52w * 100
    else:
        drawdown = 0

    # PE 分位估算（简化：基于常识和行业经验）
    # 真实场景应用 mootdx 拉3年K线结合利润表计算历史PE区间
    # 这里用行业常用PE区间做参考
    pe_ranges = {
        "白酒": (15, 60), "保险": (6, 20), "银行": (4, 12),
        "家电": (10, 25), "医药": (25, 80), "新能源": (15, 60),
        "食品饮料": (20, 55), "煤炭": (6, 18), "电力": (12, 28),
        "通信": (8, 20), "有色": (12, 35), "化工": (12, 30),
        "建材": (8, 20), "汽车": (8, 25),
    }
    pe_min, pe_max = pe_ranges.get(industry, (10, 40))
    # PE分位: PE越接近历史低位 → 分位越低 → 越便宜
    # 公式: (PE - min) / (max - min) × 100，低分位 = 便宜 = 好事
    if pe_max > pe_min and pe > 0:
        pe_percentile = max(0, min(100, (pe - pe_min) / (pe_max - pe_min) * 100))
    else:
        pe_percentile = 50  # 默认中位

    # 估值压缩程度打分
    pe_score = 1
    if pe_percentile < 20: pe_score = 5
    elif pe_percentile < 35: pe_score = 4
    elif pe_percentile < 50: pe_score = 3
    elif pe_percentile < 70: pe_score = 2

    dd_score = 1
    if drawdown > 30: dd_score = 5
    elif drawdown > 20: dd_score = 4
    elif drawdown > 15: dd_score = 3
    elif drawdown > 10: dd_score = 2

    compression_score = (pe_score * 0.6 + dd_score * 0.4)

    # 盈利趋势分位
    np_values = [v for _, v in net_profits]
    growth = 0
    if len(np_values) >= 4:
        recent_avg = sum(np_values[:4]) / 4
        older_avg = sum(np_values[4:]) / 4
        growth = (recent_avg - older_avg) / older_avg * 100 if older_avg > 0 else 0

        # 波动性
        cv = 0
        if recent_avg > 0:
            std = (sum((v - recent_avg)**2 for v in np_values[:4]) / 4) ** 0.5
            cv = std / recent_avg

        if growth > 5 and cv < 0.15:
            profit_trend_score = 85  # 增长+稳定
        elif growth > 0 and cv < 0.25:
            profit_trend_score = 75
        elif cv < 0.2:
            profit_trend_score = 65  # 稳定但无明显增长
        elif growth > 0:
            profit_trend_score = 55
        else:
            profit_trend_score = 45  # 轻微下滑
    else:
        profit_trend_score = 50
        growth = 0

    # 背离度 = profit_trend_score - pe_percentile
    # 重新理解：pe_percentile 越低 = PE越便宜 = 越好
    # 背离度的含义：盈利越好(高分位)但PE越低(低分位) → 背离大 → 错杀严重
    # 实际：profit_trend_score 高(好) + pe_percentile 低 = 背离度大
    divergence = profit_trend_score - pe_percentile

    div_score = 1
    if divergence > 40: div_score = 5
    elif divergence > 25: div_score = 4
    elif divergence > 15: div_score = 3
    elif divergence > 5: div_score = 2

    # 错杀场景判断
    if divergence > 25 and drawdown > 20:
        scenario = "A: 泥沙俱下"
    elif divergence > 15 and drawdown > 15:
        scenario = "A/B: 可能错杀"
    elif pe_percentile < 30 and profit_trend_score > 60:
        scenario = "B: 短期利空砸出估值坑"
    else:
        scenario = "非典型错杀"

    return {
        "pe": pe, "pb": pb, "mcap": mcap, "price": price,
        "drawdown": round(drawdown, 1),
        "pe_percentile": round(pe_percentile, 1),
        "profit_trend_score": profit_trend_score,
        "divergence": round(divergence, 1),
        "compression_score": round(compression_score, 1),
        "div_score": div_score,
        "scenario": scenario,
        "growth": round(growth, 1),
    }


# ============================================================
# 综合评分 + 定级
# ============================================================

def composite_score(moat_result: dict, mispricing: dict, margin_detail: dict,
                    red_flag_count: int, bonus_penalty: float = 0) -> tuple:
    """综合得分公式"""
    # 护城河强度折算
    moat_strong = sum(1 for v in moat_result.values() if isinstance(v, tuple) and v[0] == "强")
    moat_mid = sum(1 for v in moat_result.values() if isinstance(v, tuple) and v[0] == "中")

    if moat_strong >= 2:
        moat_score = 5
    elif moat_strong == 1:
        moat_score = 4
    elif moat_mid >= 3:
        moat_score = 4
    elif moat_mid >= 2:
        moat_score = 3
    elif moat_mid == 1:
        moat_score = 2
    else:
        moat_score = 1

    # 毛利率得分
    mq = margin_detail.get("quality", "不合格")
    if mq == "优质": margin_score = 5
    elif mq == "合格": margin_score = 3
    elif "金融" in str(mq): margin_score = 3  # 金融行业中性
    else: margin_score = 1

    # 财报可信度（红旗越少越高）
    if red_flag_count == 0: credit_score = 5
    elif red_flag_count == 1: credit_score = 2
    else: credit_score = 0  # ≥2 面红旗直接排除

    total = (
        mispricing["compression_score"] * 0.25 +
        mispricing["div_score"] * 0.25 +
        moat_score * 0.20 +
        margin_score * 0.15 +
        credit_score * 0.15 +
        bonus_penalty
    )

    if total >= 4.0: grade = "⭐⭐⭐ 核心老登"
    elif total >= 3.0: grade = "⭐⭐ 优质老登"
    elif total >= 2.0: grade = "⭐ 观察老登"
    else: grade = "不入池"

    return round(total, 2), grade


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 80)
    print(f"🏛️ 老登股全市场扫描 — {TODAY}")
    print("=" * 80)
    print(f"漏斗: 候选池 → 持续盈利 → 护城河 → 财报可信 → 毛利率 → 估值错杀 → 综合评分\n")

    # Step 1-2: 构建候选池
    all_codes = []
    code_to_industry = {}
    for industry, info in CANDIDATE_POOL.items():
        for code in info["stocks"]:
            all_codes.append(code)
            code_to_industry[code] = industry

    print(f"📋 Step 1-2: 候选池 {len(all_codes)} 只（{len(CANDIDATE_POOL)} 个行业）")

    # 批量拉行情
    print("📡 拉取实时行情...")
    quotes = tencent_quote(all_codes)
    print(f"   获取 {len(quotes)} 只股票行情\n")

    # Step 3-8: 逐只分析
    results = []
    passed_profit = 0
    passed_moat = 0
    passed_redflag = 0

    for i, code in enumerate(all_codes):
        industry = code_to_industry[code]
        name = quotes.get(code, {}).get("name", "未知")
        print(f"[{i+1}/{len(all_codes)}] {code} {name} ({industry})...", end=" ", flush=True)

        # Step 3: 持续盈利能力
        profit_ok, profit_detail = check_sustained_profitability(code, industry)
        if not profit_ok:
            print(f"❌ 盈利: {profit_detail.get('fail', '不通过')}")
            continue
        passed_profit += 1
        print("✅盈利", end=" ", flush=True)

        # 拉取完整财报数据
        try:
            lrb = sina_financial_report(code, "lrb", num=8)
        except:
            print("❌ 财报拉取失败")
            continue

        # Step 5: 财报可信度
        red_count, red_flags = check_red_flags(code, lrb)
        if red_count >= 2:
            print(f"❌ 红旗{red_count}面(≥2排除)")
            continue
        passed_redflag += 1

        # Step 6: 毛利率
        industry_avg_margin = CANDIDATE_POOL.get(industry, {}).get("industry_avg_gross_margin")
        margin_detail = analyze_gross_margin(lrb, industry_avg_margin)

        # Step 4: 护城河快速判断
        industry_stocks = CANDIDATE_POOL.get(industry, {}).get("stocks", [])
        moat_result = quick_moat_assess(code, name, industry, quotes, margin_detail, industry_stocks)

        # 护城河硬门槛检查
        moat_strong = sum(1 for v in moat_result.values() if isinstance(v, tuple) and v[0] == "强")
        moat_mid = sum(1 for v in moat_result.values() if isinstance(v, tuple) and v[0] == "中")
        if moat_strong == 0 and moat_mid < 2:
            print(f"❌ 护城河不足(强{moat_strong}/中{moat_mid})")
            continue
        passed_moat += 1

        # Step 7: 估值错杀识别
        net_profits = profit_detail.get("net_profits", [])
        mispricing = evaluate_mispricing(code, name, quotes, net_profits, industry)

        # Step 8: 综合评分
        score, grade = composite_score(moat_result, mispricing, margin_detail, red_count)

        print(f"✅ 得分{score} {grade} 背离度{mispricing['divergence']}")

        results.append({
            "code": code, "name": name, "industry": industry,
            "profit_detail": profit_detail,
            "moat_result": moat_result,
            "moat_strong_count": moat_strong,
            "moat_mid_count": moat_mid,
            "red_count": red_count,
            "red_flags": red_flags,
            "margin_detail": margin_detail,
            "mispricing": mispricing,
            "score": score,
            "grade": grade,
        })

        time.sleep(0.3)  # 友好限流

    # ============================================================
    # 输出报告
    # ============================================================
    results.sort(key=lambda x: x["score"], reverse=True)

    print("\n" + "=" * 80)
    print(f"📊 筛选结果总览")
    print("=" * 80)
    print(f"候选池: {len(all_codes)} → 持续盈利: {passed_profit} → 护城河: {passed_moat} → 红旗通过: {passed_redflag}")
    print(f"最终入选: {len(results)} 只")
    print(f"  核心老登(≥4.0): {sum(1 for r in results if r['score'] >= 4.0)} 只")
    print(f"  优质老登(3.0-3.9): {sum(1 for r in results if 3.0 <= r['score'] < 4.0)} 只")
    print(f"  观察老登(2.0-2.9): {sum(1 for r in results if 2.0 <= r['score'] < 3.0)} 只")

    # 按行业汇总
    print(f"\n{'='*80}")
    print("🏛️ 各行业错杀概览")
    print(f"{'='*80}")
    industry_summary = defaultdict(lambda: {"candidates": 0, "core": 0, "quality": 0, "watch": 0, "stocks": []})
    for r in results:
        s = industry_summary[r["industry"]]
        s["candidates"] += 1
        if r["score"] >= 4.0: s["core"] += 1
        elif r["score"] >= 3.0: s["quality"] += 1
        else: s["watch"] += 1
        if r["score"] >= 3.0:
            s["stocks"].append(r)

    for ind, s in sorted(industry_summary.items()):
        strength = "🟢" if s["core"] > 0 else ("🟡" if s["quality"] > 0 else "⚪")
        print(f"  {strength} {ind}: {s['candidates']}入选, 核心{s['core']}/优质{s['quality']}/观察{s['watch']}")

    # 核心老登清单
    core_results = [r for r in results if r["score"] >= 4.0]
    quality_results = [r for r in results if 3.0 <= r["score"] < 4.0]

    if core_results:
        print(f"\n{'='*80}")
        print("⭐⭐⭐ 核心老登（综合 ≥ 4.0）—— 好公司被错杀")
        print(f"{'='*80}")
        print(f"{'#':3s} {'代码':8s} {'名称':10s} {'行业':6s} {'市值(亿)':>8s} {'PE':>6s} {'PE分位':>6s} {'回撤':>6s} {'背离度':>6s} {'红旗':>4s} {'得分':>5s} {'错杀场景':>12s}")
        print("-" * 95)
        for i, r in enumerate(core_results, 1):
            m = r["mispricing"]
            print(f"{i:<3d} {r['code']:<8s} {r['name']:<10s} {r['industry']:<6s} "
                  f"{m['mcap']:>8.0f} {m['pe']:>6.1f} {m['pe_percentile']:>5.1f}% "
                  f"{m['drawdown']:>5.1f}% {m['divergence']:>6.1f} "
                  f"{r['red_count']:>4d} {r['score']:>5.2f} {m['scenario']:>12s}")

    if quality_results:
        print(f"\n{'='*80}")
        print("⭐⭐ 优质老登（综合 3.0-3.9）—— 好公司但错杀程度不够极端")
        print(f"{'='*80}")
        for i, r in enumerate(quality_results, 1):
            m = r["mispricing"]
            print(f"  {i}. {r['code']} {r['name']} ({r['industry']}) "
                  f"PE={m['pe']:.1f} 回撤={m['drawdown']:.1f}% 背离度={m['divergence']:.1f} "
                  f"得分={r['score']:.2f} {r['grade']}")

    # 详细画像（核心老登前 5）
    print(f"\n{'='*80}")
    print("📋 核心老登详细画像")
    print(f"{'='*80}")

    for r in core_results[:5]:
        m = r["mispricing"]
        pd = r["profit_detail"]
        md = r["margin_detail"]
        mr = r["moat_result"]

        print(f"\n{'─'*80}")
        print(f"### {r['name']}（{r['code']}）⭐⭐⭐ 得分: {r['score']:.2f}/5")
        print(f"{'─'*80}")
        print(f"| 维度 | 判断 | 关键数据 |")
        print(f"|------|------|---------|")

        # 持续盈利
        nps = pd.get("net_profits", [])
        np_str = ", ".join([f"{np/1e8:.0f}亿" for _, np in nps[:4]])
        roe = pd.get("roe", "N/A")
        print(f"| 持续盈利 | ✅ 8季全部盈利 | 近4季净利: [{np_str}]，ROE≈{roe}% |")

        # 护城河
        strong_moats = [k for k, v in mr.items() if isinstance(v, tuple) and v[0] == "强"]
        mid_moats = [k for k, v in mr.items() if isinstance(v, tuple) and v[0] == "中"]
        moat_str = " + ".join(strong_moats + [f"{m}(中)" for m in mid_moats]) if (strong_moats or mid_moats) else "待深度验证"
        print(f"| 护城河 | ✅ 强{len(strong_moats)}类/中{len(mid_moats)}类 | {moat_str} |")

        # 财报可信
        rf_str = " + ".join(r["red_flags"]) if r["red_flags"] else "无"
        print(f"| 财报可信 | {'✅' if r['red_count'] == 0 else '🟡'} {r['red_count']}面红旗 | {rf_str} |")

        # 毛利率
        print(f"| 毛利率 | {md.get('quality', 'N/A')} | {md.get('avg_margin', 'N/A')}%，趋势{md.get('trend', 'N/A')}，波动{md.get('volatility', 'N/A')}pp |")

        # 估值错杀
        print(f"| **估值错杀** | ⭐{'⭐'*min(4, int(m['div_score']))} 背离度{m['divergence']:.1f} | PE={m['pe']:.1f}(分位{m['pe_percentile']:.0f}%) 回撤={m['drawdown']:.1f}% {m['scenario']} |")

        print(f"| **综合** | {r['grade']} | 错杀场景: {m['scenario']} |")

    print(f"\n{'='*80}")
    print("⚠️ 重要提示")
    print(f"{'='*80}")
    print("1. 以上分析基于公开财务数据 + 护城河快速判断（非深度验证）")
    print("2. 核心老登建议后续调用 moat-hunter 做深度不可替代性分析")
    print("3. 错杀不等于马上涨，估值修复需要催化剂和时间")
    print("4. 假错杀排除需进一步验证：卖方EPS下调情况、隐性政策风险、行业通杀程度")
    print("5. 本研究仅供分析参考，不构成买卖建议")

    # 输出 JSON（便于后续技能流转）
    output_path = f"src/old-guard-stocks-{TODAY}.json"
    os.makedirs("src", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({
            "date": TODAY,
            "summary": {
                "candidates": len(all_codes),
                "passed": len(results),
                "core": len(core_results),
                "quality": len(quality_results),
                "watch": len([r for r in results if r["score"] < 3.0]),
            },
            "results": [{k: str(v) if isinstance(v, (dict, list)) else v
                         for k, v in r.items()} for r in results]
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 原始数据已保存至: {output_path}")


if __name__ == "__main__":
    main()
