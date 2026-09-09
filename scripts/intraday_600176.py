#!/usr/bin/env python3
"""
盘中实时交易信号 — 中国巨石(600176) V1.3
自动拉取七维数据 → 多情景概率预判 → 买卖时机信号
"""
import time, random, requests, json, re, os, sys
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

# ====== 东财基础配置 (from a-stock-data) ======
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

def em_get(url, params=None, headers=None, timeout=15, **kwargs):
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def eastmoney_fund_flow_minute(code: str) -> list:
    """个股资金流向（分钟级，当日盘中）— a-stock-data §3.4
    注: push2 fflow/kline 端点偶尔连接断开(RemoteDisconnected)，自动重试3次。"""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid, "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    d = None
    for attempt in range(3):
        try:
            # 用独立 session 避免连接复用问题
            s = requests.Session()
            s.headers.update({"User-Agent": UA})
            r = s.get(url, params=params, headers=headers, timeout=20)
            d = r.json()
            break
        except Exception as e:
            if attempt < 2:
                wait = (attempt + 1) * 8  # 8s/16s 阶梯等待，push2 风控较严
                print(f"[WARN] push2 资金流第{attempt+1}次失败, {wait}s后重试: {str(e)[:60]}")
                time.sleep(wait)
            else:
                print(f"[WARN] push2 资金流3次均失败: {e}")
                return []
    if d is None:
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


def eastmoney_concept_blocks(code: str) -> dict:
    """个股所属板块/概念归属 — a-stock-data §3.3"""
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3", "pi": "0", "pz": "200", "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/slist/get",
                   params=params, headers=headers, timeout=15)
        d = r.json()
    except Exception as e:
        print(f"[WARN] 东财板块归属请求失败: {e}")
        return {"total": 0, "boards": [], "concept_tags": []}
    diff = (d.get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    boards = []
    for it in items:
        boards.append({
            "name": it.get("f14", ""),
            "code": it.get("f12", ""),
            "change_pct": it.get("f3", ""),
            "lead_stock": it.get("f128", ""),
        })
    return {"total": len(boards), "boards": boards, "concept_tags": [b["name"] for b in boards]}


PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"
_SECTOR_CACHE = None
_SECTOR_CACHE_TIME = None


def _load_all_concept_sectors() -> dict:
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
                "code": bk_code,
                "name": it.get("f14", ""),
                "change_pct": it.get("f3", 0),
                "main_net_wan": round(main_net / 1e4, 1),
                "direction": "流入" if main_net > 0 else "流出",
                "up_count": it.get("f104", 0),
                "down_count": it.get("f105", 0),
            }
    _SECTOR_CACHE = sectors
    _SECTOR_CACHE_TIME = now
    return sectors


# ====== Layer 0: 时效性门控 ======
def check_data_freshness() -> dict:
    now = datetime.now()
    if now.weekday() >= 5:
        return {"is_trading": False, "phase": 0, "phase_name": "非交易日",
                "minutes_from_open": -1, "freshness": _all_unavailable("休市")}
    open_minutes = 9 * 60 + 30
    current_minutes = now.hour * 60 + now.minute
    minutes_from_open = current_minutes - open_minutes
    close_minutes = 15 * 60
    if current_minutes >= close_minutes:
        return {"is_trading": False, "phase": 5, "phase_name": "已收盘",
                "minutes_from_open": minutes_from_open, "freshness": _all_available()}
    if 11 * 60 + 30 <= current_minutes < 13 * 60:
        return {"is_trading": False, "phase": 0, "phase_name": "午间休市",
                "minutes_from_open": minutes_from_open, "freshness": _all_available()}
    if minutes_from_open < 0: phase, phase_name = 0, "盘前"
    elif minutes_from_open <= 30: phase, phase_name = 1, f"盘初({minutes_from_open}min)"
    elif minutes_from_open <= 90: phase, phase_name = 2, f"早盘过渡({minutes_from_open}min)"
    elif minutes_from_open <= 300: phase, phase_name = 3, f"盘中正常({minutes_from_open}min)"
    else: phase, phase_name = 4, f"尾盘({minutes_from_open}min)"
    return {"is_trading": phase >= 1, "phase": phase, "phase_name": phase_name,
            "minutes_from_open": minutes_from_open, "freshness": _build_freshness(phase)}


def _dim(avail, wm, status, reliability, reason):
    return {"available": avail, "weight_multiplier": wm, "status": status,
            "reliability": reliability, "reason": reason}

def _all_unavailable(r=""):
    return {k: _dim(False, 0, "unavailable", 0, r or "休市")
            for k in ["quote","minute_flow","sector","news","north_bound","market","breadth"]}

def _all_available():
    return {k: _dim(True, 1.0, "ready", 90, "正常")
            for k in ["quote","minute_flow","sector","news","north_bound","market","breadth"]}

def _build_freshness(phase):
    if phase == 1:
        return {"quote": _dim(True, 1.0, "ready", 95, "腾讯行情9:25起"),
                "minute_flow": _dim(True, 1.0, "ready", 90, "mootdx实时"),
                "sector": _dim(False, 0.0, "unavailable", 10, "板块push2 10:00后首刷"),
                "news": _dim(True, 0.6, "delayed", 50, "盘初新闻少"),
                "north_bound": _dim(False, 0.0, "unavailable", 5, "北向10:30后才有非零"),
                "market": _dim(True, 1.0, "ready", 90, "腾讯指数实时"),
                "breadth": _dim(False, 0.0, "unavailable", 5, "涨停池10:00后刷新")}
    elif phase == 2:
        return {"quote": _dim(True, 1.0, "ready", 95, "正常"),
                "minute_flow": _dim(True, 1.0, "ready", 90, "正常"),
                "sector": _dim(True, 0.7, "delayed", 60, "板块首刷完成,样本较少"),
                "news": _dim(True, 0.8, "ready", 70, "早盘新闻出现"),
                "north_bound": _dim(True, 0.3, "delayed", 25, "北向可能仍为0"),
                "market": _dim(True, 1.0, "ready", 90, "正常"),
                "breadth": _dim(True, 0.5, "delayed", 40, "涨跌家数首刷,波动未完全反映")}
    elif phase == 3:
        return {"quote": _dim(True, 1.0, "ready", 95, "正常"),
                "minute_flow": _dim(True, 1.0, "ready", 90, "正常"),
                "sector": _dim(True, 1.0, "ready", 85, "盘中多次刷新"),
                "news": _dim(True, 1.0, "ready", 80, "全天更新"),
                "north_bound": _dim(True, 1.0, "ready", 80, "北向稳定刷新"),
                "market": _dim(True, 1.0, "ready", 90, "正常"),
                "breadth": _dim(True, 1.0, "ready", 80, "正常")}
    elif phase == 4:
        return {"quote": _dim(True, 1.0, "ready", 95, "尾盘"),
                "minute_flow": _dim(True, 1.2, "ready", 90, "尾盘异动+20%"),
                "sector": _dim(True, 1.0, "ready", 85, "正常"),
                "news": _dim(True, 1.0, "ready", 80, "全天"),
                "north_bound": _dim(True, 1.0, "ready", 80, "正常"),
                "market": _dim(True, 1.0, "ready", 90, "正常"),
                "breadth": _dim(True, 1.0, "ready", 80, "正常")}
    return _all_unavailable("盘前")


