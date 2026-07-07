# API 字段速查参考

> 补充 SKILL.md 中的字段说明，按 API 端点分组。完整列表供快速查阅。

---

## RPT_PUBLIC_OP_NEWPREDICT（业绩预告）

**端点**: `datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_PUBLIC_OP_NEWPREDICT`
**实测日期**: 2026-07-03
**记录量**: ~186,012

### 核心字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `SECUCODE` | str | 带市场后缀的代码 | `002396.SZ` |
| `SECURITY_CODE` | str | 6位股票代码 | `002396` |
| `SECURITY_NAME_ABBR` | str | 股票简称 | `星网锐捷` |
| `NOTICE_DATE` | str | 公告日期 | `2026-07-03 00:00:00` |
| `REPORT_DATE` | str | 报告期截止日期 | `2026-06-30 00:00:00` |
| `PREDICT_TYPE` | str | 预告类型 | `预增`/`略增`/`略减`/`预减`/`首亏`/`续亏`/`扭亏`/`续盈`/`不确定` |
| `PREDICT_FINANCE` | str | 预告财务指标 | `归母净利润`/`扣非净利润`/`每股收益`/`营业收入` |
| `PREDICT_FINANCE_CODE` | str | 指标代码 | `003`/`005`/`006` |
| `PREDICT_AMT_LOWER` | float | 预告金额下限（万元） | |
| `PREDICT_AMT_UPPER` | float | 预告金额上限（万元） | |
| `FORECAST_STATE` | str | 预告方向 | `increase`/`reduction` |
| `IS_LATEST` | str | 是否最新预告 | `T`/`F` |

### 可用筛选条件

- `SECURITY_CODE` — 个股精确筛选
- `NOTICE_DATE` — 公告日期范围
- `REPORT_DATE` — 报告期筛选
- `PREDICT_TYPE` — 预告类型筛选
- `FORECAST_STATE` — 方向筛选

---

## RPT_LICO_FN_CPD（上市公司财务数据/业绩报表）

**端点**: `datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_LICO_FN_CPD`
**实测日期**: 2026-07-03
**记录量**: ~485,515

### 核心字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `SECUCODE` | str | 带市场后缀的代码 | `000001.SZ` |
| `SECURITY_CODE` | str | 6位股票代码 | `000001` |
| `SECURITY_NAME_ABBR` | str | 股票简称 | `平安银行` |
| `TRADE_MARKET` | str | 交易市场 | `深交所主板` |
| `SECURITY_TYPE` | str | 证券类型 | `A股` |
| `REPORTDATE` | str | 报告期截止日期 | `2026-03-31 00:00:00` |
| `QDATE` | str | 季度标识 | `2026Q1` |
| `DATATYPE` | str | 报告类型名称 | `2026年 一季报` |
| `DATAYEAR` | str | 报告年份 | `2026` |
| `DATEMMDD` | str | 报告期别 | `一季报`/`中报`/`三季报`/`年报` |
| `BASIC_EPS` | float | 基本每股收益（元） | `0.67` |
| `DEDUCT_BASIC_EPS` | float | 扣非基本每股收益（元） | `0.67` |
| `TOTAL_OPERATE_INCOME` | float | 营业总收入（元） | `35277000000` |
| `PARENT_NETPROFIT` | float | 归母净利润（元） | `14523000000` |
| `WEIGHTAVG_ROE` | float | 加权平均ROE（%） | `2.83` |
| `BPS` | float | 每股净资产（元） | `23.91` |
| `MGJYXJJE` | float | 每股经营现金流（元） | `1.95` |
| `YSTZ` | float | 营收同比增长率（%） | `4.65` |
| `SJLTZ` | float | 归母净利同比增长率（%） | `3.0` |
| `XSMLL` | float | 销售毛利率（%），部分行业为空 | |
| `YSHZ` | float | 营收环比增长率（%） | `14.63` |
| `SJLHZ` | float | 净利环比增长率（%） | `238.22` |
| `ASSIGNDSCRPT` | str | 分配方案 | `10送4.00派3.00元...` |
| `NOTICE_DATE` | str | 实际披露日期 | `2026-04-25 00:00:00` |
| `ISNEW` | str | 是否最新一期 | `1`/`0` |
| `BOARD_NAME` | str | 所属行业板块名称 | `银行Ⅱ` |
| `BOARD_CODE` | str | 行业板块代码 | `BK0475` |
| `PUBLISHNAME` | str | 行业分类 | `银行Ⅱ` |
| `ZXGXL` | float | 最新股息率（%） | |

