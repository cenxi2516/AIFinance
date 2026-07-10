#!/usr/bin/env python3
"""
A股行业情绪指数全景报告 V1.1 — 混合数据源版
==============================================
五维度: 资金面25% + 价格面20% + 宽度面20% + 涨停面20% + 量能面15%
数据源: push2ex涨停池 + 同花顺热榜 + (push2被封时用热榜+涨停数据推导)
"""
import requests, json, math, os, sys, time, random
from datetime import datetime
from collections import Counter, defaultdict

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
PUSH2EX = "https://push2ex.eastmoney.com/getTopicZTPool"
ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"

# ============================================================
# 工具函数
# ============================================================
def sigmoid_score(x, center=0, scale=1.0, out_min=0, out_max=100):
    try:
        return out_min + (out_max - out_min) / (1 + math.exp(-(x - center) / scale))
    except OverflowError:
        return out_max if x > center else out_min

def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))

def sentiment_bar(score, width=16):
    filled = int(score / 100 * width)
    return "█" * filled + "░" * (width - filled)

# ============================================================
# 行业→概念板块映射
# ============================================================
INDUSTRY_MAPPING = {
    "半导体": {
        "label": "半导体",
        "concepts": ["半导体", "芯片概念", "存储芯片", "先进封装", "光刻机(胶)", "第三代半导体", "IGBT概念", "汽车芯片", "半导体概念", "中芯概念", "HBM", "AI芯片", "Chiplet概念", "光刻胶", "电子化学品"],
        "sub_sectors": {
            "半导体设备": ["光刻机(胶)", "半导体", "半导体概念", "中芯概念"],
            "半导体材料": ["光刻机(胶)", "光刻胶", "电子化学品", "第三代半导体"],
            "存储芯片": ["存储芯片", "HBM"],
            "CPU/算力芯片": ["AI芯片", "半导体概念", "芯片概念"],
            "先进封装": ["先进封装", "Chiplet概念"],
            "通信芯片": ["5G概念", "光通信", "CPO概念", "芯片概念"],
        },
    },
    "AI与算力": {
        "label": "AI与算力",
        "concepts": ["人工智能", "算力概念", "CPO概念", "ChatGPT概念", "多模态AI", "AIGC概念", "机器人概念", "人形机器人", "液冷概念", "东数西算", "Sora概念", "机器视觉"],
        "sub_sectors": {
            "算力基础设施": ["算力概念", "液冷概念", "CPO概念", "东数西算"],
            "AI应用": ["ChatGPT概念", "多模态AI", "AIGC概念", "Sora概念"],
            "机器人": ["机器人概念", "人形机器人", "机器视觉"],
        },
    },
    "新能源": {
        "label": "新能源",
        "concepts": ["新能源", "光伏", "锂电池", "储能", "风电", "氢能源", "固态电池", "钠电池", "HIT电池", "钙钛矿电池", "TOPCon电池", "虚拟电厂", "动力电池回收", "海上风电"],
        "sub_sectors": {
            "光伏": ["光伏", "HIT电池", "钙钛矿电池", "TOPCon电池"],
            "储能": ["储能", "虚拟电厂", "固态电池"],
            "锂电": ["锂电池", "钠电池", "动力电池回收"],
            "风电": ["风电", "海上风电"],
        },
    },
    "消费": {
        "label": "消费",
        "concepts": ["酿酒概念", "食品饮料", "新零售", "预制菜概念", "跨境电商", "免税概念", "白酒"],
        "sub_sectors": {
            "白酒": ["酿酒概念", "白酒"],
            "食品": ["食品饮料", "预制菜概念"],
            "零售": ["新零售", "免税概念", "跨境电商"],
        },
    },
    "医药": {
        "label": "医药",
        "concepts": ["医药", "创新药", "医疗器械概念", "中药概念", "生物制药", "CXO概念"],
        "sub_sectors": {
            "创新药": ["创新药", "生物制药", "CXO概念"],
            "医疗器械": ["医疗器械概念"],
            "中药": ["中药概念"],
        },
    },
    "军工": {
        "label": "军工",
        "concepts": ["军工", "军民融合", "大飞机", "商业航天", "航母概念", "北斗导航"],
        "sub_sectors": {
            "航空航天": ["大飞机", "商业航天", "航母概念"],
            "军工电子": ["军工", "军民融合", "北斗导航"],
        },
    },
    "金融": {
        "label": "金融",
        "concepts": ["券商概念", "互联金融", "银行", "保险"],
        "sub_sectors": {
            "券商": ["券商概念"],
            "银行": ["银行"],
            "保险": ["保险"],
        },
    },
    "汽车": {
        "label": "汽车",
        "concepts": ["新能源车", "无人驾驶", "汽车零部件", "智能汽车", "激光雷达"],
        "sub_sectors": {
            "整车": ["新能源车", "智能汽车"],
            "零部件": ["汽车零部件"],
            "智能驾驶": ["无人驾驶", "激光雷达"],
        },
    },
}

