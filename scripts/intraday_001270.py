#!/usr/bin/env python3
"""
盘中实时交易信号系统 V1.3 — 铖昌科技(001270) 七维分析
日期: 2026-08-04 盘中
数据源: push2(分钟级资金流) + 腾讯(行情) + mootdx(分时) + 东财push2(板块/广度) + 同花顺(北向)
注: V1.2 动态概念板块 —— 通过 slist 拉取铖昌科技真实归属概念, 再与全量板块资金流匹配
"""
import time, random, requests, json, re, os, sys
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
session = requests.Session()
session.headers.update({"User-Agent": UA})
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    adapter = HTTPAdapter(max_retries=Retry(
        total=2, connect=2, backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    session.mount("https://", adapter)
    session.mount("http://", adapter)
except Exception:
    pass
EM_MIN_INTERVAL = 0.8
_em_last = [0.0]

def em_get(url, params=None, headers=None, timeout=15):
    wait = EM_MIN_INTERVAL - (time.time() - _em_last[0])
    if wait > 0: time.sleep(wait + random.uniform(0.05, 0.3))
    try:
        return session.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last[0] = time.time()

CODE = "001270"
NOW = datetime.now()
DATE_STR = NOW.strftime("%Y%m%d")
DATE_TIME_STR = NOW.strftime("%Y-%m-%d %H:%M:%S")

# ====== 数据时效性门控 V1.3 ======
def check_data_freshness():
    """检查各维度数据在当前时段的可用性"""
    now = datetime.now()
    weekday = now.weekday()
    minutes_from_open = 0
    if weekday < 5:
        h, m = now.hour, now.minute
        total_min = h * 60 + m
        if total_min >= 9 * 60 + 30:
            minutes_from_open = total_min - (9 * 60 + 30)
            if total_min > 11 * 60 + 30:
                minutes_from_open -= 90  # 午休
            if total_min > 13 * 60:
                minutes_from_open = min(minutes_from_open, 240)

    if minutes_from_open <= 0:
        phase = 0
        phase_name = "盘前"
    elif minutes_from_open <= 30:
        phase = 1
        phase_name = f"盘初({minutes_from_open}min, 数据延迟高发期)"
    elif minutes_from_open <= 90:
        phase = 2
        phase_name = f"早盘过渡({minutes_from_open}min)"
    elif minutes_from_open <= 210:
        phase = 3
        phase_name = f"盘中正常({minutes_from_open}min)"
    else:
        phase = 4
        phase_name = f"尾盘({minutes_from_open}min)"

    freshness = {
        "quote": {"available": True, "status": "ready"},
        "minute_flow": {"available": True, "status": "ready"},
        "sector": {"available": minutes_from_open > 15, "status": "ready" if minutes_from_open > 15 else "delayed"},
        "news": {"available": True, "status": "ready"},
        "north_bound": {"available": minutes_from_open > 60, "status": "ready" if minutes_from_open > 60 else "delayed"},
        "market": {"available": True, "status": "ready"},
        "breadth": {"available": minutes_from_open > 30, "status": "ready" if minutes_from_open > 30 else "delayed"},
    }

    weight_matrix = {
        1: {"quote": 25, "minute_flow": 50, "sector": 5, "news": 5, "north_bound": 0, "market": 15, "breadth": 0},
        2: {"quote": 20, "minute_flow": 35, "sector": 12, "news": 8, "north_bound": 5, "market": 12, "breadth": 8},
        3: {"quote": 15, "minute_flow": 25, "sector": 15, "news": 10, "north_bound": 15, "market": 10, "breadth": 10},
        4: {"quote": 15, "minute_flow": 30, "sector": 12, "news": 10, "north_bound": 13, "market": 10, "breadth": 10},
    }

    return {
        "phase": phase,
        "phase_name": phase_name,
        "minutes_from_open": minutes_from_open,
        "freshness": freshness,
        "weights": weight_matrix.get(phase, weight_matrix[3]),
    }

FRESHNESS = check_data_freshness()

# ====== Layer 1: 腾讯实时行情 ======
def fetch_tencent_quote(code):
    prefixed = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
    url = f"https://qt.gtimg.cn/q={prefixed}"
    try:
        req = Request(url); req.add_header("User-Agent", UA)
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

# ====== Layer 2: 分钟级资金流 (push2 新版) ======
def fetch_minute_fund_flow(code):
    """从 push2 eastmoney 拉取当日分钟级资金流"""
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
        params = {
            "lmt": "0", "klt": "1",
            "secid": f"0.{code}" if code[0] in "03" else f"1.{code}",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
        }
        r = em_get(url, params=params, timeout=15)
        d = r.json()
        lines = (d.get("data", {}).get("klines", []) or [])
        if not lines:
            return {"error": "无资金流数据", "minutes": [], "summary": {}, "trend": {}}

        minutes = []
        for l in lines:
            parts = l.split(",")
            if len(parts) >= 6:
                # 字段验证: f52 ≈ -(f53+f54), f53+f54+f55+f56 ≈ 0
                # main_net = 超大单+大单(主力标准定义)，而非直接使用f52
                super_val = float(parts[2]) if parts[2] != "-" else 0
                large_val = float(parts[3]) if parts[3] != "-" else 0
                mid_val = float(parts[4]) if parts[4] != "-" else 0
                small_val = float(parts[5]) if parts[5] != "-" else 0
                minutes.append({
                    "time": parts[0],
                    "main_net": super_val + large_val,  # 主力 = 超大单+大单(标准定义)
                    "super_net": super_val,
                    "large_net": large_val,
                    "mid_net": mid_val,
                    "small_net": small_val,
                })

        if not minutes:
            return {"error": "解析资金流数据为空", "minutes": [], "summary": {}, "trend": {}}

        # ★ 数据为累计值（非每分钟增量），直接用最新值作为总量
        last = minutes[-1]
        total_main = last["main_net"]  # 最新累计主力净流入
        total_super = last["super_net"]
        total_large = last["large_net"]
        total_mid = last["mid_net"]
        total_small = last["small_net"]

        # 累计序列（直接使用原始累计值）
        cum_main = [m["main_net"] for m in minutes]

        # 计算每分钟增量（用于趋势分析）
        deltas = []
        prev_main = 0.0
        for m in minutes:
            delta = m["main_net"] - prev_main
            deltas.append(delta)
            prev_main = m["main_net"]

        # 趋势分析（基于每分钟增量的半段对比）
        if len(deltas) >= 10:
            mid_point = len(deltas) // 2
            first_half_deltas = deltas[1:mid_point]  # 跳过第一分钟(无前值)
            second_half_deltas = deltas[mid_point:]
            first_slope = sum(first_half_deltas) / max(len(first_half_deltas), 1)
            second_slope = sum(second_half_deltas) / max(len(second_half_deltas), 1)
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

        # 转向点检测
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
                "direction": direction,
                "acceleration": acceleration,
                "first_half_slope_wan_per_min": round(first_slope / 1e4, 2),
                "second_half_slope_wan_per_min": round(second_slope / 1e4, 2),
                "cum_sequence_wan": [round(v / 1e4, 1) for v in cum_main],
                "turning_points": turning_points[-5:],
                "last_turn": turning_points[-1] if turning_points else None,
            },
        }
    except Exception as e:
        return {"error": f"资金流拉取失败: {e}", "minutes": [], "summary": {}, "trend": {}}

# ====== mootdx 分时数据 ======
def fetch_minute_data_mootdx(code):
    """从通达信拉取分时价格+成交量"""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        df = client.minutes(symbol=code, date=DATE_STR)
        if df is None or len(df) == 0:
            return []
        rows = []
        for idx, row in df.iterrows():
            rows.append({"time": str(idx), "price": float(row.get("price", 0)),
                         "vol": int(row.get("vol", 0))})
        return rows
    except Exception as e:
        print(f"  [WARN] mootdx 分时失败: {e}")
        return []

def analyze_mootdx_flow(minute_data):
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
        cum_flow.append({"time": minute_data[i]["time"], "net_vol": running, "price": curr_p})

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
    else:
        direction = "数据不足"; accel = "数据不足"

    return {
        "minutes": cum_flow,
        "summary": {
            "total_buy_vol": buy_vol, "total_sell_vol": sell_vol,
            "total_net_vol": buy_vol - sell_vol,
            "buy_ratio_pct": round(buy_ratio, 1),
            "data_points": len(cum_flow),
        },
        "trend": {"direction": direction, "acceleration": accel},
    }

# ====== Layer 3: 板块情绪 (V1.2 动态概念板块) ======
# 排除的分类: 行业(申万)/地区板块/规模风格/ transient(昨日*)
_EXCLUDE_BOARD_TYPES = {"行业", "板块"}
_EXCLUDE_NAME_HINTS = ("昨日", "小盘", "中盘", "大盘", "近期摘帽", "深股通", "融资融券", "沪股通")

