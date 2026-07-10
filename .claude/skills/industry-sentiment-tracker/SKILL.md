---
name: industry-sentiment-tracker
description: A股行业情绪指数追踪 — 覆盖全市场/8大行业/细分方向三级情绪指数，五维度加权合成(资金面25%+价格面20%+宽度面20%+量能面15%+涨停面20%)，输出0-100量化情绪分。核心能力：①全市场情绪总览 ②行业级情绪排名与热力图 ③细分方向情绪 drill-down(如半导体→设备/材料/存储/CPU/通信/芯片) ④情绪趋势追踪(日/周变化) ⑤与capital-flow-tracker/limit-up-tracker/etf-fund-flow-tracker多维交叉验证。适用于市场情绪判断、行业轮动确认、极端情绪拐点检测。
version: 1.0.0
updated: 2026-07-09
---

# A股行业情绪指数追踪器 V1.0

全市场行业情绪量化工具——覆盖 8 大行业 + 细分方向，五维度加权合成 0-100 情绪指数。**核心价值：将分散在多个 skill 中的情绪信号（资金流、涨停、热榜）统一量化为可比较的情绪指数，实现行业级和细分方向级的情绪追踪。**

> **设计原则：** 依赖 a-stock-data 的通用 helper（`em_get`），本 skill 聚焦多维度情绪合成、行业聚合、趋势追踪和信号检测。
>
> **与现有 skill 的关系：** capital-flow-tracker 看"钱去哪了"，limit-up-tracker 看"情绪有多热"，etf-fund-flow-tracker 看"机构怎么配"。本 skill 将三者信号统一量化为 0-100 分数，支持行业间横向对比和纵向趋势追踪。

## When to Activate

- 用户要看**市场整体情绪**（A股现在是热还是冷）
- 用户要看**行业情绪排名**（哪些行业最热、哪些最冷）
- 用户要分析**细分方向情绪**（半导体里设备vs材料vs存储谁更强）
- 用户要检测**情绪拐点**（连续降温后首次升温 / 过度亢奋后的风险）
- 用户要做**多维交叉验证**（情绪分 + 资金流 + 涨停 + ETF 是否共振）
- 关键词：`情绪指数`、`行业情绪`、`市场情绪`、`情绪热力图`、`情绪温度`、`半导体情绪`、`板块热度`、`市场热度`

## Prerequisites — 数据拉取全部委托给 a-stock-api

本 skill **不内置数据拉取代码**。所有行情/资金流/新闻/板块/融资融券/龙虎榜数据，统一通过项目共享模块 `a_stock_api` 获取。

```python
import sys
sys.path.insert(0, '.claude/skills/_shared')
from a_stock_api import (
    em_get,                    # 东财统一请求入口（已内置限流+重试）
    eastmoney_datacenter,      # 东财数据中心通用查询
    tencent_quote,             # 腾讯行情（PE/PB/市值/换手率，不封IP）
    stock_fund_flow_120d,      # 个股资金流120日
    eastmoney_fund_flow_minute, # 个股资金流分钟级
    industry_comparison,       # 行业板块排名
    eastmoney_concept_blocks,  # 个股概念板块归属
    eastmoney_stock_news,      # 个股新闻
    concept_sector_fund_flow,  # 概念板块资金流
    em_zt_pool,               # 涨停池
    full_valuation,            # 完整估值
)
```

> 所有 `eastmoney.com` 请求已内置限流（≥1s 间隔 + 随机抖动 + Keep-Alive + 自动重试），无需自行实现。

---

## Layer 1: 行业-概念板块映射

完整的行业→概念板块→细分方向映射表见 `references/industry-concept-mapping.py`。本层提供 BK 码动态初始化逻辑。

### 1.1 BK 码动态初始化

```python
# 模块级缓存
_BK_CACHE = {}       # {concept_name: bk_code}
_CONCEPT_LIST = []   # 全量概念板块列表 [{code, name}]
_INITIALIZED = False

PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

def _load_all_concepts() -> list[dict]:
    """加载全量概念板块列表（含 BK 码），自动缓存"""
    global _CONCEPT_LIST
    if _CONCEPT_LIST:
        return _CONCEPT_LIST
    params = {
        "pn": "1", "pz": "500", "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",
        "fields": "f12,f14",
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    r = em_get(PUSH2_CLIST, params=params, headers=headers, timeout=15)
    d = r.json()
    _CONCEPT_LIST = [
        {"code": it.get("f12", ""), "name": it.get("f14", "")}
        for it in (d.get("data", {}).get("diff", []) or [])
    ]
    return _CONCEPT_LIST


def find_concept_code(keyword: str) -> list[dict]:
    """按关键字搜索概念板块 BK 码"""
    all_concepts = _load_all_concepts()
    keyword_lower = keyword.lower()
    return [c for c in all_concepts if keyword_lower in c["name"].lower()]


def init_bk_codes(force_refresh: bool = False) -> dict:
    """
    初始化映射表中所有概念板块的 BK 码。
    首次调用从东财 API 动态查询，后续使用缓存。
    
    返回: {concept_name: bk_code}
    """
    global _BK_CACHE, _INITIALIZED
    if _INITIALIZED and not force_refresh:
        return _BK_CACHE

    # 从映射表收集所有概念板块名称
    # 注意: 在 skill 运行环境中需调整 import 路径
    try:
        from industry_concept_mapping import get_all_concept_names
    except ImportError:
        # 内联定义（独立运行时）
        get_all_concept_names = _inline_get_all_concept_names
    
    all_names = get_all_concept_names()
    all_concepts = _load_all_concepts()
    
    # 建立名称→BK码索引
    name_index = {c["name"]: c["code"] for c in all_concepts}
    
    _BK_CACHE = {}
    for name in all_names:
        # 精确匹配
        if name in name_index:
            _BK_CACHE[name] = name_index[name]
            continue
        # 模糊匹配（取包含关系最佳匹配）
        matches = [c for c in all_concepts if name in c["name"] or c["name"] in name]
        if matches:
            _BK_CACHE[name] = matches[0]["code"]
        else:
            _BK_CACHE[name] = None
    
    _INITIALIZED = True
    
    # 统计
    found = sum(1 for v in _BK_CACHE.values() if v)
    total = len(_BK_CACHE)
    print(f"[BK码初始化] 匹配 {found}/{total} 个概念板块")
    if found < total:
        missing = [k for k, v in _BK_CACHE.items() if not v]
        print(f"  未匹配 ({len(missing)}): {', '.join(missing[:10])}")
    
    return _BK_CACHE


def get_bk_code(concept_name: str) -> str | None:
    """获取单个概念板块的 BK 码"""
    if not _INITIALIZED:
        init_bk_codes()
    return _BK_CACHE.get(concept_name)
```

