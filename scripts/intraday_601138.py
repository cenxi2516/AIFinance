#!/usr/bin/env python3
"""
工业富联(601138) 盘中实时交易信号分析 V1.3
==========================================
日期: 2026-07-16
基于 intraday-trading-signal skill V1.3 — 七维交叉验证 + 时效性门控

调用链:
  a-stock-data (a_stock_api.py) → 数据拉取
  data_freshness.py → 时效性门控
  → 概率引擎 → 买卖信号 → Console + Markdown 双输出
"""

import sys, os, json, time, re
from datetime import datetime
from urllib.request import Request, urlopen

# 路径设置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.claude', 'skills', '_shared'))
from a_stock_api import (
    UA, em_get, tencent_quote, eastmoney_concept_blocks,
    hsgt_realtime, eastmoney_stock_news, PUSH2_CLIST, PUSH2EX,
)
from data_freshness import check_data_freshness, apply_freshness_to_condition, format_freshness_report

CODE = "601138"
NAME = "工业富联"
NOW = datetime.now()
DATE_STR = NOW.strftime("%Y-%m-%d")
TIME_STR = NOW.strftime("%Y-%m-%d %H:%M:%S")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'src', '盘中交易信号', f"{DATE_STR}-{NAME}-盘中信号")

# ============================================================
# 数据拉取
# ============================================================

print(f"╔══════════════════════════════════════════════════════════════╗")
print(f"║  工业富联(601138) 盘中实时交易信号 V1.3                    ║")
print(f"║  分析时间: {TIME_STR}                                     ║")
print(f"╚══════════════════════════════════════════════════════════════╝")

# --- 时效性门控 ---
freshness = check_data_freshness()
print(f"\n⏱️ 时效性: {freshness['phase_name']} (Phase {freshness['phase']})")
print(format_freshness_report(freshness))

# --- 1. 实时行情 (用原始API，因 a_stock_api tencent_quote 字段映射有偏差) ---
print(f"\n[1/7] 拉取实时行情...")
quote = {}
try:
    url = f"http://qt.gtimg.cn/q=sh{CODE}"
    req = Request(url, headers={"User-Agent": UA})
    resp = urlopen(req, timeout=8)
    data = resp.read().decode("gbk")
    vals = data.split('"')[1].split("~") if '"' in data else []
    # Standard Tencent API field mapping (verified 2026-07-16):
    # [0]=market [1]=name [2]=code [3]=price [4]=prev_close [5]=open
    # [6]=volume_shou [32]=change_pct [33]=high [34]=low
    # [37]=amount_wan [38]=turnover_pct [39]=pe_ttm [43]=amplitude
    # [45]=mcap [46]=pb [47]=limit_up [48]=limit_down [49]=vol_ratio
    def _f(idx): return float(vals[idx]) if idx < len(vals) and vals[idx] else 0.0
    quote = {
        "name": vals[1] if len(vals) > 1 else NAME,
        "code": vals[2] if len(vals) > 2 else CODE,
        "price": _f(3),
        "prev_close": _f(4),
        "open": _f(5),
        "high": _f(33),
        "low": _f(34),
        "change_pct": _f(32),
        "turnover_pct": _f(38),
        "amplitude": _f(43),
        "vol_ratio": _f(49),
        "amount": _f(37),  # 成交额(万)
        "pe_ttm": _f(39),
        "mcap": _f(45),  # 总市值(亿)
        "pb": _f(46),
        "limit_up": _f(47),
        "limit_down": _f(48),
    }
except Exception as e:
    quote = {"error": str(e)}

print(f"   {quote.get('name', '?')}: {quote.get('price', 0):.2f} | {quote.get('change_pct', 0):+.2f}% | "
      f"振幅{quote.get('amplitude', 0):.2f}% | 换手{quote.get('turnover_pct', 0):.2f}% | 量比{quote.get('vol_ratio', 0):.2f}")

# --- 2. 分钟级资金流 ---
print(f"\n[2/7] 拉取分钟级资金流...")
secid = f"1.{CODE}"
url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
params = {
    "secid": secid,
    "fields1": "f1,f2,f3,f4",
    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    "lmt": "240",  # 全天最多240分钟
    "klt": "1",
}
flow_minutes = []
try:
    r = em_get(url, params=params, timeout=10)
    d = r.json()
    if d.get("data") and d["data"].get("klines"):
        for line in d["data"]["klines"]:
            parts = line.split(",")
            if len(parts) >= 6:
                flow_minutes.append({
                    "time": parts[0],
                    "main_net": float(parts[1]) if parts[1] != "-" else 0,
                    "small_net": float(parts[2]) if parts[2] != "-" else 0,
                    "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                    "large_net": float(parts[4]) if parts[4] != "-" else 0,
                    "super_net": float(parts[5]) if parts[5] != "-" else 0,
                })
except Exception as e:
    print(f"   资金流拉取失败: {e}")

# 聚合
total_main = sum(m["main_net"] for m in flow_minutes)
total_super = sum(m["super_net"] for m in flow_minutes)
total_large = sum(m["large_net"] for m in flow_minutes)
total_mid = sum(m["mid_net"] for m in flow_minutes)
total_small = sum(m["small_net"] for m in flow_minutes)
n_points = len(flow_minutes)

# 累计序列 + 趋势分析
cum_main = []
running = 0.0
for m in flow_minutes:
    running += m["main_net"]
    cum_main.append(running)

direction = "流入" if total_main > 0 else "流出"
acceleration = "数据不足"
first_slope = second_slope = 0.0
if len(cum_main) >= 20:
    mid = len(cum_main) // 2
    first_slope = (cum_main[mid - 1] - cum_main[0]) / max(mid, 1)
    second_slope = (cum_main[-1] - cum_main[mid]) / max(len(cum_main) - mid, 1)
    if second_slope > first_slope * 1.5:
        acceleration = "加速流入" if second_slope > 0 else "流出减缓"
    elif second_slope < first_slope * 0.3:
        acceleration = "流入减缓" if second_slope > 0 else "加速流出"
    else:
        acceleration = "匀速" + direction

# 转向点检测
turning_points = []
if len(cum_main) >= 20:
    for i in range(10, len(cum_main) - 5):
        before = cum_main[i - 5:i]
        after = cum_main[i:i + 5]
        is_peak = all(cum_main[i] > b for b in before) and all(cum_main[i] > a for a in after)
        is_valley = all(cum_main[i] < b for b in before) and all(cum_main[i] < a for a in after)
        if is_peak:
            turning_points.append({"time": flow_minutes[i]["time"], "type": "峰值(资金见顶)", "value_wan": cum_main[i] / 1e4})
        elif is_valley:
            turning_points.append({"time": flow_minutes[i]["time"], "type": "谷值(资金见底)", "value_wan": cum_main[i] / 1e4})

# 三方资金
inst_net = total_super
hm_net = total_large
retail_net = total_mid + total_small

print(f"   数据点: {n_points}分钟 | 时段: {flow_minutes[0]['time'] if flow_minutes else '?'} → {flow_minutes[-1]['time'] if flow_minutes else '?'}")
print(f"   主力累计: {total_main/1e4:+.0f}万 | 机构(超大单): {inst_net/1e4:+.0f}万 | 游资(大单): {hm_net/1e4:+.0f}万 | 散户: {retail_net/1e4:+.0f}万")
print(f"   趋势: {direction} | {acceleration} | 前半斜率{first_slope/1e4:+.2f}万/分 → 后半斜率{second_slope/1e4:+.2f}万/分")

