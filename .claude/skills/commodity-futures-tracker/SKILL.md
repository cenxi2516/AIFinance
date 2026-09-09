---
name: commodity-futures-tracker
description: 大宗商品期货追踪器 V1.0 — 覆盖黄金/白银/稀土/工业金属/有色金属/能源金属/战争金属/工业材料等全球期货价格，实时拉取价格+涨跌幅，基于供需关系+政策+事件+产业趋势+量产数据等权威信息分析价格趋势，映射到A股相关板块。核心回答四个问题："涨了还是跌了？为什么涨跌？还会继续吗？A股怎么映射？"。触发词：期货、大宗商品、黄金价格、白银走势、铜价、铝价、稀土、碳酸锂、工业金属、能源金属、COMEX、LME、沪金、沪银、沪铜、商品价格趋势、供需关系。
version: 1.0.0
updated: 2026-07-23
---

# 大宗商品期货追踪器 V1.0

**定位**：14 技能架构的第 15 个 skill — 首个覆盖**非股票资产类别**的技能。聚焦全球大宗商品期货价格，回答四个问题：

> 1. **涨了还是跌了？** → 实时价格仪表盘，多品种多周期涨跌幅
> 2. **为什么涨跌？** → 供需关系 + 政策事件 + 产业趋势归因
> 3. **还会继续吗？** → 趋势研判 + 关键拐点信号检测
> 4. **A股怎么映射？** → 商品价格 → A 股板块/标的传导链

**核心原则**：==数据不交叉验证，不写入报告。== 所有价格数据需多源对比（新浪为主源+WebFetch/WebSearch为验证源）。供需分析必须以权威机构数据为基准（WBMS/ICSG/INSG/LME/SHFE等），不做无来源推测。

> **与现有 skill 的关系：**
> - `a-stock-data`：提供 A 股行情数据（用于映射验证和标的弹性计算）
> - `policy-event-tracker`：消费其政策事件输出，叠加商品维度的影响分析
> - `quant-dashboard`：为其提供商品价格信号作为宏观输入（商品是大类资产轮动的重要一环）
> - `industry-sentiment-tracker`：消费其行业情绪数据，验证商品→股票的传导有效性
> - `serenity-skill`：产业链瓶颈分析时，商品价格是关键的成本/利润输入
>
> **设计原则：** 依赖新浪 `hq.sinajs.cn` 直连 HTTP（零鉴权、免费），聚焦多品种价格拉取 → 涨跌归因 → 趋势研判 → A股映射。供需分析通过 WebSearch 获取权威机构数据。

## When to Activate

- 用户要看**大宗商品价格**（黄金/白银/铜/铝/稀土/锂/原油等涨跌）
- 用户要分析**商品价格趋势**（供需基本面 + 政策事件驱动）
- 用户要了解**商品→A股传导**（期货涨了但A股没涨 = 背离信号）
- 用户要判断**商品配置方向**（哪个品种当前最具供需矛盾）
- 用户要追踪**特定品种的产业链动态**（矿山停产/出口管制/收储抛储/新产能投产）
- 关键词：`期货`、`商品期货`、`大宗商品`、`黄金价格`、`白银走势`、`铜价`、`铝价`、`稀土价格`、`碳酸锂`、`工业金属`、`能源金属`、`有色金属期货`、`COMEX`、`LME`、`沪金`、`沪银`、`沪铜`、`战争金属`、`工业材料`、`黄金涨了还是跌了`、`商品价格趋势`、`供需关系`

**不适用场景**：
- 精确点位预测（研究边界约束，禁止）
- 个股买卖建议（用 fund-flow-predictor / stock-pick）
- A 股全市场研判（用 quant-dashboard）
- 纯产业链深度分析（用 serenity-skill）

---

## 核心框架：四层分析引擎