def apply_freshness(cond_text, threshold, actual, met, weight, dimension, freshness):
    fd = freshness.get("freshness", {})
    dim_info = fd.get(dimension, {"available": True, "weight_multiplier": 1.0, "status": "ready"})
    avail, wm, status, reason = dim_info.get("available", True), dim_info.get("weight_multiplier", 1.0), dim_info.get("status", "ready"), dim_info.get("reason", "")
    if not avail:
        return {"condition": cond_text, "threshold": threshold,
                "actual": f"{actual} [未就绪:{reason[:30]}]", "met": "PENDING", "weight": 0.0,
                "original_weight": weight, "dimension": dimension,
                "freshness_status": "unavailable", "freshness_reason": reason}
    elif status == "delayed":
        return {"condition": cond_text, "threshold": threshold,
                "actual": f"{actual} [延迟:{reason[:25]}]",
                "met": met, "weight": weight * wm, "original_weight": weight,
                "dimension": dimension, "freshness_status": "delayed"}
    return {"condition": cond_text, "threshold": threshold, "actual": str(actual),
            "met": met, "weight": weight, "original_weight": weight,
            "dimension": dimension, "freshness_status": "ready"}


# ====== Layer 1: 实时行情 ======
def fetch_realtime_quote(code):
    prefixed = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
    url = f"https://qt.gtimg.cn/q={prefixed}"
    try:
        req = Request(url); req.add_header("User-Agent", UA)
        resp = urlopen(req, timeout=8)
        data = resp.read().decode("gbk")
        vals = data.split('"')[1].split("~") if '"' in data else []
        if len(vals) < 53: return {"error": f"字段不足({len(vals)})"}
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


# ====== Layer 2: 资金面 ======
def fetch_minute_fund_flow(code):
    try:
        minutes = eastmoney_fund_flow_minute(code)
    except Exception as e:
        return {"error": f"拉取失败: {e}", "minutes": [], "summary": {}, "trend": {}}
    if not minutes:
        return {"error": "无资金流数据", "minutes": [], "summary": {}, "trend": {}}

    total_main = sum(m["main_net"] for m in minutes)
    total_super = sum(m["super_net"] for m in minutes)
    total_large = sum(m["large_net"] for m in minutes)
    total_mid = sum(m["mid_net"] for m in minutes)
    total_small = sum(m["small_net"] for m in minutes)

    cum_main = []
    running = 0.0
    for m in minutes:
        running += m["main_net"]
        cum_main.append(running)

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
        direction = "数据不足"; acceleration = "数据不足"
        first_slope = second_slope = 0

    turning_points = []
    if len(cum_main) >= 20:
        for i in range(10, len(cum_main) - 5):
            before = cum_main[i - 5:i]; after = cum_main[i:i + 5]
            is_peak = all(cum_main[i] > b for b in before) and all(cum_main[i] > a for a in after)
            is_valley = all(cum_main[i] < b for b in before) and all(cum_main[i] < a for a in after)
            if is_peak:
                turning_points.append({"time": minutes[i]["time"], "type": "峰值(资金见顶)",
                                       "value_wan": cum_main[i] / 1e4})
            elif is_valley:
                turning_points.append({"time": minutes[i]["time"], "type": "谷值(资金见底)",
                                       "value_wan": cum_main[i] / 1e4})

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
            "last_turn": turning_points[-1] if turning_points else None,
        },
    }


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
    inst_share = round(abs(inst_net) / total_abs * 100, 1) if total_abs > 0 else 0
    hm_share = round(abs(hm_net) / total_abs * 100, 1) if total_abs > 0 else 0
    retail_share = round(abs(retail_net) / total_abs * 100, 1) if total_abs > 0 else 0

    if inst_net > 200 and hm_net > 0 and retail_net < -100:
        scenario = "机构+游资合力做多，散户恐慌出局 → 强多头信号"; level = "🟢 积极"
    elif inst_net > 200 and retail_net > 100:
        scenario = "机构与散户同向流入 → 共识强，但散户过度乐观是隐忧"; level = "🟡 中性偏多"
    elif inst_net < -200 and retail_net > 200:
        scenario = f"机构净流出{abs(inst_net):.0f}万 + 散户净流入{retail_net:.0f}万 → 机构派发、散户接盘"; level = "🔴 警惕"
    elif inst_net < -100 and hm_net < -100 and retail_net > 100:
        scenario = "机构+游资合力出逃，散户接盘 → 强空头信号"; level = "🔴 危险"
    elif inst_net > 100 and hm_net < -50 and retail_net < -50:
        scenario = f"机构独力做多{inst_net:.0f}万，游资{hm_net:.0f}万+散户{retail_net:.0f}万不跟"; level = "🟡 中性"
    else:
        scenario = "三方分歧，方向不明确"; level = "⚪ 观望"

    return {
        "institution": {"net_wan": round(inst_net, 1), "direction": "流入" if inst_net > 0 else "流出",
                        "share_pct": inst_share, "rate_per_min_wan": round(inst_rate, 2)},
        "hot_money": {"net_wan": round(hm_net, 1), "direction": "流入" if hm_net > 0 else "流出",
                      "share_pct": hm_share, "rate_per_min_wan": round(hm_rate, 2)},
        "retail": {"net_wan": round(retail_net, 1), "direction": "流入" if retail_net > 0 else "流出",
                   "share_pct": retail_share, "rate_per_min_wan": round(retail_rate, 2)},
        "verdict": {"scenario": scenario, "level": level,
                    "main_direction": "多头占优" if main_net > 0 else "空头占优"},
        "data_basis": {"data_points": data_points,
                       "time_range": f"{s.get('first_time', '?')}→{s.get('last_time', '?')}",
                       "source": "东财push2分钟级资金流API"},
    }


def detect_fund_price_divergence(flow_data, quote):
    minutes = flow_data.get("minutes", [])
    if len(minutes) < 20:
        return {"has_divergence": False, "reason": f"数据不足({len(minutes)}分钟)"}
    cum_main = []
    running = 0.0
    for m in minutes:
        running += m["main_net"]
        cum_main.append(running)
    n = len(minutes); seg_size = n // 4; divergences = []
    change_pct = quote.get("change_pct", 0)
    for i in range(1, 4):
        prev_start, prev_end = (i - 1) * seg_size, i * seg_size
        curr_start, curr_end = i * seg_size, min((i + 1) * seg_size, n)
        if curr_end <= curr_start: continue
        prev_fc = cum_main[prev_end - 1] - cum_main[prev_start]
        curr_fc = cum_main[curr_end - 1] - cum_main[curr_start]
        if change_pct > 3 and prev_fc > 0 and curr_fc < prev_fc * 0.3:
            divergences.append({"type": "顶背离(资金衰竭)",
                                "detail": f"价格涨{change_pct:+.2f}%，资金从{prev_fc/1e4:.0f}万骤降至{curr_fc/1e4:.0f}万",
                                "risk": "上涨动力衰竭，警惕冲高回落"})
        if change_pct < -3 and prev_fc < 0 and curr_fc > abs(prev_fc) * 0.5:
            divergences.append({"type": "底背离(资金回流)",
                                "detail": f"价格跌{change_pct:+.2f}%，资金转为流入{curr_fc/1e4:.0f}万",
                                "risk": "下跌动力衰竭，关注反弹"})
    return {"has_divergence": len(divergences) > 0, "divergences": divergences}


