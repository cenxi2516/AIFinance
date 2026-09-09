#!/usr/bin/env python3
"""
多平台数据交叉验证模块 (V1.0)
================================
所有 skill 在生成报告前必须调用此模块验证数据真实性。

核心原则: 数据不交叉验证，不写入报告。

使用方式:
    from cross_validation import fetch_realtime_with_validation, print_validation_summary

    realtime = fetch_realtime_with_validation("600176")
    print_validation_summary(realtime.get("_validation", {}))

支持的数据源:
    - 腾讯行情 (qt.gtimg.cn): 价格/量/PE/PB/市值/换手率
    - 新浪行情 (hq.sinajs.cn): 价格/量/额（交叉验证用，不提供PE/PB）
    - 东财 datacenter-web: 融资融券（单源）

验证维度与阈值:
    - 价格类（开/高/低/收/昨收/涨跌幅）: 差异 < 0.5%
    - 成交额: 差异 < 2%
    - 成交量: 差异 < 5%（因腾讯=手、新浪=股的单位换算容差）

质量评级:
    - 🟢 高置信度: 全部双源验证通过
    - 🟡 中等置信度: 部分单源但无不一致
    - 🔴 低置信度: 存在双源不一致
"""

import requests
from typing import Optional


# ══════════════════════════════════════════════════════════════════════
# 数据源: 新浪行情（交叉验证专用）
# ══════════════════════════════════════════════════════════════════════

def fetch_realtime_sina(code: str) -> dict:
    """
    从新浪获取实时行情 — 作为腾讯的交叉验证源。

    Args:
        code: 6位股票代码

    Returns:
        {"available": True/False, "price": ..., "volume": ..., ...}
        注意: 新浪不提供 PE/PB/市值/换手率，仅用于价格/量/额的交叉验证。
        新浪成交量单位是"股"（腾讯是"手"），换算时需×100。
    """
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    try:
        r = requests.get(
            f"https://hq.sinajs.cn/list={prefix}{code}",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10
        )
        r.encoding = "gbk"
        data = r.text.split('"')[1].split(",")
        if len(data) < 30:
            return {"available": False, "reason": f"数据字段不足(仅{len(data)}字段)"}

        return {
            "available": True,
            "name": data[0],
            "open": float(data[1]),
            "last_close": float(data[2]),
            "price": float(data[3]),
            "high": float(data[4]),
            "low": float(data[5]),
            "volume": int(float(data[8])),          # 股（非手！腾讯是手）
            "amount_yi": float(data[9]) / 1e8,      # 成交额(元→亿)
            "change_pct": round(
                (float(data[3]) - float(data[2])) / float(data[2]) * 100, 2
            ),
        }
    except Exception as e:
        return {"available": False, "reason": str(e)[:80]}


# ══════════════════════════════════════════════════════════════════════
# 核心: 腾讯 ⇔ 新浪 交叉验证
# ══════════════════════════════════════════════════════════════════════

def cross_validate_realtime(tencent: dict, sina: dict) -> dict:
    """
    交叉验证腾讯 vs 新浪实时行情。

    Args:
        tencent: _fetch_realtime_tencent() 的返回
        sina: fetch_realtime_sina() 的返回（available=True 时）

    Returns:
        {
            "passed": bool,           # 是否全部通过
            "quality": str,           # 🟢/🟡/🔴 质量评级
            "checks": [dict],         # 逐项验证详情
            "summary": str,           # 一句话总结
        }
    """
    checks = []
    all_ok = True

    def compare(metric: str, tv: Optional[float], sv: Optional[float],
                threshold_pct: float) -> dict:
        nonlocal all_ok
        if tv is None or sv is None or sv == 0:
            return {
                "metric": metric,
                "tencent": tv, "sina": sv,
                "diff_pct": None, "ok": None,
                "note": "单源无法比较"
            }
        diff = abs(tv - sv) / abs(sv) * 100
        ok = diff < threshold_pct
        if not ok:
            all_ok = False
        return {
            "metric": metric,
            "tencent": tv, "sina": sv,
            "diff_pct": round(diff, 3), "ok": ok,
            "threshold": threshold_pct,
        }

    # 价格类: 阈值 0.5%
    checks.append(compare("当前价", tencent.get("price"), sina.get("price"), 0.5))
    checks.append(compare("开盘价", tencent.get("open"), sina.get("open"), 0.5))
    checks.append(compare("最高价", tencent.get("high"), sina.get("high"), 0.5))
    checks.append(compare("最低价", tencent.get("low"), sina.get("low"), 0.5))
    checks.append(compare("昨收价", tencent.get("last_close"), sina.get("last_close"), 0.5))
    checks.append(compare("涨跌幅%", tencent.get("change_pct"), sina.get("change_pct"), 0.5))

    # 成交额: 阈值 2%（腾讯 amount_wan 万→亿, 新浪 amount_yi 亿）
    tencent_amount_yi = (tencent.get("amount_wan", 0) or 0) / 1e4
    checks.append(compare("成交额(亿)", tencent_amount_yi, sina.get("amount_yi", 0), 2.0))

    # 成交量: 阈值 5%（单位换算容差: 腾讯=手→×100=股, 新浪=股）
    tencent_vol_gu = (tencent.get("volume", 0) or 0) * 100
    checks.append(compare("成交量(股)", tencent_vol_gu, sina.get("volume", 0), 5.0))

    # 统计
    passed = sum(1 for c in checks if c["ok"] is True)
    failed = sum(1 for c in checks if c["ok"] is False)
    single = sum(1 for c in checks if c["ok"] is None)

    if failed == 0 and single <= 2:
        quality = "🟢 高置信度(双源验证通过)"
    elif failed == 0:
        quality = "🟡 中等置信度(部分单源)"
    else:
        quality = f"🔴 低置信度({failed}项未通过交叉验证)"

    return {
        "passed": all_ok and failed == 0,
        "quality": quality,
        "checks": checks,
        "summary": f"通过{passed}项, 未通过{failed}项, 单源{single}项 → {quality}",
        "sources": ["腾讯", "新浪"],
    }


