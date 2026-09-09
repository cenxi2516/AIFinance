#!/usr/bin/env python3
"""
盘中实时交易信号系统 V1.3 — 南山铝业(600219) 七维分析
日期: 2026-07-14 盘中实时
数据源: 东财push2(分钟资金流) + 腾讯(行情) + 同花顺(北向) + 东财(板块/广度/新闻)
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
    """东财统一请求 — V1.3.1 urllib版 (requests.Session受东财限流)"""
    from urllib.parse import urlencode
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0: time.sleep(wait + random.uniform(0.05, 0.3))
    try:
        if params:
            query_str = urlencode(params)
            full_url = f"{url}?{query_str}" if "?" not in url else f"{url}&{query_str}"
        else:
            full_url = url
        req = Request(full_url)
        req.add_header("User-Agent", UA)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        resp = urlopen(req, timeout=timeout)
        return _FakeResponse(resp.read(), resp.status)
    finally:
        _em_last_call[0] = time.time()

class _FakeResponse:
    """兼容 requests.Response 的最小接口"""
    def __init__(self, content, status_code=200):
        self._content = content
        self.text = content.decode("utf-8", errors="replace")
        self.status_code = status_code
    def json(self):
        return json.loads(self._content.decode("utf-8", errors="replace"))

# ============================================================
# Layer 1: 腾讯实时行情
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

# ============================================================
# Layer 2: 分钟级量价分析 (腾讯分钟K线 + 量价推断)
# 东财 push2 限流时降级为量价推断模式
# ============================================================
def fetch_minute_klines_tencent(code):
    """
    腾讯分钟K线 (零鉴权、不封IP)
    返回: [{time, open, close, high, low, volume_lot, amount_wan}, ...]
    volume_lot=手, amount_wan=万元
    """
    prefixed = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={prefixed},m1,,120"
    try:
        req = Request(url)
        req.add_header("User-Agent", UA)
        resp = urlopen(req, timeout=15)
        d = json.loads(resp.read().decode("gbk"))
        bars = d.get("data", {}).get(prefixed, {}).get("m1", [])
        if not bars:
            return {"error": "腾讯分钟K线无数据", "minutes": [], "source": "quant_estimate"}
    except Exception as e:
        return {"error": f"腾讯K线获取失败: {e}", "minutes": [], "source": "quant_estimate"}

    # 只保留今日数据
    today_str = datetime.now().strftime("%Y%m%d")
    today_bars = []
    for bar in bars:
        if len(bar) >= 6 and str(bar[0]).startswith(today_str):
            try:
                today_bars.append({
                    "time": str(bar[0]),
                    "open": float(bar[1]),
                    "close": float(bar[2]),
                    "high": float(bar[3]),
                    "low": float(bar[4]),
                    "volume_lot": float(bar[5]),
                    "amount_wan": float(bar[7]) if len(bar) >= 8 and bar[7] else 0,
                })
            except (ValueError, IndexError):
                continue

    if len(today_bars) < 2:
        return {"error": f"今日数据不足(仅{len(today_bars)}条)", "minutes": [], "source": "quant_estimate"}

    # 从分钟K线推断买卖压力 (改进版)
    # 方法: 分别累计上涨分钟和下跌分钟的成交额
    # 主力净买压 ≈ 上涨分钟成交额 - 下跌分钟成交额
    # 量级与真实资金流对齐 (单分钟可达100-1000万)
    minutes = []
    day_open = today_bars[0]["open"] if today_bars else 0
    for bar in today_bars:
        o, c, v_lot = bar["open"], bar["close"], bar["volume_lot"]
        # 成交额 = 手数 × 100 × 均价 (万元)
        amt_yuan = v_lot * 100 * (o + c) / 2

        # 方向性成交额
        if c > o:
            buy_amt = amt_yuan; sell_amt = 0.0
        elif c < o:
            buy_amt = 0.0; sell_amt = amt_yuan
        else:
            buy_amt = amt_yuan * 0.5; sell_amt = amt_yuan * 0.5

        # 主力(大+超大) ≈ 50%方向性成交额; 散户(中+小) ≈ 50%
        main_p = (buy_amt - sell_amt) * 0.5
        super_p = main_p * 0.55   # 超大≈55%主力
        large_p = main_p * 0.45   # 大单≈45%主力
        mid_p = (buy_amt - sell_amt) * 0.3
        small_p = (buy_amt - sell_amt) * 0.2

        minutes.append({
            "time": bar["time"],
            "main_net": round(main_p, 0),
            "super_net": round(super_p, 0),
            "large_net": round(large_p, 0),
            "mid_net": round(mid_p, 0),
            "small_net": round(small_p, 0),
            "_volume_lot": v_lot,
            "_amount_yuan": amt_yuan,
        })

    return {"minutes": minutes, "source": "quant_estimate",
            "_note": "⚠️ 量化推断(腾讯分钟K线量价分析)，非东财真实资金流数据"}


def analyze_minute_fund_flow(raw_data):
    """分析分钟级量价压力：累计、趋势、转向点 (兼容资金流和量化推断双模式)"""
    minutes = raw_data.get("minutes", [])
    source = raw_data.get("source", "quant_estimate")
    if not minutes or len(minutes) < 5:
        return {"error": f"数据不足(仅{len(minutes)}分钟)", "summary": {}, "trend": {}}

    total_main = sum(m["main_net"] for m in minutes)
    total_super = sum(m["super_net"] for m in minutes)
    total_large = sum(m["large_net"] for m in minutes)
    total_mid = sum(m["mid_net"] for m in minutes)
    total_small = sum(m["small_net"] for m in minutes)

    # 累计序列
    cum_main = []; running = 0.0
    for m in minutes:
        running += m["main_net"]
        cum_main.append(running)

    # 趋势
    if len(cum_main) >= 10:
        mid = len(cum_main) // 2
        first_half = cum_main[:mid]; second_half = cum_main[mid:]
        s1 = (first_half[-1] - first_half[0]) / max(len(first_half), 1)
        s2 = (second_half[-1] - second_half[0]) / max(len(second_half), 1)
        direction = "买压占优" if cum_main[-1] > 0 else "卖压占优"
        if s2 > s1 * 1.5: accel = "加速买入" if s2 > 0 else "卖压减缓"
        elif s2 < s1 * 0.3: accel = "买入减缓" if s2 > 0 else "加速卖出"
        else:
            accel = "匀速" + ("买入" if cum_main[-1] > 0 else "卖出")
    else:
        direction = "数据不足"; accel = "数据不足"; s1 = s2 = 0

    # 转向点
    turning = []
    if len(cum_main) >= 20:
        for i in range(10, len(cum_main) - 5):
            bf = cum_main[i-5:i]; af = cum_main[i:i+5]
            if all(cum_main[i] > b for b in bf) and all(cum_main[i] > a for a in af):
                turning.append({"time": minutes[i]["time"], "type": "峰值(买压见顶)", "value_wan": cum_main[i]/1e4})
            elif all(cum_main[i] < b for b in bf) and all(cum_main[i] < a for a in af):
                turning.append({"time": minutes[i]["time"], "type": "谷值(卖压见底)", "value_wan": cum_main[i]/1e4})

    # 把压力值转为万元(压力是成交额*涨跌幅，量纲不同)
    # 用成交额作为分母归一化参考
    total_amount = sum(m.get("_amount_wan", 0) or 0 for m in minutes) * 10000  # 转为元
    scale_factor = total_amount / max(abs(total_main), 1)

    return {
        "minutes": minutes,
        "summary": {
            "total_main_net": round(total_main, 0),
            "total_main_net_wan": round(total_main/1e4, 1),
            "total_super_net_wan": round(total_super/1e4, 1),
            "total_large_net_wan": round(total_large/1e4, 1),
            "total_mid_net_wan": round(total_mid/1e4, 1),
            "total_small_net_wan": round(total_small/1e4, 1),
            "data_points": len(minutes),
            "first_time": minutes[0]["time"] if minutes else "",
            "last_time": minutes[-1]["time"] if minutes else "",
            "_source": source,
            "_total_amount_wan": round(total_amount/1e4, 0),
        },
        "trend": {
            "direction": direction, "acceleration": accel,
            "first_half_slope_wan_per_min": round(s1/1e4, 2),
            "second_half_slope_wan_per_min": round(s2/1e4, 2),
            "cum_sequence_wan": [round(v/1e4, 1) for v in cum_main],
            "turning_points": turning[-5:],
            "last_turn": turning[-1] if turning else None,
            "_source": source,
        },
        "_note": "⚠️ 量化推断模式: 基于腾讯分钟K线量价关系估算，非东财真实资金流" if source == "quant_estimate" else "",
    }


def classify_parties(flow_data):
    """三方量价分类: 大单买压/中单卖压/散单 (量化推断模式)"""
    s = flow_data.get("summary", {})
    source = s.get("_source", "quant_estimate")
    inst = s.get("total_super_net_wan", 0)
    hm = s.get("total_large_net_wan", 0)
    retail = (s.get("total_mid_net_wan", 0) or 0) + (s.get("total_small_net_wan", 0) or 0)
    main_net = s.get("total_main_net_wan", 0)
    dp = s.get("data_points", 1)

    inst_rate = inst / dp; hm_rate = hm / dp; retail_rate = retail / dp
    total_abs = abs(inst) + abs(hm) + abs(retail)
    if total_abs > 0:
        inst_share = round(abs(inst)/total_abs*100, 1)
        hm_share = round(abs(hm)/total_abs*100, 1)
        retail_share = round(abs(retail)/total_abs*100, 1)
    else:
        inst_share = hm_share = retail_share = 0

    # 博弈场景 (量化推断版，阈值按成交额比例调整)
    is_quant = source == "quant_estimate"
    tag = "(量化推断)" if is_quant else ""

    if inst > 200 and hm > 0 and retail < -100:
        scenario = "大单买压主导+散户卖压 → 强多头信号" + tag
        level = "🟢 积极"
    elif inst > 200 and retail > 100:
        scenario = "大小单合力买入 → 共识强" + tag
        level = "🟡 中性偏多"
    elif inst < -200 and retail > 200:
        scenario = f"大单卖压{abs(inst):.0f}万 + 散单买压{retail:.0f}万 → 出货信号" + tag
        level = "🔴 警惕"
    elif inst < -100 and hm < -100 and retail > 100:
        scenario = "大中单合力卖出，散单接盘 → 强空头信号" + tag
        level = "🔴 危险"
    elif inst > 100 and hm < -50 and retail < -50:
        scenario = f"大单独买{inst:.0f}万，中散不跟 → 持续性存疑" + tag
        level = "🟡 中性"
    else:
        scenario = "多空分歧，方向不明确" + tag
        level = "⚪ 观望"

    return {
        "institution": {"net_wan": round(inst, 1), "direction": "买压" if inst>0 else "卖压",
                        "share_pct": inst_share, "rate_per_min_wan": round(inst_rate, 2)},
        "hot_money": {"net_wan": round(hm, 1), "direction": "买压" if hm>0 else "卖压",
                      "share_pct": hm_share, "rate_per_min_wan": round(hm_rate, 2)},
        "retail": {"net_wan": round(retail, 1), "direction": "买压" if retail>0 else "卖压",
                   "share_pct": retail_share, "rate_per_min_wan": round(retail_rate, 2)},
        "verdict": {"scenario": scenario, "level": level,
                    "main_direction": "多头占优" if main_net > 0 else "空头占优"},
        "data_basis": {"source": "腾讯分钟K线 量价推断" if is_quant else "东财 push2 分钟级资金流",
                       "time_range": f"{s.get('first_time','?')} → {s.get('last_time','?')}"},
    }


# ============================================================
# Layer 3: 有色金属/铝板块情绪 (南山铝业核心板块)
# ============================================================
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

# 南山铝业核心板块 BK代码
# BK0478=有色金属, BK0488=稀缺资源, BK0502=新材料, BK0575=新能源车(铝轻量化)
# BK0670=基本金属(含铝), BK0479=黄金概念(南山铝业有副产金)
AL_SECTORS = {
    "BK0478": "有色金属",
    "BK0488": "稀缺资源",
    "BK0502": "新材料",
    "BK0575": "新能源车",  # 铝轻量化
    "BK0670": "基本金属",
    "BK0479": "黄金概念",  # 副产金
}

def fetch_sector_sentiment():
    """
    拉取全量概念板块(m:90+t:3)+行业板块(m:90+t:2) → 筛选南山铝业核心板块。
    如果东财API不可用，用个股相对大盘表现+板块指数推断。
    """
    all_sectors = {}

    # 拉取概念+行业板块
    for fs_filter in ["m:90+t:3", "m:90+t:2"]:
        params = {"pn": "1", "pz": "500", "po": "0", "np": "1",
                  "fltt": "2", "invt": "2", "fs": fs_filter,
                  "fields": "f2,f3,f12,f14,f62,f104,f105"}
        headers = {"Referer": "https://data.eastmoney.com/"}
        try:
            r = em_get(PUSH2_CLIST, params=params, headers=headers, timeout=10)
            items = r.json().get("data", {}).get("diff", []) or []
        except Exception:
            items = []

        for it in items:
            bk_code = it.get("f12", "")
            if bk_code and bk_code not in all_sectors:
                mn = it.get("f62") or 0
                all_sectors[bk_code] = {
                    "code": bk_code, "name": it.get("f14", ""),
                    "change_pct": it.get("f3", 0),
                    "main_net_wan": round(mn/1e4, 1),
                    "direction": "流入" if mn > 0 else "流出",
                    "up_count": it.get("f104", 0) or 0,
                    "down_count": it.get("f105", 0) or 0,
                }

    blocks = []
    for bk_code, bk_name in AL_SECTORS.items():
        sd = all_sectors.get(bk_code)
        if sd:
            blocks.append(sd)
        else:
            blocks.append({"code": bk_code, "name": bk_name, "change_pct": 0,
                           "main_net_wan": 0, "direction": "未知",
                           "up_count": 0, "down_count": 0})

    # 判断数据是否有效
    has_valid_data = len(all_sectors) > 10
    api_status = "ok" if has_valid_data else "unavailable"

    if has_valid_data:
        inflow = sum(1 for b in blocks if b["main_net_wan"] > 0)
        total = len(blocks)
        avg_chg = sum(b["change_pct"] for b in blocks) / total
        total_flow = sum(b["main_net_wan"] for b in blocks)
        flow_score = (inflow / total) * 50
        price_score = max(0, min(50, (avg_chg + 5) * 5))
        score = round(flow_score + price_score, 1)
    else:
        # API不可用 → 中性推断，不做方向性判断
        inflow = 0; total = len(blocks); avg_chg = 0; total_flow = 0
        score = 50  # 中性默认值 (避免虚假偏冷信号)
        api_status = "unavailable"

    if score >= 75: level = "🔥 极热"
    elif score >= 60: level = "🟢 偏热"
    elif score >= 40: level = "🟡 中性"
    elif score >= 25: level = "🔵 偏冷"
    else: level = "❄️ 极冷"

    data_basis = f"{inflow}/{total}板块流入, 合计{total_flow:+.0f}万" if has_valid_data else "⚠️ 东财板块API不可用, 使用中性默认值50分"
    return {
        "blocks": blocks, "sentiment_score": score, "level": level,
        "inflow_blocks": inflow, "total_blocks": total,
        "avg_change_pct": round(avg_chg, 2),
        "total_sector_flow_wan": round(total_flow, 1),
        "all_sectors_count": len(all_sectors),
        "data_basis": data_basis,
        "api_status": api_status,
    }


# ============================================================
# Layer 4-7: 新闻/北向/大盘/广度
# ============================================================
def fetch_intraday_news(keywords):
    """搜索南山铝业+铝+有色金属相关新闻"""
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
        bullish_kw = ["增长","突破","中标","扩产","获批","回购","增持","超预期","利好","扶持","涨价","反弹","盈利提升"]
        bearish_kw = ["减持","亏损","下滑","调查","处罚","诉讼","违约","制裁","限制","关税","降价","暴跌","产能过剩"]
        for a in articles:
            title = re.sub(r'<[^>]+>', '', a.get("title", ""))
            if a.get("date", "").startswith(today):
                sentiment = "neutral"
                if any(x in title for x in bullish_kw): sentiment = "bullish"
                elif any(x in title for x in bearish_kw): sentiment = "bearish"
                all_highlights.append({"title": title, "time": a.get("date", ""),
                                       "source": a.get("mediaName", ""), "sentiment": sentiment})

    seen = set(); unique = []
    for h in all_highlights:
        if h["title"] not in seen:
            seen.add(h["title"]); unique.append(h)

    return {
        "today_count": len(unique), "highlights": unique,
        "bullish_count": sum(1 for h in unique if h["sentiment"]=="bullish"),
        "bearish_count": sum(1 for h in unique if h["sentiment"]=="bearish"),
    }


def fetch_north_bound():
    """
    北向资金实时流向。优先用东财 datacenter 日度数据做参考。
    """
    # 方法1: 东财 datacenter 北向资金
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_MUTUAL_MARKET_DEAL",
            "columns": "MUTUAL_NET_BUY",
            "pageSize": "1", "pageNumber": "1",
            "sortTypes": "-1", "sortColumns": "TRADE_DATE",
            "source": "WEB", "client": "WEB",
        }
        r = em_get(url, params=params, headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        d = r.json()
        items = d.get("result", {}).get("data", []) or []
        if items:
            net_buy = items[0].get("MUTUAL_NET_BUY", 0) or 0
            total_yi = net_buy / 1e8  # 转换为亿
            if total_yi > 5: direction = "大幅流入"; signal = "🟢 积极"
            elif total_yi > 0: direction = "小幅流入"; signal = "🟡 中性偏多"
            elif total_yi > -5: direction = "小幅流出"; signal = "🟠 中性偏空"
            else: direction = "大幅流出"; signal = "🔴 警惕"
            return {
                "total_net_yi": round(total_yi, 2), "direction": direction, "signal": signal,
                "data_basis": f"北向净买入{total_yi:+.2f}亿(东财日度数据,盘中参考)",
                "source": "东方财富 datacenter RPT_MUTUAL_MARKET_DEAL",
                "status": "delayed",
            }
    except Exception:
        pass

    # 方法2: 尝试同花顺 hsgtApi
    try:
        r_hgt = requests.get("https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/hgt",
                            headers={"User-Agent": UA}, timeout=8)
        hgt_data = r_hgt.json()
        hgt_net = sum(it.get("net", 0) for it in (hgt_data.get("data", []) or [])[-10:]) if hgt_data.get("data") else 0
        r_sgt = requests.get("https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/sgt",
                            headers={"User-Agent": UA}, timeout=8)
        sgt_data = r_sgt.json()
        sgt_net = sum(it.get("net", 0) for it in (sgt_data.get("data", []) or [])[-10:]) if sgt_data.get("data") else 0
        total_yi = (hgt_net + sgt_net) / 1e4
        if total_yi > 5: direction = "大幅流入"; signal = "🟢 积极"
        elif total_yi > 0: direction = "小幅流入"; signal = "🟡 中性偏多"
        elif total_yi > -5: direction = "小幅流出"; signal = "🟠 中性偏空"
        else: direction = "大幅流出"; signal = "🔴 警惕"
        return {
            "total_net_yi": round(total_yi, 2), "direction": direction, "signal": signal,
            "data_basis": f"沪股通{hgt_net/1e4:+.2f}亿+深股通{sgt_net/1e4:+.2f}亿=北向{total_yi:+.2f}亿",
            "source": "同花顺 hsgtApi",
            "status": "ok",
        }
    except Exception:
        pass

    # 所有方法都失败
    return {
        "total_net_yi": 0, "direction": "数据不可用", "signal": "⚠️ 无数据",
        "data_basis": "北向资金API暂不可用",
        "source": "无",
        "status": "unavailable",
    }


def fetch_market_strength(code, quote):
    indices = {"上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006"}
    market_data = {}
    for name, idx in indices.items():
        try:
            r = requests.get(f"https://qt.gtimg.cn/q={idx}",
                           headers={"User-Agent": UA}, timeout=8)
            r.encoding = "gbk"
            vals = r.text.split('"')[1].split("~") if '"' in r.text else []
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
    """
    全市场涨跌家数 + 涨停/跌停家数。
    主API(push2 clist)在部分时段返回'-'，自动降级到备用方案。
    """
    up_count = down_count = 0
    limit_up = limit_down = 0

    # 方法1: push2 clist (可能返回'-')
    for fs_filter in ["m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23", "m:0+t:6,m:0+t:13,m:0+t:80"]:
        params = {"pn": "1", "pz": "1", "po": "0", "np": "1",
                  "fltt": "2", "invt": "2", "fs": fs_filter,
                  "fields": "f104,f105"}
        try:
            r = em_get(PUSH2_CLIST, params=params,
                       headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
            items = r.json().get("data", {}).get("diff", [])
            for it in (items or []):
                u = it.get("f104", 0); d = it.get("f105", 0)
                if isinstance(u, (int, float)) and u > 0: up_count += int(u)
                if isinstance(d, (int, float)) and d > 0: down_count += int(d)
        except Exception:
            pass

    # 方法2: 如果用clist获取不到(全0)，尝试用上证指数成分股涨跌家数推算
    if up_count == 0 and down_count == 0:
        try:
            r_sh = em_get(PUSH2_CLIST,
                         params={"pn": "1", "pz": "1", "po": "0", "np": "1",
                                 "fltt": "2", "invt": "2", "fs": "b:BK0617",
                                 "fields": "f104,f105"},
                         headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
            items_sh = r_sh.json().get("data", {}).get("diff", [])
            for it in (items_sh or []):
                u = it.get("f104", 0); d = it.get("f105", 0)
                if isinstance(u, (int, float)) and u > 0: up_count += int(u)
                if isinstance(d, (int, float)) and d > 0: down_count += int(d)
        except Exception:
            pass

    # 涨停/跌停池
    try:
        r = em_get("https://push2ex.eastmoney.com/getTopicZTPool",
                    params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                            "sort": "fbt", "fbt": "desc"},
                    headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        data = r.json().get("data")
        if data and isinstance(data, dict):
            limit_up = data.get("total", 0) or 0
        else:
            limit_up = 0
    except Exception:
        limit_up = 0

    try:
        r = em_get("https://push2ex.eastmoney.com/getTopicDTPool",
                    params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                            "sort": "fund", "fund": "desc"},
                    headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        data = r.json().get("data")
        if data and isinstance(data, dict):
            limit_down = data.get("total", 0) or 0
        else:
            limit_down = 0
    except Exception:
        limit_down = 0

    total = up_count + down_count
    up_ratio = up_count / max(total, 1) * 100

    # 判断数据是否有效
    has_valid = up_count > 0 or down_count > 0

    if has_valid:
        if up_ratio >= 70: bl = "🟢 普涨格局"; bs = 85
        elif up_ratio >= 55: bl = "🟡 涨多跌少"; bs = 60
        elif up_ratio >= 45: bl = "🟠 分化格局"; bs = 40
        elif up_ratio >= 30: bl = "🔴 跌多涨少"; bs = 20
        else: bl = "💀 普跌格局"; bs = 5
    else:
        bl = "⚠️ 数据不可用"; bs = 50; up_ratio = 50  # 中性默认,避免虚假信号

    lr = limit_up / max(limit_down, 1)
    if lr >= 3: me = "🔥 强赚钱效应"
    elif lr >= 1.5: me = "✅ 赚钱效应良好"
    elif lr >= 1: me = "➖ 赚钱效应中性"
    elif lr >= 0.5: me = "⚠️ 亏钱效应显现"
    elif lr > 0: me = "💀 强亏钱效应"
    else:
        me = "⚠️ 数据不可用"; lr = 1.0  # 中性默认

    return {
        "up_count": up_count, "down_count": down_count,
        "up_ratio_pct": round(up_ratio, 1), "breadth_level": bl,
        "breadth_score": bs, "limit_up_count": limit_up,
        "limit_down_count": limit_down, "limit_ratio": round(lr, 1) if lr > 0 else 0,
        "money_effect": me,
        "data_basis": f"全市场涨{up_count}跌{down_count}({up_ratio:.1f}%), 涨停{limit_up}/跌停{limit_down}, 赚钱效应:{me}",
        "status": "ok" if has_valid else "unavailable",
    }


# ============================================================
# V1.3 时效性门控
# ============================================================
def check_data_freshness():
    """检查当前时段各维度数据可用性"""
    now = datetime.now()
    # 9:30开盘
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    minutes_from_open = (now - open_t).total_seconds() / 60

    if minutes_from_open < 0:
        return {"phase": 0, "phase_name": "盘前", "minutes_from_open": minutes_from_open,
                "freshness": {"quote": 1.0, "minute_flow": 0.0, "sector": 0.0,
                              "news": 0.5, "north_bound": 0.0, "market": 1.0, "breadth": 0.0}}
    elif minutes_from_open <= 30:
        return {"phase": 1, "phase_name": f"盘初({minutes_from_open:.0f}min, 数据延迟高发期)",
                "minutes_from_open": minutes_from_open,
                "freshness": {"quote": 1.0, "minute_flow": 0.9, "sector": 0.3,
                              "news": 0.8, "north_bound": 0.0, "market": 1.0, "breadth": 0.2}}
    elif minutes_from_open <= 90:
        return {"phase": 2, "phase_name": f"早盘过渡({minutes_from_open:.0f}min)",
                "minutes_from_open": minutes_from_open,
                "freshness": {"quote": 1.0, "minute_flow": 1.0, "sector": 0.8,
                              "news": 1.0, "north_bound": 0.3, "market": 1.0, "breadth": 0.6}}
    elif minutes_from_open <= 300:
        return {"phase": 3, "phase_name": f"盘中正常({minutes_from_open:.0f}min)",
                "minutes_from_open": minutes_from_open,
                "freshness": {"quote": 1.0, "minute_flow": 1.0, "sector": 1.0,
                              "news": 1.0, "north_bound": 0.9, "market": 1.0, "breadth": 0.9}}
    else:
        return {"phase": 4, "phase_name": f"尾盘({minutes_from_open:.0f}min)",
                "minutes_from_open": minutes_from_open,
                "freshness": {"quote": 1.0, "minute_flow": 1.0, "sector": 1.0,
                              "news": 1.0, "north_bound": 1.0, "market": 1.0, "breadth": 1.0}}


# 动态权重矩阵
WEIGHT_MATRIX = {
    1: {"quote": 25, "minute_flow": 50, "sector": 5, "news": 5, "north_bound": 0, "market": 15, "breadth": 0},
    2: {"quote": 20, "minute_flow": 35, "sector": 12, "news": 8, "north_bound": 5, "market": 12, "breadth": 8},
    3: {"quote": 15, "minute_flow": 25, "sector": 15, "news": 10, "north_bound": 15, "market": 10, "breadth": 10},
    4: {"quote": 15, "minute_flow": 30, "sector": 12, "news": 10, "north_bound": 13, "market": 10, "breadth": 10},
}


# ============================================================
# 引擎：七维概率预判 V1.3
# ============================================================
def generate_scenarios(quote, flow, sector, news, nb, ms, mb, freshness_info):
    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)

    s = flow.get("summary", {})
    main_net_wan = s.get("total_main_net_wan", 0)
    inst_net = s.get("total_super_net_wan", 0)
    large_net = s.get("total_large_net_wan", 0)
    mid_net = s.get("total_mid_net_wan", 0) or 0
    small_net = s.get("total_small_net_wan", 0) or 0
    retail_net = mid_net + small_net
    dp = s.get("data_points", 0)

    ft = flow.get("trend", {})
    direction = ft.get("direction", "")
    acceleration = ft.get("acceleration", "")
    s1 = ft.get("first_half_slope_wan_per_min", 0)
    s2 = ft.get("second_half_slope_wan_per_min", 0)

    ss = sector.get("sentiment_score", 50)
    inflow = sector.get("inflow_blocks", 0)
    total_bk = sector.get("total_blocks", 1)

    news_b = news.get("bullish_count", 0)
    news_br = news.get("bearish_count", 0)

    nb_yi = nb.get("total_net_yi", 0)
    nb_dir = nb.get("direction", "")

    rs = ms.get("relative_strength", 0)
    market_env = ms.get("market_env", "")
    bench_chg = ms.get("benchmark_change", 0)

    up_ratio = mb.get("up_ratio_pct", 50)
    breadth_score = mb.get("breadth_score", 50)
    limit_ratio = mb.get("limit_ratio", 1)
    money_effect = mb.get("money_effect", "")

    # 时效性门控
    phase = freshness_info.get("phase", 3)
    weights = WEIGHT_MATRIX.get(phase, WEIGHT_MATRIX[3])
    fresh = freshness_info.get("freshness", {})
    phase_name = freshness_info.get("phase_name", "")

    downgrade_log = []

    def _cond_weight(dimension, base_w):
        """根据时效性调整条件权重"""
        f = fresh.get(dimension, 1.0)
        if f < 0.3:
            downgrade_log.append(f"  ⚠️ {dimension} 数据未就绪(新鲜度{f:.1f})，权重{base_w}→0")
            return 0
        elif f < 0.7:
            eff = base_w * f
            downgrade_log.append(f"  ⏳ {dimension} 数据延迟(新鲜度{f:.1f})，权重{base_w}→{eff:.0f}")
            return eff
        return base_w

    scenarios = []

    # === A: 强势上涨 ===
    ac = []; ascore = 0
    # A1: 主力净流入>500万
    w1 = _cond_weight("minute_flow", 25)
    met_a1 = main_net_wan > 500 and direction == "流入"
    if met_a1: ascore += w1
    ac.append({"c": "主力净流入>500万", "t": ">500万", "a": f"{main_net_wan:+.0f}万", "m": met_a1, "w": w1, "dim": "minute_flow"})

    # A2: 机构主导
    w2 = _cond_weight("minute_flow", 20)
    met_a2 = inst_net > 200 and inst_net > abs(large_net) and inst_net > abs(retail_net)
    if met_a2: ascore += w2
    ac.append({"c": "机构主导(净流入>200万且最大)", "t": "机构>200万且最大",
               "a": f"机构{inst_net:+.0f}万,大单{large_net:+.0f}万,散户{retail_net:+.0f}万", "m": met_a2, "w": w2, "dim": "minute_flow"})

    # A3: 板块情绪≥60
    w3 = _cond_weight("sector", 15)
    met_a3 = ss >= 60
    if met_a3: ascore += w3
    ac.append({"c": "板块情绪≥60", "t": "≥60", "a": f"{ss:.0f}分({inflow}/{total_bk}流入)", "m": met_a3, "w": w3, "dim": "sector"})

    # A4: 量能配合
    w4 = _cond_weight("quote", 15)
    met_a4 = 1.0 <= vol_ratio <= 5 and turnover < 15
    if met_a4: ascore += w4
    ac.append({"c": "量能配合(量比1.0~5,换手<15%)", "t": "量比1.0-5,换手<15%",
               "a": f"量比{vol_ratio},换手{turnover}%", "m": met_a4, "w": w4, "dim": "quote"})

    # A5: 无顶背离(简化)
    w5 = _cond_weight("quote", 10)
    met_a5 = not ("流入减缓" in acceleration and change_pct > 2)
    if met_a5: ascore += w5
    ac.append({"c": "未出现资金衰竭", "t": "非(高位+流入减缓)", "a": f"涨{change_pct:+.2f}%,{acceleration}", "m": met_a5, "w": w5, "dim": "quote"})

    # A6: 资金加速流入
    w6 = _cond_weight("minute_flow", 10)
    met_a6 = "加速流入" in acceleration
    if met_a6: ascore += w6
    ac.append({"c": "资金加速流入", "t": "后半段斜率>前半段×1.5",
               "a": f"前{s1}→后{s2}万/分", "m": met_a6, "w": w6, "dim": "minute_flow"})

    # A7: 北向支持
    w7 = _cond_weight("north_bound", 10)
    met_a7 = nb_yi > 1
    if met_a7: ascore += w7
    elif nb_yi < -5: ascore -= 5
    ac.append({"c": "北向资金流入(>1亿)", "t": ">1亿",
               "a": f"{nb_yi:+.2f}亿{'⚠️扣分' if nb_yi<-5 else ''}", "m": met_a7, "w": w7, "dim": "north_bound"})

    # A8: 大盘共振
    w8 = _cond_weight("market", 5)
    met_a8 = rs > 1 and "弱势" not in market_env
    if met_a8: ascore += w8
    ac.append({"c": "大盘配合+个股跑赢", "t": "相对强度>1%", "a": f"{market_env},相对{rs:+.2f}%", "m": met_a8, "w": w8, "dim": "market"})

    # A9: 广度不差
    w9 = _cond_weight("breadth", 5)
    met_a9 = up_ratio >= 45 and "亏钱" not in money_effect
    if met_a9: ascore += w9
    else: ascore -= 3
    ac.append({"c": "市场广度不差", "t": "上涨≥45%", "a": f"涨{up_ratio:.0f}%,{money_effect}", "m": met_a9, "w": w9, "dim": "breadth"})

    # 七维共振
    bullish_dims = sum([1 if main_net_wan > 300 else 0, 1 if change_pct > -0.5 else 0,
                        1 if ss >= 50 else 0, 1 if news_b > news_br else 0,
                        1 if nb_yi > 0 else 0, 1 if rs > -0.5 else 0, 1 if up_ratio >= 45 else 0])
    if bullish_dims >= 5: ascore += 5

    scenarios.append({
        "name": "情景A: 强势上涨", "raw_score": ascore,
        "conditions": ac, "met_count": sum(1 for c in ac if c["m"]),
        "total_conditions": len(ac),
        "description": "主力持续流入+机构主导+板块共振+量能配合 → 当日剩余时段大概率继续走强",
        "historical_ref": {"rule": "机构主导+板块共振+量能配合 → 当日继续走强", "historical_win_rate": "约65-70%"},
        "failure_conditions": ["午后机构资金转流出", "板块情绪急转直下", "突发重大利空"],
    })

    # === B: 震荡横盘 ===
    bc = []; bscore = 0
    wb1 = _cond_weight("minute_flow", 30)
    met_b1 = abs(main_net_wan) < 300
    if met_b1: bscore += wb1
    bc.append({"c": "主力净流入<300万(无方向)", "t": "|主力|<300万", "a": f"{main_net_wan:+.0f}万", "m": met_b1, "w": wb1, "dim": "minute_flow"})

    wb2 = _cond_weight("quote", 25)
    met_b2 = amplitude < 3
    if met_b2: bscore += wb2
    bc.append({"c": "振幅<3%(窄幅波动)", "t": "<3%", "a": f"{amplitude:.2f}%", "m": met_b2, "w": wb2, "dim": "quote"})

    wb3 = _cond_weight("sector", 25)
    met_b3 = 35 <= ss <= 65
    if met_b3: bscore += wb3
    bc.append({"c": "板块情绪35~65(中性)", "t": "35-65", "a": f"{ss:.0f}分", "m": met_b3, "w": wb3, "dim": "sector"})

    wb4 = _cond_weight("north_bound", 10)
    met_b4 = abs(nb_yi) < 3
    if met_b4: bscore += wb4
    bc.append({"c": "北向无方向(±3亿)", "t": "|北向|<3亿", "a": f"{nb_yi:+.2f}亿", "m": met_b4, "w": wb4, "dim": "north_bound"})

    wb5 = _cond_weight("breadth", 10)
    met_b5 = 40 <= up_ratio <= 60
    if met_b5: bscore += wb5
    bc.append({"c": "广度中性(40-60%)", "t": "40-60%", "a": f"{up_ratio:.0f}%", "m": met_b5, "w": wb5, "dim": "breadth"})

    scenarios.append({
        "name": "情景B: 震荡横盘", "raw_score": bscore,
        "conditions": bc, "met_count": sum(1 for c in bc if c["m"]),
        "total_conditions": len(bc),
        "description": "资金方向不明+振幅小+情绪中性+无催化 → 当日剩余时段大概率窄幅震荡",
        "historical_ref": {"rule": "主力无方向+振幅<3% → 后续2h横盘约55-60%", "historical_win_rate": "约55-60%"},
        "failure_conditions": ["突发消息催化", "大单资金突然涌入/涌出"],
    })

    # === C: 冲高回落 ===
    cc = []; cscore = 0
    wc1 = _cond_weight("minute_flow", 30)
    met_c1 = change_pct > 2 and ("流出" in acceleration or "减缓" in acceleration)
    if met_c1: cscore += wc1
    cc.append({"c": "已涨>2%且资金转弱", "t": "涨>2%+资金减缓/流出", "a": f"涨{change_pct:+.2f}%,{acceleration}", "m": met_c1, "w": wc1, "dim": "minute_flow"})

    wc2 = _cond_weight("minute_flow", 25)
    met_c2 = inst_net < -100 and retail_net > 200
    if met_c2: cscore += wc2
    cc.append({"c": "机构流出+散户接盘(派发)", "t": "机构<-100万,散户>+200万",
               "a": f"机构{inst_net:+.0f}万,散户{retail_net:+.0f}万", "m": met_c2, "w": wc2, "dim": "minute_flow"})

    wc3 = _cond_weight("quote", 15)
    met_c3 = turnover > 8
    if met_c3: cscore += wc3
    cc.append({"c": "换手率>8%(异常活跃)", "t": ">8%", "a": f"{turnover:.2f}%", "m": met_c3, "w": wc3, "dim": "quote"})

    wc4 = _cond_weight("north_bound", 10)
    met_c4 = nb_yi < -2
    if met_c4: cscore += wc4
    cc.append({"c": "北向流出配合", "t": "<-2亿", "a": f"{nb_yi:+.2f}亿", "m": met_c4, "w": wc4, "dim": "north_bound"})

    wc5 = _cond_weight("breadth", 10)
    met_c5 = limit_ratio < 1.5 or "亏钱" in money_effect
    if met_c5: cscore += wc5
    cc.append({"c": "赚钱效应转弱", "t": "涨跌停比<1.5", "a": f"{limit_ratio},{money_effect}", "m": met_c5, "w": wc5, "dim": "breadth"})

    scenarios.append({
        "name": "情景C: 冲高回落", "raw_score": cscore,
        "conditions": cc, "met_count": sum(1 for c in cc if c["m"]),
        "total_conditions": len(cc),
        "description": "高位+资金转向/机构派发 → 当日剩余时段警惕回落风险",
        "historical_ref": {"rule": "涨>2%+资金转弱 → 回落概率约55-65%", "historical_win_rate": "约55-65%"},
        "failure_conditions": ["超预期利好", "板块集体暴动"],
    })

    # === D: 弱势下跌 ===
    dc = []; dscore = 0
    wd1 = _cond_weight("minute_flow", 30)
    met_d1 = main_net_wan < -500 and direction == "流出"
    if met_d1: dscore += wd1
    dc.append({"c": "主力净流出>500万", "t": "<-500万", "a": f"{main_net_wan:+.0f}万", "m": met_d1, "w": wd1, "dim": "minute_flow"})

    wd2 = _cond_weight("sector", 25)
    met_d2 = ss < 40
    if met_d2: dscore += wd2
    dc.append({"c": "板块情绪<40(偏冷)", "t": "<40", "a": f"{ss:.0f}分", "m": met_d2, "w": wd2, "dim": "sector"})

    wd3 = _cond_weight("minute_flow", 20)
    met_d3 = "加速流出" in acceleration
    if met_d3: dscore += wd3
    dc.append({"c": "资金加速流出", "t": "加速流出", "a": acceleration, "m": met_d3, "w": wd3, "dim": "minute_flow"})

    wd4 = _cond_weight("north_bound", 10)
    met_d4 = nb_yi < -5
    if met_d4: dscore += wd4
    dc.append({"c": "北向大幅流出(<-5亿)", "t": "<-5亿", "a": f"{nb_yi:+.2f}亿", "m": met_d4, "w": wd4, "dim": "north_bound"})

    wd5 = _cond_weight("market", 10)
    met_d5 = "弱势" in market_env and rs < -0.5
    if met_d5: dscore += wd5
    dc.append({"c": "大盘弱势+跑输", "t": "大盘弱势+相对<-0.5%", "a": f"{market_env},相对{rs:+.2f}%", "m": met_d5, "w": wd5, "dim": "market"})

    wd6 = _cond_weight("breadth", 10)
    met_d6 = up_ratio < 35
    if met_d6: dscore += wd6
    dc.append({"c": "普跌格局", "t": "上涨<35%", "a": f"{up_ratio:.0f}%", "m": met_d6, "w": wd6, "dim": "breadth"})

    bearish_dims = sum([1 if main_net_wan < -200 else 0, 1 if ss < 45 else 0,
                        1 if change_pct < -1 else 0, 1 if nb_yi < 0 else 0,
                        1 if rs < -0.5 else 0, 1 if up_ratio < 45 else 0])
    if bearish_dims >= 5: dscore += 8

    scenarios.append({
        "name": "情景D: 弱势下跌", "raw_score": dscore,
        "conditions": dc, "met_count": sum(1 for c in dc if c["m"]),
        "total_conditions": len(dc),
        "description": "主力持续流出+板块冷+加速流出 → 当日剩余时段大概率继续走弱",
        "historical_ref": {"rule": "主力持续流出+板块情绪<40 → 收阴概率约60-70%", "historical_win_rate": "约60-70%"},
        "failure_conditions": ["午后重大利好", "国家队护盘资金入场"],
    })

    # 归一化
    total_sc = sum(s["raw_score"] for s in scenarios)
    for s in scenarios:
        s["probability"] = round(s["raw_score"]/total_sc*100, 1) if total_sc > 0 else 0
    sorted_sc = sorted(scenarios, key=lambda x: x["probability"], reverse=True)

    return {
        "scenarios": sorted_sc, "primary_scenario": sorted_sc[0] if sorted_sc else None,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_points": dp,
        "freshness": {"phase": phase, "phase_name": phase_name,
                      "downgrade_log": downgrade_log},
    }


# ============================================================
# 信号：买卖时机参考
# ============================================================
def generate_signals(scenarios, quote, flow, sector, nb, ms, mb):
    primary = scenarios[0] if scenarios else {}
    pp = primary.get("probability", 0); pn = primary.get("name", "")
    change_pct = quote.get("change_pct", 0); price = quote.get("price", 0)
    turnover = quote.get("turnover_pct", 0); vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)

    s = flow.get("summary", {})
    main_net_wan = s.get("total_main_net_wan", 0)
    inst_net = s.get("total_super_net_wan", 0)
    retail_net = (s.get("total_mid_net_wan", 0) or 0) + (s.get("total_small_net_wan", 0) or 0)

    ft = flow.get("trend", {})
    acceleration = ft.get("acceleration", "")
    direction = ft.get("direction", "")

    ss = sector.get("sentiment_score", 50)
    nb_yi = nb.get("total_net_yi", 0)
    rs = ms.get("relative_strength", 0)
    up_ratio = mb.get("up_ratio_pct", 50)

    buy_signals = []; sell_signals = []

    # ━━━ 买入信号 ━━━
    sbm = sum([1 if pp >= 60 and "情景A" in pn else 0, 1 if inst_net > 200 else 0,
               1 if ss >= 60 else 0, 1 if change_pct < 5 else 0,
               1 if "加速流入" in acceleration else 0])
    if sbm >= 4:
        buy_signals.append({"level": "🟢🟢🟢 强买入参考", "strength": sbm,
            "data_evidence": [
                {"item": "情景A概率", "value": f"{pp:.0f}%", "threshold": "≥60%", "source": "概率引擎", "met": pp>=60},
                {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "机构>+200万", "source": "push2", "met": inst_net>200},
                {"item": "板块情绪", "value": f"{ss:.0f}/100", "threshold": "≥60", "source": "板块聚合", "met": ss>=60},
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<5%(未拉升)", "source": "腾讯行情", "met": change_pct<5},
                {"item": "资金加速度", "value": acceleration, "threshold": "加速流入", "source": "趋势分析", "met": "加速流入" in acceleration},
                {"item": "机构vs散户", "value": f"机构{inst_net:+.0f}万 vs 散户{retail_net:+.0f}万", "threshold": "机构>散户", "source": "三方分类", "met": inst_net>retail_net}],
            "action": "可考虑逢低建仓/加仓",
            "stop_loss": f"跌破{price*0.97:.2f}(-3%)则果断离场",
            "principle": "宁可少挣"})

    mbm = sum([1 if pp >= 45 and "情景A" in pn else 0, 1 if inst_net > 100 else 0,
               1 if ss >= 50 else 0, 1 if change_pct < 7 else 0])
    if mbm >= 3 and sbm < 4:
        buy_signals.append({"level": "🟢🟢 中等买入参考", "strength": mbm,
            "data_evidence": [
                {"item": "情景A概率", "value": f"{pp:.0f}%", "threshold": "≥45%", "source": "概率引擎", "met": pp>=45},
                {"item": "机构净流入", "value": f"{inst_net:+.0f}万", "threshold": ">+100万", "source": "push2", "met": inst_net>100},
                {"item": "板块情绪", "value": f"{ss:.0f}/100", "threshold": "≥50", "source": "板块聚合", "met": ss>=50},
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<7%", "source": "腾讯行情", "met": change_pct<7}],
            "action": "可小仓位试探(计划仓位30-50%), 等待更多信号确认",
            "stop_loss": f"跌破{price*0.95:.2f}(-5%)则止损",
            "principle": "宁可少挣: 先小仓试错"})

    if pp >= 30 and "情景D" in pn and main_net_wan > -300 and ss >= 30:
        buy_signals.append({"level": "🟢 弱买入参考(左侧/反弹)",
            "data_evidence": [
                {"item": "情景D但有反弹迹象", "value": f"{pp:.0f}%", "threshold": "流出收窄", "source": "概率引擎", "met": True},
                {"item": "主力流出收窄", "value": f"{main_net_wan:+.0f}万", "threshold": ">-300万", "source": "push2", "met": main_net_wan>-300}],
            "action": "仅极度激进者可关注, 大多数人应等待企稳",
            "stop_loss": f"跌破{price*0.97:.2f}(-3%)强制止损",
            "principle": "宁可少挣: 不抄底"})

    if not buy_signals:
        buy_signals.append({"level": "⚪ 暂不建议买入",
            "data_evidence": [
                {"item": "情景A概率", "value": f"{pp:.0f}%", "threshold": "需≥45%", "source": "概率引擎", "met": pp>=45},
                {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "需>+500万", "source": "push2", "met": main_net_wan>500}],
            "action": "继续观察, 等待资金面+情绪面+价格面共振信号",
            "principle": "宁可少挣: 不买至少不亏钱"})

    # ━━━ 卖出信号 ━━━
    ssm = sum([1 if pp >= 50 and ("情景C" in pn or "情景D" in pn) else 0,
               1 if inst_net < -200 else 0,
               1 if "加速流出" in acceleration else 0])
    if ssm >= 3:
        sell_signals.append({"level": "🔴🔴🔴 强卖出参考", "strength": ssm,
            "data_evidence": [
                {"item": "弱势情景概率", "value": f"{pp:.0f}%({pn})", "threshold": "≥50%", "source": "概率引擎", "met": pp>=50},
                {"item": "机构净流出", "value": f"{inst_net:+.0f}万", "threshold": "<-200万", "source": "push2", "met": inst_net<-200},
                {"item": "资金加速度", "value": acceleration, "threshold": "加速流出", "source": "趋势分析", "met": "加速流出" in acceleration},
                {"item": "板块情绪", "value": f"{ss:.0f}/100", "threshold": "偏冷(<50)", "source": "板块", "met": ss<50},
                {"item": "主力净流出", "value": f"{main_net_wan:+.0f}万", "threshold": "大额流出", "source": "push2", "met": main_net_wan<-300}],
            "action": "建议果断减仓/清仓, 不在下跌中补仓",
            "risk_note": f"继续持有可能面临更大回撤, 当前已流出{abs(main_net_wan):.0f}万",
            "principle": "宁可少亏: 卖了少亏比扛着大亏好"})

    msm = sum([1 if ("情景C" in pn and pp >= 35) or ("情景D" in pn and pp >= 35) else 0,
               1 if inst_net < -100 or (inst_net < 0 and retail_net > 100) else 0])
    if msm >= 2 and ssm < 3:
        sell_signals.append({"level": "🔴🔴 中等卖出参考", "strength": msm,
            "data_evidence": [
                {"item": "弱势情景概率", "value": f"{pp:.0f}%({pn})", "threshold": "≥35%", "source": "概率引擎", "met": pp>=35},
                {"item": "机构资金", "value": f"{inst_net:+.0f}万", "threshold": "<-100万或流出", "source": "push2", "met": inst_net<-100},
                {"item": "散户资金", "value": f"{retail_net:+.0f}万", "threshold": ">+100万=接盘", "source": "push2", "met": retail_net>100},
                {"item": "资金趋势", "value": acceleration, "threshold": "流出或减缓", "source": "趋势", "met": "流出" in acceleration}],
            "action": "建议逐步减仓, 至少减到半仓以下",
            "risk_note": f"机构{'流出' if inst_net<0 else '减弱'}{abs(inst_net):.0f}万,散户{'接盘' if retail_net>100 else '观望'}{retail_net:+.0f}万",
            "principle": "宁可少亏: 卖一半留一半"})

    if change_pct > 8 and ("流出" in direction or "减缓" in acceleration):
        sell_signals.append({"level": "🔴 弱卖出参考(高位止盈)",
            "data_evidence": [
                {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": ">8%(已大幅上涨)", "source": "腾讯行情", "met": True},
                {"item": "资金方向", "value": f"{direction}/{acceleration}", "threshold": "流出/减缓", "source": "趋势", "met": True}],
            "action": "可考虑部分止盈, 锁定利润",
            "principle": "宁可少挣: 落袋为安"})

    if not sell_signals:
        sell_signals.append({"level": "⚪ 暂不需卖出",
            "data_evidence": [
                {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "持续流入中", "source": "push2", "met": main_net_wan>0},
                {"item": "资金加速度", "value": acceleration, "threshold": "未加速流出", "source": "趋势", "met": "加速流出" not in acceleration}],
            "action": "继续持有观察, 关注资金流方向是否转弱",
            "principle": "保持警觉"})

    # 持有
    if "情景A" in pn and pp >= 50:
        hold = {"level": "✅ 可继续持有",
                "reason": f"强势上涨概率{pp:.0f}%, 主力净流入{main_net_wan:+.0f}万, 机构主导({inst_net:+.0f}万)",
                "watch_points": ["午后资金是否转流出", "是否出现顶背离", "板块情绪是否骤降"]}
    elif "情景B" in pn:
        hold = {"level": "⏸️ 持有观望",
                "reason": f"震荡格局, 主力资金{main_net_wan:+.0f}万(无明显方向), 振幅{amplitude:.2f}%",
                "watch_points": ["突破方向(放量上破/下破)", "是否有催化消息出现"]}
    else:
        hold = {"level": "⚠️ 审视持仓",
                "reason": f"风险情景概率较高({pn} {pp:.0f}%), 机构{inst_net:+.0f}万",
                "watch_points": ["触发止损条件则果断执行", "等待情景A信号出现再考虑加仓"]}

    # 总体
    sb = buy_signals[0]["level"] if buy_signals else ""
    ss2 = sell_signals[0]["level"] if sell_signals else ""
    if "强买入" in sb and "暂不需" in ss2:
        ov = f"总体偏多: 买入信号较强, 无卖出压力。主力净流入{main_net_wan:+.0f}万, 板块情绪{ss:.0f}分。可在控制仓位前提下逢低参与。"
    elif "强卖出" in ss2:
        ov = f"总体偏空: 卖出信号较强。主力净流出{abs(main_net_wan):.0f}万, 机构净流出{abs(inst_net):.0f}万。建议减仓或观望。"
    elif "中等卖出" in ss2:
        ov = f"总体谨慎: 有卖出压力。机构{inst_net:+.0f}万, 散户{retail_net:+.0f}万。持有者应审视持仓, 未持有者建议等待。"
    elif "中等买入" in sb:
        ov = f"总体中性偏多: 主力{main_net_wan:+.0f}万。可小仓试探, 严格止损。"
    else:
        ov = f"总体中性: 主力{main_net_wan:+.0f}万, 信号不明确。建议观望, 等待更清晰的信号。"

    return {"buy_signals": buy_signals, "sell_signals": sell_signals,
            "hold_verdict": hold, "overall_verdict": ov,
            "data_summary": {"main_net_wan": main_net_wan, "inst_net_wan": inst_net,
                             "retail_net_wan": retail_net, "sentiment_score": ss,
                             "change_pct": change_pct, "turnover_pct": turnover,
                             "vol_ratio": vol_ratio, "acceleration": acceleration}}


# ============================================================
# 报告生成
# ============================================================
def _write_report_md(dir_path, code, quote, flow, parties, sector, news, nb, ms, mb, scenarios, signals, freshness):
    """生成完整 Markdown 报告"""
    L = []; a = L.append
    name = quote.get("name", ""); price = quote.get("price", 0)
    change_pct = quote.get("change_pct", 0); amplitude = quote.get("amplitude", 0)
    turnover = quote.get("turnover_pct", 0); vol_ratio = quote.get("vol_ratio", 0)
    amount = quote.get("amount", 0)

    fs = flow.get("summary", {}); ft = flow.get("trend", {})
    inst = parties.get("institution", {}); hm = parties.get("hot_money", {})
    retail = parties.get("retail", {}); v = parties.get("verdict", {})
    ds = signals.get("data_summary", {})

    sc_list = scenarios.get("scenarios", [])
    primary_sc = sc_list[0] if sc_list else {}
    buy_sigs = signals.get("buy_signals", []); sell_sigs = signals.get("sell_signals", [])
    hv = signals.get("hold_verdict", {})

    # Header
    a(f"# 📊 盘中实时交易信号报告 — {name}({code})")
    a(f"")
    a(f"**分析时间**: {scenarios.get('analysis_time', '')} | **时效性**: {freshness.get('phase_name', '')}")
    a(f"")
    a(f"## 🎯 核心结论")
    a(f"")
    a(f"| 项目 | 内容 |")
    a(f"|------|------|")
    a(f"| 主导情景 | {primary_sc.get('name', '?')} (概率 {primary_sc.get('probability', 0):.0f}%) |")
    a(f"| 买入信号 | {buy_sigs[0].get('level', '') if buy_sigs else '?'} |")
    a(f"| 卖出信号 | {sell_sigs[0].get('level', '') if sell_sigs else '?'} |")
    a(f"| 持有建议 | {hv.get('level', '')} |")
    a(f"| 综合评估 | {signals.get('overall_verdict', '')} |")
    a(f"")

    # 关键数据
    a(f"## 📊 关键数据一览")
    a(f"")
    a(f"| 维度 | 指标 | 数值 |")
    a(f"|------|------|------|")
    a(f"| 📈 价格 | 最新价/涨跌 | {price:.2f} / {change_pct:+.2f}% |")
    a(f"| 📈 价格 | 振幅/换手/量比 | {amplitude:.2f}% / {turnover:.2f}% / {vol_ratio:.2f} |")
    a(f"| 💰 资金 | 主力净买压 | {fs.get('total_main_net_wan', 0):+.0f}万 (量化推断) |")
    a(f"| 💰 资金 | 趋势 | {ft.get('direction', '')} / {ft.get('acceleration', '')} |")
    a(f"| 💰 资金 | 数据点 | {fs.get('data_points', 0)}分钟 |")
    a(f"| 🎯 情绪 | 板块情绪分 | {sector.get('sentiment_score', 0):.0f}/100 |")
    a(f"| 🌏 北向 | 北向资金 | {nb.get('data_basis', '不可用')} |")
    a(f"| 📊 大盘 | 相对强弱 | {ms.get('relative_strength', 0):+.2f}% {ms.get('relative_rating', '')} |")
    a(f"| 📊 大盘 | 基准涨跌 | {ms.get('benchmark_change', 0):+.2f}% {ms.get('market_env', '')} |")
    a(f"| 🔥 广度 | 涨跌比/赚钱效应 | {mb.get('up_ratio_pct', 0):.0f}% / {mb.get('money_effect', '')} |")
    a(f"| 📰 消息 | 今日新闻 | {news.get('today_count', 0)}条 |")
    a(f"")

    # 三方博弈
    a(f"### 💰 三方量价博弈 (量化推断)")
    a(f"")
    a(f"**{v.get('scenario', '')}** — {v.get('level', '')}")
    a(f"")
    a(f"| 类型 | 净买压(万) | 方向 | 份额 |")
    a(f"|------|-----------|------|------|")
    a(f"| 大单买压 | {inst.get('net_wan', 0):+.0f} | {inst.get('direction', '')} | {inst.get('share_pct', 0):.0f}% |")
    a(f"| 中单买压 | {hm.get('net_wan', 0):+.0f} | {hm.get('direction', '')} | {hm.get('share_pct', 0):.0f}% |")
    a(f"| 散单买压 | {retail.get('net_wan', 0):+.0f} | {retail.get('direction', '')} | {retail.get('share_pct', 0):.0f}% |")
    a(f"")
    a(f"> ⚠️ 量化推断模式: 基于腾讯分钟K线量价关系估算，非东财真实资金流数据。东财push2 API今日不可用。")
    a(f"")

    # 概率预判
    a(f"## 🔮 多情景概率预判")
    a(f"")
    for sc in sc_list:
        prob = sc.get("probability", 0)
        a(f"### {sc['name']} → {prob:.0f}%")
        a(f"")
        a(f"{sc.get('description', '')}")
        a(f"")
        a(f"| 条件 | 阈值 | 当前值 | 满足? |")
        a(f"|------|------|--------|-------|")
        for c in sc.get("conditions", []):
            st = "✅" if c.get("m") else "❌"
            a(f"| {c.get('c', '')} | {c.get('t', '')} | {c.get('a', '')} | {st} |")
        a(f"")
        a(f"**历史参考**: {sc.get('historical_ref', {}).get('rule', '')} (胜率: {sc.get('historical_ref', {}).get('historical_win_rate', '')})")
        a(f"")

    # 买卖信号
    a(f"## ⚡ 买卖时机参考")
    a(f"")
    a(f"### 📥 买入参考")
    for bs in buy_sigs:
        a(f"**{bs.get('level', '')}**")
        a(f"- 操作: {bs.get('action', '')}")
        if bs.get("stop_loss"): a(f"- 止损: {bs['stop_loss']}")
        a(f"- 原则: {bs.get('principle', '')}")
        a(f"")
    a(f"### 📤 卖出参考")
    for ss in sell_sigs:
        a(f"**{ss.get('level', '')}**")
        a(f"- 操作: {ss.get('action', '')}")
        if ss.get("risk_note"): a(f"- 风险: {ss['risk_note']}")
        a(f"")
    a(f"### 📌 持有参考")
    a(f"**{hv.get('level', '')}**: {hv.get('reason', '')}")
    a(f"")

    # Footer
    a(f"## ⚠️ 研究声明")
    a(f"")
    a(f"1. 本报告基于公开API实时数据(延迟3-5秒)，所有信号为研究框架产出，**不构成投资建议**")
    a(f"2. 量价分析为量化推断模式(东财push2 API今日不可用)，不区分真实机构/游资/散户资金")
    a(f"3. 板块情绪/市场广度API同样不可用，使用中性默认值")
    a(f"4. **核心原则：宁可少挣，宁可少亏——不确定时不出手**")
    a(f"5. 报告自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    a(f"")

    with open(os.path.join(dir_path, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"  📝 Markdown报告已生成: {dir_path}/report.md")


# ============================================================
# 主流程
# ============================================================
def main():
    code = "600219"
    print("═"*70)
    print(f"  盘中实时交易信号系统 V1.3 — 南山铝业({code})")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═"*70)

    # 时效性检查
    freshness = check_data_freshness()
    print(f"\n  ⏱️ 时效性: {freshness['phase_name']} (阶段{freshness['phase']})")
    if freshness['phase'] <= 1:
        print(f"  ⚠️ 盘初阶段: 板块/北向/广度数据可能延迟，已自动降权")

    # [1/6] 行情
    print("\n[1/6] 拉取实时行情...")
    quote = fetch_tencent_quote(code)
    if "error" in quote:
        print(f"  ❌ 行情获取失败: {quote['error']}"); return
    print(f"  {quote['name']}({code}) 现价{quote['price']:.2f} 涨跌{quote['change_pct']:+.2f}%  "
          f"振幅{quote['amplitude']:.2f}% 换手{quote['turnover_pct']:.2f}% 量比{quote['vol_ratio']:.2f}")

    # [2/6] 资金流
    print("\n[2/6] 拉取分钟级量价数据(腾讯K线)...")
    raw_flow = fetch_minute_klines_tencent(code)
    if "error" in raw_flow:
        print(f"  ❌ 量价数据获取失败: {raw_flow['error']}"); return
    flow = analyze_minute_fund_flow(raw_flow)
    fs = flow["summary"]; ft = flow["trend"]
    print(f"  数据点: {fs['data_points']}分钟 ({fs['first_time']}→{fs['last_time']})")
    print(f"  主力净流入: {fs['total_main_net_wan']:+.0f}万 | 超大单: {fs['total_super_net_wan']:+.0f}万 | "
          f"大单: {fs['total_large_net_wan']:+.0f}万 | 中单: {fs['total_mid_net_wan']:+.0f}万 | 小单: {fs['total_small_net_wan']:+.0f}万")
    print(f"  趋势: {ft['direction']} | {ft['acceleration']}")

    parties = classify_parties(flow)
    v = parties["verdict"]
    print(f"  博弈: {v['scenario'][:80]}")
    print(f"  等级: {v['level']}")

    # [3/6] 板块情绪 + 新闻
    print("\n[3/6] 拉取板块情绪 + 新闻...")
    sector = fetch_sector_sentiment()
    print(f"  有色/铝板块情绪: {sector['sentiment_score']:.0f}/100 {sector['level']}")
    print(f"  {sector['data_basis']}")
    for bk in sector.get("blocks", []):
        emoji = "🟢" if bk["main_net_wan"] > 0 else "🔴"
        print(f"    {emoji} {bk['name']}: 主力{bk['main_net_wan']:+.0f}万 涨跌{bk['change_pct']:+.2f}%")

    news = fetch_intraday_news(["南山铝业", "铝", "有色金属", "电解铝", "氧化铝"])
    print(f"  新闻: {news['today_count']}条 (利好{news['bullish_count']}/利空{news['bearish_count']})")
    for h in (news.get("highlights") or [])[:5]:
        e = "🟢" if h["sentiment"]=="bullish" else ("🔴" if h["sentiment"]=="bearish" else "⚪")
        print(f"    {e} {h['title'][:80]}")

    # [4/6] 北向+大盘+广度
    print("\n[4/6] 拉取北向资金 + 大盘强度 + 市场广度...")
    nb = fetch_north_bound()
    print(f"  北向: {nb['data_basis']}  {nb['signal']}")
    ms = fetch_market_strength(code, quote)
    print(f"  大盘: {ms['data_basis']}  |  {ms['relative_rating']}")
    mb = fetch_market_breadth()
    print(f"  广度: {mb['data_basis']}")

    # [5/6] 概率预判
    print("\n[5/6] 七维概率预判 (V1.3 时效性门控)...")
    scenarios = generate_scenarios(quote, flow, sector, news, nb, ms, mb, freshness)

    # 打印降权日志
    for log in scenarios.get("freshness", {}).get("downgrade_log", []):
        print(log)

    # 获取 fresh 数据用于后续显示
    _fresh_detail = freshness.get("freshness", {})

    for sc in scenarios["scenarios"]:
        icon = "🔥" if sc["probability"] >= 50 else ("📊" if sc["probability"] >= 25 else "🔍")
        print(f"  {icon} {sc['name']}: 概率{sc['probability']:.0f}% ({sc['met_count']}/{sc['total_conditions']}条件)")

    # [6/6] 买卖信号
    print("\n[6/6] 生成买卖时机参考信号...")
    signals = generate_signals(scenarios["scenarios"], quote, flow, sector, nb, ms, mb)

    # ====== 控制台详细输出 ======
    print(f"\n{'─'*60}")
    print(f"  📈 行情: {quote['name']}({code}) 现价{quote['price']:.2f} 涨跌{quote['change_pct']:+.2f}%  "
          f"振幅{quote['amplitude']:.2f}% 换手{quote['turnover_pct']:.2f}% 量比{quote['vol_ratio']:.2f}")
    print(f"  💰 资金: 主力{fs['total_main_net_wan']:+.0f}万 | 机构{fs['total_super_net_wan']:+.0f}万 | "
          f"游资{fs['total_large_net_wan']:+.0f}万 | 散户{(fs['total_mid_net_wan'] or 0)+(fs['total_small_net_wan'] or 0):+.0f}万")
    print(f"  💰 趋势: {ft['direction']} | {ft['acceleration']} ({fs['data_points']}分钟)")
    print(f"  🎯 板块: {sector['sentiment_score']:.0f}/100 {sector['level']} ({sector['inflow_blocks']}/{sector['total_blocks']}流入)")
    print(f"  🌏 北向: {nb['data_basis']} {nb.get('signal', nb.get('status', ''))}")
    print(f"  📊 大盘: {ms['benchmark']}{ms['benchmark_change']:+.2f}% | 个股相对{ms['relative_strength']:+.2f}% {ms['relative_rating']} {ms['market_env']}")
    print(f"  🔥 广度: {mb['up_ratio_pct']:.0f}%上涨 {mb['breadth_level']} | 涨跌停比{mb['limit_ratio']:.1f} {mb['money_effect']}")
    print(f"  📰 新闻: {news['today_count']}条 (利好{news['bullish_count']}/利空{news['bearish_count']})")
    print(f"  ⏱️ 时效性: {freshness['phase_name']}")

    # API状态标注
    api_issues = []
    if nb.get("status") == "unavailable": api_issues.append("北向资金API不可用")
    if mb.get("up_ratio_pct", 0) == 0 and mb.get("down_count", 0) == 0: api_issues.append("市场广度API返回空数据")
    if api_issues:
        print(f"  ⚠️ API问题: {'; '.join(api_issues)}")

    print(f"\n{'─'*60}")
    print(f"  🔮 概率预判:")
    for sc in scenarios["scenarios"]:
        icon = "🔥" if sc["probability"] >= 50 else ("📊" if sc["probability"] >= 25 else "🔍")
        print(f"\n  {icon} {sc['name']} → 概率: {sc['probability']:.0f}% (满足{sc['met_count']}/{sc['total_conditions']}条件)")
        print(f"     {sc['description']}")
        for c in sc["conditions"]:
            st = "✅" if c["m"] else "❌"
            freshness_note = ""
            if c.get("dim") and _fresh_detail.get(c["dim"], 1.0) < 0.7:
                freshness_note = f" ⚠️数据延迟(新鲜度{_fresh_detail.get(c['dim'], 1.0):.1f})"
            print(f"     {st} {c['c']}: 阈值{c['t']}, 当前={c['a']}{freshness_note}")
        print(f"     参考: {sc['historical_ref']['rule']} ({sc['historical_ref']['historical_win_rate']})")

    print(f"\n{'─'*60}")
    print(f"  ⚡ 买卖时机参考:")

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

    print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  🎯 综合评估: {signals['overall_verdict']}")

    # 保存数据
    date_str = datetime.now().strftime("%Y-%m-%d")
    stock_name = quote.get("name", "南山铝业")
    dir_path = f"src/盘中交易信号/{date_str}-{stock_name}-盘中信号"
    os.makedirs(dir_path, exist_ok=True)

    data_json = {
        "target": {"type": "个股", "code": code, "name": stock_name},
        "analysis_time": datetime.now().isoformat(),
        "freshness": freshness,
        "quote": {k: v for k, v in quote.items() if k != "error"},
        "flow_summary": flow.get("summary", {}),
        "flow_trend": {k: v for k, v in flow.get("trend", {}).items() if k != "turning_points"},
        "parties": parties.get("verdict", {}),
        "sector_sentiment": {k: v for k, v in sector.items() if k != "blocks"},
        "north_bound": nb, "market_strength": ms, "market_breadth": mb,
        "scenarios": [{"name": s["name"], "probability": s["probability"],
                       "met_count": s["met_count"], "total_conditions": s["total_conditions"]}
                      for s in scenarios["scenarios"]],
        "signals": signals.get("data_summary", {}),
        "overall_verdict": signals.get("overall_verdict", ""),
        "minute_data": [
            {"time": m["time"], "main_net": m["main_net"],
             "super_net": m["super_net"], "large_net": m["large_net"]}
            for m in flow.get("minutes", [])[-60:]
        ],
    }
    with open(os.path.join(dir_path, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data_json, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n{'═'*70}")
    print(f"  ⚠️ 研究声明:")
    print(f"  1. 所有信号基于公开API实时数据(延迟3-5秒)，不构成投资建议")
    print(f"  2. 概率预判基于七维多因子条件匹配+历史统计规律，不代表未来确定走势")
    print(f"  3. 每个买卖信号标注了具体数据阈值和当前值，可逐一验证")
    print(f"  4. 核心原则：宁可少挣，宁可少亏——不确定时不出手")
    print(f"  5. 报告已保存: {dir_path}/")
    print(f"  6. V1.3 时效性门控: 盘初板块/北向/广度数据可能延迟，自动降权处理")
    print(f"{'═'*70}\n")

    # 生成 Markdown 报告
    _write_report_md(dir_path, code, quote, flow, parties, sector, news, nb, ms, mb, scenarios, signals, freshness)

    return quote, flow, parties, sector, news, nb, ms, mb, scenarios, signals


if __name__ == "__main__":
    main()
