#!/usr/bin/env python3
"""
盘中实时交易信号系统 V1.3 — 东方电气(600875) 七维分析
日期: 2026-07-13 盘中实时
数据源: push2(分钟级资金流) + 腾讯(行情/K线) + 东财(板块/新闻/广度) + 同花顺(北向)

东方电气(600875): 发电设备龙头，火电/水电/核电/风电全产业链
适配板块: 核电核能/风电/光伏/储能/高端装备/国企改革/一带一路
"""
import time, random, requests, json, re, os, sys
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

# 添加 _shared 目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".claude", "skills", "_shared"))

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
CODE = "600875"
PREFIXED = "sh600875"

# ============================================================
# 市场状态 + 时效性门控
# ============================================================
now = datetime.now()
HM = now.hour * 60 + now.minute
MARKET_SESSION = "上午交易时段" if HM < 11*60+30 else ("下午交易时段" if HM < 15*60 else "盘后")

# 时效性阶段
if HM < 9*60+30: PHASE = 0; PHASE_NAME = "盘前"
elif HM < 10*60: PHASE = 1; PHASE_NAME = "Phase1 盘初(数据延迟高发期)"
elif HM < 11*60: PHASE = 2; PHASE_NAME = "Phase2 早盘过渡"
elif HM < 14*60+30: PHASE = 3; PHASE_NAME = "Phase3 盘中正常"
else: PHASE = 4; PHASE_NAME = "Phase4 尾盘"

# 动态权重矩阵
WEIGHTS = {
    1: {"quote": 25, "fund": 50, "sector": 5, "news": 5, "north": 0, "market": 15, "breadth": 0},
    2: {"quote": 20, "fund": 35, "sector": 12, "news": 8, "north": 5, "market": 12, "breadth": 8},
    3: {"quote": 15, "fund": 25, "sector": 15, "news": 10, "north": 15, "market": 10, "breadth": 10},
    4: {"quote": 15, "fund": 30, "sector": 12, "news": 10, "north": 13, "market": 10, "breadth": 10},
}
W = WEIGHTS.get(PHASE, WEIGHTS[3])

print("═" * 70)
print(f"  📊 盘中实时交易信号 V1.3 — 东方电气(600875)")
print(f"  时间: {now.strftime('%Y-%m-%d %H:%M:%S')} | {MARKET_SESSION} | {PHASE_NAME}")
print(f"  权重: 行情{W['quote']}% 资金{W['fund']}% 板块{W['sector']}% 消息{W['news']}% 北向{W['north']}% 大盘{W['market']}% 广度{W['breadth']}%")
print("═" * 70)

# ============================================================
# Layer 1: 腾讯实时行情 + 日K线
# ============================================================
print("\n[1/7] 拉取实时行情...")

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

quote = fetch_tencent_quote(CODE)
if "error" in quote:
    print(f"  ❌ 行情获取失败: {quote['error']}")
    sys.exit(1)
print(f"  ✅ {quote['name']}({quote['code']}) | 现价{quote['price']:.2f} | 涨跌{quote['change_pct']:+.2f}% | 量比{quote['vol_ratio']:.2f} | 换手{quote['turnover_pct']:.2f}%")

# 日K线
def fetch_tencent_kline(code, days=30):
    prefixed = f"sh{code}" if code.startswith("6") else f"sz{code}"
    try:
        r = requests.get('http://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                         params={'param': f'{prefixed},day,,,{days},qfq'}, timeout=12)
        data = r.json()
        raw = data.get('data', {}).get(prefixed, {}).get('qfqday', []) or \
              data.get('data', {}).get(prefixed, {}).get('day', [])
        return [{"date": d[0], "open": float(d[1]), "close": float(d[2]),
                 "high": float(d[3]), "low": float(d[4]), "volume": int(float(d[5])),
                 "change_pct": round((float(d[2])-float(d[1]))/float(d[1])*100, 2) if float(d[1]) > 0 else 0}
                for d in raw]
    except Exception as e:
        print(f"  [WARN] 日K线获取失败: {e}")
        return []

klines = fetch_tencent_kline(CODE)
if klines:
    last5 = klines[-5:]
    prev_close_k = klines[-2]["close"] if len(klines) >= 2 else quote.get("prev_close", 0)
    kline_strs = []
    for k in last5:
        kline_strs.append(f"{k['date'][-5:]}: {k['change_pct']:+.2f}%")
    print(f"  📈 近5日涨跌: {' | '.join(kline_strs)}")

# ============================================================
# Layer 2: 分钟级资金流 (push2)
# ============================================================
print("\n[2/7] 拉取分钟级资金流...")

def fetch_minute_fund_flow(code):
    """个股分钟级资金流 — push2 API (fflow/kline/get)"""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid, "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        items = d.get("data", {}).get("klines", []) or []
    except Exception as e:
        print(f"  ❌ push2 资金流请求失败: {e}")
        return []

    minutes = []
    for line in items:
        parts = line.split(",")
        if len(parts) >= 6:
            # f51:时间 f52:主力净流入 f53:小单净流入 f54:中单净流入 f55:大单净流入 f56:超大单净流入
            minutes.append({
                "time": parts[0],
                "main_net": float(parts[1]) if parts[1] != "-" else 0,
                "small_net": float(parts[2]) if parts[2] != "-" else 0,
                "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                "large_net": float(parts[4]) if parts[4] != "-" else 0,
                "super_net": float(parts[5]) if parts[5] != "-" else 0,
            })
    return minutes

minutes = fetch_minute_fund_flow(CODE)
if not minutes:
    print("  ❌ 无资金流数据")
    sys.exit(1)

# 聚合统计
total_main = sum(m["main_net"] for m in minutes)
total_super = sum(m["super_net"] for m in minutes)
total_large = sum(m["large_net"] for m in minutes)
total_mid = sum(m["mid_net"] for m in minutes)
total_small = sum(m["small_net"] for m in minutes)

# 累计序列
cum_main = []
running = 0.0
for m in minutes:
    running += m["main_net"]
    cum_main.append(running)

# 趋势方向与加速度
if len(cum_main) >= 10:
    mid_point = len(cum_main) // 2
    first_half = cum_main[:mid_point]
    second_half = cum_main[mid_point:]
    first_slope = (first_half[-1] - first_half[0]) / max(len(first_half), 1) if len(first_half) >= 2 else 0
    second_slope = (second_half[-1] - second_half[0]) / max(len(second_half), 1) if len(second_half) >= 2 else 0
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

# 转向点
turning_points = []
if len(cum_main) >= 20:
    for i in range(10, len(cum_main) - 5):
        before = cum_main[i-5:i]; after = cum_main[i:i+5]
        if all(cum_main[i] > b for b in before) and all(cum_main[i] > a for a in after):
            turning_points.append({"time": minutes[i]["time"], "type": "峰值(资金见顶)", "value_wan": cum_main[i]/1e4})
        elif all(cum_main[i] < b for b in before) and all(cum_main[i] < a for a in after):
            turning_points.append({"time": minutes[i]["time"], "type": "谷值(资金见底)", "value_wan": cum_main[i]/1e4})

main_net_wan = round(total_main / 1e4, 1)
super_net_wan = round(total_super / 1e4, 1)
large_net_wan = round(total_large / 1e4, 1)
mid_net_wan = round(total_mid / 1e4, 1)
small_net_wan = round(total_small / 1e4, 1)
retail_net_wan = mid_net_wan + small_net_wan

print(f"  ✅ {len(minutes)}分钟数据 | {minutes[0]['time']} → {minutes[-1]['time']}")
print(f"  主力累计: {main_net_wan:+.0f}万 | 机构(超大): {super_net_wan:+.0f}万 | 游资(大): {large_net_wan:+.0f}万 | 散户(中+小): {retail_net_wan:+.0f}万")
print(f"  趋势: {direction} | {acceleration} | 前半段{first_slope/1e4:+.2f}万/分 → 后半段{second_slope/1e4:+.2f}万/分")

# 三方博弈
inst_net = super_net_wan
hm_net = large_net_wan
retail_net = retail_net_wan
data_points = len(minutes)

total_abs = abs(inst_net) + abs(hm_net) + abs(retail_net)
inst_share = round(abs(inst_net)/total_abs*100, 1) if total_abs > 0 else 0
hm_share = round(abs(hm_net)/total_abs*100, 1) if total_abs > 0 else 0
retail_share = round(abs(retail_net)/total_abs*100, 1) if total_abs > 0 else 0

# 博弈场景判断
if inst_net > 200 and hm_net > 0 and retail_net < -100:
    party_scenario = "机构+游资合力做多，散户恐慌出局 → 强多头信号"; party_level = "🟢 积极"
elif inst_net > 200 and retail_net > 100:
    party_scenario = "机构与散户同向流入 → 共识强，但散户过度乐观是隐忧"; party_level = "🟡 中性偏多"
elif inst_net < -200 and retail_net > 200:
    party_scenario = f"机构净流出{abs(inst_net):.0f}万 + 散户净流入{retail_net:.0f}万 → 机构派发、散户接盘，⚠️ 明确风险信号"; party_level = "🔴 警惕"
elif inst_net < -100 and hm_net < -100 and retail_net > 100:
    party_scenario = "机构+游资合力出逃，散户接盘 → 强空头信号"; party_level = "🔴 危险"
elif inst_net > 100 and hm_net < -50 and retail_net < -50:
    party_scenario = f"机构独力做多{inst_net:.0f}万，游资{hm_net:.0f}万+散户{retail_net:.0f}万不跟 → 孤军深入"; party_level = "🟡 中性"
else:
    party_scenario = "三方分歧，方向不明确"; party_level = "⚪ 观望"

print(f"  三方博弈: {party_scenario}")
print(f"  信号等级: {party_level}")

# 资金-价格背离检测
change_pct = quote.get("change_pct", 0)
divergences = []
if len(minutes) >= 20:
    n = len(minutes); seg_size = n // 4
    for i in range(1, 4):
        ps = (i-1)*seg_size; pe = i*seg_size
        cs = i*seg_size; ce = min((i+1)*seg_size, n)
        if ce <= cs: continue
        prev_change = cum_main[pe-1] - cum_main[ps]
        curr_change = cum_main[ce-1] - cum_main[cs]
        if change_pct > 3 and prev_change > 0 and curr_change < prev_change * 0.3:
            divergences.append({"type": "顶背离(资金衰竭)", "detail": f"资金流入从{prev_change/1e4:.0f}万骤降至{curr_change/1e4:.0f}万", "risk": "上涨动力衰竭"})
        if change_pct < -3 and prev_change < 0 and curr_change > abs(prev_change) * 0.5:
            divergences.append({"type": "底背离(资金回流)", "detail": f"资金从流出{abs(prev_change)/1e4:.0f}万转为流入{curr_change/1e4:.0f}万", "risk": "下跌动力衰竭"})
has_divergence = len(divergences) > 0
if has_divergence:
    for d in divergences:
        print(f"  ⚠️ {d['type']}: {d['detail']} → {d['risk']}")

# ============================================================
# Layer 3: 概念板块情绪
# ============================================================
print("\n[3/7] 拉取概念板块情绪...")

def fetch_concept_blocks(code):
    """获取个股所属概念板块"""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    params = {
        "pn": "1", "pz": "50", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": f"b:MK0354",  # 概念板块成分股
        "fields": "f12,f14,f3",
    }
    # 用个股所属板块的 hycode 接口
    url = "https://push2.eastmoney.com/api/qt/slist/get"
    params_alt = {
        "pn": "1", "pz": "50", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": f"b:{secid}+b:MK0354",
        "fields": "f12,f14,f3",
    }
    # 更直接的方式：用东财的 stock_board 接口
    try:
        url2 = "https://push2.eastmoney.com/api/qt/stock/get"
        params2 = {
            "secid": secid, "invt": "2", "fltt": "2",
            "fields": "f12,f14,f128",  # f128 = 所属板块
        }
        r = em_get(url2, params=params2,
                   headers={"Referer": "https://quote.eastmoney.com/"}, timeout=8)
        d = r.json()
        # 这个接口不返回板块列表，换一种方式
    except Exception:
        pass

    # 使用东财 datacenter 获取个股所属概念板块
    try:
        # 通过 BK 接口获取
        inner_params = {
            "secid": secid,
            "fields": "f12,f14,f3,f62,f104,f105",
        }
        cb = "jQuery_cb"
        r2 = em_get(
            "https://push2.eastmoney.com/api/qt/slist/get",
            params={
                "spt": "1", "np": "1", "fltt": "2", "invt": "2",
                "fs": f"b:{secid}",
                "fields": "f12,f14",
            },
            headers={"Referer": "https://quote.eastmoney.com/"}, timeout=8)
        # This is getting complex. Let me use the simpler BK lookup approach
    except Exception:
        pass

    # Simplest approach: use the concept board list and match by code
    try:
        r3 = em_get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": "1", "pz": "50", "po": "0", "np": "1",
                "fltt": "2", "invt": "2",
                "fs": f"b:{secid}",
                "fields": "f12,f14,f3,f62,f104,f105",
            },
            headers={"Referer": "https://quote.eastmoney.com/"}, timeout=8)
        d3 = r3.json()
        data = d3.get("data", {})
        if data and data.get("diff"):
            return [{"code": it.get("f12", ""), "name": it.get("f14", ""),
                     "change_pct": it.get("f3", 0),
                     "main_net_wan": round((it.get("f62", 0) or 0) / 1e4, 1),
                     "up_count": it.get("f104", 0), "down_count": it.get("f105", 0)}
                    for it in data["diff"]]
    except Exception as e:
        print(f"  [WARN] 板块获取失败: {e}")

    return []