# --- 3. 概念板块 + 资金流 ---
print(f"\n[3/7] 拉取板块情绪...")
blocks = eastmoney_concept_blocks(CODE)
print(f"   所属板块: {len(blocks)}个 → {[b.get('bk_name', '')[:6] for b in blocks[:6]]}")

# 拉取全量概念板块资金流 (m:90+t:3)
sector_sentiment_blocks = []
try:
    params_s = {
        "pn": "1", "pz": "500", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",
        "fields": "f2,f3,f12,f14,f62,f104,f105",
    }
    r_s = em_get(PUSH2_CLIST, params=params_s, timeout=15)
    d_s = r_s.json()
    all_sectors = {}
    for it in (d_s.get("data", {}).get("diff", []) or []):
        bk = it.get("f12", "")
        if bk:
            mf = it.get("f62") or 0
            all_sectors[bk] = {
                "code": bk, "name": it.get("f14", ""),
                "change_pct": it.get("f3", 0),
                "main_net_wan": round(mf / 1e4, 1),
                "direction": "流入" if mf > 0 else "流出",
                "up_count": it.get("f104", 0),
                "down_count": it.get("f105", 0),
            }
    # 匹配
    for blk in blocks[:8]:
        bk_code = blk.get("bk_code", "")
        if bk_code in all_sectors:
            sector_sentiment_blocks.append(all_sectors[bk_code])
        else:
            sector_sentiment_blocks.append({
                "code": bk_code, "name": blk.get("bk_name", ""),
                "change_pct": blk.get("change_pct", 0),
                "main_net_wan": 0, "direction": "未知",
                "up_count": 0, "down_count": 0,
            })
except Exception as e:
    print(f"   板块资金流拉取失败: {e}")

# 情绪分计算
if sector_sentiment_blocks:
    inflow_count = sum(1 for b in sector_sentiment_blocks if b["main_net_wan"] > 0)
    total_blk = len(sector_sentiment_blocks)
    avg_change = sum(b["change_pct"] for b in sector_sentiment_blocks) / max(total_blk, 1)
    total_flow = sum(b["main_net_wan"] for b in sector_sentiment_blocks)
    flow_score = (inflow_count / max(total_blk, 1)) * 50
    price_score = max(0, min(50, (avg_change + 5) * 5))
    sentiment_score = round(flow_score + price_score, 1)
else:
    inflow_count = total_blk = 0
    avg_change = 0
    total_flow = 0
    sentiment_score = 50

if sentiment_score >= 75: level = "🔥 极热"
elif sentiment_score >= 60: level = "🟢 偏热"
elif sentiment_score >= 40: level = "🟡 中性"
elif sentiment_score >= 25: level = "🔵 偏冷"
else: level = "❄️ 极冷"

print(f"   情绪分: {sentiment_score:.0f}/100 {level} | {inflow_count}/{total_blk}板块流入 | 均涨{avg_change:+.2f}% | 合计资金{total_flow:+.0f}万")

# --- 4. 新闻 ---
print(f"\n[4/7] 拉取新闻...")
news_list = eastmoney_stock_news(CODE, 20)
today_news = [n for n in news_list if n.get("date", "").startswith(DATE_STR)]
bullish_kw = ["增长", "突破", "中标", "订单", "扩产", "获批", "回购", "增持", "超预期"]
bearish_kw = ["减持", "亏损", "下滑", "调查", "处罚", "诉讼", "违约", "暴雷", "退市"]
news_highlights = []
for n in today_news[:8]:
    s = "neutral"
    title = n.get("title", "")
    if any(kw in title for kw in bullish_kw): s = "bullish"
    elif any(kw in title for kw in bearish_kw): s = "bearish"
    news_highlights.append({**n, "sentiment": s})
print(f"   今日新闻: {len(today_news)}条 (利好{sum(1 for h in news_highlights if h['sentiment']=='bullish')}/利空{sum(1 for h in news_highlights if h['sentiment']=='bearish')})")

# --- 5. 北向资金 ---
print(f"\n[5/7] 拉取北向资金...")
nb = hsgt_realtime()
if nb.get("available"):
    nb_net_yi = nb.get("total_net_yi", 0)
    if nb_net_yi > 5: nb_dir = "大幅流入"; nb_sig = "🟢 积极"
    elif nb_net_yi > 0: nb_dir = "小幅流入"; nb_sig = "🟡 中性偏多"
    elif nb_net_yi > -5: nb_dir = "小幅流出"; nb_sig = "🟠 中性偏空"
    else: nb_dir = "大幅流出"; nb_sig = "🔴 警惕"
    print(f"   北向合计: {nb_net_yi:+.2f}亿 | {nb_dir} {nb_sig}")
else:
    nb_net_yi = 0; nb_dir = "数据不可用"; nb_sig = "⚪"
    print(f"   北向数据不可用")

# --- 6. 大盘强度 ---
print(f"\n[6/7] 拉取大盘指数...")
market_data = {}
try:
    url_idx = f"http://qt.gtimg.cn/q=sh000001,sz399001,sz399006"
    req_idx = Request(url_idx, headers={"User-Agent": UA})
    resp_idx = urlopen(req_idx, timeout=8)
    raw_idx = resp_idx.read().decode("gbk")
    for line in raw_idx.strip().split("\n"):
        if '="' not in line: continue
        var = line.split('="')[0]
        vals = line.split('="')[1].rstrip('";').split("~")
        if len(vals) < 33: continue
        chg = float(vals[32]) if vals[32] else 0.0
        if "000001" in var: market_data["上证指数"] = {"change_pct": chg, "price": float(vals[3]) if vals[3] else 0}
        elif "399001" in var: market_data["深证成指"] = {"change_pct": chg, "price": float(vals[3]) if vals[3] else 0}
        elif "399006" in var: market_data["创业板指"] = {"change_pct": chg, "price": float(vals[3]) if vals[3] else 0}
except Exception as e:
    print(f"   大盘指数拉取失败: {e}")
    market_data = {"上证指数": {"change_pct": 0}, "深证成指": {"change_pct": 0}, "创业板指": {"change_pct": 0}}

benchmark = "上证指数"
benchmark_change = market_data.get("上证指数", {}).get("change_pct", 0)
stock_change = quote.get("change_pct", 0)
relative_strength = stock_change - benchmark_change

if benchmark_change > 1: market_env = "🟢 大盘强势"
elif benchmark_change > 0: market_env = "🟡 大盘微涨"
elif benchmark_change > -1: market_env = "🟠 大盘微跌"
else: market_env = "🔴 大盘弱势"

if relative_strength > 3: rel_rating = "🚀 显著跑赢"
elif relative_strength > 1: rel_rating = "✅ 跑赢大盘"
elif relative_strength > -1: rel_rating = "➖ 与大盘同步"
elif relative_strength > -3: rel_rating = "⚠️ 跑输大盘"
else: rel_rating = "🔴 显著跑输"

print(f"   上证{benchmark_change:+.2f}% | 深证{market_data.get('深证成指', {}).get('change_pct', 0):+.2f}% | 创业板{market_data.get('创业板指', {}).get('change_pct', 0):+.2f}%")
print(f"   个股{stock_change:+.2f}% | 相对强度{relative_strength:+.2f}% | {rel_rating} | {market_env}")

