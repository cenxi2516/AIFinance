---
name: earnings-tracker
description: A股业绩全景追踪器 — 覆盖业绩预告(预增/预减/扭亏/首亏等9类预告类型)、业绩报表(单季/累计/同比/环比多期对比)、F10主要财务指标(含全量增长率)、业绩超预期分析(实际vs一致预期)、行业业绩对比排名。三个东财datacenter直连API端点经实测验证可用(2026-07)。适用于业绩预告季追踪、财报深度分析、业绩拐点识别、超预期/低于预期筛选、同行业横向对比。
version: 1.0.0
updated: 2026-07-03
---

# A股业绩追踪器 V1.0

全维度业绩数据工具 — 覆盖 3 个东财 datacenter 直连 API 端点（业绩预告 + 业绩报表 + F10 财务指标），支持个股历史多期对比、行业横向排名、实际 vs 一致预期差异分析、业绩拐点识别。所有 API 均实测可用（2026-07-03 验证）。

> **设计原则：** 依赖 a-stock-data 的通用 helper（`em_get`/`eastmoney_datacenter`），本 skill 只提供业绩数据的获取、聚合与分析逻辑。
>
> **核心创新：** ① 业绩预告全类型覆盖（9 类预告 + 净利润区间）② 累计→单季度差分计算 ③ 实际 vs 一致预期差异分析（超预期/低于预期自动判定）④ F10 全量财务指标 + 增长率 ⑤ 业绩拐点自动检测

## When to Activate

- 用户要看**业绩预告**（哪些公司发了预增/预减/扭亏公告）
- 用户要查**个股财务数据**（营收/净利/EPS/ROE 历史序列）
- 用户要**多期业绩对比**（同比/环比增长率趋势）
- 用户要**业绩超预期分析**（实际 EPS vs 一致预期差距）
- 用户要**业绩拐点识别**（营收/净利润增速趋势反转）
- 用户要**行业业绩排名**（同行业公司横向对比）
- 用户要**业绩披露日历**（预告→快报→正式财报时间线）
- 用户要**单季度业绩**（从累计财报做差分提取单季数据）
- 关键词：`业绩`、`业绩预告`、`预增`、`预减`、`扭亏`、`财报`、`季报`、`年报`、`中报`、`EPS`、`净利润`、`营收`、`ROE`、`超预期`、`低于预期`、`业绩拐点`、`财务指标`、`同比`、`环比`、`业绩对比`、`业绩排名`

## Prerequisites

本 skill 使用 a-stock-data 的通用 helper（模式A：源码复制，独立可执行）。

```python
# 通用 helper（与 a-stock-data 一致）
import time, random, requests, json
from datetime import datetime, timedelta

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.2
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15):
    """东财统一请求：自动节流 + Keep-Alive"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last_call[0] = time.time()

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def eastmoney_datacenter(report_name, columns="ALL", filter_str="",
                        page_size=50, sort_columns="", sort_types="-1"):
    """东财数据中心统一查询"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("success") and d["result"] and d["result"].get("data"):
        return d["result"]["data"]
    return []

def eastmoney_datacenter_paged(report_name, columns="ALL", filter_str="",
                               max_pages=5, page_size=500, sort_columns="", sort_types="-1"):
    """分页拉取全部数据"""
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
```

---

## 三层 API 架构

```
业绩预告层 ── RPT_PUBLIC_OP_NEWPREDICT (186K+) → 预告类型/净利润区间/预告日期
    │
业绩报表层 ── RPT_LICO_FN_CPD (485K+) → EPS/营收/净利/ROE/同比/环比/报告期
    │
财务指标层 ── RPT_F10_FINANCE_MAINFINADATA (677K+) → 全量指标+全维度增长率+财务比率
```

| 优先级 | API (reportName) | 记录量 | 核心用途 |
|--------|-----------------|--------|---------|
| **1** | `RPT_PUBLIC_OP_NEWPREDICT` | ~186K | 业绩预告查询 |
| **2** | `RPT_LICO_FN_CPD` | ~485K | 业绩报表查询 |
| **3** | `RPT_F10_FINANCE_MAINFINADATA` | ~677K | 完整财务指标 |

---

## Layer 1: 业绩预告追踪