### 1.2 映射表快速参考

| 行业 | 概念板块数 | 细分方向 |
|------|-----------|---------|
| 半导体 | 8 | 设备 / 材料 / 存储 / CPU算力 / 先进封装 / 通信芯片 |
| AI与算力 | 8 | 算力基础设施 / AI应用 / 机器人 |
| 新能源 | 8 | 光伏 / 储能 / 锂电 / 风电 |
| 消费 | 6 | 白酒 / 食品 / 零售 |
| 医药 | 6 | 创新药 / 医疗器械 / 中药 |
| 军工 | 6 | 航空航天 / 军工电子 |
| 金融 | 4 | 券商 / 银行 / 保险 |
| 汽车 | 4 | 整车 / 零部件 / 智能驾驶 |

---

## Layer 2: 多维度原始数据采集

### 2.1 全量概念板块快照（一次请求）

```python
def fetch_all_concept_snapshot() -> dict[str, dict]:
    """
    一次 push2 clist 请求拉取全量概念板块行情+资金数据。
    
    fs=m:90+t:3 = 概念板块（约 494 个）
    
    返回: {concept_name: {
        code, name, price, change_pct, main_net, super_large_net,
        large_net, mid_net, small_net, up_count, down_count,
        turnover_pct, vol_ratio, total_mcap
    }}
    """
    params = {
        "pn": "1", "pz": "500", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",
        "fields": "f2,f3,f8,f10,f12,f14,f20,f62,f66,f72,f78,f84,f104,f105,f128",
        "st": "f62",
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    try:
        r = em_get(PUSH2_CLIST, params=params, headers=headers, timeout=20)
        d = r.json()
    except Exception as e:
        print(f"[ERROR] 概念板块快照拉取失败: {e}")
        return {}

    items = d.get("data", {}).get("diff", []) or []
    total = d.get("data", {}).get("total", 0)
    print(f"[数据采集] 概念板块: {len(items)}/{total} 条")

    snapshot = {}
    for it in items:
        name = it.get("f14", "")
        snapshot[name] = {
            "code": it.get("f12", ""),
            "name": name,
            "price": it.get("f2") or 0,
            "change_pct": it.get("f3") or 0,
            "turnover_pct": it.get("f8") or 0,
            "vol_ratio": it.get("f10") or 0,
            "total_mcap": it.get("f20") or 0,
            "main_net": it.get("f62") or 0,
            "super_large_net": it.get("f66") or 0,
            "large_net": it.get("f72") or 0,
            "mid_net": it.get("f78") or 0,
            "small_net": it.get("f84") or 0,
            "up_count": it.get("f104") or 0,
            "down_count": it.get("f105") or 0,
            "leader_name": it.get("f128", ""),
        }
    return snapshot
```

### 2.2 涨停池情绪数据

```python
PUSH2EX = "https://push2ex.eastmoney.com/getTopicZTPool"

def fetch_limit_up_sentiment(date_str: str = None) -> dict:
    """
    获取当日全市场涨停情绪宏观指标。
    
    返回: {
        zt_count, dt_count, break_rate, max_height,
        ladder: {连板数: 家数},
        concept_zt_map: {概念板块名: 涨停家数}
    }
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    
    params = {
        "sort": "fbt", "asc": "1",
        "pageindex": "0", "pagesize": "500",
        "po": "1", "pz": "500", "pn": "1",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "c,n,p,zdp,amount,ltsz,hs,lbc,fbt,lbt,fund,zbc,hybk,zttj",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    
    zt_list = []
    try:
        r = em_get(PUSH2EX, params={**params, "st": "zttj"}, headers=headers, timeout=15)
        d = r.json()
        for p in (d.get("data", {}).get("pool", []) or []):
            zt_list.append({
                "code": p.get("c", ""),
                "name": p.get("n", ""),
                "limit_days": p.get("lbc", 0),
                "first_seal": p.get("fbt", ""),
                "break_times": p.get("zbc", 0),
                "industry": p.get("hybk", ""),
                "zt_stat": p.get("zttj", ""),
            })
    except Exception as e:
        print(f"[WARN] 涨停池拉取失败: {e}")
        return {}

    # 拉取跌停池
    dt_count = 0
    try:
        r2 = em_get(PUSH2EX, params={**params, "fs": "m:0+t:80"},
                    headers=headers, timeout=15)
        d2 = r2.json()
        dt_count = len(d2.get("data", {}).get("pool", []) or [])
    except Exception:
        pass

    # 计算情绪指标
    zt_count = len(zt_list)
    
    # 连板梯队
    ladder = defaultdict(int)
    for s in zt_list:
        ladder[s["limit_days"]] += 1
    
    max_height = max(ladder.keys()) if ladder else 0
    
    # 炸板率（炸板次数>0的占比）
    zb_related = sum(1 for s in zt_list if s.get("break_times", 0) > 0)
    break_rate = round(zb_related / zt_count * 100, 1) if zt_count else 0
    
    # 涨停股 → 概念板块映射
    concept_zt_map = defaultdict(int)
    for s in zt_list:
        industry = s.get("industry", "")
        if industry:
            concept_zt_map[industry] += 1
    
    return {
        "date": date_str,
        "zt_count": zt_count,
        "dt_count": dt_count,
        "break_rate": break_rate,
        "max_height": max_height,
        "ladder": dict(sorted(ladder.items())),
        "concept_zt_map": dict(concept_zt_map),
    }
```

### 2.3 同花顺热榜

```python
def fetch_ths_hot_sentiment() -> dict:
    """
    同花顺热榜 → 概念热度聚合。
    返回: {
        hot_stocks: [{code, name, heat, concepts, rank_chg}],
        concept_heat_map: {概念名: 累计人气值}
    }
    """
    url = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"
    params = {"stock_type": "a", "type": "day", "list_type": "normal"}
    headers = {"User-Agent": UA, "Referer": "https://data.10jqka.com.cn/"}
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        items = d.get("data", []) or []
    except Exception as e:
        print(f"[WARN] 同花顺热榜失败: {e}")
        return {"hot_stocks": [], "concept_heat_map": {}}
    
    hot_stocks = []
    concept_heat_map = defaultdict(float)
    
    for it in items:
        code = it.get("code", "")
        name = it.get("name", "")
        heat = it.get("rate", 0)
        concepts = []
        tag_data = it.get("tag", {}) or {}
        concept_tags = tag_data.get("concept_tag", []) or []
        for ct in concept_tags:
            cn = ct.get("name", "") if isinstance(ct, dict) else str(ct)
            if cn:
                concepts.append(cn)
                concept_heat_map[cn] += float(heat)
        
        hot_stocks.append({
            "code": code,
            "name": name,
            "heat": heat,
            "concepts": concepts,
            "rank_chg": it.get("hot_rank_chg", 0),
        })
    
    return {
        "hot_stocks": hot_stocks,
        "concept_heat_map": dict(concept_heat_map),
    }
```