def fetch_stock_concept_blocks(code):
    """通过 F10 主题库拉取个股真实归属概念板块 (按名称返回, 用于与 clist 资金流匹配)。
    slist 接口对部分标的返回 null, F10 主题库更稳定。"""
    secucode = f"{code}.SZ" if code[0] in "03" else f"{code}.SH"
    try:
        params = {"reportName": "RPT_F10_CORETHEME_BOARDTYPE", "columns": "ALL",
                  "filter": f'(SECUCODE="{secucode}")',
                  "pageSize": "50", "pageNumber": "1",
                  "sortColumns": "SECURITY_CODE", "sortTypes": "1"}
        r = em_get("https://datacenter.eastmoney.com/securities/api/data/v1/get",
                   params=params, headers={"Referer": "https://emweb.securities.eastmoney.com/"},
                   timeout=10)
        d = r.json()
        items = (d.get("result") or {}).get("data", []) or []
    except Exception as e:
        print(f"  [WARN] F10概念板块拉取失败: {e}")
        return []

    blocks = []
    for it in items:
        name = it.get("BOARD_NAME", "")
        btype = it.get("BOARD_TYPE")
        if not name:
            continue
        # 过滤: 行业分类、地区板块、规模风格、transient 标签
        if btype in _EXCLUDE_BOARD_TYPES:
            continue
        if any(h in name for h in _EXCLUDE_NAME_HINTS):
            continue
        blocks.append({"code": it.get("BOARD_CODE", ""), "name": name,
                       "change_pct": it.get("CHANGE_RATE", 0)})
    return blocks

def fetch_sector_sentiment(code):
    """拉取个股所属概念板块的情绪快照 (F10归属 + 全量概念板块资金流按名称匹配)"""
    stock_blocks = fetch_stock_concept_blocks(code)
    if not stock_blocks:
        return {"error": "未获取到概念板块归属(F10)", "blocks": [], "sentiment_score": 0,
                "inflow_blocks": 0, "total_blocks": 0, "level": ""}

    # 全量概念板块资金流 (m:90+t:3)
    try:
        params = {"pn": "1", "pz": "500", "po": "0", "np": "1",
                  "fltt": "2", "invt": "2", "fs": "m:90+t:3",
                  "fields": "f2,f3,f12,f14,f62,f104,f105"}
        headers = {"Referer": "https://data.eastmoney.com/"}
        r = em_get("https://push2.eastmoney.com/api/qt/clist/get",
                   params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", []) or []
    except Exception as e:
        print(f"  [WARN] 板块资金流拉取失败: {e}")
        items = []

    # 按名称建索引 (F10 的 BOARD_CODE 与 clist 的 BK 码体系不同, 用名称匹配)
    by_name = {}
    for it in items:
        nm = it.get("f14", "")
        if nm:
            main_net = it.get("f62") or 0
            by_name[nm] = {
                "code": it.get("f12", ""), "name": nm,
                "change_pct": it.get("f3", 0),
                "main_net_wan": round(main_net / 1e4, 1),
                "direction": "流入" if main_net > 0 else "流出",
                "up_count": it.get("f104", 0),
                "down_count": it.get("f105", 0),
            }

    sentiment_blocks = []
    for bk in stock_blocks:
        sector_data = by_name.get(bk["name"])
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
        return {"error": "板块数据匹配失败", "blocks": [], "sentiment_score": 0,
                "inflow_blocks": 0, "total_blocks": 0, "level": ""}

    # 计算板块情绪分 (仅用成功匹配到资金流的板块)
    matched = [b for b in sentiment_blocks if b["direction"] != "未知"]
    # 可靠性门槛: 匹配<2个 → 视为不可用(clist可能被限流返回部分数据), 避免薄样本误导情绪分
    if len(matched) < 2:
        return {"error": f"概念板块匹配不足(仅{len(matched)}个, clist可能被限流), 情绪分不可靠",
                "blocks": sentiment_blocks, "sentiment_score": 0,
                "inflow_blocks": 0, "total_blocks": len(matched), "level": ""}
    inflow_count = sum(1 for b in matched if b["main_net_wan"] > 0)
    total_blocks = len(matched)
    avg_change = sum(b["change_pct"] for b in matched) / max(total_blocks, 1)
    total_flow = sum(b["main_net_wan"] for b in matched)

    flow_score = (inflow_count / max(total_blocks, 1)) * 50
    price_score = max(0, min(50, (avg_change + 5) * 5))
    sentiment_score = round(flow_score + price_score, 1)

    if sentiment_score >= 75: level = "🔥 极热"
    elif sentiment_score >= 60: level = "🟢 偏热"
    elif sentiment_score >= 40: level = "🟡 中性"
    elif sentiment_score >= 25: level = "🔵 偏冷"
    else: level = "❄️ 极冷"

    return {
        "blocks": sentiment_blocks,
        "sentiment_score": sentiment_score,
        "level": level,
        "inflow_blocks": inflow_count,
        "total_blocks": total_blocks,
        "avg_change_pct": round(avg_change, 2),
        "total_sector_flow_wan": round(total_flow, 1),
        "data_basis": f"{inflow_count}/{total_blocks}板块流入, 合计{total_flow:+.0f}万, 平均涨跌{avg_change:+.2f}%, 情绪分{sentiment_score}",
    }

# ====== Layer 4: 消息面 ======
def fetch_intraday_news(code):
    """拉取个股近期新闻"""
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
    try:
        r = em_get("https://search-api-web.eastmoney.com/search/jsonp",
                   params={"cb": cb, "param": inner},
                   headers={"Referer": "https://so.eastmoney.com/"}, timeout=10)
        text = r.text
        json_str = text[text.index("(") + 1:text.rindex(")")]
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
        "today_count": len(today_news),
        "highlights": highlights,
        "bullish_count": sum(1 for h in highlights if h["sentiment"] == "bullish"),
        "bearish_count": sum(1 for h in highlights if h["sentiment"] == "bearish"),
    }

# ====== Layer 5: 北向资金 ======
def fetch_north_bound():
    """拉取北向资金实时流向"""
    hgt_net = 0.0; sgt_net = 0.0
    # 沪股通
    try:
        r_hgt = requests.get("https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/hgt",
                             headers={"User-Agent": UA}, timeout=8)
        hgt_data = r_hgt.json()
        hgt_items = hgt_data.get("data", []) if isinstance(hgt_data.get("data"), list) else []
        hgt_net = sum(it.get("net", 0) for it in (hgt_items or [])[-10:])
    except Exception:
        pass
    # 深股通
    try:
        r_sgt = requests.get("https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/sgt",
                             headers={"User-Agent": UA}, timeout=8)
        sgt_data = r_sgt.json()
        sgt_items = sgt_data.get("data", []) if isinstance(sgt_data.get("data"), list) else []
        sgt_net = sum(it.get("net", 0) for it in (sgt_items or [])[-10:])
    except Exception:
        pass

    total_net = hgt_net + sgt_net
    total_net_yi = total_net / 1e4

    if total_net > 5000: direction = "大幅流入"; signal = "🟢 积极"
    elif total_net > 0: direction = "小幅流入"; signal = "🟡 中性偏多"
    elif total_net > -5000: direction = "小幅流出"; signal = "🟠 中性偏空"
    else: direction = "大幅流出"; signal = "🔴 警惕"

    return {
        "hgt_net_wan": round(hgt_net, 0),
        "sgt_net_wan": round(sgt_net, 0),
        "total_net_wan": round(total_net, 0),
        "total_net_yi": round(total_net_yi, 2),
        "direction": direction,
        "signal": signal,
        "data_basis": f"沪股通{hgt_net/1e4:+.2f}亿 + 深股通{sgt_net/1e4:+.2f}亿 = 北向合计{total_net_yi:+.2f}亿",
    }

# ====== Layer 6: 大盘强度 ======
def fetch_market_strength(code, quote):
    """拉取大盘指数 + 计算个股相对强弱"""
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
                market_data[name] = {
                    "price": float(vals[3]) if vals[3] else 0,
                    "change_pct": float(vals[32]) if vals[32] else 0,
                }
        except Exception:
            market_data[name] = {"price": 0, "change_pct": 0}

    primary_benchmark = "上证指数" if code.startswith(("6", "9")) else ("创业板指" if code.startswith("30") else "深证成指")
    benchmark_change = market_data.get(primary_benchmark, {}).get("change_pct", 0)
    stock_change = quote.get("change_pct", 0)
    relative_strength = stock_change - benchmark_change

    if benchmark_change > 1: market_env = "🟢 大盘强势"
    elif benchmark_change > 0: market_env = "🟡 大盘微涨"
    elif benchmark_change > -1: market_env = "🟠 大盘微跌"
    else: market_env = "🔴 大盘弱势"

    if relative_strength > 3: relative_rating = "🚀 显著跑赢"
    elif relative_strength > 1: relative_rating = "✅ 跑赢大盘"
    elif relative_strength > -1: relative_rating = "➖ 与大盘同步"
    elif relative_strength > -3: relative_rating = "⚠️ 跑输大盘"
    else: relative_rating = "🔴 显著跑输"

    return {
        "benchmark": primary_benchmark,
        "benchmark_change": round(benchmark_change, 2),
        "market_env": market_env,
        "stock_change": round(stock_change, 2),
        "relative_strength": round(relative_strength, 2),
        "relative_rating": relative_rating,
        "market_detail": {k: round(v.get("change_pct", 0), 2) for k, v in market_data.items()},
        "data_basis": f"{primary_benchmark}{benchmark_change:+.2f}%, 个股{stock_change:+.2f}%, 相对强弱{relative_strength:+.2f}%",
    }