```
┌──────────────────────────────────────────────────────────────┐
│              commodity-futures-tracker V1.0                    │
│           全球大宗商品期货追踪 + 趋势研判 + A股映射              │
└──────────────┬───────────────────────────────────────────────┘
               │
     ┌─────────┴──────────┐
     ▼                    ▼
┌──────────────┐   ┌──────────────┐
│ 国际期货 (hf_)│   │ 国内期货 (nf_)│
│ COMEX/LME/   │   │ SHFE/DCE/    │
│ NYMEX/伦敦   │   │ CZCE/GFEX    │
└──────┬───────┘   └──────┬───────┘
       │                  │
       └────────┬─────────┘
                ▼
    ┌──────────────────────┐
    │ Layer 1: 价格仪表盘   │  ← 实时价+多周期涨跌幅+内外价差+技术位
    │ 新浪 hq.sinajs.cn    │
    └──────────┬───────────┘
               ▼
    ┌──────────────────────┐
    │ Layer 2: 供需基本面   │  ← 全球供需平衡+库存趋势+产能变化
    │ WebSearch 权威机构   │
    └──────────┬───────────┘
               ▼
    ┌──────────────────────┐
    │ Layer 3: 政策事件驱动 │  ← 出口管制/关税/矿山停产/收储抛储
    │ WebSearch+policy     │
    └──────────┬───────────┘
               ▼
    ┌──────────────────────┐
    │ Layer 4: A股传导映射  │  ← 商品价格→板块涨跌幅+弹性+背离
    │ a-stock-data 行情     │
    └──────────────────────┘
```

---

## Layer 0: 数据拉取 — 新浪期货行情 API

### 品种代码全集

详见 `references/commodity-universe.md`。核心品种代码速查：

```python
# ═══════════════════════════════════════════════════════════════
# 新浪期货行情 API (hq.sinajs.cn)
# 免费零鉴权，仅需 Referer。注意：有 10-15 分钟延迟。
# ═══════════════════════════════════════════════════════════════

# === 国际期货 (hf_ 前缀) ===
INTL_FUTURES = {
    # 贵金属 — COMEX
    "hf_GC":   "COMEX黄金",    "hf_SI":   "COMEX白银",
    # 贵金属 — 伦敦现货
    "hf_XAU":  "伦敦金(现货)",  "hf_XAG":  "伦敦银(现货)",
    # 工业金属 — COMEX
    "hf_HG":   "COMEX铜",
    # 工业金属 — LME
    "hf_CAD":  "LME铜",        "hf_AHD":  "LME铝",
    "hf_ZSD":  "LME锌",        "hf_NID":  "LME镍",
    "hf_PBD":  "LME铅",        "hf_SND":  "LME锡",
    # 能源 — NYMEX
    "hf_CL":   "WTI原油",      "hf_NG":   "天然气",
}

# === 国内期货 (nf_ 前缀，连续合约) ===
DOMESTIC_FUTURES = {
    # 贵金属 — 上期所
    "nf_AU0":  "沪金连续",      "nf_AG0":  "沪银连续",
    # 工业金属 — 上期所
    "nf_CU0":  "沪铜连续",      "nf_AL0":  "沪铝连续",
    "nf_ZN0":  "沪锌连续",      "nf_NI0":  "沪镍连续",
    "nf_PB0":  "沪铅连续",      "nf_SN0":  "沪锡连续",
    # 黑色系 — 大商所
    "nf_I0":   "铁矿石连续",    "nf_J0":   "焦炭连续",
    # 钢材 — 上期所
    "nf_RB0":  "螺纹钢连续",    "nf_RU0":  "天然橡胶连续",
    # 能源金属 — 广期所
    "nf_LC0":  "碳酸锂连续",    "nf_SI0":  "工业硅连续",
    # 化工 — 郑商所
    "nf_SA0":  "纯碱连续",
}
```

### 价格拉取函数

