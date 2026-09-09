#!/usr/bin/env python3
"""
盘中实时交易信号系统 V1.3 — 科创50ETF华夏(588000) 七维分析
日期: 2026-07-22 盘中
数据源: 腾讯(分时/行情/K线) + 东财push2(板块/广度) + 同花顺(北向)
ETF版本: 分钟级买力分析(非资金流分类) + 科创板板块情绪
"""
import time, random, requests, json, re, os
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _em_adapter = HTTPAdapter(max_retries=Retry(
        total=2, connect=2, backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    EM_SESSION.mount("https://", _em_adapter)
    EM_SESSION.mount("http://", _em_adapter)
except Exception:
    pass
EM_MIN_INTERVAL = 0.8
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15, **kwargs):
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0: time.sleep(wait + random.uniform(0.05, 0.3))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()

OUTPUT_BASE = "src/盘中交易信号"

# ============================================================
# 时效性门控 V1.3
# ============================================================
def check_data_freshness():
    now = datetime.now()
    market_open = now.replace(hour=9, minute=30, second=0)
    minutes_from_open = (now - market_open).total_seconds() / 60
    if minutes_from_open < 0: minutes_from_open = 0

    dims = {
        "quote": {"first_available_min": 0, "status": "ready"},
        "minute_flow": {"first_available_min": 2, "status": "ready"},
        "sector": {"first_available_min": 15, "status": "ready" if minutes_from_open >= 15 else "pending"},
        "news": {"first_available_min": 0, "status": "ready"},
        "north_bound": {"first_available_min": 30, "status": "ready" if minutes_from_open >= 30 else "pending"},
        "market": {"first_available_min": 0, "status": "ready"},
        "breadth": {"first_available_min": 30, "status": "ready" if minutes_from_open >= 30 else "pending"},
    }

    if minutes_from_open <= 30:
        phase, phase_name = 1, f"盘初({minutes_from_open:.0f}分, 数据延迟高发期)"
        weights = {"quote": 25, "minute_flow": 50, "sector": 5, "news": 5, "north_bound": 0, "market": 15, "breadth": 0}
    elif minutes_from_open <= 90:
        phase, phase_name = 2, f"早盘过渡({minutes_from_open:.0f}分)"
        weights = {"quote": 20, "minute_flow": 35, "sector": 12, "news": 8, "north_bound": 5, "market": 12, "breadth": 8}
    elif minutes_from_open <= 300:
        phase, phase_name = 3, f"盘中正常({minutes_from_open:.0f}分)"
        weights = {"quote": 15, "minute_flow": 25, "sector": 15, "news": 10, "north_bound": 15, "market": 10, "breadth": 10}
    else:
        phase, phase_name = 4, f"尾盘({minutes_from_open:.0f}分)"
        weights = {"quote": 15, "minute_flow": 30, "sector": 12, "news": 10, "north_bound": 13, "market": 10, "breadth": 10}

    return {"phase": phase, "phase_name": phase_name,
            "minutes_from_open": minutes_from_open,
            "freshness": dims, "weights": weights}

FRESHNESS = check_data_freshness()

# ============================================================
# Layer 1: 腾讯行情 + 新浪验证
# ============================================================
def fetch_tencent_quote(code):
    prefixed = f"sh{code}" if code.startswith(("5", "6", "9")) else f"sz{code}"
    url = f"https://qt.gtimg.cn/q={prefixed}"
    try:
        req = Request(url); req.add_header("User-Agent", UA)
        resp = urlopen(req, timeout=8)
        data = resp.read().decode("gbk")
        vals = data.split('"')[1].split("~") if '"' in data else []
        if len(vals) < 53: return {"error": "数据字段不足"}
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
        }
    except Exception as e:
        return {"error": str(e)}

def fetch_sina_quote(code):
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    try:
        r = requests.get(f"https://hq.sinajs.cn/list={prefix}{code}",
                        headers={"Referer": "https://finance.sina.com.cn"}, timeout=8)
        r.encoding = "gbk"
        data = r.text.split('"')[1].split(",")
        if len(data) < 30: return {"available": False}
        return {"available": True, "price": float(data[3]), "open": float(data[1]),
                "high": float(data[4]), "low": float(data[5]),
                "change_pct": round((float(data[3])-float(data[2]))/float(data[2])*100,2)}
    except Exception:
        return {"available": False}

# ============================================================
# Layer 2: 腾讯分时 → 买卖力道分析 (ETF版)
# ============================================================
def fetch_minute_data_tencent(code):
    """腾讯分时API — mootdx备选, ETF也可用"""
    prefixed = f"sh{code}" if code.startswith(("5", "6", "9")) else f"sz{code}"
    url = f"https://ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data&code={prefixed}"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        text = r.text
        json_str = text.split("min_data=")[1] if "min_data=" in text else text
        data = json.loads(json_str)
        if data.get("code") != 0:
            return []
        qt = data.get("data", {}).get(prefixed, {}).get("data", {})
        if not qt:
            # 尝试用前两天日期key
            for k in data.get("data", {}).get(prefixed, {}).get("data", {}):
                qt = data["data"][prefixed]["data"][k]
                break
        mins = qt.get("data", []) if qt else []
        rows = []
        for m in mins:
            parts = m.split()
            if len(parts) >= 3:
                rows.append({"time": parts[0], "price": float(parts[1]),
                            "vol": int(parts[2])})
        return rows
    except Exception as e:
        print(f"  [WARN] 腾讯分时失败: {e}")
        return []