# 涨停池行业简称 → 映射到我们的概念板块名
ZT_INDUSTRY_TO_CONCEPT = {
    "半导体": ["半导体概念", "芯片概念", "半导体"],
    "元件": ["芯片概念", "半导体概念"],
    "光学光电": ["半导体概念", "芯片概念"],
    "其他电子": ["半导体概念"],
    "电子化学品": ["半导体概念", "光刻胶", "电子化学品"],
    "通用设备": ["机器人概念", "人工智能"],
    "专用设备": ["机器人概念", "半导体概念"],
    "自动化设": ["机器人概念", "人工智能"],
    "汽车零部": ["汽车零部件"],
    "汽车整车": ["新能源车", "智能汽车"],
    "塑料": ["新能源"],
    "物流": ["跨境电商", "新零售"],
    "光伏设备": ["光伏"],
    "电池": ["锂电池", "固态电池"],
    "电网设备": ["储能", "虚拟电厂"],
    "风电设备": ["风电", "海上风电"],
    "军工装备": ["军工", "军民融合"],
    "航天航空": ["大飞机", "商业航天"],
    "通信设备": ["5G概念", "CPO概念", "光通信"],
    "计算机设": ["人工智能", "算力概念"],
    "软件开发": ["人工智能", "多模态AI", "AIGC概念"],
    "互联网服": ["ChatGPT概念", "人工智能"],
    "食品饮料": ["食品饮料", "酿酒概念"],
    "酿酒": ["酿酒概念", "白酒"],
    "医药商业": ["医药"],
    "化学制药": ["创新药", "医药"],
    "医疗器械": ["医疗器械概念"],
    "中药": ["中药概念"],
    "券商": ["券商概念"],
    "银行": ["银行"],
    "保险": ["保险"],
    "房地产": [],
    "钢铁": [],
    "煤炭": [],
    "电力": [],
    "水泥": [],
    "建材": [],
    "工程机械": [],
    "港口航运": [],
    "铁路公路": [],
}

# ============================================================
# 数据采集
# ============================================================
def fetch_limit_up_full():
    """拉取全量涨停池"""
    zt_list = []
    concept_zt_map = Counter()
    try:
        for page in range(0, 3):
            params = {
                "ut": ZTB_UT, "dpt": "wz.ztzt",
                "Pageindex": page, "pagesize": 200,
                "sort": "fbt:asc", "date": datetime.now().strftime("%Y%m%d"),
            }
            r = requests.get(PUSH2EX, params=params,
                headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}, timeout=15)
            pool = (r.json().get("data") or {}).get("pool") or []
            if not pool:
                break
            for p in pool:
                ind = p.get("hybk", "")
                zt_list.append({
                    "code": p.get("c",""), "name": p.get("n",""),
                    "limit_days": p.get("lbc", 0),
                    "break_times": p.get("zbc", 0),
                    "industry": ind,
                    "zt_stat": f'{(p.get("zttj") or {}).get("days","?")}天{(p.get("zttj") or {}).get("ct","?")}板',
                })
                if ind:
                    # 映射到全名概念（避免原始简称污染聚合）
                    mapped = ZT_INDUSTRY_TO_CONCEPT.get(ind, [ind])
                    for mc in mapped:
                        concept_zt_map[mc] += 1
            if len(pool) < 200:
                break
            time.sleep(1.5)
    except Exception as e:
        print(f"[WARN] 涨停池拉取异常: {e}")

    ladder = Counter(s["limit_days"] for s in zt_list)
    max_height = max(ladder.keys()) if ladder else 0
    zb_related = sum(1 for s in zt_list if s.get("break_times", 0) > 0)
    zt_count = len(zt_list)
    break_rate = round(zb_related / zt_count * 100, 1) if zt_count else 0

    # 跌停池（独立端点 getTopicDTPool）
    dt_count = 0
    try:
        r = requests.get("https://push2ex.eastmoney.com/getTopicDTPool",
            params={"ut": ZTB_UT, "dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 200,
                    "sort": "fund:asc", "date": datetime.now().strftime("%Y%m%d")},
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}, timeout=10)
        dt_count = len((r.json().get("data") or {}).get("pool") or [])
    except Exception:
        pass

    print(f"[涨停池] 涨停{zt_count}只 跌停{dt_count}只 炸板率{break_rate}% 最高{max_height}连板")
    return {
        "zt_list": zt_list, "zt_count": zt_count, "dt_count": dt_count,
        "break_rate": break_rate, "max_height": max_height,
        "ladder": dict(sorted(ladder.items())),
        "concept_zt_map": dict(concept_zt_map),
    }