```python
import requests
import re
from datetime import datetime
from typing import Optional

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
SINA_FUTURES_URL = "https://hq.sinajs.cn/list="

def fetch_futures_prices(codes: list[str]) -> dict[str, dict]:
    """
    从新浪拉取期货行情，自动区分国际(hf_)/国内(nf_)品种。

    Args:
        codes: 品种代码列表，如 ["hf_GC", "nf_AU0", "hf_XAU"]

    Returns:
        {code: {
            "name": 品种名称,
            "price": 最新价,
            "open": 今开(国内)或昨收(国际),
            "high": 最高价,
            "low": 最低价,
            "prev_close": 昨收/昨结算,
            "time": 更新时间,
            "date": 日期,
            "change_pct": 涨跌幅%,
            "change_amt": 涨跌额,
            "source": "sina",
        }}
    """
    url = SINA_FUTURES_URL + ",".join(codes)
    headers = {
        "User-Agent": UA,
        "Referer": "https://finance.sina.com.cn",
    }
    r = requests.get(url, headers=headers, timeout=15)
    r.encoding = "gbk"
    text = r.text

    results = {}
    for line in text.strip().split("\n"):
        match = re.search(r'hq_str_(\w+)="([^"]*)"', line)
        if not match:
            continue
        code, data = match.groups()
        if not data:
            continue
        parts = data.split(",")

        if code.startswith("hf_"):
            # === 国际期货字段解析 ===
            # 两种字段模式：
            # 模式A (COMEX/LME/NYMEX, 15字段): [0]=最新价 [8]=昨收
            # 模式B (伦敦现货 XAU/XAG, 14字段): [0]=最新价 [1]=昨收
            # [6]=时间 [12]=日期 [倒数第2或第1个中文字段]=品种名
            price = safe_float(parts[0])

            # 根据字段数判断模式: 14字段→模式B(昨收在[1]), 15字段→模式A(昨收在[8])
            if len(parts) == 14:
                prev = safe_float(parts[1])  # 伦敦现货: 昨收在[1]
            else:
                prev = safe_float(parts[8])  # COMEX/LME/NYMEX: 昨收在[8]

            name_raw = ""
            for p in reversed(parts):
                if p and any('一' <= c <= '鿿' for c in p):
                    name_raw = p
                    break
            date_str = ""
            for p in parts:
                if re.match(r'\d{4}-\d{2}-\d{2}', p):
                    date_str = p
                    break
            time_str = ""
            for p in parts:
                if re.match(r'\d{2}:\d{2}:\d{2}', p):
                    time_str = p
                    break
            # 日高/日低 (COMEX/LME模式)
            day_high = safe_float(parts[4]) if len(parts) > 4 and parts[4] else 0
            day_low = safe_float(parts[5]) if len(parts) > 5 and parts[5] else 0
            # 开盘价
            open_p = safe_float(parts[3]) if len(parts) > 3 and parts[3] else 0

        elif code.startswith("nf_"):
            # === 国内期货字段解析 ===
            # [0]=合约名称, [1]=时间(HHMMSS), [2]=最新价, [3]=今开
            # [4]=最高, [5]=最低, [6]=昨结算
            name_raw = parts[0] if parts[0] else ""
            time_str_raw = parts[1] if len(parts) > 1 else ""
            # 格式化时间: 092416 → 09:24:16
            time_str = f"{time_str_raw[:2]}:{time_str_raw[2:4]}:{time_str_raw[4:6]}" if len(time_str_raw) >= 6 else time_str_raw
            price = safe_float(parts[2])
            open_p = safe_float(parts[3]) if len(parts) > 3 else 0
            day_high = safe_float(parts[4]) if len(parts) > 4 else 0
            day_low = safe_float(parts[5]) if len(parts) > 5 else 0
            prev = safe_float(parts[6]) if len(parts) > 6 else 0  # 昨结算
            date_str = parts[17] if len(parts) > 17 and parts[17] else ""  # 日期
        else:
            continue

        # 计算涨跌幅和涨跌额
        change_amt = 0
        change_pct = 0
        if prev and prev > 0:
            change_amt = round(price - prev, 4)
            change_pct = round((price - prev) / prev * 100, 2)

        results[code] = {
            "name": name_raw,
            "price": price,
            "open": open_p,
            "high": day_high,
            "low": day_low,
            "prev_close": prev,
            "time": time_str,
            "date": date_str,
            "change_pct": change_pct,
            "change_amt": change_amt,
            "source": "sina",
        }

    return results


def safe_float(val) -> float:
    """安全转换为float，空值返回0"""
    try:
        return float(val) if val else 0
    except (ValueError, TypeError):
        return 0
```