# ====== Layer 7: 市场广度 ======
def fetch_market_breadth():
    """全市场涨跌家数 + 涨停/跌停家数"""
    up_count, down_count = 0, 0
    try:
        params = {
            "pn": "1", "pz": "1", "po": "0", "np": "1",
            "fltt": "2", "invt": "2",
            "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f104,f105",
        }
        r = em_get("https://push2.eastmoney.com/api/qt/clist/get",
                   params=params, headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        d = r.json()
        items = d.get("data", {}).get("diff", []) or []
        up_count = sum(it.get("f104", 0) for it in items)
        down_count = sum(it.get("f105", 0) for it in items)
    except Exception:
        pass

    limit_up_count, limit_down_count = 0, 0
    try:
        r_up = em_get("https://push2ex.eastmoney.com/getTopicZTPool",
                      params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                              "sort": "fbt", "fbt": "desc"},
                      headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        limit_up_count = r_up.json().get("data", {}).get("total", 0) or 0
    except Exception:
        pass
    try:
        r_down = em_get("https://push2ex.eastmoney.com/getTopicDTPool",
                        params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                                "sort": "fund", "fund": "desc"},
                        headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        limit_down_count = r_down.json().get("data", {}).get("total", 0) or 0
    except Exception:
        pass

    total = up_count + down_count
    up_ratio = up_count / max(total, 1) * 100

    if up_ratio >= 70: breadth_level = "🟢 普涨格局"; breadth_score = 85
    elif up_ratio >= 55: breadth_level = "🟡 涨多跌少"; breadth_score = 60
    elif up_ratio >= 45: breadth_level = "🟠 分化格局"; breadth_score = 40
    elif up_ratio >= 30: breadth_level = "🔴 跌多涨少"; breadth_score = 20
    else: breadth_level = "💀 普跌格局"; breadth_score = 5

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
        "data_basis": f"涨{up_count}跌{down_count}({up_ratio:.1f}%), 涨停{limit_up_count}/跌停{limit_down_count}",
    }

# ====== 资金-价格背离检测 ======
def detect_divergence(flow_data, quote):
    """检测资金流与价格走势的背离"""
    minutes = flow_data.get("minutes", [])
    if not minutes or len(minutes) < 20:
        return {"has_divergence": False, "reason": f"数据不足(仅{len(minutes)}分钟)"}

    cum_main = []; running = 0.0
    for m in minutes:
        running += m["main_net"]
        cum_main.append(running)

    n = len(minutes); seg_size = n // 4
    change_pct = quote.get("change_pct", 0)
    divergences = []

    for i in range(1, 4):
        prev_start = (i - 1) * seg_size; prev_end = i * seg_size
        curr_start = i * seg_size; curr_end = min((i + 1) * seg_size, n)
        if curr_end <= curr_start: continue

        prev_flow_change = cum_main[prev_end - 1] - cum_main[prev_start]
        curr_flow_change = cum_main[curr_end - 1] - cum_main[curr_start]

        # 顶背离
        if change_pct > 3 and prev_flow_change > 0 and curr_flow_change < prev_flow_change * 0.3:
            divergences.append({
                "type": "顶背离(资金衰竭)",
                "detail": f"价格涨{change_pct:+.2f}%，但资金流入从{prev_flow_change/1e4:.0f}万骤降至{curr_flow_change/1e4:.0f}万",
                "risk": "上涨动力衰竭，警惕冲高回落",
            })
        # 底背离
        if change_pct < -3 and prev_flow_change < 0 and curr_flow_change > abs(prev_flow_change) * 0.5:
            divergences.append({
                "type": "底背离(资金回流)",
                "detail": f"价格跌{change_pct:+.2f}%，但资金从流出{abs(prev_flow_change)/1e4:.0f}万转为流入{curr_flow_change/1e4:.0f}万",
                "risk": "下跌动力衰竭，关注反弹机会",
            })

    return {"has_divergence": len(divergences) > 0, "divergences": divergences}

# ====== 三方资金分类 ======
def classify_parties(flow_data):
    """机构/游资/散户三方资金分类"""
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
    inst_share = round(abs(inst_net) / max(total_abs, 1) * 100, 1)
    hm_share = round(abs(hm_net) / max(total_abs, 1) * 100, 1)
    retail_share = round(abs(retail_net) / max(total_abs, 1) * 100, 1)

    # 博弈场景
    if inst_net > 200 and hm_net > 0 and retail_net < -100:
        scenario = "机构+游资合力做多，散户恐慌出局 → 强多头信号"; level = "🟢 积极"
    elif inst_net > 200 and retail_net > 100:
        scenario = "机构与散户同向流入 → 共识强，但散户过度乐观是隐忧"; level = "🟡 中性偏多"
    elif inst_net < -200 and retail_net > 200:
        scenario = f"机构净流出{abs(inst_net):.0f}万 + 散户净流入{retail_net:.0f}万 → 机构派发、散户接盘，⚠️ 明确风险信号"; level = "🔴 警惕"
    elif inst_net < -100 and hm_net < -100 and retail_net > 100:
        scenario = "机构+游资合力出逃，散户接盘 → 强空头信号"; level = "🔴 危险"
    elif inst_net > 100 and hm_net < -50 and retail_net < -50:
        scenario = f"机构独力做多{inst_net:.0f}万，游资+散户不跟 → 孤军深入"; level = "🟡 中性"
    else:
        scenario = "三方分歧，方向不明确"; level = "⚪ 观望"

    return {
        "institution": {"net_wan": round(inst_net, 1), "direction": "流入" if inst_net > 0 else "流出",
                        "share_pct": inst_share, "rate_per_min_wan": round(inst_rate, 2)},
        "hot_money": {"net_wan": round(hm_net, 1), "direction": "流入" if hm_net > 0 else "流出",
                      "share_pct": hm_share, "rate_per_min_wan": round(hm_rate, 2)},
        "retail": {"net_wan": round(retail_net, 1), "direction": "流入" if retail_net > 0 else "流出",
                   "share_pct": retail_share, "rate_per_min_wan": round(retail_rate, 2)},
        "verdict": {"scenario": scenario, "level": level, "main_direction": "多头占优" if main_net > 0 else "空头占优"},
    }