数据源：`RPT_PUBLIC_OP_NEWPREDICT`（2026-07-03 实测可用）

### 1.1 全市场最新业绩预告

```python
def latest_earnings_forecast(days: int = 7, page_size: int = 500) -> list[dict]:
    """
    拉取最近 N 天全市场业绩预告。
    
    返回字段：SECURITY_CODE, SECURITY_NAME_ABBR, NOTICE_DATE, REPORT_DATE,
    PREDICT_TYPE（预增/略增/预减/略减/首亏/续亏/扭亏/续盈/不确定）,
    PREDICT_FINANCE, PREDICT_AMT_LOWER（净利润下限 元，需 /1e8 转亿）, PREDICT_AMT_UPPER（上限 元）,
    FORECAST_STATE（increase/reduction）, IS_LATEST
    """
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    filter_str = f'(NOTICE_DATE>=\'{cutoff_date}\')'
    return eastmoney_datacenter_paged(
        "RPT_PUBLIC_OP_NEWPREDICT",
        filter_str=filter_str, page_size=page_size,
        sort_columns="NOTICE_DATE", sort_types="-1"
    )
```

### 1.2 个股业绩预告历史

```python
def stock_earnings_forecast(code: str) -> list[dict]:
    """拉取指定个股全部业绩预告历史"""
    filter_str = f'(SECURITY_CODE="{code}")'
    return eastmoney_datacenter_paged(
        "RPT_PUBLIC_OP_NEWPREDICT",
        filter_str=filter_str, max_pages=3,
        sort_columns="NOTICE_DATE", sort_types="-1"
    )
```

### 1.3 预告类型分布统计

```python
def forecast_type_summary(days: int = 30) -> dict:
    """统计最近 N 天各预告类型数量分布"""
    forecasts = latest_earnings_forecast(days=days, page_size=500)
    summary = {}
    for f in forecasts:
        t = f.get("PREDICT_TYPE", "未知")
        summary[t] = summary.get(t, 0) + 1
    return summary
```

### 1.4 业绩预告类型速查

| PREDICT_TYPE | 含义 | 方向 | 典型特征 |
|---|---|---|---|
| `预增` | 净利润大幅增长 | ↑↑ | 同比增长 ≥50% |
| `略增` | 净利润小幅增长 | ↑ | 同比增长 0~50% |
| `预减` | 净利润大幅下降 | ↓↓ | 同比下降 ≥50% |
| `略减` | 净利润小幅下降 | ↓ | 同比下降 0~50% |
| `扭亏` | 亏损转为盈利 | ↑↑ | 上期亏损→本期盈利 |
| `首亏` | 首次出现亏损 | ↓↓ | 上期盈利→本期亏损 |
| `续亏` | 持续亏损 | ↓ | 连续两期以上亏损 |
| `续盈` | 持续盈利 | → | 持续盈利但幅度不确定 |
| `不确定` | 业绩不确定 | ? | 无法准确预测 |

### 1.5 预增/扭亏 TOP 筛选

```python
def top_forecast_by_type(days: int = 30, pred_type: str = "预增", top_n: int = 20) -> list[dict]:
    """筛选指定预告类型中净利润上限最高的 TOP N"""
    forecasts = latest_earnings_forecast(days=days, page_size=500)
    filtered = [f for f in forecasts
                if f.get("PREDICT_TYPE") == pred_type and f.get("PREDICT_AMT_UPPER")]
    filtered.sort(key=lambda x: float(x["PREDICT_AMT_UPPER"]) if x["PREDICT_AMT_UPPER"] else 0, reverse=True)
    return filtered[:top_n]
```

---

## Layer 2: 业绩报表查询

数据源：`RPT_LICO_FN_CPD`（2026-07-03 实测可用）

### 2.1 个股历史财务数据