### 多品种批量拉取 + 分类展示

```python
def fetch_commodity_dashboard() -> dict:
    """
    拉取全品种价格仪表盘。
    返回按类别组织的价格数据，含涨跌幅排名。
    """
    all_codes = list(INTL_FUTURES.keys()) + list(DOMESTIC_FUTURES.keys())
    prices = fetch_futures_prices(all_codes)

    # 按类别分组
    categories = {
        "贵金属": {
            "国际": ["hf_GC", "hf_XAU", "hf_SI", "hf_XAG"],
            "国内": ["nf_AU0", "nf_AG0"],
            "描述": "黄金+白银，核心避险资产"
        },
        "工业金属": {
            "国际": ["hf_HG", "hf_CAD", "hf_AHD", "hf_ZSD", "hf_NID", "hf_PBD", "hf_SND"],
            "国内": ["nf_CU0", "nf_AL0", "nf_ZN0", "nf_NI0", "nf_PB0", "nf_SN0"],
            "描述": "铜铝锌镍铅锡，经济晴雨表"
        },
        "黑色系": {
            "国际": [],
            "国内": ["nf_I0", "nf_RB0", "nf_J0"],
            "描述": "铁矿石+螺纹钢+焦炭，地产基建风向标"
        },
        "能源": {
            "国际": ["hf_CL", "hf_NG"],
            "国内": [],
            "描述": "原油+天然气，通胀之锚"
        },
        "能源金属": {
            "国际": [],
            "国内": ["nf_LC0", "nf_SI0"],
            "描述": "碳酸锂+工业硅，新能源上游"
        },
    }

    # 计算涨跌排名
    ranked = sorted(
        [(c, d["change_pct"]) for c, d in prices.items() if d["price"] > 0],
        key=lambda x: x[1], reverse=True
    )

    return {
        "prices": prices,
        "categories": categories,
        "top_gainers": ranked[:5],
        "top_losers": ranked[-5:][::-1],
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
```

---

## Layer 1: 价格仪表盘 (Price Dashboard)

### 1.1 当日价格与涨跌幅

针对拉取到的全品种价格，按类别组织展示：

```python
def print_price_dashboard(dashboard: dict):
    """控制台打印价格仪表盘"""
    prices = dashboard["prices"]
    categories = dashboard["categories"]

    print(f"\n{'='*80}")
    print(f"  全球大宗商品期货价格仪表盘")
    print(f"  更新时间: {dashboard['fetch_time']}")
    print(f"  ⚠️ 数据源: 新浪财经 (10-15分钟延迟)")
    print(f"{'='*80}")

    for cat_name, cat_info in categories.items():
        intl_codes = cat_info["intl"]
        dom_codes = cat_info["国内"]
        all_cat_codes = intl_codes + dom_codes

        if not all_cat_codes:
            continue

        print(f"\n  ▸ {cat_name} — {cat_info['描述']}")
        print(f"  {'品种':<16s} {'最新价':>10s} {'涨跌幅':>8s} {'涨跌额':>8s}")
        print(f"  {'─'*16} {'─'*10} {'─'*8} {'─'*8}")

        for code in all_cat_codes:
            if code not in prices:
                continue
            d = prices[code]
            name = d["name"][:14]
            change_sign = "+" if d["change_pct"] >= 0 else ""
            print(f"  {name:<16s} {d['price']:>10.2f} {change_sign}{d['change_pct']:>7.2f}% {d['change_amt']:>8.2f}")

    # 涨幅/跌幅 TOP 5
    print(f"\n  ▸ 涨幅 TOP 5:")
    for i, (code, pct) in enumerate(dashboard["top_gainers"], 1):
        name = prices[code]["name"]
        print(f"    {i}. {name}({code}): +{pct:.2f}%")

    print(f"\n  ▸ 跌幅 TOP 5:")
    for i, (code, pct) in enumerate(dashboard["top_losers"], 1):
        name = prices[code]["name"]
        print(f"    {i}. {name}({code}): {pct:.2f}%")
```