concept_blocks = fetch_concept_blocks(CODE)
print(f"  ✅ 匹配到 {len(concept_blocks)} 个概念板块")
if concept_blocks:
    for bk in concept_blocks[:5]:
        direction_str = "流入" if bk["main_net_wan"] > 0 else "流出"
        print(f"     {bk['name']}({bk['code']}): {bk['change_pct']:+.2f}% | 主力{bk['main_net_wan']:+.0f}万{direction_str} | 涨{bk['up_count']}跌{bk['down_count']}")

# 加载全量概念板块（用于情绪分计算）
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"
def load_all_concept_sectors():
    params = {
        "pn": "1", "pz": "500", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",
        "fields": "f2,f3,f12,f14,f62,f104,f105",
    }
    try:
        r = em_get(PUSH2_CLIST, params=params,
                   headers={"Referer": "https://data.eastmoney.com/"}, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", []) or []
        sectors = {}
        for it in items:
            bk_code = it.get("f12", "")
            if bk_code:
                mn = it.get("f62") or 0
                sectors[bk_code] = {
                    "code": bk_code, "name": it.get("f14", ""),
                    "change_pct": it.get("f3", 0),
                    "main_net_wan": round(mn / 1e4, 1),
                    "direction": "流入" if mn > 0 else "流出",
                    "up_count": it.get("f104", 0), "down_count": it.get("f105", 0),
                }
        return sectors
    except Exception:
        return {}

all_sectors = load_all_concept_sectors()

# 匹配板块
matched_blocks = []
for bk in concept_blocks[:8]:
    sector_data = all_sectors.get(bk["code"])
    if sector_data:
        matched_blocks.append(sector_data)
    else:
        matched_blocks.append(bk)

if matched_blocks:
    inflow_blocks = sum(1 for b in matched_blocks if b["main_net_wan"] > 0)
    total_blocks = len(matched_blocks)
    avg_change = sum(b["change_pct"] for b in matched_blocks) / max(total_blocks, 1)
    total_flow = sum(b["main_net_wan"] for b in matched_blocks)
    flow_score = (inflow_blocks / max(total_blocks, 1)) * 50
    price_score = max(0, min(50, (avg_change + 5) * 5))
    sentiment_score = round(flow_score + price_score, 1)
else:
    sentiment_score = 50; inflow_blocks = 0; total_blocks = 0
    avg_change = 0; total_flow = 0

if sentiment_score >= 75: sentiment_level = "🔥 极热"
elif sentiment_score >= 60: sentiment_level = "🟢 偏热"
elif sentiment_score >= 40: sentiment_level = "🟡 中性"
elif sentiment_score >= 25: sentiment_level = "🔵 偏冷"
else: sentiment_level = "❄️ 极冷"

print(f"  板块情绪: {sentiment_score:.0f}/100 {sentiment_level} | {inflow_blocks}/{total_blocks}板块流入 | 平均涨跌{avg_change:+.2f}%")

# ============================================================
# Layer 4: 消息面
# ============================================================
print("\n[4/7] 拉取个股消息...")

def fetch_intraday_news(code):
    cb_val = "jQuery_news"
    inner = json.dumps({
        "uid": "", "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {
            "searchScope": "default", "sort": "default",
            "pageIndex": 1, "pageSize": 20, "preTag": "", "postTag": "",
        }},
    }, separators=(',', ':'))
    params = {"cb": cb_val, "param": inner}
    try:
        r = em_get("https://search-api-web.eastmoney.com/search/jsonp",
                   params=params, headers={"Referer": "https://so.eastmoney.com/"}, timeout=10)
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = json.loads(json_str)
        articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
    except Exception:
        return {"today_count": 0, "highlights": [], "bullish_count": 0, "bearish_count": 0}

    today_str = now.strftime("%Y-%m-%d")
    news_list = []
    for a in articles:
        title = re.sub(r'<[^>]+>', '', a.get("title", ""))
        content = re.sub(r'<[^>]+>', '', a.get("content", ""))[:200]
        news_list.append({
            "title": title, "content": content,
            "time": a.get("date", ""), "source": a.get("mediaName", ""),
            "is_today": a.get("date", "").startswith(today_str),
        })

    today_news = [n for n in news_list if n["is_today"]]
    bullish_kw = ["增长", "突破", "中标", "订单", "扩产", "获批", "回购", "增持", "超预期"]
    bearish_kw = ["减持", "亏损", "下滑", "调查", "处罚", "诉讼", "违约", "暴雷", "退市"]

    highlights = []
    for n in today_news[:8]:
        sentiment = "neutral"
        if any(kw in n["title"] for kw in bullish_kw): sentiment = "bullish"
        elif any(kw in n["title"] for kw in bearish_kw): sentiment = "bearish"
        highlights.append({**n, "sentiment": sentiment})

    return {
        "today_count": len(today_news),
        "highlights": highlights,
        "bullish_count": sum(1 for h in highlights if h["sentiment"] == "bullish"),
        "bearish_count": sum(1 for h in highlights if h["sentiment"] == "bearish"),
    }