```python
def stock_financial_history(code: str, max_pages: int = 3) -> list[dict]:
    """
    拉取个股全部历史财务数据。
    
    返回字段：REPORTDATE, QDATE(如2026Q1), DATATYPE(如"2026年 一季报"),
    BASIC_EPS, DEDUCT_BASIC_EPS, TOTAL_OPERATE_INCOME(元), PARENT_NETPROFIT(元),
    WEIGHTAVG_ROE(%), BPS, YSTZ(营收同比%), SJLTZ(净利同比%), MGJYXJJE(每股经营现金流)
    """
    filter_str = f'(SECURITY_CODE="{code}")'
    return eastmoney_datacenter_paged(
        "RPT_LICO_FN_CPD", filter_str=filter_str,
        max_pages=max_pages, page_size=500,
        sort_columns="REPORTDATE", sort_types="-1"
    )
```

### 2.2 最新一期财务数据

```python
def stock_latest_financial(code: str) -> dict | None:
    """获取个股最新一期财务数据（ISNEW=1）"""
    data = stock_financial_history(code, max_pages=1)
    if data:
        newest = [d for d in data if d.get("ISNEW") == "1"]
        return newest[0] if newest else data[0]
    return None
```

### 2.3 累计→单季度差分计算（核心创新）

东财 API 返回的是**累计**数据（如 Q2 = 前 6 个月累计），需要做差提取单季度数据。

```python
def extract_single_quarter(history: list[dict]) -> list[dict]:
    """
    从累计财报数据中提取单季度数据。
    
    原理：
    - Q1 单季 = Q1 累计
    - Q2 单季 = Q2 累计 - Q1 累计
    - Q3 单季 = Q3 累计 - Q2 累计
    - Q4 单季 = Q4 累计(年报) - Q3 累计
    
    同比：单季度 vs 去年同季度单季度
    """
    if not history:
        return []
    
    sorted_data = sorted(history, key=lambda x: x.get("REPORTDATE", ""))
    quarters = {d.get("QDATE", ""): d for d in sorted_data}
    
    single_quarters = []
    for qdate, d in sorted(quarters.items()):
        year = int(qdate[:4]); q = int(qdate[5:])
        single = {
            "QDATE": qdate, "SECURITY_CODE": d.get("SECURITY_CODE"),
            "SECURITY_NAME_ABBR": d.get("SECURITY_NAME_ABBR"),
            "REPORTDATE": d.get("REPORTDATE"), "DATATYPE": d.get("DATATYPE"),
            "BASIC_EPS": d.get("BASIC_EPS"), "WEIGHTAVG_ROE": d.get("WEIGHTAVG_ROE"),
        }
        
        if q == 1:
            single["TOTAL_OPERATE_INCOME_SINGLE"] = float(d.get("TOTAL_OPERATE_INCOME") or 0)
            single["PARENT_NETPROFIT_SINGLE"] = float(d.get("PARENT_NETPROFIT") or 0)
        else:
            prev = quarters.get(f"{year}Q{q-1}")
            if prev:
                single["TOTAL_OPERATE_INCOME_SINGLE"] = (
                    float(d.get("TOTAL_OPERATE_INCOME") or 0) - float(prev.get("TOTAL_OPERATE_INCOME") or 0))
                single["PARENT_NETPROFIT_SINGLE"] = (
                    float(d.get("PARENT_NETPROFIT") or 0) - float(prev.get("PARENT_NETPROFIT") or 0))
            else:
                single["TOTAL_OPERATE_INCOME_SINGLE"] = float(d.get("TOTAL_OPERATE_INCOME") or 0)
                single["PARENT_NETPROFIT_SINGLE"] = float(d.get("PARENT_NETPROFIT") or 0)
        
        # 同比：找去年同季度单季数据
        prev_year = quarters.get(f"{year-1}Q{q}")
        if prev_year and q == 1:
            single["INCOME_YOY"] = _safe_yoy(single["TOTAL_OPERATE_INCOME_SINGLE"],
                                              float(prev_year.get("TOTAL_OPERATE_INCOME") or 0))
            single["PROFIT_YOY"] = _safe_yoy(single["PARENT_NETPROFIT_SINGLE"],
                                              float(prev_year.get("PARENT_NETPROFIT") or 0))
        elif prev_year and q > 1:
            prev_year_prev = quarters.get(f"{year-1}Q{q-1}")
            if prev_year_prev:
                prev_income = (float(prev_year.get("TOTAL_OPERATE_INCOME") or 0)
                               - float(prev_year_prev.get("TOTAL_OPERATE_INCOME") or 0))
                prev_profit = (float(prev_year.get("PARENT_NETPROFIT") or 0)
                               - float(prev_year_prev.get("PARENT_NETPROFIT") or 0))
            else:
                prev_income = float(prev_year.get("TOTAL_OPERATE_INCOME") or 0)
                prev_profit = float(prev_year.get("PARENT_NETPROFIT") or 0)
            single["INCOME_YOY"] = _safe_yoy(single["TOTAL_OPERATE_INCOME_SINGLE"], prev_income)
            single["PROFIT_YOY"] = _safe_yoy(single["PARENT_NETPROFIT_SINGLE"], prev_profit)
        else:
            single["INCOME_YOY"] = None; single["PROFIT_YOY"] = None
        
        single_quarters.append(single)
    return single_quarters

def _safe_yoy(current: float, previous: float) -> float | None:
    """安全计算同比增长率，前值为0时返回None"""
    if previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)
```

