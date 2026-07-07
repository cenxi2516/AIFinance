#!/usr/bin/env python3
"""
全市场业绩预告扫描脚本
基于 earnings-tracker skill 的 API 调用
"""

import time, random, requests, json
from datetime import datetime, timedelta

# ── 东财通用 helper（与 a-stock-data 一致）──────────────────────────
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.2
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15):
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last_call[0] = time.time()

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def eastmoney_datacenter_paged(report_name, columns="ALL", filter_str="",
                               max_pages=5, page_size=500, sort_columns="", sort_types="-1"):
    all_data = []
    for page in range(1, max_pages + 1):
        params = {
            "reportName": report_name, "columns": columns,
            "filter": filter_str, "pageNumber": str(page), "pageSize": str(page_size),
            "sortColumns": sort_columns, "sortTypes": sort_types,
            "source": "WEB", "client": "WEB",
        }
        r = em_get(DATACENTER_URL, params=params, timeout=15)
        d = r.json()
        if not d.get("success") or not d["result"] or not d["result"].get("data"):
            break
        all_data.extend(d["result"]["data"])
        print(f"  [分页] 第{page}页拉取 {len(d['result']['data'])} 条，累计 {len(all_data)} 条")
        if page * page_size >= d["result"]["count"]:
            break
    return all_data


def latest_earnings_forecast(days: int = 7, page_size: int = 500) -> list:
    """拉取最近 N 天全市场业绩预告"""
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    filter_str = f'(NOTICE_DATE>=\'{cutoff_date}\')'
    print(f"  查询条件: NOTICE_DATE >= {cutoff_date}")
    return eastmoney_datacenter_paged(
        "RPT_PUBLIC_OP_NEWPREDICT",
        filter_str=filter_str, page_size=page_size,
        sort_columns="NOTICE_DATE", sort_types="-1"
    )


def scan_positive_forecasts(days: int = 7) -> dict:
    """扫描最近 N 天全市场正向业绩预告，按净利上限排序"""
    forecasts = latest_earnings_forecast(days=days, page_size=500)

    positive = [f for f in forecasts if f.get("PREDICT_TYPE") in ("预增", "扭亏")]
    positive.sort(key=lambda x: float(x.get("PREDICT_AMT_UPPER") or 0), reverse=True)

    negative = [f for f in forecasts if f.get("PREDICT_TYPE") in ("预减", "首亏", "续亏")]
    negative.sort(key=lambda x: float(x.get("PREDICT_AMT_LOWER") or 0))

    return {
        "forecasts": forecasts,
        "positive": positive,
        "negative": negative,
        "total": len(forecasts)
    }


def print_summary(result: dict, days: int):
    """打印扫描汇总"""
    forecasts = result["forecasts"]
    positive = result["positive"]
    negative = result["negative"]

    # 预告类型分布
    type_dist = {}
    for f in forecasts:
        t = f.get("PREDICT_TYPE", "未知")
        type_dist[t] = type_dist.get(t, 0) + 1

    print()
    print("=" * 72)
    print(f"  全市场业绩预告扫描 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  时间范围: 最近 {days} 天")
    print("=" * 72)

    print(f"\n  📊 预告总数: {len(forecasts)} 条")

    # 类型分布
    print(f"\n  【预告类型分布】")
    type_order = ["预增", "略增", "扭亏", "续盈", "不确定", "略减", "预减", "首亏", "续亏"]
    for t in type_order:
        if t in type_dist:
            bar = "█" * min(type_dist[t], 40)
            print(f"    {t:<6} {type_dist[t]:>4}  {bar}")

    # 正向：预增 + 扭亏
    print(f"\n  ── 🟢 正向预告 TOP 20（预增 + 扭亏，按净利上限排序）──")
    for i, f in enumerate(positive[:20]):
        code = f.get("SECURITY_CODE", "")
        name = f.get("SECURITY_NAME_ABBR", "")
        ptype = f.get("PREDICT_TYPE", "")
        notice_date = (f.get("NOTICE_DATE", "") or "")[:10]
        report_date = (f.get("REPORT_DATE", "") or "")[:10]
        amt_lower = float(f.get("PREDICT_AMT_LOWER") or 0) / 1e8
        amt_upper = float(f.get("PREDICT_AMT_UPPER") or 0) / 1e8
        print(f"    {i+1:>2}. {name:<8} ({code})  [{ptype}]")
        print(f"        净利区间: {amt_lower:.2f} ~ {amt_upper:.2f} 亿 | "
              f"公告日: {notice_date} | 报告期: {report_date}")

    # 负向：预减 + 首亏 + 续亏
    print(f"\n  ── 🔴 负向预告（预减 + 首亏 + 续亏）──")
    for i, f in enumerate(negative[:15]):
        code = f.get("SECURITY_CODE", "")
        name = f.get("SECURITY_NAME_ABBR", "")
        ptype = f.get("PREDICT_TYPE", "")
        notice_date = (f.get("NOTICE_DATE", "") or "")[:10]
        amt_lower = float(f.get("PREDICT_AMT_LOWER") or 0) / 1e8
        amt_upper = float(f.get("PREDICT_AMT_UPPER") or 0) / 1e8
        print(f"    {i+1:>2}. {name:<8} ({code})  [{ptype}]")
        print(f"        净利区间: {amt_lower:.2f} ~ {amt_upper:.2f} 亿 | "
              f"公告日: {notice_date}")

    print(f"\n  {'='*72}")
    print(f"  ⚠️ 研究声明：以上为客观数据呈现，不构成任何投资建议。")
    print(f"     业绩预告为初步预测，实际业绩以正式财报为准。")
    print(f"  {'='*72}")

    return type_dist


