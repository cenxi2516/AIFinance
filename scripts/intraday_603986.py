#!/usr/bin/env python3
"""
兆易创新(603986) 盘中实时交易信号分析
V1.3 七维交叉验证 + 时效性门控
生成时间: 自动
"""
import sys, os, time, json, re
from datetime import datetime
from urllib.request import Request, urlopen
import requests as req_lib

# ============================================================
# 基础配置
# ============================================================
CODE = "603986"
NAME = "兆易创新"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
OUTPUT_BASE = "src/盘中交易信号"

# ============================================================
# Layer 0: 时效性门控
# ============================================================
def check_data_freshness():
    now = datetime.now()
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    minutes_from_open = (now - open_t).total_seconds() / 60

    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        phase, phase_name = 0, "盘前"
    elif minutes_from_open <= 30:
        phase, phase_name = 1, f"盘初({minutes_from_open:.0f}min, 数据延迟高发期)"
    elif minutes_from_open <= 90:
        phase, phase_name = 2, f"早盘过渡({minutes_from_open:.0f}min)"
    elif now.hour < 14 or (now.hour == 14 and now.minute < 30):
        phase, phase_name = 3, f"盘中正常({minutes_from_open:.0f}min)"
    else:
        phase, phase_name = 4, f"尾盘({minutes_from_open:.0f}min)"

    if phase == 1:
        weights = {"quote": 25, "minute_flow": 50, "sector": 5, "news": 5, "north_bound": 0, "market": 15, "breadth": 0}
    elif phase == 2:
        weights = {"quote": 20, "minute_flow": 35, "sector": 12, "news": 8, "north_bound": 5, "market": 12, "breadth": 8}
    elif phase == 3:
        weights = {"quote": 15, "minute_flow": 25, "sector": 15, "news": 10, "north_bound": 15, "market": 10, "breadth": 10}
    else:
        weights = {"quote": 15, "minute_flow": 30, "sector": 12, "news": 10, "north_bound": 13, "market": 10, "breadth": 10}

    return {"phase": phase, "phase_name": phase_name, "minutes_from_open": minutes_from_open, "dynamic_weights": weights}

# ============================================================
# Layer 1: 腾讯实时行情
# ============================================================
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
            return {"error": f"字段不足, 实际{len(vals)}"}
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