### 2.4 行业业绩排名

```python
def industry_performance_ranking(qdate: str = "", board_code: str = "", top_n: int = 30) -> list[dict]:
    """
    按行业/报告期拉取公司财务数据并按归母净利润排名。
    
    Args:
        qdate: 报告期（如 '2026Q1'），为空则最新
        board_code: 东财行业代码（如 'BK0475'=银行Ⅱ），为空则全市场
    """
    filters = ['(ISNEW="1")']
    if qdate:
        filters.append(f'(QDATE="{qdate}")')
    if board_code:
        filters.append(f'(BOARD_CODE="{board_code}")')
    filter_str = " AND ".join(filters)
    return eastmoney_datacenter("RPT_LICO_FN_CPD", filter_str=filter_str,
                                page_size=top_n, sort_columns="PARENT_NETPROFIT", sort_types="-1")
```

---

## Layer 3: F10 主要财务指标

数据源：`RPT_F10_FINANCE_MAINFINADATA`（2026-07-03 实测可用）

### 3.1 个股全量财务指标

```python
def stock_f10_indicators(code: str, max_pages: int = 3) -> list[dict]:
    """
    拉取个股 F10 全量财务指标（80+ 字段，含所有增长率）。
    
    相比 RPT_LICO_FN_CPD 额外提供：
    - EPSKCJB(扣非EPS) / KCFJCXSYJLR(扣非归母净利)
    - XSMLL(销售毛利率%) / XSJLL(销售净利率%)
    - ZCFZL(资产负债率%) / MGJYXJJE(每股经营现金流)
    - DJD_TOI_YOY(单季度营收同比) / DJD_DPNP_YOY(单季度净利同比)
    - 流动比率/速动比率/总资产周转率等 30+ 财务比率
    """
    filter_str = f'(SECURITY_CODE="{code}")'
    return eastmoney_datacenter_paged(
        "RPT_F10_FINANCE_MAINFINADATA", filter_str=filter_str,
        max_pages=max_pages, page_size=500,
        sort_columns="REPORT_DATE", sort_types="-1"
    )
```

### 3.2 关键财务指标速查

| 字段 | 含义 | 用途 |
|------|------|------|
| `EPSJB` | 基本每股收益（元） | 核心盈利指标 |
| `EPSKCJB` | 扣非每股收益（元） | 剔除一次性损益 |
| `TOTALOPERATEREVE` | 营业总收入（元） | |
| `PARENTNETPROFIT` | 归母净利润（元） | |
| `KCFJCXSYJLR` | 扣非归母净利润（元） | **更纯粹的经营利润** |
| `ROEJQ` | 净资产收益率（%） | |
| `BPS` | 每股净资产（元） | |
| `MGJYXJJE` | 每股经营现金流（元） | **现金含量检验** |
| `XSMLL` | 销售毛利率（%） | 竞争壁垒观测 |
| `XSJLL` | 销售净利率（%） | |
| `ZCFZL` | 资产负债率（%） | |
| `TOTALOPERATEREVETZ` | 营收同比增长率（%） | |
| `PARENTNETPROFITTZ` | 归母净利同比增长率（%） | |
| `DJD_TOI_YOY` | 单季度营收同比（%） | **最敏感拐点信号** |
| `DJD_DPNP_YOY` | 单季度归母净利同比（%） | **最敏感拐点信号** |
| `DJD_DEDUCTDPNP_YOY` | 单季度扣非净利同比（%） | 剔除一次性损益的拐点信号 |