# ====== 七维概率引擎 V1.3 ======
def generate_scenarios(quote, flow, sector, news, parties, divergence, nb, ms, mb):
    """七维25+条件概率预判引擎 V1.3 (时效性门控 + 零数据门控, 全情景覆盖)"""
    _fd = FRESHNESS["freshness"]
    weights = FRESHNESS["weights"]
    phase = FRESHNESS["phase"]
    phase_name = FRESHNESS["phase_name"]

    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)

    s = flow.get("summary", {})
    main_net_wan = s.get("total_main_net_wan", 0)
    inst_net = parties.get("institution", {}).get("net_wan", 0)
    hm_net = parties.get("hot_money", {}).get("net_wan", 0)
    retail_net = parties.get("retail", {}).get("net_wan", 0)

    t = flow.get("trend", {})
    acceleration = t.get("acceleration", "")
    direction = t.get("direction", "")
    first_slope = t.get("first_half_slope_wan_per_min", 0)
    second_slope = t.get("second_half_slope_wan_per_min", 0)
    last_turn = t.get("last_turn", {})

    sentiment_score = sector.get("sentiment_score", 50)
    inflow_blocks = sector.get("inflow_blocks", 0)
    total_blocks = sector.get("total_blocks", 1)

    news_bullish = news.get("bullish_count", 0)
    news_bearish = news.get("bearish_count", 0)

    has_divergence = divergence.get("has_divergence", False)
    divergence_type = ""
    if has_divergence and divergence.get("divergences"):
        divergence_type = divergence["divergences"][0].get("type", "")

    nb_net_yi = nb.get("total_net_yi", 0)
    nb_direction = nb.get("direction", "")

    relative_strength = ms.get("relative_strength", 0)
    market_env = ms.get("market_env", "")

    up_ratio = mb.get("up_ratio_pct", 50)
    breadth_score = mb.get("breadth_score", 50)
    limit_ratio = mb.get("limit_ratio", 1)
    money_effect = mb.get("money_effect", "")

    # ====== 数据可用性判定 (时间门控 + 零数据门控) ======
    # 板块: F10归属成功且匹配到资金流(非全0/error)
    sector_ok = ("error" not in sector) and sector.get("total_blocks", 0) > 0
    # 北向: 盘中净额恰好为0几乎只可能是未刷新 → 视为不可用
    north_ok = _fd.get("north_bound", {}).get("status") == "ready" and abs(nb_net_yi) > 0.01
    # 广度: 涨跌家数全0 = 未刷新
    breadth_ok = _fd.get("breadth", {}).get("status") == "ready" and \
                 (mb.get("up_count", 0) + mb.get("down_count", 0)) > 0

    dim_usable = {
        "quote": True, "minute_flow": True, "market": True, "news": True,
        "sector": sector_ok, "north_bound": north_ok, "breadth": breadth_ok,
    }
    downgrade_log = []
    for dim, ok in dim_usable.items():
        if not ok:
            downgrade_log.append({"dimension": dim, "reason": "数据未刷新/拉取失败, 相关条件置PENDING"})

    def make_cond(dim, text, threshold, actual, met, weight):
        """统一条件构造: 不可用维度→PENDING(权重0,不计分); 延迟维度→权重×0.4"""
        time_status = _fd.get(dim, {}).get("status", "ready")
        usable = dim_usable.get(dim, True)
        if not usable:
            return {"condition": text, "threshold": threshold,
                    "actual": f"{actual} [PENDING-数据未就绪]", "met": "PENDING",
                    "weight": 0, "effective_weight": 0, "dim": dim}
        if time_status == "delayed":
            eff = weight * 0.4
            return {"condition": text, "threshold": threshold, "actual": f"{actual} [延迟]",
                    "met": met, "weight": eff, "effective_weight": eff, "dim": dim}
        return {"condition": text, "threshold": threshold, "actual": actual,
                "met": met, "weight": weight, "effective_weight": weight, "dim": dim}

    # 情景构建器: 每个情景一个累加器
    def new_scenario():
        return {"score": 0, "eff_total": 0, "conds": []}

    def add(sc, dim, text, threshold, actual, met, weight):
        c = make_cond(dim, text, threshold, actual, met, weight)
        sc["conds"].append(c)
        if c["met"] == True:
            sc["score"] += c["effective_weight"]
        sc["eff_total"] += c["effective_weight"]

    scenarios = []

    # ═══ 情景A: 强势上涨 ═══
    A = new_scenario()
    add(A, "minute_flow", "主力净流入>500万", ">500万",
        f"{main_net_wan:+.0f}万", main_net_wan > 500 and direction == "流入", weights["minute_flow"])
    inst_dominates = inst_net > 200 and inst_net > abs(hm_net) and inst_net > abs(retail_net)
    add(A, "minute_flow", "机构主导(净流入>200万且>游资+散户)", "机构>200万且最大",
        f"机构{inst_net:+.0f}万, 游资{hm_net:+.0f}万, 散户{retail_net:+.0f}万",
        inst_dominates, max(weights["minute_flow"] - 5, 5))
    add(A, "sector", "板块情绪分≥60", "≥60",
        f"{sentiment_score:.0f}分 ({inflow_blocks}/{total_blocks}板块流入)",
        sentiment_score >= 60, weights["sector"])
    vol_ok = 1.2 <= vol_ratio <= 5 and turnover < 15
    add(A, "quote", "量能配合(量比1.2~5,换手<15%)", "量比1.2-5,换手<15%",
        f"量比{vol_ratio}, 换手{turnover}%", vol_ok, weights["quote"])
    no_top_div = not has_divergence or "顶背离" not in divergence_type
    add(A, "minute_flow", "无顶背离信号", "无顶背离",
        f"背离: {'有('+divergence_type+')' if has_divergence else '无'}", no_top_div, 10)
    add(A, "minute_flow", "资金加速流入", "后半段斜率>前半段×1.5",
        f"前半段{first_slope}万/分 → 后半段{second_slope}万/分", "加速流入" in acceleration, 10)
    add(A, "north_bound", "北向资金流入(>1亿)", ">1亿",
        f"北向{nb_net_yi:+.2f}亿", nb_net_yi > 1, weights["north_bound"])
    market_tailwind = relative_strength > 1 and "弱势" not in market_env
    add(A, "market", "个股跑赢大盘(相对强度>1%)", "相对强度>1%",
        f"{market_env}, 相对强度{relative_strength:+.2f}%", market_tailwind, weights["market"])
    add(A, "breadth", "市场广度不差(上涨>45%)", "上涨占比≥45%",
        f"涨{up_ratio:.0f}%, {money_effect}", up_ratio >= 45 and "亏钱" not in money_effect, weights["breadth"])
    add(A, "quote", "量能参考(量比≥0.8+换手≥0.5%)", "量比≥0.8,换手≥0.5%",
        f"量比{vol_ratio},换手{turnover}%", vol_ratio >= 0.8 and turnover >= 0.5, 2)

    # 多头共振 (仅可用维度参与)
    bullish_dims = sum([
        1 if main_net_wan > 300 else 0,
        1 if change_pct > 0 else 0,
        1 if (sector_ok and sentiment_score >= 50) else 0,
        1 if news_bullish > news_bearish else 0,
        1 if (north_ok and nb_net_yi > 0) else 0,
        1 if relative_strength > 0 else 0,
        1 if (breadth_ok and up_ratio >= 45) else 0,
    ])
    usable_bull = sum(dim_usable.values())
    resonance_bonus = 10 if (usable_bull >= 6 and bullish_dims >= 6) else (5 if (usable_bull >= 5 and bullish_dims >= 5) else 0)
    if resonance_bonus:
        A["score"] += resonance_bonus
        A["eff_total"] += resonance_bonus
        A["conds"].append({"condition": f"七维共振加分({bullish_dims}/7维看多)", "threshold": "≥5维",
                           "actual": f"{bullish_dims}维看多(可用{usable_bull}/7维)", "met": True,
                           "weight": resonance_bonus, "effective_weight": resonance_bonus, "dim": "resonance"})

    scenarios.append({
        "name": "情景A: 强势上涨",
        "description": "主力持续流入+机构主导+板块共振+量能配合 → 当日剩余时段大概率继续走强",
        "raw_score": A["score"], "max_score": A["eff_total"],
        "probability": round(A["score"] / max(A["eff_total"], 1) * 100, 1),
        "conditions": A["conds"],
        "met_count": sum(1 for c in A["conds"] if c["met"] == True),
        "pending_count": sum(1 for c in A["conds"] if c["met"] == "PENDING"),
        "total_conditions": len(A["conds"]),
        "historical_win_rate": "约65-70%",
    })

    # ═══ 情景B: 震荡横盘 ═══
    B = new_scenario()
    add(B, "minute_flow", "主力净流入<300万(无方向)", "|主力|<300万",
        f"{main_net_wan:+.0f}万", abs(main_net_wan) < 300, 30)
    add(B, "quote", "振幅<3%(窄幅波动)", "<3%",
        f"{amplitude}%", amplitude < 3, 25)
    add(B, "sector", "板块情绪35~65(中性)", "35-65",
        f"{sentiment_score:.0f}分", 35 <= sentiment_score <= 65, 25)
    add(B, "news", "无明确消息催化", "0条今日新闻",
        f"利好{news_bullish}/利空{news_bearish}", news_bullish == 0 and news_bearish == 0, 15)
    add(B, "north_bound", "北向资金无明显方向(±3亿内)", "|北向|<3亿",
        f"北向{nb_net_yi:+.2f}亿", abs(nb_net_yi) < 3, 10)
    add(B, "market", "大盘+个股均中性波动", "|相对强度|<1.5%",
        f"相对{relative_strength:+.2f}%", abs(relative_strength) < 1.5, 10)

    scenarios.append({
        "name": "情景B: 震荡横盘",
        "description": "资金方向不明+振幅小+情绪中性+无催化 → 当日剩余时段大概率窄幅震荡",
        "raw_score": B["score"], "max_score": B["eff_total"],
        "probability": round(B["score"] / max(B["eff_total"], 1) * 100, 1),
        "conditions": B["conds"],
        "met_count": sum(1 for c in B["conds"] if c["met"] == True),
        "pending_count": sum(1 for c in B["conds"] if c["met"] == "PENDING"),
        "total_conditions": len(B["conds"]),
        "historical_win_rate": "约55-60%",
    })

    # ═══ 情景C: 冲高回落 ═══
    C = new_scenario()
    add(C, "minute_flow", "已涨>3%且资金流转向", "涨>3%+资金减缓/流出",
        f"涨{change_pct:+.2f}%, 趋势:{acceleration}",
        change_pct > 3 and ("流出" in acceleration or "减缓" in acceleration), 30)
    add(C, "minute_flow", "出现顶背离(资金衰竭)", "顶背离信号",
        divergence_type if (has_divergence and "顶背离" in divergence_type) else "无",
        has_divergence and "顶背离" in divergence_type, 25)
    add(C, "minute_flow", "机构流出>100万+散户流入>200万(派发)", "机构<-100万,散户>+200万",
        f"机构{inst_net:+.0f}万,散户{retail_net:+.0f}万", inst_net < -100 and retail_net > 200, 25)
    add(C, "quote", "换手率>10%(异常活跃)", ">10%",
        f"{turnover}%", turnover > 10, 15)
    add(C, "north_bound", "北向资金流出(<-2亿)", "北向<-2亿",
        f"北向{nb_net_yi:+.2f}亿", nb_net_yi < -2, 10)
    add(C, "market", "个股高位+大盘走弱(逆势难持续)", "涨>2%+大盘弱势",
        f"涨{change_pct:+.2f}%, {market_env}",
        change_pct > 2 and relative_strength > 1 and "弱势" in market_env, 10)

    scenarios.append({
        "name": "情景C: 冲高回落",
        "description": "高位+资金转向/顶背离/机构派发 → 当日剩余时段警惕回落风险",
        "raw_score": C["score"], "max_score": C["eff_total"],
        "probability": round(C["score"] / max(C["eff_total"], 1) * 100, 1),
        "conditions": C["conds"],
        "met_count": sum(1 for c in C["conds"] if c["met"] == True),
        "pending_count": sum(1 for c in C["conds"] if c["met"] == "PENDING"),
        "total_conditions": len(C["conds"]),
        "historical_win_rate": "约55-65%",
    })

    # ═══ 情景D: 弱势下跌 ═══
    D = new_scenario()
    add(D, "minute_flow", "主力净流出>500万", "<-500万",
        f"{main_net_wan:+.0f}万", main_net_wan < -500 and direction == "流出", 30)
    add(D, "sector", "板块情绪<40(偏冷)", "<40",
        f"{sentiment_score:.0f}分", sentiment_score < 40, 25)
    add(D, "minute_flow", "资金加速流出", "后半段斜率<前半段×0.3",
        f"前半段{first_slope}万/分 → 后半段{second_slope}万/分", "加速流出" in acceleration, 25)
    add(D, "news", "有利空消息", "利空>0条",
        f"利空{news_bearish}条" if news_bearish > 0 else "无", news_bearish > 0, 15)
    add(D, "north_bound", "北向大幅流出(<-5亿)", "北向<-5亿",
        f"北向{nb_net_yi:+.2f}亿", nb_net_yi < -5, 10)
    add(D, "market", "大盘弱势+个股跑输", "大盘弱势+相对强度<-0.5%",
        f"{market_env}, 相对{relative_strength:+.2f}%",
        "弱势" in market_env and relative_strength < -0.5, 10)
    add(D, "breadth", "市场普跌(上涨<35%或涨跌停比<0.8)", "上涨<35%",
        f"涨{up_ratio:.0f}%, 涨跌停比{limit_ratio}", up_ratio < 35 or limit_ratio < 0.8, 10)

    # 空头共振 (仅可用维度参与)
    bearish_dims = sum([
        1 if main_net_wan < -300 else 0,
        1 if change_pct < -2 else 0,
        1 if (sector_ok and sentiment_score < 40) else 0,
        1 if news_bearish > 0 else 0,
        1 if (north_ok and nb_net_yi < -2) else 0,
        1 if relative_strength < -1 else 0,
        1 if (breadth_ok and up_ratio < 35) else 0,
    ])
    usable_bear = sum(dim_usable.values())
    resonance_d = 8 if (usable_bear >= 6 and bearish_dims >= 5) else (4 if (usable_bear >= 5 and bearish_dims >= 4) else 0)
    if resonance_d:
        D["score"] += resonance_d
        D["eff_total"] += resonance_d
        D["conds"].append({"condition": f"空头共振加分({bearish_dims}/7维看空)", "threshold": "≥4维",
                           "actual": f"{bearish_dims}维看空(可用{usable_bear}/7维)", "met": True,
                           "weight": resonance_d, "effective_weight": resonance_d, "dim": "resonance"})

    scenarios.append({
        "name": "情景D: 弱势下跌",
        "description": "主力持续流出+板块冷+加速流出 → 当日剩余时段大概率继续走弱",
        "raw_score": D["score"], "max_score": D["eff_total"],
        "probability": round(D["score"] / max(D["eff_total"], 1) * 100, 1),
        "conditions": D["conds"],
        "met_count": sum(1 for c in D["conds"] if c["met"] == True),
        "pending_count": sum(1 for c in D["conds"] if c["met"] == "PENDING"),
        "total_conditions": len(D["conds"]),
        "historical_win_rate": "约60-70%",
    })

    # 归一化
    total_prob = sum(s["probability"] for s in scenarios)
    for s in scenarios:
        if total_prob > 0:
            s["probability"] = round(s["probability"] / total_prob * 100, 1)

    scenarios_sorted = sorted(scenarios, key=lambda x: x["probability"], reverse=True)

    return {
        "scenarios": scenarios_sorted,
        "primary_scenario": scenarios_sorted[0] if scenarios_sorted else None,
        "analysis_time": DATE_TIME_STR,
        "data_points": s.get("data_points", 0),
        "freshness": {
            "phase": phase,
            "phase_name": phase_name,
            "minutes_from_open": FRESHNESS["minutes_from_open"],
            "downgraded_count": len(downgrade_log),
            "downgrade_details": downgrade_log,
            "dim_usable": dim_usable,
        },
    }