# ══════════════════════════════════════════════════════════════════════
# 便捷函数: 一键拉取 + 验证
# ══════════════════════════════════════════════════════════════════════

def fetch_realtime_with_validation(code: str, tencent_fetcher=None) -> dict:
    """
    拉取实时行情 + 交叉验证。
    主源: 腾讯 → 验证源: 新浪。

    Args:
        code: 股票代码
        tencent_fetcher: 腾讯行情获取函数。不传则需在调用前确保
                        _fetch_realtime_tencent 已定义。

    Returns:
        腾讯行情 dict，附带 _validation 和 _sources 字段。
    """
    # 如果传入了自定义 fetcher，用它；否则用默认名称
    if tencent_fetcher:
        realtime = tencent_fetcher(code)
    else:
        # 尝试导入调用方的 fetch 函数
        import sys
        caller_frame = sys._getframe(1)
        caller_globals = caller_frame.f_globals
        fetcher = caller_globals.get("fetch_realtime_tencent") or \
                  caller_globals.get("_fetch_realtime_tencent")
        if fetcher:
            realtime = fetcher(code)
        else:
            raise RuntimeError(
                "未找到 _fetch_realtime_tencent 函数，"
                "请传入 tencent_fetcher 参数"
            )

    sina = fetch_realtime_sina(code)

    if sina.get("available"):
        validation = cross_validate_realtime(realtime, sina)
        realtime["_validation"] = validation
        realtime["_sources"] = ["腾讯", "新浪"]
    else:
        realtime["_validation"] = {
            "passed": None,
            "quality": "🟡 单源(新浪不可用)",
            "checks": [],
            "summary": f"仅腾讯单源 — 新浪: {sina.get('reason', '未知')}",
            "sources": ["腾讯"],
        }
        realtime["_sources"] = ["腾讯"]

    return realtime


# ══════════════════════════════════════════════════════════════════════
# 输出辅助函数
# ══════════════════════════════════════════════════════════════════════

def print_validation_summary(validation: dict, indent: str = "  ") -> None:
    """
    打印数据验证摘要到 console。
    所有 skill 的 _print_report 应在 Part 1 中调用此函数。
    """
    if not validation:
        return

    quality = validation.get("quality", "未知")
    summary = validation.get("summary", "")
    print(f"{indent}数据质量: {quality} | {summary}")

    # 打印验证详情（如果有不通过的项）
    checks = validation.get("checks", [])
    failed_checks = [c for c in checks if c.get("ok") is False]
    if failed_checks:
        print(f"{indent}⚠️  未通过项:")
        for c in failed_checks:
            print(f"{indent}    {c['metric']}: 腾讯={c['tencent']}, "
                  f"新浪={c['sina']}, 差异={c['diff_pct']}% "
                  f"(阈值{c.get('threshold', '?')}%)")


def markdown_validation_summary(validation: dict) -> list[str]:
    """
    生成数据验证摘要的 markdown 行。
    所有 skill 的 _save_markdown 应在 Part 1 中调用此函数。

    Returns:
        markdown 行列表（不含换行符），可直接 extend 到 lines 列表。
    """
    if not validation:
        return []

    lines = []
    quality = validation.get("quality", "未知")
    summary = validation.get("summary", "")

    lines.append(f"| 数据质量 | {quality} |")
    lines.append(f"")
    lines.append(f"> **交叉验证**: {summary}")

    # 数据来源清单
    sources = validation.get("sources", [])
    if sources:
        src_str = "+".join(sources)
        lines.append(f"> **数据来源**: 行情[{src_str}交叉验证] | "
                     f"K线[腾讯] | PE/PB[腾讯单源] | 融资融券[东财单源]")

    return lines


def check_data_quality(validation: dict) -> str:
    """
    检查数据质量是否允许生成报告。
    返回: "ok" | "warn" | "block"
    - "ok": 双源验证全部通过，可以生成报告
    - "warn": 单源或部分不一致，可以生成但需标注 ⚠️
    - "block": 严重不一致，不应生成报告
    """
    if not validation:
        return "warn"

    checks = validation.get("checks", [])
    failed = [c for c in checks if c.get("ok") is False]

    if len(failed) >= 3:
        return "block"  # 3项以上不一致，数据可能有严重问题
    elif len(failed) >= 1:
        return "warn"   # 有少量不一致，标注后仍可生成
    else:
        return "ok"     # 全部通过


# ══════════════════════════════════════════════════════════════════════
# 使用示例
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # 独立测试
    code = "600176"
    print(f"═══ 交叉验证模块测试: {code} ═══\n")

    # 测试新浪行情
    sina = fetch_realtime_sina(code)
    print(f"[新浪行情] available={sina.get('available')}")
    if sina.get("available"):
        for k, v in sina.items():
            if k != "available":
                print(f"  {k}: {v}")

    print(f"\n模块导入就绪。实际使用时请调用 fetch_realtime_with_validation()。")