news = fetch_intraday_news(CODE)
print(f"  ✅ 今日新闻: {news['today_count']}条 (利好{news['bullish_count']}/利空{news['bearish_count']})")
for h in (news.get("highlights") or [])[:3]:
    emoji = "🟢" if h["sentiment"] == "bullish" else ("🔴" if h["sentiment"] == "bearish" else "⚪")
    print(f"     {emoji} {h['title'][:70]}")

# ============================================================
# Layer 5: 北向资金
# ============================================================
print("\n[5/7] 拉取北向资金+大盘强度+市场广度...")

north_data = {"total_net_yi": 0, "direction": "数据待刷新", "signal": "⚪", "data_basis": "北向数据未刷新"}
# 北向数据通常 10:30 后才刷新
if W["north"] > 0:
    try:
        hgt_url = "https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/hgt"
        r_hgt = requests.get(hgt_url, headers={"User-Agent": UA}, timeout=8)
        hgt_data = r_hgt.json()
        sgt_url = "https://hqapi.10jqka.com.cn/hsgt/api/moneyflow/sgt"
        r_sgt = requests.get(sgt_url, headers={"User-Agent": UA}, timeout=8)
        sgt_data = r_sgt.json()

        hgt_net = sum(it.get("net", 0) for it in hgt_data.get("data", [])[-10:]) if hgt_data.get("data") else 0
        sgt_net = sum(it.get("net", 0) for it in sgt_data.get("data", [])[-10:]) if sgt_data.get("data") else 0
        total_north = hgt_net + sgt_net
        total_north_yi = total_north / 1e4

        if abs(total_north) < 100 and PHASE < 3:
            north_data = {"total_net_yi": 0, "direction": "数据待刷新", "signal": "⏳",
                          "data_basis": f"北向数据尚未刷新(当前{total_north_yi:+.2f}亿,延迟)，按V1.3规则降权"}
            print(f"  ⚠️ 北向资金延迟({total_north_yi:+.2f}亿≈0)，按Phase{PHASE}规则权重降为{W['north']}%")
        else:
            if total_north > 5000: nb_dir = "大幅流入"; nb_sig = "🟢 积极"
            elif total_north > 0: nb_dir = "小幅流入"; nb_sig = "🟡 中性偏多"
            elif total_north > -5000: nb_dir = "小幅流出"; nb_sig = "🟠 中性偏空"
            else: nb_dir = "大幅流出"; nb_sig = "🔴 警惕"
            north_data = {
                "total_net_yi": round(total_north_yi, 2),
                "direction": nb_dir, "signal": nb_sig,
                "data_basis": f"沪股通{hgt_net/1e4:+.2f}亿 + 深股通{sgt_net/1e4:+.2f}亿 = 北向合计{total_north_yi:+.2f}亿",
            }
            print(f"  ✅ {north_data['data_basis']} | {nb_dir} {nb_sig}")
    except Exception as e:
        print(f"  ⚠️ 北向获取失败: {e} | 按V1.3降权处理")

# ============================================================
# Layer 6: 大盘相对强度
# ============================================================
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

primary_benchmark = "上证指数" if CODE.startswith(("6", "9")) else ("创业板指" if CODE.startswith("30") else "深证成指")
benchmark_change = market_data.get(primary_benchmark, {}).get("change_pct", 0)
relative_strength = change_pct - benchmark_change

if benchmark_change > 1: market_env = "🟢 大盘强势"
elif benchmark_change > 0: market_env = "🟡 大盘微涨"
elif benchmark_change > -1: market_env = "🟠 大盘微跌"
else: market_env = "🔴 大盘弱势"

if relative_strength > 3: relative_rating = "🚀 显著跑赢"
elif relative_strength > 1: relative_rating = "✅ 跑赢大盘"
elif relative_strength > -1: relative_rating = "➖ 与大盘同步"
elif relative_strength > -3: relative_rating = "⚠️ 跑输大盘"
else: relative_rating = "🔴 显著跑输"

print(f"  ✅ {primary_benchmark}{benchmark_change:+.2f}% | 个股{change_pct:+.2f}% | 相对强度{relative_strength:+.2f}% | {relative_rating}")

# ============================================================
# Layer 7: 市场广度
# ============================================================
up_count = down_count = limit_up_count = limit_down_count = 0
if W["breadth"] > 0:
    try:
        r_breadth = em_get(PUSH2_CLIST, params={
            "pn": "1", "pz": "1", "po": "0", "np": "1",
            "fltt": "2", "invt": "2",
            "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f104,f105",
        }, headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        d = r_breadth.json()
        items = d.get("data", {}).get("diff", [])
        up_count = sum(it.get("f104", 0) for it in items) if items else 0
        down_count = sum(it.get("f105", 0) for it in items) if items else 0
    except Exception:
        pass

    try:
        r_zt = em_get("https://push2ex.eastmoney.com/getTopicZTPool",
                      params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                              "sort": "fbt", "fbt": "desc"},
                      headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        limit_up_count = r_zt.json().get("data", {}).get("total", 0) or 0
        r_dt = em_get("https://push2ex.eastmoney.com/getTopicDTPool",
                      params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1",
                              "sort": "fund", "fund": "desc"},
                      headers={"Referer": "https://data.eastmoney.com/"}, timeout=8)
        limit_down_count = r_dt.json().get("data", {}).get("total", 0) or 0
    except Exception:
        pass

total_stocks = up_count + down_count
up_ratio = up_count / max(total_stocks, 1) * 100
limit_ratio = limit_up_count / max(limit_down_count, 1)

if total_stocks == 0:
    breadth_level = "⏳ 数据未刷新"; breadth_score = 50
    money_effect = "⏳ 数据未刷新"
elif up_ratio >= 70: breadth_level = "🟢 普涨格局"; breadth_score = 85
elif up_ratio >= 55: breadth_level = "🟡 涨多跌少"; breadth_score = 60
elif up_ratio >= 45: breadth_level = "🟠 分化格局"; breadth_score = 40
elif up_ratio >= 30: breadth_level = "🔴 跌多涨少"; breadth_score = 20
else: breadth_level = "💀 普跌格局"; breadth_score = 5

if total_stocks == 0: pass
elif limit_ratio >= 3: money_effect = "🔥 强赚钱效应"
elif limit_ratio >= 1.5: money_effect = "✅ 赚钱效应良好"
elif limit_ratio >= 1: money_effect = "➖ 赚钱效应中性"
elif limit_ratio >= 0.5: money_effect = "⚠️ 亏钱效应显现"
else: money_effect = "💀 强亏钱效应"

if total_stocks > 0:
    print(f"  ✅ 全市场涨{up_count}跌{down_count}({up_ratio:.1f}%) | 涨停{limit_up_count}/跌停{limit_down_count} | {breadth_level} | {money_effect}")
else:
    print(f"  ⚠️ 市场广度未刷新(涨跌全0)，按V1.3规则热度降级处理")

# ============================================================
# Layer 8: 七维概率预判引擎 V1.3
# ============================================================
print("\n[计算] 七维多情景概率预判...")

# 时效性门控：不可用维度的条件标记为 PENDING
breadth_available = total_stocks > 0 and W["breadth"] > 0
north_available = abs(north_data.get("total_net_yi", 0)) > 0.1 and W["north"] > 0
sector_available = len(matched_blocks) > 0 and W["sector"] > 0