---

## Layer 4: 业绩分析引擎

### 4.1 业绩拐点识别

```python
def detect_earnings_inflection(code: str, quarters: int = 8) -> dict:
    """
    检测业绩拐点信号。
    
    核心逻辑：
    - F10 单季度营收同比连续下降后首次转正 → 营收拐点
    - F10 单季度扣非净利同比连续下降后首次转正 → 利润拐点
    - 营收拐点 + 利润拐点同时出现 → 强拐点信号
    
    Returns:
        {has_revenue_inflection, has_profit_inflection, inflection_strength("强/中/弱/无"),
         recent_quarters, signal_detail, rev_djd_yoy, profit_djd_yoy, deduct_djd_yoy}
    """
    history = stock_financial_history(code)
    singles = extract_single_quarter(history)
    
    if len(singles) < quarters:
        return {"inflection_strength": "数据不足", "recent_quarters": singles}
    
    recent = singles[-quarters:]
    f10_data = stock_f10_indicators(code, max_pages=1)
    f10_latest = f10_data[0] if f10_data else {}
    
    rev_djd_yoy = f10_latest.get("DJD_TOI_YOY")
    profit_djd_yoy = f10_latest.get("DJD_DPNP_YOY")
    deduct_djd_yoy = f10_latest.get("DJD_DEDUCTDPNP_YOY")
    
    prev_yoy_values = [s.get("PROFIT_YOY") for s in recent[:-1]]
    
    signal_parts = []; has_rev, has_profit = False, False
    
    if rev_djd_yoy is not None:
        rev_djd_yoy = float(rev_djd_yoy)
        prev_neg = [v for v in prev_yoy_values[-3:] if v is not None and v < 0]
        if rev_djd_yoy > 0 and len(prev_neg) >= 2:
            has_rev = True
            signal_parts.append(f"营收拐点：单季营收同比{rev_djd_yoy:.1f}%（前几季度连续负增长后首度转正）")
    
    if deduct_djd_yoy is not None:
        deduct_djd_yoy = float(deduct_djd_yoy)
        prev_profit_neg = [v for v in prev_yoy_values[-3:] if v is not None and v < 0]
        if deduct_djd_yoy > 0 and len(prev_profit_neg) >= 2:
            has_profit = True
            signal_parts.append(f"利润拐点：单季扣非净利同比{deduct_djd_yoy:.1f}%（前几季度连续负增长后首度转正）")
    
    if has_rev and has_profit:
        strength = "强"
        signal_parts.insert(0, "★★★ 强拐点信号：营收+利润双拐点共振 ★★★")
    elif has_rev or has_profit:
        strength = "中"
        signal_parts.insert(0, f"★★ 中拐点信号：{'营收拐点' if has_rev else '利润拐点'}")
    else:
        strength = "无"
        signal_parts.append("未检测到明确拐点信号")
    
    return {"has_revenue_inflection": has_rev, "has_profit_inflection": has_profit,
            "inflection_strength": strength, "recent_quarters": recent,
            "signal_detail": "\n".join(signal_parts),
            "rev_djd_yoy": rev_djd_yoy, "profit_djd_yoy": profit_djd_yoy, "deduct_djd_yoy": deduct_djd_yoy}
```

### 4.2 实际 vs 一致预期差异分析