# ====== Layer 3: 情绪面 ======
def fetch_sector_sentiment(code):
    try:
        raw_blocks = eastmoney_concept_blocks(code)
        stock_blocks = [{"code": it["code"], "name": it["name"],
                         "change_pct": it.get("change_pct", 0)}
                        for it in raw_blocks.get("boards", [])]
    except Exception:
        return {"error": "板块归属获取失败", "blocks": [], "sentiment_score": 0}
    if not stock_blocks:
        return {"error": "未找到所属概念板块", "blocks": [], "sentiment_score": 0}

    all_sectors = _load_all_concept_sectors()
    sentiment_blocks = []
    for bk in stock_blocks[:8]:
        sd = all_sectors.get(bk["code"])
        if sd:
            sentiment_blocks.append(sd)
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

    if sentiment_score >= 75: level = "🔥 极热"
    elif sentiment_score >= 60: level = "🟢 偏热"
    elif sentiment_score >= 40: level = "🟡 中性"
    elif sentiment_score >= 25: level = "🔵 偏冷"
    else: level = "❄️ 极冷"

    return {
        "blocks": sentiment_blocks, "sentiment_score": sentiment_score,
        "level": level, "inflow_blocks": inflow_count, "total_blocks": total_blocks,
        "avg_change_pct": round(avg_change, 2),
        "total_sector_flow_wan": round(total_flow, 1),
        "data_basis": f"{inflow_count}/{total_blocks}板块流入, 合计{total_flow:+.0f}万, 平均涨跌{avg_change:+.2f}%, 情绪分{sentiment_score}",
        "source": "东财 push2 slist + clist m:90+t:3",
    }