# ============================================================
# Layer 2: 分钟级资金流
# ============================================================
def fetch_minute_fund_flow(code):
    market = 1 if code.startswith(("6", "9")) else 0
    secid = f"{market}.{code}"
    params = {
        "lmt": "0", "klt": "1", "secid": secid,
        "fields1": "f1,f2,f3,f4",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
        "ut": "b2884a393a59ad64023092a90a2f19e6",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    try:
        r = req_lib.get("https://push2his.eastmoney.com/api/qt/stock/fflow/minute/get",
                       params=params, headers=headers, timeout=15)
        lines = r.json().get("data", {}).get("data", []) or []
    except Exception as e:
        return {"error": f"API失败: {e}", "minutes": [], "summary": {}, "trend": {}}

    if not lines:
        return {"error": "无资金流数据", "minutes": [], "summary": {}, "trend": {}}

    minutes = []
    for line in lines:
        parts = line.split(",")
        if len(parts) >= 6:
            minutes.append({
                "time": parts[0],
                "price": float(parts[1]) if parts[1] else 0,
                "change_pct": float(parts[2]) if parts[2] else 0,
                "volume": float(parts[3]) if parts[3] else 0,
                "amount": float(parts[4]) if parts[4] else 0,
                "main_net": float(parts[5]) if parts[5] else 0,
                "super_net": float(parts[6]) if len(parts) > 6 and parts[6] else 0,
                "large_net": float(parts[7]) if len(parts) > 7 and parts[7] else 0,
                "mid_net": float(parts[8]) if len(parts) > 8 and parts[8] else 0,
                "small_net": float(parts[9]) if len(parts) > 9 and parts[9] else 0,
            })

    if not minutes:
        return {"error": "解析后无数据", "minutes": [], "summary": {}, "trend": {}}

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
        direction = acceleration = "数据不足"
        first_slope = second_slope = 0

    turning_points = []
    if len(cum_main) >= 20:
        for i in range(10, len(cum_main) - 5):
            before = cum_main[i-5:i]
            after = cum_main[i:i+5]
            is_peak = all(cum_main[i] > b for b in before) and all(cum_main[i] > a for a in after)
            is_valley = all(cum_main[i] < b for b in before) and all(cum_main[i] < a for a in after)
            if is_peak:
                turning_points.append({"time": minutes[i]["time"], "type": "峰值", "value_wan": cum_main[i] / 1e4})
            elif is_valley:
                turning_points.append({"time": minutes[i]["time"], "type": "谷值", "value_wan": cum_main[i] / 1e4})

    return {
        "minutes": minutes,
        "summary": {
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
            "direction": direction,
            "acceleration": acceleration,
            "first_half_slope_wan_per_min": round(first_slope / 1e4, 2),
            "second_half_slope_wan_per_min": round(second_slope / 1e4, 2),
            "cum_sequence_wan": [round(v / 1e4, 1) for v in cum_main],
            "turning_points": turning_points[-5:],
            "last_turn": turning_points[-1] if turning_points else None,
        },
    }

# ============================================================
# Layer 2b: 三方资金分类
# ============================================================
def classify_intraday_parties(flow_data):
    s = flow_data.get("summary", {})
    inst_net = s.get("total_super_net_wan", 0)
    hm_net = s.get("total_large_net_wan", 0)
    retail_net = (s.get("total_mid_net_wan", 0) or 0) + (s.get("total_small_net_wan", 0) or 0)
    main_net = s.get("total_main_net_wan", 0)
    dp = s.get("data_points", 0)

    inst_dir = "流入" if inst_net > 0 else "流出"
    hm_dir = "流入" if hm_net > 0 else "流出"
    retail_dir = "流入" if retail_net > 0 else "流出"

    total_abs = abs(inst_net) + abs(hm_net) + abs(retail_net)
    inst_share = round(abs(inst_net) / total_abs * 100, 1) if total_abs > 0 else 0
    hm_share = round(abs(hm_net) / total_abs * 100, 1) if total_abs > 0 else 0
    retail_share = round(abs(retail_net) / total_abs * 100, 1) if total_abs > 0 else 0

    if inst_net > 200 and hm_net > 0 and retail_net < -100:
        scenario = "机构+游资合力做多，散户恐慌出局 → 强多头信号"; level = "🟢 积极"
    elif inst_net > 200 and retail_net > 100:
        scenario = "机构与散户同向流入 → 共识强"; level = "🟡 中性偏多"
    elif inst_net < -200 and retail_net > 200:
        scenario = f"机构{inst_net:.0f}万流出+散户{retail_net:.0f}万接盘 ⚠️"; level = "🔴 警惕"
    elif inst_net < -100 and hm_net < -100 and retail_net > 100:
        scenario = "机构+游资出逃，散户接盘 → 强空头"; level = "🔴 危险"
    elif inst_net > 100 and hm_net < -50 and retail_net < -50:
        scenario = "机构独力做多，游资+散户不跟 → 孤军深入"; level = "🟡 中性"
    else:
        scenario = "三方分歧，方向不明确"; level = "⚪ 观望"

    return {
        "institution": {"net_wan": round(inst_net, 1), "direction": inst_dir, "share_pct": inst_share},
        "hot_money": {"net_wan": round(hm_net, 1), "direction": hm_dir, "share_pct": hm_share},
        "retail": {"net_wan": round(retail_net, 1), "direction": retail_dir, "share_pct": retail_share},
        "verdict": {"scenario": scenario, "level": level, "main_direction": "多头占优" if main_net > 0 else "空头占优"},
    }

# ============================================================
# Layer 2c: 背离检测
# ============================================================
def detect_fund_price_divergence(flow_data, quote):
    minutes = flow_data.get("minutes", [])
    if not minutes or len(minutes) < 20:
        return {"has_divergence": False}

    cum_main = []
    running = 0.0
    for m in minutes:
        running += m["main_net"]
        cum_main.append(running)

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
        prev_flow = cum_main[prev_end - 1] - cum_main[prev_start]
        curr_flow = cum_main[curr_end - 1] - cum_main[curr_start]

        if change_pct > 3 and prev_flow > 0 and curr_flow < prev_flow * 0.3:
            divergences.append({"type": "顶背离(资金衰竭)",
                              "detail": f"涨{change_pct:+.2f}%, 资金{prev_flow/1e4:.0f}→{curr_flow/1e4:.0f}万骤降",
                              "risk": "上涨动力衰竭，警惕冲高回落"})
        if change_pct < -3 and prev_flow < 0 and curr_flow > abs(prev_flow) * 0.5:
            divergences.append({"type": "底背离(资金回流)",
                              "detail": f"跌{change_pct:+.2f}%, 资金从流出转流入",
                              "risk": "下跌衰竭，关注反弹"})

    return {"has_divergence": len(divergences) > 0, "divergences": divergences}

# ============================================================
# Layer 3: 板块情绪
# ============================================================
def fetch_sector_sentiment(code):
    market = 1 if code.startswith(("6", "9")) else 0
    try:
        r = req_lib.get(f"https://push2.eastmoney.com/api/qt/slist/get",
                       params={"spt": "1", "fltt": "2", "invt": "2",
                               "fields": "f12,f14,f3,f100", "secid": f"{market}.{code}"},
                       headers={"Referer": "https://quote.eastmoney.com/"}, timeout=10)
        blocks_raw = r.json().get("data", []) or []
    except:
        blocks_raw = []

    stock_blocks = [{"code": it["f12"], "name": it["f14"], "change_pct": it.get("f3", 0)}
                    for it in blocks_raw if isinstance(it, dict)]

    if not stock_blocks:
        return {"error": "未找到概念板块", "blocks": [], "sentiment_score": 0}

    try:
        r2 = req_lib.get("https://push2.eastmoney.com/api/qt/clist/get",
                        params={"pn": "1", "pz": "500", "po": "0", "np": "1", "fltt": "2", "invt": "2",
                                "fs": "m:90+t:3", "fields": "f2,f3,f12,f14,f62,f104,f105"},
                        headers={"Referer": "https://data.eastmoney.com/"}, timeout=15)
        items = r2.json().get("data", {}).get("diff", []) or []
    except:
        items = []

    all_sectors = {}
    for it in items:
        bk_code = it.get("f12", "")
        if bk_code:
            main_net = it.get("f62") or 0
            all_sectors[bk_code] = {"code": bk_code, "name": it.get("f14", ""),
                                    "change_pct": it.get("f3", 0),
                                    "main_net_wan": round(main_net / 1e4, 1),
                                    "direction": "流入" if main_net > 0 else "流出",
                                    "up_count": it.get("f104", 0), "down_count": it.get("f105", 0)}

    sentiment_blocks = []
    for bk in stock_blocks[:8]:
        sd = all_sectors.get(bk["code"])
        if sd:
            sentiment_blocks.append(sd)
        else:
            sentiment_blocks.append({"code": bk["code"], "name": bk["name"],
                                     "change_pct": bk.get("change_pct", 0),
                                     "main_net_wan": 0, "direction": "未知",
                                     "up_count": 0, "down_count": 0})

    inflow_count = sum(1 for b in sentiment_blocks if b["main_net_wan"] > 0)
    total_blocks = len(sentiment_blocks)
    avg_change = sum(b["change_pct"] for b in sentiment_blocks) / max(total_blocks, 1)
    total_flow = sum(b["main_net_wan"] for b in sentiment_blocks)
    sentiment_score = round((inflow_count / max(total_blocks, 1)) * 50 + max(0, min(50, (avg_change + 5) * 5)), 1)

    if sentiment_score >= 75: level = "🔥 极热"
    elif sentiment_score >= 60: level = "🟢 偏热"
    elif sentiment_score >= 40: level = "🟡 中性"
    elif sentiment_score >= 25: level = "🔵 偏冷"
    else: level = "❄️ 极冷"

    return {"blocks": sentiment_blocks, "sentiment_score": sentiment_score, "level": level,
            "inflow_blocks": inflow_count, "total_blocks": total_blocks,
            "avg_change_pct": round(avg_change, 2), "total_sector_flow_wan": round(total_flow, 1),
            "data_basis": f"{inflow_count}/{total_blocks}板块流入, 板块资金{total_flow:+.0f}万, 平均涨跌{avg_change:+.2f}%"}

# ============================================================
# Layer 4: 消息面
# ============================================================
def fetch_intraday_news(code):
    cb = "jQuery_news"
    inner = json.dumps({
        "uid": "", "keyword": code, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                        "pageIndex": 1, "pageSize": 20, "preTag": "", "postTag": ""}},
    }, separators=(',', ':'))
    try:
        r = req_lib.get("https://search-api-web.eastmoney.com/search/jsonp",
                       params={"cb": cb, "param": inner},
                       headers={"Referer": "https://so.eastmoney.com/"}, timeout=10)
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        articles = json.loads(json_str).get("result", {}).get("cmsArticleWebOld", []) or []
    except:
        return {"today_count": 0, "highlights": []}

    today_str = datetime.now().strftime("%Y-%m-%d")
    news = []
    for a in articles:
        title = re.sub(r'<[^>]+>', '', a.get("title", ""))
        news.append({"title": title, "time": a.get("date", ""), "source": a.get("mediaName", ""),
                     "is_today": a.get("date", "").startswith(today_str)})

    today_news = [n for n in news if n["is_today"]]
    bullish_kw = ["增长", "突破", "中标", "订单", "扩产", "获批", "回购", "增持", "超预期"]
    bearish_kw = ["减持", "亏损", "下滑", "调查", "处罚", "诉讼", "违约", "暴雷", "退市"]

    highlights = []
    for n in today_news[:8]:
        sentiment = "neutral"
        if any(kw in n["title"] for kw in bullish_kw): sentiment = "bullish"
        elif any(kw in n["title"] for kw in bearish_kw): sentiment = "bearish"
        highlights.append({**n, "sentiment": sentiment})

    return {"today_count": len(today_news), "highlights": highlights,
            "bullish_count": sum(1 for h in highlights if h["sentiment"] == "bullish"),
            "bearish_count": sum(1 for h in highlights if h["sentiment"] == "bearish")}