```python
def earnings_surprise_analysis(code: str) -> dict:
    """
    对比最新实际 EPS 与一致预期，判定超预期/符合预期/低于预期。
    
    依赖 a-stock-data 的 ths_eps_forecast()（同花顺一致预期EPS）。
    
    Returns: {actual_eps, consensus_eps, surprise_pct(%), verdict("大幅超预期/超预期/符合预期/低于预期/大幅低于预期")}
    """
    latest_fin = stock_latest_financial(code)
    if not latest_fin:
        return {"verdict": "数据不足", "detail": "无最新财务数据"}
    
    actual_eps = float(latest_fin.get("BASIC_EPS") or 0)
    report_date = latest_fin.get("REPORTDATE", "")
    report_year = report_date[:4] if report_date else str(datetime.now().year)
    
    try:
        df = ths_eps_forecast(code)
        consensus_eps = None
        for _, row in df.iterrows():
            if str(row.iloc[0]) == report_year:
                consensus_eps = float(row.iloc[2]) if pd.notna(row.iloc[2]) else None
                break
        if consensus_eps is None and len(df) > 0:
            consensus_eps = float(df.iloc[0, 2]) if pd.notna(df.iloc[0, 2]) else None
    except Exception:
        consensus_eps = None
    
    if consensus_eps is None or consensus_eps == 0:
        return {"actual_eps": actual_eps, "consensus_eps": None,
                "verdict": "无一致预期", "detail": "该股票无机构覆盖或数据不可用"}
    
    surprise_pct = round((actual_eps - consensus_eps) / abs(consensus_eps) * 100, 2)
    
    if surprise_pct > 10:
        verdict = "★★★ 大幅超预期"
    elif surprise_pct > 3:
        verdict = "★★ 超预期"
    elif surprise_pct >= -3:
        verdict = "★ 符合预期"
    elif surprise_pct >= -10:
        verdict = "低于预期"
    else:
        verdict = "大幅低于预期"
    
    return {"actual_eps": actual_eps, "consensus_eps": consensus_eps,
            "surprise_pct": surprise_pct, "verdict": verdict,
            "detail": f"实际EPS={actual_eps} vs 一致预期={consensus_eps}，超预期幅度={surprise_pct:+.1f}%"}
```

### 4.3 毛利率趋势分析

```python
def gross_margin_trend(code: str, periods: int = 8) -> dict:
    """
    提取毛利率历史趋势。
    
    毛利率持续提升 → 竞争壁垒增强或成本优势改善
    毛利率持续下降 → 竞争加剧或成本压力增大
    
    Returns: {trend("↑ 持续改善/↓ 持续恶化/平稳"), history: [{report_date, gross_margin, net_margin}]}
    """
    indicators = stock_f10_indicators(code)
    result = []
    for d in indicators[:periods]:
        xsmll = d.get("XSMLL"); xsjll = d.get("XSJLL")
        result.append({"report_date": d.get("REPORT_DATE_NAME", d.get("REPORT_DATE", "")),
                       "gross_margin": float(xsmll) if xsmll is not None else None,
                       "net_margin": float(xsjll) if xsjll is not None else None})
    
    valid_margins = [r["gross_margin"] for r in result if r["gross_margin"] is not None]
    trend = "平稳"
    if len(valid_margins) >= 4:
        half = len(valid_margins) // 2
        recent_avg = sum(valid_margins[:half]) / half
        older_avg = sum(valid_margins[half:]) / max(len(valid_margins) - half, 1)
        if recent_avg - older_avg > 2:
            trend = "↑ 持续改善"
        elif recent_avg - older_avg < -2:
            trend = "↓ 持续恶化"
    
    return {"trend": trend, "history": result}
```

---

## Layer 5: 综合业绩报告

### 5.1 个股业绩全景报告