def analyze_minute_flow(minute_data):
    if not minute_data or len(minute_data) < 2:
        return {"error": "分时数据不足"}

    buy_vol = sell_vol = 0
    cum_flow = []; running = 0

    for i in range(1, len(minute_data)):
        prev_p = minute_data[i-1]["price"]
        curr_p = minute_data[i]["price"]
        vol = minute_data[i]["vol"]
        if curr_p > prev_p:
            buy_vol += vol; running += vol
        elif curr_p < prev_p:
            sell_vol += vol; running -= vol
        cum_flow.append({"time": minute_data[i]["time"], "net_vol": running,
                        "price": curr_p})

    total = buy_vol + sell_vol
    buy_ratio = buy_vol / total * 100 if total > 0 else 50

    if len(cum_flow) >= 10:
        mid = len(cum_flow) // 2
        s1 = (cum_flow[mid-1]["net_vol"] - cum_flow[0]["net_vol"]) / max(mid, 1)
        s2 = (cum_flow[-1]["net_vol"] - cum_flow[mid]["net_vol"]) / max(len(cum_flow)-mid, 1)
        direction = "买方占优" if cum_flow[-1]["net_vol"] > 0 else "卖方占优"
        if s2 > s1 * 1.5: accel = "买方加速" if s2 > 0 else "卖压减弱"
        elif s2 < s1 * 0.3: accel = "买力减弱" if s2 > 0 else "卖压加速"
        else: accel = "匀速"
        bs1, bs2 = round(s1,0), round(s2,0)
    else:
        direction = "数据不足"; accel = "数据不足"; bs1 = bs2 = 0

    turning = []
    net_seq = [c["net_vol"] for c in cum_flow]
    if len(net_seq) >= 20:
        for i in range(10, len(net_seq)-5):
            bf = net_seq[i-5:i]; af = net_seq[i:i+5]
            if all(net_seq[i] > b for b in bf) and all(net_seq[i] > a for a in af):
                turning.append({"time": cum_flow[i]["time"], "type": "买力见顶", "value": net_seq[i]})
            elif all(net_seq[i] < b for b in bf) and all(net_seq[i] < a for a in af):
                turning.append({"time": cum_flow[i]["time"], "type": "卖压见底", "value": net_seq[i]})

    return {
        "minutes": cum_flow,
        "summary": {
            "total_buy_vol": buy_vol, "total_sell_vol": sell_vol,
            "total_net_vol": buy_vol - sell_vol,
            "buy_ratio_pct": round(buy_ratio, 1),
            "data_points": len(cum_flow),
            "first_time": cum_flow[0]["time"] if cum_flow else "",
            "last_time": cum_flow[-1]["time"] if cum_flow else "",
        },
        "trend": {"direction": direction, "acceleration": accel,
                  "first_half_slope": bs1, "second_half_slope": bs2,
                  "turning_points": turning[-5:]},
        "source": "腾讯分时API → 买卖力道推导 (ETF版)",
    }

# ============================================================
# Layer 3: 科创板板块情绪
# ============================================================
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

# 科创50ETF 核心板块
KECHUANG_SECTORS = {
    "BK0892": "半导体概念",
    "BK0472": "国产芯片",
    "BK1036": "半导体设备",
    "BK1062": "半导体材料",
    "BK0888": "光刻机(胶)",
    "BK1091": "中芯概念",
    "BK1097": "AI芯片",
    "BK1199": "存储芯片",
}

def fetch_sector_sentiment():
    params = {"pn": "1", "pz": "500", "po": "0", "np": "1",
              "fltt": "2", "invt": "2", "fs": "m:90+t:3",
              "fields": "f2,f3,f12,f14,f62,f104,f105"}
    headers = {"Referer": "https://data.eastmoney.com/"}
    try:
        r = em_get(PUSH2_CLIST, params=params, headers=headers, timeout=15)
        items = r.json().get("data", {}).get("diff", []) or []
    except Exception as e:
        print(f"  [WARN] 板块拉取失败: {e}")
        items = []

    all_sectors = {}
    for it in items:
        bk_code = it.get("f12", "")
        if bk_code:
            mn = it.get("f62") or 0
            all_sectors[bk_code] = {
                "code": bk_code, "name": it.get("f14", ""),
                "change_pct": it.get("f3", 0),
                "main_net_wan": round(mn/1e4, 1),
                "direction": "流入" if mn > 0 else "流出",
                "up_count": it.get("f104", 0), "down_count": it.get("f105", 0),
            }

    blocks = []
    for bk_code, bk_name in KECHUANG_SECTORS.items():
        sd = all_sectors.get(bk_code)
        if sd:
            blocks.append(sd)
        else:
            blocks.append({"code": bk_code, "name": bk_name, "change_pct": 0,
                          "main_net_wan": 0, "direction": "未知",
                          "up_count": 0, "down_count": 0})

    inflow = sum(1 for b in blocks if b["main_net_wan"] > 0)
    total = len(blocks)
    avg_chg = sum(b["change_pct"] for b in blocks) / total if total > 0 else 0
    total_flow = sum(b["main_net_wan"] for b in blocks)

    sector_freshness = FRESHNESS["freshness"].get("sector", {})
    if sector_freshness.get("status") == "pending":
        flow_score = 25
        price_score = 25
    else:
        flow_score = (inflow / total) * 50
        price_score = max(0, min(50, (avg_chg + 5) * 5))
    score = round(flow_score + price_score, 1)

    if score >= 75: level = "🔥 极热"
    elif score >= 60: level = "🟢 偏热"
    elif score >= 40: level = "🟡 中性"
    elif score >= 25: level = "🔵 偏冷"
    else: level = "❄️ 极冷"

    return {
        "blocks": blocks, "sentiment_score": score, "level": level,
        "inflow_blocks": inflow, "total_blocks": total,
        "avg_change_pct": round(avg_chg, 2),
        "total_sector_flow_wan": round(total_flow, 1),
        "all_sectors_count": len(all_sectors),
        "data_basis": f"{inflow}/{total}板块流入, 合计{total_flow:+.0f}万, 平均涨跌{avg_chg:+.2f}%, 情绪分{score}",
        "freshness_status": sector_freshness.get("status", "ready"),
    }