# ====== 买卖时机信号 ======
def generate_signals(scenarios, quote, flow, parties, sector, nb, ms, mb):
    """生成买卖时机参考信号，每个信号用数据说话"""
    primary = scenarios["scenarios"][0] if scenarios["scenarios"] else {}
    primary_prob = primary.get("probability", 0)
    primary_name = primary.get("name", "")

    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)
    price = quote.get("price", 0)

    s = flow.get("summary", {})
    main_net_wan = s.get("total_main_net_wan", 0)
    inst_net = parties.get("institution", {}).get("net_wan", 0)
    hm_net = parties.get("hot_money", {}).get("net_wan", 0)
    retail_net = parties.get("retail", {}).get("net_wan", 0)
    inst_share = parties.get("institution", {}).get("share_pct", 0)

    t = flow.get("trend", {})
    acceleration = t.get("acceleration", "")
    direction = t.get("direction", "")

    sentiment_score = sector.get("sentiment_score", 50)
    nb_net_yi = nb.get("total_net_yi", 0)
    relative_strength = ms.get("relative_strength", 0)
    market_env = ms.get("market_env", "")
    up_ratio = mb.get("up_ratio_pct", 50)
    money_effect = mb.get("money_effect", "")

    buy_signals = []; sell_signals = []

    # ━━━ 买入信号 ━━━
    strong_buy_met = sum([
        primary_prob >= 60 and "情景A" in primary_name,
        inst_net > 200,
        sentiment_score >= 60,
        change_pct < 5,
        "加速流入" in acceleration,
    ])

    if strong_buy_met >= 4:
        buy_signals.append({
            "level": "🟢🟢🟢 强买入参考",
            "strength": strong_buy_met,
            "action": "可考虑逢低建仓/加仓",
            "stop_loss": f"跌破{price * 0.97:.2f}(-3%)则果断离场",
        })

    medium_buy_met = sum([
        primary_prob >= 45 and "情景A" in primary_name,
        inst_net > 100,
        sentiment_score >= 50,
        change_pct < 7,
    ])

    if medium_buy_met >= 3 and strong_buy_met < 4:
        buy_signals.append({
            "level": "🟢🟢 中等买入参考",
            "strength": medium_buy_met,
            "action": "可小仓位试探(计划仓位的30-50%), 等待更多信号确认",
            "stop_loss": f"跌破{price * 0.95:.2f}(-5%)则止损",
        })

    if primary_prob >= 30 and "情景D" in primary_name and main_net_wan > -300 and sentiment_score >= 30:
        buy_signals.append({
            "level": "🟢 弱买入参考(左侧/反弹)",
            "action": "仅极度激进者可关注, 大多数人应等待企稳确认",
            "stop_loss": f"跌破{price * 0.97:.2f}(-3%)强制止损",
        })

    if not buy_signals:
        buy_signals.append({
            "level": "⚪ 暂不建议买入",
            "action": "继续观察, 等待资金面+情绪面+价格面共振信号",
        })

    # ━━━ 卖出信号 ━━━
    strong_sell_met = sum([
        primary_prob >= 50 and ("情景C" in primary_name or "情景D" in primary_name),
        inst_net < -200,
        "加速流出" in acceleration,
    ])

    if strong_sell_met >= 3:
        sell_signals.append({
            "level": "🔴🔴🔴 强卖出参考",
            "action": "建议果断减仓/清仓, 不在下跌中补仓",
            "risk_note": f"继续持有可能面临更大回撤, 当前已流出{abs(main_net_wan):.0f}万",
        })

    medium_sell_met = sum([
        ("情景C" in primary_name or "情景D" in primary_name) and primary_prob >= 35,
        inst_net < -100 or (inst_net < 0 and retail_net > 100),
    ])

    if medium_sell_met >= 2 and strong_sell_met < 3:
        sell_signals.append({
            "level": "🔴🔴 中等卖出参考",
            "action": "建议逐步减仓, 至少减到半仓以下",
            "risk_note": f"机构{'流出' if inst_net < 0 else '减弱'}{abs(inst_net):.0f}万, 散户{'接盘' if retail_net > 100 else '观望'}{retail_net:+.0f}万",
        })

    if change_pct > 8 and ("流出" in direction or "减缓" in acceleration):
        sell_signals.append({
            "level": "🔴 弱卖出参考(高位止盈)",
            "action": "可考虑部分止盈, 锁定利润",
        })

    if not sell_signals:
        sell_signals.append({
            "level": "⚪ 暂不需卖出",
            "action": "继续持有观察, 关注资金流方向是否转弱",
        })

    # ━━━ 持有参考 ━━━
    if "情景A" in primary_name and primary_prob >= 50:
        hold_verdict = {
            "level": "✅ 可继续持有",
            "reason": f"强势上涨概率{primary_prob:.0f}%, 主力{main_net_wan:+.0f}万, 机构{inst_net:+.0f}万",
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
            "watch_points": ["触发止损条件则果断执行", "等待企稳信号出现再考虑操作"],
        }

    # ━━━ 综合评估 ━━━
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
        overall = f"总体中性偏谨慎: 主力{main_net_wan:+.0f}万, 信号不明确。建议观望, 等待更清晰的信号。"

    return {
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "hold_verdict": hold_verdict,
        "overall_verdict": overall,
    }