### 可用筛选条件

- `SECURITY_CODE` — 个股
- `QDATE` — 报告期（`2026Q1`等）
- `BOARD_CODE` — 行业板块
- `ISNEW` — 最新一期（`1`）
- `REPORTDATE` — 日期范围

### 注意事项

1. `TOTAL_OPERATE_INCOME`/`PARENT_NETPROFIT` 是**累计值**（如 Q2 = 上半年累计），需要 `extract_single_quarter()` 做差分
2. `YSTZ`/`SJLTZ` 是**累计同比**，非单季度同比
3. 银行/保险/券商等金融行业 `XSMLL`（毛利率）为空
4. 早期数据（1990年代）字段可能大量为空

---

## RPT_F10_FINANCE_MAINFINADATA（F10主要财务指标）

**端点**: `datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_F10_FINANCE_MAINFINADATA`
**实测日期**: 2026-07-03
**记录量**: ~676,731

### 核心字段（按类别分组）

#### 每股指标

| 字段 | 说明 | 单位 |
|------|------|------|
| `EPSJB` | 基本每股收益 | 元 |
| `EPSKCJB` | 扣非每股收益 | 元 |
| `EPSXS` | 稀释每股收益 | 元 |
| `BPS` | 每股净资产 | 元 |
| `MGZBGJ` | 每股资本公积金 | 元 |
| `MGWFPLR` | 每股未分配利润 | 元 |
| `MGJYXJJE` | 每股经营现金流 | 元 |

#### 成长性指标（同比）

| 字段 | 说明 | 单位 |
|------|------|------|
| `TOTALOPERATEREVETZ` | 营业总收入同比增长率 | % |
| `PARENTNETPROFITTZ` | 归母净利润同比增长率 | % |
| `KCFJCXSYJLRTZ` | 扣非归母净利润同比增长率 | % |
| `EPSJBTZ` | 基本每股收益同比增长率 | % |
| `BPSTZ` | 每股净资产同比增长率 | % |
| `TOTALOPERATEREVE` | 营业总收入（累计） | 元 |
| `PARENTNETPROFIT` | 归母净利润（累计） | 元 |
| `KCFJCXSYJLR` | 扣非归母净利润（累计） | 元 |

#### 单季度指标（★ 拐点检测核心字段）

| 字段 | 说明 | 单位 |
|------|------|------|
| `DJD_TOI_YOY` | 单季度营业总收入同比 | % |
| `DJD_DPNP_YOY` | 单季度归母净利润同比 | % |
| `DJD_DEDUCTDPNP_YOY` | 单季度扣非净利润同比 | % |
| `DJD_TOI_QOQ` | 单季度营业总收入环比 | % |
| `DJD_DPNP_QOQ` | 单季度归母净利润环比 | % |
| `DJD_DEDUCTDPNP_QOQ` | 单季度扣非净利润环比 | % |

#### 盈利能力指标

| 字段 | 说明 | 单位 |
|------|------|------|
| `ROEJQ` | 净资产收益率 | % |
| `ROEKCJQ` | 扣非净资产收益率 | % |
| `XSMLL` | 销售毛利率 | % |
| `XSJLL` | 销售净利率 | % |
| `ZZCJLL` | 总资产净利率 | % |
| `TOTAL_ROI` | 总资产报酬率（金融） | % |
| `NET_ROI` | 净资产报酬率（金融） | % |
| `ROIC` | 投入资本回报率 | % |