# ============================================================
# Layer 5: 北向资金
# ============================================================
def fetch_north_bound_flow():
    hgt_net = sgt_net = 0.0
    try:
        r = req_lib.get("https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/hgt",
                       headers={"User-Agent": UA}, timeout=8)
        items = r.json().get("data", []) or []
        hgt_net = sum(it.get("net", 0) for it in (items if isinstance(items, list) else [])[-10:])
    except: pass
    try:
        r = req_lib.get("https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/sgt",
                       headers={"User-Agent": UA}, timeout=8)
        items = r.json().get("data", []) or []
        sgt_net = sum(it.get("net", 0) for it in (items if isinstance(items, list) else [])[-10:])
    except: pass

    total = hgt_net + sgt_net
    yi = total / 1e4
    if total > 5000: direction, signal = "大幅流入", "🟢 积极"
    elif total > 0: direction, signal = "小幅流入", "🟡 中性偏多"
    elif total > -5000: direction, signal = "小幅流出", "🟠 中性偏空"
    else: direction, signal = "大幅流出", "🔴 警惕"

    return {"total_net_yi": round(yi, 2), "direction": direction, "signal": signal,
            "data_basis": f"沪股通{hgt_net/1e4:+.2f}亿 + 深股通{sgt_net/1e4:+.2f}亿 = 北向合计{yi:+.2f}亿"}

# ============================================================
# Layer 6: 大盘强度
# ============================================================
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
        except: pass

    primary = "上证指数" if code.startswith(("6", "9")) else ("创业板指" if code.startswith("30") else "深证成指")
    bm_change = market_data.get(primary, {}).get("change_pct", 0)
    stock_change = quote.get("change_pct", 0)
    relative = stock_change - bm_change

    if bm_change > 1: env = "🟢 大盘强势"
    elif bm_change > 0: env = "🟡 大盘微涨"
    elif bm_change > -1: env = "🟠 大盘微跌"
    else: env = "🔴 大盘弱势"

    if relative > 3: rating = "🚀 显著跑赢"
    elif relative > 1: rating = "✅ 跑赢大盘"
    elif relative > -1: rating = "➖ 与大盘同步"
    elif relative > -3: rating = "⚠️ 跑输大盘"
    else: rating = "🔴 显著跑输"

    return {"benchmark": primary, "benchmark_change": round(bm_change, 2), "market_env": env,
            "relative_strength": round(relative, 2), "relative_rating": rating,
            "market_detail": {k: round(v.get("change_pct", 0), 2) for k, v in market_data.items()},
            "data_basis": f"{primary}{bm_change:+.2f}%, 个股{stock_change:+.2f}%, 相对强弱{relative:+.2f}%"}