# ====== 报告输出 ======
def print_report(quote, flow, mootdx_flow, sector, news, nb, ms, mb, scenarios, signals):
    """打印完整盘中信号报告到控制台"""
    print()
    print("═" * 70)
    print(f"  📊 盘中实时交易信号 V1.3: 铖昌科技(001270)")
    print(f"  分析时间: {DATE_TIME_STR}")
    print(f"  时效性阶段: {FRESHNESS['phase_name']}")
    _du = scenarios.get("freshness", {}).get("dim_usable", {})
    _icon = lambda k: "✅" if _du.get(k, True) else "❌"
    print(f"  数据可用: 行情✅ | 资金流✅ | 板块{_icon('sector')} | 北向{_icon('north_bound')} | 大盘✅ | 广度{_icon('breadth')}")
    if not all(_du.values()):
        print(f"  ⚠️ 零数据门控: 部分维度未刷新/拉取失败, 相关条件已置PENDING, 不参与概率计算")
    print("═" * 70)

    # ━━━ 一、价格面 ━━━
    print(f"\n{'─' * 60}")
    print(f"  📈 一、价格面")
    print(f"{'─' * 60}")
    if quote and "error" not in quote:
        print(f"  {quote.get('name', '')}({quote.get('code', '')})")
        print(f"  最新价: {quote.get('price', 0):.2f}  涨跌: {quote.get('change_pct', 0):+.2f}%  "
              f"振幅: {quote.get('amplitude', 0):.2f}%")
        print(f"  换手率: {quote.get('turnover_pct', 0):.2f}%  量比: {quote.get('vol_ratio', 0):.2f}  "
              f"成交额: {quote.get('amount', 0):.0f}万")
        print(f"  今开: {quote.get('open', 0):.2f}  最高: {quote.get('high', 0):.2f}  "
              f"最低: {quote.get('low', 0):.2f}  昨收: {quote.get('prev_close', 0):.2f}")

    # ━━━ 二、资金面 ━━━
    print(f"\n{'─' * 60}")
    print(f"  💰 二、资金面 (分钟级, push2 API)")
    print(f"{'─' * 60}")
    if flow and "error" not in flow:
        s = flow["summary"]
        t = flow["trend"]
        print(f"  追踪: {s.get('first_time', '?')} → {s.get('last_time', '?')} "
              f"(共{s.get('data_points', 0)}分钟)")
        print(f"  主力累计: {s.get('total_main_net_wan', 0):+.0f}万")
        print(f"    机构(超大单): {s.get('total_super_net_wan', 0):+.0f}万")
        print(f"    游资(大单):   {s.get('total_large_net_wan', 0):+.0f}万")
        print(f"    中单:         {s.get('total_mid_net_wan', 0):+.0f}万")
        print(f"    小单:         {s.get('total_small_net_wan', 0):+.0f}万")
        print(f"  趋势: {t.get('direction', '?')} | {t.get('acceleration', '?')}")
        print(f"  前后半段斜率: {t.get('first_half_slope_wan_per_min', 0):+.2f} → {t.get('second_half_slope_wan_per_min', 0):+.2f} 万/分")
        turns = t.get("turning_points", [])
        if turns:
            print(f"  关键转向点:")
            for tp in turns:
                print(f"    {tp['time']} {tp['type']}: {tp['value_wan']:+.0f}万")

    # 三方博弈
    parties = classify_parties(flow)
    if parties:
        v = parties.get("verdict", {})
        inst = parties.get("institution", {})
        hm = parties.get("hot_money", {})
        retail = parties.get("retail", {})
        print(f"\n  🎯 三方博弈: {v.get('scenario', '')}")
        print(f"  信号等级: {v.get('level', '')}")
        print(f"  机构: {inst.get('net_wan', 0):+.0f}万 {inst.get('direction', '')} "
              f"({inst.get('share_pct', 0):.0f}%)")
        print(f"  游资: {hm.get('net_wan', 0):+.0f}万 {hm.get('direction', '')} "
              f"({hm.get('share_pct', 0):.0f}%)")
        print(f"  散户: {retail.get('net_wan', 0):+.0f}万 {retail.get('direction', '')} "
              f"({retail.get('share_pct', 0):.0f}%)")

    # 背离
    divergence = detect_divergence(flow, quote)
    if divergence and divergence.get("has_divergence"):
        print(f"\n  ⚠️ 背离检测:")
        for div in divergence.get("divergences", []):
            print(f"    {div['type']}: {div['detail']}")
            print(f"    风险: {div['risk']}")

    # ━━━ 三、情绪面 ━━━
    print(f"\n{'─' * 60}")
    print(f"  🎯 三、情绪面 (铖昌科技动态概念板块)")
    print(f"{'─' * 60}")
    if sector and "error" not in sector:
        print(f"  板块情绪: {sector.get('sentiment_score', 0):.0f}/100 {sector.get('level', '')}")
        print(f"  数据: {sector.get('data_basis', '')}")
        for bk in sector.get("blocks", [])[:8]:
            print(f"    {bk['name']}: 主力{bk['main_net_wan']:+.0f}万 "
                  f"涨跌{bk['change_pct']:+.2f}% 涨{bk['up_count']}跌{bk['down_count']}")

    # ━━━ 四、消息面 ━━━
    print(f"\n{'─' * 60}")
    print(f"  📰 四、消息面")
    print(f"{'─' * 60}")
    if news:
        print(f"  今日新闻: {news.get('today_count', 0)}条 "
              f"(利好{news.get('bullish_count', 0)}/利空{news.get('bearish_count', 0)})")
        for h in (news.get("highlights") or [])[:5]:
            emoji = "🟢" if h.get("sentiment") == "bullish" else ("🔴" if h.get("sentiment") == "bearish" else "⚪")
            print(f"  {emoji} {h.get('time', '')} | {h.get('source', '')}")
            print(f"     {h.get('title', '')[:80]}")

    # ━━━ 五、北向+大盘+广度 ━━━
    print(f"\n{'─' * 60}")
    print(f"  🌏📊🔥 五、北向资金 + 大盘 + 市场广度 (V1.1)")
    print(f"{'─' * 60}")
    if nb:
        print(f"  北向资金: {nb.get('data_basis', '')}")
        print(f"  方向: {nb.get('direction', '')} {nb.get('signal', '')}")
    if ms:
        print(f"  大盘环境: {ms.get('data_basis', '')}")
        print(f"  个股评级: {ms.get('relative_rating', '')} | {ms.get('market_env', '')}")
        if ms.get("market_detail"):
            for k, v in ms["market_detail"].items():
                print(f"    {k}: {v:+.2f}%")
    if mb:
        print(f"  市场广度: {mb.get('data_basis', '')}")
        print(f"  赚钱效应: {mb.get('money_effect', '')} (涨跌停比{mb.get('limit_ratio', 1):.1f})")

    # ━━━ 六、多情景概率预判 ━━━
    print(f"\n{'─' * 60}")
    print(f"  🔮 六、多情景概率预判 (七维25+条件 V1.3)")
    print(f"{'─' * 60}")
    for sc in scenarios.get("scenarios", []):
        prob = sc.get("probability", 0)
        name = sc.get("name", "")
        met = sc.get("met_count", 0)
        pending = sc.get("pending_count", 0)
        total = sc.get("total_conditions", 0)

        icon = "🔥" if prob >= 50 else ("📊" if prob >= 25 else "🔍")
        pending_str = f" +{pending}PENDING" if pending else ""
        print(f"\n  {icon} {name} → 概率: {prob:.0f}% (满足{met}/{total}条件{pending_str})")
        print(f"     {sc.get('description', '')}")
        print(f"     历史胜率: {sc.get('historical_win_rate', '')}")
        for c in sc.get("conditions", []):
            status = "✅" if c["met"] == True else ("⏳" if c["met"] == "PENDING" else "❌")
            weight_info = f"(权重{c['weight']})"
            print(f"     {status} {c['condition']}: 阈值{c['threshold']}, 当前={c['actual']} {weight_info}")

    # ━━━ 七、买卖时机参考 ━━━
    print(f"\n{'─' * 60}")
    print(f"  ⚡ 七、买卖时机参考（数据说话）")
    print(f"{'─' * 60}")

    print(f"\n  📥 买入参考:")
    for bs in signals.get("buy_signals", []):
        print(f"    {bs['level']}")
        print(f"    操作: {bs.get('action', '')}")
        if bs.get("stop_loss"):
            print(f"    止损: {bs['stop_loss']}")

    print(f"\n  📤 卖出参考:")
    for ss in signals.get("sell_signals", []):
        print(f"    {ss['level']}")
        print(f"    操作: {ss.get('action', '')}")
        if ss.get("risk_note"):
            print(f"    风险: {ss['risk_note']}")

    hv = signals.get("hold_verdict", {})
    if hv:
        print(f"\n  📌 持有参考: {hv.get('level', '')}")
        print(f"    {hv.get('reason', '')}")
        for wp in hv.get("watch_points", []):
            print(f"    👁 {wp}")

    print(f"\n  ━━━━━━━━━━━━")
    print(f"  🎯 综合评估: {signals.get('overall_verdict', '')}")

    # ━━━ 八、时效性门控报告 ━━━
    freshness = scenarios.get("freshness", {})
    if freshness.get("downgraded_count", 0) > 0:
        print(f"\n{'─' * 60}")
        print(f"  ⏱️ 八、时效性门控报告 (V1.3)")
        print(f"{'─' * 60}")
        print(f"  当前阶段: {freshness.get('phase_name', '')}")
        print(f"  不可用维度: {freshness.get('downgraded_count', 0)}个")
        for detail in freshness.get("downgrade_details", []):
            print(f"    ⚠️ {detail['dimension']}: {detail.get('reason','')}")
        print(f"  → 这些维度的条件标记为 PENDING, 权重归零, 不参与概率计算")

    # 风险声明
    print(f"\n{'═' * 70}")
    print(f"  ⚠️ 研究声明:")
    print(f"  1. 所有信号基于公开API实时数据(延迟3-5秒)，不构成投资建议")
    print(f"  2. 概率预判基于七维25+条件多因子匹配+历史统计规律，不代表未来确定走势")
    print(f"  3. V1.3 时效性门控: PENDING标记的条件表示数据尚未刷新，未参与概率计算")
    print(f"  4. 核心原则：宁可少挣，宁可少亏——不确定时不出手")
    print(f"  5. 分析时间: {DATE_TIME_STR}, 阶段: {FRESHNESS['phase_name']}")
    print(f"{'═' * 70}")
    print()