def fetch_ths_hot_list():
    """拉取同花顺热榜"""
    try:
        r = requests.get("https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock",
            params={"stock_type": "a", "type": "day", "list_type": "normal"},
            headers={"User-Agent": UA}, timeout=10)
        data = r.json().get("data", {})
        stock_list = data.get("stock_list", []) if isinstance(data, dict) else []

        hot_stocks = []
        concept_heat = Counter()
        for it in stock_list:
            if not isinstance(it, dict):
                continue
            tag = it.get("tag") or {}
            concepts = []
            if isinstance(tag, dict):
                concept_tags = tag.get("concept_tag", []) or []
                for ct in concept_tags:
                    cn = ct.get("name", "") if isinstance(ct, dict) else str(ct)
                    if cn:
                        concepts.append(cn)
            heat_val = float(it.get("rate", 0))
            for c in concepts:
                concept_heat[c] += heat_val
            hot_stocks.append({
                "code": it.get("code",""), "name": it.get("name",""),
                "heat": heat_val, "concepts": concepts,
                "pct": it.get("rise_and_fall", 0),
                "rank_chg": it.get("hot_rank_chg", 0),
            })
        print(f"[同花顺热榜] {len(hot_stocks)} 只热门股, {len(concept_heat)} 个概念")
        return {"hot_stocks": hot_stocks, "concept_heat": dict(concept_heat)}
    except Exception as e:
        print(f"[WARN] 同花顺热榜失败: {e}")
        return {"hot_stocks": [], "concept_heat": {}}