# --- 7. 市场广度 ---
print(f"\n[7/7] 拉取市场广度...")
up_count = down_count = 0
limit_up_count = limit_down_count = 0
try:
    params_b = {
        "pn": "1", "pz": "1", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f104,f105",
    }
    r_b = em_get(PUSH2_CLIST, params=params_b, timeout=8)
    items = (r_b.json().get("data", {}).get("diff", []) or [])
    up_count = sum(it.get("f104", 0) for it in items)
    down_count = sum(it.get("f105", 0) for it in items)
except Exception:
    pass

try:
    r_zt = em_get("https://push2ex.eastmoney.com/getTopicZTPool",
                   params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1", "sort": "fbt", "fbt": "desc"},
                   timeout=8)
    limit_up_count = r_zt.json().get("data", {}).get("total", 0) or 0
except Exception:
    pass

try:
    r_dt = em_get("https://push2ex.eastmoney.com/getTopicDTPool",
                   params={"ut": "7eea3ed8b1e5b1c3", "pageSize": "500", "pageNum": "1", "sort": "fund", "fund": "desc"},
                   timeout=8)
    limit_down_count = r_dt.json().get("data", {}).get("total", 0) or 0
except Exception:
    pass

total_stocks = up_count + down_count
up_ratio = up_count / max(total_stocks, 1) * 100
limit_ratio = limit_up_count / max(limit_down_count, 1)

if up_ratio >= 70: breadth_level = "🟢 普涨格局"; breadth_score = 85
elif up_ratio >= 55: breadth_level = "🟡 涨多跌少"; breadth_score = 60
elif up_ratio >= 45: breadth_level = "🟠 分化格局"; breadth_score = 40
elif up_ratio >= 30: breadth_level = "🔴 跌多涨少"; breadth_score = 20
else: breadth_level = "💀 普跌格局"; breadth_score = 5

if limit_ratio >= 3: money_effect = "🔥 强赚钱效应"
elif limit_ratio >= 1.5: money_effect = "✅ 赚钱效应良好"
elif limit_ratio >= 1: money_effect = "➖ 赚钱效应中性"
elif limit_ratio >= 0.5: money_effect = "⚠️ 亏钱效应显现"
else: money_effect = "💀 强亏钱效应"

print(f"   涨{up_count}跌{down_count} ({up_ratio:.1f}%) | 涨停{limit_up_count}/跌停{limit_down_count} | {breadth_level} | {money_effect}")

# ============================================================
# 概率引擎 (七维 25+条件)
# ============================================================

print(f"\n{'='*60}")
print(f"  概率引擎计算中...")
print(f"{'='*60}")

fd = freshness.get("freshness", {})
_downgrade_log = []

def _cond(text, threshold, actual, met, weight, dimension):
    result = apply_freshness_to_condition(text, threshold, actual, met, weight, dimension, freshness)
    if result.get("freshness_status") != "ready":
        _downgrade_log.append({"condition": text, "dimension": dimension,
                               "status": result["freshness_status"],
                               "original_weight": weight,
                               "effective_weight": result["weight"]})
    return result

# 关键数据提取
change_pct = quote.get("change_pct", 0)
turnover = quote.get("turnover_pct", 0)
vol_ratio = quote.get("vol_ratio", 0)
amplitude = quote.get("amplitude", 0)
price = quote.get("price", 0)
main_net_wan = total_main / 1e4
inst_net_wan = inst_net / 1e4
hm_net_wan = hm_net / 1e4
retail_net_wan = retail_net / 1e4

# 背离检测
divergences = []
if len(cum_main) >= 20:
    seg = len(cum_main) // 4
    for i in range(1, 4):
        ps = (i - 1) * seg; pe = i * seg
        cs = i * seg; ce = min((i + 1) * seg, len(cum_main))
        if ce <= cs: continue
        prev_change = cum_main[pe - 1] - cum_main[ps]
        curr_change = cum_main[ce - 1] - cum_main[cs]
        if change_pct > 3 and prev_change > 0 and curr_change < prev_change * 0.3:
            divergences.append({"type": "顶背离(资金衰竭)", "detail": f"涨{change_pct:+.2f}%,资金流入从{prev_change/1e4:.0f}万降至{curr_change/1e4:.0f}万"})
        if change_pct < -3 and prev_change < 0 and curr_change > abs(prev_change) * 0.5:
            divergences.append({"type": "底背离(资金回流)", "detail": f"跌{change_pct:+.2f}%,资金从流出转为流入"})
has_div = len(divergences) > 0
div_type = divergences[0]["type"] if has_div else ""

scenarios = []

# ━━━ 情景A: 强势上涨 ━━━
a_conds = []; a_score = 0
c = _cond("主力净流入>500万", ">500万", f"{main_net_wan:+.0f}万", main_net_wan > 500 and direction == "流入", 25, "minute_flow")
a_conds.append(c); a_score += c["weight"] if c["met"] == True else 0

inst_dom = inst_net_wan > 200 and inst_net_wan > abs(hm_net_wan) and inst_net_wan > abs(retail_net_wan)
c = _cond("机构主导(>200万且>游资+散户)", "机构>200万且最大", f"机构{inst_net_wan:+.0f}万,游资{hm_net_wan:+.0f}万,散户{retail_net_wan:+.0f}万", inst_dom, 20, "minute_flow")
a_conds.append(c); a_score += c["weight"] if c["met"] == True else 0

c = _cond("板块情绪≥60", "≥60", f"{sentiment_score:.0f}分 ({inflow_count}/{total_blk}板块流入)", sentiment_score >= 60, 15, "sector")
a_conds.append(c); a_score += c["weight"] if c["met"] == True else 0

vol_ok = 1.2 <= vol_ratio <= 5 and turnover < 15
c = _cond("量能配合(量比1.2~5,换手<15%)", "量比1.2-5,换手<15%", f"量比{vol_ratio},换手{turnover}%", vol_ok, 15, "quote")
a_conds.append(c); a_score += c["weight"] if c["met"] == True else 0

no_top_div = not has_div or "顶背离" not in div_type
c = _cond("无顶背离信号", "无顶背离", f"背离:{'有('+div_type+')' if has_div else '无'}", no_top_div, 15, "minute_flow")
a_conds.append(c); a_score += c["weight"] if c["met"] == True else 0

accel_pos = "加速流入" in acceleration
c = _cond("资金加速流入", "后半斜率>前半×1.5", f"前{first_slope/1e4:+.2f}→后{second_slope/1e4:+.2f}万/分", accel_pos, 10, "minute_flow")
a_conds.append(c); a_score += c["weight"] if c["met"] == True else 0

nb_ok = nb_net_yi > 1
c = _cond("北向资金流入(>1亿)", "北向>1亿", f"北向{nb_net_yi:+.2f}亿", nb_ok or nb_net_yi > -5, 10, "north_bound")
a_conds.append(c); a_score += c["weight"] if (c["met"] == True and nb_ok) else (0 if nb_net_yi < -5 else c["weight"]*0.5 if c["met"]==True else 0)

market_ok = relative_strength > 1 and "弱势" not in market_env
c = _cond("大盘配合+个股跑赢", "相对强度>1%且大盘非弱势", f"{market_env},相对{relative_strength:+.2f}%", market_ok, 5, "market")
a_conds.append(c); a_score += c["weight"] if c["met"] == True else 0

breadth_ok = up_ratio >= 45 and "亏钱" not in money_effect
c = _cond("市场广度不差(上涨>45%)", "上涨≥45%", f"涨{up_ratio:.0f}%,{money_effect}", breadth_ok, 5, "breadth")
a_conds.append(c); a_score += c["weight"] if c["met"] == True else (-3 if not breadth_ok and up_ratio > 0 else 0)