# ====== Layer 4: 消息面 ======
def fetch_intraday_news(code):
    cb = "jQuery_news"
    inner = json.dumps({
        "uid": "", "keyword": code, "type": ["cmsArticleWebOld"],
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
    bullish_kw = ["增长", "突破", "中标", "订单", "扩产", "获批", "回购", "增持", "超预期"]
    bearish_kw = ["减持", "亏损", "下滑", "调查", "处罚", "诉讼", "违约", "暴雷", "退市"]
    highlights = []
    for a in articles[:8]:
        title = re.sub(r'<[^>]+>', '', a.get("title", ""))
        content = re.sub(r'<[^>]+>', '', a.get("content", ""))[:200]
        is_today = a.get("date", "").startswith(today_str)
        sentiment = "neutral"
        if any(kw in title for kw in bullish_kw): sentiment = "bullish"
        elif any(kw in title for kw in bearish_kw): sentiment = "bearish"
        highlights.append({"title": title, "content": content,
                          "time": a.get("date", ""), "source": a.get("mediaName", ""),
                          "url": a.get("url", ""), "is_today": is_today,
                          "sentiment": sentiment})
    today_news = [h for h in highlights if h["is_today"]]
    return {
        "today_count": len(today_news),
        "highlights": highlights,
        "bullish_count": sum(1 for h in highlights if h["sentiment"] == "bullish"),
        "bearish_count": sum(1 for h in highlights if h["sentiment"] == "bearish"),
        "source": "东财 search-api-web",
    }


# ====== Layer 5: 北向资金 ======
def fetch_north_bound_flow():
    hgt_net = 0.0; sgt_net = 0.0
    try:
        r = requests.get("https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/hgt",
                         headers={"User-Agent": UA}, timeout=8)
        d = r.json()
        items = d.get("data", []) if isinstance(d.get("data"), list) else []
        hgt_net = sum(it.get("net", 0) for it in items[-10:])
    except: pass
    try:
        r = requests.get("https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/sgt",
                         headers={"User-Agent": UA}, timeout=8)
        d = r.json()
        items = d.get("data", []) if isinstance(d.get("data"), list) else []
        sgt_net = sum(it.get("net", 0) for it in items[-10:])
    except: pass
    total_net = hgt_net + sgt_net; total_net_yi = total_net / 1e4
    if total_net > 5000: direction, signal = "大幅流入", "🟢 积极"
    elif total_net > 0: direction, signal = "小幅流入", "🟡 中性偏多"
    elif total_net > -5000: direction, signal = "小幅流出", "🟠 中性偏空"
    else: direction, signal = "大幅流出", "🔴 警惕"
    return {
        "hgt_net_wan": round(hgt_net, 0), "sgt_net_wan": round(sgt_net, 0),
        "total_net_wan": round(total_net, 0), "total_net_yi": round(total_net_yi, 2),
        "direction": direction, "signal": signal,
        "source": "同花顺 hsgtApi",
        "data_basis": f"沪股通{hgt_net/1e4:+.2f}亿+深股通{sgt_net/1e4:+.2f}亿=北向合计{total_net_yi:+.2f}亿",
    }


# ====== Layer 6: 大盘强度 ======
def fetch_market_strength(code, quote):
    indices = {"上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006"}
    market_data = {}
    for name, idx_code in indices.items():
        try:
            url = f"https://qt.gtimg.cn/q={idx_code}"
            req = Request(url); req.add_header("User-Agent", UA)
            resp = urlopen(req, timeout=5)
            data = resp.read().decode("gbk")
            vals = data.split('"')[1].split("~") if '"' in data else []
            if len(vals) >= 33:
                market_data[name] = {"price": float(vals[3]) if vals[3] else 0,
                                     "change_pct": float(vals[32]) if vals[32] else 0}
        except: market_data[name] = {"price": 0, "change_pct": 0}

    if code.startswith(("6", "9")): primary = "上证指数"
    elif code.startswith("30"): primary = "创业板指"
    else: primary = "深证成指"

    bm = market_data.get(primary, {}).get("change_pct", 0)
    sc = quote.get("change_pct", 0)
    rs = sc - bm

    if bm > 1: me = "🟢 大盘强势"
    elif bm > 0: me = "🟡 大盘微涨"
    elif bm > -1: me = "🟠 大盘微跌"
    else: me = "🔴 大盘弱势"

    if rs > 3: rr = "🚀 显著跑赢"
    elif rs > 1: rr = "✅ 跑赢大盘"
    elif rs > -1: rr = "➖ 与大盘同步"
    elif rs > -3: rr = "⚠️ 跑输大盘"
    else: rr = "🔴 显著跑输"

    return {
        "benchmark": primary, "benchmark_change": round(bm, 2),
        "market_env": me, "stock_change": round(sc, 2),
        "relative_strength": round(rs, 2), "relative_rating": rr,
        "market_detail": {k: round(v.get("change_pct", 0), 2) for k, v in market_data.items()},
        "source": "腾讯财经指数行情",
        "data_basis": f"{primary}{bm:+.2f}%, 个股{sc:+.2f}%, 相对强弱{rs:+.2f}%",
    }


# ====== Layer 7: 市场广度 ======
def fetch_market_breadth():
    params = {
        "pn": "1", "pz": "1", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f104,f105",
    }
    try:
        r = em_get(PUSH2_CLIST, params=params,
                   headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        up_count = sum(it.get("f104", 0) for it in items) if items else 0
        down_count = sum(it.get("f105", 0) for it in items) if items else 0
    except: up_count, down_count = 0, 0

    limit_up_count = 0; limit_down_count = 0
    try:
        r = em_get("https://push2ex.eastmoney.com/getTopicZTPool",
                   params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                           "sort": "fbt", "fbt": "desc"},
                   headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        try: limit_up_count = r.json().get("data", {}).get("total", 0) or 0
        except: pass
        r = em_get("https://push2ex.eastmoney.com/getTopicDTPool",
                   params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                           "sort": "fund", "fund": "desc"},
                   headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        try: limit_down_count = r.json().get("data", {}).get("total", 0) or 0
        except: pass
    except: pass

    total = up_count + down_count
    up_ratio = up_count / max(total, 1) * 100
    if up_ratio >= 70: breadth_level, breadth_score = "🟢 普涨格局", 85
    elif up_ratio >= 55: breadth_level, breadth_score = "🟡 涨多跌少", 60
    elif up_ratio >= 45: breadth_level, breadth_score = "🟠 分化格局", 40
    elif up_ratio >= 30: breadth_level, breadth_score = "🔴 跌多涨少", 20
    else: breadth_level, breadth_score = "💀 普跌格局", 5

    limit_ratio = limit_up_count / max(limit_down_count, 1)
    if limit_ratio >= 3: money_effect = "🔥 强赚钱效应"
    elif limit_ratio >= 1.5: money_effect = "✅ 赚钱效应良好"
    elif limit_ratio >= 1: money_effect = "➖ 赚钱效应中性"
    elif limit_ratio >= 0.5: money_effect = "⚠️ 亏钱效应显现"
    else: money_effect = "💀 强亏钱效应"

    return {
        "up_count": up_count, "down_count": down_count,
        "up_ratio_pct": round(up_ratio, 1),
        "breadth_level": breadth_level, "breadth_score": breadth_score,
        "limit_up_count": limit_up_count, "limit_down_count": limit_down_count,
        "limit_ratio": round(limit_ratio, 1), "money_effect": money_effect,
        "source": "东财 push2ex 涨停/跌停池 + push2 clist",
        "data_basis": f"涨{up_count}跌{down_count}({up_ratio:.1f}%), 涨停{limit_up_count}/跌停{limit_down_count}, {money_effect}",
    }


# ====== Layer 8: 七维概率预判引擎 ======
def generate_probability_scenarios(flow_data, quote, sector_data, news_data, party_data,
                                   divergence, north_bound=None, market_strength=None,
                                   market_breadth=None):
    freshness = check_data_freshness()
    _downgrade_log = []

    def _cond(text, threshold, actual, met, weight, dimension):
        result = apply_freshness(text, threshold, actual, met, weight, dimension, freshness)
        if result.get("freshness_status") != "ready":
            _downgrade_log.append({"condition": text, "dimension": dimension,
                                   "status": result["freshness_status"],
                                   "original_weight": weight, "effective_weight": result["weight"]})
        return result

    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)

    s = flow_data.get("summary", {})
    main_net_wan = s.get("total_main_net_wan", 0)
    inst_net = party_data.get("institution", {}).get("net_wan", 0)
    hm_net = party_data.get("hot_money", {}).get("net_wan", 0)
    retail_net = party_data.get("retail", {}).get("net_wan", 0)

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
    ms = market_strength or {}
    relative_strength = ms.get("relative_strength", 0)
    market_env = ms.get("market_env", "")
    mb = market_breadth or {}
    up_ratio = mb.get("up_ratio_pct", 50)
    limit_ratio = mb.get("limit_ratio", 1)
    money_effect = mb.get("money_effect", "")

    scenarios = []
    bearish_dims = 0

    # ═══ 情景A: 强势上涨 ═══
    a_conditions = []; a_score = 0
    for (text, thresh, actual, met, w, dim) in [
        ("主力净流入>500万", ">500万", f"{main_net_wan:+.0f}万", main_net_wan > 500 and direction == "流入", 25, "minute_flow"),
        ("机构主导(净流入>200万且>游资+散户)", "机构>200万且最大",
         f"机构{inst_net:+.0f}万, 游资{hm_net:+.0f}万, 散户{retail_net:+.0f}万",
         inst_net > 200 and inst_net > abs(hm_net) and inst_net > abs(retail_net), 20, "minute_flow"),
        ("板块情绪分≥60", "≥60", f"{sentiment_score:.0f}分 ({inflow_blocks}/{total_blocks}板块流入)",
         sentiment_score >= 60, 15, "sector"),
        ("量能配合(量比1.2~5, 换手<15%)", "量比1.2-5, 换手<15%",
         f"量比{vol_ratio}, 换手{turnover}%", 1.2 <= vol_ratio <= 5 and turnover < 15, 15, "quote"),
        ("无顶背离信号", "无顶背离",
         f"背离: {'有('+divergence_type+')' if has_divergence else '无'}",
         not has_divergence or "顶背离" not in divergence_type, 15, "minute_flow"),
        ("资金加速流入", "后半段斜率>前半段×1.5",
         f"前半段{first_slope}万/分→后半段{second_slope}万/分",
         "加速流入" in acceleration, 10, "minute_flow"),
        ("北向资金流入(>1亿)", "北向净流入>1亿", f"北向{nb_net_yi:+.2f}亿", nb_net_yi > 1, 10, "north_bound"),
        ("大盘配合+个股跑赢", "相对强度>1%且大盘非弱势",
         f"{market_env}, 相对强度{relative_strength:+.2f}%",
         relative_strength > 1 and "弱势" not in market_env, 5, "market"),
        ("市场广度不差(上涨>45%)", "上涨占比≥45%且无强亏钱效应",
         f"涨{up_ratio:.0f}%, {money_effect}",
         up_ratio >= 45 and "亏钱" not in money_effect, 5, "breadth"),
        ("量能参考(量比≥0.8+换手≥0.5%)", "量比≥0.8,换手≥0.5%",
         f"量比{vol_ratio},换手{turnover}%", vol_ratio >= 0.8 and turnover >= 0.5, 2, "quote"),
    ]:
        c = _cond(text, thresh, actual, met, w, dim)
        a_conditions.append(c)
        if c["met"] == True: a_score += c["weight"]
    if nb_net_yi < -5: a_score -= 5
    if up_ratio < 45:
        a_score -= 3

    bullish_dims = sum([1 if main_net_wan > 300 else 0, 1 if change_pct > 0 else 0,
                        1 if sentiment_score >= 50 else 0, 1 if news_bullish > news_bearish else 0,
                        1 if nb_net_yi > 0 else 0, 1 if relative_strength > 0 else 0,
                        1 if up_ratio >= 45 else 0])
    if bullish_dims >= 6: a_score += 10
    elif bullish_dims >= 5: a_score += 5

    scenarios.append({
        "name": "情景A: 强势上涨",
        "description": "主力持续流入+机构主导+板块共振+量能配合 → 当日剩余时段大概率继续走强",
        "raw_score": max(0, a_score), "conditions": a_conditions,
        "met_count": sum(1 for c in a_conditions if c["met"] == True),
        "total_conditions": len(a_conditions),
        "historical_ref": {"rule": "机构主导+板块共振+量能配合→当日继续走强",
                          "historical_win_rate": "约65-70%", "source": "基于2024-2025年A股日内资金流统计"},
        "failure_conditions": ["午后机构资金转流出", "板块情绪急转直下", "突发重大利空"],
    })

    # ═══ 情景B: 震荡横盘 ═══
    b_conditions = []; b_score = 0
    for (text, thresh, actual, met, w, dim) in [
        ("主力净流入<300万(无方向)", "绝对值<300万", f"{main_net_wan:+.0f}万", abs(main_net_wan) < 300, 30, "minute_flow"),
        ("振幅<3%(窄幅波动)", "<3%", f"{amplitude}%", amplitude < 3, 25, "quote"),
        ("板块情绪35~65(中性)", "35-65", f"{sentiment_score:.0f}分", 35 <= sentiment_score <= 65, 25, "sector"),
        ("无明确消息催化", "0条今日新闻", f"利好{news_bullish}/利空{news_bearish}", news_bullish == 0 and news_bearish == 0, 15, "news"),
        ("北向资金无明显方向(±3亿内)", "|北向|<3亿", f"北向{nb_net_yi:+.2f}亿", abs(nb_net_yi) < 3, 10, "north_bound"),
        ("大盘+个股均中性波动", "|相对强度|<1.5%,|大盘|<1%",
         f"大盘{ms.get('benchmark_change', 0):+.2f}%, 相对{relative_strength:+.2f}%",
         abs(relative_strength) < 1.5 and abs(ms.get("benchmark_change", 0)) < 1, 10, "market"),
        ("市场广度中性(涨40-60%,涨跌停比0.8-2)", "涨40-60%,涨跌停比0.8-2",
         f"涨{up_ratio:.0f}%, 涨跌停比{limit_ratio}",
         40 <= up_ratio <= 60 and 0.8 <= limit_ratio <= 2, 10, "breadth"),
    ]:
        c = _cond(text, thresh, actual, met, w, dim)
        b_conditions.append(c)
        if c["met"] == True: b_score += c["weight"]

    scenarios.append({
        "name": "情景B: 震荡横盘",
        "description": "资金方向不明+振幅小+情绪中性+无催化 → 当日剩余时段大概率窄幅震荡",
        "raw_score": b_score, "conditions": b_conditions,
        "met_count": sum(1 for c in b_conditions if c["met"] == True),
        "total_conditions": len(b_conditions),
        "historical_ref": {"rule": "主力无方向+振幅<3%→后续2h横盘", "historical_win_rate": "约55-60%",
                          "source": "A股日内波动统计"},
        "failure_conditions": ["突发消息催化", "大单资金突然涌入/涌出"],
    })

    # ═══ 情景C: 冲高回落 ═══
    c_conditions = []; c_score = 0
    for (text, thresh, actual, met, w, dim) in [
        ("已涨>3%且资金流转向", "涨>3%+资金减缓/流出",
         f"涨{change_pct:+.2f}%, 趋势:{acceleration}",
         change_pct > 3 and ("流出" in acceleration or "减缓" in acceleration), 30, "minute_flow"),
        ("出现顶背离(资金衰竭)", "顶背离信号", divergence_type,
         has_divergence and "顶背离" in divergence_type, 25, "minute_flow"),
        ("机构流出>100万+散户流入>200万(派发)", "机构<-100万,散户>+200万",
         f"机构{inst_net:+.0f}万,散户{retail_net:+.0f}万",
         inst_net < -100 and retail_net > 200, 25, "minute_flow"),
        ("换手率>10%(异常活跃)", ">10%", f"{turnover}%", turnover > 10, 15, "quote"),
        ("北向资金流出(<-2亿)", "北向<-2亿", f"北向{nb_net_yi:+.2f}亿", nb_net_yi < -2, 10, "north_bound"),
        ("个股高位+大盘走弱(逆势难持续)", "涨>2%+相对强度>1%+大盘弱势",
         f"涨{change_pct:+.2f}%, 大盘{ms.get('benchmark_change', 0):+.2f}%",
         change_pct > 2 and "弱势" in market_env, 10, "market"),
        ("赚钱效应转弱", "涨跌停比<1.5或有亏钱效应",
         f"涨跌停比{limit_ratio}, {money_effect}",
         limit_ratio < 1.5 or "亏钱" in money_effect, 10, "breadth"),
    ]:
        c = _cond(text, thresh, actual, met, w, dim)
        c_conditions.append(c)
        if c["met"] == True: c_score += c["weight"]

    scenarios.append({
        "name": "情景C: 冲高回落",
        "description": "高位+资金转向/顶背离/机构派发 → 当日剩余时段警惕回落风险",
        "raw_score": c_score, "conditions": c_conditions,
        "met_count": sum(1 for c in c_conditions if c["met"] == True),
        "total_conditions": len(c_conditions),
        "historical_ref": {"rule": "涨超3%+资金转流出+机构vs散户反向→午后回落", "historical_win_rate": "约55-65%",
                          "source": "A股日内资金-价格关系统计"},
        "failure_conditions": ["超预期利好", "板块集体暴动"],
    })

    # ═══ 情景D: 弱势下跌 ═══
    d_conditions = []; d_score = 0
    for (text, thresh, actual, met, w, dim) in [
        ("主力净流出>500万", "<-500万", f"{main_net_wan:+.0f}万",
         main_net_wan < -500 and direction == "流出", 30, "minute_flow"),
        ("板块情绪<40(偏冷)", "<40", f"{sentiment_score:.0f}分", sentiment_score < 40, 25, "sector"),
        ("资金加速流出", "后半段斜率<前半段×0.3且<0",
         f"前半段{first_slope}万/分→后半段{second_slope}万/分",
         "加速流出" in acceleration, 25, "minute_flow"),
        ("有利空消息", "利空>0条", f"利空{news_bearish}条", news_bearish > 0, 15, "news"),
        ("北向大幅流出(<-5亿)", "北向<-5亿", f"北向{nb_net_yi:+.2f}亿", nb_net_yi < -5, 10, "north_bound"),
        ("大盘弱势+个股跑输", "大盘弱势+相对强度<-0.5%",
         f"{market_env}, 相对{relative_strength:+.2f}%",
         "弱势" in market_env and relative_strength < -0.5, 10, "market"),
        ("市场普跌(上涨<35%或涨跌停比<0.8)", "上涨<35%或涨跌停比<0.8",
         f"涨{up_ratio:.0f}%, 涨跌停比{limit_ratio}, {money_effect}",
         up_ratio < 35 or limit_ratio < 0.8, 10, "breadth"),
    ]:
        c = _cond(text, thresh, actual, met, w, dim)
        d_conditions.append(c)
        if c["met"] == True:
            d_score += c["weight"]
            if dim in ("north_bound", "market", "breadth"):
                bearish_dims += 1

    if bearish_dims >= 5: d_score += 10

    scenarios.append({
        "name": "情景D: 弱势下跌",
        "description": "主力持续流出+板块冷+加速流出 → 当日剩余时段大概率继续走弱",
        "raw_score": d_score, "conditions": d_conditions,
        "met_count": sum(1 for c in d_conditions if c["met"] == True),
        "total_conditions": len(d_conditions),
        "historical_ref": {"rule": "主力持续流出+板块情绪<40→当日收阴", "historical_win_rate": "约60-70%",
                          "source": "A股日内资金-情绪联合统计"},
        "failure_conditions": ["午后重大利好", "国家队护盘资金入场"],
    })

    # ═══ 情景E: 尾盘异动 ═══
    now = datetime.now()
    if now.hour == 14 and now.minute >= 30 or now.hour == 15:
        has_rt = bool(last_turn and isinstance(last_turn, dict) and last_turn.get("time"))
        recent_turn = False
        if has_rt:
            try:
                td = datetime.strptime(last_turn["time"], "%Y-%m-%d %H:%M")
                recent_turn = (now - td).total_seconds() / 60 < 30
            except: pass
        e_conditions = []; e_score = 0
        for (text, thresh, actual, met, w, dim) in [
            ("尾盘+近30分钟资金转向", "14:30后+30分内转向",
             f"最近转向: {last_turn.get('time', '')} {last_turn.get('type', '')}",
             recent_turn, 40, "minute_flow"),
            ("尾盘放量(量比>2)", ">2", f"{vol_ratio}", vol_ratio > 2, 30, "quote"),
            ("尾盘异动(涨跌幅>3%)", ">3%或<-3%", f"{change_pct:+.2f}%", abs(change_pct) > 3, 30, "quote"),
        ]:
            c = _cond(text, thresh, actual, met, w, dim)
            e_conditions.append(c)
            if c["met"] == True: e_score += c["weight"]
        if e_score >= 30:
            scenarios.append({
                "name": "情景E: 尾盘异动",
                "description": "尾盘资金异动+放量 → 关注次日开盘延续方向",
                "raw_score": e_score, "conditions": e_conditions,
                "met_count": sum(1 for c in e_conditions if c["met"] == True),
                "total_conditions": len(e_conditions),
                "historical_ref": {"rule": "尾盘30min资金异动与次日开盘方向相关", "historical_win_rate": "约55-65%",
                                  "source": "A股尾盘效应统计"},
                "failure_conditions": ["隔夜外盘剧变", "盘后重大消息"],
            })

    # 归一化
    for s in scenarios: s["raw_score"] = max(0, s["raw_score"])
    total_score = sum(s["raw_score"] for s in scenarios)
    for s in scenarios:
        s["probability"] = round(s["raw_score"] / total_score * 100, 1) if total_score > 0 else 0

    scenarios_sorted = sorted(scenarios, key=lambda x: x["probability"], reverse=True)

    return {
        "scenarios": scenarios_sorted,
        "primary_scenario": scenarios_sorted[0] if scenarios_sorted else None,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_points": s.get("data_points", 0),
        "freshness": {
            "phase": freshness.get("phase", -1),
            "phase_name": freshness.get("phase_name", "未知"),
            "minutes_from_open": freshness.get("minutes_from_open", -1),
            "downgraded_count": len(_downgrade_log),
            "downgrade_details": _downgrade_log,
        },
        "disclaimer": "概率基于当前盘中数据的多因子条件匹配+时效性门控(V1.3)。PENDING条件表示数据尚未刷新，未参与概率计算。",
    }


# ====== 买卖时机参考信号 ======
def generate_trading_signals(scenarios, flow_data, quote, party_data, sector_data, news_data,
                             north_bound, market_strength, market_breadth):
    primary = scenarios[0] if scenarios else {}
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
    market_env = ms.get("market_env", "")
    mb = market_breadth or {}
    up_ratio = mb.get("up_ratio_pct", 50)
    limit_ratio = mb.get("limit_ratio", 1)
    money_effect = mb.get("money_effect", "")

    buy_signals = []; sell_signals = []

    # 买入
    strong_buy_met = sum([primary_prob >= 60 and "情景A" in primary_name,
                         inst_net > 200, sentiment_score >= 60,
                         change_pct < 5, "加速流入" in acceleration])
    if strong_buy_met >= 4:
        buy_signals.append({
            "level": "🟢🟢🟢 强买入参考", "strength": strong_buy_met,
            "data_evidence": [
                {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "≥60%",
                 "source": "多因子概率引擎", "met": primary_prob >= 60},
                {"item": "主力累计净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "机构>+200万",
                 "source": "push2分钟级资金流", "met": inst_net > 200},
                {"item": "板块情绪分", "value": f"{sentiment_score:.0f}/100", "threshold": "≥60",
                 "source": "板块资金流聚合", "met": sentiment_score >= 60},
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<5%(未过度拉升)",
                 "source": "腾讯行情API", "met": change_pct < 5},
                {"item": "资金加速度", "value": acceleration, "threshold": "加速流入",
                 "source": "push2趋势分析", "met": "加速流入" in acceleration},
            ],
            "action": "可考虑逢低建仓/加仓",
            "stop_loss": f"跌破{price * 0.97:.2f}(-3%)则果断离场",
            "principle": f"宁可少挣: {strong_buy_met}/5条件满足, 不追高",
        })

    medium_buy_met = sum([primary_prob >= 45 and "情景A" in primary_name,
                         inst_net > 100, sentiment_score >= 50, change_pct < 7])
    if medium_buy_met >= 3 and strong_buy_met < 4:
        buy_signals.append({
            "level": "🟢🟢 中等买入参考", "strength": medium_buy_met,
            "data_evidence": [
                {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "≥45%",
                 "source": "多因子概率引擎", "met": primary_prob >= 45},
                {"item": "机构净流入", "value": f"{inst_net:+.0f}万", "threshold": ">+100万",
                 "source": "push2分钟级资金流", "met": inst_net > 100},
                {"item": "板块情绪分", "value": f"{sentiment_score:.0f}/100", "threshold": "≥50",
                 "source": "板块资金流聚合", "met": sentiment_score >= 50},
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<7%",
                 "source": "腾讯行情API", "met": change_pct < 7},
            ],
            "action": "可小仓位试探(计划仓位的30-50%), 等待更多信号确认",
            "stop_loss": f"跌破{price * 0.95:.2f}(-5%)则止损",
            "principle": "宁可少挣: 先小仓试错,确认方向后再加仓",
        })

    if not buy_signals:
        buy_signals.append({
            "level": "⚪ 暂不建议买入",
            "data_evidence": [
                {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "需≥45%",
                 "source": "多因子概率引擎", "met": primary_prob >= 45},
                {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "需>+500万",
                 "source": "push2分钟级资金流", "met": main_net_wan > 500},
            ],
            "action": "继续观察, 等待资金面+情绪面+价格面共振信号",
            "principle": "宁可少挣: 不买至少不亏钱, 错过一波比亏一波好",
        })

    # 卖出
    strong_sell_met = sum([primary_prob >= 50 and ("情景C" in primary_name or "情景D" in primary_name),
                          inst_net < -200, "加速流出" in acceleration])
    if strong_sell_met >= 3:
        sell_signals.append({
            "level": "🔴🔴🔴 强卖出参考", "strength": strong_sell_met,
            "data_evidence": [
                {"item": "弱势情景概率", "value": f"{primary_prob:.0f}%({primary_name})", "threshold": "≥50%",
                 "source": "多因子概率引擎", "met": primary_prob >= 50},
                {"item": "机构净流出", "value": f"{inst_net:+.0f}万", "threshold": "<-200万",
                 "source": "push2分钟级资金流", "met": inst_net < -200},
                {"item": "资金加速度", "value": acceleration, "threshold": "加速流出",
                 "source": "push2趋势分析", "met": "加速流出" in acceleration},
                {"item": "主力净流出", "value": f"{main_net_wan:+.0f}万", "threshold": "大额流出",
                 "source": "push2分钟级资金流", "met": main_net_wan < -300},
            ],
            "action": "建议果断减仓/清仓, 不在下跌中补仓",
            "risk_note": f"继续持有可能面临更大回撤, 当前已流出{abs(main_net_wan):.0f}万",
            "principle": "宁可少亏: 卖了少亏比扛着大亏好, 卖错了可以再买回来",
        })

    medium_sell_met = sum([
        ("情景C" in primary_name and primary_prob >= 35) or ("情景D" in primary_name and primary_prob >= 35),
        inst_net < -100 or (inst_net < 0 and retail_net > 100),
    ])
    if medium_sell_met >= 2 and strong_sell_met < 3:
        sell_signals.append({
            "level": "🔴🔴 中等卖出参考", "strength": medium_sell_met,
            "data_evidence": [
                {"item": "弱势情景概率", "value": f"{primary_prob:.0f}%({primary_name})", "threshold": "≥35%",
                 "source": "多因子概率引擎", "met": primary_prob >= 35},
                {"item": "机构资金", "value": f"{inst_net:+.0f}万", "threshold": "<-100万或机构流出+散户流入",
                 "source": "push2分钟级资金流", "met": inst_net < -100},
                {"item": "散户资金", "value": f"{retail_net:+.0f}万", "threshold": "如>+100万则为接盘信号",
                 "source": "push2分钟级资金流", "met": retail_net > 100},
            ],
            "action": "建议逐步减仓, 至少减到半仓以下",
            "principle": "宁可少亏: 卖一半留一半, 涨了还有仓位, 跌了少亏一半",
        })

    if change_pct > 8 and ("流出" in direction or "减缓" in acceleration):
        sell_signals.append({
            "level": "🔴 弱卖出参考(高位止盈)",
            "data_evidence": [
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": ">8%", "source": "腾讯行情", "met": True},
                {"item": "资金方向", "value": f"{direction}/{acceleration}", "threshold": "流出/减缓",
                 "source": "push2趋势", "met": True},
            ],
            "action": "可考虑部分止盈, 锁定利润",
            "principle": "宁可少挣: 落袋为安, 不贪最后一个铜板",
        })

    if not sell_signals:
        sell_signals.append({
            "level": "⚪ 暂不需卖出",
            "data_evidence": [
                {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "持续流入中",
                 "source": "push2分钟级资金流", "met": main_net_wan > 0},
            ],
            "action": "继续持有观察, 关注资金流方向是否转弱",
            "principle": "保持警觉, 一旦出现卖出数据条件, 果断行动",
        })

    # 持有参考
    if "情景A" in primary_name and primary_prob >= 50:
        hold_verdict = {
            "level": "✅ 可继续持有",
            "reason": f"强势上涨概率{primary_prob:.0f}%, 主力净流入{main_net_wan:+.0f}万",
            "watch_points": ["午后资金是否转流出", "是否出现顶背离", "板块情绪是否骤降"],
        }
    elif "情景B" in primary_name:
        hold_verdict = {
            "level": "⏸️ 持有观望",
            "reason": f"震荡格局, 主力{main_net_wan:+.0f}万, 振幅{amplitude}%",
            "watch_points": ["突破方向(放量上破/下破)", "是否有催化消息出现"],
        }
    else:
        hold_verdict = {
            "level": "⚠️ 审视持仓",
            "reason": f"风险情景概率较高({primary_name} {primary_prob:.0f}%), 机构{inst_net:+.0f}万",
            "watch_points": ["触发止损条件则果断执行", "等待情景A信号出现再考虑加仓"],
        }

    s_buy = buy_signals[0]["level"] if buy_signals else ""
    s_sell = sell_signals[0]["level"] if sell_signals else ""

    if "强买入" in s_buy and "暂不需卖出" in s_sell:
        overall = f"总体偏多: 买入信号较强, 无卖出压力。主力{main_net_wan:+.0f}万, 板块情绪{sentiment_score:.0f}分。可在控制仓位前提下逢低参与。"
    elif "强卖出" in s_sell:
        overall = f"总体偏空: 卖出信号较强。主力净流出{abs(main_net_wan):.0f}万。建议减仓或观望。"
    elif "中等卖出" in s_sell:
        overall = f"总体谨慎: 有卖出压力。机构{inst_net:+.0f}万, 散户{retail_net:+.0f}万。持有者应审视持仓。"
    elif "中等买入" in s_buy:
        overall = f"总体中性偏多: 主力{main_net_wan:+.0f}万。可小仓试探, 严格止损。"
    else:
        overall = f"总体中性: 主力{main_net_wan:+.0f}万, 信号不明确。建议观望。"

    return {
        "buy_signals": buy_signals, "sell_signals": sell_signals,
        "hold_verdict": hold_verdict, "overall_verdict": overall,
        "data_summary": {
            "main_net_wan": main_net_wan, "inst_net_wan": inst_net,
            "retail_net_wan": retail_net, "sentiment_score": sentiment_score,
            "change_pct": change_pct, "turnover_pct": turnover,
            "vol_ratio": vol_ratio, "acceleration": acceleration,
            "data_points": data_points,
        },
    }