---

## Layer 3: 五维度情绪分项计算

### 3.1 通用评分函数

```python
def sigmoid_score(x: float, center: float = 0, scale: float = 1.0,
                  out_min: float = 0, out_max: float = 100) -> float:
    """
    Sigmoid 映射到 [out_min, out_max]。
    在 center 附近最敏感（约 50 分），两端趋于饱和。
    
    例: sigmoid_score(3, center=0, scale=2) → ~82
        sigmoid_score(-3, center=0, scale=2) → ~18
    """
    try:
        return out_min + (out_max - out_min) / (1 + math.exp(-(x - center) / scale))
    except OverflowError:
        return out_max if x > center else out_min


def clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))
```

### 3.2 资金面情绪 (25%)

```python
def calc_fund_flow_sentiment(d: dict) -> float:
    """
    资金面情绪 = 主力净流入方向 + 力度 + 机构资金(超大单)占比。
    返回: 0-100
    """
    main_net = d.get("main_net", 0) or 0
    super_net = d.get("super_large_net", 0) or 0
    mcap = d.get("total_mcap", 1) or 1
    
    # 1. 主力净流入力度得分 (0-50)
    flow_ratio = (main_net / mcap) * 10000 if mcap > 0 else 0
    flow_score = sigmoid_score(flow_ratio, center=0, scale=1.5, out_max=50)
    
    # 2. 超大单占比得分 (0-30)
    if main_net > 0:
        super_ratio = clamp(super_net / main_net, 0, 1) if main_net else 0
        super_score = super_ratio * 30
    elif main_net < 0:
        super_ratio = clamp(abs(super_net / main_net), 0, 1) if main_net else 0
        super_score = (1 - super_ratio) * 30
    else:
        super_score = 15
    
    # 3. 流入流出家数比得分 (0-20)
    up_n = d.get("up_count", 0) or 0
    down_n = d.get("down_count", 0) or 0
    total_n = up_n + down_n
    breadth_ratio = up_n / total_n if total_n > 0 else 0.5
    breadth_score = breadth_ratio * 20
    
    return clamp(flow_score + super_score + breadth_score)
```

### 3.3 价格面情绪 (20%)

```python
def calc_price_momentum_sentiment(d: dict, market_avg_pct: float = 0) -> float:
    """
    价格面情绪 = 涨跌幅动量 + 相对强度。
    返回: 0-100
    """
    change_pct = d.get("change_pct", 0) or 0
    
    # 1. 涨跌幅 sigmoid 映射 (0-60)
    price_score = sigmoid_score(change_pct, center=0, scale=2.0, out_max=60)
    
    # 2. 相对强度得分 (0-40)
    relative = change_pct - market_avg_pct
    relative_score = sigmoid_score(relative, center=0, scale=1.5, out_max=40)
    
    return clamp(price_score * 0.6 + relative_score * 0.4)


def calc_market_avg_change(snapshot: dict[str, dict]) -> float:
    """计算全市场概念板块平均涨跌幅"""
    if not snapshot:
        return 0
    pcts = [d.get("change_pct", 0) or 0 for d in snapshot.values()]
    return sum(pcts) / len(pcts) if pcts else 0
```

### 3.4 宽度面情绪 (20%)

```python
def calc_breadth_sentiment(d: dict, concept_zt_map: dict = None) -> float:
    """
    宽度面情绪 = 上涨占比 + 板块内涨停力度 + 领涨股表现。
    返回: 0-100
    """
    up_n = d.get("up_count", 0) or 0
    down_n = d.get("down_count", 0) or 0
    total_n = up_n + down_n
    
    # 1. 上涨家数占比 (0-50)
    up_ratio = up_n / total_n if total_n > 0 else 0.5
    breadth_score = up_ratio * 50
    
    # 2. 板块内涨停热度 (0-30)
    concept_name = d.get("name", "")
    zt_in_sector = (concept_zt_map or {}).get(concept_name, 0)
    zt_ratio = min(zt_in_sector / max(total_n, 1), 1.0) if total_n > 0 else 0
    zt_score = sigmoid_score(zt_ratio * 100, center=2, scale=2, out_max=30)
    
    # 3. 领涨股表现 (0-20)
    leader = d.get("leader_name", "")
    has_leader = 10 if leader else 0
    leader_score = clamp(has_leader + zt_in_sector * 2, 0, 20)
    
    return clamp(breadth_score + zt_score + leader_score)
```

### 3.5 量能面情绪 (15%)

```python
def calc_volume_sentiment(d: dict) -> float:
    """
    量能面情绪 = 换手率合理区间 + 量比偏离度。
    换手率最优区间 2%-8%，太高(过度投机)或太低(无人问津)都扣分。
    返回: 0-100
    """
    turnover = d.get("turnover_pct", 0) or 0
    vol_ratio = d.get("vol_ratio", 0) or 0
    
    # 1. 换手率得分 (0-60)
    if 4 <= turnover <= 6:
        turnover_score = 60
    elif 2 <= turnover <= 8:
        dist = abs(turnover - 5) / 3
        turnover_score = 60 - dist * 10
    elif 1 <= turnover < 2 or 8 < turnover <= 15:
        turnover_score = 45
    elif 0.5 <= turnover < 1 or 15 < turnover <= 20:
        turnover_score = 30
    elif turnover < 0.5:
        turnover_score = 15
    else:
        turnover_score = 20
    
    # 2. 量比得分 (0-40)
    if vol_ratio >= 2.0:
        vol_score = 40
    elif vol_ratio >= 1.5:
        vol_score = 35
    elif vol_ratio >= 1.0:
        vol_score = 30
    elif vol_ratio >= 0.7:
        vol_score = 20
    elif vol_ratio >= 0.5:
        vol_score = 10
    else:
        vol_score = 5
    
    return clamp(turnover_score + vol_score)
```

### 3.6 涨停面情绪 (20%)