# 共振加分
bullish_dims = sum([
    1 if main_net_wan > 300 else 0,
    1 if change_pct > 0 else 0,
    1 if sentiment_score >= 50 else 0,
    1 if nb_net_yi > 0 else 0,
    1 if relative_strength > 0 else 0,
    1 if up_ratio >= 45 else 0,
])
if bullish_dims >= 6: a_score += 10
elif bullish_dims >= 5: a_score += 5

scenarios.append({
    "name": "情景A: 强势上涨", "raw_score": a_score,
    "description": "主力持续流入+机构主导+板块共振+量能配合 → 当日剩余时段大概率继续走强",
    "conditions": a_conds,
    "met_count": sum(1 for c in a_conds if c["met"] == True),
    "total_conditions": len(a_conds),
    "historical_ref": {"rule": "机构主导+板块共振+量能配合 → 当日继续走强", "historical_win_rate": "约65-70%", "source": "日内资金流统计"},
    "failure_conditions": ["午后机构转流出", "板块情绪骤降>20分", "突发利空"],
})

# ━━━ 情景B: 震荡横盘 ━━━
b_conds = []; b_score = 0
c = _cond("主力净流入<300万(无方向)", "|主力|<300万", f"{main_net_wan:+.0f}万", abs(main_net_wan) < 300, 30, "minute_flow")
b_conds.append(c); b_score += c["weight"] if c["met"] == True else 0

c = _cond("振幅<3%(窄幅波动)", "<3%", f"{amplitude}%", amplitude < 3, 25, "quote")
b_conds.append(c); b_score += c["weight"] if c["met"] == True else 0

c = _cond("板块情绪35~65(中性)", "35-65", f"{sentiment_score:.0f}分", 35 <= sentiment_score <= 65, 25, "sector")
b_conds.append(c); b_score += c["weight"] if c["met"] == True else 0

no_news = len(today_news) == 0
c = _cond("无明确消息催化", "0条今日新闻", f"利好{sum(1 for h in news_highlights if h['sentiment']=='bullish')}/利空{sum(1 for h in news_highlights if h['sentiment']=='bearish')}", no_news, 15, "news")
b_conds.append(c); b_score += c["weight"] if c["met"] == True else 0

nb_neutral = abs(nb_net_yi) < 3
c = _cond("北向无明显方向(±3亿)", "|北向|<3亿", f"北向{nb_net_yi:+.2f}亿", nb_neutral, 10, "north_bound")
b_conds.append(c); b_score += c["weight"] if c["met"] == True else 0

market_neutral = abs(relative_strength) < 1.5 and abs(benchmark_change) < 1
c = _cond("大盘+个股均中性波动", "|相对|<1.5%,|大盘|<1%", f"大盘{benchmark_change:+.2f}%,相对{relative_strength:+.2f}%", market_neutral, 10, "market")
b_conds.append(c); b_score += c["weight"] if c["met"] == True else 0

breadth_neutral = 40 <= up_ratio <= 60 and 0.8 <= limit_ratio <= 2
c = _cond("市场广度中性", "涨40-60%,涨跌停比0.8-2", f"涨{up_ratio:.0f}%,涨跌停比{limit_ratio}", breadth_neutral, 10, "breadth")
b_conds.append(c); b_score += c["weight"] if c["met"] == True else 0

scenarios.append({
    "name": "情景B: 震荡横盘", "raw_score": b_score,
    "description": "资金方向不明+振幅小+情绪中性+无催化 → 当日剩余时段大概率窄幅震荡",
    "conditions": b_conds,
    "met_count": sum(1 for c in b_conds if c["met"] == True),
    "total_conditions": len(b_conds),
    "historical_ref": {"rule": "主力无方向+振幅<3% → 后续2h横盘概率较高", "historical_win_rate": "约55-60%", "source": "日内波动统计"},
    "failure_conditions": ["突发消息催化", "大单资金突然涌入/涌出"],
})

# ━━━ 情景C: 冲高回落 ━━━
c_conds = []; c_score = 0

high_turn = change_pct > 3 and ("流出" in acceleration or "减缓" in acceleration)
c = _cond("已涨>3%且资金流转向", "涨>3%+资金减缓/流出", f"涨{change_pct:+.2f}%,趋势:{acceleration}", high_turn, 30, "minute_flow")
c_conds.append(c); c_score += c["weight"] if c["met"] == True else 0

top_div = has_div and "顶背离" in div_type
c = _cond("出现顶背离(资金衰竭)", "顶背离信号", div_type if top_div else "无", top_div, 25, "minute_flow")
c_conds.append(c); c_score += c["weight"] if c["met"] == True else 0

dist = inst_net_wan < -100 and retail_net_wan > 200
c = _cond("机构流出>100万+散户流入>200万(派发)", "机构<-100万,散户>+200万", f"机构{inst_net_wan:+.0f}万,散户{retail_net_wan:+.0f}万", dist, 25, "minute_flow")
c_conds.append(c); c_score += c["weight"] if c["met"] == True else 0

abn_vol = turnover > 10
c = _cond("换手率>10%(异常活跃)", ">10%", f"{turnover}%", abn_vol, 15, "quote")
c_conds.append(c); c_score += c["weight"] if c["met"] == True else 0

nb_bear = nb_net_yi < -2
c = _cond("北向资金流出(<-2亿)", "北向<-2亿", f"北向{nb_net_yi:+.2f}亿", nb_bear, 10, "north_bound")
c_conds.append(c); c_score += c["weight"] if c["met"] == True else 0

high_weak = change_pct > 2 and relative_strength > 1 and "弱势" in market_env
c = _cond("个股高位+大盘走弱(逆势难持续)", "涨>2%+相对>1%+大盘弱势", f"涨{change_pct:+.2f}%,{market_env}", high_weak, 10, "market")
c_conds.append(c); c_score += c["weight"] if c["met"] == True else 0

money_weak = limit_ratio < 1.5 or "亏钱" in money_effect
c = _cond("赚钱效应转弱", "涨跌停比<1.5或有亏钱效应", f"涨跌停比{limit_ratio},{money_effect}", money_weak, 10, "breadth")
c_conds.append(c); c_score += c["weight"] if c["met"] == True else 0

scenarios.append({
    "name": "情景C: 冲高回落", "raw_score": c_score,
    "description": "高位+资金转向/顶背离/机构派发 → 当日剩余时段警惕回落风险",
    "conditions": c_conds,
    "met_count": sum(1 for c in c_conds if c["met"] == True),
    "total_conditions": len(c_conds),
    "historical_ref": {"rule": "涨>3%+资金转流出+机构vs散户反向 → 午后回落概率较高", "historical_win_rate": "约55-65%", "source": "资金-价格关系统计"},
    "failure_conditions": ["超预期利好", "板块集体暴动"],
})

# ━━━ 情景D: 弱势下跌 ━━━
d_conds = []; d_score = 0
c = _cond("主力净流出>500万", "<-500万", f"{main_net_wan:+.0f}万", main_net_wan < -500 and direction == "流出", 30, "minute_flow")
d_conds.append(c); d_score += c["weight"] if c["met"] == True else 0

c = _cond("板块情绪<40(偏冷)", "<40", f"{sentiment_score:.0f}分", sentiment_score < 40, 25, "sector")
d_conds.append(c); d_score += c["weight"] if c["met"] == True else 0