### 1.2 多周期涨跌幅（需K线数据）

新浪免费接口不直接提供历史K线。历史趋势判断通过以下方式：

1. **WebSearch**：搜索"COMEX黄金 近5日走势""LME铜 本周涨跌"
2. **WebFetch**：访问 investing.com / tradingeconomics.com 等公开价格页面获取历史数据
3. **记录比对**：每次运行记录价格快照到本地 JSON，累积形成自建历史数据库

```python
import json
from pathlib import Path

def save_price_snapshot(prices: dict, snapshot_dir: str = ".claude/skills/commodity-futures-tracker/snapshots"):
    """保存价格快照到本地 JSON（用于自建历史数据库）"""
    dir_path = Path(snapshot_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    snapshot = {
        "date": today,
        "fetch_time": datetime.now().isoformat(),
        "prices": {code: {"price": d["price"], "change_pct": d["change_pct"]}
                   for code, d in prices.items() if d["price"] > 0}
    }
    file_path = dir_path / f"{today}.json"
    with open(file_path, "w") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return str(file_path)

def load_price_history(days: int = 30, snapshot_dir: str = ".claude/skills/commodity-futures-tracker/snapshots") -> dict:
    """加载最近N天的价格快照，计算多周期涨跌幅"""
    dir_path = Path(snapshot_dir)
    if not dir_path.exists():
        return {}
    snapshots = {}
    for f in sorted(dir_path.glob("*.json"))[-days:]:
        with open(f) as fp:
            snapshots[f.stem] = json.load(fp)
    return snapshots
```

### 1.3 内外价差检测

```python
# 同一品种的国内外价格对比
PRICE_PAIRS = [
    ("COMEX黄金", "hf_GC", "沪金", "nf_AU0"),   # 黄金
    ("COMEX银",   "hf_SI", "沪银", "nf_AG0"),    # 白银
    ("LME铜",     "hf_CAD","沪铜", "nf_CU0"),     # 铜
    ("LME铝",     "hf_AHD","沪铝", "nf_AL0"),     # 铝
    ("LME锌",     "hf_ZSD","沪锌", "nf_ZN0"),     # 锌
    ("LME镍",     "hf_NID","沪镍", "nf_NI0"),     # 镍
    ("LME铅",     "hf_PBD","沪铅", "nf_PB0"),     # 铅
    ("LME锡",     "hf_SND","沪锡", "nf_SN0"),     # 锡
]

def check_price_divergence(prices: dict, threshold: float = 3.0) -> list[dict]:
    """
    检测内外价差偏离度。
    国际涨但国内不涨 → 可能国内有独立利空
    国际跌但国内不跌 → 可能国内有独立利好（如收储预期）
    """
    divergences = []
    for intl_name, intl_code, dom_name, dom_code in PRICE_PAIRS:
        intl_d = prices.get(intl_code, {})
        dom_d = prices.get(dom_code, {})
        if not intl_d.get("price") or not dom_d.get("price"):
            continue
        intl_chg = intl_d.get("change_pct", 0)
        dom_chg = dom_d.get("change_pct", 0)
        diff = abs(intl_chg - dom_chg)
        if diff >= threshold:
            divergences.append({
                "intl_name": intl_name,
                "dom_name": dom_name,
                "intl_change": intl_chg,
                "dom_change": dom_chg,
                "diff": round(diff, 2),
                "signal": "国内偏强" if dom_chg > intl_chg else "国内偏弱",
            })
    return divergences
```

---

## Layer 2: 供需基本面分析

### 2.1 分析框架

供需分析回答关键问题：**当前是供过于求还是供不应求？趋势是对供给有利还是对需求有利？**