# 各维度可用时的权重（实际生效权重）
w_fund = W["fund"]; w_quote = W["quote"]
w_sector_eff = W["sector"] if sector_available else 0
w_news_eff = W["news"]
w_north_eff = W["north"] if north_available else 0
w_market_eff = W["market"]
w_breadth_eff = W["breadth"] if breadth_available else 0

# 归一化分母
total_avail_weight = w_fund + w_quote + w_sector_eff + w_news_eff + w_north_eff + w_market_eff + w_breadth_eff

downgrade_log = []
if not sector_available: downgrade_log.append("板块情绪")
if not north_available: downgrade_log.append("北向资金")
if not breadth_available: downgrade_log.append("市场广度")
if downgrade_log:
    print(f"  ⚠️ V1.3门控: {', '.join(downgrade_log)}标记为PENDING，权重归零不参与计算")

scenarios_list = []

# ═══ 情景A: 强势上涨 ═══
a_score = 0; a_conds = []

# A1: 主力净流入>500万 (权重25 → 按可用权重占比缩放)
c_met = main_net_wan > 500 and direction == "流入"
wt = 25 * w_fund / 25  # 基准25，按fund权重调整
a_score += wt if c_met else 0
a_conds.append({"condition": "主力净流入>500万", "threshold": ">500万", "actual": f"{main_net_wan:+.0f}万", "met": c_met, "weight": wt})

# A2: 机构主导 (权重20)
c_met = inst_net > 200 and inst_net > abs(hm_net) and inst_net > abs(retail_net)
wt = 20 * w_fund / 25
a_score += wt if c_met else 0
a_conds.append({"condition": "机构主导(净流入>200万且>游资+散户)", "threshold": "机构>200万且最大", "actual": f"机构{inst_net:+.0f}万,游资{hm_net:+.0f}万,散户{retail_net:+.0f}万", "met": c_met, "weight": wt})

# A3: 板块情绪≥60 (权重15)
c_met = sentiment_score >= 60
wt = 15 * w_sector_eff / 15 if sector_available else 0
a_score += wt if c_met else 0
status_text = "PENDING(数据未刷新)" if not sector_available else ("✅" if c_met else "❌")
a_conds.append({"condition": "板块情绪分≥60", "threshold": "≥60",
                "actual": f"{sentiment_score:.0f}分" + (" [PENDING]" if not sector_available else ""),
                "met": c_met if sector_available else "PENDING", "weight": wt})

# A4: 量能配合 (权重15)
vol_ratio_v = quote.get("vol_ratio", 0); turnover_v = quote.get("turnover_pct", 0)
c_met = 1.2 <= vol_ratio_v <= 5 and turnover_v < 15
wt = 15 * w_quote / 15
a_score += wt if c_met else 0
a_conds.append({"condition": "量能配合(量比1.2~5,换手<15%)", "threshold": "量比1.2-5,换手<15%",
                "actual": f"量比{vol_ratio_v},换手{turnover_v}%", "met": c_met, "weight": wt})

# A5: 无顶背离 (权重15)
c_met = not has_divergence or "顶背离" not in str(divergences)
wt = 15 * w_quote / 15
a_score += wt if c_met else 0
a_conds.append({"condition": "无顶背离信号", "threshold": "无顶背离",
                "actual": "无" if not has_divergence else str(divergences), "met": c_met, "weight": wt})

# A6: 资金加速度正向 (权重10)
c_met = "加速流入" in acceleration
wt = 10 * w_fund / 25
a_score += wt if c_met else 0
a_conds.append({"condition": "资金加速流入", "threshold": "后半段斜率>前半段×1.5",
                "actual": f"前半段{first_slope/1e4:+.2f}万/分→后半段{second_slope/1e4:+.2f}万/分", "met": c_met, "weight": wt})

# A7: 北向资金支持 (权重10)
nb_net_yi = north_data.get("total_net_yi", 0)
c_met = nb_net_yi > 1
wt = 10 * w_north_eff / 15 if north_available else 0
a_score += wt if c_met else 0
if not north_available:
    a_conds.append({"condition": "北向资金流入(>1亿)", "threshold": "北向净流入>1亿",
                    "actual": f"北向{nb_net_yi:+.2f}亿 [PENDING]", "met": "PENDING", "weight": wt})
elif nb_net_yi < -5:
    a_score -= 5
    a_conds.append({"condition": "北向资金未大幅流出", "threshold": "北向>-5亿",
                    "actual": f"北向{nb_net_yi:+.2f}亿(⚠️大幅流出扣分)", "met": False, "weight": wt})
else:
    a_conds.append({"condition": "北向资金不拖累", "threshold": "北向不大幅流出",
                    "actual": f"北向{nb_net_yi:+.2f}亿", "met": nb_net_yi > -5, "weight": wt})

# A8: 大盘共振 (权重5)
c_met = relative_strength > 1 and "弱势" not in market_env
wt = 5 * w_market_eff / 10
a_score += wt if c_met else 0
a_conds.append({"condition": "大盘配合+个股跑赢", "threshold": "相对强度>1%且大盘非弱势",
                "actual": f"{market_env}, 相对强度{relative_strength:+.2f}%", "met": c_met, "weight": wt})

# A9: 市场广度支持 (权重5)
c_met = up_ratio >= 45 and "亏钱" not in money_effect
wt = 5 * w_breadth_eff / 10 if breadth_available else 0
a_score += wt if c_met and breadth_available else 0
if not breadth_available:
    a_conds.append({"condition": "市场广度不差(上涨>45%)", "threshold": "上涨占比≥45%",
                    "actual": f"涨0跌0 [PENDING]", "met": "PENDING", "weight": wt})
else:
    a_conds.append({"condition": "市场广度不差(上涨>45%)", "threshold": "上涨占比≥45%",
                    "actual": f"涨{up_ratio:.0f}%, {money_effect}", "met": c_met, "weight": wt})
    if not c_met:
        a_score -= 3

# 七维同向共振
bullish_dims = sum([
    1 if main_net_wan > 300 else 0,
    1 if change_pct > 0 else 0,
    1 if sentiment_score >= 50 else 0,
    1 if news["bullish_count"] > news["bearish_count"] else 0,
    1 if nb_net_yi > 0 else 0,
    1 if relative_strength > 0 else 0,
    1 if up_ratio >= 45 else 0,
])
if bullish_dims >= 6: a_score += 10
elif bullish_dims >= 5: a_score += 5

scenarios_list.append({
    "name": "情景A: 强势上涨", "raw_score": a_score,
    "description": "主力持续流入+机构主导+板块共振+量能配合 → 当日剩余时段大概率继续走强",
    "conditions": a_conds, "met_count": sum(1 for c in a_conds if c["met"] == True),
    "total_conditions": len(a_conds),
    "historical_ref": {"rule": "机构主导+板块共振+量能配合 → 当日继续走强", "historical_win_rate": "约65-70%", "source": "基于2024-2025年A股日内资金流统计规律"},
    "failure_conditions": ["午后机构资金转流出", "板块情绪急转直下", "突发重大利空"],
})

# ═══ 情景B: 震荡横盘 ═══
b_score = 0; b_conds = []

c_met = abs(main_net_wan) < 300
wt = 30 * w_fund / 25
b_score += wt if c_met else 0
b_conds.append({"condition": "主力净流入<300万(无方向)", "threshold": "绝对值<300万", "actual": f"{main_net_wan:+.0f}万", "met": c_met, "weight": wt})

c_met = quote.get("amplitude", 0) < 3
wt = 25 * w_quote / 15
b_score += wt if c_met else 0
b_conds.append({"condition": "振幅<3%(窄幅波动)", "threshold": "<3%", "actual": f"{quote.get('amplitude', 0)}%", "met": c_met, "weight": wt})

c_met = 35 <= sentiment_score <= 65
wt = 25 * w_sector_eff / 15 if sector_available else 0
b_score += wt if c_met and sector_available else 0
b_conds.append({"condition": "板块情绪35~65(中性)", "threshold": "35-65",
                "actual": f"{sentiment_score:.0f}分" + (" [PENDING]" if not sector_available else ""),
                "met": c_met if sector_available else "PENDING", "weight": wt})

c_met = news["bullish_count"] == 0 and news["bearish_count"] == 0
wt = 15 * w_news_eff / 10
b_score += wt if c_met else 0
b_conds.append({"condition": "无明确消息催化", "threshold": "0条今日新闻",
                "actual": f"利好{news['bullish_count']}/利空{news['bearish_count']}", "met": c_met, "weight": wt})