```python
def calc_limit_up_sentiment_for_concept(
    d: dict, concept_zt_map: dict, ladder: dict) -> float:
    """
    涨停面情绪 = 板块涨停数 + 高标存在 + 炸板率惩罚。
    返回: 0-100
    """
    concept_name = d.get("name", "")
    zt_count = concept_zt_map.get(concept_name, 0)
    total_stocks = (d.get("up_count", 0) or 0) + (d.get("down_count", 0) or 0)
    
    # 1. 板块涨停数得分 (0-50)
    if zt_count >= 8:      zt_num_score = 50
    elif zt_count >= 5:    zt_num_score = 40
    elif zt_count >= 3:    zt_num_score = 30
    elif zt_count >= 1:    zt_num_score = 20
    else:                  zt_num_score = 0
    
    # 涨停占比加成
    density_bonus = clamp(zt_count / total_stocks * 200, 0, 10) if total_stocks > 0 else 0
    
    # 2. 连板强度得分 (0-30)
    max_h = max(ladder.keys()) if ladder else 0
    if zt_count > 0 and max_h >= 4:     streak_score = 30
    elif zt_count > 0 and max_h >= 3:   streak_score = 25
    elif zt_count > 0 and max_h >= 2:   streak_score = 15
    elif zt_count > 0:                  streak_score = 10
    else:                               streak_score = 0
    
    # 3. 炸板率惩罚 (0-20)
    break_score = 20  # 默认满分（全市场炸板率低），可根据实际炸板率调
    
    return clamp(zt_num_score + density_bonus + streak_score + break_score)
```

### 3.7 综合情绪合成

```python
def synthesize_sentiment(scores: dict[str, float]) -> dict:
    """
    五维度加权合成综合情绪指数。
    
    输入: {"fund_flow": 65.2, "price": 55.0, "breadth": 58.3, "volume": 48.1, "limit_up": 70.5}
    返回: {composite, dimension_scores, level, emoji, dimension_consensus}
    """
    weights = {
        "fund_flow": 0.25, "price": 0.20, "breadth": 0.20,
        "volume": 0.15, "limit_up": 0.20,
    }
    
    composite = sum(scores.get(k, 50) * w for k, w in weights.items())
    composite = clamp(round(composite, 1))
    
    # 情绪等级
    if composite >= 80:      level, emoji = "极度亢奋", "🔴"
    elif composite >= 60:    level, emoji = "偏暖", "🟠"
    elif composite >= 40:    level, emoji = "中性", "🟡"
    elif composite >= 20:    level, emoji = "偏冷", "🔵"
    else:                    level, emoji = "极度悲观", "🟢"
    
    # 维度共识度
    directions = []
    for k in weights:
        v = scores.get(k, 50)
        directions.append("warm" if v >= 60 else ("cold" if v <= 40 else "neutral"))
    warm_cnt = directions.count("warm")
    cold_cnt = directions.count("cold")
    consensus_cnt = max(warm_cnt, cold_cnt)
    
    if consensus_cnt >= 4:       consensus = "高"
    elif consensus_cnt >= 3:     consensus = "中"
    else:                        consensus = "低"
    
    return {
        "composite": composite,
        "dimension_scores": {k: round(scores.get(k, 50), 1) for k in weights},
        "level": level,
        "emoji": emoji,
        "dimension_consensus": consensus,
    }


def calc_concept_sentiment(concept_name: str, snapshot: dict,
                           concept_zt_map: dict, ladder: dict,
                           market_avg_pct: float) -> dict | None:
    """计算单个概念板块的完整情绪指数（5维度+综合）"""
    if concept_name not in snapshot:
        return None
    
    d = snapshot[concept_name]
    
    scores = {
        "fund_flow": calc_fund_flow_sentiment(d),
        "price": calc_price_momentum_sentiment(d, market_avg_pct),
        "breadth": calc_breadth_sentiment(d, concept_zt_map),
        "volume": calc_volume_sentiment(d),
        "limit_up": calc_limit_up_sentiment_for_concept(d, concept_zt_map, ladder),
    }
    
    result = synthesize_sentiment(scores)
    result["name"] = concept_name
    result["code"] = d.get("code", "")
    result["change_pct"] = d.get("change_pct", 0)
    result["main_net_yi"] = round((d.get("main_net", 0) or 0) / 1e8, 2)
    result["up_count"] = d.get("up_count", 0)
    result["down_count"] = d.get("down_count", 0)
    
    return result
```

---

## Layer 4: 行业与细分方向情绪聚合

```python
def aggregate_industry_sentiment(industry_key: str,
                                  concept_sentiments: dict[str, dict],
                                  mapping: dict) -> dict:
    """
    将行业下属所有概念板块的情绪指数加权聚合。
    
    mapping: 来自 industry-concept-mapping.py 的 INDUSTRY_SENTIMENT_MAP
    返回: {industry_label, composite, dimension_breakdown, sub_sectors, ...}
    """
    cfg = mapping.get(industry_key, {})
    if not cfg:
        return {"error": f"未知行业: {industry_key}"}
    
    # 收集此行业覆盖的概念板块情绪数据
    parent_names = cfg.get("parent_concepts", [])
    industry_concepts = [
        concept_sentiments[name] for name in parent_names
        if name in concept_sentiments
    ]
    
    if not industry_concepts:
        return {
            "industry_key": industry_key,
            "industry_label": cfg.get("label", industry_key),
            "composite": None,
            "error": "无有效概念板块数据",
        }
    
    # 等权平均聚合
    n = len(industry_concepts)
    composite = sum(c["composite"] for c in industry_concepts) / n
    
    # 维度分解
    dim_keys = ["fund_flow", "price", "breadth", "volume", "limit_up"]
    dim_breakdown = {}
    for k in dim_keys:
        dim_breakdown[k] = round(
            sum(c["dimension_scores"].get(k, 50) for c in industry_concepts) / n, 1
        )
    
    # 情绪等级
    if composite >= 80:      level, emoji = "极度亢奋", "🔴"
    elif composite >= 60:    level, emoji = "偏暖", "🟠"
    elif composite >= 40:    level, emoji = "中性", "🟡"
    elif composite >= 20:    level, emoji = "偏冷", "🔵"
    else:                    level, emoji = "极度悲观", "🟢"
    
    # 细分方向情绪
    sub_sectors = {}
    for sub_key, sub_cfg in cfg.get("sub_sectors", {}).items():
        sub_concept_names = sub_cfg.get("concepts", [])
        sub_data = [
            concept_sentiments[n] for n in sub_concept_names
            if n in concept_sentiments
        ]
        if sub_data:
            sub_composite = sum(c["composite"] for c in sub_data) / len(sub_data)
            sub_sectors[sub_key] = {
                "composite": round(sub_composite, 1),
                "concept_count": len(sub_data),
                "concepts": [c["name"] for c in sub_data],
            }
    
    # 排序取首尾
    sorted_concepts = sorted(industry_concepts, key=lambda x: x["composite"], reverse=True)
    
    return {
        "industry_key": industry_key,
        "industry_label": cfg.get("label", industry_key),
        "composite": round(composite, 1),
        "level": level,
        "emoji": emoji,
        "dimension_breakdown": dim_breakdown,
        "sub_sectors": sub_sectors,
        "concept_count": len(industry_concepts),
        "top_concepts": [
            {"name": c["name"], "composite": c["composite"]}
            for c in sorted_concepts[:3]
        ],
        "bottom_concepts": [
            {"name": c["name"], "composite": c["composite"]}
            for c in sorted_concepts[-3:][::-1]
        ],
    }


def aggregate_market_wide_sentiment(
    concept_sentiments: dict[str, dict],
    limit_up_data: dict,
    market_wide_names: list[str]) -> dict:
    """
    A 股整体情绪指数。
    从代表性概念板块（约20个核心板块）聚合全市场情绪。
    """
    market_concepts = [
        concept_sentiments[name] for name in market_wide_names
        if name in concept_sentiments
    ]
    
    if not market_concepts:
        return {"error": "无全市场概念板块数据"}
    
    n = len(market_concepts)
    composite = sum(c["composite"] for c in market_concepts) / n
    
    dim_keys = ["fund_flow", "price", "breadth", "volume", "limit_up"]
    dim_breakdown = {}
    for k in dim_keys:
        dim_breakdown[k] = round(
            sum(c["dimension_scores"].get(k, 50) for c in market_concepts) / n, 1
        )
    
    if composite >= 80:      level, emoji = "极度亢奋", "🔴"
    elif composite >= 60:    level, emoji = "偏暖", "🟠"
    elif composite >= 40:    level, emoji = "中性", "🟡"
    elif composite >= 20:    level, emoji = "偏冷", "🔵"
    else:                    level, emoji = "极度悲观", "🟢"
    
    return {
        "composite": round(composite, 1),
        "level": level,
        "emoji": emoji,
        "dimension_breakdown": dim_breakdown,
        "concept_count": n,
        "zt_count": limit_up_data.get("zt_count", 0),
        "dt_count": limit_up_data.get("dt_count", 0),
        "break_rate": limit_up_data.get("break_rate", 0),
        "max_height": limit_up_data.get("max_height", 0),
    }
```