| 维度 | 关键数据 | 数据来源 |
|------|---------|---------|
| 全球供需平衡 | 精炼铜/铝/锌/镍/铅/锡 供需缺口(万吨) | WBMS/ICSG/INSG/ILZSG 月度报告 |
| 库存趋势 | LME/SHFE/COMEX 注册仓单(吨)、变化趋势 | 交易所周度库存报告 |
| 矿山产能 | 开工率、停产矿山、新投产项目 | 公司公告、行业报告 |
| 下游需求 | 新能源用铜/铝、电网投资、地产开工、汽车产量 | 国家统计局、行业协会 |
| 加工费 TC/RC | 铜精矿加工费（反映矿端紧张程度） | Fastmarkets/SMM |

### 2.2 典型搜索策略

```python
# 供需分析搜索模板（按品种）
SUPPLY_DEMAND_SEARCHES = {
    "铜": [
        "ICSG 全球铜供需平衡 2026 短缺 过剩",
        "LME铜库存 注册仓单 SHFE铜库存 2026年7月",
        "铜精矿加工费 TC RC 2026 最新",
        "全球铜矿 停产 罢工 新投产 2026",
    ],
    "铝": [
        "全球铝供需平衡 2026 中国铝产能上限",
        "LME铝库存 SHFE铝库存 2026年7月",
        "云南电解铝 限产 复产 2026",
    ],
    "黄金": [
        "全球央行购金 2026 黄金ETF持仓",
        "COMEX黄金库存 变化 2026",
        "美国实际利率 黄金 关系 2026",
    ],
    "碳酸锂": [
        "碳酸锂供需平衡 2026 过剩 去库",
        "锂矿停产 减产 2026 澳洲 南美",
        "碳酸锂库存 2026年7月 正极材料 排产",
    ],
    # 更多品种见 references/supply-demand-sources.md
}
```

### 2.3 供需评分卡

对每个品种做供需速评：

| 评分维度 | 权重 | 评分标准 |
|---------|------|---------|
| 供需缺口方向 | 30% | 短缺+3 / 平衡+1 / 过剩-2 |
| 库存趋势 | 25% | 去库+2 / 持平+0 / 累库-2 |
| 矿端供应 | 20% | 停产/减产+2 / 稳定+0 / 扩产-1 |
| 下游需求 | 15% | 加速增长+2 / 稳定+0 / 放缓-1 |
| 加工费(TC) | 10% | 走低+2(矿紧) / 稳定+0 / 走高-1(矿松) |

总分: >2=供给紧缺看涨, -1~2=供需平衡, <-1=供给过剩看跌

---

## Layer 3: 政策事件驱动分析

### 3.1 事件分类与影响评估

| 事件类型 | 影响方向 | 影响程度 | 持续时间 | 示例 |
|---------|---------|---------|---------|------|
| 出口管制/禁令 | 国外涨、国内跌 | 重度 | 6-24月 | 中国稀土出口管制、印尼镍矿禁令 |
| 矿山停产/罢工 | 全球涨 | 重度 | 1-6月 | Escondida罢工、Grasberg停产 |
| 关税/贸易战 | 内外分化 | 中度 | 3-12月 | 美国对华钢铝关税 |
| 收储/抛储 | 国内涨/跌 | 中度 | 1-3月 | 国储局收储铜/铝/锌 |
| 环保限产 | 国内涨 | 中度 | 1-3月 | 唐山限产、云南电解铝限电 |
| 新产能投产 | 全球跌 | 中度-轻度 | 6-24月 | 刚果金Kamoa铜矿二期投产 |
| 央行政策 | 黄金涨/跌 | 中度 | 3-12月 | 美联储降息预期、央行购金 |
| 地缘冲突 | 避险涨(金)/供应涨(油) | 重度(短期) | 1-3月 | 中东局势、俄乌冲突 |

### 3.2 搜索策略

