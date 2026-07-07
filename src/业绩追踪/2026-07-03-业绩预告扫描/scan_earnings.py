#!/usr/bin/env python3
"""全市场业绩预告扫描 — 2026-07-03"""
import time, random, json, requests
from datetime import datetime, timedelta

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
        if page * page_size >= d["result"]["count"]:
            break
    return all_data


# ===== 1. 全市场业绩预告（最近 30 天） =====
print("正在拉取近 30 天全市场业绩预告...")
cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
forecasts = eastmoney_datacenter_paged(
    "RPT_PUBLIC_OP_NEWPREDICT",
    filter_str=f'(NOTICE_DATE>=\'{cutoff}\')',
    max_pages=4, page_size=500,
    sort_columns="NOTICE_DATE", sort_types="-1"
)
print(f"  → 共获取 {len(forecasts)} 条业绩预告")

# 分类统计
type_summary = {}
for f in forecasts:
    t = f.get("PREDICT_TYPE", "未知")
    type_summary[t] = type_summary.get(t, 0) + 1

# 正向 vs 负向
positive = [f for f in forecasts if f.get("PREDICT_TYPE") in ("预增", "扭亏")]
negative = [f for f in forecasts if f.get("PREDICT_TYPE") in ("预减", "首亏", "续亏")]
neutral  = [f for f in forecasts if f.get("PREDICT_TYPE") in ("略增", "略减", "续盈", "不确定")]

# 按净利上限排序 TOP 预增（按个股去重，优选取归母净利润预告）
seen_codes = set()
top_increase = []
for f in sorted(
    [f for f in positive if f.get("PREDICT_AMT_UPPER")],
    key=lambda x: float(x["PREDICT_AMT_UPPER"]),
    reverse=True
):
    code = f.get("SECURITY_CODE", "")
    fin_type = f.get("PREDICT_FINANCE", "")
    # 优先取归母净利润预告，同一代码只保留一条
    if code not in seen_codes:
        seen_codes.add(code)
        top_increase.append(f)
    elif "归母" in fin_type and code in seen_codes:
        # 如果已有的是扣非版本，替换为归母版本
        for idx, existing in enumerate(top_increase):
            if existing.get("SECURITY_CODE") == code and "扣非" in existing.get("PREDICT_FINANCE", ""):
                top_increase[idx] = f
                break
top_increase = top_increase[:30]

# 按净利下限排序 TOP 预减/首亏（亏损最大）
top_decrease = sorted(
    [f for f in negative if f.get("PREDICT_AMT_LOWER")],
    key=lambda x: float(x["PREDICT_AMT_LOWER"])
)[:20]

# ===== 2. 精选个股拉取最新财务数据 =====
print("\n正在拉取精选个股最新财务数据...")
stock_codes = set()
for f in top_increase[:10]:
    stock_codes.add(f.get("SECURITY_CODE", ""))
for f in top_decrease[:5]:
    stock_codes.add(f.get("SECURITY_CODE", ""))

stock_financials = {}
for code in list(stock_codes)[:12]:
    if not code:
        continue
    data = eastmoney_datacenter_paged(
        "RPT_LICO_FN_CPD",
        filter_str=f'(SECURITY_CODE="{code}") AND (ISNEW="1")',
        max_pages=1, page_size=5,
        sort_columns="REPORTDATE", sort_types="-1"
    )
    if data:
        stock_financials[code] = data[0]
    time.sleep(0.3)