---

## Layer 5: 情绪趋势追踪与信号检测

```python
def track_sentiment_trend(today_composite: float,
                          history: dict = None) -> dict:
    """
    情绪趋势追踪——对比历史数据。
    history: {"2026-07-08": {"composite": 55.0}, ...}
    """
    result = {
        "today": today_composite,
        "change_1d": None,
        "change_1w": None,
        "trend_direction": "首次运行",
        "signals": [],
    }
    
    if not history:
        result["signals"].append("无历史数据，趋势追踪从下次运行开始")
        return result
    
    sorted_dates = sorted(history.keys(), reverse=True)
    
    if len(sorted_dates) >= 1:
        yesterday = history.get(sorted_dates[0], {}).get("composite")
        if yesterday is not None:
            result["change_1d"] = round(today_composite - yesterday, 1)
    
    if len(sorted_dates) >= 5:
        week_ago = history.get(sorted_dates[4], {}).get("composite")
        if week_ago is not None:
            result["change_1w"] = round(today_composite - week_ago, 1)
    elif len(sorted_dates) >= 2:
        week_ago = history.get(sorted_dates[-1], {}).get("composite")
        if week_ago is not None:
            result["change_1w"] = round(today_composite - week_ago, 1)
    
    chg = result["change_1d"]
    if chg is not None:
        if chg > 5:          result["trend_direction"] = "☀️ 大幅升温"
        elif chg > 1:        result["trend_direction"] = "🌤️ 温和升温"
        elif chg > -1:       result["trend_direction"] = "➖ 稳定"
        elif chg > -5:       result["trend_direction"] = "🌧️ 温和降温"
        else:                result["trend_direction"] = "⛈️ 大幅降温"
    
    return result


def detect_sentiment_signals(industry_sentiments: dict[str, dict]) -> list[dict]:
    """检测市场情绪信号"""
    signals = []
    industries = {
        k: v for k, v in industry_sentiments.items()
        if "error" not in v and v.get("composite") is not None
    }
    if not industries:
        return signals
    
    composites = {k: v["composite"] for k, v in industries.items()}
    
    # 全面亢奋
    hot_count = sum(1 for c in composites.values() if c >= 80)
    if hot_count >= len(composites) * 0.5:
        signals.append({
            "signal_type": "🔴 全面亢奋", "severity": "高",
            "affected": f"{hot_count}/{len(composites)} 个行业≥80",
            "description": "多数行业情绪极度亢奋，短线过热风险显著",
        })
    elif hot_count >= 1:
        hot_names = [k for k, c in composites.items() if c >= 80]
        signals.append({
            "signal_type": "🟠 局部亢奋", "severity": "中",
            "affected": ", ".join(hot_names),
            "description": f"部分行业情绪过热({hot_count}个)，关注分化",
        })
    
    # 全面悲观
    cold_count = sum(1 for c in composites.values() if c <= 20)
    if cold_count >= len(composites) * 0.5:
        signals.append({
            "signal_type": "🟢 全面悲观", "severity": "高",
            "affected": f"{cold_count}/{len(composites)} 个行业≤20",
            "description": "多数行业情绪极度悲观，可能是左侧布局机会",
        })
    
    # 极端分化
    if len(composites) >= 3:
        top_val = max(composites.values())
        bot_val = min(composites.values())
        spread = top_val - bot_val
        if spread > 40:
            top_name = max(composites, key=composites.get)
            bot_name = min(composites, key=composites.get)
            signals.append({
                "signal_type": "⚠️ 极端分化", "severity": "中",
                "affected": f"{top_name}({top_val}) vs {bot_name}({bot_val})",
                "description": f"行业情绪剪刀差 {spread:.0f} 点，结构性行情极致演绎",
            })
    
    # 情绪共振
    warm_count = sum(1 for c in composites.values() if c >= 60)
    if warm_count >= len(composites) * 0.7:
        signals.append({
            "signal_type": "🔥 情绪共振偏暖", "severity": "低",
            "affected": f"{warm_count}/{len(composites)} 行业偏暖",
            "description": "多数行业情绪偏暖，市场合力向上",
        })
    
    return signals
```

---

## Layer 6: 综合报告生成

### 6.1 主流程