```python
# 政策事件搜索模板
POLICY_EVENT_SEARCHES = [
    # 出口管制
    "中国 出口管制 稀土 锗 镓 钨 2026",
    "印尼 镍矿 出口禁令 铝土矿 2026",
    # 关税贸易
    "美国 对华 关税 钢铝 铜 2026",
    "欧盟 CBAM 碳边境调节 金属 2026",
    # 矿山供应
    "全球铜矿 停产 罢工 供应中断 2026年7月",
    "锂矿 减产 停产 2026 澳洲 Greenbushes",
    # 收储抛储
    "国储局 收储 抛储 有色金属 2026",
    # 宏观
    "美联储 降息 2026 黄金 美元",
    "中国 经济刺激 基建 房地产 金属需求 2026",
]
```

---

## Layer 4: A股传导映射

### 4.1 商品→A股映射表

详见 `references/commodity-universe.md` 完整映射。核心映射速查：

| 商品 | 国际代码 | 国内代码 | A股板块 | BK代码 | 核心标的 |
|------|---------|---------|--------|--------|---------|
| 黄金 | hf_GC/hf_XAU | nf_AU0 | 黄金概念 | BK0479 | 紫金矿业(601899)、山东黄金(600547)、中金黄金(600489) |
| 白银 | hf_SI/hf_XAG | nf_AG0 | 黄金概念 | BK0479 | 盛达资源(000603)、兴业银锡(000426) |
| 铜 | hf_CAD/hf_HG | nf_CU0 | 有色金属 | BK0478 | 紫金矿业(601899)、江西铜业(600362)、铜陵有色(000630) |
| 铝 | hf_AHD | nf_AL0 | 有色金属 | BK0478 | 中国铝业(601600)、南山铝业(600219)、云铝股份(000807) |
| 镍 | hf_NID | nf_NI0 | 能源金属 | BK1096 | 华友钴业(603799)、格林美(002340) |
| 碳酸锂 | — | nf_LC0 | 能源金属 | BK1096 | 天齐锂业(002466)、赣锋锂业(002460)、盐湖股份(000792) |
| 稀土 | — | — | 稀土永磁 | BK0457 | 北方稀土(600111)、中国稀土(000831) |
| 工业硅 | — | nf_SI0 | 小金属 | BK0643 | 合盛硅业(603260)、新安股份(600596) |

### 4.2 传导验证逻辑

```python
def verify_commodity_stock_transmission(commodity_changes: dict, stock_data: dict = None) -> dict:
    """
    验证商品价格→A股板块的传导是否生效。

    核心信号：
    - 正常传导：商品涨 + A股板块涨 → 市场认可
    - 背离信号：商品涨 + A股板块跌 → 可能有机会（补涨）或市场不买账
    - 领先信号：商品先涨3-5天 + A股板块滞后反应 → 关注窗口

    注意：稀土无直接期货品种，用北方稀土(600111)/中国稀土(000831)股价代理。
    """
    signals = []
    # 铜→有色金属板块
    cu_chg = commodity_changes.get("nf_CU0", 0)
    if abs(cu_chg) > 1:
        direction = "涨" if cu_chg > 0 else "跌"
        signals.append({
            "commodity": "铜",
            "change": cu_chg,
            "sector": "有色金属(BK0478)",
            "tickers": ["601899", "600362"],
            "expected_direction": direction,
            "note": f"沪铜{direction}{abs(cu_chg):.1f}%，关注有色板块是否跟随",
        })
    # 更多映射见 references/commodity-universe.md
    return signals
```

---

## 完整分析流程

### 流程 A: 每日全品种快报（Console）

```python
def daily_commodity_brief():
    """每日大宗商品快报 — 拉取全品种价格+涨跌幅，打印仪表盘"""
    print("正在拉取全球大宗商品期货行情...")
    dashboard = fetch_commodity_dashboard()

    # Part 1: 价格仪表盘
    print_price_dashboard(dashboard)

    # Part 2: 内外价差检测
    divergences = check_price_divergence(dashboard["prices"])
    if divergences:
        print(f"\n  ⚠️ 内外价差偏离 (>3%):")
        for d in divergences:
            print(f"    {d['intl_name']}({d['intl_change']:+.2f}%) vs "
                  f"{d['dom_name']}({d['dom_change']:+.2f}%) → {d['signal']} (差{d['diff']:.1f}%)")

    # Part 3: 保存价格快照
    snapshot_path = save_price_snapshot(dashboard["prices"])
    print(f"\n  📁 价格快照已保存: {snapshot_path}")

    return dashboard
```