# ============================================================
# Layer 7: 市场广度
# ============================================================
def fetch_market_breadth():
    try:
        r = req_lib.get("https://push2.eastmoney.com/api/qt/clist/get",
                       params={"pn": "1", "pz": "1", "po": "0", "np": "1", "fltt": "2", "invt": "2",
                               "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23", "fields": "f104,f105"},
                       headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        items = r.json().get("data", {}).get("diff", [])
        up = sum(it.get("f104", 0) for it in items) if items else 0
        down = sum(it.get("f105", 0) for it in items) if items else 0
    except:
        up = down = 0

    try:
        r = req_lib.get("https://push2ex.eastmoney.com/getTopicZTPool",
                       params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1", "sort": "fbt", "fbt": "desc"},
                       headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        limit_up = r.json().get("data", {}).get("total", 0) or 0
    except: limit_up = 0

    try:
        r = req_lib.get("https://push2ex.eastmoney.com/getTopicDTPool",
                       params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1", "sort": "fund", "fund": "desc"},
                       headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        limit_down = r.json().get("data", {}).get("total", 0) or 0
    except: limit_down = 0

    total = up + down
    up_ratio = up / max(total, 1) * 100

    if up_ratio >= 70: breadth_level, breadth_score = "🟢 普涨格局", 85
    elif up_ratio >= 55: breadth_level, breadth_score = "🟡 涨多跌少", 60
    elif up_ratio >= 45: breadth_level, breadth_score = "🟠 分化格局", 40
    elif up_ratio >= 30: breadth_level, breadth_score = "🔴 跌多涨少", 20
    else: breadth_level, breadth_score = "💀 普跌格局", 5

    limit_ratio = limit_up / max(limit_down, 1)
    if limit_ratio >= 3: money_effect = "🔥 强赚钱效应"
    elif limit_ratio >= 1.5: money_effect = "✅ 赚钱效应良好"
    elif limit_ratio >= 1: money_effect = "➖ 赚钱效应中性"
    elif limit_ratio >= 0.5: money_effect = "⚠️ 亏钱效应显现"
    else: money_effect = "💀 强亏钱效应"

    return {"up_count": up, "down_count": down, "up_ratio_pct": round(up_ratio, 1),
            "breadth_level": breadth_level, "breadth_score": breadth_score,
            "limit_up_count": limit_up, "limit_down_count": limit_down,
            "limit_ratio": round(limit_ratio, 1), "money_effect": money_effect,
            "data_basis": f"涨{up}跌{down}({up_ratio:.1f}%), 涨停{limit_up}/跌停{limit_down}, {money_effect}"}

# ============================================================
# Layer 8: 概率引擎
# ============================================================
def generate_probability_scenarios(flow_data, quote, sector_data, news_data, party_data, divergence,
                                   north_bound, market_strength, market_breadth):
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

    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)

    sentiment_score = sector_data.get("sentiment_score", 50)
    inflow_blocks = sector_data.get("inflow_blocks", 0)
    total_blocks = sector_data.get("total_blocks", 1)

    news_bullish = news_data.get("bullish_count", 0)
    news_bearish = news_data.get("bearish_count", 0)

    has_divergence = divergence.get("has_divergence", False)
    div_type = divergence["divergences"][0]["type"] if has_divergence and divergence.get("divergences") else ""

    nb = north_bound or {}
    nb_net_yi = nb.get("total_net_yi", 0)
    nb_direction = nb.get("direction", "")

    ms = market_strength or {}
    relative_strength = ms.get("relative_strength", 0)
    market_env = ms.get("market_env", "")

    mb = market_breadth or {}
    up_ratio = mb.get("up_ratio_pct", 50)
    limit_ratio = mb.get("limit_ratio", 1)
    money_effect = mb.get("money_effect", "")

    scenarios = []

    # === 情景A: 强势上涨 ===
    a_cond, a_score = [], 0

    if main_net_wan > 500 and direction == "流入":
        a_score += 25; a_cond.append({"condition": "主力净流入>500万", "threshold": ">500万",
                                      "actual": f"{main_net_wan:+.0f}万", "met": True, "weight": 25})
    else:
        a_cond.append({"condition": "主力净流入>500万", "threshold": ">500万",
                       "actual": f"{main_net_wan:+.0f}万", "met": False, "weight": 25})

    inst_dom = inst_net > 200 and inst_net > abs(hm_net) and inst_net > abs(retail_net)
    if inst_dom:
        a_score += 20; a_cond.append({"condition": "机构主导(>200万且>游资+散户)", "threshold": "机构>200万且最大",
                                      "actual": f"机构{inst_net:+.0f}万,游资{hm_net:+.0f}万,散户{retail_net:+.0f}万", "met": True, "weight": 20})
    else:
        a_cond.append({"condition": "机构主导(>200万且>游资+散户)", "threshold": "机构>200万且最大",
                       "actual": f"机构{inst_net:+.0f}万,游资{hm_net:+.0f}万,散户{retail_net:+.0f}万", "met": False, "weight": 20})

    if sentiment_score >= 60:
        a_score += 15; a_cond.append({"condition": "板块情绪≥60", "threshold": "≥60",
                                      "actual": f"{sentiment_score:.0f}分({inflow_blocks}/{total_blocks}板块流入)", "met": True, "weight": 15})
    else:
        a_cond.append({"condition": "板块情绪≥60", "threshold": "≥60", "actual": f"{sentiment_score:.0f}分", "met": False, "weight": 15})

    vol_ok = 1.2 <= vol_ratio <= 5 and turnover < 15
    if vol_ok:
        a_score += 15; a_cond.append({"condition": "量能配合(量比1.2~5,换手<15%)", "threshold": "量比1.2-5,换手<15%",
                                      "actual": f"量比{vol_ratio},换手{turnover}%", "met": True, "weight": 15})
    else:
        a_cond.append({"condition": "量能配合(量比1.2~5,换手<15%)", "threshold": "量比1.2-5,换手<15%",
                       "actual": f"量比{vol_ratio},换手{turnover}%", "met": False, "weight": 15})

    no_top = not has_divergence or "顶背离" not in div_type
    if no_top:
        a_score += 15; a_cond.append({"condition": "无顶背离", "threshold": "无顶背离",
                                      "actual": f"背离:{'有' if has_divergence else '无'}", "met": True, "weight": 15})
    else:
        a_cond.append({"condition": "无顶背离", "threshold": "无顶背离", "actual": div_type, "met": False, "weight": 15})

    if "加速流入" in acceleration:
        a_score += 10; a_cond.append({"condition": "资金加速流入", "threshold": "后半段斜率>前半段×1.5",
                                      "actual": f"前{first_slope}→后{second_slope}万/分", "met": True, "weight": 10})
    else:
        a_cond.append({"condition": "资金加速流入", "threshold": "后半段斜率>前半段×1.5",
                       "actual": f"前{first_slope}→后{second_slope}万/分", "met": False, "weight": 10})

    if nb_net_yi > 1:
        a_score += 10; a_cond.append({"condition": "北向流入>1亿", "threshold": ">1亿",
                                      "actual": f"{nb_net_yi:+.2f}亿", "met": True, "weight": 10})
    elif nb_net_yi < -5:
        a_score -= 5; a_cond.append({"condition": "北向未大幅流出", "threshold": ">-5亿",
                                     "actual": f"{nb_net_yi:+.2f}亿(⚠️扣分)", "met": False, "weight": 10})
    else:
        a_cond.append({"condition": "北向不拖累", "threshold": ">-5亿", "actual": f"{nb_net_yi:+.2f}亿", "met": nb_net_yi > -5, "weight": 10})

    if relative_strength > 1 and "弱势" not in market_env:
        a_score += 5; a_cond.append({"condition": "大盘配合+个股跑赢", "threshold": "相对强度>1%",
                                     "actual": f"{market_env},相对{relative_strength:+.2f}%", "met": True, "weight": 5})
    else:
        a_cond.append({"condition": "大盘配合+个股跑赢", "threshold": "相对强度>1%",
                       "actual": f"{market_env},相对{relative_strength:+.2f}%", "met": False, "weight": 5})

    if up_ratio >= 45 and "亏钱" not in money_effect:
        a_score += 5; a_cond.append({"condition": "市场广度不差(上涨>45%)", "threshold": "上涨≥45%",
                                     "actual": f"涨{up_ratio:.0f}%,{money_effect}", "met": True, "weight": 5})
    else:
        a_score -= 3; a_cond.append({"condition": "市场广度不差", "threshold": "上涨≥45%",
                                     "actual": f"涨{up_ratio:.0f}%,{money_effect}(⚠️扣分)", "met": False, "weight": 5})

    if vol_ratio >= 0.8 and turnover >= 0.5:
        a_score += 2; a_cond.append({"condition": "量能参考(量比≥0.8+换手≥0.5%)", "threshold": "量比≥0.8",
                                     "actual": f"量比{vol_ratio},换手{turnover}%", "met": True, "weight": 2})
    else:
        a_cond.append({"condition": "量能参考(量比≥0.8+换手≥0.5%)", "threshold": "量比≥0.8",
                       "actual": f"量比{vol_ratio},换手{turnover}%", "met": False, "weight": 2})

    bullish_dims = sum([1 if main_net_wan > 300 else 0, 1 if change_pct > 0 else 0,
                        1 if sentiment_score >= 50 else 0, 1 if news_bullish > news_bearish else 0,
                        1 if nb_net_yi > 0 else 0, 1 if relative_strength > 0 else 0, 1 if up_ratio >= 45 else 0])
    if bullish_dims >= 6:
        a_score += 10; a_cond.append({"condition": "七维共振(≥6维看多)", "threshold": "≥6/7",
                                      "actual": f"{bullish_dims}/7维", "met": True, "weight": 10})
    elif bullish_dims >= 5:
        a_score += 5; a_cond.append({"condition": "五维共振(≥5维看多)", "threshold": "≥5/7",
                                     "actual": f"{bullish_dims}/7维", "met": True, "weight": 5})

    scenarios.append({"name": "情景A: 强势上涨",
                      "description": "主力持续流入+机构主导+板块共振+量能配合 → 当日继续走强",
                      "raw_score": a_score, "conditions": a_cond,
                      "met_count": sum(1 for c in a_cond if c["met"]), "total_conditions": len(a_cond),
                      "historical_ref": {"rule": "机构主导+板块共振+量能配合 → 当日走强",
                                         "historical_win_rate": "约65-70%"},
                      "failure_conditions": ["午后机构资金转流出", "板块情绪骤降", "突发利空"]})

    # === 情景B: 震荡横盘 ===
    b_cond, b_score = [], 0

    if abs(main_net_wan) < 300:
        b_score += 30; b_cond.append({"condition": "主力无方向(|净流入|<300万)", "threshold": "|<300万",
                                      "actual": f"{main_net_wan:+.0f}万", "met": True, "weight": 30})
    else:
        b_cond.append({"condition": "主力无方向(|净流入|<300万)", "threshold": "|<300万",
                       "actual": f"{main_net_wan:+.0f}万", "met": False, "weight": 30})

    if amplitude < 3:
        b_score += 25; b_cond.append({"condition": "振幅<3%(窄幅)", "threshold": "<3%",
                                      "actual": f"{amplitude}%", "met": True, "weight": 25})
    else:
        b_cond.append({"condition": "振幅<3%(窄幅)", "threshold": "<3%", "actual": f"{amplitude}%", "met": False, "weight": 25})

    if 35 <= sentiment_score <= 65:
        b_score += 25; b_cond.append({"condition": "板块情绪35~65(中性)", "threshold": "35-65",
                                      "actual": f"{sentiment_score:.0f}分", "met": True, "weight": 25})
    else:
        b_cond.append({"condition": "板块情绪35~65(中性)", "threshold": "35-65",
                       "actual": f"{sentiment_score:.0f}分", "met": False, "weight": 25})

    if news_bullish == 0 and news_bearish == 0:
        b_score += 15; b_cond.append({"condition": "无消息催化", "threshold": "0条",
                                      "actual": f"利好{news_bullish}/利空{news_bearish}", "met": True, "weight": 15})
    else:
        b_cond.append({"condition": "无消息催化", "threshold": "0条",
                       "actual": f"利好{news_bullish}/利空{news_bearish}", "met": False, "weight": 15})

    if abs(nb_net_yi) < 3:
        b_score += 10; b_cond.append({"condition": "北向无方向(±3亿)", "threshold": "|北向|<3亿",
                                      "actual": f"{nb_net_yi:+.2f}亿", "met": True, "weight": 10})
    else:
        b_cond.append({"condition": "北向无方向(±3亿)", "threshold": "|北向|<3亿",
                       "actual": f"{nb_net_yi:+.2f}亿", "met": False, "weight": 10})

    if abs(relative_strength) < 1.5 and abs(ms.get("benchmark_change", 0)) < 1:
        b_score += 10; b_cond.append({"condition": "大盘+个股中性", "threshold": "|相对|<1.5%,|大盘|<1%",
                                      "actual": f"大盘{ms.get('benchmark_change',0):+.2f}%,相对{relative_strength:+.2f}%", "met": True, "weight": 10})
    else:
        b_cond.append({"condition": "大盘+个股中性", "threshold": "|相对|<1.5%",
                       "actual": f"大盘{ms.get('benchmark_change',0):+.2f}%,相对{relative_strength:+.2f}%", "met": False, "weight": 10})

    if 40 <= up_ratio <= 60:
        b_score += 10; b_cond.append({"condition": "市场广度中性(涨40-60%)", "threshold": "涨40-60%",
                                      "actual": f"涨{up_ratio:.0f}%", "met": True, "weight": 10})
    else:
        b_cond.append({"condition": "市场广度中性(涨40-60%)", "threshold": "涨40-60%",
                       "actual": f"涨{up_ratio:.0f}%", "met": False, "weight": 10})

    scenarios.append({"name": "情景B: 震荡横盘",
                      "description": "资金方向不明+振幅小+情绪中性+无催化 → 窄幅震荡",
                      "raw_score": b_score, "conditions": b_cond,
                      "met_count": sum(1 for c in b_cond if c["met"]), "total_conditions": len(b_cond),
                      "historical_ref": {"rule": "主力无方向+振幅<3% → 后续2h横盘", "historical_win_rate": "约55-60%"},
                      "failure_conditions": ["突发消息催化", "大单资金突然涌入/涌出"]})

    # === 情景C: 冲高回落 ===
    c_cond, c_score = [], 0

    if change_pct > 3 and ("流出" in acceleration or "减缓" in acceleration):
        c_score += 30; c_cond.append({"condition": "涨>3%且资金转弱", "threshold": "涨>3%+资金减缓",
                                      "actual": f"涨{change_pct:+.2f}%,{acceleration}", "met": True, "weight": 30})
    else:
        c_cond.append({"condition": "涨>3%且资金转弱", "threshold": "涨>3%+资金减缓",
                       "actual": f"涨{change_pct:+.2f}%,{acceleration}", "met": False, "weight": 30})

    if has_divergence and "顶背离" in div_type:
        c_score += 25; c_cond.append({"condition": "顶背离(资金衰竭)", "threshold": "顶背离",
                                      "actual": div_type, "met": True, "weight": 25})
    else:
        c_cond.append({"condition": "顶背离(资金衰竭)", "threshold": "顶背离", "actual": "无", "met": False, "weight": 25})

    if inst_net < -100 and retail_net > 200:
        c_score += 25; c_cond.append({"condition": "机构派发(<-100万)+散户接盘(>+200万)", "threshold": "机构<-100万,散户>+200万",
                                      "actual": f"机构{inst_net:+.0f}万,散户{retail_net:+.0f}万", "met": True, "weight": 25})
    else:
        c_cond.append({"condition": "机构派发+散户接盘", "threshold": "机构<-100万,散户>+200万",
                       "actual": f"机构{inst_net:+.0f}万,散户{retail_net:+.0f}万", "met": False, "weight": 25})

    if turnover > 10:
        c_score += 15; c_cond.append({"condition": "换手率>10%(异常)", "threshold": ">10%",
                                      "actual": f"{turnover}%", "met": True, "weight": 15})
    else:
        c_cond.append({"condition": "换手率>10%(异常)", "threshold": ">10%", "actual": f"{turnover}%", "met": False, "weight": 15})

    if nb_net_yi < -2:
        c_score += 10; c_cond.append({"condition": "北向流出(<-2亿)", "threshold": "<-2亿",
                                      "actual": f"{nb_net_yi:+.2f}亿", "met": True, "weight": 10})
    else:
        c_cond.append({"condition": "北向配合", "threshold": "<-2亿更确认",
                       "actual": f"{nb_net_yi:+.2f}亿", "met": False, "weight": 10})

    if change_pct > 2 and relative_strength > 1 and "弱势" in market_env:
        c_score += 10; c_cond.append({"condition": "个股高位+大盘走弱", "threshold": "涨>2%+大盘弱势",
                                      "actual": f"涨{change_pct:+.2f}%,{market_env}", "met": True, "weight": 10})
    else:
        c_cond.append({"condition": "个股高位+大盘走弱", "threshold": "涨>2%+大盘弱势",
                       "actual": f"涨{change_pct:+.2f}%,{market_env}", "met": False, "weight": 10})

    if limit_ratio < 1.5 or "亏钱" in money_effect:
        c_score += 10; c_cond.append({"condition": "赚钱效应转弱", "threshold": "涨跌停比<1.5",
                                      "actual": f"涨跌停比{limit_ratio},{money_effect}", "met": True, "weight": 10})
    else:
        c_cond.append({"condition": "赚钱效应转弱", "threshold": "涨跌停比<1.5",
                       "actual": f"涨跌停比{limit_ratio}", "met": False, "weight": 10})

    scenarios.append({"name": "情景C: 冲高回落",
                      "description": "高位+资金转向/顶背离/机构派发 → 警惕回落",
                      "raw_score": c_score, "conditions": c_cond,
                      "met_count": sum(1 for c in c_cond if c["met"]), "total_conditions": len(c_cond),
                      "historical_ref": {"rule": "涨超3%+资金转流出 → 午后回落", "historical_win_rate": "约55-65%"},
                      "failure_conditions": ["超预期利好", "板块集体暴动"]})

    # === 情景D: 弱势下跌 ===
    d_cond, d_score = [], 0

    if main_net_wan < -500 and direction == "流出":
        d_score += 30; d_cond.append({"condition": "主力净流出>500万", "threshold": "<-500万",
                                      "actual": f"{main_net_wan:+.0f}万", "met": True, "weight": 30})
    else:
        d_cond.append({"condition": "主力净流出>500万", "threshold": "<-500万",
                       "actual": f"{main_net_wan:+.0f}万", "met": False, "weight": 30})

    if sentiment_score < 40:
        d_score += 25; d_cond.append({"condition": "板块情绪<40(偏冷)", "threshold": "<40",
                                      "actual": f"{sentiment_score:.0f}分", "met": True, "weight": 25})
    else:
        d_cond.append({"condition": "板块情绪<40(偏冷)", "threshold": "<40",
                       "actual": f"{sentiment_score:.0f}分", "met": False, "weight": 25})

    if "加速流出" in acceleration:
        d_score += 25; d_cond.append({"condition": "资金加速流出", "threshold": "后半段斜率<前半段×0.3",
                                      "actual": f"前{first_slope}→后{second_slope}万/分", "met": True, "weight": 25})
    else:
        d_cond.append({"condition": "资金加速流出", "threshold": "后半段斜率<前半段×0.3",
                       "actual": f"前{first_slope}→后{second_slope}万/分", "met": False, "weight": 25})

    if news_bearish > 0:
        d_score += 15; d_cond.append({"condition": "有利空消息", "threshold": "利空>0",
                                      "actual": f"利空{news_bearish}条", "met": True, "weight": 15})
    else:
        d_cond.append({"condition": "有利空消息", "threshold": "利空>0", "actual": "无", "met": False, "weight": 15})

    if nb_net_yi < -5:
        d_score += 10; d_cond.append({"condition": "北向大幅流出(<-5亿)", "threshold": "<-5亿",
                                      "actual": f"{nb_net_yi:+.2f}亿", "met": True, "weight": 10})
    else:
        d_cond.append({"condition": "北向大幅流出", "threshold": "<-5亿",
                       "actual": f"{nb_net_yi:+.2f}亿", "met": False, "weight": 10})

    if "弱势" in market_env and relative_strength < -0.5:
        d_score += 10; d_cond.append({"condition": "大盘弱势+个股跑输", "threshold": "相对<-0.5%",
                                      "actual": f"{market_env},相对{relative_strength:+.2f}%", "met": True, "weight": 10})
    else:
        d_cond.append({"condition": "大盘弱势+个股跑输", "threshold": "相对<-0.5%",
                       "actual": f"{market_env},相对{relative_strength:+.2f}%", "met": False, "weight": 10})

    if up_ratio < 35 or limit_ratio < 0.8:
        d_score += 10; d_cond.append({"condition": "普跌(上涨<35%或涨跌停比<0.8)", "threshold": "上涨<35%",
                                      "actual": f"涨{up_ratio:.0f}%,涨跌停比{limit_ratio}", "met": True, "weight": 10})
    else:
        d_cond.append({"condition": "普跌(上涨<35%)", "threshold": "上涨<35%",
                       "actual": f"涨{up_ratio:.0f}%", "met": False, "weight": 10})

    bearish_dims = sum([1 if main_net_wan < -300 else 0, 1 if change_pct < 0 else 0,
                        1 if sentiment_score < 40 else 0, 1 if news_bearish > 0 else 0,
                        1 if nb_net_yi < 0 else 0, 1 if relative_strength < 0 else 0, 1 if up_ratio < 45 else 0])
    if bearish_dims >= 5:
        d_score += 10

    scenarios.append({"name": "情景D: 弱势下跌",
                      "description": "主力持续流出+板块冷+加速流出 → 继续走弱",
                      "raw_score": d_score, "conditions": d_cond,
                      "met_count": sum(1 for c in d_cond if c["met"]), "total_conditions": len(d_cond),
                      "historical_ref": {"rule": "主力流出+板块<40 → 当日收阴", "historical_win_rate": "约60-70%"},
                      "failure_conditions": ["午后重大利好", "国家队护盘"]})

    # 归一化
    total_score = sum(s["raw_score"] for s in scenarios)
    for s in scenarios:
        s["probability"] = round(s["raw_score"] / total_score * 100, 1) if total_score > 0 else 0

    freshness = check_data_freshness()
    return {"scenarios": sorted(scenarios, key=lambda x: x["probability"], reverse=True),
            "primary_scenario": scenarios[0] if scenarios else None,
            "data_points": data_points,
            "freshness": {"phase": freshness["phase"], "phase_name": freshness["phase_name"]}}

# ============================================================
# Layer 9: 买卖信号
# ============================================================
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
    hm_net = party_data.get("hot_money", {}).get("net_wan", 0)
    retail_net = party_data.get("retail", {}).get("net_wan", 0)
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
    money_effect = mb.get("money_effect", "")

    buy_signals, sell_signals = [], []

    # 强买入
    strong_buy_met = sum([
        primary_prob >= 60 and "情景A" in primary_name,
        inst_net > 200, sentiment_score >= 60, change_pct < 5,
        "加速流入" in acceleration,
    ])
    if strong_buy_met >= 4:
        buy_signals.append({"level": "🟢🟢🟢 强买入参考", "strength": strong_buy_met,
                           "action": "可考虑逢低建仓/加仓",
                           "stop_loss": f"跌破{price*0.97:.2f}(-3%)果断离场",
                           "principle": f"宁可少挣: {strong_buy_met}/5条件满足,不追高"})

    # 中等买入
    medium_buy_met = sum([
        primary_prob >= 45 and "情景A" in primary_name,
        inst_net > 100, sentiment_score >= 50, change_pct < 7,
    ])
    if medium_buy_met >= 3 and strong_buy_met < 4:
        buy_signals.append({"level": "🟢🟢 中等买入参考", "strength": medium_buy_met,
                           "action": "可小仓位试探(30-50%),等更多信号",
                           "stop_loss": f"跌破{price*0.95:.2f}(-5%)止损",
                           "principle": "宁可少挣: 先小仓试错,确认后再加仓"})

    # 弱买入
    if primary_prob >= 30 and "情景D" in primary_name and main_net_wan > -300 and sentiment_score >= 30:
        buy_signals.append({"level": "🟢 弱买入参考(左侧反弹)", "strength": 1,
                           "action": "仅极度激进者可关注,大多数人等企稳确认",
                           "stop_loss": f"跌破{price*0.97:.2f}(-3%)强制止损",
                           "principle": "宁可少挣: 宁可等企稳再追,不提前抄底"})

    if not buy_signals:
        buy_signals.append({"level": "⚪ 暂不建议买入",
                           "action": "继续观察,等资金+情绪+价格共振",
                           "principle": "宁可少挣: 不买至少不亏钱"})

    # 强卖出
    strong_sell_met = sum([
        primary_prob >= 50 and ("情景C" in primary_name or "情景D" in primary_name),
        inst_net < -200, "加速流出" in acceleration,
    ])
    if strong_sell_met >= 3:
        sell_signals.append({"level": "🔴🔴🔴 强卖出参考", "strength": strong_sell_met,
                           "action": "建议果断减仓/清仓,不在下跌中补仓",
                           "risk_note": f"已流出{abs(main_net_wan):.0f}万,继续持有可能更大回撤",
                           "principle": "宁可少亏: 卖了少亏比扛着大亏好"})

    # 中等卖出
    medium_sell_met = sum([
        ("情景C" in primary_name and primary_prob >= 35) or ("情景D" in primary_name and primary_prob >= 35),
        inst_net < -100 or (inst_net < 0 and retail_net > 100),
    ])
    if medium_sell_met >= 2 and strong_sell_met < 3:
        sell_signals.append({"level": "🔴🔴 中等卖出参考", "strength": medium_sell_met,
                           "action": "建议逐步减仓,至少到半仓以下",
                           "risk_note": f"机构{inst_net:+.0f}万,散户{'接盘' if retail_net>100 else ''}{retail_net:+.0f}万",
                           "principle": "宁可少亏: 卖一半留一半"})

    # 高位止盈
    if change_pct > 8 and ("流出" in direction or "减缓" in acceleration):
        sell_signals.append({"level": "🔴 弱卖出参考(高位止盈)",
                           "action": "可考虑部分止盈,锁定利润",
                           "principle": "宁可少挣: 落袋为安"})

    if not sell_signals:
        sell_signals.append({"level": "⚪ 暂不需卖出",
                           "action": "继续持有观察,关注资金是否转弱",
                           "principle": "保持警觉,一旦出现卖出条件果断行动"})

    # 持有参考
    if "情景A" in primary_name and primary_prob >= 50:
        hold = {"level": "✅ 可继续持有",
                "reason": f"强势概率{primary_prob:.0f}%,主力{main_net_wan:+.0f}万",
                "watch_points": ["午后资金是否转流出", "是否出现顶背离"]}
    elif "情景B" in primary_name:
        hold = {"level": "⏸️ 持有观望",
                "reason": f"震荡,主力{main_net_wan:+.0f}万,振幅{amplitude}%",
                "watch_points": ["突破方向", "是否有催化"]}
    else:
        hold = {"level": "⚠️ 审视持仓",
                "reason": f"风险情景({primary_name}{primary_prob:.0f}%),机构{inst_net:+.0f}万",
                "watch_points": ["触发止损则果断执行", "等情景A信号再考虑加仓"]}

    # 综合
    strongest_buy = buy_signals[0]["level"]
    strongest_sell = sell_signals[0]["level"]
    if "强买入" in strongest_buy and "暂不需卖出" in strongest_sell:
        overall = f"总体偏多: 主力净流入{main_net_wan:+.0f}万,板块情绪{sentiment_score:.0f}分。可逢低参与。"
    elif "强卖出" in strongest_sell:
        overall = f"总体偏空: 主力净流出{abs(main_net_wan):.0f}万,机构{abs(inst_net):.0f}万。建议减仓或观望。"
    elif "中等卖出" in strongest_sell:
        overall = f"总体谨慎: 机构{inst_net:+.0f}万,散户{retail_net:+.0f}万。持有者审视持仓。"
    elif "中等买入" in strongest_buy:
        overall = f"总体中性偏多: 主力{main_net_wan:+.0f}万。可小仓试探,严格止损。"
    else:
        overall = f"总体中性: 主力{main_net_wan:+.0f}万,信号不明确。建议观望。"

    return {"buy_signals": buy_signals, "sell_signals": sell_signals, "hold_verdict": hold,
            "overall_verdict": overall,
            "data_summary": {"main_net_wan": main_net_wan, "inst_net_wan": inst_net,
                            "retail_net_wan": retail_net, "sentiment_score": sentiment_score,
                            "change_pct": change_pct, "turnover_pct": turnover, "vol_ratio": vol_ratio,
                            "acceleration": acceleration, "data_points": data_points}}

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("=" * 70)
    print(f"  📊 盘中实时交易信号: {NAME}({CODE})")
    print(f"  分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    freshness = check_data_freshness()
    print(f"\n  ⏱️ 时效性: {freshness['phase_name']}")

    # 1. 行情
    print(f"\n[1/7] 实时行情...", end=" ")
    quote = fetch_realtime_quote(CODE)
    if "error" in quote:
        print(f"❌ {quote['error']}"); sys.exit(1)
    print(f"✅ {quote['name']} 最新{quote['price']:.2f} 涨跌{quote['change_pct']:+.2f}% 振幅{quote['amplitude']:.2f}%")
    print(f"  换手{quote['turnover_pct']:.2f}% 量比{quote['vol_ratio']:.2f} 成交额{quote['amount']:.0f}万")

    # 2. 资金流
    print(f"[2/7] 分钟级资金流...", end=" ")
    flow = fetch_minute_fund_flow(CODE)
    if "error" in flow:
        print(f"❌ {flow['error']}"); sys.exit(1)
    fs = flow["summary"]
    ft = flow["trend"]
    print(f"✅ {fs['first_time']}→{fs['last_time']} ({fs['data_points']}分钟)")
    print(f"  主力: {fs['total_main_net_wan']:+.0f}万 | 机构: {fs['total_super_net_wan']:+.0f}万 | 游资: {fs['total_large_net_wan']:+.0f}万 | 散户: {(fs['total_mid_net_wan'] or 0)+(fs['total_small_net_wan'] or 0):+.0f}万")
    print(f"  趋势: {ft['direction']} | {ft['acceleration']}")

    parties = classify_intraday_parties(flow)
    v = parties["verdict"]
    print(f"  博弈: {v['level']} {v['scenario']}")

    divergence = detect_fund_price_divergence(flow, quote)
    if divergence["has_divergence"]:
        for d in divergence["divergences"]:
            print(f"  ⚠️ {d['type']}: {d['detail']}")

    # 3. 板块情绪
    print(f"[3/7] 板块情绪...", end=" ")
    sector = fetch_sector_sentiment(CODE)
    if "error" in sector:
        print(f"⚠️ {sector['error']}")
    else:
        print(f"✅ 情绪{sector['sentiment_score']:.0f}/100 {sector['level']}")
        print(f"  {sector['data_basis']}")
        for bk in sector["blocks"][:5]:
            print(f"  {bk['name']}: 主力{bk['main_net_wan']:+.0f}万 涨{bk['change_pct']:+.2f}%")

    # 4. 消息
    print(f"[4/7] 消息面...", end=" ")
    news = fetch_intraday_news(CODE)
    print(f"✅ 今日{news['today_count']}条(利好{news['bullish_count']}/利空{news['bearish_count']})")
    for h in (news.get("highlights") or [])[:3]:
        emoji = "🟢" if h["sentiment"]=="bullish" else ("🔴" if h["sentiment"]=="bearish" else "⚪")
        print(f"  {emoji} {h['time']} | {h['source']}: {h['title'][:50]}")

    # 5. 北向
    print(f"[5/7] 北向资金...", end=" ")
    north_bound = fetch_north_bound_flow()
    print(f"✅ {north_bound['data_basis']}")
    print(f"  {north_bound['direction']} {north_bound['signal']}")

    # 6. 大盘
    print(f"[6/7] 大盘强度...", end=" ")
    ms = fetch_market_strength(CODE, quote)
    print(f"✅ {ms['data_basis']}")
    print(f"  {ms['relative_rating']} | {ms['market_env']}")
    for k, v in ms.get("market_detail", {}).items():
        print(f"  {k}: {v:+.2f}%")

    # 7. 广度
    print(f"[7/7] 市场广度...", end=" ")
    mb = fetch_market_breadth()
    print(f"✅ {mb['data_basis']}")
    print(f"  {mb['breadth_level']} ({mb['breadth_score']}分)")

    # 8. 概率
    print(f"\n{'='*70}")
    print(f"  🔮 七维概率预判 (时效性: {freshness['phase_name']})")
    print(f"{'='*70}")
    scenarios = generate_probability_scenarios(flow, quote, sector, news, parties, divergence,
                                               north_bound, ms, mb)

    for sc in scenarios["scenarios"]:
        prob = sc["probability"]
        icon = "🔥" if prob >= 50 else ("📊" if prob >= 25 else "🔍")
        print(f"\n  {icon} {sc['name']} → 概率: {prob:.0f}% ({sc['met_count']}/{sc['total_conditions']}条件)")
        for c in sc["conditions"]:
            s = "✅" if c["met"] else "❌"
            print(f"     {s} {c['condition']}: 阈值{c.get('threshold','')}, 当前={c.get('actual','')}")
        print(f"     历史胜率: {sc['historical_ref']['historical_win_rate']}")
        if sc.get("failure_conditions"):
            print(f"     失效: {'; '.join(sc['failure_conditions'])}")

    # 9. 信号
    print(f"\n{'='*70}")
    print(f"  ⚡ 买卖时机参考（数据说话）")
    print(f"{'='*70}")
    signals = generate_trading_signals(scenarios["scenarios"], flow, quote, parties, sector, news,
                                       north_bound, ms, mb)

    print(f"\n  📥 买入参考:")
    for bs in signals["buy_signals"]:
        print(f"    {bs['level']}")
        print(f"    操作: {bs.get('action','')}")
        if bs.get("stop_loss"): print(f"    止损: {bs['stop_loss']}")
        print(f"    原则: {bs.get('principle','')}")

    print(f"\n  📤 卖出参考:")
    for ss in signals["sell_signals"]:
        print(f"    {ss['level']}")
        print(f"    操作: {ss.get('action','')}")
        if ss.get("risk_note"): print(f"    风险: {ss['risk_note']}")
        print(f"    原则: {ss.get('principle','')}")

    hv = signals.get("hold_verdict", {})
    if hv:
        print(f"\n  📌 持有参考: {hv.get('level','')}")
        print(f"    {hv.get('reason','')}")
        for wp in hv.get("watch_points", []): print(f"    👁 {wp}")

    print(f"\n  {'─'*60}")
    print(f"  🎯 综合评估: {signals['overall_verdict']}")

    ds = signals["data_summary"]
    print(f"\n  📋 七维摘要:")
    print(f"    资金: 主力{ds['main_net_wan']:+.0f}万 机构{ds['inst_net_wan']:+.0f}万 涨跌{ds['change_pct']:+.2f}% 换手{ds['turnover_pct']}%")
    print(f"    北向: {north_bound['total_net_yi']:+.2f}亿 {north_bound['direction']}")
    print(f"    大盘: {ms['data_basis']}")
    print(f"    广度: {mb['data_basis']}")
    print(f"    情绪: {ds['sentiment_score']:.0f}分 量比{ds['vol_ratio']}")

    print(f"\n{'='*70}")
    print(f"  ⚠️ 研究声明: 信号基于公开API实时数据,不构成投资建议")
    print(f"  核心原则: 宁可少挣,宁可少亏。买入卖出,数据说话。")
    print(f"{'='*70}")

    # 保存
    try:
        date_str = datetime.now().strftime("%Y-%m-%d")
        dir_path = os.path.join(OUTPUT_BASE, f"{date_str}-{NAME}-盘中信号")
        os.makedirs(dir_path, exist_ok=True)
        data_json = {
            "target": {"type": "个股", "code": CODE, "name": NAME},
            "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "quote": quote, "fund_flow_summary": flow.get("summary", {}),
            "fund_flow_trend": flow.get("trend", {}), "parties": parties,
            "sector_sentiment": sector, "scenarios": scenarios,
            "signals_data_summary": signals.get("data_summary", {}),
            "minute_data": [
                {"time": m["time"], "main_net": m["main_net"],
                 "super_net": m["super_net"], "large_net": m["large_net"]}
                for m in flow.get("minutes", [])[-60:]
            ],
        }
        with open(os.path.join(dir_path, "data.json"), "w", encoding="utf-8") as f:
            json.dump(data_json, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n✅ 数据已保存: {dir_path}/data.json")
    except Exception as e:
        print(f"\n⚠️ 保存失败: {e}")