```python
def generate_sentiment_report(output_dir: str = None) -> dict:
    """
    一键生成行业情绪全景报告。
    
    流程:
    1. 初始化 BK 码 → 2. 全量概念板块快照 → 3. 涨停情绪 →
    4. 同花顺热榜 → 5. 逐个概念板块计算情绪 →
    6. 聚合行业+细分方向 → 7. 信号检测 → 输出报告
    """
    # 内联映射表（独立运行时无需 import）
    mapping, market_wide_names = _load_mapping()
    
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "market_wide": {},
        "industries": {},
        "signals": [],
    }
    
    print("[1/7] 初始化概念板块 BK 码...")
    init_bk_codes()
    
    print("[2/7] 拉取全市场概念板块数据...")
    snapshot = fetch_all_concept_snapshot()
    if not snapshot:
        print("[ERROR] 数据拉取失败，无法生成报告")
        return report
    market_avg_pct = calc_market_avg_change(snapshot)
    
    print("[3/7] 拉取涨停池情绪数据...")
    limit_up_data = fetch_limit_up_sentiment()
    concept_zt_map = limit_up_data.get("concept_zt_map", {})
    ladder = limit_up_data.get("ladder", {})
    
    print("[4/7] 拉取同花顺热榜...")
    ths_data = fetch_ths_hot_sentiment()
    
    print("[5/7] 计算各概念板块情绪指数...")
    all_concept_names = set()
    for cfg in mapping.values():
        all_concept_names.update(cfg.get("parent_concepts", []))
        for sub_cfg in cfg.get("sub_sectors", {}).values():
            all_concept_names.update(sub_cfg.get("concepts", []))
    
    concept_sentiments = {}
    for name in all_concept_names:
        result = calc_concept_sentiment(
            name, snapshot, concept_zt_map, ladder, market_avg_pct
        )
        if result:
            concept_sentiments[name] = result
    
    print(f"  有效概念板块: {len(concept_sentiments)}/{len(all_concept_names)}")
    
    print("[6/7] 聚合行业与细分方向情绪...")
    industry_sentiments = {}
    for industry_key in mapping:
        ind_result = aggregate_industry_sentiment(
            industry_key, concept_sentiments, mapping
        )
        industry_sentiments[industry_key] = ind_result
    
    market_wide = aggregate_market_wide_sentiment(
        concept_sentiments, limit_up_data, market_wide_names
    )
    report["market_wide"] = market_wide
    report["industries"] = industry_sentiments
    
    print("[7/7] 检测情绪信号...")
    report["signals"] = detect_sentiment_signals(industry_sentiments)
    
    report["meta"] = {
        "concept_sectors_total": len(snapshot),
        "calculated_concepts": len(concept_sentiments),
        "zt_count": limit_up_data.get("zt_count", 0),
        "break_rate": limit_up_data.get("break_rate", 0),
        "max_height": limit_up_data.get("max_height", 0),
        "ths_hot_stocks": len(ths_data.get("hot_stocks", [])),
    }
    
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, "report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"  JSON 已保存: {json_path}")
        
        md_path = os.path.join(output_dir, "report.md")
        _save_sentiment_markdown(report, md_path)
        print(f"  Markdown 已保存: {md_path}")
    
    return report


def _load_mapping() -> tuple[dict, list[str]]:
    """加载映射表（优先从文件导入，失败则内联）"""
    try:
        from industry_concept_mapping import (
            INDUSTRY_SENTIMENT_MAP, MARKET_WIDE_CONCEPTS
        )
        return INDUSTRY_SENTIMENT_MAP, MARKET_WIDE_CONCEPTS
    except ImportError:
        # 独立运行时内联定义（精简版核心映射）
        return _inline_mapping(), _inline_market_wide()


def _inline_mapping() -> dict:
    """内联核心映射（精简版，完整版见 references/industry-concept-mapping.py）"""
    return {
        "半导体": {
            "label": "半导体",
            "parent_concepts": [
                "半导体概念", "芯片概念", "存储芯片", "先进封装",
                "光刻机(胶)", "第三代半导体", "IGBT概念", "汽车芯片",
            ],
            "sub_sectors": {
                "半导体设备": {"concepts": ["光刻机(胶)", "半导体概念", "中芯概念"]},
                "半导体材料": {"concepts": ["光刻机(胶)", "光刻胶", "电子化学品", "第三代半导体"]},
                "存储芯片": {"concepts": ["存储芯片", "HBM"]},
                "CPU/算力芯片": {"concepts": ["算力概念", "AI芯片", "半导体概念"]},
                "先进封装": {"concepts": ["先进封装", "Chiplet概念"]},
                "通信芯片": {"concepts": ["5G概念", "光通信", "CPO概念", "芯片概念"]},
            },
        },
        "AI与算力": {
            "label": "AI与算力",
            "parent_concepts": [
                "人工智能", "算力概念", "CPO概念", "ChatGPT概念",
                "多模态AI", "AIGC概念", "机器人概念", "人形机器人",
            ],
            "sub_sectors": {
                "算力基础设施": {"concepts": ["算力概念", "液冷概念", "CPO概念", "东数西算"]},
                "AI应用": {"concepts": ["ChatGPT概念", "多模态AI", "AIGC概念", "Sora概念"]},
                "机器人": {"concepts": ["机器人概念", "人形机器人", "机器视觉"]},
            },
        },
        "新能源": {
            "label": "新能源",
            "parent_concepts": [
                "新能源", "光伏", "锂电池", "储能",
                "风电", "氢能源", "固态电池", "钠电池",
            ],
            "sub_sectors": {
                "光伏": {"concepts": ["光伏", "HIT电池", "钙钛矿电池", "TOPCon电池"]},
                "储能": {"concepts": ["储能", "虚拟电厂", "固态电池"]},
                "锂电": {"concepts": ["锂电池", "钠电池", "动力电池回收"]},
                "风电": {"concepts": ["风电", "海上风电"]},
            },
        },
        "消费": {
            "label": "消费",
            "parent_concepts": [
                "酿酒概念", "食品饮料", "新零售",
                "预制菜概念", "跨境电商", "免税概念",
            ],
            "sub_sectors": {
                "白酒": {"concepts": ["酿酒概念", "白酒"]},
                "食品": {"concepts": ["食品饮料", "预制菜概念"]},
                "零售": {"concepts": ["新零售", "免税概念", "跨境电商"]},
            },
        },
        "医药": {
            "label": "医药",
            "parent_concepts": [
                "医药", "创新药", "医疗器械概念",
                "中药概念", "生物制药", "CXO概念",
            ],
            "sub_sectors": {
                "创新药": {"concepts": ["创新药", "生物制药", "CXO概念"]},
                "医疗器械": {"concepts": ["医疗器械概念"]},
                "中药": {"concepts": ["中药概念"]},
            },
        },
        "军工": {
            "label": "军工",
            "parent_concepts": [
                "军工", "军民融合", "大飞机",
                "商业航天", "航母概念", "北斗导航",
            ],
            "sub_sectors": {
                "航空航天": {"concepts": ["大飞机", "商业航天", "航母概念"]},
                "军工电子": {"concepts": ["军工", "军民融合", "北斗导航"]},
            },
        },
        "金融": {
            "label": "金融",
            "parent_concepts": ["券商概念", "互联金融", "银行", "保险"],
            "sub_sectors": {
                "券商": {"concepts": ["券商概念"]},
                "银行": {"concepts": ["银行"]},
                "保险": {"concepts": ["保险"]},
            },
        },
        "汽车": {
            "label": "汽车",
            "parent_concepts": [
                "新能源车", "无人驾驶", "汽车零部件", "智能汽车",
            ],
            "sub_sectors": {
                "整车": {"concepts": ["新能源车", "智能汽车"]},
                "零部件": {"concepts": ["汽车零部件"]},
                "智能驾驶": {"concepts": ["无人驾驶", "激光雷达"]},
            },
        },
    }


def _inline_market_wide() -> list[str]:
    return [
        "上证50", "沪深300", "中证500", "中证1000",
        "半导体概念", "芯片概念", "人工智能", "新能源",
        "券商概念", "酿酒概念", "医药", "军工",
        "5G概念", "光伏", "锂电池", "储能",
        "机器人概念", "算力概念", "新能源车", "银行",
    ]


def _inline_get_all_concept_names() -> list[str]:
    """收集映射表中所有概念板块名称（去重）"""
    mapping = _inline_mapping()
    names = set(_inline_market_wide())
    for cfg in mapping.values():
        names.update(cfg.get("parent_concepts", []))
        for sub_cfg in cfg.get("sub_sectors", {}).values():
            names.update(sub_cfg.get("concepts", []))
    return sorted(names)
```