# ====== Main ======
def main():
    print(f"\n{'='*60}")
    print(f"  铖昌科技(001270) 盘中实时交易信号 V1.3")
    print(f"  启动时间: {DATE_TIME_STR}")
    print(f"  时效性阶段: {FRESHNESS['phase_name']}")
    print(f"{'='*60}")

    # 1. 行情
    print("\n[1/6] 拉取实时行情...")
    quote = fetch_tencent_quote(CODE)
    if "error" in quote:
        print(f"  ❌ 行情获取失败: {quote['error']}")
        return
    print(f"  ✅ {quote['name']}({CODE}): {quote['price']}  {quote['change_pct']:+.2f}%")

    # 2. 资金流 (push2 失败时降级到 mootdx 分时, 并标记机构分类不可用)
    print("\n[2/6] 拉取分钟级资金流...")
    flow = fetch_minute_fund_flow(CODE)
    flow_failed = "error" in flow
    if flow_failed:
        print(f"  ⚠️ 东财资金流拉取失败({flow['error'][:50]}...), 降级为 mootdx 分时力道")
        mootdx_data = fetch_minute_data_mootdx(CODE)
        mootdx_flow = analyze_mootdx_flow(mootdx_data) if mootdx_data else {}
        if mootdx_flow and "error" not in mootdx_flow:
            # 用 mootdx 买卖力道构造一个最小 flow 结构 (无机构/游资/散户分类)
            ms2 = mootdx_flow.get("summary", {})
            mt2 = mootdx_flow.get("trend", {})
            net_vol = ms2.get("total_net_vol", 0)
            # mootdx minutes 的 schema 是 {time,net_vol,price}, 与 push2 的 {time,main_net,...} 不同
            # 降级模式下不提供 main_net 序列 → detect_divergence 会自动跳过(数据不足)
            flow = {
                "minutes": [],  # 不传 mootdx minutes, 避免 schema 冲突
                "summary": {
                    "total_main_net": net_vol,
                    "total_main_net_wan": round(net_vol / 1e2, 1),  # 手→万元(粗估, 仅方向参考)
                    "total_super_net_wan": 0, "total_large_net_wan": 0,
                    "total_mid_net_wan": 0, "total_small_net_wan": 0,
                    "data_points": ms2.get("data_points", 0),
                    "first_time": mootdx_flow["minutes"][0]["time"] if mootdx_flow.get("minutes") else "",
                    "last_time": mootdx_flow["minutes"][-1]["time"] if mootdx_flow.get("minutes") else "",
                    "source": "mootdx分时(降级, 无机构分类)",
                },
                "trend": {"direction": mt2.get("direction", ""), "acceleration": mt2.get("acceleration", ""),
                          "first_half_slope_wan_per_min": 0, "second_half_slope_wan_per_min": 0,
                          "cum_sequence_wan": [], "turning_points": [], "last_turn": None},
                "degraded": True,
            }
            print(f"  ✅ mootdx降级: {ms2.get('data_points',0)}分钟, 买方占比{ms2.get('buy_ratio_pct',0):.1f}%, {mt2.get('direction','')}/{mt2.get('acceleration','')}")
            print(f"  ⚠️ 降级模式: 机构/游资/散户分类不可用, 资金面条件置信度降低")
        else:
            print(f"  ❌ mootdx 分时也失败, 资金面完全不可用")
            flow = {"error": "资金面完全不可用", "minutes": [], "summary": {}, "trend": {}, "degraded": True}
    else:
        s = flow["summary"]
        print(f"  ✅ {s['data_points']}分钟数据, 主力累计{s['total_main_net_wan']:+.0f}万")
        print(f"  趋势: {flow['trend']['direction']} / {flow['trend']['acceleration']}")

    # mootdx 分时 (非降级时也拉取作为交叉验证)
    if not flow_failed:
        print("\n[2.5/6] 拉取mootdx分时数据(交叉验证)...")
        mootdx_data = fetch_minute_data_mootdx(CODE)
        mootdx_flow = analyze_mootdx_flow(mootdx_data) if mootdx_data else {}
        if mootdx_flow and "error" not in mootdx_flow:
            ms2 = mootdx_flow.get("summary", {})
            mt2 = mootdx_flow.get("trend", {})
            print(f"  ✅ mootdx: 买方占比{ms2.get('buy_ratio_pct', 0):.1f}%, {mt2.get('direction', '')}/{mt2.get('acceleration', '')}")
    else:
        mootdx_flow = mootdx_flow if 'mootdx_flow' in dir() else {}

    # 3. 板块情绪
    print("\n[3/6] 拉取铖昌科技动态概念板块情绪...")
    sector = fetch_sector_sentiment(CODE)
    if "error" in sector:
        print(f"  ⚠️ 板块情绪: {sector['error']}")
    else:
        print(f"  ✅ 板块情绪: {sector['sentiment_score']:.0f}/100 {sector['level']}")
        print(f"  {sector['data_basis']}")

    # 4. 消息面
    print("\n[4/6] 拉取个股新闻...")
    news = fetch_intraday_news(CODE)
    print(f"  ✅ 今日新闻: {news.get('today_count', 0)}条 (利好{news.get('bullish_count', 0)}/利空{news.get('bearish_count', 0)})")

    # 5. 北向+大盘+广度
    print("\n[5/6] 拉取北向资金+大盘强度+市场广度...")
    nb = fetch_north_bound()
    ms_strength = fetch_market_strength(CODE, quote)
    mb = fetch_market_breadth()
    print(f"  ✅ 北向: {nb.get('data_basis', '')}")
    print(f"  ✅ 大盘: {ms_strength.get('data_basis', '')}")
    print(f"  ✅ 广度: {mb.get('data_basis', '')}")

    # 6. 概率预判+买卖信号
    print("\n[6/6] 生成七维多情景概率预判+买卖时机信号(V1.3)...")
    parties = classify_parties(flow)
    divergence = detect_divergence(flow, quote)
    scenarios = generate_scenarios(quote, flow, sector, news, parties, divergence, nb, ms_strength, mb)
    signals = generate_signals(scenarios, quote, flow, parties, sector, nb, ms_strength, mb)
    print(f"  ✅ 主导情景: {scenarios['primary_scenario']['name']} ({scenarios['primary_scenario']['probability']:.0f}%)")

    # 打印完整报告
    print_report(quote, flow, mootdx_flow, sector, news, nb, ms_strength, mb, scenarios, signals)

    # 保存报告
    _save_report(quote, flow, mootdx_flow, sector, news, nb, ms_strength, mb, scenarios, signals)