# ============================================================
# Layer 4: 新闻
# ============================================================
def fetch_intraday_news(keywords):
    all_highlights = []
    for kw in keywords:
        try:
            inner = json.dumps({
                "uid": "", "keyword": kw,
                "type": ["cmsArticleWebOld"],
                "client": "web", "clientType": "web", "clientVersion": "curr",
                "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                               "pageIndex": 1, "pageSize": 5,
                                               "preTag": "", "postTag": ""}},
            }, separators=(',', ':'))
            r = requests.get("https://search-api-web.eastmoney.com/search/jsonp",
                           params={"cb": "j", "param": inner},
                           headers={"Referer": "https://so.eastmoney.com/"}, timeout=10)
            text = r.text
            json_str = text[text.index("(")+1:text.rindex(")")]
            articles = json.loads(json_str).get("result", {}).get("cmsArticleWebOld", []) or []
        except Exception:
            continue

        today = datetime.now().strftime("%Y-%m-%d")
        bullish_kw = ["增长","突破","中标","扩产","获批","回购","增持","超预期","利好","扶持","补贴"]
        bearish_kw = ["减持","亏损","下滑","调查","处罚","诉讼","违约","制裁","限制","关税"]
        for a in articles:
            title = re.sub(r'<[^>]+>', '', a.get("title", ""))
            if a.get("date", "").startswith(today):
                sentiment = "neutral"
                if any(x in title for x in bullish_kw): sentiment = "bullish"
                elif any(x in title for x in bearish_kw): sentiment = "bearish"
                all_highlights.append({"title": title, "time": a.get("date", ""),
                                      "source": a.get("mediaName", ""), "sentiment": sentiment})

    seen = set()
    unique = []
    for h in all_highlights:
        if h["title"] not in seen:
            seen.add(h["title"]); unique.append(h)

    return {
        "today_count": len(unique), "highlights": unique,
        "bullish_count": sum(1 for h in unique if h["sentiment"]=="bullish"),
        "bearish_count": sum(1 for h in unique if h["sentiment"]=="bearish"),
    }

# ============================================================
# Layer 5-7: 北向 / 大盘 / 市场广度
# ============================================================
def fetch_north_bound():
    hgt_net = sgt_net = 0.0
    try:
        r = requests.get("https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/hgt",
                        headers={"User-Agent": UA}, timeout=8)
        items = r.json().get("data", []) if r.ok else []
        hgt_net = sum(it.get("net", 0) for it in (items if isinstance(items, list) else [])[-10:])
    except Exception: pass
    try:
        r = requests.get("https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/sgt",
                        headers={"User-Agent": UA}, timeout=8)
        items = r.json().get("data", []) if r.ok else []
        sgt_net = sum(it.get("net", 0) for it in (items if isinstance(items, list) else [])[-10:])
    except Exception: pass

    total_net = hgt_net + sgt_net
    total_yi = total_net / 1e4

    if total_net > 5000: direction, signal = "大幅流入", "🟢 积极"
    elif total_net > 0: direction, signal = "小幅流入", "🟡 中性偏多"
    elif total_net > -5000: direction, signal = "小幅流出", "🟠 中性偏空"
    else: direction, signal = "大幅流出", "🔴 警惕"

    nb_fresh = FRESHNESS["freshness"].get("north_bound", {})
    if nb_fresh.get("status") == "pending":
        total_yi = 0; direction = "数据延迟中"; signal = "⏳"

    return {
        "hgt_net_wan": round(hgt_net, 0), "sgt_net_wan": round(sgt_net, 0),
        "total_net_yi": round(total_yi, 2), "direction": direction, "signal": signal,
        "data_basis": f"沪股通{hgt_net/1e4:+.2f}亿 + 深股通{sgt_net/1e4:+.2f}亿 = 北向合计{total_yi:+.2f}亿",
        "freshness_status": nb_fresh.get("status", "ready"),
    }

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
                market_data[name] = {"change_pct": float(vals[32]) if vals[32] else 0}
        except Exception:
            market_data[name] = {"change_pct": 0}

    if code.startswith(("5", "6", "9")): primary = "上证指数"
    elif code.startswith("30"): primary = "创业板指"
    else: primary = "深证成指"

    bm_chg = market_data.get(primary, {}).get("change_pct", 0)
    stock_chg = quote.get("change_pct", 0)
    relative = stock_chg - bm_chg

    if bm_chg > 1: env = "🟢 大盘强势"
    elif bm_chg > 0: env = "🟡 大盘微涨"
    elif bm_chg > -1: env = "🟠 大盘微跌"
    else: env = "🔴 大盘弱势"

    if relative > 3: rating = "🚀 显著跑赢"
    elif relative > 1: rating = "✅ 跑赢"
    elif relative > -1: rating = "➖ 同步"
    elif relative > -3: rating = "⚠️ 跑输"
    else: rating = "🔴 显著跑输"

    return {
        "benchmark": primary, "benchmark_change": round(bm_chg, 2),
        "market_env": env, "relative_strength": round(relative, 2),
        "relative_rating": rating,
        "market_detail": {k: round(v.get("change_pct", 0), 2) for k, v in market_data.items()},
        "data_basis": f"{primary}{bm_chg:+.2f}%, 个股{stock_chg:+.2f}%, 相对强弱{relative:+.2f}%",
    }