### 6.2 Console 打印

```python
def print_sentiment_report(report: dict):
    """打印情绪全景报告到控制台"""
    market = report.get("market_wide", {})
    industries = report.get("industries", {})
    signals = report.get("signals", [])
    meta = report.get("meta", {})
    
    print()
    print("=" * 80)
    print("  📊 A股行业情绪指数全景报告")
    print(f"  生成时间: {report.get('generated_at', '')}")
    print("=" * 80)
    
    # ━━━ Part 1: A 股整体情绪 ━━━
    print()
    print("━" * 60)
    print("  🏛️ Part 1: A 股整体情绪指数")
    print("━" * 60)
    if market.get("error"):
        print(f"  ⚠️ {market['error']}")
    else:
        print(f"  综合情绪: {market['composite']} / 100  → {market['emoji']} {market['level']}")
        print(f"  全市场涨停: {market.get('zt_count', '?')} 只  |  "
              f"炸板率: {market.get('break_rate', '?')}%  |  "
              f"最高: {market.get('max_height', '?')} 连板")
        print()
        _print_dimension_bars(market.get("dimension_breakdown", {}))
    
    # ━━━ Part 2: 行业情绪排名 ━━━
    print()
    print("━" * 60)
    print("  🔥 Part 2: 行业情绪排名")
    print("━" * 60)
    
    sorted_inds = sorted(
        [(k, v) for k, v in industries.items()
         if "error" not in v and v.get("composite") is not None],
        key=lambda x: x[1]["composite"], reverse=True
    )
    
    print(f"  {'排名':<4s} {'行业':<12s} {'综合情绪':>8s}  {'等级':<12s}  {'概念数':>6s}")
    print(f"  {'─' * 55}")
    for i, (key, ind) in enumerate(sorted_inds):
        comp = ind["composite"]
        bar = _sentiment_bar(comp, width=16)
        print(f"  {i+1:<4d} {ind['industry_label']:<12s} "
              f"{comp:>6.1f} {bar} {ind['emoji']} {ind['level']:<8s} "
              f"{ind['concept_count']:>4d}个")
    
    # ━━━ Part 3: 重点行业细分方向 ━━━
    print()
    print("━" * 60)
    print("  🎯 Part 3: 重点行业细分方向分析")
    print("━" * 60)
    
    for key, ind in sorted_inds[:2]:
        print(f"\n  【{ind['emoji']} {ind['industry_label']}】综合: {ind['composite']} | "
              f"覆盖 {ind['concept_count']} 个概念板块")
        
        sub_sectors = ind.get("sub_sectors", {})
        if sub_sectors:
            sorted_subs = sorted(sub_sectors.items(),
                                key=lambda x: x[1]["composite"], reverse=True)
            print(f"  细分方向:")
            for sub_key, sub_data in sorted_subs:
                sub_bar = _sentiment_bar(sub_data["composite"], width=14)
                print(f"    {sub_key:<14s} {sub_data['composite']:>5.1f} {sub_bar}")
        
        top_c = ind.get("top_concepts", [])
        bot_c = ind.get("bottom_concepts", [])
        if top_c:
            print(f"  🔥 最热: {', '.join(f'{c['name']}({c['composite']:.0f})' for c in top_c)}")
        if bot_c:
            print(f"  💧 最冷: {', '.join(f'{c['name']}({c['composite']:.0f})' for c in bot_c)}")
    
    # ━━━ Part 4: 情绪信号 ━━━
    print()
    print("━" * 60)
    print("  🚨 Part 4: 情绪信号与风险提示")
    print("━" * 60)
    if signals:
        for sig in signals:
            print(f"  {sig['signal_type']} [{sig['severity']}]: {sig['description']}")
            print(f"    影响: {sig['affected']}")
    else:
        print("  ✅ 未检测到显著情绪信号")
    
    # ━━━ Footer ━━━
    print()
    print("=" * 80)
    print("  ⚠️ 研究声明:")
    print("  1. 情绪指数基于公开API数据多维合成，分值区间为0-100（越高越积极）")
    print("  2. 数据源: 东财push2 clist(概念板块) + push2ex(涨停池) + 同花顺热榜")
    print("  3. 权重: 资金面25% + 价格面20% + 宽度面20% + 涨停面20% + 量能面15%")
    print("  4. ≥80极度亢奋(风险信号) | ≤20极度悲观(机会信号)")
    print("  5. 情绪指数仅供参考，不构成投资建议")
    print("=" * 80)


def _sentiment_bar(score: float, width: int = 16) -> str:
    """生成情绪条形图"""
    filled = int(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _print_dimension_bars(dims: dict):
    """打印五维度条形图"""
    labels = {
        "fund_flow": "💰 资金面", "price": "📈 价格面",
        "breadth": "📊 宽度面", "volume": "📐 量能面",
        "limit_up": "🔥 涨停面",
    }
    for key, label in labels.items():
        score = dims.get(key, 50)
        bar = _sentiment_bar(score, width=20)
        print(f"    {label:<10s} {bar} {score:.0f}")


def _save_sentiment_markdown(report: dict, filepath: str):
    """保存情绪报告为 Markdown 文件"""
    market = report.get("market_wide", {})
    industries = report.get("industries", {})
    signals = report.get("signals", [])
    meta = report.get("meta", {})
    
    lines = []
    lines.append("# A股行业情绪指数全景报告\n\n")
    lines.append(f"**生成时间**: {report.get('generated_at', '')}  \n")
    lines.append(f"**数据覆盖**: {meta.get('calculated_concepts', '?')} 个概念板块\n\n")
    lines.append("---\n\n")
    
    # 整体情绪
    lines.append("## 一、A股整体情绪\n\n")
    if market.get("error"):
        lines.append(f"> ⚠️ {market['error']}\n\n")
    else:
        lines.append(f"- **综合情绪**: {market['composite']}/100 → {market['emoji']} {market['level']}\n")
        lines.append(f"- **涨停总数**: {market.get('zt_count', '?')} 只\n")
        lines.append(f"- **炸板率**: {market.get('break_rate', '?')}%\n")
        lines.append(f"- **最高连板**: {market.get('max_height', '?')} 板\n\n")
        lines.append("**五维度分解**:\n\n")
        lines.append("| 维度 | 得分 |\n")
        lines.append("|------|------|\n")
        for k, label in [("fund_flow","💰 资金面"), ("price","📈 价格面"),
                          ("breadth","📊 宽度面"), ("volume","📐 量能面"),
                          ("limit_up","🔥 涨停面")]:
            lines.append(f"| {label} | {market.get('dimension_breakdown', {}).get(k, '?')} |\n")
    
    # 行业排名
    lines.append("\n## 二、行业情绪排名\n\n")
    sorted_inds = sorted(
        [(k, v) for k, v in industries.items()
         if "error" not in v and v.get("composite") is not None],
        key=lambda x: x[1]["composite"], reverse=True
    )
    
    lines.append("| 排名 | 行业 | 综合情绪 | 等级 | 覆盖概念数 |\n")
    lines.append("|------|------|----------|------|------------|\n")
    for i, (key, ind) in enumerate(sorted_inds):
        lines.append(f"| {i+1} | {ind['industry_label']} | "
                     f"{ind['composite']} | {ind['emoji']} {ind['level']} | "
                     f"{ind['concept_count']} |\n")
    
    # 重点细分
    lines.append("\n## 三、重点行业细分方向\n\n")
    for key, ind in sorted_inds[:3]:
        lines.append(f"### {ind['emoji']} {ind['industry_label']} (综合: {ind['composite']})\n\n")
        sub_sectors = ind.get("sub_sectors", {})
        if sub_sectors:
            lines.append("| 细分方向 | 情绪 | 覆盖概念 |\n")
            lines.append("|----------|------|----------|\n")
            sorted_subs = sorted(sub_sectors.items(),
                                key=lambda x: x[1]["composite"], reverse=True)
            for sub_key, sub_data in sorted_subs:
                concepts_str = "、".join(sub_data.get("concepts", [])[:3])
                lines.append(f"| {sub_key} | {sub_data['composite']} | {concepts_str} |\n")
        
        dims = ind.get("dimension_breakdown", {})
        if dims:
            lines.append(f"\n**五维度**: "
                        f"资金{dims.get('fund_flow','?')} / "
                        f"价格{dims.get('price','?')} / "
                        f"宽度{dims.get('breadth','?')} / "
                        f"量能{dims.get('volume','?')} / "
                        f"涨停{dims.get('limit_up','?')}\n\n")
    
    # 信号
    lines.append("\n## 四、情绪信号\n\n")
    if signals:
        for sig in signals:
            lines.append(f"- **{sig['signal_type']}** [{sig['severity']}]: {sig['description']}\n")
            lines.append(f"  - 影响范围: {sig['affected']}\n")
    else:
        lines.append("✅ 未检测到显著情绪信号\n")
    
    lines.append("\n---\n\n")
    lines.append("## 研究声明\n\n")
    lines.append("1. 情绪指数基于公开API数据多维合成，分值区间为0-100\n")
    lines.append("2. 数据源: 东财push2 clist(概念板块) + push2ex(涨停池) + 同花顺热榜\n")
    lines.append("3. 权重: 资金面25% + 价格面20% + 宽度面20% + 涨停面20% + 量能面15%\n")
    lines.append("4. ≥80极度亢奋(风险信号) | ≤20极度悲观(机会信号)\n")
    lines.append("5. 情绪指数仅供参考，不构成投资建议\n")
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("".join(lines))
```