### 流程 B: 单品种深度分析（含供需+政策+事件）

```python
def deep_dive_commodity(commodity: str, codes: list[str]):
    """
    单品种深度分析。
    commodity: 品种中文名, 如 "铜"
    codes: 对应的期货代码, 如 ["hf_CAD", "nf_CU0"]
    """
    # Step 1: 拉取价格
    prices = fetch_futures_prices(codes)

    # Step 2: 拉取历史快照（自建数据库）
    history = load_price_history(30)

    # Step 3: 搜索供需数据
    # 用 WebSearch 搜索 ICSG/LME库存/加工费 等
    # （具体搜索词见 SUPPLY_DEMAND_SEARCHES）

    # Step 4: 搜索政策事件
    # 用 WebSearch 搜索政策/事件

    # Step 5: 映射到A股
    # 用 a-stock-data 拉取对应板块行情

    # Step 6: 输出研判报告
    # 价格趋势 + 供需评分 + 事件影响 + A股传导 + 风险提示
```

### 流程 C: 全品种周度研报（Markdown 输出）

输出到 `src/有色金属/YYYY-MM-DD-大宗商品追踪/report.md`，包含：
- Part 1: 全品种价格仪表盘（表格形式）
- Part 2: 涨跌幅排名与板块轮动
- Part 3: 重点品种供需分析（铜/铝/金/锂/稀土）
- Part 4: 政策事件追踪（最近1-2周）
- Part 5: A股传导验证（期货涨跌 vs 板块涨跌）
- Part 6: 风险提示与下周关注

---

## 风控边界

- ✅ **提供**：价格趋势研判、供需分析框架、传导逻辑推理、风险信号检测、多情景推演
- ❌ **严禁**：精确价格预测、杠杆/保证金策略、买卖指令、承诺收益
- ⚠️ **数据延迟**：新浪免费 API 有 10-15 分钟延迟，不适合日内短线参考
- ⚠️ **单源风险**：新浪期货数据为单一来源，报告中必须标注"⚠️ 单源，未经交叉验证"
- ⚠️ **稀土代理**：稀土无直接期货品种，通过 A 股股价代理，需明确标注

---

## 已知限制与后续改进

1. **历史K线**：新浪免费接口不提供期货历史K线。当前通过 WebSearch+WebFetch 访问公开价格页面补充，并自建本地快照数据库。
2. **交叉验证**：当前仅新浪一个期货数据源。后续可接入 Bloomberg/Wind 终端数据，或通过 investing.com 页面抓取做交叉验证。
3. **稀土指标**：稀土无期货品种，需维护稀土氧化物现货价格的手动采集或通过行业协会数据。
4. **库存数据**：LME/SHFE 库存数据通过 WebSearch 获取，非结构化。后续可接入交易所公开 API。
5. **黄金ETF持仓**：SPDR Gold Trust (GLD) 持仓变化是黄金的重要先行指标，后续可接入。
6. **时区差异** ⚠️：国际期货（hf_）在亚洲上午时段变动极小（欧美市场未开），涨跌幅主要反映隔夜电子盘。国内期货（nf_）在 09:00-15:00 交易活跃，数据更具参考价值。分析时需注意时区上下文。
7. **昨收解析** ⚠️：国际期货字段布局不一致。COMEX/LME/NYMEX（15字段）昨收在[8]，伦敦现货 XAU/XAG（14字段）昨收在[1]。代码已按字段数自动判别。

---

## 安装说明

```bash
# 1. 创建 skill 目录（已完成）
mkdir -p .claude/skills/commodity-futures-tracker/references

# 2. 安装依赖（与项目共用 venv）
pip install requests

# 3. 在 Claude Code 中触发
# 说 "大宗商品今天怎么样" 或 "黄金期货涨了还是跌了" 即可自动激活
```
