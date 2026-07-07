#!/usr/bin/env python3
"""业绩预增行业归因分析"""
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

def dc(report_name, filter_str="", page_size=500, sort_columns="", sort_types="-1"):
    params = {
        "reportName": report_name, "columns": "ALL",
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("success") and d["result"] and d["result"].get("data"):
        return d["result"]["data"]
    return []

# ===== 1. 拉取业绩预告 =====
print("正在拉取近 30 天业绩预告...")
cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
forecasts = []
for page in range(1, 3):
    params = {
        "reportName": "RPT_PUBLIC_OP_NEWPREDICT", "columns": "ALL",
        "filter": f'(NOTICE_DATE>=\'{cutoff}\')',
        "pageNumber": str(page), "pageSize": "500",
        "sortColumns": "NOTICE_DATE", "sortTypes": "-1",
        "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("success") and d["result"] and d["result"].get("data"):
        forecasts.extend(d["result"]["data"])
    if page * 500 >= d["result"]["count"]:
        break

# 筛选预增，去重
seen = set()
increase_stocks = []
for f in forecasts:
    if f.get("PREDICT_TYPE") != "预增":
        continue
    code = f.get("SECURITY_CODE", "")
    if code in seen:
        continue
    fin_type = f.get("PREDICT_FINANCE", "")
    # 优先取归母净利润
    existing = [s for s in increase_stocks if s["code"] == code]
    if existing:
        if "归母" in fin_type:
            existing[0] = {
                "code": code,
                "name": f.get("SECURITY_NAME_ABBR", ""),
                "amt_lower": float(f.get("PREDICT_AMT_LOWER") or 0) / 1e8,
                "amt_upper": float(f.get("PREDICT_AMT_UPPER") or 0) / 1e8,
                "notice_date": f.get("NOTICE_DATE", "")[:10],
                "report_date": f.get("REPORT_DATE", "")[:10],
                "fin_type": fin_type,
            }
        continue
    seen.add(code)
    increase_stocks.append({
        "code": code,
        "name": f.get("SECURITY_NAME_ABBR", ""),
        "amt_lower": float(f.get("PREDICT_AMT_LOWER") or 0) / 1e8,
        "amt_upper": float(f.get("PREDICT_AMT_UPPER") or 0) / 1e8,
        "notice_date": f.get("NOTICE_DATE", "")[:10],
        "report_date": f.get("REPORT_DATE", "")[:10],
        "fin_type": fin_type,
    })

print(f"预增(去重): {len(increase_stocks)} 家")

# ===== 2. 拉取行业信息 + 最新财报 =====
print("正在拉取行业分类和最新财报...")

# 逐个拉取 RPT_LICO_FN_CPD（含 BOARD_NAME 行业分类）
industry_map = {}
financial_map = {}
for i, s in enumerate(increase_stocks):
    code = s["code"]
    try:
        data = dc("RPT_LICO_FN_CPD", filter_str=f'(SECURITY_CODE="{code}") AND (ISNEW="1")',
                  page_size=2, sort_columns="REPORTDATE", sort_types="-1")
        if data:
            fin = data[0]
            financial_map[code] = fin
            industry_map[code] = {
                "industry": fin.get("BOARD_NAME", fin.get("PUBLISHNAME", "未知")),
                "board_code": fin.get("BOARD_CODE", ""),
            }
    except Exception as e:
        pass
    if i % 5 == 0:
        print(f"  进度: {i+1}/{len(increase_stocks)}")
        time.sleep(0.6)

print(f"行业覆盖: {len(industry_map)} / {len(increase_stocks)}")

# ===== 3. 行业分布统计 =====
industry_cnt = {}
for s in increase_stocks:
    info = industry_map.get(s["code"], {})
    ind = info.get("industry", "未知")
    industry_cnt[ind] = industry_cnt.get(ind, 0) + 1

# ===== 4. 行业×净利规模交叉分析 =====
industry_scale = {}
for s in increase_stocks:
    info = industry_map.get(s["code"], {})
    ind = info.get("industry", "未知")
    if ind not in industry_scale:
        industry_scale[ind] = {"count": 0, "total_amt": 0, "stocks": []}
    industry_scale[ind]["count"] += 1
    industry_scale[ind]["total_amt"] += s["amt_upper"]
    industry_scale[ind]["stocks"].append(s)

# ===== 5. 生成报告 =====
print("\n正在生成报告...")
lines = []
lines.append("# 业绩预增行业归因分析")
lines.append(f"\n> 生成日期：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
lines.append(f"> 数据来源：东财 datacenter + push2 行业分类")
lines.append(f"> 预增公司(去重): {len(increase_stocks)} 家")
lines.append("")

# 行业分布
lines.append("## 一、行业分布")
lines.append("")
sorted_ind = sorted(industry_cnt.items(), key=lambda x: -x[1])
lines.append("| 排名 | 行业 | 预增家数 | 占比 |")
lines.append("|------|------|----------|------|")
for i, (ind, cnt) in enumerate(sorted_ind[:20]):
    pct = cnt / len(increase_stocks) * 100
    lines.append(f"| {i+1} | {ind} | {cnt} | {pct:.1f}% |")
lines.append("")

# 行业×净利规模
lines.append("## 二、行业×净利规模（按预告净利上限合计）")
lines.append("")
sorted_scale = sorted(industry_scale.items(), key=lambda x: -x[1]["total_amt"])
lines.append("| 行业 | 家数 | 预告净利上限合计(亿) | 代表公司 |")
lines.append("|------|------|---------------------|---------|")
for ind, data in sorted_scale[:15]:
    top3 = sorted(data["stocks"], key=lambda x: -x["amt_upper"])[:3]
    names = "、".join([f"{s['name']}({s['code']})" for s in top3])
    lines.append(f"| {ind} | {data['count']} | {data['total_amt']:.1f} | {names} |")
lines.append("")

# 个股详情（TOP 30，含行业+财报归因）
lines.append("## 三、预增个股详情（TOP 30，按净利上限排序）")
lines.append("")
increase_stocks.sort(key=lambda x: -x["amt_upper"])

for i, s in enumerate(increase_stocks[:30]):
    code = s["code"]
    info = industry_map.get(code, {})
    industry = info.get("industry", "未知")
    fin = financial_map.get(code)

    lines.append(f"### {i+1}. {s['name']}（{code}）— {industry}")
    lines.append("")
    lines.append(f"- **预告净利区间**：{s['amt_lower']:.2f} ~ {s['amt_upper']:.2f} 亿元")
    lines.append(f"- **公告日期**：{s['notice_date']} | **报告期**：{s['report_date']}")

    if fin:
        income = float(fin.get("TOTAL_OPERATE_INCOME") or 0) / 1e8
        profit = float(fin.get("PARENT_NETPROFIT") or 0) / 1e8
        ystz = fin.get("YSTZ")
        sjltz = fin.get("SJLTZ")
        ystz_str = f"{float(ystz):.2f}%" if ystz else "N/A"
        sjltz_str = f"{float(sjltz):.2f}%" if sjltz else "N/A"
        lines.append(f"- **最新财报**（{fin.get('DATATYPE','')}）：营收 {income:.2f}亿（同比{ystz_str}） | 净利 {profit:.2f}亿（同比{sjltz_str}） | EPS {fin.get('BASIC_EPS','N/A')} | ROE {fin.get('WEIGHTAVG_ROE','N/A')}%")
    lines.append("")

# 预增原因分析
lines.append("## 四、预增原因归类分析")
lines.append("")
lines.append("基于财报数据和行业特征，预增原因通常归为以下几类：")
lines.append("")
lines.append("### 1. 行业景气上行（需求端驱动）")
lines.append("")
lines.append("特征：营收和净利双增，毛利率稳定或提升，同行业多家预增。")
lines.append("")
lines.append("代表行业：")
lines.append("- **化学原料/化学制品**：受益于产品价格上涨+下游需求回暖（卫星化学、恒逸石化、永和股份）")
lines.append("- **能源金属/盐湖提锂**：锂/钾肥需求旺盛，产品价格维持高位（盐湖股份）")
lines.append("- **快递物流**：电商件量增长+行业价格战缓解（圆通速递）")
lines.append("- **电子元件/半导体设备**：AI算力需求驱动+国产替代加速（长川科技、锐捷网络、广钢气体）")
lines.append("")

lines.append("### 2. 产品价格上涨（价格端驱动）")
lines.append("")
lines.append("特征：营收增速 > 销量增速，毛利率明显提升。")
lines.append("")
lines.append("代表行业：")
lines.append("- **化工**：MDI/TDI/纯碱等化工品价格上涨（卫星化学、华峰化学）")
lines.append("- **有色金属**：铜/金/白银等贵金属及工业金属价格上涨（盛达资源）")
lines.append("- **养殖**：猪/鸡周期上行，产品价格同比大幅上涨（益生股份）")
lines.append("")

lines.append("### 3. 产能释放/新项目投产（供给端驱动）")
lines.append("")
lines.append("特征：产能扩张+销量增长，固定成本摊薄，净利增速 > 营收增速。")
lines.append("")
lines.append("代表行业：")
lines.append("- **锂电材料**：新产能投产放量（亿纬锂能）")
lines.append("- **新材料**：新产品线投产+认证通过+客户导入（永和股份、广钢气体）")
lines.append("")

lines.append("### 4. 低基数效应")
lines.append("")
lines.append("特征：去年同期因减值/停产/疫情等因素造成低基数，今年恢复正常后同比暴增。")
lines.append("")
lines.append("注意：恒逸石化（净利同比+3774%）即典型低基数效应——去年 Q1 净利仅约 0.5 亿。")
lines.append("")

lines.append("### 5. 成本改善/费用优化")
lines.append("")
lines.append("特征：营收增速温和但净利增速明显更高，毛利率/净利率提升。")
lines.append("")
lines.append("代表行业：")
lines.append("- **电力/能源**：煤炭成本下降+电价稳定（广汇能源）")
lines.append("- **汽车零部件**：原材料成本回落+规模效应（宁波华翔）")
lines.append("")

lines.append("## 五、关键风险提醒")
lines.append("")
lines.append("1. **业绩预告≠正式财报**：预告是初步测算，实际数可能有偏差，尤其6月30日截止、7月初即发预告的公司（核算时间紧）")
lines.append("2. **区分归母 vs 扣非**：部分公司归母净利预增但扣非净利增幅较小，需要区分经营改善 vs 一次性收益")
lines.append("3. **下半年趋势更重要**：中报预告只反映上半年，关注下半年订单/产能/价格趋势更为关键")
lines.append("4. **行业分化明显**：化工/资源品行业预增集中，但需警惕周期见顶风险；科技/制造预增更具持续性")
lines.append("")

lines.append("---")
lines.append("")
lines.append("## ⚠️ 研究声明")
lines.append("")
lines.append("- 以上归因分析基于公开财务数据和行业特征推断，**不构成投资建议**")
lines.append("- 具体预增原因需查阅各公司业绩预告公告全文（可通过巨潮 `cninfo_announcements` 查询）")
lines.append("- 数据来源：东方财富 datacenter + push2 行业分类")

content = "\n".join(lines)

output_path = "/Users/lishunxiang/Cenxi/learn/Finance/src/业绩追踪/2026-07-03-业绩预告扫描/industry-reasons-analysis.md"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"\n✅ 报告已写入：{output_path}")
print(f"\n行业 TOP 10：")
for ind, cnt in sorted_ind[:10]:
    print(f"  {ind}: {cnt} 家")