# ============================================================
# 情绪计算（适配数据可用性）
# ============================================================
def calc_industry_sentiment_v2(industry_key, cfg, zt_data, ths_data):
    """
    V2 情绪计算: 基于涨停+热榜数据推导行业情绪。
    当 push2 概念板块行情不可用时使用。
    """
    concepts = cfg.get("concepts", [])
    concept_zt_map = zt_data.get("concept_zt_map", {})
    ladder = zt_data.get("ladder", {})
    concept_heat = ths_data.get("concept_heat", {})
    zt_count_total = zt_data.get("zt_count", 1)
    max_height = zt_data.get("max_height", 0)
    break_rate = zt_data.get("break_rate", 30)

    # 1. 涨停面情绪 (40% 权重，因为缺乏资金数据)
    zt_in_industry = sum(concept_zt_map.get(c, 0) for c in concepts)
    zt_ratio = zt_in_industry / max(zt_count_total, 1)

    # 涨停密度得分 (0-60)
    if zt_in_industry >= 10:    zt_num_score = 60
    elif zt_in_industry >= 7:   zt_num_score = 55
    elif zt_in_industry >= 5:   zt_num_score = 45
    elif zt_in_industry >= 3:   zt_num_score = 35
    elif zt_in_industry >= 1:   zt_num_score = 25
    else:                       zt_num_score = 10

    # 涨停占比得分 (0-20)
    density_score = clamp(zt_ratio * 100, 0, 20)

    # 连板高度得分 (0-20)
    if zt_in_industry > 0 and max_height >= 5:   height_score = 20
    elif zt_in_industry > 0 and max_height >= 3: height_score = 15
    elif zt_in_industry > 0 and max_height >= 2: height_score = 10
    elif zt_in_industry > 0:                     height_score = 5
    else:                                        height_score = 0

    limit_up_score = clamp(zt_num_score + density_score + height_score)

    # 2. 热度面情绪 (40% 权重，基于同花顺热榜)
    heat_in_industry = sum(concept_heat.get(c, 0) for c in concepts)
    max_heat = max(concept_heat.values()) if concept_heat else 1
    heat_ratio = heat_in_industry / max_heat if max_heat > 0 else 0
    # 有涨停+高热度 → 高分；有热度无涨停 → 中分；无热度无涨停 → 低分
    if zt_in_industry > 0:
        heat_score = clamp(heat_ratio * 60 + 25)  # 涨停行业：热度加成
    else:
        heat_score = clamp(heat_ratio * 50 + 15)  # 非涨停行业：基础分偏低但不极端

    # 3. 情绪宽度面 (20% 权重，基于涨停分布广度)
    concepts_with_zt = sum(1 for c in concepts if concept_zt_map.get(c, 0) > 0)
    coverage_ratio = concepts_with_zt / max(len(concepts), 1)
    if zt_in_industry > 0:
        breadth_score = clamp(coverage_ratio * 50 + 35)
    else:
        breadth_score = 30  # 无涨停但有概念覆盖

    # 综合情绪
    composite = limit_up_score * 0.40 + heat_score * 0.40 + breadth_score * 0.20
    composite = clamp(round(composite, 1))

    # 情绪等级
    if composite >= 80:      level, emoji = "极度亢奋", "🔴"
    elif composite >= 60:    level, emoji = "偏暖", "🟠"
    elif composite >= 40:    level, emoji = "中性", "🟡"
    elif composite >= 20:    level, emoji = "偏冷", "🔵"
    else:                    level, emoji = "极度悲观", "🟢"

    # 细分方向
    sub_sectors = {}
    for sub_key, sub_cfg in cfg.get("sub_sectors", {}).items():
        sub_concepts = sub_cfg
        sub_zt = sum(concept_zt_map.get(c, 0) for c in sub_concepts)
        sub_heat = sum(concept_heat.get(c, 0) for c in sub_concepts)
        sub_zt_score = clamp(sub_zt / max(zt_count_total, 1) * 80)  # 涨停贡献(0-80)
        sub_heat_score = clamp(sub_heat / max(max_heat, 1) * 30)   # 热度贡献(0-30)
        sub_composite = clamp(sub_zt_score + sub_heat_score + 25)    # 基础25分
        sub_sectors[sub_key] = {
            "composite": round(sub_composite, 1),
            "zt_count": sub_zt,
            "concepts": sub_concepts[:3],
        }

    # 概念板块热度排名
    concept_scores = {}
    for c in concepts:
        c_zt = concept_zt_map.get(c, 0)
        c_heat = concept_heat.get(c, 0)
        c_score = clamp(
            c_zt / max(zt_count_total, 1) * 70 +
            c_heat / max(max_heat, 1) * 30 + 15  # 基础15分
        )
        concept_scores[c] = round(c_score, 1)

    sorted_concepts = sorted(concept_scores.items(), key=lambda x: x[1], reverse=True)

    return {
        "industry_key": industry_key,
        "industry_label": cfg.get("label", industry_key),
        "composite": composite,
        "level": level, "emoji": emoji,
        "dimension_breakdown": {
            "limit_up": round(limit_up_score, 1),
            "heat": round(heat_score, 1),
            "breadth": round(breadth_score, 1),
            "fund_flow": 50.0,  # 无数据，中性
            "price": 50.0,       # 无数据，中性
        },
        "sub_sectors": sub_sectors,
        "concept_count": len(concepts),
        "zt_in_industry": zt_in_industry,
        "heat_in_industry": round(heat_in_industry / 1e6, 1),
        "top_concepts": [
            {"name": name, "composite": score}
            for name, score in sorted_concepts[:3]
        ],
        "bottom_concepts": [
            {"name": name, "composite": score}
            for name, score in sorted_concepts[-3:][::-1]
        ],
    }