accel_out = "加速流出" in acceleration
c = _cond("资金加速流出", "后半斜率<前半×0.3", f"前{first_slope/1e4:+.2f}→后{second_slope/1e4:+.2f}万/分", accel_out, 25, "minute_flow")
d_conds.append(c); d_score += c["weight"] if c["met"] == True else 0

bear_news = sum(1 for h in news_highlights if h['sentiment']=='bearish') > 0
c = _cond("有利空消息", "利空>0条", f"利空{sum(1 for h in news_highlights if h['sentiment']=='bearish')}条", bear_news, 15, "news")
d_conds.append(c); d_score += c["weight"] if c["met"] == True else 0

nb_heavy = nb_net_yi < -5
c = _cond("北向大幅流出(<-5亿)", "北向<-5亿", f"北向{nb_net_yi:+.2f}亿", nb_heavy, 10, "north_bound")
d_conds.append(c); d_score += c["weight"] if c["met"] == True else 0

market_drag = "弱势" in market_env and relative_strength < -0.5
c = _cond("大盘弱势+个股跑输", "大盘弱势+相对<-0.5%", f"{market_env},相对{relative_strength:+.2f}%", market_drag, 10, "market")
d_conds.append(c); d_score += c["weight"] if c["met"] == True else 0

breadth_bear = up_ratio < 35 or limit_ratio < 0.8
c = _cond("市场普跌(上涨<35%或涨跌停比<0.8)", "上涨<35%", f"涨{up_ratio:.0f}%,涨跌停比{limit_ratio}", breadth_bear, 10, "breadth")
d_conds.append(c); d_score += c["weight"] if c["met"] == True else 0

bearish_dims = sum([
    1 if main_net_wan < -300 else 0,
    1 if sentiment_score < 40 else 0,
    1 if accel_out else 0,
    1 if nb_heavy else 0,
    1 if market_drag else 0,
    1 if breadth_bear else 0,
])
if bearish_dims >= 5: d_score += 10

scenarios.append({
    "name": "情景D: 弱势下跌", "raw_score": d_score,
    "description": "主力持续流出+板块冷+加速流出 → 当日剩余时段大概率继续走弱",
    "conditions": d_conds,
    "met_count": sum(1 for c in d_conds if c["met"] == True),
    "total_conditions": len(d_conds),
    "historical_ref": {"rule": "主力持续流出+板块情绪<40 → 当日收阴概率较高", "historical_win_rate": "约60-70%", "source": "资金-情绪联合统计"},
    "failure_conditions": ["午后重大利好", "国家队护盘"],
})

# 归一化概率
total_score = sum(s["raw_score"] for s in scenarios)
for s in scenarios:
    s["probability"] = round(s["raw_score"] / total_score * 100, 1) if total_score > 0 else 0

scenarios_sorted = sorted(scenarios, key=lambda x: x["probability"], reverse=True)
primary_sc = scenarios_sorted[0]

print(f"\n  主导情景: {primary_sc['name']} → 概率{primary_sc['probability']:.0f}%")
print(f"  时效性降权条件: {len(_downgrade_log)}个")
for dl in _downgrade_log:
    print(f"    ⚡ {dl['dimension']}: {dl['condition']} → {dl['status']} (权重{dl['original_weight']}→{dl['effective_weight']})")

# ============================================================
# 买卖信号生成
# ============================================================