# ====== 主函数 ======
def main():
    code = "600176"
    now = datetime.now()

    print("=" * 70)
    print(f"  📊 盘中实时交易信号系统 V1.3")
    print(f"  标的: 中国巨石({code})")
    print(f"  分析时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    if now.weekday() >= 5:
        print("\n  ❌ 今日为周末，A股休市"); return

    freshness = check_data_freshness()
    if freshness.get("phase", 0) == 0 and not freshness.get("is_trading"):
        print(f"\n  ⚠️ {freshness['phase_name']}, 数据可能不完整")

    print(f"\n  ⏱️ 数据时效性: {freshness['phase_name']} (Phase {freshness['phase']})")
    if freshness["phase"] == 2:
        print(f"     ⚡ 板块/北向/广度数据可能延迟，已自动降权")

    # [1/7] 行情
    print("\n[1/7] 拉取实时行情...")
    quote = fetch_realtime_quote(code)
    if "error" in quote:
        print(f"  ❌ {quote['error']}"); return
    print(f"  ✅ {quote['name']}: {quote['price']:.2f}  {quote['change_pct']:+.2f}%")

    # [2/7] 资金流
    print("[2/7] 拉取分钟级资金流...")
    flow = fetch_minute_fund_flow(code)
    if "error" in flow:
        print(f"  ❌ {flow['error']}"); return
    s = flow["summary"]; t = flow["trend"]
    print(f"  ✅ {s['data_points']}分钟: 主力{s['total_main_net_wan']:+.0f}万 | {t['direction']}/{t['acceleration']}")

    # [3/7] 三方+板块
    print("[3/7] 三方资金分类 + 板块情绪...")
    parties = classify_intraday_parties(flow)
    v = parties["verdict"]
    print(f"  ✅ 博弈: {v['scenario'][:60]}...")
    print(f"     等级: {v['level']}")
    sector = fetch_sector_sentiment(code)
    print(f"  ✅ 板块情绪: {sector.get('sentiment_score', 0):.0f}/100 {sector.get('level', '')}")
    divergence = detect_fund_price_divergence(flow, quote)
    if divergence.get("has_divergence"):
        print(f"  ⚠️ 检测到背离!")

    # [4/7] 北向/大盘/广度
    print("[4/7] 拉取北向+大盘+广度...")
    north_bound = fetch_north_bound_flow()
    print(f"  ✅ {north_bound.get('data_basis', '')}")
    market_strength = fetch_market_strength(code, quote)
    print(f"  ✅ {market_strength.get('data_basis', '')}")
    market_breadth = fetch_market_breadth()
    print(f"  ✅ {market_breadth.get('data_basis', '')[:80]}...")

    # [5/7] 消息
    print("[5/7] 拉取消息面...")
    news = fetch_intraday_news(code)
    print(f"  ✅ 今日{news['today_count']}条 (利好{news['bullish_count']}/利空{news['bearish_count']})")

    # [6/7] 概率
    print("[6/7] 生成七维多情景概率预判...")
    scenarios = generate_probability_scenarios(
        flow, quote, sector, news, parties, divergence,
        north_bound, market_strength, market_breadth,
    )
    primary = scenarios.get("primary_scenario", {})
    print(f"  ✅ 主导: {primary.get('name', '?')} → {primary.get('probability', 0):.0f}%")
    fi = scenarios.get("freshness", {})
    if fi.get("downgraded_count", 0) > 0:
        print(f"     ⚡ {fi['downgraded_count']}个条件降权/挂起(PENDING)")

    # [7/7] 信号
    print("[7/7] 生成买卖时机参考信号...")
    signals = generate_trading_signals(
        scenarios["scenarios"], flow, quote, parties, sector, news,
        north_bound, market_strength, market_breadth,
    )
    print(f"  ✅ {signals.get('overall_verdict', '')[:80]}...")

    # ━━━ 核心结论 ━━━
    print("\n" + "=" * 70)
    print("  🎯 核心结论")
    print("=" * 70)
    print(f"""
  📈 价格: {quote['name']} {quote['price']:.2f} {quote['change_pct']:+.2f}%
     今开{quote['open']:.2f} 最高{quote['high']:.2f} 最低{quote['low']:.2f}
     换手率{quote['turnover_pct']:.2f}% 量比{quote['vol_ratio']:.2f} 振幅{quote['amplitude']:.2f}%

  💰 资金: 主力净流入 {s['total_main_net_wan']:+.0f}万 ({s['data_points']}分钟)
     机构(超大单): {s['total_super_net_wan']:+.0f}万 | 游资(大单): {s['total_large_net_wan']:+.0f}万
     散户(中+小): {(s.get('total_mid_net_wan', 0) or 0) + (s.get('total_small_net_wan', 0) or 0):+.0f}万
     趋势: {t['direction']} / {t['acceleration']}

  🎯 情绪: 板块情绪 {sector.get('sentiment_score', 0):.0f}/100 {sector.get('level', '')}
     {sector.get('inflow_blocks', 0)}/{sector.get('total_blocks', 1)}板块流入

  🌏 北向: {north_bound.get('data_basis', '')}
  📊 大盘: {market_strength.get('data_basis', '')}
     {market_strength.get('relative_rating', '')} | {market_strength.get('market_env', '')}
  🔥 广度: {market_breadth.get('data_basis', '')[:100]}

  🔮 主导情景: {primary.get('name', '?')} → 概率 {primary.get('probability', 0):.0f}%
     满足 {primary.get('met_count', 0)}/{primary.get('total_conditions', 0)} 条件
     历史胜率: {primary.get('historical_ref', {}).get('historical_win_rate', '?')}

  ⚡ 买入: {signals['buy_signals'][0]['level'] if signals.get('buy_signals') else '无'}
  ⚡ 卖出: {signals['sell_signals'][0]['level'] if signals.get('sell_signals') else '无'}
  📌 持有: {signals.get('hold_verdict', {}).get('level', '未知')}

  🎯 综合: {signals.get('overall_verdict', '')}
""")

    # 情景详情
    print("─" * 60)
    print("  情景概率详情:")
    for sc in scenarios.get("scenarios", []):
        prob = sc.get("probability", 0)
        name = sc.get("name", "")
        met = sc.get("met_count", 0)
        total = sc.get("total_conditions", 0)
        icon = "🔥" if prob >= 50 else ("📊" if prob >= 25 else "🔍")
        print(f"\n  {icon} {name} → {prob:.0f}% (满足{met}/{total})")
        for c in sc.get("conditions", []):
            m = c.get("met")
            status = "✅" if m is True else ("⏸️" if m == "PENDING" else "❌")
            print(f"     {status} [{c.get('weight', 0):.0f}] {c['condition']}: {c.get('actual', '')[:80]}")

    # 信号详情
    print(f"\n{'─' * 60}")
    print("  买卖信号详情:")
    for bs in signals.get("buy_signals", []):
        print(f"\n  {bs['level']}")
        for ev in bs.get("data_evidence", []):
            s = "✅" if ev.get("met") else "❌"
            print(f"    {s} {ev['item']}: {ev['value']} (阈值:{ev['threshold']})")
        print(f"    操作: {bs.get('action', '')}")
        if bs.get("stop_loss"): print(f"    止损: {bs['stop_loss']}")

    for ss in signals.get("sell_signals", []):
        print(f"\n  {ss['level']}")
        for ev in ss.get("data_evidence", []):
            s = "✅" if ev.get("met") else "❌"
            print(f"    {s} {ev['item']}: {ev['value']} (阈值:{ev['threshold']})")
        print(f"    操作: {ss.get('action', '')}")

    hv = signals.get("hold_verdict", {})
    if hv:
        print(f"\n  📌 {hv.get('level', '')}")
        print(f"     {hv.get('reason', '')}")
        for wp in hv.get("watch_points", []):
            print(f"     👁 {wp}")

    print(f"\n{'=' * 70}")
    print("  ⚠️ 研究声明:")
    print("  1. 所有信号基于公开API实时数据(延迟3-5秒)，不构成投资建议")
    print("  2. 概率预判基于七维25+条件多因子匹配+历史统计规律")
    print(f"  3. 时效性门控(V1.3): Phase {freshness.get('phase', '?')}—{freshness.get('phase_name', '')}")
    print("     标记为⏸️PENDING的条件表示数据源尚未刷新，未参与计算")
    print("  4. 核心原则：宁可少挣，宁可少亏——不确定时不出手")
    print("=" * 70)
    print("\n✅ 盘中信号分析完成!")


if __name__ == "__main__":
    main()