def save_scan_result(result: dict, days: int):
    """保存扫描结果到文件"""
    today = datetime.now().strftime("%Y-%m-%d")
    output_dir = f"src/业绩追踪/{today}-业绩预告扫描"

    import os
    os.makedirs(output_dir, exist_ok=True)

    # 保存完整原始数据
    with open(f"{output_dir}/raw_forecasts.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    # 保存摘要报告
    positive = result["positive"]
    negative = result["negative"]

    with open(f"{output_dir}/scan_summary.md", "w", encoding="utf-8") as f:
        f.write(f"# 全市场业绩预告扫描\n\n")
        f.write(f"**扫描日期**: {today}\n")
        f.write(f"**时间范围**: 最近 {days} 天\n")
        f.write(f"**预告总数**: {result['total']}\n\n")

        f.write(f"## 🟢 正向预告 TOP 30（预增 + 扭亏）\n\n")
        f.write(f"| # | 股票 | 代码 | 类型 | 净利下限(亿) | 净利上限(亿) | 公告日 | 报告期 |\n")
        f.write(f"|---|------|------|------|-------------|-------------|--------|--------|\n")
        for i, item in enumerate(positive[:30]):
            code = item.get("SECURITY_CODE", "")
            name = item.get("SECURITY_NAME_ABBR", "")
            ptype = item.get("PREDICT_TYPE", "")
            notice_date = (item.get("NOTICE_DATE", "") or "")[:10]
            report_date = (item.get("REPORT_DATE", "") or "")[:10]
            amt_lower = float(item.get("PREDICT_AMT_LOWER") or 0) / 1e8
            amt_upper = float(item.get("PREDICT_AMT_UPPER") or 0) / 1e8
            f.write(f"| {i+1} | {name} | {code} | {ptype} | {amt_lower:.2f} | {amt_upper:.2f} | {notice_date} | {report_date} |\n")

        if negative:
            f.write(f"\n## 🔴 负向预告（预减 + 首亏 + 续亏）\n\n")
            f.write(f"| # | 股票 | 代码 | 类型 | 净利下限(亿) | 净利上限(亿) | 公告日 |\n")
            f.write(f"|---|------|------|------|-------------|-------------|--------|\n")
            for i, item in enumerate(negative[:30]):
                code = item.get("SECURITY_CODE", "")
                name = item.get("SECURITY_NAME_ABBR", "")
                ptype = item.get("PREDICT_TYPE", "")
                notice_date = (item.get("NOTICE_DATE", "") or "")[:10]
                amt_lower = float(item.get("PREDICT_AMT_LOWER") or 0) / 1e8
                amt_upper = float(item.get("PREDICT_AMT_UPPER") or 0) / 1e8
                f.write(f"| {i+1} | {name} | {code} | {ptype} | {amt_lower:.2f} | {amt_upper:.2f} | {notice_date} |\n")

    print(f"\n  📁 扫描结果已保存到: {output_dir}/")
    return output_dir


if __name__ == "__main__":
    print("🔍 开始全市场业绩预告扫描...")
    result = scan_positive_forecasts(days=7)
    print_summary(result, days=7)
    save_scan_result(result, days=7)