def calc_market_sentiment_v2(zt_data, ths_data):
    """全市场情绪综合"""
    zt_count = zt_data.get("zt_count", 0)
    dt_count = zt_data.get("dt_count", 0)
    break_rate = zt_data.get("break_rate", 30)
    max_height = zt_data.get("max_height", 0)

    # 涨停面得分 (涨停数映射)
    zt_score = sigmoid_score(zt_count, center=50, scale=30, out_max=100)

    # 市场宽度得分 (炸板率倒数，30%以内为健康，超过惩罚)
    profit_score = clamp(max(0, 100 - max(0, break_rate - 30) * 1.2))

    # 高度得分 (高标代表赚钱效应)
    height_score = clamp(max_height * 7 + 40)

    # 热度面 (热榜数据）
    hot_stocks = len(ths_data.get("hot_stocks", []))
    hot_score = sigmoid_score(hot_stocks, center=40, scale=30, out_max=100)

    composite = zt_score * 0.30 + profit_score * 0.25 + height_score * 0.25 + hot_score * 0.20
    composite = clamp(round(composite, 1))

    if composite >= 80:      level, emoji = "极度亢奋", "🔴"
    elif composite >= 60:    level, emoji = "偏暖", "🟠"
    elif composite >= 40:    level, emoji = "中性", "🟡"
    elif composite >= 20:    level, emoji = "偏冷", "🔵"
    else:                    level, emoji = "极度悲观", "🟢"

    return {
        "composite": composite, "level": level, "emoji": emoji,
        "dimension_breakdown": {
            "limit_up": round(zt_score, 1),
            "heat": round(profit_score, 1),
            "breadth": round(height_score, 1),
            "fund_flow": round(hot_score, 1),
            "price": 50.0,
        },
        "zt_count": zt_count, "dt_count": dt_count,
        "break_rate": break_rate, "max_height": max_height,
    }


def detect_signals(industry_sentiments):
    """检测市场信号"""
    signals = []
    industries = {
        k: v for k, v in industry_sentiments.items()
        if v.get("composite") is not None
    }
    if not industries:
        return signals

    composites = {k: v["composite"] for k, v in industries.items()}

    hot_count = sum(1 for c in composites.values() if c >= 80)
    if hot_count >= len(composites) * 0.5:
        signals.append({
            "signal_type": "🔴 全面亢奋", "severity": "高",
            "affected": f"{hot_count}/{len(composites)} 行业≥80",
            "description": "多数行业情绪极度亢奋，短线过热风险显著",
        })
    elif hot_count >= 1:
        hot_names = [k for k, c in composites.items() if c >= 80]
        signals.append({
            "signal_type": "🟠 局部亢奋", "severity": "中",
            "affected": ", ".join(hot_names),
            "description": f"部分行业情绪过热({hot_count}个)，关注分化",
        })

    cold_count = sum(1 for c in composites.values() if c <= 20)
    if cold_count >= len(composites) * 0.5:
        signals.append({
            "signal_type": "🟢 全面悲观", "severity": "高",
            "affected": f"{cold_count}/{len(composites)} 行业≤20",
            "description": "多数行业情绪极度悲观，可能是左侧布局机会",
        })

    if len(composites) >= 3:
        top_val = max(composites.values())
        bot_val = min(composites.values())
        spread = top_val - bot_val
        if spread > 40:
            top_name = max(composites, key=composites.get)
            bot_name = min(composites, key=composites.get)
            signals.append({
                "signal_type": "⚠️ 极端分化", "severity": "中",
                "affected": f"{top_name}({top_val:.0f}) vs {bot_name}({bot_val:.0f})",
                "description": f"行业情绪剪刀差 {spread:.0f} 点，结构性行情极致演绎",
            })

    warm_count = sum(1 for c in composites.values() if c >= 60)
    if warm_count >= len(composites) * 0.7:
        signals.append({
            "signal_type": "🔥 情绪共振偏暖", "severity": "低",
            "affected": f"{warm_count}/{len(composites)} 行业偏暖",
            "description": "多数行业情绪偏暖，市场合力向上",
        })

    return signals


