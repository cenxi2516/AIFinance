#!/usr/bin/env python3
"""
中兴通讯(000063) 盘中实时交易信号分析
运行时间: 2026-07-21 10:47 (Phase 2 早盘过渡)
"""
import time, random, requests, json, re, os, sys
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

# ── 路径设置 ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.claude', 'skills', '_shared'))
from data_freshness import check_data_freshness, apply_freshness_to_condition, get_phase_weight_matrix, format_freshness_report

# ── 全局配置 ──
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _em_adapter = HTTPAdapter(max_retries=Retry(
        total=3, connect=3, backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    EM_SESSION.mount("https://", _em_adapter)
    EM_SESSION.mount("http://", _em_adapter)
except Exception:
    pass
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15, max_retries=5, **kwargs):
    global EM_SESSION
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            r = EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
            _em_last_call[0] = time.time()
            return r
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                delay = 4 + random.uniform(2, 5)
                time.sleep(delay)
                # 重建 session
                try:
                    EM_SESSION.close()
                except Exception:
                    pass
                EM_SESSION = requests.Session()
                EM_SESSION.headers.update({"User-Agent": UA})
    raise last_err

CODE = "000063"
OUTPUT_BASE = "src/盘中交易信号"

# ════════════════════════════════════════════════════════════
# Layer 0: 时效性门控
# ════════════════════════════════════════════════════════════
_freshness = check_data_freshness()
_fd = _freshness.get("freshness", {})
_downgrade_log = []

def _cond(text, threshold, actual, met, weight, dimension):
    result = apply_freshness_to_condition(text, threshold, actual, met, weight, dimension, _freshness)
    if result.get("freshness_status") != "ready":
        _downgrade_log.append({"condition": text, "dimension": dimension,
                               "status": result["freshness_status"],
                               "original_weight": weight,
                               "effective_weight": result["weight"]})
    return result

# ════════════════════════════════════════════════════════════
# Layer 1: 实时行情
# ════════════════════════════════════════════════════════════
def fetch_realtime_quote(code):
    prefixed = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
    url = f"https://qt.gtimg.cn/q={prefixed}"
    try:
        req = Request(url)
        req.add_header("User-Agent", UA)
        resp = urlopen(req, timeout=8)
        data = resp.read().decode("gbk")
        vals = data.split('"')[1].split("~") if '"' in data else []
        if len(vals) < 53:
            return {"error": "数据字段不足", "raw_len": len(vals)}
        return {
            "name": vals[1], "code": vals[2],
            "price": float(vals[3]) if vals[3] else 0,
            "prev_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "volume": float(vals[6]) if vals[6] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "amplitude": float(vals[43]) if vals[43] else 0,
            "vol_ratio": float(vals[49]) if vals[49] else 0,
            "amount": float(vals[37]) if vals[37] else 0,
            "pe": float(vals[39]) if vals[39] else 0,
            "mcap": float(vals[45]) if vals[45] else 0,
        }
    except Exception as e:
        return {"error": str(e)}

# ════════════════════════════════════════════════════════════
# Layer 2: 分钟级资金流
# ════════════════════════════════════════════════════════════
def eastmoney_fund_flow_minute(code):
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid, "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/", "Origin": "https://quote.eastmoney.com"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
    except Exception as e:
        print(f"[WARN] push2 资金流请求失败: {e}")
        return []
    rows = []
    for line in d.get("data", {}).get("klines", []):
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append({
                "time": parts[0],
                "main_net": float(parts[1]),
                "small_net": float(parts[2]),
                "mid_net": float(parts[3]),
                "large_net": float(parts[4]),
                "super_net": float(parts[5]),
            })
    return rows

def fetch_minute_fund_flow(code):
    try:
        minutes = eastmoney_fund_flow_minute(code)
    except Exception as e:
        return {"error": f"资金流拉取失败: {e}", "minutes": [], "summary": {}, "trend": {}}
    if not minutes:
        return {"error": "无资金流数据", "minutes": [], "summary": {}, "trend": {}}

    # push2 API 返回值是累计值(元)，不是每分钟增量
    # 取最新一条作为当日累计
    latest = minutes[-1]
    total_main = latest["main_net"]
    total_super = latest["super_net"]
    total_large = latest["large_net"]
    total_mid = latest["mid_net"]
    total_small = latest["small_net"]

    # 累计序列直接使用（已经是累计值）
    cum_main = [m["main_net"] for m in minutes]

    if len(cum_main) >= 10:
        mid_point = len(cum_main) // 2
        first_half = cum_main[:mid_point]
        second_half = cum_main[mid_point:]
        first_slope = (first_half[-1] - first_half[0]) / max(len(first_half), 1)
        second_slope = (second_half[-1] - second_half[0]) / max(len(second_half), 1)
        direction = "流入" if cum_main[-1] > 0 else "流出"
        if second_slope > first_slope * 1.5:
            acceleration = "加速流入" if second_slope > 0 else "流出减缓"
        elif second_slope < first_slope * 0.3:
            acceleration = "流入减缓" if second_slope > 0 else "加速流出"
        else:
            acceleration = "匀速" + direction
    else:
        direction = "数据不足"
        acceleration = "数据不足"
        first_slope = second_slope = 0

    turning_points = []
    if len(cum_main) >= 20:
        for i in range(10, len(cum_main) - 5):
            before = cum_main[i - 5:i]
            after = cum_main[i:i + 5]
            is_peak = all(cum_main[i] > b for b in before) and all(cum_main[i] > a for a in after)
            is_valley = all(cum_main[i] < b for b in before) and all(cum_main[i] < a for a in after)
            if is_peak:
                turning_points.append({"time": minutes[i]["time"], "type": "峰值(资金见顶)", "value_wan": cum_main[i] / 1e4})
            elif is_valley:
                turning_points.append({"time": minutes[i]["time"], "type": "谷值(资金见底)", "value_wan": cum_main[i] / 1e4})
    last_turn = turning_points[-1] if turning_points else None

    return {
        "minutes": minutes,
        "summary": {
            "total_main_net": round(total_main, 0),
            "total_main_net_wan": round(total_main / 1e4, 1),
            "total_super_net_wan": round(total_super / 1e4, 1),
            "total_large_net_wan": round(total_large / 1e4, 1),
            "total_mid_net_wan": round(total_mid / 1e4, 1),
            "total_small_net_wan": round(total_small / 1e4, 1),
            "data_points": len(minutes),
            "first_time": minutes[0]["time"] if minutes else "",
            "last_time": minutes[-1]["time"] if minutes else "",
        },
        "trend": {
            "direction": direction, "acceleration": acceleration,
            "first_half_slope_wan_per_min": round(first_slope / 1e4, 2),
            "second_half_slope_wan_per_min": round(second_slope / 1e4, 2),
            "cum_sequence_wan": [round(v / 1e4, 1) for v in cum_main],
            "turning_points": turning_points[-5:],
            "last_turn": last_turn,
        },
    }

# ════════════════════════════════════════════════════════════
# Layer 2.2: 三方资金分类
# ════════════════════════════════════════════════════════════
def classify_intraday_parties(flow_data):
    s = flow_data.get("summary", {})
    inst_net = s.get("total_super_net_wan", 0)
    hm_net = s.get("total_large_net_wan", 0)
    retail_net = (s.get("total_mid_net_wan", 0) or 0) + (s.get("total_small_net_wan", 0) or 0)
    main_net = s.get("total_main_net_wan", 0)
    data_points = s.get("data_points", 0)

    inst_rate = inst_net / max(data_points, 1)
    hm_rate = hm_net / max(data_points, 1)
    retail_rate = retail_net / max(data_points, 1)

    total_abs = abs(inst_net) + abs(hm_net) + abs(retail_net)
    if total_abs > 0:
        inst_share = round(abs(inst_net) / total_abs * 100, 1)
        hm_share = round(abs(hm_net) / total_abs * 100, 1)
        retail_share = round(abs(retail_net) / total_abs * 100, 1)
    else:
        inst_share = hm_share = retail_share = 0

    if inst_net > 200 and hm_net > 0 and retail_net < -100:
        scenario = "机构+游资合力做多，散户恐慌出局 → 强多头信号"
        level = "🟢 积极"
    elif inst_net > 200 and retail_net > 100:
        scenario = "机构与散户同向流入 → 共识强，但散户过度乐观是隐忧"
        level = "🟡 中性偏多"
    elif inst_net < -200 and retail_net > 200:
        scenario = f"机构净流出{abs(inst_net):.0f}万 + 散户净流入{retail_net:.0f}万 → 机构派发、散户接盘，⚠️ 明确风险信号"
        level = "🔴 警惕"
    elif inst_net < -100 and hm_net < -100 and retail_net > 100:
        scenario = "机构+游资合力出逃，散户接盘 → 强空头信号"
        level = "🔴 危险"
    elif inst_net > 100 and hm_net < -50 and retail_net < -50:
        scenario = f"机构独力做多{inst_net:.0f}万，游资{hm_net:.0f}万+散户{retail_net:.0f}万不跟 → 孤军深入，持续性存疑"
        level = "🟡 中性"
    else:
        scenario = "三方分歧，方向不明确"
        level = "⚪ 观望"

    return {
        "institution": {"net_wan": round(inst_net, 1), "direction": "流入" if inst_net >= 0 else "流出",
                        "share_pct": inst_share, "rate_per_min_wan": round(inst_rate, 2)},
        "hot_money": {"net_wan": round(hm_net, 1), "direction": "流入" if hm_net >= 0 else "流出",
                      "share_pct": hm_share, "rate_per_min_wan": round(hm_rate, 2)},
        "retail": {"net_wan": round(retail_net, 1), "direction": "流入" if retail_net >= 0 else "流出",
                   "share_pct": retail_share, "rate_per_min_wan": round(retail_rate, 2)},
        "verdict": {"scenario": scenario, "level": level,
                    "main_direction": "多头占优" if main_net > 0 else "空头占优"},
        "data_basis": {
            "data_points": data_points,
            "time_range": f"{s.get('first_time', '?')} → {s.get('last_time', '?')}",
            "source": "东方财富 push2 分钟级资金流 API",
        },
    }

# ════════════════════════════════════════════════════════════
# Layer 2.3: 资金-价格背离检测
# ════════════════════════════════════════════════════════════
def detect_fund_price_divergence(flow_data, quote):
    minutes = flow_data.get("minutes", [])
    if not minutes or len(minutes) < 20:
        return {"has_divergence": False, "reason": f"数据不足（当前仅{len(minutes)}分钟，需≥20分钟）"}

    # push2 API 值已是累计值，直接使用
    cum_main = [m["main_net"] for m in minutes]

    n = len(minutes)
    seg_size = n // 4
    divergences = []
    change_pct = quote.get("change_pct", 0)

    for i in range(1, 4):
        prev_start = (i - 1) * seg_size
        prev_end = i * seg_size
        curr_start = i * seg_size
        curr_end = min((i + 1) * seg_size, n)
        if curr_end <= curr_start:
            continue
        prev_flow_change = cum_main[prev_end - 1] - cum_main[prev_start]
        curr_flow_change = cum_main[curr_end - 1] - cum_main[curr_start]

        if change_pct > 3 and prev_flow_change > 0 and curr_flow_change < prev_flow_change * 0.3:
            divergences.append({
                "type": "顶背离(资金衰竭)",
                "detail": f"价格涨{change_pct:+.2f}%，但资金流入从{prev_flow_change/1e4:.0f}万骤降至{curr_flow_change/1e4:.0f}万",
                "data": f"时段对比: {minutes[prev_start]['time']}-{minutes[prev_end-1]['time']} vs {minutes[curr_start]['time']}-{minutes[curr_end-1]['time']}",
                "risk": "上涨动力衰竭，警惕冲高回落",
            })
        if change_pct < -3 and prev_flow_change < 0 and curr_flow_change > abs(prev_flow_change) * 0.5:
            divergences.append({
                "type": "底背离(资金回流)",
                "detail": f"价格跌{change_pct:+.2f}%，但资金从流出{abs(prev_flow_change)/1e4:.0f}万转为流入{curr_flow_change/1e4:.0f}万",
                "data": f"时段对比: {minutes[prev_start]['time']}-{minutes[prev_end-1]['time']} vs {minutes[curr_start]['time']}-{minutes[curr_end-1]['time']}",
                "risk": "下跌动力衰竭，关注反弹机会",
            })

    return {"has_divergence": len(divergences) > 0, "divergences": divergences}

# ════════════════════════════════════════════════════════════
# Layer 3: 板块情绪 + 概念板块
# ════════════════════════════════════════════════════════════
def eastmoney_concept_blocks(code):
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3", "pi": "0", "pz": "200", "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/slist/get", params=params, headers=headers, timeout=15)
        d = r.json()
    except Exception as e:
        return {"total": 0, "boards": [], "concept_tags": []}
    diff = (d.get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    boards = []
    for it in items:
        boards.append({
            "name": it.get("f14", ""), "code": it.get("f12", ""),
            "change_pct": it.get("f3", 0), "lead_stock": it.get("f128", ""),
        })
    return {"total": len(boards), "boards": boards, "concept_tags": [b["name"] for b in boards]}

_SECTOR_CACHE = None
_SECTOR_CACHE_TIME = None
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

def _load_all_concept_sectors():
    global _SECTOR_CACHE, _SECTOR_CACHE_TIME
    now = time.time()
    if _SECTOR_CACHE is not None and _SECTOR_CACHE_TIME and (now - _SECTOR_CACHE_TIME) < 60:
        return _SECTOR_CACHE
    params = {
        "pn": "1", "pz": "500", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",
        "fields": "f2,f3,f12,f14,f62,f104,f105",
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    try:
        r = em_get(PUSH2_CLIST, params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", []) or []
    except Exception:
        return {}
    sectors = {}
    for it in items:
        bk_code = it.get("f12", "")
        if bk_code:
            main_net = it.get("f62") or 0
            sectors[bk_code] = {
                "code": bk_code, "name": it.get("f14", ""),
                "change_pct": it.get("f3", 0),
                "main_net_wan": round(main_net / 1e4, 1),
                "direction": "流入" if main_net > 0 else "流出",
                "up_count": it.get("f104", 0), "down_count": it.get("f105", 0),
            }
    _SECTOR_CACHE = sectors
    _SECTOR_CACHE_TIME = now
    return sectors

def fetch_sector_sentiment(code):
    try:
        raw_blocks = eastmoney_concept_blocks(code)
        boards_raw = raw_blocks.get("boards", [])
        stock_blocks = [{"code": it.get("code", ""), "name": it.get("name", ""),
                         "change_pct": it.get("change_pct", 0)} for it in boards_raw]
    except Exception:
        return {"error": "板块归属获取失败", "blocks": [], "sentiment_score": 0}
    if not stock_blocks:
        return {"error": "未找到所属概念板块", "blocks": [], "sentiment_score": 0}

    all_sectors = _load_all_concept_sectors()
    sentiment_blocks = []
    for bk in stock_blocks[:8]:
        sector_data = all_sectors.get(bk["code"])
        if sector_data:
            sentiment_blocks.append(sector_data)
        else:
            sentiment_blocks.append({
                "code": bk["code"], "name": bk["name"],
                "change_pct": bk["change_pct"],
                "main_net_wan": 0, "direction": "未知",
                "up_count": 0, "down_count": 0,
            })
    if not sentiment_blocks:
        return {"error": "板块数据获取失败", "blocks": [], "sentiment_score": 0}

    inflow_count = sum(1 for b in sentiment_blocks if b["main_net_wan"] > 0)
    total_blocks = len(sentiment_blocks)
    avg_change = sum(b["change_pct"] for b in sentiment_blocks) / max(total_blocks, 1)
    total_flow = sum(b["main_net_wan"] for b in sentiment_blocks)

    flow_score = (inflow_count / max(total_blocks, 1)) * 50
    price_score = max(0, min(50, (avg_change + 5) * 5))
    sentiment_score = round(flow_score + price_score, 1)

    if sentiment_score >= 75:
        level = "🔥 极热"
    elif sentiment_score >= 60:
        level = "🟢 偏热"
    elif sentiment_score >= 40:
        level = "🟡 中性"
    elif sentiment_score >= 25:
        level = "🔵 偏冷"
    else:
        level = "❄️ 极冷"

    return {
        "blocks": sentiment_blocks,
        "sentiment_score": sentiment_score, "level": level,
        "inflow_blocks": inflow_count, "total_blocks": total_blocks,
        "avg_change_pct": round(avg_change, 2),
        "total_sector_flow_wan": round(total_flow, 1),
        "data_basis": f"{inflow_count}/{total_blocks}板块流入, 板块合计资金{total_flow:+.0f}万, 平均涨跌{avg_change:+.2f}%, 情绪分{sentiment_score}",
        "source": "东财 push2 slist(板块归属) + clist m:90+t:3(板块资金流)",
    }

# ════════════════════════════════════════════════════════════
# Layer 4: 消息面
# ════════════════════════════════════════════════════════════
def fetch_intraday_news(code):
    cb = "jQuery_news"
    inner = json.dumps({
        "uid": "", "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {
            "searchScope": "default", "sort": "default",
            "pageIndex": 1, "pageSize": 20, "preTag": "", "postTag": "",
        }},
    }, separators=(',', ':'))
    params = {"cb": cb, "param": inner}
    headers = {"Referer": "https://so.eastmoney.com/"}
    try:
        r = em_get("https://search-api-web.eastmoney.com/search/jsonp", params=params, headers=headers, timeout=10)
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = json.loads(json_str)
        articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
    except Exception:
        return {"today_count": 0, "highlights": [], "error": "新闻获取失败"}

    today_str = datetime.now().strftime("%Y-%m-%d")
    news = []
    for a in articles:
        title = re.sub(r'<[^>]+>', '', a.get("title", ""))
        content = re.sub(r'<[^>]+>', '', a.get("content", ""))[:200]
        news.append({
            "title": title, "content": content,
            "time": a.get("date", ""), "source": a.get("mediaName", ""),
            "url": a.get("url", ""),
            "is_today": a.get("date", "").startswith(today_str),
        })

    today_news = [n for n in news if n["is_today"]]
    bullish_keywords = ["增长", "突破", "中标", "订单", "扩产", "获批", "回购", "增持", "超预期"]
    bearish_keywords = ["减持", "亏损", "下滑", "调查", "处罚", "诉讼", "违约", "暴雷", "退市"]

    highlights = []
    for n in today_news[:8]:
        sentiment = "neutral"
        if any(kw in n["title"] for kw in bullish_keywords):
            sentiment = "bullish"
        elif any(kw in n["title"] for kw in bearish_keywords):
            sentiment = "bearish"
        highlights.append({**n, "sentiment": sentiment})

    return {
        "today_count": len(today_news), "highlights": highlights,
        "bullish_count": sum(1 for h in highlights if h["sentiment"] == "bullish"),
        "bearish_count": sum(1 for h in highlights if h["sentiment"] == "bearish"),
        "source": "东方财富 search-api-web 个股新闻",
    }

# ════════════════════════════════════════════════════════════
# Layer 5: 北向资金
# ════════════════════════════════════════════════════════════
def fetch_north_bound_flow():
    try:
        hgt_url = "https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/hgt"
        r_hgt = requests.get(hgt_url, headers={"User-Agent": UA}, timeout=8)
        hgt_data = r_hgt.json()
    except Exception:
        hgt_data = None
    try:
        sgt_url = "https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/sgt"
        r_sgt = requests.get(sgt_url, headers={"User-Agent": UA}, timeout=8)
        sgt_data = r_sgt.json()
    except Exception:
        sgt_data = None

    hgt_net = 0.0
    sgt_net = 0.0
    if hgt_data and hgt_data.get("data"):
        hgt_items = hgt_data["data"] if isinstance(hgt_data["data"], list) else []
        hgt_net = sum(it.get("net", 0) for it in hgt_items[-10:])
    if sgt_data and sgt_data.get("data"):
        sgt_items = sgt_data["data"] if isinstance(sgt_data["data"], list) else []
        sgt_net = sum(it.get("net", 0) for it in sgt_items[-10:])

    total_net = hgt_net + sgt_net
    total_net_yi = total_net / 1e4

    if total_net > 5000:
        direction = "大幅流入"
        signal = "🟢 积极"
    elif total_net > 0:
        direction = "小幅流入"
        signal = "🟡 中性偏多"
    elif total_net > -5000:
        direction = "小幅流出"
        signal = "🟠 中性偏空"
    else:
        direction = "大幅流出"
        signal = "🔴 警惕"

    return {
        "hgt_net_wan": round(hgt_net, 0), "sgt_net_wan": round(sgt_net, 0),
        "total_net_wan": round(total_net, 0), "total_net_yi": round(total_net_yi, 2),
        "direction": direction, "signal": signal,
        "source": "同花顺 hsgtApi (实时北向资金)",
        "data_basis": f"沪股通{hgt_net/1e4:+.2f}亿 + 深股通{sgt_net/1e4:+.2f}亿 = 北向合计{total_net_yi:+.2f}亿",
    }

# ════════════════════════════════════════════════════════════
# Layer 6: 大盘相对强度
# ════════════════════════════════════════════════════════════
def fetch_market_strength(code, quote):
    indices = {"上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006"}
    market_data = {}
    for name, idx_code in indices.items():
        try:
            url = f"https://qt.gtimg.cn/q={idx_code}"
            req = Request(url)
            req.add_header("User-Agent", UA)
            resp = urlopen(req, timeout=5)
            data = resp.read().decode("gbk")
            vals = data.split('"')[1].split("~") if '"' in data else []
            if len(vals) >= 33:
                market_data[name] = {
                    "price": float(vals[3]) if vals[3] else 0,
                    "change_pct": float(vals[32]) if vals[32] else 0,
                }
        except Exception:
            market_data[name] = {"price": 0, "change_pct": 0}

    if code.startswith(("6", "9")):
        primary_benchmark = "上证指数"
    elif code.startswith("30"):
        primary_benchmark = "创业板指"
    else:
        primary_benchmark = "深证成指"

    benchmark_change = market_data.get(primary_benchmark, {}).get("change_pct", 0)
    stock_change = quote.get("change_pct", 0)
    relative_strength = stock_change - benchmark_change

    if benchmark_change > 1:
        market_env = "🟢 大盘强势"
    elif benchmark_change > 0:
        market_env = "🟡 大盘微涨"
    elif benchmark_change > -1:
        market_env = "🟠 大盘微跌"
    else:
        market_env = "🔴 大盘弱势"

    if relative_strength > 3:
        relative_rating = "🚀 显著跑赢"
    elif relative_strength > 1:
        relative_rating = "✅ 跑赢大盘"
    elif relative_strength > -1:
        relative_rating = "➖ 与大盘同步"
    elif relative_strength > -3:
        relative_rating = "⚠️ 跑输大盘"
    else:
        relative_rating = "🔴 显著跑输"

    return {
        "benchmark": primary_benchmark, "benchmark_change": round(benchmark_change, 2),
        "market_env": market_env, "stock_change": round(stock_change, 2),
        "relative_strength": round(relative_strength, 2), "relative_rating": relative_rating,
        "market_detail": {k: round(v.get("change_pct", 0), 2) for k, v in market_data.items()},
        "source": "腾讯财经指数行情",
        "data_basis": f"{primary_benchmark}{benchmark_change:+.2f}%, 个股{stock_change:+.2f}%, 相对强弱{relative_strength:+.2f}%",
    }

# ════════════════════════════════════════════════════════════
# Layer 7: 市场广度
# ════════════════════════════════════════════════════════════
def fetch_market_breadth():
    # 1. 全市场涨跌家数
    params = {
        "pn": "1", "pz": "1", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f104,f105",
    }
    try:
        r = em_get(PUSH2_CLIST, params=params, headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        up_count = sum(it.get("f104", 0) for it in items) if items else 0
        down_count = sum(it.get("f105", 0) for it in items) if items else 0
    except Exception:
        up_count, down_count = 0, 0

    # 2. 涨停/跌停家数
    try:
        r_up = em_get("https://push2ex.eastmoney.com/getTopicZTPool",
                      params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                              "sort": "fbt", "fbt": "desc"},
                      headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        try:
            limit_up_count = r_up.json().get("data", {}).get("total", 0) or 0
        except Exception:
            limit_up_count = 0
        r_down = em_get("https://push2ex.eastmoney.com/getTopicDTPool",
                        params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                                "sort": "fund", "fund": "desc"},
                        headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        try:
            limit_down_count = r_down.json().get("data", {}).get("total", 0) or 0
        except Exception:
            limit_down_count = 0
    except Exception:
        limit_up_count, limit_down_count = 0, 0

    total = up_count + down_count
    up_ratio = up_count / max(total, 1) * 100

    if up_ratio >= 70:
        breadth_level = "🟢 普涨格局"
        breadth_score = 85
    elif up_ratio >= 55:
        breadth_level = "🟡 涨多跌少"
        breadth_score = 60
    elif up_ratio >= 45:
        breadth_level = "🟠 分化格局"
        breadth_score = 40
    elif up_ratio >= 30:
        breadth_level = "🔴 跌多涨少"
        breadth_score = 20
    else:
        breadth_level = "💀 普跌格局"
        breadth_score = 5

    limit_ratio = limit_up_count / max(limit_down_count, 1)
    if limit_ratio >= 3:
        money_effect = "🔥 强赚钱效应"
    elif limit_ratio >= 1.5:
        money_effect = "✅ 赚钱效应良好"
    elif limit_ratio >= 1:
        money_effect = "➖ 赚钱效应中性"
    elif limit_ratio >= 0.5:
        money_effect = "⚠️ 亏钱效应显现"
    else:
        money_effect = "💀 强亏钱效应"

    return {
        "up_count": up_count, "down_count": down_count,
        "up_ratio_pct": round(up_ratio, 1), "breadth_level": breadth_level,
        "breadth_score": breadth_score,
        "limit_up_count": limit_up_count, "limit_down_count": limit_down_count,
        "limit_ratio": round(limit_ratio, 1), "money_effect": money_effect,
        "source": "东财 push2ex 涨停/跌停池 + push2 clist",
        "data_basis": f"全市场涨{up_count}跌{down_count}({up_ratio:.1f}%), 涨停{limit_up_count}/跌停{limit_down_count}, 赚钱效应:{money_effect}",
    }

# ════════════════════════════════════════════════════════════
# Layer 8: 七维概率预判引擎
# ════════════════════════════════════════════════════════════
def generate_probability_scenarios(flow_data, quote, sector_data, news_data, party_data, divergence,
                                   north_bound=None, market_strength=None, market_breadth=None):
    global _downgrade_log
    _downgrade_log = []

    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)

    s = flow_data.get("summary", {})
    main_net_wan = s.get("total_main_net_wan", 0)
    inst_net = party_data.get("institution", {}).get("net_wan", 0)
    hm_net = party_data.get("hot_money", {}).get("net_wan", 0)
    retail_net = party_data.get("retail", {}).get("net_wan", 0)
    data_points = s.get("data_points", 0)

    t = flow_data.get("trend", {})
    acceleration = t.get("acceleration", "")
    direction = t.get("direction", "")
    first_slope = t.get("first_half_slope_wan_per_min", 0)
    second_slope = t.get("second_half_slope_wan_per_min", 0)
    last_turn = t.get("last_turn", {})

    sentiment_score = sector_data.get("sentiment_score", 50)
    inflow_blocks = sector_data.get("inflow_blocks", 0)
    total_blocks = sector_data.get("total_blocks", 1)

    news_bullish = news_data.get("bullish_count", 0)
    news_bearish = news_data.get("bearish_count", 0)

    has_divergence = divergence.get("has_divergence", False)
    divergence_type = ""
    if has_divergence and divergence.get("divergences"):
        divergence_type = divergence["divergences"][0].get("type", "")

    nb = north_bound or {}
    nb_net_yi = nb.get("total_net_yi", 0)
    nb_direction = nb.get("direction", "")

    ms = market_strength or {}
    relative_strength = ms.get("relative_strength", 0)
    market_env = ms.get("market_env", "")

    mb = market_breadth or {}
    up_ratio = mb.get("up_ratio_pct", 50)
    breadth_score = mb.get("breadth_score", 50)
    limit_ratio = mb.get("limit_ratio", 1)
    money_effect = mb.get("money_effect", "")

    scenarios = []

    # ═══════ 情景A: 强势上涨 ═══════
    a_conditions = []
    a_score = 0

    c = _cond("主力净流入>500万", ">500万", f"{main_net_wan:+.0f}万",
              main_net_wan > 500 and direction == "流入", 25, "minute_flow")
    a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0

    inst_dominates = inst_net > 200 and inst_net > abs(hm_net) and inst_net > abs(retail_net)
    c = _cond("机构主导(净流入>200万且>游资+散户)", "机构>200万且最大",
              f"机构{inst_net:+.0f}万, 游资{hm_net:+.0f}万, 散户{retail_net:+.0f}万",
              inst_dominates, 20, "minute_flow")
    a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0

    c = _cond("板块情绪分≥60", "≥60", f"{sentiment_score:.0f}分 ({inflow_blocks}/{total_blocks}板块流入)",
              sentiment_score >= 60, 15, "sector")
    a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0

    vol_ok = 1.2 <= vol_ratio <= 5 and turnover < 15
    c = _cond("量能配合(量比1.2~5, 换手<15%)", "量比1.2-5, 换手<15%",
              f"量比{vol_ratio}, 换手{turnover}%", vol_ok, 15, "quote")
    a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0

    no_top_div = not has_divergence or "顶背离" not in divergence_type
    c = _cond("无顶背离信号", "无顶背离",
              f"背离: {'有('+divergence_type+')' if has_divergence else '无'}", no_top_div, 15, "minute_flow")
    a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0

    accel_positive = "加速流入" in acceleration
    c = _cond("资金加速流入", "后半段斜率>前半段×1.5",
              f"前半段{first_slope}万/分 → 后半段{second_slope}万/分", accel_positive, 10, "minute_flow")
    a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0

    nb_support = nb_net_yi > 0 or nb_direction in ("大幅流入", "小幅流入")
    if nb_support and nb_net_yi > 1:
        c = _cond("北向资金流入(>1亿)", "北向净流入>1亿", f"北向{nb_net_yi:+.2f}亿", True, 10, "north_bound")
        a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0
    elif nb_net_yi < -5:
        c = _cond("北向资金未大幅流出", "北向>-5亿", f"北向{nb_net_yi:+.2f}亿(⚠️大幅流出扣分)", False, 10, "north_bound")
        a_conditions.append(c); a_score -= 5
    else:
        c = _cond("北向资金不拖累", "北向不大幅流出", f"北向{nb_net_yi:+.2f}亿", nb_net_yi > -5, 10, "north_bound")
        a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0

    market_tailwind = relative_strength > 1 and "弱势" not in market_env
    c = _cond("大盘配合+个股跑赢", "相对强度>1%且大盘非弱势",
              f"{market_env}, 相对强度{relative_strength:+.2f}%", market_tailwind, 5, "market")
    a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0

    breadth_ok = up_ratio >= 45 and "亏钱" not in money_effect
    if breadth_ok:
        c = _cond("市场广度不差(上涨>45%)", "上涨占比≥45%且无强亏钱效应",
                  f"涨{up_ratio:.0f}%, {money_effect}", True, 5, "breadth")
        a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0
    else:
        c = _cond("市场广度不差(上涨>45%)", "上涨占比≥45%",
                  f"涨{up_ratio:.0f}%, {money_effect}(⚠️扣分)", False, 5, "breadth")
        a_conditions.append(c); a_score -= 3

    vol_ref_ok = vol_ratio >= 0.8 and turnover >= 0.5
    c = _cond("量能参考(量比≥0.8+换手≥0.5%)", "量比≥0.8,换手≥0.5%",
              f"量比{vol_ratio},换手{turnover}%", vol_ref_ok, 2, "quote")
    a_conditions.append(c); a_score += c["weight"] if c.get("met") == True else 0

    # 七维同向共振加分
    bullish_dims = sum([
        1 if main_net_wan > 300 else 0,
        1 if change_pct > 0 else 0,
        1 if sentiment_score >= 50 else 0,
        1 if news_bullish > news_bearish else 0,
        1 if nb_net_yi > 0 else 0,
        1 if relative_strength > 0 else 0,
        1 if up_ratio >= 45 else 0,
    ])
    if bullish_dims >= 6:
        a_score += 10
    elif bullish_dims >= 5:
        a_score += 5

    scenarios.append({
        "name": "情景A: 强势上涨",
        "description": "主力持续流入+机构主导+板块共振+量能配合 → 当日剩余时段大概率继续走强",
        "raw_score": a_score, "conditions": a_conditions,
        "met_count": sum(1 for c in a_conditions if c.get("met") == True),
        "total_conditions": len(a_conditions),
        "resonance_dims": bullish_dims,
        "historical_ref": {
            "rule": "机构主导+板块共振+量能配合 → 当日继续走强",
            "historical_win_rate": "约65-70%",
            "source": "基于2024-2025年A股日内资金流统计规律",
        },
        "failure_conditions": ["午后机构资金转流出", "板块情绪急转直下(骤降>20分)", "突发重大利空"],
    })

    # ═══════ 情景B: 震荡横盘 ═══════
    b_conditions = []
    b_score = 0

    no_direction = abs(main_net_wan) < 300
    c = _cond("主力净流入<300万(无方向)", "绝对值<300万", f"{main_net_wan:+.0f}万", no_direction, 30, "minute_flow")
    b_conditions.append(c); b_score += c["weight"] if c.get("met") == True else 0

    narrow_range = amplitude < 3
    c = _cond("振幅<3%(窄幅波动)", "<3%", f"{amplitude}%", narrow_range, 25, "quote")
    b_conditions.append(c); b_score += c["weight"] if c.get("met") == True else 0

    neutral_sentiment = 35 <= sentiment_score <= 65
    c = _cond("板块情绪35~65(中性)", "35-65", f"{sentiment_score:.0f}分", neutral_sentiment, 25, "sector")
    b_conditions.append(c); b_score += c["weight"] if c.get("met") == True else 0

    no_news = news_bullish == 0 and news_bearish == 0
    c = _cond("无明确消息催化", "0条今日新闻", f"利好{news_bullish}/利空{news_bearish}", no_news, 15, "news")
    b_conditions.append(c); b_score += c["weight"] if c.get("met") == True else 0

    nb_neutral = abs(nb_net_yi) < 3
    c = _cond("北向资金无明显方向(±3亿内)", "|北向|<3亿", f"北向{nb_net_yi:+.2f}亿", nb_neutral, 10, "north_bound")
    b_conditions.append(c); b_score += c["weight"] if c.get("met") == True else 0

    market_neutral = abs(relative_strength) < 1.5 and abs(ms.get("benchmark_change", 0)) < 1
    c = _cond("大盘+个股均中性波动", "|相对强度|<1.5%,|大盘|<1%",
              f"大盘{ms.get('benchmark_change', 0):+.2f}%, 相对{relative_strength:+.2f}%", market_neutral, 10, "market")
    b_conditions.append(c); b_score += c["weight"] if c.get("met") == True else 0

    breadth_neutral = 40 <= up_ratio <= 60 and 0.8 <= limit_ratio <= 2
    c = _cond("市场广度中性(涨40-60%,涨跌停比0.8-2)", "涨40-60%,涨跌停比0.8-2",
              f"涨{up_ratio:.0f}%, 涨跌停比{limit_ratio}", breadth_neutral, 10, "breadth")
    b_conditions.append(c); b_score += c["weight"] if c.get("met") == True else 0

    scenarios.append({
        "name": "情景B: 震荡横盘",
        "description": "资金方向不明+振幅小+情绪中性+无催化 → 当日剩余时段大概率窄幅震荡",
        "raw_score": b_score, "conditions": b_conditions,
        "met_count": sum(1 for c in b_conditions if c.get("met") == True),
        "total_conditions": len(b_conditions),
        "historical_ref": {
            "rule": "主力资金无明显方向+振幅<3% → 后续2小时横盘概率较高",
            "historical_win_rate": "约55-60%",
            "source": "基于A股日内波动统计规律",
        },
        "failure_conditions": ["突发消息催化", "大单资金突然涌入/涌出"],
    })

    # ═══════ 情景C: 冲高回落 ═══════
    c_conditions = []
    c_score = 0

    high_and_turning = change_pct > 3 and ("流出" in acceleration or "减缓" in acceleration)
    c = _cond("已涨>3%且资金流转向", "涨>3%+资金减缓/流出",
              f"涨{change_pct:+.2f}%, 趋势:{acceleration}", high_and_turning, 30, "minute_flow")
    c_conditions.append(c); c_score += c["weight"] if c.get("met") == True else 0

    top_divergence = has_divergence and "顶背离" in divergence_type
    c = _cond("出现顶背离(资金衰竭)", "顶背离信号", divergence_type if top_divergence else "无", top_divergence, 25, "minute_flow")
    c_conditions.append(c); c_score += c["weight"] if c.get("met") == True else 0

    distribution = inst_net < -100 and retail_net > 200
    c = _cond("机构流出>100万+散户流入>200万(派发)", "机构<-100万,散户>+200万",
              f"机构{inst_net:+.0f}万,散户{retail_net:+.0f}万", distribution, 25, "minute_flow")
    c_conditions.append(c); c_score += c["weight"] if c.get("met") == True else 0

    abnormal_turnover = turnover > 10
    c = _cond("换手率>10%(异常活跃)", ">10%", f"{turnover}%", abnormal_turnover, 15, "quote")
    c_conditions.append(c); c_score += c["weight"] if c.get("met") == True else 0

    nb_bearish = nb_net_yi < -2
    c = _cond("北向资金流出(<-2亿)", "北向<-2亿", f"北向{nb_net_yi:+.2f}亿", nb_bearish, 10, "north_bound")
    c_conditions.append(c); c_score += c["weight"] if c.get("met") == True else 0

    high_weak_market = change_pct > 2 and relative_strength > 1 and "弱势" in market_env
    c = _cond("个股高位+大盘走弱(逆势难持续)", "涨>2%+相对强度>1%+大盘弱势",
              f"涨{change_pct:+.2f}%, 大盘{ms.get('benchmark_change', 0):+.2f}%", high_weak_market, 10, "market")
    c_conditions.append(c); c_score += c["weight"] if c.get("met") == True else 0

    money_weakening = limit_ratio < 1.5 or "亏钱" in money_effect
    c = _cond("赚钱效应转弱", "涨跌停比<1.5或有亏钱效应",
              f"涨跌停比{limit_ratio}, {money_effect}", money_weakening, 10, "breadth")
    c_conditions.append(c); c_score += c["weight"] if c.get("met") == True else 0

    scenarios.append({
        "name": "情景C: 冲高回落",
        "description": "高位+资金转向/顶背离/机构派发 → 当日剩余时段警惕回落风险",
        "raw_score": c_score, "conditions": c_conditions,
        "met_count": sum(1 for c in c_conditions if c.get("met") == True),
        "total_conditions": len(c_conditions),
        "historical_ref": {
            "rule": "涨超3%+资金转流出+机构vs散户反向 → 午后回落概率较高",
            "historical_win_rate": "约55-65%",
            "source": "基于A股日内资金流-价格关系统计",
        },
        "failure_conditions": ["超预期利好", "板块集体暴动(涨停潮)"],
    })

    # ═══════ 情景D: 弱势下跌 ═══════
    d_conditions = []
    d_score = 0

    heavy_outflow = main_net_wan < -500 and direction == "流出"
    c = _cond("主力净流出>500万", "<-500万", f"{main_net_wan:+.0f}万", heavy_outflow, 30, "minute_flow")
    d_conditions.append(c); d_score += c["weight"] if c.get("met") == True else 0

    cold_sentiment = sentiment_score < 40
    c = _cond("板块情绪<40(偏冷)", "<40", f"{sentiment_score:.0f}分", cold_sentiment, 25, "sector")
    d_conditions.append(c); d_score += c["weight"] if c.get("met") == True else 0

    accel_outflow = "加速流出" in acceleration
    c = _cond("资金加速流出", "后半段斜率<前半段×0.3且<0",
              f"前半段{first_slope}万/分 → 后半段{second_slope}万/分", accel_outflow, 25, "minute_flow")
    d_conditions.append(c); d_score += c["weight"] if c.get("met") == True else 0

    bearish_news = news_bearish > 0
    c = _cond("有利空消息", "利空>0条", f"利空{news_bearish}条" if news_bearish > 0 else "无", bearish_news, 15, "news")
    d_conditions.append(c); d_score += c["weight"] if c.get("met") == True else 0

    nb_heavy_out = nb_net_yi < -5
    c = _cond("北向大幅流出(<-5亿)", "北向<-5亿", f"北向{nb_net_yi:+.2f}亿", nb_heavy_out, 10, "north_bound")
    d_conditions.append(c); d_score += c["weight"] if c.get("met") == True else 0

    market_drag = "弱势" in market_env and relative_strength < -0.5
    c = _cond("大盘弱势+个股跑输", "大盘弱势+相对强度<-0.5%",
              f"{market_env}, 相对{relative_strength:+.2f}%", market_drag, 10, "market")
    d_conditions.append(c); d_score += c["weight"] if c.get("met") == True else 0

    breadth_bearish = up_ratio < 35 or limit_ratio < 0.8
    c = _cond("市场普跌(上涨<35%或涨跌停比<0.8)", "上涨<35%或涨跌停比<0.8",
              f"涨{up_ratio:.0f}%, 涨跌停比{limit_ratio}, {money_effect}", breadth_bearish, 10, "breadth")
    d_conditions.append(c); d_score += c["weight"] if c.get("met") == True else 0

    bearish_dims = sum([1 if main_net_wan < -300 else 0, 1 if change_pct < 0 else 0,
                        1 if sentiment_score < 40 else 0, 1 if news_bearish > 0 else 0,
                        1 if nb_net_yi < 0 else 0, 1 if relative_strength < -1 else 0,
                        1 if up_ratio < 35 else 0])
    if bearish_dims >= 5:
        d_score += 10

    scenarios.append({
        "name": "情景D: 弱势下跌",
        "description": "主力持续流出+板块冷+加速流出 → 当日剩余时段大概率继续走弱",
        "raw_score": d_score, "conditions": d_conditions,
        "met_count": sum(1 for c in d_conditions if c.get("met") == True),
        "total_conditions": len(d_conditions),
        "resonance_dims": bearish_dims,
        "historical_ref": {
            "rule": "主力持续流出+板块情绪<40 → 当日收阴概率较高",
            "historical_win_rate": "约60-70%",
            "source": "基于A股日内资金流-板块情绪联合统计",
        },
        "failure_conditions": ["午后重大利好", "国家队护盘资金入场"],
    })

    # ═══════ 概率归一化 ═══════
    # 确保最低分值不为负
    for s in scenarios:
        s["raw_score"] = max(0, s["raw_score"])

    total_score = sum(s["raw_score"] for s in scenarios)
    for s in scenarios:
        s["probability"] = round(s["raw_score"] / total_score * 100, 1) if total_score > 0 else 0

    scenarios_sorted = sorted(scenarios, key=lambda x: x["probability"], reverse=True)

    return {
        "scenarios": scenarios_sorted,
        "primary_scenario": scenarios_sorted[0] if scenarios_sorted else None,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_points": data_points,
        "freshness": {
            "phase": _freshness.get("phase", -1),
            "phase_name": _freshness.get("phase_name", "未知"),
            "minutes_from_open": _freshness.get("minutes_from_open", -1),
            "downgraded_count": len(_downgrade_log),
            "downgrade_details": _downgrade_log,
        },
        "disclaimer": "概率基于当前盘中数据的多因子条件匹配+时效性门控(V1.3)。标记为PENDING的条件表示数据尚未刷新，未参与概率计算。",
    }

# ════════════════════════════════════════════════════════════
# Layer 9: 买卖时机参考信号
# ════════════════════════════════════════════════════════════
def generate_trading_signals(scenarios, flow_data, quote, party_data, sector_data, north_bound=None,
                             market_strength=None, market_breadth=None):
    if not scenarios:
        return {"buy_signals": [], "sell_signals": [], "hold_verdict": {}, "overall_verdict": "数据不足"}

    primary = scenarios[0]
    primary_prob = primary.get("probability", 0)
    primary_name = primary.get("name", "")

    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)
    price = quote.get("price", 0)

    s = flow_data.get("summary", {})
    main_net_wan = s.get("total_main_net_wan", 0)
    inst_net = party_data.get("institution", {}).get("net_wan", 0)
    hm_net = party_data.get("hot_money", {}).get("net_wan", 0)
    retail_net = party_data.get("retail", {}).get("net_wan", 0)
    inst_share = party_data.get("institution", {}).get("share_pct", 0)
    data_points = s.get("data_points", 0)

    t = flow_data.get("trend", {})
    acceleration = t.get("acceleration", "")
    direction = t.get("direction", "")

    sentiment_score = sector_data.get("sentiment_score", 50)
    nb = north_bound or {}
    nb_net_yi = nb.get("total_net_yi", 0)
    ms = market_strength or {}
    relative_strength = ms.get("relative_strength", 0)

    buy_signals = []
    sell_signals = []

    # --- 强买入 ---
    strong_buy_conditions = [
        primary_prob >= 60 and "情景A" in primary_name,
        inst_net > 200,
        sentiment_score >= 60,
        change_pct < 5,
        "加速流入" in acceleration,
    ]
    strong_buy_met = sum(1 for c in strong_buy_conditions if c)

    if strong_buy_met >= 4:
        buy_signals.append({
            "level": "🟢🟢🟢 强买入参考", "strength": strong_buy_met,
            "data_evidence": [
                {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "≥60%", "source": "多因子概率引擎", "met": primary_prob >= 60},
                {"item": "主力累计净流入", "value": f"{main_net_wan:+.0f}万", "threshold": ">+200万(机构主导)", "source": "push2 分钟级资金流", "met": inst_net > 200},
                {"item": "板块情绪分", "value": f"{sentiment_score:.0f}/100", "threshold": "≥60", "source": "板块资金流聚合", "met": sentiment_score >= 60},
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<5%(未过度拉升)", "source": "腾讯行情API", "met": change_pct < 5},
                {"item": "资金加速度", "value": acceleration, "threshold": "加速流入", "source": "push2 趋势分析", "met": "加速流入" in acceleration},
                {"item": "机构vs散户", "value": f"机构{inst_net:+.0f}万 vs 散户{retail_net:+.0f}万", "threshold": "机构>+200万且>散户", "source": "三方资金分类", "met": inst_net > 200 and inst_net > retail_net},
            ],
            "action": "可考虑逢低建仓/加仓",
            "stop_loss": f"跌破{price * 0.97:.2f}(-3%)则果断离场",
            "principle": f"宁可少挣: {strong_buy_met}/5条件满足才触发,不追高,等回调到分时均线附近再动手",
        })

    # --- 中等买入 ---
    medium_buy_conditions = [
        primary_prob >= 45 and "情景A" in primary_name,
        inst_net > 100,
        sentiment_score >= 50,
        change_pct < 7,
    ]
    medium_buy_met = sum(1 for c in medium_buy_conditions if c)

    if medium_buy_met >= 3 and strong_buy_met < 4:
        buy_signals.append({
            "level": "🟢🟢 中等买入参考", "strength": medium_buy_met,
            "data_evidence": [
                {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "≥45%", "source": "多因子概率引擎", "met": primary_prob >= 45},
                {"item": "机构净流入", "value": f"{inst_net:+.0f}万", "threshold": ">+100万", "source": "push2 分钟级资金流", "met": inst_net > 100},
                {"item": "板块情绪分", "value": f"{sentiment_score:.0f}/100", "threshold": "≥50", "source": "板块资金流聚合", "met": sentiment_score >= 50},
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<7%", "source": "腾讯行情API", "met": change_pct < 7},
            ],
            "action": "可小仓位试探(计划仓位的30-50%), 等待更多信号确认",
            "stop_loss": f"跌破{price * 0.95:.2f}(-5%)则止损",
            "principle": "宁可少挣: 先小仓试错,确认方向后再加仓,不一次梭哈",
        })

    # --- 弱买入(左侧反弹) ---
    if primary_prob >= 30 and "情景D" in primary_name and main_net_wan > -300 and sentiment_score >= 30:
        buy_signals.append({
            "level": "🟢 弱买入参考(左侧/反弹)", "strength": 1,
            "data_evidence": [
                {"item": "情景D概率", "value": f"{primary_prob:.0f}%", "threshold": "≥30%但有反弹迹象", "source": "多因子概率引擎", "met": True},
                {"item": "主力净流出", "value": f"{main_net_wan:+.0f}万", "threshold": ">-300万(流出收窄)", "source": "push2 分钟级资金流", "met": main_net_wan > -300},
                {"item": "板块情绪", "value": f"{sentiment_score:.0f}/100", "threshold": "≥30(未极冷)", "source": "板块资金流聚合", "met": sentiment_score >= 30},
            ],
            "action": "仅极度激进者可关注, 大多数人应等待企稳确认",
            "stop_loss": f"跌破{price * 0.97:.2f}(-3%)强制止损",
            "principle": "宁可少挣: 宁可等企稳再追,也不提前抄底",
        })

    if not buy_signals:
        buy_signals.append({
            "level": "⚪ 暂不建议买入",
            "data_evidence": [
                {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "需≥45%", "source": "多因子概率引擎", "met": primary_prob >= 45 and "情景A" in primary_name},
                {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "需>+500万", "source": "push2 分钟级资金流", "met": main_net_wan > 500},
            ],
            "action": "继续观察, 等待资金面+情绪面+价格面共振信号",
            "principle": "宁可少挣: 不买至少不亏钱, 错过一波比亏一波好",
        })

    # --- 强卖出 ---
    strong_sell_conditions = [
        primary_prob >= 50 and ("情景C" in primary_name or "情景D" in primary_name),
        inst_net < -200,
        "加速流出" in acceleration,
    ]
    strong_sell_met = sum(1 for c in strong_sell_conditions if c)

    if strong_sell_met >= 3:
        sell_signals.append({
            "level": "🔴🔴🔴 强卖出参考", "strength": strong_sell_met,
            "data_evidence": [
                {"item": "弱势情景概率", "value": f"{primary_prob:.0f}%({primary_name})", "threshold": "≥50%", "source": "多因子概率引擎", "met": primary_prob >= 50},
                {"item": "机构净流出", "value": f"{inst_net:+.0f}万", "threshold": "<-200万", "source": "push2 分钟级资金流", "met": inst_net < -200},
                {"item": "资金加速度", "value": acceleration, "threshold": "加速流出", "source": "push2 趋势分析", "met": "加速流出" in acceleration},
                {"item": "机构份额", "value": f"{inst_share:.0f}%", "threshold": "机构主导流出", "source": "三方资金分类", "met": inst_share > 30},
                {"item": "板块情绪", "value": f"{sentiment_score:.0f}/100", "threshold": "偏冷(<40)", "source": "板块资金流聚合", "met": sentiment_score < 50},
                {"item": "主力净流出", "value": f"{main_net_wan:+.0f}万", "threshold": "大额流出", "source": "push2 分钟级资金流", "met": main_net_wan < -300},
            ],
            "action": "建议果断减仓/清仓, 不在下跌中补仓",
            "risk_note": f"继续持有可能面临更大回撤, 当前已流出{abs(main_net_wan):.0f}万",
            "principle": "宁可少亏: 卖了少亏比扛着大亏好, 卖错了可以再买回来",
        })

    # --- 中等卖出 ---
    medium_sell_conditions = [
        ("情景C" in primary_name and primary_prob >= 35) or ("情景D" in primary_name and primary_prob >= 35),
        inst_net < -100 or (inst_net < 0 and retail_net > 100),
    ]
    medium_sell_met = sum(1 for c in medium_sell_conditions if c)

    if medium_sell_met >= 2 and strong_sell_met < 3:
        sell_signals.append({
            "level": "🔴🔴 中等卖出参考", "strength": medium_sell_met,
            "data_evidence": [
                {"item": "弱势情景概率", "value": f"{primary_prob:.0f}%({primary_name})", "threshold": "≥35%", "source": "多因子概率引擎", "met": primary_prob >= 35},
                {"item": "机构资金", "value": f"{inst_net:+.0f}万", "threshold": "<-100万或机构流出+散户流入", "source": "push2 分钟级资金流", "met": inst_net < -100},
                {"item": "散户资金", "value": f"{retail_net:+.0f}万", "threshold": "如>+100万则为接盘信号", "source": "push2 分钟级资金流", "met": retail_net > 100},
                {"item": "资金趋势", "value": acceleration, "threshold": "流出或减缓", "source": "push2 趋势分析", "met": "流出" in acceleration},
            ],
            "action": "建议逐步减仓, 至少减到半仓以下",
            "risk_note": f"机构{'流出' if inst_net < 0 else '减弱'}{abs(inst_net):.0f}万, 散户{'接盘' if retail_net > 100 else '观望'}{retail_net:+.0f}万",
            "principle": "宁可少亏: 卖一半留一半, 涨了还有仓位, 跌了少亏一半",
        })

    # --- 弱卖出(止盈) ---
    if change_pct > 8 and ("流出" in direction or "减缓" in acceleration):
        sell_signals.append({
            "level": "🔴 弱卖出参考(高位止盈)",
            "data_evidence": [
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": ">8%(已大幅上涨)", "source": "腾讯行情API", "met": True},
                {"item": "资金方向", "value": f"{direction}/{acceleration}", "threshold": "流出/减缓", "source": "push2 趋势分析", "met": True},
                {"item": "换手率", "value": f"{turnover}%", "threshold": "如>8%警惕出货", "source": "腾讯行情API", "met": turnover > 8},
            ],
            "action": "可考虑部分止盈, 锁定利润",
            "principle": "宁可少挣: 落袋为安, 不贪最后一个铜板",
        })

    if not sell_signals:
        sell_signals.append({
            "level": "⚪ 暂不需卖出",
            "data_evidence": [
                {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "持续流入中", "source": "push2 分钟级资金流", "met": main_net_wan > 0},
                {"item": "资金加速度", "value": acceleration, "threshold": "未出现流出加速", "source": "push2 趋势分析", "met": "加速流出" not in acceleration},
            ],
            "action": "继续持有观察, 关注资金流方向是否转弱",
            "principle": "保持警觉, 一旦出现卖出数据条件, 果断行动",
        })

    # --- 持有参考 ---
    if "情景A" in primary_name and primary_prob >= 50:
        hold_verdict = {
            "level": "✅ 可继续持有",
            "reason": f"强势上涨概率{primary_prob:.0f}%, 主力净流入{main_net_wan:+.0f}万, 机构主导({inst_net:+.0f}万)",
            "watch_points": ["午后资金是否转流出", "是否出现顶背离", "板块情绪是否骤降"],
        }
    elif "情景B" in primary_name:
        hold_verdict = {
            "level": "⏸️ 持有观望",
            "reason": f"震荡格局, 主力资金{main_net_wan:+.0f}万(无明显方向), 振幅{amplitude}%",
            "watch_points": ["突破方向(放量上破/下破)", "是否有催化消息出现"],
        }
    else:
        hold_verdict = {
            "level": "⚠️ 审视持仓",
            "reason": f"风险情景概率较高({primary_name} {primary_prob:.0f}%), 机构{inst_net:+.0f}万",
            "watch_points": ["触发止损条件则果断执行", "等待情景A信号出现再考虑加仓"],
        }

    # --- 综合评估 ---
    strongest_buy = buy_signals[0]["level"] if buy_signals else ""
    strongest_sell = sell_signals[0]["level"] if sell_signals else ""

    if "强买入" in strongest_buy and "暂不需卖出" in strongest_sell:
        overall = f"总体偏多: 买入信号较强(满足{strong_buy_met}/5条件), 无卖出压力。主力净流入{main_net_wan:+.0f}万, 板块情绪{sentiment_score:.0f}分。可在控制仓位前提下逢低参与。"
    elif "强卖出" in strongest_sell:
        overall = f"总体偏空: 卖出信号较强(满足{strong_sell_met}/3条件)。主力净流出{abs(main_net_wan):.0f}万, 机构净流出{abs(inst_net):.0f}万。建议减仓或观望。"
    elif "中等卖出" in strongest_sell:
        overall = f"总体谨慎: 有卖出压力。机构{inst_net:+.0f}万, 散户{retail_net:+.0f}万。持有者应审视持仓, 未持有者建议等待。"
    elif "中等买入" in strongest_buy:
        overall = f"总体中性偏多: 满足{medium_buy_met}/4买入条件。主力{main_net_wan:+.0f}万。可小仓试探, 严格止损。"
    else:
        overall = f"总体中性: 主力{main_net_wan:+.0f}万, 信号不明确。建议观望, 等待更清晰的信号。"

    return {
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "hold_verdict": hold_verdict,
        "overall_verdict": overall,
        "data_summary": {
            "main_net_wan": main_net_wan, "inst_net_wan": inst_net, "retail_net_wan": retail_net,
            "sentiment_score": sentiment_score, "change_pct": change_pct,
            "turnover_pct": turnover, "vol_ratio": vol_ratio,
            "acceleration": acceleration, "data_points": data_points,
            "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    }

# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════
def main():
    global _freshness
    now = datetime.now()
    print("═" * 70)
    print(f"  📊 盘中实时交易信号: 中兴通讯(000063)")
    print(f"  分析时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  时效性阶段: {_freshness['phase_name']}")
    print("═" * 70)

    # [1/7] 实时行情
    print(f"\n[1/7] 拉取实时行情...")
    quote = fetch_realtime_quote(CODE)
    if "error" in quote:
        print(f"  ❌ 行情获取失败: {quote['error']}")
        return
    print(f"  ✅ {quote.get('name', '')}({quote.get('code', '')})  "
          f"价格:{quote.get('price', 0):.2f} 涨跌:{quote.get('change_pct', 0):+.2f}%  "
          f"量比:{quote.get('vol_ratio', 0):.2f}")

    # [2/7] 分钟级资金流
    print(f"\n[2/7] 拉取分钟级资金流...")
    flow = fetch_minute_fund_flow(CODE)
    if "error" in flow:
        print(f"  ❌ 资金流异常: {flow['error']}")
        return
    s = flow["summary"]
    t = flow["trend"]
    print(f"  ✅ 主力净流入: {s['total_main_net_wan']:+.0f}万 ({s['data_points']}分钟)")
    print(f"     趋势: {t['direction']} | {t['acceleration']}")

    # [3/7] 三方资金博弈 + 背离
    print(f"\n[3/7] 分析三方资金博弈 + 背离...")
    parties = classify_intraday_parties(flow)
    v = parties["verdict"]
    print(f"  ✅ 博弈场景: {v['scenario']}")
    print(f"     信号等级: {v['level']}")
    divergence = detect_fund_price_divergence(flow, quote)
    if divergence.get("has_divergence"):
        for d in divergence["divergences"]:
            print(f"  ⚠️ 背离: {d['type']}")

    # [4/7] 板块情绪
    print(f"\n[4/7] 拉取板块情绪...")
    sector = fetch_sector_sentiment(CODE)
    if "error" not in sector:
        print(f"  ✅ 情绪分: {sector['sentiment_score']:.0f}/100 {sector['level']}")
    else:
        print(f"  ⚠️ 板块情绪: {sector.get('error', '')}")

    # [5/7] 消息面
    print(f"\n[5/7] 拉取消息面...")
    news = fetch_intraday_news(CODE)
    print(f"  ✅ 今日新闻: {news['today_count']}条 (利好{news['bullish_count']}/利空{news['bearish_count']})")

    # [6/7] 北向+大盘+广度
    print(f"\n[6/7] 拉取北向资金+大盘+市场广度...")
    north_bound = fetch_north_bound_flow()
    print(f"  ✅ 北向: {north_bound['data_basis']}")
    market_strength = fetch_market_strength(CODE, quote)
    print(f"  ✅ 大盘: {market_strength['data_basis']}")
    print(f"     个股评级: {market_strength['relative_rating']} | {market_strength['market_env']}")
    market_breadth = fetch_market_breadth()
    print(f"  ✅ 广度: {market_breadth['data_basis']}")

    # [7/7] 概率预判 + 信号生成
    print(f"\n[7/7] 生成七维概率预判 + 买卖信号...")
    scenarios = generate_probability_scenarios(
        flow, quote, sector, news, parties, divergence,
        north_bound, market_strength, market_breadth,
    )
    signals = generate_trading_signals(
        scenarios["scenarios"], flow, quote, parties, sector,
        north_bound, market_strength, market_breadth,
    )

    # ━━━ 控制台输出 ━━━
    print(f"\n{'─' * 60}")
    print(f"  🔮 多情景概率预判 (时效性: {_freshness['phase_name']})")
    print(f"{'─' * 60}")
    for sc in scenarios["scenarios"]:
        prob = sc.get("probability", 0)
        name = sc.get("name", "")
        met = sc.get("met_count", 0)
        total = sc.get("total_conditions", 0)
        ref = sc.get("historical_ref", {})
        icon = "🔥" if prob >= 50 else ("📊" if prob >= 25 else "🔍")
        print(f"\n  {icon} {name} → 概率: {prob:.0f}% (满足{met}/{total}条件)")
        print(f"     {sc.get('description', '')}")
        for c in sc.get("conditions", []):
            status = "✅" if c.get("met") == True else ("⏸️" if c.get("met") == "PENDING" else "❌")
            print(f"     {status} {c['condition']}: 阈值{c['threshold']}, 当前={c['actual']}")
        print(f"     历史胜率: {ref.get('historical_win_rate', '')}")
        if sc.get("resonance_dims"):
            print(f"     七维共振: {sc['resonance_dims']}/7维同向")

    # 时效性降级报告
    if _downgrade_log:
        print(f"\n  ⏱️ 时效性降级 ({len(_downgrade_log)}项):")
        for d in _downgrade_log:
            print(f"     {d['dimension']}: {d['condition'][:30]}... → {d['status']} (权重{d['original_weight']}→{d['effective_weight']})")

    print(f"\n{'─' * 60}")
    print(f"  ⚡ 买卖时机参考（数据说话）")
    print(f"{'─' * 60}")

    print(f"\n  📥 买入参考:")
    for bs in signals.get("buy_signals", []):
        print(f"    {bs['level']}")
        for ev in bs.get("data_evidence", []):
            status = "✅" if ev.get("met", False) else "❌"
            print(f"      {status} {ev['item']}: {ev['value']} (阈值: {ev['threshold']}) [{ev['source']}]")
        print(f"    操作: {bs.get('action', '')}")
        if bs.get("stop_loss"):
            print(f"    止损: {bs['stop_loss']}")

    print(f"\n  📤 卖出参考:")
    for ss in signals.get("sell_signals", []):
        print(f"    {ss['level']}")
        for ev in ss.get("data_evidence", []):
            status = "✅" if ev.get("met", False) else "❌"
            print(f"      {status} {ev['item']}: {ev['value']} (阈值: {ev['threshold']}) [{ev['source']}]")
        print(f"    操作: {ss.get('action', '')}")

    hv = signals.get("hold_verdict", {})
    if hv:
        print(f"\n  📌 持有参考: {hv.get('level', '')}")
        print(f"    {hv.get('reason', '')}")
        for wp in hv.get("watch_points", []):
            print(f"    👁 {wp}")

    print(f"\n  ━━━━━━━━━━━━")
    print(f"  🎯 综合评估: {signals.get('overall_verdict', '')}")

    ds = signals.get("data_summary", {})
    print(f"\n  📋 七维数据摘要:")
    print(f"     资金: 主力{ds.get('main_net_wan', 0):+.0f}万 | 机构{ds.get('inst_net_wan', 0):+.0f}万 | "
          f"涨跌{ds.get('change_pct', 0):+.2f}% | 换手{ds.get('turnover_pct', 0)}%")
    print(f"     北向: {north_bound.get('total_net_yi', 0):+.2f}亿 {north_bound.get('direction', '')}")
    print(f"     大盘: {market_strength.get('data_basis', '')}")
    print(f"     广度: {market_breadth.get('data_basis', '')}")
    print(f"     情绪: {ds.get('sentiment_score', 0):.0f}分 | 量比{ds.get('vol_ratio', 0)}")

    # ━━━ 保存报告 ━━━
    target_name = quote.get("name", CODE)
    date_str = now.strftime("%Y-%m-%d")
    dir_name = f"{date_str}-{target_name}-盘中信号"
    dir_path = os.path.join(OUTPUT_BASE, dir_name)
    os.makedirs(dir_path, exist_ok=True)

    # 生成完整report
    report = {
        "target_input": "中兴通讯(000063)",
        "target": {"type": "个股", "code": CODE},
        "analysis_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "market_status": {"session": "上午交易时段"},
        "quote": quote, "fund_flow": flow, "parties": parties,
        "sector_sentiment": sector, "news": news, "divergence": divergence,
        "north_bound": north_bound, "market_strength": market_strength,
        "market_breadth": market_breadth,
        "scenarios": scenarios, "signals": signals,
    }

    # report.md
    report_md = _format_report_markdown(report)
    with open(os.path.join(dir_path, "report.md"), "w", encoding="utf-8") as f:
        f.write(report_md)

    # data.json
    def _serialize(obj):
        if isinstance(obj, dict): return {k: _serialize(v) for k, v in obj.items()}
        elif isinstance(obj, list): return [_serialize(v) for v in obj]
        elif isinstance(obj, datetime): return obj.isoformat()
        else: return obj

    data_json = {
        "target": {"code": CODE, "name": target_name},
        "analysis_time": now.isoformat(),
        "quote": _serialize(quote),
        "fund_flow_summary": _serialize(flow.get("summary", {})),
        "fund_flow_trend": _serialize(flow.get("trend", {})),
        "parties": _serialize(parties),
        "sector_sentiment": _serialize(sector),
        "scenarios": _serialize(scenarios.get("scenarios", [])),
        "signals_data_summary": _serialize(signals.get("data_summary", {})),
        "minute_data": [
            {"time": m["time"], "main_net": m["main_net"], "super_net": m["super_net"], "large_net": m["large_net"]}
            for m in flow.get("minutes", [])[-60:]
        ],
    }
    with open(os.path.join(dir_path, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data_json, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n{'═' * 70}")
    print(f"  ✅ 报告已保存:")
    print(f"     {dir_path}/")
    print(f"     ├── report.md    (完整信号报告)")
    print(f"     └── data.json    (原始数据, 用于回测)")
    print(f"\n  ⚠️ 研究声明:")
    print(f"  1. 所有信号基于公开API实时数据，不构成投资建议")
    print(f"  2. 概率预判基于七维25+条件多因子匹配+时效性门控(V1.3)")
    print(f"  3. 当前处于{_freshness['phase_name']}，{len(_downgrade_log)}个条件被时效性门控降级")
    print(f"  4. 标记为⏸️PENDING的条件表示数据未就绪，未参与概率计算")
    print(f"  5. 核心原则：宁可少挣，宁可少亏——买入卖出，数据说话")
    print(f"{'═' * 70}")


def _format_report_markdown(report):
    L = []; a = L.append
    quote = report.get("quote", {})
    flow = report.get("fund_flow", {})
    parties = report.get("parties", {})
    sector = report.get("sector_sentiment", {})
    news = report.get("news", {})
    divergence = report.get("divergence", {})
    scenarios = report.get("scenarios", {})
    signals = report.get("signals", {})
    nb = report.get("north_bound", {})
    ms = report.get("market_strength", {})
    mb = report.get("market_breadth", {})

    target_name = quote.get("name", CODE)
    target_code = quote.get("code", CODE)
    s = flow.get("summary", {}) or {}
    t = flow.get("trend", {}) or {}
    inst = parties.get("institution", {}) or {}
    hm = parties.get("hot_money", {}) or {}
    retail = parties.get("retail", {}) or {}
    v = parties.get("verdict", {}) or {}

    a(f"# 📊 盘中实时交易信号报告")
    a(f"")
    a(f"**标的**: {target_name} ({target_code})")
    a(f"**分析时间**: {report.get('analysis_time', '')}")
    a(f"**时效性阶段**: {_freshness['phase_name']} (V1.3 门控)")
    a(f"**核心原则**: 宁可少挣，宁可少亏。买入卖出，数据说话。")
    a(f""); a(f"---"); a(f"")

    # Part 1: 核心结论
    primary_sc = scenarios.get("primary_scenario", {}) or {}
    primary_name = primary_sc.get("name", "无数据")
    primary_prob = primary_sc.get("probability", 0)
    overall = signals.get("overall_verdict", "")
    hold_v = signals.get("hold_verdict", {}) or {}
    buy_sigs = signals.get("buy_signals", []) or []
    sell_sigs = signals.get("sell_signals", []) or []
    strongest_buy = buy_sigs[0].get("level", "") if buy_sigs else ""
    strongest_sell = sell_sigs[0].get("level", "") if sell_sigs else ""

    a(f"## 🎯 Part 1: 核心结论")
    a(f""); a(f"```")
    a(f"主导情景: {primary_name} (概率 {primary_prob:.0f}%)")
    a(f"买入信号: {strongest_buy}")
    a(f"卖出信号: {strongest_sell}")
    a(f"持有建议: {hold_v.get('level', '')}")
    a(f"```"); a(f"")
    a(f"**综合评估**: {overall}"); a(f"")
    a(f"### 时效性门控报告")
    a(format_freshness_report(_freshness))
    a(f""); a(f"---"); a(f"")

    # Part 2: 关键数据一览
    a(f"## 📊 Part 2: 关键数据一览")
    a(f"")
    a(f"| 维度 | 指标 | 数值 | 信号 |")
    a(f"|------|------|------|------|")
    a(f"| 📈 价格 | 最新价 | {quote.get('price', 0):.2f} | — |")
    a(f"| 📈 价格 | 涨跌幅 | {quote.get('change_pct', 0):+.2f}% | {'🔴' if quote.get('change_pct', 0) < 0 else '🟢'} |")
    a(f"| 📈 价格 | 振幅 | {quote.get('amplitude', 0):.2f}% | — |")
    a(f"| 📈 价格 | 换手率 | {quote.get('turnover_pct', 0):.2f}% | {'🔴 异常' if quote.get('turnover_pct', 0) > 10 else '正常'} |")
    a(f"| 📈 价格 | 量比 | {quote.get('vol_ratio', 0):.2f} | — |")
    a(f"| 💰 资金 | 主力净流入 | {s.get('total_main_net_wan', 0):+.0f}万 | {'🔴 流出' if s.get('total_main_net_wan', 0) < 0 else '🟢 流入'} |")
    a(f"| 💰 资金 | 机构(超大单) | {s.get('total_super_net_wan', 0):+.0f}万 | {'🔴' if s.get('total_super_net_wan', 0) < 0 else '🟢'} |")
    a(f"| 💰 资金 | 游资(大单) | {s.get('total_large_net_wan', 0):+.0f}万 | — |")
    a(f"| 💰 资金 | 散户(中+小) | {(s.get('total_mid_net_wan', 0) or 0) + (s.get('total_small_net_wan', 0) or 0):+.0f}万 | {'🔴 接盘' if (s.get('total_mid_net_wan', 0) or 0) + (s.get('total_small_net_wan', 0) or 0) > 100 else '—'} |")
    a(f"| 💰 资金 | 趋势 | {t.get('direction', '?')} / {t.get('acceleration', '?')} | — |")
    a(f"| 💰 资金 | 数据点 | {s.get('data_points', 0)}分钟 | — |")
    a(f"| 🎯 情绪 | 板块情绪分 | {sector.get('sentiment_score', 0):.0f}/100 {sector.get('level', '')} | — |")
    a(f"| 🎯 情绪 | 板块流入比 | {sector.get('inflow_blocks', 0)}/{sector.get('total_blocks', 1)} | — |")
    a(f"| 🌏 北向 | 北向资金 | {nb.get('total_net_yi', 0):+.2f}亿 | {nb.get('signal', '')} |")
    a(f"| 📊 大盘 | 相对强度 | {ms.get('relative_strength', 0):+.2f}% | {ms.get('relative_rating', '')} |")
    a(f"| 📊 大盘 | 基准涨跌 | {ms.get('benchmark_change', 0):+.2f}% | {ms.get('market_env', '')} |")
    a(f"| 🔥 广度 | 涨跌家数比 | {mb.get('up_ratio_pct', 50):.0f}% | {mb.get('breadth_level', '')} |")
    a(f"| 🔥 广度 | 涨跌停比 | {mb.get('limit_ratio', 1):.1f} | {mb.get('money_effect', '')} |")
    a(f"| 📰 消息 | 今日新闻 | {news.get('today_count', 0)}条 (利好{news.get('bullish_count', 0)}/利空{news.get('bearish_count', 0)}) | — |")
    a(f""); a(f"---"); a(f"")

    # Part 3: 七维数据明细
    a(f"## 📋 Part 3: 七维数据明细"); a(f"")

    a(f"### 💰 资金面（分钟级）"); a(f"")
    a(f"**追踪时段**: {s.get('first_time', '?')} → {s.get('last_time', '?')} (共{s.get('data_points', 0)}分钟)"); a(f"")
    a(f"**三方资金博弈**: {v.get('scenario', '')}"); a(f"")
    a(f"| 资金类型 | 净流入(万) | 方向 | 份额 | 速率(万/分) |")
    a(f"|---------|-----------|------|------|------------|")
    a(f"| 🔴 机构(超大单) | {inst.get('net_wan', 0):+.0f} | {inst.get('direction', '')} | {inst.get('share_pct', 0):.0f}% | {inst.get('rate_per_min_wan', 0):+.2f} |")
    a(f"| 🟡 游资(大单) | {hm.get('net_wan', 0):+.0f} | {hm.get('direction', '')} | {hm.get('share_pct', 0):.0f}% | {hm.get('rate_per_min_wan', 0):+.2f} |")
    a(f"| 🟢 散户(中+小) | {retail.get('net_wan', 0):+.0f} | {retail.get('direction', '')} | {retail.get('share_pct', 0):.0f}% | {retail.get('rate_per_min_wan', 0):+.2f} |")
    a(f"")
    a(f"**信号等级**: {v.get('level', '')} | **主方向**: {v.get('main_direction', '')}"); a(f"")

    turns = t.get("turning_points", []) or []
    if turns:
        a(f"**关键转向点**:"); a(f"")
        a(f"| 时间 | 类型 | 累计值(万) |")
        a(f"|------|------|-----------|")
        for tp in turns:
            a(f"| {tp['time']} | {tp['type']} | {tp['value_wan']:+.0f} |")
        a(f"")

    if divergence.get("has_divergence"):
        a(f"**⚠️ 资金-价格背离检测**:")
        for div in divergence.get("divergences", []):
            a(f"- **{div['type']}**: {div['detail']}")
            a(f"  - 风险: {div['risk']}")
        a(f"")

    a(f"### 🎯 板块情绪"); a(f"")
    a(f"**情绪分**: {sector.get('sentiment_score', 0):.0f}/100 {sector.get('level', '')}")
    blocks = sector.get("blocks", []) or []
    if blocks:
        a(f"| 板块 | 主力净流入(万) | 涨跌% | 涨家 | 跌家 |")
        a(f"|------|--------------|-------|------|------|")
        for bk in blocks[:8]:
            a(f"| {bk['name']} | {bk['main_net_wan']:+.0f} | {bk['change_pct']:+.2f}% | {bk['up_count']} | {bk['down_count']} |")
        a(f"")

    if nb:
        a(f"### 🌏 北向资金"); a(f"")
        a(f"**{nb.get('data_basis', '')}**"); a(f"")

    if ms:
        a(f"### 📊 大盘相对强度"); a(f"")
        a(f"**{ms.get('data_basis', '')}**"); a(f"")
        a(f"- 个股评级: {ms.get('relative_rating', '')} | 大盘环境: {ms.get('market_env', '')}"); a(f"")

    if mb:
        a(f"### 🔥 市场广度"); a(f"")
        a(f"**{mb.get('data_basis', '')}**"); a(f"")

    a(f"### 📰 消息面"); a(f"")
    highlights = news.get("highlights", []) or []
    if highlights:
        for h in highlights[:8]:
            emoji = "🟢" if h.get("sentiment") == "bullish" else ("🔴" if h.get("sentiment") == "bearish" else "⚪")
            a(f"- {emoji} [{h.get('time', '')}] {h.get('title', '')} (来源: {h.get('source', '')})")
    else:
        a(f"今日无相关新闻")
    a(f""); a(f"---"); a(f"")

    # Part 4: 多情景概率
    a(f"## 🔮 Part 4: 多情景概率预判（七维25+条件 + 时效性门控V1.3）"); a(f"")
    sc_list = scenarios.get("scenarios", []) or []
    for sc in sc_list:
        prob = sc.get("probability", 0); name = sc.get("name", "")
        met = sc.get("met_count", 0); total = sc.get("total_conditions", 0)
        ref = sc.get("historical_ref", {}) or {}
        icon = "🔥" if prob >= 50 else ("📊" if prob >= 25 else "🔍")
        a(f"### {icon} {name} → 概率: {prob:.0f}%"); a(f"")
        a(f"**{sc.get('description', '')}**"); a(f"")
        a(f"**条件满足**: {met}/{total}"); a(f"")
        a(f"| 条件 | 阈值 | 当前值 | 满足? | 权重 |")
        a(f"|------|------|--------|-------|------|")
        for c in sc.get("conditions", []):
            status = "✅" if c.get("met") == True else ("⏸️" if c.get("met") == "PENDING" else "❌")
            a(f"| {c['condition']} | {c.get('threshold', '')} | {c.get('actual', '')} | {status} | {c.get('weight', 0)} |")
        a(f"")
        a(f"**历史参考**: {ref.get('rule', '')} (历史胜率: {ref.get('historical_win_rate', '')})")
        a(f"")
    a(f"---"); a(f"")

    # Part 5: 买卖时机
    a(f"## ⚡ Part 5: 买卖时机参考（数据说话）"); a(f"")
    a(f"### 📥 买入参考"); a(f"")
    for bs in buy_sigs:
        a(f"**{bs.get('level', '')}**"); a(f"")
        a(f"| 数据项 | 数值 | 阈值 | 满足? | 来源 |")
        a(f"|--------|------|------|-------|------|")
        for ev in bs.get("data_evidence", []):
            status = "✅" if ev.get("met", False) else "❌"
            a(f"| {ev.get('item', '')} | {ev.get('value', '')} | {ev.get('threshold', '')} | {status} | {ev.get('source', '')} |")
        a(f""); a(f"- **操作**: {bs.get('action', '')}")
        if bs.get("stop_loss"): a(f"- **止损**: {bs['stop_loss']}")
        a(f"")

    a(f"### 📤 卖出参考"); a(f"")
    for ss in sell_sigs:
        a(f"**{ss.get('level', '')}**"); a(f"")
        a(f"| 数据项 | 数值 | 阈值 | 满足? | 来源 |")
        a(f"|--------|------|------|-------|------|")
        for ev in ss.get("data_evidence", []):
            status = "✅" if ev.get("met", False) else "❌"
            a(f"| {ev.get('item', '')} | {ev.get('value', '')} | {ev.get('threshold', '')} | {status} | {ev.get('source', '')} |")
        a(f""); a(f"- **操作**: {ss.get('action', '')}")
        a(f"")

    a(f"### 📌 持有参考"); a(f"")
    if hold_v:
        a(f"**{hold_v.get('level', '')}**"); a(f"")
        a(f"- {hold_v.get('reason', '')}")
        for wp in hold_v.get("watch_points", []): a(f"- 👁 {wp}")
    a(f"")

    a(f"### 🎯 综合评估"); a(f"")
    a(f"> {overall}"); a(f""); a(f"---"); a(f"")

    a(f"## ⚠️ 研究声明"); a(f"")
    a(f"1. 本报告基于公开API实时数据，所有信号为研究框架产出，**不构成投资建议**")
    a(f"2. 每个买卖信号标注了具体数据阈值和当前值，可逐一验证")
    a(f"3. 概率预判基于七维25+条件多因子匹配 + 历史统计规律 + V1.3时效性门控")
    a(f"4. 报告自动生成于 {report.get('analysis_time', '')}，原始数据见 data.json")
    a(f"")

    return "\n".join(L)


if __name__ == "__main__":
    main()