```python
def earnings_full_report(code: str) -> str:
    """
    一键生成个股业绩全景报告。
    
    包含：最新业绩预告 → 最新财报摘要 → 近 4 季单季度数据 →
          业绩拐点检测 → 毛利率趋势 → 一致预期差异
    """
    forecasts = stock_earnings_forecast(code)
    latest_fin = stock_latest_financial(code)
    history = stock_financial_history(code)
    singles = extract_single_quarter(history)
    inflection = detect_earnings_inflection(code)
    
    lines = []
    lines.append("=" * 60)
    lines.append(f"  {code} 业绩全景报告 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)
    
    # 业绩预告
    if forecasts:
        latest_fc = forecasts[0]
        lines.append(f"\n【业绩预告】")
        lines.append(f"  公告日期: {latest_fc.get('NOTICE_DATE','')[:10]}")
        lines.append(f"  报告期: {latest_fc.get('REPORT_DATE','')[:10]}")
        lines.append(f"  预告类型: {latest_fc.get('PREDICT_TYPE','')}")
        amt_lower = float(latest_fc.get("PREDICT_AMT_LOWER") or 0) / 10000
        amt_upper = float(latest_fc.get("PREDICT_AMT_UPPER") or 0) / 10000
        lines.append(f"  净利润区间: {amt_lower:.2f}~{amt_upper:.2f} 亿元")
    else:
        lines.append(f"\n【业绩预告】无最新预告")
    
    # 最新财报
    if latest_fin:
        lines.append(f"\n【最新财报】{latest_fin.get('DATATYPE','')}")
        income = float(latest_fin.get("TOTAL_OPERATE_INCOME") or 0) / 1e8
        profit = float(latest_fin.get("PARENT_NETPROFIT") or 0) / 1e8
        lines.append(f"  营业总收入: {income:.2f} 亿 (同比 {latest_fin.get('YSTZ','N/A')}%)")
        lines.append(f"  归母净利润: {profit:.2f} 亿 (同比 {latest_fin.get('SJLTZ','N/A')}%)")
        lines.append(f"  基本EPS: {latest_fin.get('BASIC_EPS','N/A')} | 加权ROE: {latest_fin.get('WEIGHTAVG_ROE','N/A')}%")
    
    # 近 4 季单季度
    if singles:
        lines.append(f"\n【近 4 季单季度数据】")
        lines.append(f"  {'报告期':<10} {'单季营收(亿)':<14} {'单季净利(亿)':<14} {'营收YoY':<10} {'净利YoY':<10}")
        lines.append(f"  {'-'*56}")
        for s in singles[-4:]:
            income = s.get("TOTAL_OPERATE_INCOME_SINGLE", 0) / 1e8
            profit = s.get("PARENT_NETPROFIT_SINGLE", 0) / 1e8
            rev_yoy = f"{s.get('INCOME_YOY'):.1f}%" if s.get('INCOME_YOY') is not None else "N/A"
            prof_yoy = f"{s.get('PROFIT_YOY'):.1f}%" if s.get('PROFIT_YOY') is not None else "N/A"
            lines.append(f"  {s['QDATE']:<10} {income:<14.2f} {profit:<14.2f} {rev_yoy:<10} {prof_yoy:<10}")
    
    # 业绩拐点
    lines.append(f"\n【业绩拐点检测】")
    lines.append(f"  拐点强度: {inflection.get('inflection_strength', 'N/A')}")
    lines.append(f"  {inflection.get('signal_detail', '')}")
    
    # 毛利率
    margin_info = gross_margin_trend(code)
    lines.append(f"\n【毛利率趋势】{margin_info['trend']}")
    
    lines.append(f"\n{'='*60}")
    lines.append("⚠️ 研究声明：以上为客观数据呈现，不构成任何投资建议。业绩预告为初步预测，以正式财报为准。")
    return "\n".join(lines)
```

### 5.2 全市场业绩预告扫描

```python
def scan_positive_forecasts(days: int = 7) -> dict:
    """扫描最近 N 天全市场正向业绩预告（预增 + 扭亏），按净利上限排序 TOP 30"""
    forecasts = latest_earnings_forecast(days=days, page_size=500)
    positive = [f for f in forecasts if f.get("PREDICT_TYPE") in ("预增", "扭亏")]
    positive.sort(key=lambda x: float(x.get("PREDICT_AMT_UPPER") or 0), reverse=True)
    negative = [f for f in forecasts if f.get("PREDICT_TYPE") in ("预减", "首亏", "续亏")]
    
    print(f"最近 {days} 天全市场业绩预告扫描：")
    print(f"  预告总数: {len(forecasts)}")
    print(f"  正向(预增+扭亏): {len(positive)}")
    print(f"  负向(预减+首亏+续亏): {len(negative)}")
    print(f"\n正向预告 TOP 10（按净利上限）：")
    for i, f in enumerate(positive[:10]):
        amt_lower = float(f.get("PREDICT_AMT_LOWER") or 0) / 10000
        amt_upper = float(f.get("PREDICT_AMT_UPPER") or 0) / 10000
        print(f"  {i+1}. {f['SECURITY_NAME_ABBR']}({f['SECURITY_CODE']}) "
              f"{f['PREDICT_TYPE']} | 净利: {amt_lower:.2f}~{amt_upper:.2f}亿")
    
    return {"positive": positive[:30], "negative": negative, "total": len(forecasts)}
```