---

## 常用调用组合

| 场景 | 调用链 |
|------|--------|
| 全市场情绪快览 | `generate_sentiment_report()` → `print_sentiment_report()` |
| 只看半导体细分方向 | `aggregate_industry_sentiment("半导体", concept_sentiments, mapping)` |
| 单概念板块深度分析 | `calc_concept_sentiment("存储芯片", snapshot, ...)` |
| 情绪趋势追踪 | `track_sentiment_trend(today_composite, history)` |
| 信号检测 | `detect_sentiment_signals(industry_sentiments)` |

## 输出目录

分析报告统一输出到 `src/行业情绪/` 下：

```bash
mkdir -p src/行业情绪/$(date +%Y-%m-%d)-行业情绪扫描/
```

目录结构：
```
src/行业情绪/
├── _index.md
└── YYYY-MM-DD-行业情绪扫描/
    ├── report.md          # Markdown 报告
    └── report.json        # 原始数据（供历史回溯和趋势对比）
```

## 情绪指数解读原则

| 现象 | 含义 | 置信度 |
|------|------|--------|
| ≥80 极度亢奋 + 多个行业 | 短期过热，回调风险高 | 高 |
| ≤20 极度悲观 + 多个行业 | 极端悲观，可能是左侧机会 | 中 |
| 情绪分日变化 >10 点 | 情绪剧烈波动，关注触发原因 | 中 |
| 行业间情绪剪刀差 >40 点 | 极端结构性行情 | 高 |
| 情绪 + 资金流 + 涨停 三维共振 | 趋势确认 | 高 |
| 情绪高但 ETF 资金流出 | 可能虚高，游资主导 | 中 |

## 风险声明

- 情绪指数基于公开数据多维合成，各维度阈值和权重为经验设定，需要持续校准
- 涨停池概念板块映射使用东财的行业分类（hybk 字段），精度有限
- BK 码可能随东财调整而变化，建议重要分析前执行 `init_bk_codes(force_refresh=True)`
- 情绪指数反映的是市场短期温度，不直接等于涨跌方向
- 所有数据仅供参考，不构成投资建议