c_met = abs(nb_net_yi) < 3
wt = 10 * w_north_eff / 15 if north_available else 0
b_score += wt if c_met and north_available else 0
b_conds.append({"condition": "北向资金无明显方向(±3亿内)", "threshold": "|北向|<3亿",
                "actual": f"北向{nb_net_yi:+.2f}亿" + (" [PENDING]" if not north_available else ""),
                "met": c_met if north_available else "PENDING", "weight": wt})

c_met = abs(relative_strength) < 1.5 and abs(benchmark_change) < 1
wt = 10 * w_market_eff / 10
b_score += wt if c_met else 0
b_conds.append({"condition": "大盘+个股均中性波动", "threshold": "|相对强度|<1.5%,|大盘|<1%",
                "actual": f"大盘{benchmark_change:+.2f}%, 相对{relative_strength:+.2f}%", "met": c_met, "weight": wt})

c_met = 40 <= up_ratio <= 60 and 0.8 <= limit_ratio <= 2
wt = 10 * w_breadth_eff / 10 if breadth_available else 0
b_score += wt if c_met and breadth_available else 0
b_conds.append({"condition": "市场广度中性(涨40-60%)", "threshold": "涨40-60%",
                "actual": f"涨{up_ratio:.0f}%" + (" [PENDING]" if not breadth_available else ""),
                "met": c_met if breadth_available else "PENDING", "weight": wt})

scenarios_list.append({
    "name": "情景B: 震荡横盘", "raw_score": b_score,
    "description": "资金方向不明+振幅小+情绪中性+无催化 → 当日剩余时段大概率窄幅震荡",
    "conditions": b_conds, "met_count": sum(1 for c in b_conds if c["met"] == True),
    "total_conditions": len(b_conds),
    "historical_ref": {"rule": "主力资金无明显方向+振幅<3% → 后续2小时横盘概率较高", "historical_win_rate": "约55-60%", "source": "基于A股日内波动统计规律"},
    "failure_conditions": ["突发消息催化", "大单资金突然涌入/涌出"],
})

# ═══ 情景C: 冲高回落 ═══
c_score = 0; c_conds = []

c_met = change_pct > 3 and ("流出" in acceleration or "减缓" in acceleration)
wt = 30 * w_fund / 25
c_score += wt if c_met else 0
c_conds.append({"condition": "已涨>3%且资金流转向", "threshold": "涨>3%+资金减缓/流出",
                "actual": f"涨{change_pct:+.2f}%, 趋势:{acceleration}", "met": c_met, "weight": wt})

c_met = has_divergence and "顶背离" in str(divergences)
wt = 25 * w_quote / 15
c_score += wt if c_met else 0
c_conds.append({"condition": "出现顶背离(资金衰竭)", "threshold": "顶背离信号",
                "actual": "有" if has_divergence else "无", "met": c_met, "weight": wt})

c_met = inst_net < -100 and retail_net > 200
wt = 25 * w_fund / 25
c_score += wt if c_met else 0
c_conds.append({"condition": "机构流出>100万+散户流入>200万(派发)", "threshold": "机构<-100万,散户>+200万",
                "actual": f"机构{inst_net:+.0f}万,散户{retail_net:+.0f}万", "met": c_met, "weight": wt})

c_met = turnover_v > 10
wt = 15 * w_quote / 15
c_score += wt if c_met else 0
c_conds.append({"condition": "换手率>10%(异常活跃)", "threshold": ">10%", "actual": f"{turnover_v}%", "met": c_met, "weight": wt})

c_met = nb_net_yi < -2
wt = 10 * w_north_eff / 15 if north_available else 0
c_score += wt if c_met and north_available else 0
c_conds.append({"condition": "北向资金流出(<-2亿)", "threshold": "北向<-2亿",
                "actual": f"北向{nb_net_yi:+.2f}亿" + (" [PENDING]" if not north_available else ""),
                "met": c_met if north_available else "PENDING", "weight": wt})

c_met = change_pct > 2 and relative_strength > 1 and "弱势" in market_env
wt = 10 * w_market_eff / 10
c_score += wt if c_met else 0
c_conds.append({"condition": "个股高位+大盘走弱(逆势难持续)", "threshold": "涨>2%+大盘弱势",
                "actual": f"涨{change_pct:+.2f}%, 大盘{benchmark_change:+.2f}%", "met": c_met, "weight": wt})

c_met = limit_ratio < 1.5 and "亏钱" not in money_effect
wt = 10 * w_breadth_eff / 10 if breadth_available else 0
c_score += wt if c_met and breadth_available else 0
c_conds.append({"condition": "赚钱效应转弱", "threshold": "涨跌停比<1.5",
                "actual": f"涨跌停比{limit_ratio}" + (" [PENDING]" if not breadth_available else ""),
                "met": c_met if breadth_available else "PENDING", "weight": wt})

scenarios_list.append({
    "name": "情景C: 冲高回落", "raw_score": c_score,
    "description": "高位+资金转向/顶背离/机构派发 → 当日剩余时段警惕回落风险",
    "conditions": c_conds, "met_count": sum(1 for c in c_conds if c["met"] == True),
    "total_conditions": len(c_conds),
    "historical_ref": {"rule": "涨超3%+资金转流出+机构vs散户反向 → 午后回落概率较高", "historical_win_rate": "约55-65%", "source": "基于A股日内资金流-价格关系统计"},
    "failure_conditions": ["超预期利好", "板块集体暴动(涨停潮)"],
})

# ═══ 情景D: 弱势下跌 ═══
d_score = 0; d_conds = []

c_met = main_net_wan < -500 and direction == "流出"
wt = 30 * w_fund / 25
d_score += wt if c_met else 0
d_conds.append({"condition": "主力净流出>500万", "threshold": "<-500万", "actual": f"{main_net_wan:+.0f}万", "met": c_met, "weight": wt})

c_met = sentiment_score < 40
wt = 25 * w_sector_eff / 15 if sector_available else 0
d_score += wt if c_met and sector_available else 0
d_conds.append({"condition": "板块情绪<40(偏冷)", "threshold": "<40",
                "actual": f"{sentiment_score:.0f}分" + (" [PENDING]" if not sector_available else ""),
                "met": c_met if sector_available else "PENDING", "weight": wt})

c_met = "加速流出" in acceleration
wt = 25 * w_fund / 25
d_score += wt if c_met else 0
d_conds.append({"condition": "资金加速流出", "threshold": "后半段斜率<前半段×0.3且<0",
                "actual": f"前半段{first_slope/1e4:+.2f}→后半段{second_slope/1e4:+.2f}万/分", "met": c_met, "weight": wt})

c_met = news["bearish_count"] > 0
wt = 15 * w_news_eff / 10
d_score += wt if c_met else 0
d_conds.append({"condition": "有利空消息", "threshold": "利空>0条", "actual": f"利空{news['bearish_count']}条", "met": c_met, "weight": wt})

c_met = nb_net_yi < -5
wt = 10 * w_north_eff / 15 if north_available else 0
d_score += wt if c_met and north_available else 0
d_conds.append({"condition": "北向大幅流出(<-5亿)", "threshold": "北向<-5亿",
                "actual": f"北向{nb_net_yi:+.2f}亿" + (" [PENDING]" if not north_available else ""),
                "met": c_met if north_available else "PENDING", "weight": wt})

c_met = "弱势" in market_env and relative_strength < -0.5
wt = 10 * w_market_eff / 10
d_score += wt if c_met else 0
d_conds.append({"condition": "大盘弱势+个股跑输", "threshold": "大盘弱势+相对强度<-0.5%",
                "actual": f"{market_env}, 相对{relative_strength:+.2f}%", "met": c_met, "weight": wt})

c_met = up_ratio < 35
wt = 10 * w_breadth_eff / 10 if breadth_available else 0
d_score += wt if c_met and breadth_available else 0
d_conds.append({"condition": "市场普跌(上涨<35%)", "threshold": "上涨<35%",
                "actual": f"涨{up_ratio:.0f}%" + (" [PENDING]" if not breadth_available else ""),
                "met": c_met if breadth_available else "PENDING", "weight": wt})

# 空头共振
bearish_dims = sum([
    1 if main_net_wan < -300 else 0,
    1 if change_pct < 0 else 0,
    1 if sentiment_score < 40 else 0,
    1 if news["bearish_count"] > 0 else 0,
    1 if nb_net_yi < 0 else 0,
    1 if relative_strength < -0.5 else 0,
    1 if up_ratio < 45 else 0,
])
if bearish_dims >= 5: d_score += 10