# ===== 3. 生成报告 =====
print("\n正在生成报告...")
report_lines = []
report_lines.append("# 全市场业绩预告扫描报告")
report_lines.append(f"\n> 生成日期：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
report_lines.append(f"> 数据来源：东财 datacenter (`RPT_PUBLIC_OP_NEWPREDICT` + `RPT_LICO_FN_CPD`)")
report_lines.append(f"> 数据截止：{datetime.now().strftime('%Y-%m-%d')}")
report_lines.append(f"> 回溯窗口：最近 30 天")
report_lines.append(f"> 预告总数：{len(forecasts)} 条")
report_lines.append("")

# 概要
report_lines.append("## 一、概要")
report_lines.append("")
report_lines.append(f"| 指标 | 数值 |")
report_lines.append(f"|------|------|")
report_lines.append(f"| 预告总数 | {len(forecasts)} |")
report_lines.append(f"| 预增 | {type_summary.get('预增', 0)} |")
report_lines.append(f"| 略增 | {type_summary.get('略增', 0)} |")
report_lines.append(f"| 扭亏 | {type_summary.get('扭亏', 0)} |")
report_lines.append(f"| 略减 | {type_summary.get('略减', 0)} |")
report_lines.append(f"| 预减 | {type_summary.get('预减', 0)} |")
report_lines.append(f"| 首亏 | {type_summary.get('首亏', 0)} |")
report_lines.append(f"| 续亏 | {type_summary.get('续亏', 0)} |")
report_lines.append(f"| 续盈 | {type_summary.get('续盈', 0)} |")
report_lines.append(f"| 不确定 | {type_summary.get('不确定', 0)} |")
report_lines.append(f"| 正向(预增+扭亏) | {len(positive)} |")
report_lines.append(f"| 负向(预减+首亏+续亏) | {len(negative)} |")
report_lines.append("")

# 正向 TOP 30
report_lines.append("## 二、正向预告 TOP 30（预增 + 扭亏，按净利上限排序）")
report_lines.append("")
report_lines.append("| 排名 | 代码 | 简称 | 预告类型 | 预告指标 | 净利下限(亿) | 净利上限(亿) | 公告日期 | 报告期 |")
report_lines.append("|------|------|------|----------|----------|-------------|-------------|----------|--------|")
for i, f in enumerate(top_increase[:30]):
    amt_lower = float(f.get("PREDICT_AMT_LOWER") or 0) / 1e8
    amt_upper = float(f.get("PREDICT_AMT_UPPER") or 0) / 1e8
    fin_type = f.get("PREDICT_FINANCE", "").replace("归属于上市公司股东的", "").replace("扣除非经常性损益后的", "扣非")
    fin_type_short = "归母净利" if "股东" in f.get("PREDICT_FINANCE", "") else ("扣非净利" if "扣非" in f.get("PREDICT_FINANCE", "") else fin_type[:6])
    report_lines.append(
        f"| {i+1} | {f.get('SECURITY_CODE','')} | {f.get('SECURITY_NAME_ABBR','')} "
        f"| {f.get('PREDICT_TYPE','')} | {fin_type_short} | {amt_lower:.2f} | {amt_upper:.2f} "
        f"| {f.get('NOTICE_DATE','')[:10]} | {f.get('REPORT_DATE','')[:10]} |"
    )
report_lines.append("")

# 预增 TOP 20 详情
report_lines.append("## 三、预增 TOP 10 个股详情")
report_lines.append("")
top_increase_only = [f for f in top_increase if f.get("PREDICT_TYPE") == "预增"][:10]
for i, f in enumerate(top_increase_only):
    code = f.get("SECURITY_CODE", "")
    name = f.get("SECURITY_NAME_ABBR", "")
    amt_lower = float(f.get("PREDICT_AMT_LOWER") or 0) / 1e8
    amt_upper = float(f.get("PREDICT_AMT_UPPER") or 0) / 1e8

    report_lines.append(f"### {i+1}. {name}（{code}）")
    report_lines.append(f"")
    report_lines.append(f"- **预告类型**：{f.get('PREDICT_TYPE','')}")
    report_lines.append(f"- **预告财务指标**：{f.get('PREDICT_FINANCE','')}")
    report_lines.append(f"- **净利区间**：{amt_lower:.2f} ~ {amt_upper:.2f} 亿元")
    report_lines.append(f"- **公告日期**：{f.get('NOTICE_DATE','')[:10]}")
    report_lines.append(f"- **报告期**：{f.get('REPORT_DATE','')[:10]}")

    # 如果有最新财务数据，补充
    fin = stock_financials.get(code)
    if fin:
        income = float(fin.get("TOTAL_OPERATE_INCOME") or 0) / 1e8
        profit = float(fin.get("PARENT_NETPROFIT") or 0) / 1e8
        ystz = fin.get("YSTZ")
        sjltz = fin.get("SJLTZ")
        ystz_str = f"{float(ystz):.2f}" if ystz else "N/A"
        sjltz_str = f"{float(sjltz):.2f}" if sjltz else "N/A"
        report_lines.append(f"- **最新财报**：{fin.get('DATATYPE','')} | 营收 {income:.2f}亿(同比{ystz_str}%) | 净利 {profit:.2f}亿(同比{sjltz_str}%) | EPS {fin.get('BASIC_EPS','N/A')} | ROE {fin.get('WEIGHTAVG_ROE','N/A')}%")
    report_lines.append(f"")

# 负向 TOP 20
report_lines.append("## 四、负向预告 TOP 20（预减 + 首亏 + 续亏，按亏损程度排序）")
report_lines.append("")
report_lines.append("| 排名 | 代码 | 简称 | 预告类型 | 净利下限(亿) | 净利上限(亿) | 公告日期 | 报告期 |")
report_lines.append("|------|------|------|----------|-------------|-------------|----------|--------|")
for i, f in enumerate(top_decrease[:20]):
    amt_lower = float(f.get("PREDICT_AMT_LOWER") or 0) / 1e8
    amt_upper = float(f.get("PREDICT_AMT_UPPER") or 0) / 1e8
    report_lines.append(
        f"| {i+1} | {f.get('SECURITY_CODE','')} | {f.get('SECURITY_NAME_ABBR','')} "
        f"| {f.get('PREDICT_TYPE','')} | {amt_lower:.2f} | {amt_upper:.2f} "
        f"| {f.get('NOTICE_DATE','')[:10]} | {f.get('REPORT_DATE','')[:10]} |"
    )
report_lines.append("")

# 最近 7 天
report_lines.append("## 五、最近 7 天业绩预告")
report_lines.append("")
recent_7d = [f for f in forecasts if f.get("NOTICE_DATE", "")[:10] >= (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")]
report_lines.append(f"共 {len(recent_7d)} 条")
report_lines.append("")
report_lines.append("| 代码 | 简称 | 预告类型 | 净利下限(亿) | 净利上限(亿) | 公告日期 |")
report_lines.append("|------|------|----------|-------------|-------------|----------|")
for f in recent_7d[:50]:
    amt_lower = float(f.get("PREDICT_AMT_LOWER") or 0) / 1e8
    amt_upper = float(f.get("PREDICT_AMT_UPPER") or 0) / 1e8
    report_lines.append(
        f"| {f.get('SECURITY_CODE','')} | {f.get('SECURITY_NAME_ABBR','')} "
        f"| {f.get('PREDICT_TYPE','')} | {amt_lower:.2f} | {amt_upper:.2f} "
        f"| {f.get('NOTICE_DATE','')[:10]} |"
    )
report_lines.append("")

# 分析洞察
report_lines.append("## 六、分析洞察")
report_lines.append("")
pos_ratio = len(positive) / len(forecasts) * 100 if forecasts else 0
neg_ratio = len(negative) / len(forecasts) * 100 if forecasts else 0
report_lines.append(f"1. **情绪倾向**：正向预告占比 {pos_ratio:.1f}%，负向占比 {neg_ratio:.1f}%，中性占比 {100-pos_ratio-neg_ratio:.1f}%")
report_lines.append(f"2. **预告密集期**：当前处于 2026 年中报预告窗口期（7-8月），预告数量处于高峰")
report_lines.append(f"3. **关注方向**：预增且净利上限超 10 亿的公司共 {len([f for f in top_increase if float(f.get('PREDICT_AMT_UPPER') or 0)/1e8 > 10])} 家")
report_lines.append(f"4. **风险方向**：首亏公司 {type_summary.get('首亏', 0)} 家，需重点跟踪后续正式财报是否确认")
report_lines.append("")

# 研究声明
report_lines.append("---")
report_lines.append("")
report_lines.append("## ⚠️ 研究声明")
report_lines.append("")
report_lines.append("- 业绩预告为上市公司自行发布的**初步预测**，实际业绩可能与预告存在偏差")
report_lines.append("- 业绩预告修正（业绩变脸）常见，需关注后续修正公告")
report_lines.append("- 本报告提供客观数据呈现，**不构成任何投资建议**")
report_lines.append("- 数据来源：东方财富 datacenter (`RPT_PUBLIC_OP_NEWPREDICT` + `RPT_LICO_FN_CPD`)")
report_lines.append("")

report_content = "\n".join(report_lines)

# 写入文件
output_path = "/Users/lishunxiang/Cenxi/learn/Finance/src/业绩追踪/2026-07-03-业绩预告扫描/earnings-forecast-scan.md"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(report_content)

print(f"\n✅ 报告已写入：{output_path}")
print(f"   预告总数：{len(forecasts)}")
print(f"   正向(预增+扭亏)：{len(positive)}")
print(f"   负向(预减+首亏+续亏)：{len(negative)}")
print(f"   预增 TOP 5：")
for i, f in enumerate(top_increase[:5]):
    amt_upper = float(f.get("PREDICT_AMT_UPPER") or 0) / 1e8
    print(f"     {i+1}. {f['SECURITY_NAME_ABBR']}({f['SECURITY_CODE']}) 预增 净利上限 {amt_upper:.2f}亿")