---

## 快速参考

### 常用调用组合

| 目的 | 函数调用 |
|------|---------|
| 最近一周预增公告 | `latest_earnings_forecast(7)` → 筛选 `PREDICT_TYPE=="预增"` |
| 个股历史 EPS/ROE 序列 | `stock_financial_history(code)` → 取 `BASIC_EPS`/`WEIGHTAVG_ROE` |
| 行业净利排名 | `industry_performance_ranking(qdate="2026Q1", board_code="BK0475")` |
| 单季度业绩拆分 | `extract_single_quarter(stock_financial_history(code))` |
| 业绩拐点检测 | `detect_earnings_inflection(code)` |
| 实际vs一致预期 | `earnings_surprise_analysis(code)` |
| 全景业绩报告 | `earnings_full_report(code)` |
| 全市场预告扫描 | `scan_positive_forecasts(7)` |

### 过滤器语法参考

```python
'(SECURITY_CODE="000001")'
'(NOTICE_DATE>=\'2026-06-26\')'
'(PREDICT_TYPE="预增")'
'(ISNEW="1")'
'(SECURITY_CODE="000001") AND (QDATE="2026Q1")'
'((PREDICT_TYPE="预增") OR (PREDICT_TYPE="扭亏"))'
```

### 报告期标识速查

| QDATE | DATATYPE | 含义 | 累计范围 |
|-------|----------|------|---------|
| `2026Q1` | 2026年 一季报 | 第一季度报告 | 1-3月 |
| `2026Q2` | 2026年 中报 | 半年报 | 1-6月 |
| `2026Q3` | 2026年 三季报 | 第三季度报告 | 1-9月 |
| `2026Q4` | 2026年 年报 | 年度报告 | 1-12月 |

---

## 常见问题

### Q: 东财接口返回空或超时怎么办？
**A**: 所有接口使用 `em_get` 内置节流（1.2s 间隔 + 随机抖动）。若仍超时，增大 `EM_MIN_INTERVAL` 到 1.5s。若某日期返回空，可能数据尚未发布，等下个交易日再试。

### Q: `RPT_LICO_FN_CPD` 和 `RPT_F10_FINANCE_MAINFINADATA` 有什么区别？
**A**: `RPT_LICO_FN_CPD` 是业绩报表（简洁版），约 20 个字段，数据更新快，适合快速查询和排名。`RPT_F10_FINANCE_MAINFINADATA` 是 F10 完整财务指标，80+ 字段（毛利率/净利率/现金流/资产负债率/单季度同比等），适合深度分析和拐点检测。

### Q: 单季度数据 vs 累计数据有什么区别？
**A**: 东财 API 返回的都是**累计**数据。例如"2026年 中报"的营收是 1-6 月的**总和**，不是 4-6 月的单季数据。`extract_single_quarter()` 已实现累计→单季度差分计算，并自动算单季度同比（与去年同季度相比）。

### Q: 业绩快报（YJKB）怎么获取？
**A**: 东财 datacenter 的业绩快报 reportName 尚未实测验证。当前替代方案：
1. 巨潮公告：`cninfo_announcements(keyword="业绩快报")`
2. 后续版本将补上直连 API

### Q: 如何判断"业绩变脸"？
**A**: 查询同一个股同一报告期的多次预告记录，对比 `PREDICT_TYPE` 和 `PREDICT_AMT_*` 的变化。从"预增"变为"预减"或净利区间大幅下修 → 业绩变脸。

---

## 风险声明

- **数据来源**：东财 datacenter、同花顺一致预期。原始数据可能有延迟或误差
- **业绩预告**：为上市公司自行发布初步预测，实际业绩可能与预告存在偏差
- **一致预期**：为多家机构预测均值，不代表任何单一机构的准确预测
- **研究边界**：本 skill 提供业绩数据获取与分析工具，不构成任何投资建议。业绩好 ≠ 股价涨，市场定价受多重因素影响
- **风控合规**：所有东财接口走 `em_get` 节流机制。若频繁调用触发风控（HTTP 000/连接重置），暂停 5-10 分钟后重试