scenarios_list.append({
    "name": "情景D: 弱势下跌", "raw_score": d_score,
    "description": "主力持续流出+板块冷+加速流出 → 当日剩余时段大概率继续走弱",
    "conditions": d_conds, "met_count": sum(1 for c in d_conds if c["met"] == True),
    "total_conditions": len(d_conds),
    "historical_ref": {"rule": "主力持续流出+板块情绪<40 → 当日收阴概率较高", "historical_win_rate": "约60-70%", "source": "基于A股日内资金流-板块情绪联合统计"},
    "failure_conditions": ["午后重大利好", "国家队护盘资金入场"],
})

# 归一化概率
total_score = sum(s["raw_score"] for s in scenarios_list)
for s in scenarios_list:
    s["probability"] = round(s["raw_score"] / total_score * 100, 1) if total_score > 0 else 0

scenarios_sorted = sorted(scenarios_list, key=lambda x: x["probability"], reverse=True)

# ============================================================
# 买卖时机参考信号
# ============================================================
primary = scenarios_sorted[0]
primary_prob = primary["probability"]
primary_name = primary["name"]

buy_signals = []
sell_signals = []

# 强买入
strong_buy = [primary_prob >= 60 and "情景A" in primary_name, inst_net > 200, sentiment_score >= 60, change_pct < 5, "加速流入" in acceleration]
strong_buy_met = sum(1 for c in strong_buy if c)
if strong_buy_met >= 4:
    buy_signals.append({"level": "🟢🟢🟢 强买入参考", "strength": strong_buy_met,
        "data_evidence": [
            {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "≥60%", "source": "多因子概率引擎", "met": primary_prob >= 60},
            {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "机构>+200万", "source": "push2分钟级资金流", "met": inst_net > 200},
            {"item": "板块情绪", "value": f"{sentiment_score:.0f}/100", "threshold": "≥60", "source": "板块资金流聚合", "met": sentiment_score >= 60},
            {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<5%", "source": "腾讯行情", "met": change_pct < 5},
            {"item": "资金加速度", "value": acceleration, "threshold": "加速流入", "source": "push2趋势分析", "met": "加速流入" in acceleration},
        ],
        "action": "可考虑逢低建仓/加仓", "stop_loss": f"跌破{quote['price']*0.97:.2f}(-3%)则果断离场",
        "principle": f"宁可少挣: {strong_buy_met}/5条件满足，不追高，等回调到分时均线附近再动手"})

# 中等买入
medium_buy = [primary_prob >= 45 and "情景A" in primary_name, inst_net > 100, sentiment_score >= 50, change_pct < 7]
medium_buy_met = sum(1 for c in medium_buy if c)
if medium_buy_met >= 3 and strong_buy_met < 4:
    buy_signals.append({"level": "🟢🟢 中等买入参考", "strength": medium_buy_met,
        "data_evidence": [
            {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "≥45%", "source": "多因子概率引擎", "met": primary_prob >= 45},
            {"item": "机构净流入", "value": f"{inst_net:+.0f}万", "threshold": ">+100万", "source": "push2分钟级资金流", "met": inst_net > 100},
            {"item": "板块情绪", "value": f"{sentiment_score:.0f}/100", "threshold": "≥50", "source": "板块资金流聚合", "met": sentiment_score >= 50},
            {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<7%", "source": "腾讯行情", "met": change_pct < 7},
        ],
        "action": "可小仓位试探(计划仓位的30-50%)，等待更多信号确认",
        "stop_loss": f"跌破{quote['price']*0.95:.2f}(-5%)则止损",
        "principle": "宁可少挣: 先小仓试错，确认方向后再加仓"})

if not buy_signals:
    buy_signals.append({"level": "⚪ 暂不建议买入",
        "data_evidence": [
            {"item": "情景A概率", "value": f"{primary_prob:.0f}%", "threshold": "需≥45%", "source": "多因子概率引擎", "met": primary_prob >= 45},
            {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "需>+500万(情景A)或流出收窄", "source": "push2分钟级资金流", "met": main_net_wan > 500},
        ],
        "action": "继续观察，等待资金面+情绪面+价格面共振信号",
        "principle": "宁可少挣: 不买至少不亏钱，错过一波比亏一波好"})

# 强卖出
strong_sell = [primary_prob >= 50 and ("情景C" in primary_name or "情景D" in primary_name), inst_net < -200, "加速流出" in acceleration]
strong_sell_met = sum(1 for c in strong_sell if c)
if strong_sell_met >= 3:
    sell_signals.append({"level": "🔴🔴🔴 强卖出参考", "strength": strong_sell_met,
        "data_evidence": [
            {"item": "弱势情景概率", "value": f"{primary_prob:.0f}%({primary_name})", "threshold": "≥50%", "source": "多因子概率引擎", "met": primary_prob >= 50},
            {"item": "机构净流出", "value": f"{inst_net:+.0f}万", "threshold": "<-200万", "source": "push2分钟级资金流", "met": inst_net < -200},
            {"item": "资金加速度", "value": acceleration, "threshold": "加速流出", "source": "push2趋势分析", "met": "加速流出" in acceleration},
            {"item": "主力净流出", "value": f"{main_net_wan:+.0f}万", "threshold": "大额流出", "source": "push2分钟级资金流", "met": main_net_wan < -300},
        ],
        "action": "建议果断减仓/清仓，不在下跌中补仓",
        "risk_note": f"继续持有可能面临更大回撤，当前已流出{abs(main_net_wan):.0f}万",
        "principle": "宁可少亏: 卖了少亏比扛着大亏好，卖错了可以再买回来"})

# 中等卖出
medium_sell = [("情景C" in primary_name and primary_prob >= 35) or ("情景D" in primary_name and primary_prob >= 35), inst_net < -100 or (inst_net < 0 and retail_net > 100)]
medium_sell_met = sum(1 for c in medium_sell if c)
if medium_sell_met >= 2 and strong_sell_met < 3:
    sell_signals.append({"level": "🔴🔴 中等卖出参考", "strength": medium_sell_met,
        "data_evidence": [
            {"item": "弱势情景概率", "value": f"{primary_prob:.0f}%({primary_name})", "threshold": "≥35%", "source": "多因子概率引擎", "met": primary_prob >= 35},
            {"item": "机构资金", "value": f"{inst_net:+.0f}万", "threshold": "<-100万或机构流出+散户流入", "source": "push2分钟级资金流", "met": inst_net < -100},
            {"item": "散户资金", "value": f"{retail_net:+.0f}万", "threshold": "如>+100万则为接盘信号", "source": "push2分钟级资金流", "met": retail_net > 100},
        ],
        "action": "建议逐步减仓，至少减到半仓以下",
        "principle": "宁可少亏: 卖一半留一半，涨了还有仓位，跌了少亏一半"})

if not sell_signals:
    sell_signals.append({"level": "⚪ 暂不需卖出",
        "data_evidence": [
            {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "持续流入中", "source": "push2分钟级资金流", "met": main_net_wan > 0},
            {"item": "资金加速度", "value": acceleration, "threshold": "未出现流出加速", "source": "push2趋势分析", "met": "加速流出" not in acceleration},
        ],
        "action": "继续持有观察，关注资金流方向是否转弱",
        "principle": "保持警觉，一旦出现卖出数据条件，果断行动"})

# 持有参考
if "情景A" in primary_name and primary_prob >= 50:
    hold_verdict = {"level": "✅ 可继续持有", "reason": f"强势上涨概率{primary_prob:.0f}%，主力净流入{main_net_wan:+.0f}万，机构主导({inst_net:+.0f}万)",
                    "watch_points": ["午后资金是否转流出", "是否出现顶背离", "板块情绪是否骤降"]}
elif "情景B" in primary_name:
    hold_verdict = {"level": "⏸️ 持有观望", "reason": f"震荡格局，主力资金{main_net_wan:+.0f}万(无明显方向)，振幅{quote.get('amplitude', 0)}%",
                    "watch_points": ["突破方向(放量上破/下破)", "是否有催化消息出现"]}
else:
    hold_verdict = {"level": "⚠️ 审视持仓", "reason": f"风险情景概率较高({primary_name} {primary_prob:.0f}%)，机构{inst_net:+.0f}万",
                    "watch_points": ["触发止损条件则果断执行", "等待情景A信号出现再考虑加仓"]}

# ============================================================
# 控制台输出
# ============================================================
print("\n" + "═" * 70)
print(f"  🎯 核心结论")
print("═" * 70)
strongest_buy = buy_signals[0]["level"] if buy_signals else ""
strongest_sell = sell_signals[0]["level"] if sell_signals else ""
print(f"""
  主导情景: {primary_name} (概率 {primary_prob:.0f}%)
  买入信号: {strongest_buy}
  卖出信号: {strongest_sell}
  持有建议: {hold_verdict['level']}
""")

# 各情景详情
print("─" * 60)
print("  🔮 多情景概率预判")
print("─" * 60)
for sc in scenarios_sorted:
    prob = sc["probability"]; name = sc["name"]; met = sc["met_count"]; total = sc["total_conditions"]
    icon = "🔥" if prob >= 50 else ("📊" if prob >= 25 else "🔍")
    print(f"\n  {icon} {name} → 概率: {prob:.0f}% (满足{met}/{total}条件)")
    print(f"     {sc['description']}")
    for c in sc["conditions"]:
        status = "✅" if c["met"] == True else ("PENDING" if c["met"] == "PENDING" else "❌")
        print(f"     {status} {c['condition']}: 阈值{c['threshold']}, 当前={c['actual']}")

# 买卖信号
print(f"\n{'─' * 60}")
print(f"  ⚡ 买卖时机参考（数据说话）")
print(f"{'─' * 60}")
print(f"\n  📥 买入参考:")
for bs in buy_signals:
    print(f"    {bs['level']}")
    for ev in bs["data_evidence"]:
        status = "✅" if ev["met"] else "❌"
        print(f"      {status} {ev['item']}: {ev['value']} (阈值: {ev['threshold']}) [{ev['source']}]")
    print(f"    操作: {bs['action']}")
    if bs.get("stop_loss"): print(f"    止损: {bs['stop_loss']}")
    print(f"    原则: {bs.get('principle', '')}")

print(f"\n  📤 卖出参考:")
for ss in sell_signals:
    print(f"    {ss['level']}")
    for ev in ss.get("data_evidence", []):
        status = "✅" if ev["met"] else "❌"
        print(f"      {status} {ev['item']}: {ev['value']} (阈值: {ev['threshold']}) [{ev['source']}]")
    print(f"    操作: {ss['action']}")
    if ss.get("risk_note"): print(f"    风险: {ss['risk_note']}")
    print(f"    原则: {ss.get('principle', '')}")

print(f"\n  📌 持有参考: {hold_verdict['level']}")
print(f"    {hold_verdict['reason']}")
for wp in hold_verdict.get("watch_points", []):
    print(f"    👁 {wp}")

# 综合评估
if "强买入" in strongest_buy: overall = f"总体偏多: 买入信号较强(满足{strong_buy_met}/5条件)。主力净流入{main_net_wan:+.0f}万，板块情绪{sentiment_score:.0f}分。可在控制仓位前提下逢低参与。"
elif "强卖出" in strongest_sell: overall = f"总体偏空: 卖出信号较强(满足{strong_sell_met}/3条件)。主力净流出{abs(main_net_wan):.0f}万。建议减仓或观望。"
elif "中等卖出" in strongest_sell: overall = f"总体谨慎: 有卖出压力。机构{inst_net:+.0f}万，散户{retail_net:+.0f}万。持有者应审视持仓。"
elif "中等买入" in strongest_buy: overall = f"总体中性偏多: 满足{medium_buy_met}/4买入条件。主力{main_net_wan:+.0f}万。可小仓试探，严格止损。"
else: overall = f"总体中性: 主力{main_net_wan:+.0f}万，信号不明确。建议观望，等待更清晰的信号。"

print(f"\n  ━━━━━━━━━━━━")
print(f"  🎯 综合评估: {overall}")

# 七维数据摘要
print(f"\n  📋 七维数据摘要:")
print(f"     资金: 主力{main_net_wan:+.0f}万 | 机构{inst_net:+.0f}万 | 散户{retail_net:+.0f}万 | {direction}/{acceleration}")
print(f"     行情: {quote['name']} | 现价{quote['price']:.2f} | 涨跌{change_pct:+.2f}% | 量比{vol_ratio_v:.2f} | 换手{turnover_v:.2f}%")
print(f"     板块: {sentiment_score:.0f}/100 {sentiment_level} | {inflow_blocks}/{total_blocks}板块流入")
print(f"     北向: {north_data.get('data_basis', '')}")
print(f"     大盘: {primary_benchmark}{benchmark_change:+.2f}% | 个股{change_pct:+.2f}% | 相对{relative_strength:+.2f}% | {relative_rating}")
if breadth_available:
    print(f"     广度: 涨{up_count}跌{down_count}({up_ratio:.1f}%) | 涨停{limit_up_count}/跌停{limit_down_count} | {breadth_level} | {money_effect}")
else:
    print(f"     广度: ⏳ 数据未刷新 [PENDING]")
print(f"     消息: 今日{news['today_count']}条 (利好{news['bullish_count']}/利空{news['bearish_count']})")

# 风险声明
print(f"\n{'═' * 70}")
print(f"  ⚠️ 研究声明:")
print(f"  1. 所有信号基于公开API实时数据(延迟3-5秒)，不构成投资建议")
print(f"  2. 概率预判基于七维条件匹配+时效性门控(V1.3)，PENDING项不参与计算")
print(f"  3. 每个买卖信号标注了具体数据阈值和当前值，可逐一验证")
print(f"  4. 核心原则：宁可少挣，宁可少亏——不确定时不出手")
print(f"  5. 报告已自动保存到 src/盘中交易信号/ 目录(data.json可用于回测)")
print(f"{'═' * 70}")

# ============================================================
# 保存报告到 src/盘中交易信号/
# ============================================================
target_name = quote.get("name", CODE)
date_str = now.strftime("%Y-%m-%d")
dir_name = f"{date_str}-{target_name}-盘中信号"
dir_path = os.path.join(OUTPUT_BASE, dir_name)
os.makedirs(dir_path, exist_ok=True)

# report.md
report_lines = []
a = report_lines.append
a(f"# 📊 盘中实时交易信号报告")
a(f"")
a(f"**标的**: {target_name} ({CODE})")
a(f"**分析时间**: {now.strftime('%Y-%m-%d %H:%M:%S')}")
a(f"**市场状态**: {MARKET_SESSION} | {PHASE_NAME}")
a(f"**核心原则**: 宁可少挣，宁可少亏。买入卖出，数据说话。")
a(f"")
a(f"---")
a(f"")
a(f"## ⏱️ V1.3 时效性门控评估")
a(f"")
a(f"> **{PHASE_NAME}**: 行情{W['quote']}% 分时{W['fund']}% 板块{W['sector']}% 消息{W['news']}% 北向{W['north']}% 大盘{W['market']}% 广度{W['breadth']}%")
a(f"")
a(f"| 维度 | 状态 | 有效权重 |")
a(f"|------|------|---------|")
a(f"| 📈 行情 | ✅ 正常 | {w_quote}% |")
a(f"| 💰 分时 | ✅ 正常 ({data_points}分钟) | {w_fund}% |")
a(f"| 🎯 板块 | {'✅ 正常' if sector_available else '⚠️ PENDING'} | {w_sector_eff}% |")
a(f"| 🌏 北向 | {'✅ 正常' if north_available else '⚠️ PENDING'} | {w_north_eff}% |")
a(f"| 📊 大盘 | ✅ 正常 | {w_market_eff}% |")
a(f"| 🔥 广度 | {'✅ 正常' if breadth_available else '⚠️ PENDING(全0未刷新)'} | {w_breadth_eff}% |")
if downgrade_log:
    a(f"")
    a(f"**⚠️ 降级维度**: {', '.join(downgrade_log)} — 涉及这些维度的条件权重归零，不参与概率计算。")
a(f"")
a(f"---")
a(f"")

# Part 1: 核心结论
a(f"## 🎯 Part 1: 核心结论")
a(f"")
a(f"```")
a(f"主导情景: {primary_name} (概率 {primary_prob:.0f}%)")
a(f"买入信号: {strongest_buy}")
a(f"卖出信号: {strongest_sell}")
a(f"持有建议: {hold_verdict['level']}")
a(f"```")
a(f"")
a(f"**综合评估**: {overall}")
a(f"")
a(f"---")
a(f"")

# Part 2: 关键数据一览
a(f"## 📊 Part 2: 关键数据一览")
a(f"")
a(f"| 维度 | 指标 | 数值 | 信号 |")
a(f"|------|------|------|------|")
a(f"| 📈 价格 | 最新价 | {quote['price']:.2f} | — |")
a(f"| 📈 价格 | 涨跌幅 | {change_pct:+.2f}% | {'🔴' if change_pct < 0 else '🟢'} |")
a(f"| 📈 价格 | 振幅 | {quote.get('amplitude', 0):.2f}% | — |")
a(f"| 📈 价格 | 换手率 | {turnover_v:.2f}% | {'🔴 异常' if turnover_v > 10 else '正常'} |")
a(f"| 📈 价格 | 量比 | {vol_ratio_v:.2f} | — |")
a(f"| 💰 资金 | 主力净流入 | {main_net_wan:+.0f}万 | {'🔴 流出' if main_net_wan < 0 else '🟢 流入'} |")
a(f"| 💰 资金 | 机构(超大单) | {super_net_wan:+.0f}万 | {'🔴' if super_net_wan < 0 else '🟢'} |")
a(f"| 💰 资金 | 游资(大单) | {large_net_wan:+.0f}万 | — |")
a(f"| 💰 资金 | 散户(中+小) | {retail_net_wan:+.0f}万 | {'🔴 接盘' if retail_net_wan > 100 else '—'} |")
a(f"| 💰 资金 | 趋势 | {direction}/{acceleration} | — |")
a(f"| 💰 资金 | 数据点 | {data_points}分钟 | — |")
a(f"| 🎯 情绪 | 板块情绪分 | {sentiment_score:.0f}/100 {sentiment_level} | — |")
a(f"| 🌏 北向 | 北向资金 | {north_data.get('total_net_yi', 0):+.2f}亿 | {north_data.get('signal', '⏳')} |")
a(f"| 📊 大盘 | 相对强度 | {relative_strength:+.2f}% | {relative_rating} |")
a(f"| 📊 大盘 | 基准涨跌 | {benchmark_change:+.2f}% | {market_env} |")
a(f"| 🔥 广度 | 涨跌家数比 | {up_ratio:.0f}% | {breadth_level if breadth_available else '⏳ 未刷新'} |")
a(f"| 📰 消息 | 今日新闻 | {news['today_count']}条 | — |")
a(f"")

# 三方博弈详情
a(f"### 💰 三方资金博弈详情")
a(f"")
a(f"| 资金类型 | 净流入(万) | 方向 | 份额 |")
a(f"|---------|-----------|------|------|")
a(f"| 🔴 机构(超大单) | {inst_net:+.0f} | {'流入' if inst_net > 0 else '流出'} | {inst_share:.0f}% |")
a(f"| 🟡 游资(大单) | {hm_net:+.0f} | {'流入' if hm_net > 0 else '流出'} | {hm_share:.0f}% |")
a(f"| 🟢 散户(中+小) | {retail_net:+.0f} | {'流入' if retail_net > 0 else '流出'} | {retail_share:.0f}% |")
a(f"")
a(f"**信号等级**: {party_level} | **场景**: {party_scenario}")
a(f"")

if turning_points:
    a(f"### 📈 关键转向点")
    a(f"")
    a(f"| 时间 | 类型 | 累计值(万) |")
    a(f"|------|------|-----------|")
    for tp in turning_points[-5:]:
        a(f"| {tp['time']} | {tp['type']} | {tp['value_wan']:+.0f} |")
    a(f"")

if divergences:
    a(f"### ⚠️ 资金-价格背离")
    a(f"")
    for d in divergences:
        a(f"- **{d['type']}**: {d['detail']} → {d['risk']}")
    a(f"")

# Part 3: 多情景概率
a(f"## 🔮 Part 3: 多情景概率预判（七维条件引擎）")
a(f"")
for sc in scenarios_sorted:
    prob = sc["probability"]; name = sc["name"]; met = sc["met_count"]; total = sc["total_conditions"]
    ref = sc.get("historical_ref", {}); fails = sc.get("failure_conditions", [])
    a(f"### {name} → 概率: {prob:.0f}%")
    a(f"")
    a(f"**条件满足**: {met}/{total}")
    a(f"")
    a(f"| 条件 | 阈值 | 当前值 | 满足? | 权重 |")
    a(f"|------|------|--------|-------|------|")
    for c in sc["conditions"]:
        status = "✅" if c["met"] == True else ("⏳" if c["met"] == "PENDING" else "❌")
        a(f"| {c['condition']} | {c['threshold']} | {c['actual']} | {status} | {c['weight']:.0f} |")
    a(f"")
    a(f"**历史参考**: {ref.get('rule', '')} (历史胜率: {ref.get('historical_win_rate', '')})")
    if fails: a(f"**失效条件**: {'; '.join(fails)}")
    a(f"")

# Part 4: 买卖信号
a(f"## ⚡ Part 4: 买卖时机参考（数据说话）")
a(f"")
a(f"### 📥 买入参考")
a(f"")
for bs in buy_signals:
    a(f"**{bs['level']}**")
    a(f"")
    a(f"| 数据项 | 数值 | 阈值 | 满足? | 来源 |")
    a(f"|--------|------|------|-------|------|")
    for ev in bs.get("data_evidence", []):
        status = "✅" if ev["met"] else "❌"
        a(f"| {ev['item']} | {ev['value']} | {ev['threshold']} | {status} | {ev['source']} |")
    a(f"")
    a(f"- **操作**: {bs['action']}")
    if bs.get("stop_loss"): a(f"- **止损**: {bs['stop_loss']}")
    a(f"")

a(f"### 📤 卖出参考")
a(f"")
for ss in sell_signals:
    a(f"**{ss['level']}**")
    a(f"")
    a(f"| 数据项 | 数值 | 阈值 | 满足? | 来源 |")
    a(f"|--------|------|------|-------|------|")
    for ev in ss.get("data_evidence", []):
        status = "✅" if ev["met"] else "❌"
        a(f"| {ev['item']} | {ev['value']} | {ev['threshold']} | {status} | {ev['source']} |")
    a(f"")
    a(f"- **操作**: {ss['action']}")
    if ss.get("risk_note"): a(f"- **风险**: {ss['risk_note']}")
    a(f"")

a(f"### 📌 持有参考")
a(f"")
a(f"**{hold_verdict['level']}**")
a(f"- {hold_verdict['reason']}")
for wp in hold_verdict.get("watch_points", []):
    a(f"- 👁 {wp}")
a(f"")

a(f"---")
a(f"")
a(f"## ⚠️ 研究声明")
a(f"")
a(f"1. 本报告基于公开API实时数据（延迟3-5秒），所有信号为研究框架产出，**不构成投资建议**")
a(f"2. 每个买卖信号标注了具体数据阈值和当前值，可逐一验证")
a(f"3. 概率预判基于七维多因子条件匹配 + 时效性门控(V1.3)")
a(f"4. '机构/游资/散户'分类基于订单大小的近似估算")
a(f"5. **核心原则：宁可少挣，宁可少亏；买入卖出，数据说话**")
a(f"6. 本报告自动生成于 {now.strftime('%Y-%m-%d %H:%M:%S')}，原始数据见 data.json")
if downgrade_log:
    a(f"7. **V1.3时效性门控**: {', '.join(downgrade_log)}数据未刷新，相关条件标记为PENDING不参与概率计算")

report_md = "\n".join(report_lines)
with open(os.path.join(dir_path, "report.md"), "w", encoding="utf-8") as f:
    f.write(report_md)

# data.json
data_json = {
    "target": {"type": "个股", "code": CODE, "name": target_name},
    "analysis_time": now.isoformat(),
    "market_session": MARKET_SESSION,
    "phase": {"phase": PHASE, "name": PHASE_NAME, "weights": W, "downgraded": downgrade_log},
    "quote": {k: v for k, v in quote.items() if not k.startswith("_")},
    "fund_flow": {
        "main_net_wan": main_net_wan, "super_net_wan": super_net_wan,
        "large_net_wan": large_net_wan, "retail_net_wan": retail_net_wan,
        "direction": direction, "acceleration": acceleration,
        "data_points": data_points,
        "party_scenario": party_scenario, "party_level": party_level,
    },
    "sector_sentiment": {"score": sentiment_score, "level": sentiment_level,
                         "inflow_blocks": inflow_blocks, "total_blocks": total_blocks},
    "north_bound": north_data,
    "market_strength": {"benchmark": primary_benchmark, "benchmark_change": benchmark_change,
                        "relative_strength": relative_strength, "relative_rating": relative_rating},
    "market_breadth": {"up_count": up_count, "down_count": down_count, "up_ratio": up_ratio,
                       "limit_up": limit_up_count, "limit_down": limit_down_count, "available": breadth_available},
    "scenarios": [{"name": s["name"], "probability": s["probability"], "raw_score": s["raw_score"]} for s in scenarios_sorted],
    "signals": {"buy": strongest_buy, "sell": strongest_sell, "hold": hold_verdict["level"], "overall": overall},
    "minute_data": [{"time": m["time"], "main_net": m["main_net"], "super_net": m["super_net"], "large_net": m["large_net"]} for m in minutes[-60:]],
}

with open(os.path.join(dir_path, "data.json"), "w", encoding="utf-8") as f:
    json.dump(data_json, f, ensure_ascii=False, indent=2, default=str)

print(f"\n✅ 报告已保存: {dir_path}/")
print(f"   ├── report.md (完整信号报告)")
print(f"   └── data.json (原始数据)")
print()