#### 偿债能力/资本结构

| 字段 | 说明 | 单位 |
|------|------|------|
| `ZCFZL` | 资产负债率 | % |
| `QYCS` | 权益乘数 | |
| `CQBL` | 产权比率 | |
| `LD` | 流动比率 | |
| `SD` | 速动比率 | |

#### 营运能力

| 字段 | 说明 | 单位 |
|------|------|------|
| `TOAZZL` | 总资产周转率 | 次 |
| `YSZKZZTS` | 应收账款周转天数 | 天 |
| `CHZZTS` | 存货周转天数 | 天 |
| `CHZZL` | 存货周转率 | 次 |

#### 现金流量

| 字段 | 说明 | 单位 |
|------|------|------|
| `MGJYXJJE` | 每股经营现金流 | 元 |
| `NETCASH_OPERATE_PK` | 经营性现金流量净额 | 元 |
| `NETCASH_INVEST_PK` | 投资性现金流量净额 | 元 |
| `NETCASH_FINANCE_PK` | 筹资性现金流量净额 | 元 |

#### 元数据

| 字段 | 说明 | 示例 |
|------|------|------|
| `REPORT_DATE` | 报告期 | `2026-03-31 00:00:00` |
| `REPORT_TYPE` | 报告类型 | `年报`/`中报`/`一季报`/`三季报` |
| `REPORT_DATE_NAME` | 报告期名称 | `2026一季报` |
| `NOTICE_DATE` | 实际披露日期 | `2026-04-25 00:00:00` |
| `ORG_TYPE` | 机构类型 | `银行`/`券商`/`保险`/`` |
| `IS_BZ` | 是否并表 | `0`/`1` |

### 可用筛选条件

- `SECURITY_CODE` — 个股
- `REPORT_DATE` — 报告期范围
- `REPORT_TYPE` — 报告类型

### 注意事项

1. 金融行业（银行/券商/保险）的毛利率、存货周转率等非金融指标为空
2. 早期数据（1990年代）大量字段为空
3. `DJD_*` 单季度字段从 2019 年左右开始有数据
4. 同比/环比字段可能为负值

---

## 快速交叉对照

| 数据需求 | 用哪个端点 | 关键字段 |
|---------|-----------|---------|
| 最新业绩预告 | RPT_PUBLIC_OP_NEWPREDICT | PREDICT_TYPE, PREDICT_AMT_* |
| 历史 EPS 序列 | RPT_LICO_FN_CPD | BASIC_EPS, QDATE |
| 营收/净利趋势 | RPT_LICO_FN_CPD | TOTAL_OPERATE_INCOME, PARENT_NETPROFIT, YSTZ, SJLTZ |
| 单季度业绩 | RPT_LICO_FN_CPD + extract_single_quarter() | 差分计算 |
| 毛利率 | RPT_F10_FINANCE_MAINFINADATA | XSMLL |
| 扣非净利 | RPT_F10_FINANCE_MAINFINADATA | KCFJCXSYJLR, EPSKCJB |
| 单季度同比（拐点信号） | RPT_F10_FINANCE_MAINFINADATA | DJD_TOI_YOY, DJD_DPNP_YOY |
| 资产负债率 | RPT_F10_FINANCE_MAINFINADATA | ZCFZL |
| 经营现金流 | RPT_F10_FINANCE_MAINFINADATA | NETCASH_OPERATE_PK, MGJYXJJE |
| 行业排名 | RPT_LICO_FN_CPD | 按 PARENT_NETPROFIT 排序，BOARD_CODE 过滤 |

---

## 历史数据覆盖说明

| 时期 | RPT_LICO_FN_CPD | RPT_F10_FINANCE_MAINFINADATA |
|------|----------------|------------------------------|
| 1990-1999 | 有数据但字段不全 | 有数据但字段不全 |
| 2000-2018 | 基本完整 | 基本完整，单季度字段从 2019 左右开始 |
| 2019-至今 | 完整 | 完整（含单季度同比环比） |