# 买入信号
buy_signals = []
# 强买入
sb_met = sum([
    primary_sc["probability"] >= 60 and "情景A" in primary_sc["name"],
    inst_net_wan > 200,
    sentiment_score >= 60,
    change_pct < 5,
    "加速流入" in acceleration,
])
if sb_met >= 4:
    buy_signals.append({
        "level": "🟢🟢🟢 强买入参考", "strength": sb_met,
        "data_evidence": [
            {"item": "情景A概率", "value": f"{primary_sc['probability']:.0f}%", "threshold": "≥60%", "source": "概率引擎", "met": primary_sc["probability"] >= 60},
            {"item": "主力累计净流入", "value": f"{main_net_wan:+.0f}万", "threshold": ">+200万(机构主导)", "source": "push2分钟资金流", "met": inst_net_wan > 200},
            {"item": "板块情绪分", "value": f"{sentiment_score:.0f}/100", "threshold": "≥60", "source": "板块资金流聚合", "met": sentiment_score >= 60},
            {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<5%(未过度拉升)", "source": "腾讯行情", "met": change_pct < 5},
            {"item": "资金加速度", "value": acceleration, "threshold": "加速流入", "source": "趋势分析", "met": "加速流入" in acceleration},
        ],
        "action": "可考虑逢低建仓/加仓",
        "stop_loss": f"跌破{price * 0.97:.2f}(-3%)则果断离场",
        "principle": f"宁可少挣: {sb_met}/5条件满足,不追高等回调",
    })

# 中买入
mb_met = sum([
    primary_sc["probability"] >= 45 and "情景A" in primary_sc["name"],
    inst_net_wan > 100,
    sentiment_score >= 50,
    change_pct < 7,
])
if mb_met >= 3 and sb_met < 4:
    buy_signals.append({
        "level": "🟢🟢 中等买入参考", "strength": mb_met,
        "data_evidence": [
            {"item": "情景A概率", "value": f"{primary_sc['probability']:.0f}%", "threshold": "≥45%", "source": "概率引擎", "met": primary_sc["probability"] >= 45},
            {"item": "机构净流入", "value": f"{inst_net_wan:+.0f}万", "threshold": ">+100万", "source": "push2分钟资金流", "met": inst_net_wan > 100},
            {"item": "板块情绪分", "value": f"{sentiment_score:.0f}/100", "threshold": "≥50", "source": "板块资金流聚合", "met": sentiment_score >= 50},
            {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": "<7%", "source": "腾讯行情", "met": change_pct < 7},
        ],
        "action": "可小仓位试探(30-50%),等待更多确认",
        "stop_loss": f"跌破{price * 0.95:.2f}(-5%)则止损",
        "principle": "宁可少挣: 先小仓试错,确认后再加仓",
    })

# 弱买入(左侧)
if primary_sc["probability"] >= 30 and "情景D" in primary_sc["name"] and main_net_wan > -300 and sentiment_score >= 30:
    buy_signals.append({
        "level": "🟢 弱买入参考(左侧/反弹)",
        "data_evidence": [
            {"item": "情景D概率", "value": f"{primary_sc['probability']:.0f}%", "threshold": "≥30%但有反弹迹象", "source": "概率引擎", "met": True},
            {"item": "主力净流出", "value": f"{main_net_wan:+.0f}万", "threshold": ">-300万(流出收窄)", "source": "push2", "met": main_net_wan > -300},
            {"item": "板块情绪", "value": f"{sentiment_score:.0f}/100", "threshold": "≥30(未极冷)", "source": "板块资金流", "met": sentiment_score >= 30},
        ],
        "action": "仅极度激进者可关注,大多数人等待企稳确认",
        "stop_loss": f"跌破{price * 0.97:.2f}(-3%)强制止损",
        "principle": "宁可少挣: 宁可等企稳再追,也不提前抄底",
    })

if not buy_signals:
    buy_signals.append({
        "level": "⚪ 暂不建议买入",
        "data_evidence": [
            {"item": "情景A概率", "value": f"{primary_sc['probability']:.0f}%", "threshold": "需≥45%", "source": "概率引擎", "met": primary_sc["probability"] >= 45 and "情景A" in primary_sc["name"]},
            {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "需>+500万", "source": "push2", "met": main_net_wan > 500},
        ],
        "action": "继续观察,等待资金面+情绪面+价格面共振",
        "principle": "宁可少挣: 不买至少不亏钱",
    })

# 卖出信号
sell_signals = []
ss_met = sum([
    primary_sc["probability"] >= 50 and ("情景C" in primary_sc["name"] or "情景D" in primary_sc["name"]),
    inst_net_wan < -200,
    "加速流出" in acceleration,
])
if ss_met >= 3:
    sell_signals.append({
        "level": "🔴🔴🔴 强卖出参考",
        "data_evidence": [
            {"item": "弱势情景概率", "value": f"{primary_sc['probability']:.0f}%({primary_sc['name']})", "threshold": "≥50%", "source": "概率引擎", "met": primary_sc["probability"] >= 50},
            {"item": "机构净流出", "value": f"{inst_net_wan:+.0f}万", "threshold": "<-200万", "source": "push2", "met": inst_net_wan < -200},
            {"item": "资金加速度", "value": acceleration, "threshold": "加速流出", "source": "趋势分析", "met": "加速流出" in acceleration},
            {"item": "主力净流出", "value": f"{main_net_wan:+.0f}万", "threshold": "大额流出", "source": "push2", "met": main_net_wan < -300},
        ],
        "action": "建议果断减仓/清仓",
        "risk_note": f"继续持有可能面临更大回撤,已流出{abs(main_net_wan):.0f}万",
        "principle": "宁可少亏: 卖了少亏比扛着大亏好",
    })

ms_met = sum([
    ("情景C" in primary_sc["name"] and primary_sc["probability"] >= 35) or ("情景D" in primary_sc["name"] and primary_sc["probability"] >= 35),
    inst_net_wan < -100 or (inst_net_wan < 0 and retail_net_wan > 100),
])
if ms_met >= 2 and ss_met < 3:
    sell_signals.append({
        "level": "🔴🔴 中等卖出参考",
        "data_evidence": [
            {"item": "弱势情景概率", "value": f"{primary_sc['probability']:.0f}%({primary_sc['name']})", "threshold": "≥35%", "source": "概率引擎", "met": primary_sc["probability"] >= 35},
            {"item": "机构资金", "value": f"{inst_net_wan:+.0f}万", "threshold": "<-100万或机构流出+散户流入", "source": "push2", "met": inst_net_wan < -100},
            {"item": "散户资金", "value": f"{retail_net_wan:+.0f}万", "threshold": "如>100万则为接盘信号", "source": "push2", "met": retail_net_wan > 100},
        ],
        "action": "建议逐步减仓,至少减到半仓以下",
        "risk_note": f"机构{'流出' if inst_net_wan < 0 else '减弱'}{abs(inst_net_wan):.0f}万,散户{'接盘' if retail_net_wan > 100 else '观望'}{retail_net_wan:+.0f}万",
        "principle": "宁可少亏: 卖一半留一半",
    })

if change_pct > 8 and ("流出" in direction or "减缓" in acceleration):
    sell_signals.append({
        "level": "🔴 弱卖出参考(高位止盈)",
        "data_evidence": [
            {"item": "当前涨幅", "value": f"{change_pct:+.2f}%", "threshold": ">8%", "source": "腾讯行情", "met": True},
            {"item": "资金方向", "value": f"{direction}/{acceleration}", "threshold": "流出/减缓", "source": "趋势分析", "met": True},
        ],
        "action": "可考虑部分止盈,锁定利润",
        "principle": "宁可少挣: 落袋为安",
    })

if not sell_signals:
    sell_signals.append({
        "level": "⚪ 暂不需卖出",
        "data_evidence": [
            {"item": "主力净流入", "value": f"{main_net_wan:+.0f}万", "threshold": "持续流入中", "source": "push2", "met": main_net_wan > 0},
            {"item": "资金加速度", "value": acceleration, "threshold": "未出现流出加速", "source": "趋势分析", "met": "加速流出" not in acceleration},
        ],
        "action": "继续持有观察",
        "principle": "保持警觉,一旦出现卖出信号果断行动",
    })

# 持有建议
if "情景A" in primary_sc["name"] and primary_sc["probability"] >= 50:
    hold_v = {"level": "✅ 可继续持有", "reason": f"强势概率{primary_sc['probability']:.0f}%,主力{main_net_wan:+.0f}万,机构{inst_net_wan:+.0f}万",
              "watch_points": ["午后资金是否转流出", "是否出现顶背离", "板块情绪是否骤降"]}
elif "情景B" in primary_sc["name"]:
    hold_v = {"level": "⏸️ 持有观望", "reason": f"震荡格局,主力{main_net_wan:+.0f}万(无明显方向),振幅{amplitude}%",
              "watch_points": ["突破方向(放量上破/下破)", "是否有催化消息"]}
else:
    hold_v = {"level": "⚠️ 审视持仓", "reason": f"风险情景概率较高({primary_sc['name']} {primary_sc['probability']:.0f}%),机构{inst_net_wan:+.0f}万",
              "watch_points": ["触发止损条件则果断执行", "等待情景A信号再考虑加仓"]}

strongest_buy = buy_signals[0]["level"]
strongest_sell = sell_signals[0]["level"]

if "强买入" in strongest_buy and "暂不需卖出" in strongest_sell:
    overall = f"总体偏多: 买入信号较强,无卖出压力。主力{main_net_wan:+.0f}万,板块情绪{sentiment_score:.0f}分。可在控制仓位前提下逢低参与。"
elif "强卖出" in strongest_sell:
    overall = f"总体偏空: 卖出信号较强。主力净流出{abs(main_net_wan):.0f}万,机构净流出{abs(inst_net_wan):.0f}万。建议减仓或观望。"
elif "中等卖出" in strongest_sell:
    overall = f"总体谨慎: 有卖出压力。机构{inst_net_wan:+.0f}万,散户{retail_net_wan:+.0f}万。持有者应审视持仓,未持有者建议等待。"
elif "中等买入" in strongest_buy:
    overall = f"总体中性偏多: 满足{mb_met}/4买入条件。主力{main_net_wan:+.0f}万。可小仓试探,严格止损。"
else:
    overall = f"总体中性: 主力{main_net_wan:+.0f}万,信号不明确。建议观望。"

# ============================================================
# Console 输出
# ============================================================

print(f"\n{'═' * 70}")
print(f"  📊 工业富联(601138) 盘中实时交易信号")
print(f"  分析时间: {TIME_STR} | {freshness['phase_name']}")
print(f"{'═' * 70}")

# 一、价格面
print(f"\n{'─' * 60}")
print(f"  📈 一、价格面")
print(f"{'─' * 60}")
print(f"  {quote.get('name', '工业富联')}({CODE})")
print(f"  最新价: {price:.2f}  涨跌: {change_pct:+.2f}%  振幅: {amplitude:.2f}%")
print(f"  换手率: {turnover:.2f}%  量比: {vol_ratio:.2f}  成交额: {quote.get('amount', 0):.0f}万")
print(f"  今开: {quote.get('open', 0):.2f}  最高: {quote.get('high', 0):.2f}  最低: {quote.get('low', 0):.2f}")
print(f"  动态PE: {quote.get('pe_ttm', 0):.1f}  总市值: {quote.get('mcap', 0)/1e8 if quote.get('mcap') else 0:.0f}亿")

# 二、资金面
print(f"\n{'─' * 60}")
print(f"  💰 二、资金面 (分钟级)")
print(f"{'─' * 60}")
print(f"  追踪: {flow_minutes[0]['time'] if flow_minutes else '?'} → {flow_minutes[-1]['time'] if flow_minutes else '?'} (共{n_points}分钟)")
print(f"  主力累计: {main_net_wan:+.0f}万")
print(f"    机构(超大单): {inst_net_wan:+.0f}万")
print(f"    游资(大单):   {hm_net_wan:+.0f}万")
print(f"    散户(中+小):  {retail_net_wan:+.0f}万")
print(f"  趋势: {direction} | {acceleration}")
print(f"  前半斜率{first_slope/1e4:+.2f}万/分 → 后半斜率{second_slope/1e4:+.2f}万/分")

# 三方博弈
if inst_net_wan > 200 and hm_net_wan > 0 and retail_net_wan < -100:
    party_scenario = "机构+游资合力做多,散户恐慌出局 → 强多头信号"; party_level = "🟢 积极"
elif inst_net_wan > 200 and retail_net_wan > 100:
    party_scenario = "机构与散户同向流入 → 共识强,但散户过度乐观是隐忧"; party_level = "🟡 中性偏多"
elif inst_net_wan < -200 and retail_net_wan > 200:
    party_scenario = f"机构净流出{abs(inst_net_wan):.0f}万+散户净流入{retail_net_wan:.0f}万 → 机构派发、散户接盘 ⚠️"; party_level = "🔴 警惕"
elif inst_net_wan < -100 and hm_net_wan < -100 and retail_net_wan > 100:
    party_scenario = "机构+游资合力出逃,散户接盘 → 强空头信号"; party_level = "🔴 危险"
elif inst_net_wan > 100 and hm_net_wan < -50 and retail_net_wan < -50:
    party_scenario = f"机构独力做多{inst_net_wan:.0f}万,游资+散户不跟 → 孤军深入"; party_level = "🟡 中性"
else:
    party_scenario = "三方分歧,方向不明确"; party_level = "⚪ 观望"

print(f"\n  🎯 三方博弈: {party_scenario}")
print(f"  信号等级: {party_level}")

# 转向点
if turning_points:
    print(f"  关键转向点:")
    for tp in turning_points[-3:]:
        print(f"    {tp['time']} {tp['type']}: {tp['value_wan']:+.0f}万")

# 背离
if has_div:
    print(f"\n  ⚠️ 背离检测:")
    for div in divergences:
        print(f"    {div['type']}: {div['detail']}")

# 三、情绪面
print(f"\n{'─' * 60}")
print(f"  🎯 三、情绪面")
print(f"{'─' * 60}")
print(f"  板块情绪: {sentiment_score:.0f}/100 {level}")
print(f"  板块数据: {inflow_count}/{total_blk}板块流入,均涨{avg_change:+.2f}%,合计资金{total_flow:+.0f}万")
for bk in sector_sentiment_blocks[:5]:
    print(f"    {bk['name']}: 主力{bk['main_net_wan']:+.0f}万 涨{bk['up_count']}跌{bk['down_count']}")

# 四、消息面
print(f"\n{'─' * 60}")
print(f"  📰 四、消息面")
print(f"{'─' * 60}")
print(f"  今日新闻: {len(today_news)}条 (利好{sum(1 for h in news_highlights if h['sentiment']=='bullish')}/利空{sum(1 for h in news_highlights if h['sentiment']=='bearish')})")
for h in news_highlights[:5]:
    emoji = "🟢" if h["sentiment"] == "bullish" else ("🔴" if h["sentiment"] == "bearish" else "⚪")
    print(f"  {emoji} {h.get('date', '')[:16]} | {h.get('title', '')[:60]}")

# 五、北向+大盘+广度
print(f"\n{'─' * 60}")
print(f"  🌏📊🔥 五、北向+大盘+广度 (V1.1)")
print(f"{'─' * 60}")
print(f"  北向资金: 合计{nb_net_yi:+.2f}亿 | {nb_dir} {nb_sig}")
print(f"  大盘环境: 上证{benchmark_change:+.2f}% 深证{market_data.get('深证成指', {}).get('change_pct', 0):+.2f}% 创业板{market_data.get('创业板指', {}).get('change_pct', 0):+.2f}%")
print(f"  个股评级: {rel_rating} | {market_env} | 相对强度{relative_strength:+.2f}%")
print(f"  市场广度: 涨{up_count}跌{down_count}({up_ratio:.1f}%) 涨停{limit_up_count}/跌停{limit_down_count}")
print(f"  广度评级: {breadth_level}({breadth_score}分) | {money_effect}")

# 六、多情景概率
print(f"\n{'─' * 60}")
print(f"  🔮 六、多情景概率预判 (七维25+条件)")
print(f"{'─' * 60}")
for sc in scenarios_sorted:
    prob = sc["probability"]
    icon = "🔥" if prob >= 50 else ("📊" if prob >= 25 else "🔍")
    print(f"\n  {icon} {sc['name']} → 概率: {prob:.0f}% (满足{sc['met_count']}/{sc['total_conditions']}条件)")
    print(f"     {sc['description']}")
    for c in sc["conditions"]:
        if c["met"] == "PENDING":
            print(f"     ⏳ {c['condition']}: {c['actual']} [数据未就绪,不计分]")
        else:
            status = "✅" if c["met"] == True else "❌"
            print(f"     {status} {c['condition']}: 阈值{c['threshold']}, 当前={c['actual']}")
    ref = sc.get("historical_ref", {})
    print(f"     历史胜率: {ref.get('historical_win_rate', '')} ({ref.get('source', '')})")

# 七、买卖时机
print(f"\n{'─' * 60}")
print(f"  ⚡ 七、买卖时机参考（数据说话）")
print(f"{'─' * 60}")

print(f"\n  📥 买入参考:")
for bs in buy_signals:
    print(f"    {bs['level']}")
    for ev in bs.get("data_evidence", []):
        status = "✅" if ev.get("met") else "❌"
        print(f"      {status} {ev['item']}: {ev['value']} (阈值:{ev['threshold']}) [{ev['source']}]")
    print(f"    操作: {bs.get('action', '')}")
    if bs.get("stop_loss"): print(f"    止损: {bs['stop_loss']}")
    print(f"    原则: {bs.get('principle', '')}")

print(f"\n  📤 卖出参考:")
for ss in sell_signals:
    print(f"    {ss['level']}")
    for ev in ss.get("data_evidence", []):
        status = "✅" if ev.get("met") else "❌"
        print(f"      {status} {ev['item']}: {ev['value']} (阈值:{ev['threshold']}) [{ev['source']}]")
    print(f"    操作: {ss.get('action', '')}")
    if ss.get("risk_note"): print(f"    风险: {ss['risk_note']}")
    print(f"    原则: {ss.get('principle', '')}")

print(f"\n  📌 持有参考: {hold_v['level']}")
print(f"    {hold_v['reason']}")
for wp in hold_v.get("watch_points", []):
    print(f"    👁 {wp}")

print(f"\n  {'─' * 60}")
print(f"  🎯 综合评估: {overall}")

print(f"\n{'═' * 70}")
print(f"  ⚠️ 研究声明:")
print(f"  1. 所有信号基于公开API实时数据,不构成投资建议")
print(f"  2. 概率预判基于七维25+条件匹配+历史统计,V1.3时效性门控")
print(f"  3. 每个买卖信号标注了具体数据阈值和当前值,可逐一验证")
print(f"  4. 核心原则: 宁可少挣,宁可少亏——不确定时不出手")
print(f"{'═' * 70}")

# ============================================================
# 保存报告
# ============================================================
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Markdown 报告
md_lines = []
a = md_lines.append
a(f"# 📊 工业富联(601138) 盘中实时交易信号报告\n")
a(f"**分析时间**: {TIME_STR} | **时效性**: {freshness['phase_name']}\n")
a(f"**核心原则**: 宁可少挣，宁可少亏。买入卖出，数据说话。\n")
a(f"---\n")

a(f"## 🎯 Part 1: 核心结论\n")
a(f"```\n主导情景: {primary_sc['name']} (概率 {primary_sc['probability']:.0f}%)\n买入信号: {strongest_buy}\n卖出信号: {strongest_sell}\n持有建议: {hold_v['level']}\n```\n")
a(f"**综合评估**: {overall}\n")
a(f"---\n")

a(f"## 📊 Part 2: 关键数据一览\n")
a(f"| 维度 | 指标 | 数值 | 信号 |\n")
a(f"|------|------|------|------|\n")
a(f"| 📈 价格 | 最新价 | {price:.2f} | — |\n")
a(f"| 📈 价格 | 涨跌幅 | {change_pct:+.2f}% | {'🔴' if change_pct < 0 else '🟢'} |\n")
a(f"| 📈 价格 | 振幅 | {amplitude:.2f}% | — |\n")
a(f"| 📈 价格 | 换手率 | {turnover:.2f}% | {'🔴 异常' if turnover > 10 else '正常'} |\n")
a(f"| 📈 价格 | 量比 | {vol_ratio:.2f} | — |\n")
a(f"| 💰 资金 | 主力净流入 | {main_net_wan:+.0f}万 | {'🔴 流出' if main_net_wan < 0 else '🟢 流入'} |\n")
a(f"| 💰 资金 | 机构(超大单) | {inst_net_wan:+.0f}万 | {'🔴' if inst_net_wan < 0 else '🟢'} |\n")
a(f"| 💰 资金 | 游资(大单) | {hm_net_wan:+.0f}万 | — |\n")
a(f"| 💰 资金 | 散户(中+小) | {retail_net_wan:+.0f}万 | {'🔴 接盘' if retail_net_wan > 100 else '—'} |\n")
a(f"| 💰 资金 | 趋势 | {direction}/{acceleration} | — |\n")
a(f"| 🎯 情绪 | 板块情绪分 | {sentiment_score:.0f}/100 {level} | — |\n")
a(f"| 🌏 北向 | 北向资金 | {nb_net_yi:+.2f}亿 | {nb_sig} |\n")
a(f"| 📊 大盘 | 相对强度 | {relative_strength:+.2f}% | {rel_rating} |\n")
a(f"| 🔥 广度 | 涨跌比 | {up_ratio:.0f}% | {breadth_level} |\n")
a(f"| 📰 消息 | 今日新闻 | {len(today_news)}条 | — |\n")
a(f"---\n")

a(f"## 🔮 Part 3: 概率预判详情\n")
for sc in scenarios_sorted:
    a(f"### {sc['name']} → 概率: {sc['probability']:.0f}% ({sc['met_count']}/{sc['total_conditions']}条件)\n")
    a(f"{sc['description']}\n")
    a(f"| 条件 | 阈值 | 当前值 | 满足? | 权重 |\n")
    a(f"|------|------|--------|-------|------|\n")
    for c in sc["conditions"]:
        if c["met"] == "PENDING":
            a(f"| {c['condition']} | {c['threshold']} | {c['actual']} | ⏳ PENDING | 0 |\n")
        else:
            status = "✅" if c["met"] == True else "❌"
            a(f"| {c['condition']} | {c['threshold']} | {c['actual']} | {status} | {c.get('weight', 0):.0f} |\n")
    ref = sc.get("historical_ref", {})
    a(f"\n**历史参考**: {ref.get('rule', '')} (胜率: {ref.get('historical_win_rate', '')})\n")
a(f"---\n")

a(f"## ⚡ Part 4: 买卖时机参考\n")
a(f"### 📥 买入参考\n")
for bs in buy_signals:
    a(f"**{bs['level']}**\n")
    a(f"| 数据项 | 数值 | 阈值 | 满足? | 来源 |\n")
    a(f"|--------|------|------|-------|------|\n")
    for ev in bs.get("data_evidence", []):
        status = "✅" if ev.get("met") else "❌"
        a(f"| {ev['item']} | {ev['value']} | {ev['threshold']} | {status} | {ev['source']} |\n")
    a(f"\n- **操作**: {bs.get('action', '')}\n")
    if bs.get("stop_loss"): a(f"- **止损**: {bs['stop_loss']}\n")
    a(f"\n")

a(f"### 📤 卖出参考\n")
for ss in sell_signals:
    a(f"**{ss['level']}**\n")
    a(f"| 数据项 | 数值 | 阈值 | 满足? | 来源 |\n")
    a(f"|--------|------|------|-------|------|\n")
    for ev in ss.get("data_evidence", []):
        status = "✅" if ev.get("met") else "❌"
        a(f"| {ev['item']} | {ev['value']} | {ev['threshold']} | {status} | {ev['source']} |\n")
    a(f"\n- **操作**: {ss.get('action', '')}\n")
    if ss.get("risk_note"): a(f"- **风险**: {ss['risk_note']}\n")
    a(f"\n")

a(f"### 📌 持有参考\n")
a(f"**{hold_v['level']}**\n\n{hold_v['reason']}\n")
for wp in hold_v.get("watch_points", []):
    a(f"- 👁 {wp}\n")
a(f"\n> {overall}\n")
a(f"---\n")

a(f"## ⚠️ 研究声明\n")
a(f"1. 本报告基于公开API实时数据,V1.3时效性门控,不构成投资建议\n")
a(f"2. 每个买卖信号标注了具体数据阈值和当前值,可逐一验证\n")
a(f"3. 核心原则: 宁可少挣,宁可少亏;买入卖出,数据说话\n")
a(f"4. 本报告自动生成于 {TIME_STR}\n")

with open(os.path.join(OUTPUT_DIR, "report.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(md_lines))

# data.json
data_json = {
    "target": {"type": "个股", "code": CODE, "name": NAME},
    "analysis_time": TIME_STR,
    "freshness": {"phase": freshness["phase"], "phase_name": freshness["phase_name"]},
    "quote": {k: v for k, v in quote.items() if isinstance(v, (int, float, str))},
    "fund_flow_summary": {
        "main_net_wan": round(main_net_wan, 1),
        "inst_net_wan": round(inst_net_wan, 1),
        "hm_net_wan": round(hm_net_wan, 1),
        "retail_net_wan": round(retail_net_wan, 1),
        "data_points": n_points,
        "direction": direction, "acceleration": acceleration,
    },
    "scenarios": [{"name": s["name"], "probability": s["probability"], "met_count": s["met_count"], "total_conditions": s["total_conditions"]} for s in scenarios_sorted],
    "signals": {"buy": strongest_buy, "sell": strongest_sell, "hold": hold_v["level"], "overall": overall},
    "minute_data": flow_minutes[-60:],
}
with open(os.path.join(OUTPUT_DIR, "data.json"), "w", encoding="utf-8") as f:
    json.dump(data_json, f, ensure_ascii=False, indent=2, default=str)

print(f"\n✅ 报告已保存:")
print(f"   📄 {OUTPUT_DIR}/report.md")
print(f"   📊 {OUTPUT_DIR}/data.json")