# ============================================================
# 报告生成
# ============================================================
def generate_report(output_dir=None):
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "market_wide": {}, "industries": {}, "signals": [],
    }

    print("=" * 60)
    print("  📊 A股行业情绪指数全景报告 V1.1")
    print(f"  {report['generated_at']}")
    print("=" * 60)

    print("\n[1/4] 拉取涨停池数据...")
    zt_data = fetch_limit_up_full()
    report["zt_data"] = zt_data

    print("[2/4] 拉取同花顺热榜...")
    ths_data = fetch_ths_hot_list()

    print("[3/4] 计算行业情绪指数...")
    industry_sentiments = {}
    for key, cfg in INDUSTRY_MAPPING.items():
        result = calc_industry_sentiment_v2(key, cfg, zt_data, ths_data)
        industry_sentiments[key] = result

    market_wide = calc_market_sentiment_v2(zt_data, ths_data)
    report["market_wide"] = market_wide
    report["industries"] = industry_sentiments

    print("[4/4] 检测信号...",)
    report["signals"] = detect_signals(industry_sentiments)
    print(f"{len(report['signals'])} 个信号")

    report["meta"] = {
        "zt_count": zt_data.get("zt_count", 0),
        "dt_count": zt_data.get("dt_count", 0),
        "break_rate": zt_data.get("break_rate", 0),
        "max_height": zt_data.get("max_height", 0),
        "ths_hot_stocks": len(ths_data.get("hot_stocks", [])),
        "ladder": zt_data.get("ladder", {}),
        "data_note": "⚠️ push2概念板块行情API被封，情绪计算基于涨停池+热榜数据推导，资金面/价格面/量能面暂无法获取实盘数据",
    }

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        # Save JSON
        json_path = os.path.join(output_dir, "report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"  JSON → {json_path}")
        # Save MD
        md_path = os.path.join(output_dir, "report.md")
        save_markdown(report, md_path)
        print(f"  MD  → {md_path}")

    return report


# ============================================================
# 报告打印
# ============================================================
def print_report(report):
    market = report.get("market_wide", {})
    industries = report.get("industries", {})
    signals = report.get("signals", [])
    meta = report.get("meta", {})
    zt_data = report.get("zt_data", {})

    print()
    print("=" * 80)
    print("  📊 A股行业情绪指数全景报告")
    print(f"  生成时间: {report.get('generated_at', '')}")
    print("=" * 80)

    # ━━━ Part 1: 全市场情绪 ━━━
    print()
    print("━" * 60)
    print("  🏛️ Part 1: A 股整体情绪与打板温度")
    print("━" * 60)
    print(f"  综合情绪: {market['composite']} / 100  → {market['emoji']} {market['level']}")
    print(f"  涨停: {market.get('zt_count','?')} 只  |  跌停: {market.get('dt_count','?')} 只")
    print(f"  炸板率: {market.get('break_rate','?')}%  |  最高: {market.get('max_height','?')} 连板")

    ladder = meta.get("ladder", {})
    if ladder:
        ladder_str = " | ".join(f"{k}板:{v}家" for k, v in sorted(ladder.items()))
        print(f"  连板梯队: {ladder_str}")

    # 概念涨停排名
    concept_zt = zt_data.get("concept_zt_map", {})
    if concept_zt:
        top_concepts_zt = sorted(concept_zt.items(), key=lambda x: x[1], reverse=True)[:10]
        print(f"  涨停概念TOP10: {', '.join(f'{c}({n}只)' for c, n in top_concepts_zt)}")

    print()
    print(f"  五维度情绪:")
    dims = market.get("dimension_breakdown", {})
    for k, label in [("limit_up","🔥 涨停面"), ("heat","📱 热度面"),
                      ("breadth","📊 宽度面"), ("fund_flow","💰 资金面"),
                      ("price","📈 价格面")]:
        score = dims.get(k, 50)
        bar = sentiment_bar(score, width=20)
        print(f"    {label:<10s} {bar} {score:.0f}")
    print(f"  ⚠️ 注: 资金面/价格面因push2 API被封暂用中性值，情绪指数主要基于涨停+热榜")

    # ━━━ Part 2: 行业排名 ━━━
    print()
    print("━" * 60)
    print("  🔥 Part 2: 行业情绪排名")
    print("━" * 60)

    sorted_inds = sorted(
        [(k, v) for k, v in industries.items() if v.get("composite") is not None],
        key=lambda x: x[1]["composite"], reverse=True
    )

    print(f"  {'排名':<4s} {'行业':<10s} {'综合':>6s} {'':16s} {'等级':<12s} {'涨停':>4s}")
    print(f"  {'─' * 58}")
    for i, (key, ind) in enumerate(sorted_inds):
        comp = ind["composite"]
        bar = sentiment_bar(comp, width=16)
        zt_n = ind.get("zt_in_industry", 0)
        print(f"  {i+1:<4d} {ind['industry_label']:<10s} "
              f"{comp:>6.1f} {bar} {ind['emoji']} {ind['level']:<8s} "
              f"{zt_n:>4d}只")

    # ━━━ Part 3: 重点行业细分 ━━━
    print()
    print("━" * 60)
    print("  🎯 Part 3: 重点行业细分方向分析")
    print("━" * 60)

    for key, ind in sorted_inds[:3]:
        print(f"\n  【{ind['emoji']} {ind['industry_label']}】综合: {ind['composite']}")
        print(f"  涨停家数: {ind.get('zt_in_industry', 0)} 只 | "
              f"热榜热度: {ind.get('heat_in_industry', 0):.1f}M")

        sub_sectors = ind.get("sub_sectors", {})
        if sub_sectors:
            sorted_subs = sorted(sub_sectors.items(),
                                key=lambda x: x[1]["composite"], reverse=True)
            print(f"  细分方向:")
            for sub_key, sub_data in sorted_subs:
                sub_bar = sentiment_bar(sub_data["composite"], width=14)
                zt_sub = sub_data.get("zt_count", 0)
                print(f"    {sub_key:<14s} {sub_data['composite']:>5.1f} {sub_bar} ({zt_sub}只涨停)")

        top_c = ind.get("top_concepts", [])
        bot_c = ind.get("bottom_concepts", [])
        if top_c:
            print(f"  🔥 最热: {', '.join(f'{c['name']}({c['composite']:.0f})' for c in top_c)}")
        if bot_c:
            print(f"  💧 最冷: {', '.join(f'{c['name']}({c['composite']:.0f})' for c in bot_c)}")

    # ━━━ Part 4: 信号 ━━━
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
    print("  1. 情绪指数基于公开API数据合成，分值区间为0-100（越高越积极）")
    print("  2. 数据源: push2ex涨停池 + 同花顺热榜 (push2概念板块API当次被封)")
    print("  3. 实际权重: 涨停面40% + 热度面40% + 宽度面20%")
    print("  4. 今日资金面/价格面/量能面因API限制暂不可用")
    print("  5. 情绪指数仅供参考，不构成投资建议")
    print("=" * 80)
    print()


def save_markdown(report, filepath):
    market = report.get("market_wide", {})
    industries = report.get("industries", {})
    signals = report.get("signals", [])
    meta = report.get("meta", {})
    zt_data = report.get("zt_data", {})

    lines = []
    lines.append("# A股行业情绪指数全景报告\n\n")
    lines.append(f"**生成时间**: {report.get('generated_at', '')}  \n")
    lines.append(f"**数据说明**: push2概念板块API当次被封，情绪计算基于涨停池+同花顺热榜推导  \n\n")
    lines.append("---\n\n")

    lines.append("## 一、A股整体情绪\n\n")
    lines.append(f"- **综合情绪**: {market['composite']}/100 → {market['emoji']} {market['level']}\n")
    lines.append(f"- **涨停总数**: {market.get('zt_count','?')} 只\n")
    lines.append(f"- **跌停总数**: {market.get('dt_count','?')} 只\n")
    lines.append(f"- **炸板率**: {market.get('break_rate','?')}%\n")
    lines.append(f"- **最高连板**: {market.get('max_height','?')} 板\n\n")

    ladder = meta.get("ladder", {})
    if ladder:
        lines.append(f"**连板梯队**: {' | '.join(f'{k}板:{v}家' for k, v in sorted(ladder.items()))}\n\n")

    concept_zt = zt_data.get("concept_zt_map", {})
    if concept_zt:
        top = sorted(concept_zt.items(), key=lambda x: x[1], reverse=True)[:10]
        lines.append(f"**涨停概念TOP10**: {', '.join(f'{c}({n}只)' for c, n in top)}\n\n")

    lines.append("**五维度分解**:\n\n")
    lines.append("| 维度 | 得分 | 备注 |\n")
    lines.append("|------|------|------|\n")
    dims = market.get("dimension_breakdown", {})
    for k, label, note in [
        ("limit_up","🔥 涨停面","涨停池实盘"), ("heat","📱 热度面","同花顺热榜"),
        ("breadth","📊 宽度面","概念覆盖度"), ("fund_flow","💰 资金面","API被封-中性"),
        ("price","📈 价格面","API被封-中性")
    ]:
        lines.append(f"| {label} | {dims.get(k, '?')} | {note} |\n")

    lines.append("\n## 二、行业情绪排名\n\n")
    sorted_inds = sorted(
        [(k, v) for k, v in industries.items() if v.get("composite") is not None],
        key=lambda x: x[1]["composite"], reverse=True
    )
    lines.append("| 排名 | 行业 | 综合情绪 | 等级 | 涨停数 |\n")
    lines.append("|------|------|----------|------|--------|\n")
    for i, (key, ind) in enumerate(sorted_inds):
        lines.append(f"| {i+1} | {ind['industry_label']} | "
                     f"{ind['composite']} | {ind['emoji']} {ind['level']} | "
                     f"{ind.get('zt_in_industry', 0)} |\n")

    lines.append("\n## 三、重点行业细分方向\n\n")
    for key, ind in sorted_inds[:3]:
        lines.append(f"### {ind['emoji']} {ind['industry_label']} (综合: {ind['composite']})\n\n")
        lines.append(f"- 涨停家数: {ind.get('zt_in_industry', 0)} 只\n")
        lines.append(f"- 热榜热度: {ind.get('heat_in_industry', 0):.1f}M\n\n")

        sub_sectors = ind.get("sub_sectors", {})
        if sub_sectors:
            lines.append("| 细分方向 | 情绪 | 涨停数 |\n")
            lines.append("|----------|------|--------|\n")
            sorted_subs = sorted(sub_sectors.items(),
                                key=lambda x: x[1]["composite"], reverse=True)
            for sub_key, sub_data in sorted_subs:
                lines.append(f"| {sub_key} | {sub_data['composite']} | "
                            f"{sub_data.get('zt_count', 0)} |\n")

        top_c = ind.get("top_concepts", [])
        if top_c:
            concepts_str = ", ".join(f"{c['name']}({c['composite']:.0f})" for c in top_c)
            lines.append(f"\n🔥 最热概念: {concepts_str}\n")
        bot_c = ind.get("bottom_concepts", [])
        if bot_c:
            concepts_str = ", ".join(f"{c['name']}({c['composite']:.0f})" for c in bot_c)
            lines.append(f"💧 最冷概念: {concepts_str}\n")
        lines.append("\n")

    lines.append("\n## 四、情绪信号\n\n")
    if signals:
        for sig in signals:
            lines.append(f"- **{sig['signal_type']}** [{sig['severity']}]: {sig['description']}\n")
            lines.append(f"  - 影响范围: {sig['affected']}\n")
    else:
        lines.append("✅ 未检测到显著情绪信号\n")

    lines.append("\n---\n\n")
    lines.append("## 研究声明\n\n")
    lines.append("1. 情绪指数基于公开API数据合成，分值区间为0-100\n")
    lines.append("2. 数据源: push2ex涨停池 + 同花顺热榜\n")
    lines.append("3. 权重: 涨停面40% + 热度面40% + 宽度面20%\n")
    lines.append("4. ≥80极度亢奋(风险信号) | ≤20极度悲观(机会信号)\n")
    lines.append("5. 今日资金面/价格面/量能面因push2 API被封暂不可用\n")
    lines.append("6. 情绪指数仅供参考，不构成投资建议\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("".join(lines))


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    today = datetime.now().strftime("%Y-%m-%d")
    output_dir = f"src/行业情绪/{today}-行业情绪扫描"
    os.makedirs(output_dir, exist_ok=True)

    report = generate_report(output_dir)
    print_report(report)