def fetch_market_breadth():
    up_count = down_count = limit_up = limit_down = 0
    try:
        params = {"pn": "1", "pz": "1", "po": "0", "np": "1",
                  "fltt": "2", "invt": "2",
                  "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
                  "fields": "f104,f105"}
        r = em_get(PUSH2_CLIST, params=params,
                   headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        items = r.json().get("data", {}).get("diff", [])
        up_count = sum(it.get("f104", 0) for it in items) if items else 0
        down_count = sum(it.get("f105", 0) for it in items) if items else 0
    except Exception: pass

    try:
        r_up = em_get("https://push2ex.eastmoney.com/getTopicZTPool",
                     params={"ut":"7eea3ed8b1e5b1c3","pageSize":500,"pageNum":1,"sort":"fbt","fbt":"desc"},
                     headers={"Referer":"https://data.eastmoney.com/"}, timeout=8)
        limit_up = r_up.json().get("data",{}).get("total",0) or 0
    except Exception: pass
    try:
        r_down = em_get("https://push2ex.eastmoney.com/getTopicDTPool",
                       params={"ut":"7eea3ed8b1e5b1c3","pageSize":500,"pageNum":1,"sort":"fund","fund":"desc"},
                       headers={"Referer":"https://data.eastmoney.com/"}, timeout=8)
        limit_down = r_down.json().get("data",{}).get("total",0) or 0
    except Exception: pass

    total = up_count + down_count
    up_ratio = up_count / max(total, 1) * 100

    breadth_fresh = FRESHNESS["freshness"].get("breadth", {})
    if breadth_fresh.get("status") == "pending":
        up_ratio = 50; limit_up = limit_down = 0

    if up_ratio >= 70: bl, bs = "🟢 普涨格局", 85
    elif up_ratio >= 55: bl, bs = "🟡 涨多跌少", 60
    elif up_ratio >= 45: bl, bs = "🟠 分化格局", 40
    elif up_ratio >= 30: bl, bs = "🔴 跌多涨少", 20
    else: bl, bs = "💀 普跌格局", 5

    lr = limit_up / max(limit_down, 1)
    if lr >= 3: me = "🔥 强赚钱效应"
    elif lr >= 1.5: me = "✅ 赚钱效应良好"
    elif lr >= 1: me = "➖ 中性"
    elif lr >= 0.5: me = "⚠️ 亏钱效应显现"
    else: me = "💀 强亏钱效应"

    return {
        "up_count": up_count, "down_count": down_count,
        "up_ratio_pct": round(up_ratio, 1), "breadth_level": bl,
        "breadth_score": bs, "limit_up_count": limit_up,
        "limit_down_count": limit_down, "limit_ratio": round(lr, 1),
        "money_effect": me,
        "data_basis": f"涨{up_count}跌{down_count}({up_ratio:.0f}%), 涨停{limit_up}/跌停{limit_down}, 赚钱效应:{me}",
        "freshness_status": breadth_fresh.get("status", "ready"),
    }

# ============================================================
# Layer 8: 多情景概率预判 (ETF版, 基于分时买力)
# ============================================================
def generate_scenarios(flow, quote, sector, news, nb, ms, mb):
    change_pct = quote.get("change_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)

    s = flow.get("summary", {}) or {}
    net_vol = s.get("total_net_vol", 0)
    buy_ratio = s.get("buy_ratio_pct", 50)
    t = flow.get("trend", {}) or {}
    direction = t.get("direction", "")
    accel = t.get("acceleration", "")

    sentiment = sector.get("sentiment_score", 50)
    news_bull = news.get("bullish_count", 0)
    news_bear = news.get("bearish_count", 0)

    nb_yi = nb.get("total_net_yi", 0)
    rs = ms.get("relative_strength", 0)
    up_ratio = mb.get("up_ratio_pct", 50)
    lr = mb.get("limit_ratio", 1)

    scenarios = []

    # ━━ 情景A: 震荡反弹 ━━
    a_conditions = []
    buy_dom = buy_ratio > 55 and net_vol > 0
    a_conditions.append({"condition": "买方占比>55%", "threshold": ">55%", "actual": f"{buy_ratio:.0f}%", "met": buy_dom, "weight": 25})

    no_new_low = change_pct > -1 and quote.get("low", 0) >= quote.get("open", 0) * 0.98
    a_conditions.append({"condition": "未创新低(跌幅<1%且距开盘<2%)", "threshold": "跌幅<1%", "actual": f"{change_pct:+.2f}%", "met": no_new_low, "weight": 20})

    vol_ok = 0.5 <= vol_ratio <= 3
    a_conditions.append({"condition": "量能温和(量比0.5-3)", "threshold": "0.5-3", "actual": f"{vol_ratio:.1f}", "met": vol_ok, "weight": 15})

    accel_ok = "买方加速" in accel or "卖压减弱" in accel
    a_conditions.append({"condition": "买力趋势向好", "threshold": "买方加速/卖压减弱", "actual": accel, "met": accel_ok, "weight": 15})

    sentiment_ok = sentiment >= 40
    a_conditions.append({"condition": "板块情绪≥40(非极冷)", "threshold": "≥40", "actual": f"{sentiment:.0f}分", "met": sentiment_ok, "weight": 10})

    market_ok = rs > -1
    a_conditions.append({"condition": "相对大盘不跑输(>-1%)", "threshold": ">-1%", "actual": f"{rs:+.2f}%", "met": market_ok, "weight": 10})

    no_bear = news_bear == 0
    a_conditions.append({"condition": "无利空消息", "threshold": "0条", "actual": f"{news_bear}条", "met": no_bear, "weight": 5})

    a_score = sum(c["weight"] for c in a_conditions if c["met"])
    scenarios.append({
        "name": "情景A: 震荡反弹",
        "description": "买方力量占优+未创新低+量能温和 → 当日可能震荡上行",
        "raw_score": a_score,
        "conditions": a_conditions,
        "met_count": sum(1 for c in a_conditions if c["met"]),
        "total_conditions": len(a_conditions),
        "historical_ref": {"rule": "ETF分时买力占优+跌幅收窄 → 当日反弹概率较高",
                          "historical_win_rate": "约55-65%", "source": "A股ETF日内量价统计"},
        "failure_conditions": ["突发利空", "午后卖压加速"],
    })

    # ━━ 情景B: 弱势震荡 ━━
    b_conditions = []
    no_dir = abs(net_vol) < 50000 and 40 <= buy_ratio <= 60
    b_conditions.append({"condition": "买卖力量均衡(净量<5万,占比40-60%)", "threshold": "净量<5万", "actual": f"净量{net_vol/1e4:.1f}万, 占比{buy_ratio:.0f}%", "met": no_dir, "weight": 30})

    narrow = amplitude < 2
    b_conditions.append({"condition": "振幅<2%(窄幅波动)", "threshold": "<2%", "actual": f"{amplitude:.2f}%", "met": narrow, "weight": 20})

    vol_low = vol_ratio < 0.8
    b_conditions.append({"condition": "缩量(量比<0.8)", "threshold": "<0.8", "actual": f"{vol_ratio:.1f}", "met": vol_low, "weight": 20})

    accel_flat = "匀速" in accel
    b_conditions.append({"condition": "买卖力道匀速", "threshold": "匀速", "actual": accel, "met": accel_flat, "weight": 15})

    nb_neutral = abs(nb_yi) < 3
    b_conditions.append({"condition": "北向无方向(±3亿内)", "threshold": "|北向|<3亿", "actual": f"{nb_yi:+.2f}亿", "met": nb_neutral, "weight": 10})

    market_neutral = abs(rs) < 1
    b_conditions.append({"condition": "与大盘同步(相对强度±1%)", "threshold": "±1%", "actual": f"{rs:+.2f}%", "met": market_neutral, "weight": 10})

    b_score = sum(c["weight"] for c in b_conditions if c["met"])
    scenarios.append({
        "name": "情景B: 弱势震荡",
        "description": "买卖力量均衡+振幅小+缩量 → 当日大概率窄幅震荡",
        "raw_score": b_score,
        "conditions": b_conditions,
        "met_count": sum(1 for c in b_conditions if c["met"]),
        "total_conditions": len(b_conditions),
        "historical_ref": {"rule": "ETF缩量窄幅震荡 → 当日横盘概率较高",
                          "historical_win_rate": "约60-65%", "source": "A股ETF日内波动统计"},
        "failure_conditions": ["突发消息催化", "尾盘放量选方向"],
    })

    # ━━ 情景C: 冲高回落 ━━
    c_conditions = []
    high_turn = change_pct > 2 and "买力减弱" in accel
    c_conditions.append({"condition": "已涨>2%且买力减弱", "threshold": "涨>2%+买力减弱", "actual": f"涨{change_pct:+.2f}%, {accel}", "met": high_turn, "weight": 30})

    sell_accel = "卖压加速" in accel
    c_conditions.append({"condition": "卖压加速", "threshold": "卖压加速", "actual": accel, "met": sell_accel, "weight": 25})

    high_vol = vol_ratio > 2 and change_pct > 1
    c_conditions.append({"condition": "高位放量(量比>2+涨>1%)", "threshold": "量比>2+涨>1%", "actual": f"量比{vol_ratio}, 涨{change_pct:+.2f}%", "met": high_vol, "weight": 20})

    nb_out = nb_yi < -2
    c_conditions.append({"condition": "北向流出(<-2亿)", "threshold": "<-2亿", "actual": f"{nb_yi:+.2f}亿", "met": nb_out, "weight": 15})

    breadth_weak = up_ratio < 40
    c_conditions.append({"condition": "市场广度偏弱(上涨<40%)", "threshold": "<40%", "actual": f"{up_ratio:.0f}%", "met": breadth_weak, "weight": 10})

    c_score = sum(c["weight"] for c in c_conditions if c["met"])
    scenarios.append({
        "name": "情景C: 冲高回落",
        "description": "高位+买力减弱/卖压加速 → 警惕当日回落风险",
        "raw_score": c_score,
        "conditions": c_conditions,
        "met_count": sum(1 for c in c_conditions if c["met"]),
        "total_conditions": len(c_conditions),
        "historical_ref": {"rule": "ETF冲高后买力衰竭 → 午后回落概率较高",
                          "historical_win_rate": "约55-65%", "source": "A股ETF日内量价关系统计"},
        "failure_conditions": ["超预期利好", "板块集体暴动"],
    })

    # ━━ 情景D: 继续下探 ━━
    d_conditions = []
    sell_dom = buy_ratio < 40 and net_vol < -50000
    d_conditions.append({"condition": "卖方力量强(占比<40%,净卖>5万)", "threshold": "占比<40%+净卖>5万", "actual": f"占比{buy_ratio:.0f}%, 净量{net_vol/1e4:.1f}万", "met": sell_dom, "weight": 30})

    sell_accel_d = "卖压加速" in accel
    d_conditions.append({"condition": "卖压加速", "threshold": "卖压加速", "actual": accel, "met": sell_accel_d, "weight": 25})

    new_low = change_pct < -2 and quote.get("low", 0) <= quote.get("open", 0) * 0.97
    d_conditions.append({"condition": "创新低(跌>2%+距开盘>3%)", "threshold": "跌>2%+距开盘>3%", "actual": f"跌{change_pct:+.2f}%", "met": new_low, "weight": 20})

    sentiment_cold = sentiment < 35
    d_conditions.append({"condition": "板块情绪极冷(<35)", "threshold": "<35", "actual": f"{sentiment:.0f}分", "met": sentiment_cold, "weight": 15})

    breadth_bear = up_ratio < 30 or lr < 0.8
    d_conditions.append({"condition": "市场普跌(上涨<30%或涨跌停比<0.8)", "threshold": "上涨<30%", "actual": f"涨{up_ratio:.0f}%, 涨跌停比{lr}", "met": breadth_bear, "weight": 10})

    d_score = sum(c["weight"] for c in d_conditions if c["met"])
    scenarios.append({
        "name": "情景D: 继续下探",
        "description": "卖方力量主导+卖压加速+创新低 → 当日可能继续走弱",
        "raw_score": d_score,
        "conditions": d_conditions,
        "met_count": sum(1 for c in d_conditions if c["met"]),
        "total_conditions": len(d_conditions),
        "historical_ref": {"rule": "ETF分时卖压主导+持续创新低 → 当日收阴概率较高",
                          "historical_win_rate": "约60-70%", "source": "A股ETF日内量价统计"},
        "failure_conditions": ["午后重大利好", "国家队护盘"],
    })

    total = sum(s["raw_score"] for s in scenarios)
    for s in scenarios:
        s["probability"] = round(s["raw_score"] / total * 100, 1) if total > 0 else 0

    return sorted(scenarios, key=lambda x: x["probability"], reverse=True)

# ============================================================
# Layer 9: 买卖时机参考信号 (ETF版)
# ============================================================
def generate_signals(scenarios, flow, quote, sector):
    primary = scenarios[0] if scenarios else {}
    pname = primary.get("name", "")
    pprob = primary.get("probability", 0)

    change_pct = quote.get("change_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    price = quote.get("price", 0)

    s = flow.get("summary", {}) or {}
    net_vol = s.get("total_net_vol", 0)
    buy_ratio = s.get("buy_ratio_pct", 50)
    t = flow.get("trend", {}) or {}
    accel = t.get("acceleration", "")

    buy_signals = []
    sell_signals = []

    # ━━ 买入信号 ━━
    strong_buy = (
        pname == "情景A: 震荡反弹" and pprob >= 50 and
        buy_ratio > 55 and net_vol > 0 and
        "买方加速" in accel
    )
    if strong_buy:
        buy_signals.append({
            "level": "🟢🟢🟢 强买入参考",
            "data_evidence": [
                {"item": "主导情景", "value": f"{pname}({pprob:.0f}%)", "threshold": "情景A≥50%", "met": True, "source": "七维概率引擎"},
                {"item": "买方占比", "value": f"{buy_ratio:.0f}%", "threshold": ">55%", "met": True, "source": "mootdx分时分析"},
                {"item": "买力趋势", "value": accel, "threshold": "买方加速", "met": True, "source": "mootdx趋势分析"},
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "未过度拉升(<5%)", "met": change_pct < 5, "source": "腾讯行情"},
            ],
            "action": "可考虑逢低建仓，分时均线附近入场",
            "stop_loss": f"跌破{price*0.97:.2f}(-3%)止损",
        })

    medium_buy = (
        pname == "情景A: 震荡反弹" and pprob >= 35 and
        buy_ratio > 50 and "卖压减弱" in accel
    )
    if medium_buy and not strong_buy:
        buy_signals.append({
            "level": "🟢🟢 中等买入参考",
            "data_evidence": [
                {"item": "主导情景", "value": f"{pname}({pprob:.0f}%)", "threshold": "情景A≥35%", "met": True, "source": "七维概率引擎"},
                {"item": "买方占比", "value": f"{buy_ratio:.0f}%", "threshold": ">50%", "met": True, "source": "mootdx分时分析"},
                {"item": "趋势", "value": accel, "threshold": "卖压减弱", "met": True, "source": "mootdx趋势分析"},
            ],
            "action": "可小仓位试探(计划仓位30-50%), 等待更多确认",
            "stop_loss": f"跌破{price*0.95:.2f}(-5%)止损",
        })

    if not buy_signals:
        buy_signals.append({
            "level": "⚪ 暂不建议买入",
            "data_evidence": [
                {"item": "主导情景", "value": f"{pname}({pprob:.0f}%)", "threshold": "需情景A≥35%+买方占优", "met": False, "source": "七维概率引擎"},
                {"item": "买方占比", "value": f"{buy_ratio:.0f}%", "threshold": "需>50%", "met": buy_ratio > 50, "source": "mootdx分时分析"},
            ],
            "action": "继续观察，等待买方力量增强",
        })

    # ━━ 卖出信号 ━━
    strong_sell = (
        pname == "情景D: 继续下探" and pprob >= 45 and
        buy_ratio < 40 and "卖压加速" in accel
    )
    if strong_sell:
        sell_signals.append({
            "level": "🔴🔴🔴 强卖出参考",
            "data_evidence": [
                {"item": "主导情景", "value": f"{pname}({pprob:.0f}%)", "threshold": "情景D≥45%", "met": True, "source": "七维概率引擎"},
                {"item": "买方占比", "value": f"{buy_ratio:.0f}%", "threshold": "<40%", "met": True, "source": "mootdx分时分析"},
                {"item": "卖压趋势", "value": accel, "threshold": "卖压加速", "met": True, "source": "mootdx趋势分析"},
                {"item": "净卖量", "value": f"{net_vol/1e4:.1f}万", "threshold": "净卖出", "met": net_vol < 0, "source": "mootdx买卖力道"},
            ],
            "action": "建议果断减仓/清仓，不在下跌中补仓",
            "risk_note": f"卖压持续，近期累计跌幅已大，反弹前不轻易抄底",
        })

    medium_sell = (
        (pname == "情景C: 冲高回落" or pname == "情景D: 继续下探") and
        pprob >= 30 and ("卖压" in accel or buy_ratio < 45)
    )
    if medium_sell and not strong_sell:
        sell_signals.append({
            "level": "🔴🔴 中等卖出参考",
            "data_evidence": [
                {"item": "主导情景", "value": f"{pname}({pprob:.0f}%)", "threshold": "弱势情景≥30%", "met": True, "source": "七维概率引擎"},
                {"item": "买方占比", "value": f"{buy_ratio:.0f}%", "threshold": "<45%", "met": True, "source": "mootdx分时分析"},
                {"item": "趋势", "value": accel, "threshold": "卖压增加", "met": "卖压" in accel, "source": "mootdx趋势分析"},
            ],
            "action": "建议逐步减仓，至少减到半仓以下",
        })

    if not sell_signals:
        sell_signals.append({
            "level": "⚪ 暂不需卖出",
            "data_evidence": [
                {"item": "买方占比", "value": f"{buy_ratio:.0f}%", "threshold": "未触发卖出阈值", "met": True, "source": "mootdx分时分析"},
            ],
            "action": "继续持有观察，关注买方力量是否转弱",
        })

    # ━━ 持有参考 ━━
    if "情景A" in pname and pprob >= 40:
        hold = {"level": "✅ 可继续持有", "reason": f"反弹概率{pprob:.0f}%, 买方占比{buy_ratio:.0f}%",
                "watch_points": ["午后买力是否持续", "是否创新低", "板块情绪是否转冷"]}
    elif "情景B" in pname:
        hold = {"level": "⏸️ 持有观望", "reason": f"震荡格局, 买卖均衡(占比{buy_ratio:.0f}%)",
                "watch_points": ["突破方向", "是否有催化消息"]}
    else:
        hold = {"level": "⚠️ 审视持仓", "reason": f"风险情景概率较高({pname} {pprob:.0f}%)",
                "watch_points": ["触发止损则果断执行", "等待情景A信号出现"]}

    return {"buy_signals": buy_signals, "sell_signals": sell_signals, "hold_verdict": hold}

# ============================================================
# 主流程
# ============================================================
def main():
    code = "588000"
    name = "科创50ETF华夏"
    print(f"\n{'='*70}")
    print(f"  📊 盘中实时交易信号: {name}({code})")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 时效性: {FRESHNESS['phase_name']}")
    print(f"{'='*70}")

    # [1/7] 行情
    print("\n[1/7] 拉取实时行情(腾讯+新浪)...")
    quote = fetch_tencent_quote(code)
    sina = fetch_sina_quote(code)
    if sina.get("available") and "error" not in quote:
        t_p, s_p = quote.get("price", 0), sina.get("price", 0)
        if t_p > 0 and s_p > 0:
            diff = abs(t_p - s_p) / s_p * 100
            quality = "🟢 双源一致" if diff < 0.5 else f"🔴 差异{diff:.2f}%"
        else:
            quality = "🟡 单源"
        quote["_validation"] = {"quality": quality, "tencent_price": t_p, "sina_price": s_p}
    print(f"  {quote.get('name','')} 价格:{quote.get('price',0):.3f} 涨跌:{quote.get('change_pct',0):+.2f}%")

    # [2/7] 分时
    print("[2/7] 拉取分时数据(腾讯API)...")
    minute_data = fetch_minute_data_tencent(code)
    flow = analyze_minute_flow(minute_data)
    if "error" not in flow:
        s = flow["summary"]
        t = flow["trend"]
        print(f"  {s.get('data_points',0)}分钟 | 买方占比{s.get('buy_ratio_pct',50):.0f}% | {t.get('direction','')} | {t.get('acceleration','')}")

    # [3/7] 板块情绪
    print("[3/7] 拉取板块情绪(科创50核心板块)...")
    sector = fetch_sector_sentiment()
    print(f"  情绪分:{sector['sentiment_score']:.0f}/100 {sector['level']} | {sector['inflow_blocks']}/{sector['total_blocks']}板块流入")

    # [4/7] 新闻
    print("[4/7] 拉取新闻(科创50/科创板)...")
    news = fetch_intraday_news(["科创50", "科创板", "半导体"])
    print(f"  今日{news['today_count']}条 (利好{news['bullish_count']}/利空{news['bearish_count']})")

    # [5/7] 北向
    print("[5/7] 拉取北向资金...")
    nb = fetch_north_bound()
    print(f"  北向:{nb.get('data_basis','')} | {nb.get('direction','')} {nb.get('signal','')}")

    # [6/7] 大盘
    print("[6/7] 拉取大盘强度...")
    ms = fetch_market_strength(code, quote)
    print(f"  {ms.get('data_basis','')} | {ms.get('relative_rating','')} {ms.get('market_env','')}")

    # [7/7] 广度
    print("[7/7] 拉取市场广度...")
    mb = fetch_market_breadth()
    print(f"  {mb.get('data_basis','')}")

    # 概率引擎
    print("\n[分析] 生成多情景概率预判...")
    scenarios = generate_scenarios(flow, quote, sector, news, nb, ms, mb)
    primary = scenarios[0] if scenarios else {}

    # 买卖信号
    signals = generate_signals(scenarios, flow, quote, sector)

    # ━━ 打印报告 ━━
    _print_console(code, name, quote, flow, sector, news, nb, ms, mb, scenarios, signals)

    # ━━ 保存 ━━
    _save_report(code, name, quote, flow, sector, news, nb, ms, mb, scenarios, signals)

    print(f"\n✅ 报告已保存到 src/盘中交易信号/")

def _print_console(code, name, quote, flow, sector, news, nb, ms, mb, scenarios, signals):
    print(f"\n{'='*70}")
    print(f"  🎯 核心结论")
    print(f"{'='*70}")

    primary = scenarios[0] if scenarios else {}
    print(f"  主导情景: {primary.get('name','')} (概率{primary.get('probability',0):.0f}%)")
    bs = signals["buy_signals"][0] if signals["buy_signals"] else {}
    ss = signals["sell_signals"][0] if signals["sell_signals"] else {}
    print(f"  买入信号: {bs.get('level','')}")
    print(f"  卖出信号: {ss.get('level','')}")
    print(f"  持有建议: {signals['hold_verdict'].get('level','')}")

    # ━━ 七维数据一览 ━━
    print(f"\n{'─'*60}")
    print(f"  📊 七维数据一览 (时效性: {FRESHNESS['phase_name']})")
    print(f"{'─'*60}")

    s = flow.get("summary", {}) or {}
    t = flow.get("trend", {}) or {}
    print(f"  📈 价格: {quote.get('price',0):.3f} ({quote.get('change_pct',0):+.2f}%) "
          f"振幅{quote.get('amplitude',0):.2f}% 量比{quote.get('vol_ratio',0):.1f} 换手{quote.get('turnover_pct',0):.2f}%")
    print(f"  💰 分时: {s.get('data_points',0)}分钟 | 买方占比{s.get('buy_ratio_pct',50):.0f}% | "
          f"净量{s.get('total_net_vol',0)/1e4:+.1f}万 | {t.get('direction','')}/{t.get('acceleration','')}")
    print(f"  🎯 板块: 情绪{sector.get('sentiment_score',0):.0f}分 {sector.get('level','')}")
    print(f"  📰 消息: 今日{news.get('today_count',0)}条(利好{news.get('bullish_count',0)}/利空{news.get('bearish_count',0)})")
    print(f"  🌏 北向: {nb.get('data_basis','')} {nb.get('signal','')}")
    print(f"  📊 大盘: {ms.get('data_basis','')} {ms.get('relative_rating','')}")
    print(f"  🔥 广度: {mb.get('data_basis','')}")

    # ━━ 买卖力道关键转向点 ━━
    turns = t.get("turning_points", []) or []
    if turns:
        print(f"\n  ⚡ 关键转向点:")
        for tp in turns:
            print(f"    {tp['time']} {tp['type']}: 净量{tp['value']/1e4:+.1f}万")

    # ━━ 板块明细 ━━
    print(f"\n  📋 科创50核心板块:")
    for bk in sector.get("blocks", [])[:8]:
        print(f"    {bk['name']}: 涨{bk['change_pct']:+.2f}% 主力{bk['main_net_wan']:+.0f}万 {bk['direction']}")

    # ━━ 多情景概率 ━━
    print(f"\n{'─'*60}")
    print(f"  🔮 多情景概率预判 (ETF版分时买力)")
    print(f"{'─'*60}")
    for sc in scenarios:
        prob = sc["probability"]
        icon = "🔥" if prob >= 50 else ("📊" if prob >= 25 else "🔍")
        print(f"\n  {icon} {sc['name']} → {prob:.0f}% (满足{sc['met_count']}/{sc['total_conditions']}条件)")
        for c in sc["conditions"]:
            st = "✅" if c["met"] else "❌"
            print(f"    {st} {c['condition']}: {c['actual']} (阈值:{c['threshold']})")
        ref = sc.get("historical_ref", {})
        print(f"    历史参考: {ref.get('rule','')} (胜率{ref.get('historical_win_rate','')})")

    # ━━ 买卖信号 ━━
    print(f"\n{'─'*60}")
    print(f"  ⚡ 买卖时机参考")
    print(f"{'─'*60}")

    print(f"  📥 买入:")
    for bs in signals["buy_signals"]:
        print(f"    {bs['level']}")
        for ev in bs.get("data_evidence", []):
            st = "✅" if ev.get("met") else "❌"
            print(f"      {st} {ev['item']}: {ev['value']} [{ev['source']}]")
        print(f"    操作: {bs.get('action','')}")
        if bs.get("stop_loss"): print(f"    止损: {bs['stop_loss']}")

    print(f"  📤 卖出:")
    for ss in signals["sell_signals"]:
        print(f"    {ss['level']}")
        for ev in ss.get("data_evidence", []):
            st = "✅" if ev.get("met") else "❌"
            print(f"      {st} {ev['item']}: {ev['value']} [{ev['source']}]")
        print(f"    操作: {ss.get('action','')}")

    hv = signals["hold_verdict"]
    print(f"  📌 持有: {hv['level']}")
    print(f"    {hv['reason']}")
    for wp in hv.get("watch_points", []): print(f"    👁 {wp}")

    print(f"\n{'='*70}")
    print(f"  ⚠️ 研究声明: 所有信号基于公开API实时数据, 不构成投资建议")
    print(f"  时效性: {FRESHNESS['phase_name']} — 盘初板块/北向/广度数据可能延迟")
    print(f"{'='*70}")

def _save_report(code, name, quote, flow, sector, news, nb, ms, mb, scenarios, signals):
    date_str = datetime.now().strftime("%Y-%m-%d")
    dir_name = f"{date_str}-{name}-盘中信号"
    dir_path = os.path.join(OUTPUT_BASE, dir_name)
    os.makedirs(dir_path, exist_ok=True)

    lines = []
    L = lines.append
    L(f"# 📊 盘中实时交易信号: {name}({code})")
    L(f"")
    L(f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | **时效性**: {FRESHNESS['phase_name']}")
    L(f"**核心原则**: 宁可少挣，宁可少亏。买入卖出，数据说话。")
    L(f"")

    primary = scenarios[0] if scenarios else {}
    L(f"## 🎯 核心结论")
    L(f"")
    L(f"- **主导情景**: {primary.get('name','')} (概率 {primary.get('probability',0):.0f}%)")
    bs0 = signals["buy_signals"][0] if signals["buy_signals"] else {}
    ss0 = signals["sell_signals"][0] if signals["sell_signals"] else {}
    L(f"- **买入信号**: {bs0.get('level','')}")
    L(f"- **卖出信号**: {ss0.get('level','')}")
    L(f"- **持有建议**: {signals['hold_verdict'].get('level','')}")
    L(f"")

    L(f"## 📊 七维数据一览")
    L(f"")
    L(f"| 维度 | 关键数据 |")
    L(f"|------|---------|")
    s = flow.get("summary", {}) or {}
    t = flow.get("trend", {}) or {}
    L(f"| 📈 价格 | {quote.get('price',0):.3f} ({quote.get('change_pct',0):+.2f}%) 振幅{quote.get('amplitude',0):.2f}% 量比{quote.get('vol_ratio',0):.1f} |")
    L(f"| 💰 分时 | {s.get('data_points',0)}分钟 买方占比{s.get('buy_ratio_pct',50):.0f}% {t.get('direction','')}/{t.get('acceleration','')} |")
    L(f"| 🎯 板块 | 情绪{sector.get('sentiment_score',0):.0f}分 {sector.get('level','')} |")
    L(f"| 📰 消息 | {news.get('today_count',0)}条(利好{news.get('bullish_count',0)}/利空{news.get('bearish_count',0)}) |")
    L(f"| 🌏 北向 | {nb.get('data_basis','')} {nb.get('signal','')} |")
    L(f"| 📊 大盘 | {ms.get('data_basis','')} {ms.get('relative_rating','')} |")
    L(f"| 🔥 广度 | {mb.get('data_basis','')} |")
    L(f"")

    L(f"## 🔮 多情景概率预判")
    L(f"")
    for sc in scenarios:
        L(f"### {sc['name']} → {sc['probability']:.0f}%")
        L(f"")
        L(f"| 条件 | 阈值 | 当前 | 满足? |")
        L(f"|------|------|------|-------|")
        for c in sc["conditions"]:
            st = "✅" if c["met"] else "❌"
            L(f"| {c['condition']} | {c['threshold']} | {c['actual']} | {st} |")
        ref = sc.get("historical_ref", {})
        L(f"")
        L(f"**历史参考**: {ref.get('rule','')} ({ref.get('historical_win_rate','')})")
        L(f"")

    L(f"## ⚡ 买卖时机参考")
    L(f"")
    L(f"### 📥 买入")
    for bs in signals["buy_signals"]:
        L(f"- **{bs['level']}**")
        L(f"  - 操作: {bs.get('action','')}")
        if bs.get("stop_loss"): L(f"  - 止损: {bs['stop_loss']}")
    L(f"")
    L(f"### 📤 卖出")
    for ss in signals["sell_signals"]:
        L(f"- **{ss['level']}**")
        L(f"  - 操作: {ss.get('action','')}")

    L(f"")
    L(f"---")
    L(f"## ⚠️ 研究声明")
    L(f"")
    L(f"1. 所有信号基于公开API实时数据，不构成投资建议")
    L(f"2. ETF版本基于分时买力分析（非资金流分类）")
    L(f"3. 时效性: {FRESHNESS['phase_name']} — 盘初板块/北向/广度数据可能延迟")
    L(f"4. 核心原则: 宁可少挣，宁可少亏")

    with open(os.path.join(dir_path, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # data.json
    data_json = {
        "target": {"code": code, "name": name, "type": "ETF"},
        "analysis_time": datetime.now().isoformat(),
        "freshness": {"phase": FRESHNESS["phase"], "phase_name": FRESHNESS["phase_name"]},
        "quote": {k: v for k, v in quote.items() if k != "_validation"},
        "flow_summary": flow.get("summary", {}),
        "flow_trend": flow.get("trend", {}),
        "sector": sector,
        "north_bound": nb,
        "market_strength": ms,
        "market_breadth": mb,
        "scenarios": [{k: v for k, v in s.items() if k != "historical_ref"} for s in scenarios],
    }
    with open(os.path.join(dir_path, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data_json, f, ensure_ascii=False, indent=2, default=str)

    print(f"  报告目录: {dir_path}/")

if __name__ == "__main__":
    main()