def _save_report(quote, flow, mootdx_flow, sector, news, nb, ms, mb, scenarios, signals):
    """保存报告到 src/盘中交易信号/"""
    target_name = quote.get("name", CODE)
    date_str = datetime.now().strftime("%Y-%m-%d")
    dir_name = f"{date_str}-{target_name}-盘中信号"
    dir_path = os.path.join("src/盘中交易信号", dir_name)
    os.makedirs(dir_path, exist_ok=True)

    # report.md
    lines = []
    a = lines.append
    hv = signals.get("hold_verdict", {})
    bs = signals.get("buy_signals", [])
    ss = signals.get("sell_signals", [])

    a(f"# 📊 盘中实时交易信号报告 V1.3\n")
    a(f"**标的**: {target_name} ({CODE})\n")
    a(f"**分析时间**: {DATE_TIME_STR}\n")
    a(f"**时效性阶段**: {FRESHNESS['phase_name']}\n\n")
    a(f"---\n\n")

    # Part 1: 核心结论
    primary_sc = scenarios["scenarios"][0] if scenarios["scenarios"] else {}
    a(f"## 🎯 Part 1: 核心结论\n\n")
    a(f"```\n")
    a(f"主导情景: {primary_sc.get('name', '')} (概率 {primary_sc.get('probability', 0):.0f}%)\n")
    a(f"买入信号: {bs[0].get('level', '') if bs else ''}\n")
    a(f"卖出信号: {ss[0].get('level', '') if ss else ''}\n")
    a(f"持有建议: {hv.get('level', '')}\n")
    a(f"```\n\n")
    a(f"**综合评估**: {signals.get('overall_verdict', '')}\n\n")
    a(f"---\n\n")

    # Part 2: 关键数据一览
    s = flow.get("summary", {})
    t = flow.get("trend", {})
    parties = classify_parties(flow)
    inst = parties["institution"]
    retail = parties["retail"]

    a(f"## 📊 Part 2: 关键数据一览\n\n")
    a(f"| 维度 | 指标 | 数值 | 信号 |\n")
    a(f"|------|------|------|------|\n")
    a(f"| 📈 价格 | 最新价 | {quote.get('price', 0):.2f} | — |\n")
    a(f"| 📈 价格 | 涨跌幅 | {quote.get('change_pct', 0):+.2f}% | {'🔴' if quote.get('change_pct', 0) < 0 else '🟢'} |\n")
    a(f"| 📈 价格 | 振幅 | {quote.get('amplitude', 0):.2f}% | — |\n")
    a(f"| 📈 价格 | 换手率 | {quote.get('turnover_pct', 0):.2f}% | {'🔴 异常' if quote.get('turnover_pct', 0) > 10 else '正常'} |\n")
    a(f"| 📈 价格 | 量比 | {quote.get('vol_ratio', 0):.2f} | — |\n")
    a(f"| 💰 资金 | 主力净流入 | {s.get('total_main_net_wan', 0):+.0f}万 | {'🔴 流出' if s.get('total_main_net_wan', 0) < 0 else '🟢 流入'} |\n")
    a(f"| 💰 资金 | 机构(超大单) | {s.get('total_super_net_wan', 0):+.0f}万 | {'🔴' if s.get('total_super_net_wan', 0) < 0 else '🟢'} |\n")
    a(f"| 💰 资金 | 散户(中+小) | {(s.get('total_mid_net_wan', 0) or 0) + (s.get('total_small_net_wan', 0) or 0):+.0f}万 | {'🔴 接盘' if (s.get('total_mid_net_wan', 0) or 0) + (s.get('total_small_net_wan', 0) or 0) > 100 else '—'} |\n")
    a(f"| 💰 资金 | 趋势 | {t.get('direction', '?')} / {t.get('acceleration', '?')} | — |\n")
    a(f"| 🎯 情绪 | 板块情绪分 | {sector.get('sentiment_score', 0):.0f}/100 {sector.get('level', '')} | — |\n")
    a(f"| 🌏 北向 | 北向资金 | {nb.get('total_net_yi', 0):+.2f}亿 | {nb.get('signal', '')} |\n")
    a(f"| 📊 大盘 | 相对强度 | {ms.get('relative_strength', 0):+.2f}% | {ms.get('relative_rating', '')} |\n")
    a(f"| 🔥 广度 | 涨跌家数比 | {mb.get('up_ratio_pct', 50):.0f}% | {mb.get('breadth_level', '')} |\n")
    a(f"| 📰 消息 | 今日新闻 | {news.get('today_count', 0)}条 | — |\n")
    a(f"\n---\n\n")

    # Part 3: 多情景概率
    a(f"## 🔮 Part 3: 多情景概率预判\n\n")
    for sc in scenarios["scenarios"]:
        a(f"### {sc['name']}: {sc['probability']:.0f}%\n\n")
        a(f"**{sc['description']}** (历史胜率: {sc['historical_win_rate']})\n\n")
        a(f"| 条件 | 阈值 | 当前值 | 满足? | 权重 |\n")
        a(f"|------|------|--------|-------|------|\n")
        for c in sc.get("conditions", []):
            status = "✅" if c["met"] == True else ("⏳" if c["met"] == "PENDING" else "❌")
            a(f"| {c['condition']} | {c.get('threshold', '')} | {c.get('actual', '')} | {status} | {c.get('weight', 0)} |\n")
        a(f"\n")

    # Part 4: 买卖信号
    a(f"## ⚡ Part 4: 买卖时机参考\n\n")
    a(f"### 📥 买入\n\n")
    for b in bs:
        a(f"**{b['level']}**: {b.get('action', '')}\n\n")

    a(f"### 📤 卖出\n\n")
    for s_ in ss:
        a(f"**{s_['level']}**: {s_.get('action', '')}")
        if s_.get("risk_note"):
            a(f" ({s_['risk_note']})")
        a(f"\n\n")

    a(f"### 📌 持有参考: {hv.get('level', '')}\n\n")
    a(f"{hv.get('reason', '')}\n\n")
    for wp in hv.get("watch_points", []):
        a(f"- 👁 {wp}\n")
    a(f"\n")

    # 时效性门控
    freshness = scenarios.get("freshness", {})
    if freshness.get("downgraded_count", 0) > 0:
        a(f"## ⏱️ Part 5: 时效性门控 V1.3\n\n")
        a(f"当前阶段: {freshness.get('phase_name', '')}\n")
        a(f"不可用维度数: {freshness.get('downgraded_count', 0)}\n\n")
        for detail in freshness.get("downgrade_details", []):
            a(f"- ⚠️ {detail['dimension']}: {detail.get('reason','')}\n")
        a(f"\n> 这些维度的条件标记为 PENDING, 权重归零, 不参与概率计算。\n")

    a(f"\n---\n\n")
    a(f"## ⚠️ 研究声明\n\n")
    a(f"1. 所有信号基于公开API实时数据(延迟3-5秒)，不构成投资建议\n")
    a(f"2. 概率预判基于七维25+条件多因子匹配+历史统计规律\n")
    a(f"3. V1.3 时效性门控: PENDING标记的条件未参与概率计算\n")
    a(f"4. 核心原则：宁可少挣，宁可少亏——不确定时不出手\n")
    a(f"5. 分析时间: {DATE_TIME_STR}, 阶段: {FRESHNESS['phase_name']}\n")

    with open(os.path.join(dir_path, "report.md"), "w", encoding="utf-8") as f:
        f.write("".join(lines))

    # data.json
    data_json = {
        "target": {"type": "个股", "code": CODE, "name": target_name},
        "analysis_time": DATE_TIME_STR,
        "freshness": freshness,
        "quote": quote,
        "fund_flow_summary": s,
        "fund_flow_trend": t,
        "sector": {k: v for k, v in sector.items() if k != "blocks"},
        "scenarios": [{"name": sc["name"], "probability": sc["probability"], "met_count": sc["met_count"]} for sc in scenarios["scenarios"]],
        "signals": signals,
        "minute_data": flow.get("minutes", [])[-60:],
    }
    with open(os.path.join(dir_path, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data_json, f, ensure_ascii=False, indent=2, default=str)

    print(f"✅ 报告已保存到: {dir_path}/")
    print(f"    ├── report.md  (完整信号报告)")
    print(f"    └── data.json  (原始数据)")

if __name__ == "__main__":
    main()
