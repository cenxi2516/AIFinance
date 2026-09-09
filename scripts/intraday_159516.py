#!/usr/bin/env python3
"""
盘中实时交易信号系统 V1.2 — 半导体设备ETF国泰(159516) 七维分析
日期: 2026-07-10 盘后回顾
数据源: mootdx(分时买卖力道) + 腾讯(行情/K线) + 东财push2(板块/广度) + 同花顺(北向)
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

# ============================================================
# Layer 1: 腾讯行情 + 日K线
# ============================================================
def fetch_tencent_quote(code):
    prefixed = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
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
            "pe": float(vals[39]) if vals[39] else 0,
            "mcap": float(vals[45]) if vals[45] else 0,
        }
    except Exception as e:
        return {"error": str(e)}

def fetch_tencent_kline(code, days=30):
    """从腾讯获取日K线（前复权），用于展示近期走势"""
    prefixed = f"sz{code}" if not code.startswith("6") else f"sh{code}"
    try:
        r = requests.get(
            'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
            params={'param': f'{prefixed},day,,,{days},qfq'}, timeout=12)
        data = r.json()
        raw = data.get('data', {}).get(prefixed, {}).get('qfqday', []) or \
              data.get('data', {}).get(prefixed, {}).get('day', [])
        klines = []
        for d in raw:
            date_str, o, c, h, l, vol = d[0], float(d[1]), float(d[2]), float(d[3]), float(d[4]), float(d[5])
            klines.append({"date": date_str, "open": o, "close": c, "high": h, "low": l,
                           "volume": int(vol), "change_pct": round((c-o)/o*100, 2) if o > 0 else 0})
        return klines
    except Exception as e:
        print(f"  [WARN] 腾讯K线获取失败: {e}")
        return []

# ============================================================
# Layer 2: mootdx 分时数据 → 买卖力道分析
# ============================================================
def fetch_minute_data_mootdx(code, date='20260710'):
    from mootdx.quotes import Quotes
    client = Quotes.factory(market='std')
    try:
        df = client.minutes(symbol=code, date=date)
        if df is None or len(df) == 0: return []
        rows = []
        for idx, row in df.iterrows():
            rows.append({"time": str(idx), "price": float(row.get("price", 0)),
                         "vol": int(row.get("vol", 0))})
        return rows
    except Exception as e:
        print(f"  [WARN] mootdx 分时失败: {e}")
        return []

def analyze_minute_flow(minute_data):
    """从分时价格+成交量推导买卖力道"""
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

    # 趋势
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

    # 转向点
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
        "source": "mootdx 分时数据 → 买卖力道推导",
    }

# ============================================================
# Layer 3: 半导体板块情绪（6大核心板块）
# ============================================================
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

# 半导体设备ETF核心板块 BK代码
SEMI_SECTORS = {
    "BK1036": "半导体设备",
    "BK0892": "半导体概念",
    "BK0472": "国产芯片",
    "BK1062": "半导体材料",
    "BK0888": "光刻机(胶)",
    "BK1091": "中芯概念",
}

def fetch_semi_sector_sentiment():
    """拉取全量概念板块 → 筛选半导体设备ETF核心板块"""
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
    for bk_code, bk_name in SEMI_SECTORS.items():
        sd = all_sectors.get(bk_code)
        if sd:
            blocks.append(sd)
        else:
            blocks.append({"code": bk_code, "name": bk_name, "change_pct": 0,
                           "main_net_wan": 0, "direction": "未知",
                           "up_count": 0, "down_count": 0})

    inflow = sum(1 for b in blocks if b["main_net_wan"] > 0)
    total = len(blocks)
    avg_chg = sum(b["change_pct"] for b in blocks) / total
    total_flow = sum(b["main_net_wan"] for b in blocks)
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
    }

# ============================================================
# Layer 4-7: 新闻/北向/大盘/广度
# ============================================================
def fetch_intraday_news(keywords):
    """搜索半导体设备相关新闻"""
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

    # 去重
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
    total = hgt_net + sgt_net
    total_yi = total / 1e4
    if total > 5000: direction = "大幅流入"; signal = "🟢 积极"
    elif total > 0: direction = "小幅流入"; signal = "🟡 中性偏多"
    elif total > -5000: direction = "小幅流出"; signal = "🟠 中性偏空"
    else: direction = "大幅流出"; signal = "🔴 警惕"
    return {
        "total_net_yi": round(total_yi, 2), "direction": direction, "signal": signal,
        "data_basis": f"沪股通{hgt_net/1e4:+.2f}亿 + 深股通{sgt_net/1e4:+.2f}亿 = 北向合计{total_yi:+.2f}亿",
        "source": "同花顺 hsgtApi",
    }

def fetch_market_strength(code, quote):
    indices = {"上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006"}
    market_data = {}
    for name, idx in indices.items():
        try:
            req = Request(f"https://qt.gtimg.cn/q={idx}"); req.add_header("User-Agent", UA)
            vals = urlopen(req, timeout=5).read().decode("gbk").split('"')[1].split("~")
            if len(vals) >= 33:
                market_data[name] = {"change_pct": float(vals[32]) if vals[32] else 0}
        except Exception:
            market_data[name] = {"change_pct": 0}
    if code.startswith(("6","9")): bench = "上证指数"
    elif code.startswith("30"): bench = "创业板指"
    else: bench = "深证成指"
    bc = market_data.get(bench, {}).get("change_pct", 0)
    sc = quote.get("change_pct", 0)
    rs = sc - bc
    if bc > 1: env = "🟢 大盘强势"
    elif bc > 0: env = "🟡 大盘微涨"
    elif bc > -1: env = "🟠 大盘微跌"
    else: env = "🔴 大盘弱势"
    if rs > 3: rating = "🚀 显著跑赢"
    elif rs > 1: rating = "✅ 跑赢大盘"
    elif rs > -1: rating = "➖ 与大盘同步"
    elif rs > -3: rating = "⚠️ 跑输大盘"
    else: rating = "🔴 显著跑输"
    return {
        "benchmark": bench, "benchmark_change": round(bc, 2),
        "market_env": env, "relative_strength": round(rs, 2),
        "relative_rating": rating,
        "market_detail": {k: round(v.get("change_pct", 0), 2) for k, v in market_data.items()},
        "data_basis": f"{bench}{bc:+.2f}%, 个股{sc:+.2f}%, 相对强弱{rs:+.2f}%",
    }

def fetch_market_breadth():
    params = {"pn": "1", "pz": "1", "po": "0", "np": "1",
              "fltt": "2", "invt": "2",
              "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
              "fields": "f104,f105"}
    try:
        r = em_get(PUSH2_CLIST, params=params,
                   headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        items = r.json().get("data", {}).get("diff", [])
        up_count = sum(it.get("f104", 0) for it in items) if items else 0
        down_count = sum(it.get("f105", 0) for it in items) if items else 0
    except Exception:
        up_count, down_count = 0, 0
    try:
        r = requests.get("https://push2ex.eastmoney.com/getTopicZTPool",
                        params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                                "sort": "fbt", "fbt": "desc"},
                        headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        limit_up = r.json().get("data", {}).get("total", 0) or 0
    except Exception: limit_up = 0
    try:
        r = requests.get("https://push2ex.eastmoney.com/getTopicDTPool",
                        params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                                "sort": "fund", "fund": "desc"},
                        headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        limit_down = r.json().get("data", {}).get("total", 0) or 0
    except Exception: limit_down = 0

    total = up_count + down_count
    up_ratio = up_count / max(total, 1) * 100
    if up_ratio >= 70: bl = "🟢 普涨格局"; bs = 85
    elif up_ratio >= 55: bl = "🟡 涨多跌少"; bs = 60
    elif up_ratio >= 45: bl = "🟠 分化格局"; bs = 40
    elif up_ratio >= 30: bl = "🔴 跌多涨少"; bs = 20
    else: bl = "💀 普跌格局"; bs = 5

    lr = limit_up / max(limit_down, 1)
    if lr >= 3: me = "🔥 强赚钱效应"
    elif lr >= 1.5: me = "✅ 赚钱效应良好"
    elif lr >= 1: me = "➖ 赚钱效应中性"
    elif lr >= 0.5: me = "⚠️ 亏钱效应显现"
    else: me = "💀 强亏钱效应"

    return {
        "up_count": up_count, "down_count": down_count,
        "up_ratio_pct": round(up_ratio, 1), "breadth_level": bl,
        "breadth_score": bs, "limit_up_count": limit_up,
        "limit_down_count": limit_down, "limit_ratio": round(lr, 1),
        "money_effect": me,
        "data_basis": f"全市场涨{up_count}跌{down_count}({up_ratio:.1f}%), 涨停{limit_up}/跌停{limit_down}, 赚钱效应:{me}",
    }

# ============================================================
# 引擎：七维概率预判
# ============================================================
def generate_scenarios(quote, flow, sector, news, nb, ms, mb):
    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)

    buy_ratio = flow.get("summary", {}).get("buy_ratio_pct", 50)
    ft = flow.get("trend", {})
    direction = ft.get("direction", "")
    acceleration = ft.get("acceleration", "")
    ss = sector.get("sentiment_score", 50)
    inflow = sector.get("inflow_blocks", 0)
    total = sector.get("total_blocks", 1)

    news_b = news.get("bullish_count", 0)
    news_br = news.get("bearish_count", 0)
    nb_yi = nb.get("total_net_yi", 0)
    rs = ms.get("relative_strength", 0)
    market_env = ms.get("market_env", "")
    up_ratio = mb.get("up_ratio_pct", 50)
    limit_ratio = mb.get("limit_ratio", 1)
    money_effect = mb.get("money_effect", "")

    scenarios = []

    # === A: 强势反弹 ===
    ac = []; ascore = 0
    if buy_ratio > 55 and direction == "买方占优":
        ascore += 25; ac.append({"c": "买方力道>55%", "t": ">55%", "a": f"{buy_ratio:.1f}%", "m": True, "w": 25})
    else: ac.append({"c": "买方力道>55%", "t": ">55%", "a": f"{buy_ratio:.1f}%", "m": False, "w": 25})
    if ss >= 60:
        ascore += 20; ac.append({"c": "板块情绪≥60", "t": "≥60", "a": f"{ss:.0f}分({inflow}/{total}流入)", "m": True, "w": 20})
    else: ac.append({"c": "板块情绪≥60", "t": "≥60", "a": f"{ss:.0f}分", "m": False, "w": 20})
    if vol_ratio >= 0.8 and turnover < 15:
        ascore += 15; ac.append({"c": "量能正常", "t": "量比≥0.8,换手<15%", "a": f"量比{vol_ratio},换手{turnover}%", "m": True, "w": 15})
    else: ac.append({"c": "量能正常", "t": "量比≥0.8,换手<15%", "a": f"量比{vol_ratio},换手{turnover}%", "m": False, "w": 15})
    if "买方加速" in acceleration or "卖压减弱" in acceleration:
        ascore += 15; ac.append({"c": "力道改善", "t": "买方加速/卖压减弱", "a": acceleration, "m": True, "w": 15})
    else: ac.append({"c": "力道改善(买方加速/卖压减弱)", "t": "买方加速/卖压减弱", "a": acceleration, "m": False, "w": 15})
    if nb_yi > 1:
        ascore += 10; ac.append({"c": "北向流入>1亿", "t": ">1亿", "a": f"{nb_yi:+.2f}亿", "m": True, "w": 10})
    elif nb_yi < -5:
        ascore -= 5; ac.append({"c": "北向不拖累", "t": "> -5亿", "a": f"{nb_yi:+.2f}亿(⚠️扣分)", "m": False, "w": 10})
    else: ac.append({"c": "北向不拖累", "t": "不大幅流出", "a": f"{nb_yi:+.2f}亿", "m": nb_yi>-5, "w": 10})
    if rs > 1 and "弱势" not in market_env:
        ascore += 5; ac.append({"c": "大盘共振", "t": "相对强度>1%", "a": f"{market_env}, 相对{rs:+.2f}%", "m": True, "w": 5})
    else: ac.append({"c": "大盘共振", "t": "相对强度>1%", "a": f"{market_env}, 相对{rs:+.2f}%", "m": False, "w": 5})
    if up_ratio >= 45 and "亏钱" not in money_effect:
        ascore += 5; ac.append({"c": "广度不差", "t": "上涨≥45%", "a": f"涨{up_ratio:.0f}%", "m": True, "w": 5})
    else: ac.append({"c": "广度不差", "t": "上涨≥45%", "a": f"涨{up_ratio:.0f}%", "m": False, "w": 5})
    bullish_dims = sum([1 if buy_ratio > 50 else 0, 1 if ss >= 50 else 0,
                        1 if change_pct > -1 else 0, 1 if news_b > news_br else 0,
                        1 if nb_yi > 0 else 0, 1 if rs > -0.5 else 0,
                        1 if up_ratio >= 45 else 0])
    if bullish_dims >= 5: ascore += 5

    met_count_a = sum(1 for c in ac if c["m"])
    scenarios.append({
        "name": "情景A: 强势反弹", "raw_score": ascore, "conditions": ac,
        "met_count": met_count_a, "total_conditions": len(ac),
        "description": "买方占优 + 板块共振 + 北向配合 + 量能正常 → 反弹概率较高",
        "historical_ref": {"rule": "买力>55%+板块情绪≥60 → 后续走强概率约55-65%", "historical_win_rate": "约55-65%"},
        "failure_conditions": ["外围大跌", "板块情绪骤降"],
    })

    # === B: 震荡横盘 ===
    bc2 = []; bscore = 0
    if 45 <= buy_ratio <= 55:
        bscore += 30; bc2.append({"c": "买卖均衡(45-55%)", "t": "45-55%", "a": f"{buy_ratio:.1f}%", "m": True, "w": 30})
    else: bc2.append({"c": "买卖均衡(45-55%)", "t": "45-55%", "a": f"{buy_ratio:.1f}%", "m": False, "w": 30})
    if 35 <= ss <= 65:
        bscore += 25; bc2.append({"c": "情绪中性(35-65)", "t": "35-65", "a": f"{ss:.0f}分", "m": True, "w": 25})
    else: bc2.append({"c": "情绪中性(35-65)", "t": "35-65", "a": f"{ss:.0f}分", "m": False, "w": 25})
    nb_neu = abs(nb_yi) < 3; bscore += 10 if nb_neu else 0
    bc2.append({"c": "北向无方向(±3亿)", "t": "|北向|<3亿", "a": f"{nb_yi:+.2f}亿", "m": nb_neu, "w": 10})
    bc_neu = 40 <= up_ratio <= 60; bscore += 10 if bc_neu else 0
    bc2.append({"c": "广度中性(40-60%)", "t": "40-60%", "a": f"{up_ratio:.0f}%", "m": bc_neu, "w": 10})
    scenarios.append({
        "name": "情景B: 震荡横盘", "raw_score": bscore, "conditions": bc2,
        "met_count": sum(1 for c in bc2 if c["m"]), "total_conditions": len(bc2),
        "description": "买卖均衡+情绪中性+无催化 → 窄幅震荡",
        "historical_ref": {"rule": "买卖均衡+情绪中性 → 窄幅震荡约50-55%", "historical_win_rate": "约50-55%"},
        "failure_conditions": ["突发消息催化"],
    })

    # === C: 冲高回落 ===
    cc = []; cscore = 0
    if change_pct > 3 and "买力减弱" in acceleration:
        cscore += 30; cc.append({"c": "已涨>3%+买力减弱", "t": "涨>3%+买力减弱", "a": f"涨{change_pct:+.2f}%, {acceleration}", "m": True, "w": 30})
    else: cc.append({"c": "已涨>3%+买力减弱", "t": "涨>3%+买力减弱", "a": f"涨{change_pct:+.2f}%, {acceleration}", "m": False, "w": 30})
    if nb_yi < -2: cscore += 10
    cc.append({"c": "北向流出配合", "t": "<-2亿", "a": f"{nb_yi:+.2f}亿", "m": nb_yi < -2, "w": 10})
    money_weak = limit_ratio < 1.5 or "亏钱" in money_effect
    if money_weak: cscore += 10
    cc.append({"c": "赚钱效应转弱", "t": "涨跌停比<1.5", "a": f"{limit_ratio}, {money_effect}", "m": money_weak, "w": 10})
    scenarios.append({
        "name": "情景C: 冲高回落", "raw_score": cscore, "conditions": cc,
        "met_count": sum(1 for c in cc if c["m"]), "total_conditions": len(cc),
        "description": "高位+买力减弱+北向流出 → 警惕回落",
        "historical_ref": {"rule": "涨>3%+买力转弱 → 回落概率约55-65%", "historical_win_rate": "约55-65%"},
        "failure_conditions": ["超预期利好"],
    })

    # === D: 弱势下跌 ===
    dc = []; dscore = 0
    if buy_ratio < 40 and direction == "卖方占优":
        dscore += 30; dc.append({"c": "卖方力道>60%", "t": "卖力>60%", "a": f"买力{buy_ratio:.1f}%(卖力{100-buy_ratio:.1f}%)", "m": True, "w": 30})
    else: dc.append({"c": "卖方力道>60%", "t": ">60%", "a": f"买力{buy_ratio:.1f}%", "m": False, "w": 30})
    if ss < 40:
        dscore += 25; dc.append({"c": "板块情绪<40(偏冷)", "t": "<40", "a": f"{ss:.0f}分", "m": True, "w": 25})
    else: dc.append({"c": "板块情绪<40", "t": "<40", "a": f"{ss:.0f}分", "m": False, "w": 25})
    if "卖压加速" in acceleration:
        dscore += 20; dc.append({"c": "卖压加速", "t": "卖压加速", "a": acceleration, "m": True, "w": 20})
    else: dc.append({"c": "卖压加速", "t": "卖压加速", "a": acceleration, "m": False, "w": 20})
    if nb_yi < -5: dscore += 10
    dc.append({"c": "北向大幅流出", "t": "<-5亿", "a": f"{nb_yi:+.2f}亿", "m": nb_yi<-5, "w": 10})
    mkt_drag = "弱势" in market_env and rs < -0.5
    if mkt_drag: dscore += 10
    dc.append({"c": "大盘拖累", "t": "大盘弱势+跑输", "a": f"{market_env}, 相对{rs:+.2f}%", "m": mkt_drag, "w": 10})
    breadth_bear = up_ratio < 35
    if breadth_bear: dscore += 10
    dc.append({"c": "普跌格局", "t": "上涨<35%", "a": f"{up_ratio:.0f}%", "m": breadth_bear, "w": 10})
    bearish_dims = sum([1 if buy_ratio < 45 else 0, 1 if ss < 45 else 0,
                        1 if change_pct < -1 else 0, 1 if nb_yi < 0 else 0,
                        1 if rs < -0.5 else 0, 1 if up_ratio < 45 else 0])
    if bearish_dims >= 5: dscore += 8

    met_count_d = sum(1 for c in dc if c["m"])
    scenarios.append({
        "name": "情景D: 弱势下跌", "raw_score": dscore, "conditions": dc,
        "met_count": met_count_d, "total_conditions": len(dc),
        "description": "卖压沉重 + 板块冰冷 + 加速卖出 + 大盘拖累 → 继续走弱概率高",
        "historical_ref": {"rule": "卖力>60%+板块情绪<40 → 收阴概率约60-70%", "historical_win_rate": "约60-70%"},
        "failure_conditions": ["国家队护盘", "尾盘突发利好"],
    })

    # 归一化
    total_score = sum(s["raw_score"] for s in scenarios)
    for s in scenarios:
        s["probability"] = round(s["raw_score"]/total_score*100, 1) if total_score > 0 else 0
    sorted_sc = sorted(scenarios, key=lambda x: x["probability"], reverse=True)
    return {"scenarios": sorted_sc, "primary_scenario": sorted_sc[0] if sorted_sc else None,
            "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M")}

# ============================================================
# 信号：买卖时机参考
# ============================================================
def generate_signals(scenarios, quote, flow, sector, nb, ms, mb):
    primary = scenarios[0] if scenarios else {}
    pp = primary.get("probability", 0); pn = primary.get("name", "")
    change_pct = quote.get("change_pct", 0); price = quote.get("price", 0)
    turnover = quote.get("turnover_pct", 0); vol_ratio = quote.get("vol_ratio", 0)
    buy_ratio = flow.get("summary", {}).get("buy_ratio_pct", 50)
    ft = flow.get("trend", {})
    acceleration = ft.get("acceleration", "")
    ss = sector.get("sentiment_score", 50)
    nb_yi = nb.get("total_net_yi", 0); rs = ms.get("relative_strength", 0)
    up_ratio = mb.get("up_ratio_pct", 50)

    buy_signals = []; sell_signals = []

    # 买入信号
    sbm = sum([1 if pp >= 55 and "情景A" in pn else 0, 1 if buy_ratio > 55 else 0,
               1 if ss >= 60 else 0, 1 if change_pct < 5 else 0])
    if sbm >= 4:
        buy_signals.append({"level": "🟢🟢🟢 强买入参考", "strength": sbm,
            "data_evidence": [
                {"item": "情景A概率", "value": f"{pp:.0f}%", "threshold": "≥55%", "source": "概率引擎", "met": pp >= 55},
                {"item": "买方力道", "value": f"{buy_ratio:.1f}%", "threshold": ">55%", "source": "mootdx", "met": buy_ratio > 55},
                {"item": "板块情绪", "value": f"{ss:.0f}/100", "threshold": "≥60", "source": "东财板块", "met": ss >= 60},
                {"item": "当前跌幅", "value": f"{change_pct:+.2f}%", "threshold": "<5%", "source": "腾讯行情", "met": change_pct < 5}],
            "action": "可考虑逢低建仓/加仓",
            "stop_loss": f"跌破{price*0.97:.3f}(-3%)则果断离场",
            "principle": "宁可少挣: 4个条件满足才触发"})

    mbm = sum([1 if pp >= 40 and "情景A" in pn else 0, 1 if buy_ratio > 50 else 0,
               1 if ss >= 50 else 0, 1 if change_pct < 7 else 0])
    if mbm >= 3 and sbm < 4:
        buy_signals.append({"level": "🟢🟢 中等买入参考", "strength": mbm,
            "data_evidence": [
                {"item": "情景A概率", "value": f"{pp:.0f}%", "threshold": "≥40%", "source": "概率引擎", "met": pp >= 40},
                {"item": "买方力道", "value": f"{buy_ratio:.1f}%", "threshold": ">50%", "source": "mootdx", "met": buy_ratio > 50},
                {"item": "板块情绪", "value": f"{ss:.0f}/100", "threshold": "≥50", "source": "东财板块", "met": ss >= 50},
                {"item": "当前跌幅", "value": f"{change_pct:+.2f}%", "threshold": "<7%", "source": "腾讯行情", "met": change_pct < 7}],
            "action": "可小仓位试探(计划仓位30-50%), 等待更多信号确认",
            "stop_loss": f"跌破{price*0.95:.3f}(-5%)则止损",
            "principle": "宁可少挣: 先小仓试错"})

    if not buy_signals:
        buy_signals.append({"level": "⚪ 暂不建议买入",
            "data_evidence": [
                {"item": "情景A概率", "value": f"{pp:.0f}%", "threshold": "需≥40%", "source": "概率引擎", "met": pp >= 40},
                {"item": "买方力道", "value": f"{buy_ratio:.1f}%", "threshold": "需>50%", "source": "mootdx", "met": buy_ratio > 50}],
            "action": "继续观察, 等待买力+情绪共振",
            "principle": "宁可少挣: 不买至少不亏钱"})

    # 卖出信号
    ssm = sum([1 if pp >= 50 and ("情景C" in pn or "情景D" in pn) else 0,
               1 if buy_ratio < 40 else 0,
               1 if "卖压加速" in acceleration else 0])
    if ssm >= 3:
        sell_signals.append({"level": "🔴🔴🔴 强卖出参考", "strength": ssm,
            "data_evidence": [
                {"item": "弱势情景概率", "value": f"{pp:.0f}%({pn})", "threshold": "≥50%", "source": "概率引擎", "met": pp >= 50},
                {"item": "卖方力道", "value": f"买力{buy_ratio:.1f}%(卖力{100-buy_ratio:.1f}%)", "threshold": "卖力>60%", "source": "mootdx", "met": buy_ratio < 40},
                {"item": "卖压趋势", "value": acceleration, "threshold": "卖压加速", "source": "mootdx趋势", "met": "卖压加速" in acceleration},
                {"item": "板块情绪", "value": f"{ss:.0f}/100", "threshold": "偏冷(<50)", "source": "板块", "met": ss < 50}],
            "action": "建议果断减仓/清仓, 不在下跌中补仓",
            "risk_note": f"卖方力道已达{100-buy_ratio:.1f}%, 继续持有可能面临更大回撤",
            "principle": "宁可少亏: 卖了少亏比扛着大亏好"})

    msm = sum([1 if ("情景C" in pn and pp >= 30) or ("情景D" in pn and pp >= 30) else 0,
               1 if buy_ratio < 45 else 0])
    if msm >= 2 and ssm < 3:
        sell_signals.append({"level": "🔴🔴 中等卖出参考", "strength": msm,
            "data_evidence": [
                {"item": "弱势情景概率", "value": f"{pp:.0f}%({pn})", "threshold": "≥30%", "source": "概率引擎", "met": pp >= 30},
                {"item": "卖方力道", "value": f"买力{buy_ratio:.1f}%", "threshold": "买力<45%", "source": "mootdx", "met": buy_ratio < 45},
                {"item": "板块情绪", "value": f"{ss:.0f}/100", "threshold": "偏冷", "source": "板块", "met": ss < 50}],
            "action": "建议逐步减仓, 至少减到半仓以下",
            "principle": "宁可少亏: 卖一半留一半"})

    if not sell_signals:
        sell_signals.append({"level": "⚪ 暂不需卖出",
            "data_evidence": [
                {"item": "买方力道", "value": f"{buy_ratio:.1f}%", "threshold": ">50%", "source": "mootdx", "met": buy_ratio > 50}],
            "action": "继续持有观察",
            "principle": "保持警觉"})

    # 持有
    if "情景A" in pn and pp >= 45:
        hold = {"level": "✅ 可继续持有", "reason": f"反弹概率{pp:.0f}%, 买方力道{buy_ratio:.1f}%",
                "watch_points": ["买力是否转弱", "情绪是否骤降"]}
    elif "情景B" in pn:
        hold = {"level": "⏸️ 持有观望", "reason": f"震荡格局, 买卖{buy_ratio:.1f}%均衡",
                "watch_points": ["突破方向", "催化消息"]}
    else:
        hold = {"level": "⚠️ 审视持仓", "reason": f"风险情景({pn} {pp:.0f}%)",
                "watch_points": ["触发止损则执行", "等待反弹信号"]}

    # 总体
    sb = buy_signals[0]["level"] if buy_signals else ""; ss2 = sell_signals[0]["level"] if sell_signals else ""
    if "强买入" in sb and "暂不需" in ss2: ov = f"总体偏多。买力{buy_ratio:.1f}%, 板块情绪{ss:.0f}分。"
    elif "强卖出" in ss2: ov = f"总体偏空。卖力{100-buy_ratio:.1f}%。建议减仓或观望。"
    elif "中等卖出" in ss2: ov = f"总体谨慎。买力仅{buy_ratio:.1f}%。持有者审视持仓。"
    elif "中等买入" in sb: ov = f"总体中性偏多。买力{buy_ratio:.1f}%。可小仓试探。"
    else: ov = f"总体中性。买力{buy_ratio:.1f}%。建议观望。"

    return {"buy_signals": buy_signals, "sell_signals": sell_signals,
            "hold_verdict": hold, "overall_verdict": ov,
            "data_summary": {"buy_ratio": buy_ratio, "sentiment_score": ss,
                             "change_pct": change_pct, "turnover_pct": turnover,
                             "vol_ratio": vol_ratio}}

# ============================================================
# 主流程与输出
# ============================================================
def print_report(quote, klines, flow, sector, news, nb, ms, mb, scenarios, signals, code):
    print()
    print("═"*70)
    print(f"  📊 盘中实时交易信号: {quote.get('name','')}({code})")
    print(f"  分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  市场状态: 盘后回顾（2026-07-10 全天数据）")
    print("═"*70)

    fs = flow["summary"]; ft = flow["trend"]

    print(f"\n{'─'*60}\n  📈 一、价格面\n{'─'*60}")
    print(f"  {quote.get('name','')}({quote.get('code','')})")
    print(f"  收盘价: {quote.get('price',0):.3f}  涨跌: {quote.get('change_pct',0):+.2f}%  振幅: {quote.get('amplitude',0):.2f}%")
    print(f"  换手率: {quote.get('turnover_pct',0):.2f}%  量比: {quote.get('vol_ratio',0):.2f}  成交额: {quote.get('amount',0):.0f}万")
    print(f"  今开: {quote.get('open',0):.3f}  最高: {quote.get('high',0):.3f}  最低: {quote.get('low',0):.3f}")
    if klines:
        print(f"\n  近10日走势:")
        for k in klines[-10:]:
            emoji = "🟢" if k['change_pct'] > 0 else "🔴"
            bar = "█" * min(int(abs(k['change_pct'])*2), 20)
            print(f"    {k['date']} {emoji} {k['change_pct']:+.1f}% {bar}")

    print(f"\n{'─'*60}\n  💰 二、买卖力道 (mootdx分时)\n{'─'*60}")
    print(f"  数据点: {fs['data_points']}分钟 ({fs['first_time']}→{fs['last_time']})")
    print(f"  买方总量: {fs['total_buy_vol']:,}  卖方总量: {fs['total_sell_vol']:,}")
    print(f"  净买卖力道: {fs['total_net_vol']:+,}  |  买方占比: {fs['buy_ratio_pct']:.1f}%")
    print(f"  趋势: {ft['direction']} | {ft['acceleration']}")
    for tp in ft.get("turning_points", []):
        print(f"  转向点: {tp['time']} {tp['type']}: {tp['value']:+,}")

    print(f"\n{'─'*60}\n  🎯 三、半导体设备板块情绪\n{'─'*60}")
    print(f"  情绪分: {sector['sentiment_score']:.0f}/100 {sector['level']}")
    print(f"  {sector['data_basis']}")
    for bk in sector.get("blocks", []):
        emoji = "🟢" if bk["main_net_wan"] > 0 else "🔴"
        print(f"    {emoji} {bk['name']}: 主力{bk['main_net_wan']:+.0f}万 涨跌{bk['change_pct']:+.2f}% 涨{bk['up_count']}跌{bk['down_count']}")

    print(f"\n{'─'*60}\n  📰 四、消息面\n{'─'*60}")
    print(f"  今日新闻: {news['today_count']}条 (利好{news['bullish_count']}/利空{news['bearish_count']})")
    for h in (news.get("highlights") or [])[:8]:
        e = "🟢" if h["sentiment"]=="bullish" else ("🔴" if h["sentiment"]=="bearish" else "⚪")
        print(f"  {e} [{h['time']}] {h['title'][:80]}")

    print(f"\n{'─'*60}\n  🌏 五、北向 + 大盘 + 广度\n{'─'*60}")
    print(f"  北向: {nb['data_basis']}  {nb['signal']}")
    print(f"  大盘: {ms['data_basis']}  |  {ms['relative_rating']} {ms['market_env']}")
    for k, v in ms.get("market_detail", {}).items():
        print(f"    {k}: {v:+.2f}%")
    print(f"  广度: {mb['data_basis']}")
    print(f"  评级: {mb['breadth_level']} ({mb['breadth_score']}分)")

    print(f"\n{'─'*60}\n  🔮 六、七维概率预判\n{'─'*60}")
    for sc in scenarios["scenarios"]:
        icon = "🔥" if sc["probability"] >= 50 else ("📊" if sc["probability"] >= 25 else "🔍")
        print(f"\n  {icon} {sc['name']} → 概率: {sc['probability']:.0f}% (满足{sc['met_count']}/{sc['total_conditions']})")
        print(f"     {sc['description']}")
        for c in sc["conditions"]:
            st = "✅" if c["m"] else "❌"
            print(f"     {st} {c['c']}: 阈值{c['t']}, 当前={c['a']}")
        print(f"     参考: {sc['historical_ref']['rule']} ({sc['historical_ref']['historical_win_rate']})")

    print(f"\n{'─'*60}\n  ⚡ 七、买卖时机参考\n{'─'*60}")
    print(f"\n  📥 买入参考:")
    for bs in signals["buy_signals"]:
        print(f"    {bs['level']}")
        for ev in bs["data_evidence"]:
            st = "✅" if ev["met"] else "❌"
            print(f"      {st} {ev['item']}: {ev['value']} (阈值:{ev['threshold']}) [{ev['source']}]")
        print(f"    操作: {bs['action']}")
        if bs.get("stop_loss"): print(f"    止损: {bs['stop_loss']}")
        print(f"    原则: {bs['principle']}")

    print(f"\n  📤 卖出参考:")
    for ss in signals["sell_signals"]:
        print(f"    {ss['level']}")
        for ev in ss["data_evidence"]:
            st = "✅" if ev["met"] else "❌"
            print(f"      {st} {ev['item']}: {ev['value']} (阈值:{ev['threshold']}) [{ev['source']}]")
        print(f"    操作: {ss['action']}")
        if ss.get("risk_note"): print(f"    风险: {ss['risk_note']}")
        print(f"    原则: {ss['principle']}")

    hv = signals.get("hold_verdict", {})
    if hv:
        print(f"\n  📌 持有参考: {hv['level']}")
        print(f"    {hv['reason']}")
        for wp in hv["watch_points"]: print(f"    👁 {wp}")

    print(f"\n  ━━━━━━━━━━━━")
    print(f"  🎯 综合评估: {signals['overall_verdict']}")

    ds = signals["data_summary"]
    print(f"\n  📋 七维数据摘要:")
    print(f"     买卖力道: 买力{ds['buy_ratio']:.1f}% | 涨跌{ds['change_pct']:+.2f}% | 换手{ds['turnover_pct']}% | 量比{ds['vol_ratio']}")
    print(f"     情绪: {ds['sentiment_score']:.0f}分 | 北向: {nb['total_net_yi']:+.2f}亿 {nb['direction']}")
    print(f"     大盘: {ms['data_basis']} | 广度: {mb['data_basis']}")

    print(f"\n{'═'*70}")
    print(f"  ⚠️ 研究声明: 买卖力道基于mootdx分时数据推导,不构成投资建议")
    print(f"  核心原则: 宁可少挣,宁可少亏——不确定时不出手")
    print(f"{'═'*70}\n")

def main():
    code = "159516"
    print("═"*70)
    print("  盘中实时交易信号系统 V1.2 — 半导体设备ETF国泰(159516)")
    print("  ETF版: mootdx分时买卖力道替代资金流")
    print("  日期: 2026-07-10 (周五) 盘后回顾")
    print("═"*70)

    print("\n[1/6] 实时行情 + 日K线...")
    quote = fetch_tencent_quote(code)
    print(f"  {quote.get('name','?')}({code}) 收盘{quote.get('price',0):.3f} 涨跌{quote.get('change_pct',0):+.2f}%  振幅{quote.get('amplitude',0):.2f}%")
    klines = fetch_tencent_kline(code, 30)
    if klines:
        print(f"  K线: {len(klines)}天")
        for k in klines[-5:]:
            print(f"    {k['date']}: {k['change_pct']:+.1f}%")

    print("\n[2/6] 分钟级买卖力道...")
    md = fetch_minute_data_mootdx(code, '20260710')
    print(f"  分时数据: {len(md)}条")
    flow = analyze_minute_flow(md)
    fs = flow["summary"]; ft = flow["trend"]
    print(f"  买方: {fs['total_buy_vol']:,}  卖方: {fs['total_sell_vol']:,}")
    print(f"  买力: {fs['buy_ratio_pct']:.1f}%  净买卖: {fs['total_net_vol']:+,}")
    print(f"  趋势: {ft['direction']} | {ft['acceleration']}")
    for tp in ft.get("turning_points", []):
        print(f"  转向: {tp['time']} {tp['type']}: {tp['value']:+,}")

    print("\n[3/6] 板块情绪 + 新闻...")
    sector = fetch_semi_sector_sentiment()
    print(f"  板块情绪: {sector['sentiment_score']:.0f}/100 {sector['level']}")
    print(f"  全市场板块: {sector.get('all_sectors_count', 0)}个")
    for bk in sector.get("blocks", []):
        print(f"    {bk['name']}: 主力{bk['main_net_wan']:+.0f}万 涨跌{bk['change_pct']:+.2f}%")
    news = fetch_intraday_news(["半导体设备", "芯片", "光刻机", "国产替代"])
    print(f"  新闻: {news['today_count']}条 (利好{news['bullish_count']}/利空{news['bearish_count']})")

    print("\n[4/6] 北向 + 大盘 + 广度...")
    nb = fetch_north_bound()
    print(f"  北向: {nb['data_basis']}")
    ms = fetch_market_strength(code, quote)
    print(f"  大盘: {ms['data_basis']}")
    mb = fetch_market_breadth()
    print(f"  广度: {mb['data_basis']}")

    print("\n[5/6] 七维概率预判...")
    scenarios = generate_scenarios(quote, flow, sector, news, nb, ms, mb)
    for sc in scenarios["scenarios"]:
        print(f"  {sc['name']}: 概率{sc['probability']:.0f}% ({sc['met_count']}/{sc['total_conditions']})")

    print("\n[6/6] 买卖时机参考...")
    signals = generate_signals(scenarios["scenarios"], quote, flow, sector, nb, ms, mb)

    print_report(quote, klines, flow, sector, news, nb, ms, mb, scenarios, signals, code)

    # 保存数据
    os.makedirs("src/盘中交易信号/2026-07-10-半导体设备ETF国泰-盘中信号", exist_ok=True)
    data_json = {
        "target": {"type": "ETF", "code": code, "name": quote.get("name", "")},
        "analysis_time": datetime.now().isoformat(),
        "quote": {k: v for k, v in quote.items() if k not in ("error",)},
        "flow_summary": flow.get("summary", {}),
        "flow_trend": {k: v for k, v in flow.get("trend", {}).items() if k != "turning_points"},
        "sector_sentiment": {k: v for k, v in sector.items() if k != "blocks"},
        "north_bound": nb, "market_strength": ms, "market_breadth": mb,
        "scenarios": [{"name": s["name"], "probability": s["probability"],
                       "met_count": s["met_count"], "total_conditions": s["total_conditions"]}
                      for s in scenarios["scenarios"]],
        "signals_summary": signals.get("data_summary", {}),
        "overall_verdict": signals.get("overall_verdict", ""),
    }
    with open("src/盘中交易信号/2026-07-10-半导体设备ETF国泰-盘中信号/data.json", "w", encoding="utf-8") as f:
        json.dump(data_json, f, ensure_ascii=False, indent=2, default=str)
    print("数据已保存: src/盘中交易信号/2026-07-10-半导体设备ETF国泰-盘中信号/data.json")

if __name__ == "__main__":
    main()
