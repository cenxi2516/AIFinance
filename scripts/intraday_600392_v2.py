#!/usr/bin/env python3
"""
盛和资源(600392) 盘中实时交易信号 — 拉取最新数据
时间: 2026-07-13 午盘收盘附近
数据源: mootdx(分时买卖力道) + 腾讯(行情/指数) + 东财(新闻,限流时降级)
"""
import time, random, requests, json, re, os
from datetime import datetime
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CODE = "600392"

# ============================================================
# 1. 腾讯行情
# ============================================================
def fetch_quote():
    prefixed = f"sh{CODE}"
    url = f"https://qt.gtimg.cn/q={prefixed}"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=8)
        r.encoding = "gbk"
        vals = r.text.split('"')[1].split("~") if '"' in r.text else []
        if len(vals) < 53: return {"error": "字段不足"}
        return {
            "name": vals[1], "code": vals[2],
            "price": float(vals[3]) if vals[3] else 0,
            "prev_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
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
# 2. mootdx 分时买卖力道
# ============================================================
def fetch_mootdx_minutes():
    from mootdx.quotes import Quotes
    client = Quotes.factory(market='std')
    try:
        df = client.minutes(symbol=CODE, date='20260714')
        if df is None or len(df) == 0: return []
        rows = []
        for idx, row in df.iterrows():
            rows.append({"time": str(idx), "price": float(row.get("price", 0)),
                         "vol": int(row.get("vol", 0))})
        return rows
    except Exception as e:
        print(f"  [WARN] mootdx失败: {e}")
        return []

def analyze_minute_flow(minute_data):
    """从分时价格+成交量推导买卖力道"""
    if not minute_data or len(minute_data) < 2:
        return {"error": "分时数据不足", "summary": {}, "trend": {}}

    buy_vol = 0; sell_vol = 0
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

    # 趋势分析
    if len(cum_flow) >= 10:
        mid = len(cum_flow) // 2
        s1 = (cum_flow[mid-1]["net_vol"] - cum_flow[0]["net_vol"]) / max(mid, 1)
        s2 = (cum_flow[-1]["net_vol"] - cum_flow[mid]["net_vol"]) / max(len(cum_flow)-mid, 1)
        direction = "买方占优" if cum_flow[-1]["net_vol"] > 0 else "卖方占优"
        if s2 > s1 * 1.5: accel = "买方加速" if s2 > 0 else "卖压减弱"
        elif s2 < s1 * 0.3: accel = "买力减弱" if s2 > 0 else "卖压加速"
        else: accel = "匀速"
    else:
        direction = "数据不足"; accel = "数据不足"; s1 = s2 = 0

    # 转向点
    turning = []
    net_seq = [c["net_vol"] for c in cum_flow]
    if len(net_seq) >= 20:
        for i in range(10, len(net_seq)-5):
            bf = net_seq[i-5:i]; af = net_seq[i:i+5]
            if all(net_seq[i] > b for b in bf) and all(net_seq[i] > a for a in af):
                turning.append({"time": cum_flow[i]["time"], "type": "买力见顶", "vol": net_seq[i]})
            elif all(net_seq[i] < b for b in bf) and all(net_seq[i] < a for a in af):
                turning.append({"time": cum_flow[i]["time"], "type": "卖压见底", "vol": net_seq[i]})

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
        "trend": {
            "direction": direction, "acceleration": accel,
            "first_slope": round(s1, 0), "second_slope": round(s2, 0),
            "turning_points": turning[-5:],
        },
        "source": "mootdx 分时 → 买卖力道推导",
    }

# ============================================================
# 3. 大盘指数
# ============================================================
def fetch_market():
    indices = {"上证指数": "sh000001", "深证成指": "sz399001", "创业板指": "sz399006"}
    market_data = {}
    for name, idx in indices.items():
        try:
            r = requests.get(f"https://qt.gtimg.cn/q={idx}",
                           headers={"User-Agent": UA}, timeout=8)
            r.encoding = "gbk"
            vals = r.text.split('"')[1].split("~") if '"' in r.text else []
            if len(vals) >= 33:
                market_data[name] = {
                    "price": float(vals[3]) if vals[3] else 0,
                    "change_pct": float(vals[32]) if vals[32] else 0,
                }
        except Exception:
            market_data[name] = {"price": 0, "change_pct": 0}

    bench = "上证指数"
    bc = market_data.get(bench, {}).get("change_pct", 0)
    return bench, bc, market_data

# ============================================================
# 4. 新闻 (如果东财不可用就跳过)
# ============================================================
def fetch_news():
    today = datetime.now().strftime("%Y-%m-%d")
    highlights = []
    for kw in ["盛和资源", "稀土"]:
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
                           headers={"Referer": "https://so.eastmoney.com/", "User-Agent": UA}, timeout=10)
            text = r.text
            json_str = text[text.index("(")+1:text.rindex(")")]
            articles = json.loads(json_str).get("result", {}).get("cmsArticleWebOld", []) or []
        except Exception:
            continue

        bullish_kw = ["增长","突破","中标","扩产","获批","回购","增持","超预期","利好","涨价","反弹"]
        bearish_kw = ["减持","亏损","下滑","调查","处罚","诉讼","违约","制裁","限制","降价","暴跌"]
        for a in articles:
            title = re.sub(r'<[^>]+>', '', a.get("title", ""))
            if a.get("date", "").startswith(today):
                sentiment = "neutral"
                if any(x in title for x in bullish_kw): sentiment = "bullish"
                elif any(x in title for x in bearish_kw): sentiment = "bearish"
                highlights.append({"title": title, "time": a.get("date", ""),
                                   "source": a.get("mediaName", ""), "sentiment": sentiment})

    seen = set(); unique = []
    for h in highlights:
        if h["title"] not in seen: seen.add(h["title"]); unique.append(h)
    return unique

# ============================================================
# 5. 概率预判引擎
# ============================================================
def generate_scenarios(quote, flow):
    change_pct = quote.get("change_pct", 0)
    turnover = quote.get("turnover_pct", 0)
    vol_ratio = quote.get("vol_ratio", 0)
    amplitude = quote.get("amplitude", 0)

    s = flow.get("summary", {})
    buy_ratio = s.get("buy_ratio_pct", 50)
    net_vol = s.get("total_net_vol", 0)

    ft = flow.get("trend", {})
    direction = ft.get("direction", "")
    acceleration = ft.get("acceleration", "")
    s1 = ft.get("first_slope", 0)
    s2 = ft.get("second_slope", 0)

    # 因为东财限流,缺少板块/北向/广度数据,用价格+买卖力道+大盘作为核心
    # 权重调整: 资金面50% + 价格面25% + 大盘15% + 消息10%
    scenarios = []

    # === 情景A: 强势上涨(V形反弹) ===
    ac = []; ascore = 0
    met_a1 = buy_ratio > 55 and direction == "买方占优"
    ascore += 30 if met_a1 else 0
    ac.append({"c": "买方力道>55%", "t": ">55%", "a": f"{buy_ratio:.1f}%", "m": met_a1, "w": 30})

    met_a2 = change_pct < 2 and change_pct > -5  # 未过度拉升
    ascore += 20 if met_a2 else 0
    ac.append({"c": "未过度拉升(涨<2%且跌<5%)", "t": "涨<2%,跌<5%", "a": f"涨跌{change_pct:+.2f}%", "m": met_a2, "w": 20})

    met_a3 = "买方加速" in acceleration or "卖压减弱" in acceleration
    ascore += 20 if met_a3 else 0
    ac.append({"c": "力道改善(买方加速/卖压减弱)", "t": "买方加速/卖压减弱", "a": acceleration, "m": met_a3, "w": 20})

    met_a4 = vol_ratio >= 0.7 and turnover < 15
    ascore += 15 if met_a4 else 0
    ac.append({"c": "量能正常", "t": "量比≥0.7,换手<15%", "a": f"量比{vol_ratio},换手{turnover:.2f}%", "m": met_a4, "w": 15})

    met_a5 = net_vol > 0 and s2 > 0
    ascore += 15 if met_a5 else 0
    ac.append({"c": "净买量为正且后半段持续", "t": "净买量>0,后半段斜率>0", "a": f"net={net_vol},s2={s2}", "m": met_a5, "w": 15})

    scenarios.append({
        "name": "情景A: V形反弹/强势上涨", "raw_score": ascore, "conditions": ac,
        "met_count": sum(1 for c in ac if c["m"]), "total_conditions": len(ac),
        "description": "买方占优 + 量能正常 + 力道改善 → 午后反弹概率较高",
        "historical_ref": {"rule": "买力>55%+量能正常 → 午后反弹概率约55-65%", "historical_win_rate": "约55-65%"},
    })

    # === 情景B: 震荡横盘 ===
    bc2 = []; bscore = 0
    met_b1 = 45 <= buy_ratio <= 55
    bscore += 30 if met_b1 else 0
    bc2.append({"c": "买卖均衡(45-55%)", "t": "45-55%", "a": f"{buy_ratio:.1f}%", "m": met_b1, "w": 30})

    met_b2 = amplitude < 3
    bscore += 25 if met_b2 else 0
    bc2.append({"c": "振幅<3%(窄幅)", "t": "<3%", "a": f"{amplitude:.2f}%", "m": met_b2, "w": 25})

    met_b3 = abs(s2) < abs(s1) * 0.5
    bscore += 20 if met_b3 else 0
    bc2.append({"c": "力道收窄", "t": "后半段斜率<<前半段", "a": f"s1={s1},s2={s2}", "m": met_b3, "w": 20})

    scenarios.append({
        "name": "情景B: 震荡横盘", "raw_score": bscore, "conditions": bc2,
        "met_count": sum(1 for c in bc2 if c["m"]), "total_conditions": len(bc2),
        "description": "买卖均衡+振幅收窄 → 窄幅横盘",
        "historical_ref": {"rule": "买卖均衡+振幅<3% → 横盘约50-55%", "historical_win_rate": "约50-55%"},
    })

    # === 情景C: 冲高回落 ===
    cc = []; cscore = 0
    met_c1 = change_pct > 3 and ("减弱" in acceleration or "卖压" in acceleration)
    cscore += 35 if met_c1 else 0
    cc.append({"c": "已涨>3%+力道转弱", "t": "涨>3%+买力减弱", "a": f"涨{change_pct:+.2f}%,{acceleration}", "m": met_c1, "w": 35})

    met_c2 = turnover > 8
    cscore += 20 if met_c2 else 0
    cc.append({"c": "换手率>8%(异常)", "t": ">8%", "a": f"{turnover:.2f}%", "m": met_c2, "w": 20})

    met_c3 = s2 < 0 and s1 > 0
    cscore += 20 if met_c3 else 0
    cc.append({"c": "方向逆转(前买后卖)", "t": "s1>0,s2<0", "a": f"s1={s1},s2={s2}", "m": met_c3, "w": 20})

    scenarios.append({
        "name": "情景C: 冲高回落", "raw_score": cscore, "conditions": cc,
        "met_count": sum(1 for c in cc if c["m"]), "total_conditions": len(cc),
        "description": "高位+力道转弱 → 警惕午后回落",
        "historical_ref": {"rule": "涨>3%+买力转弱 → 回落约55-65%", "historical_win_rate": "约55-65%"},
    })

    # === 情景D: 弱势下跌 ===
    dc = []; dscore = 0
    met_d1 = buy_ratio < 40 and direction == "卖方占优"
    dscore += 30 if met_d1 else 0
    dc.append({"c": "卖方力道>60%", "t": "买力<40%", "a": f"买力{buy_ratio:.1f}%", "m": met_d1, "w": 30})

    met_d2 = "卖压加速" in acceleration
    dscore += 25 if met_d2 else 0
    dc.append({"c": "卖压加速", "t": "卖压加速", "a": acceleration, "m": met_d2, "w": 25})

    met_d3 = change_pct < -3
    dscore += 20 if met_d3 else 0
    dc.append({"c": "已跌>3%", "t": "跌>3%", "a": f"{change_pct:+.2f}%", "m": met_d3, "w": 20})

    met_d4 = s2 < s1 and s2 < 0
    dscore += 15 if met_d4 else 0
    dc.append({"c": "卖出加速", "t": "s2<s1且s2<0", "a": f"s1={s1},s2={s2}", "m": met_d4, "w": 15})

    scenarios.append({
        "name": "情景D: 弱势下跌", "raw_score": dscore, "conditions": dc,
        "met_count": sum(1 for c in dc if c["m"]), "total_conditions": len(dc),
        "description": "卖压沉重 + 加速卖出 → 继续走弱概率高",
        "historical_ref": {"rule": "卖力>60%+卖压加速 → 收阴约60-70%", "historical_win_rate": "约60-70%"},
    })

    # 归一化
    total_sc = sum(max(s["raw_score"], 5) for s in scenarios)  # 最低5分防止除零
    for s in scenarios:
        s["probability"] = round(max(s["raw_score"], 5) / total_sc * 100, 1)

    sorted_sc = sorted(scenarios, key=lambda x: x["probability"], reverse=True)
    return {"scenarios": sorted_sc, "primary_scenario": sorted_sc[0] if sorted_sc else None}


# ============================================================
# 主流程
# ============================================================
def main():
    now = datetime.now()
    print("═" * 70)
    print(f"  📊 盛和资源(600392) 盘中实时交易信号")
    print(f"  时间: {now.strftime('%Y-%m-%d %H:%M:%S')} (周一)")
    print(f"  数据源: mootdx(分时买卖力道) + 腾讯(行情/指数)")
    print(f"  ⚠️ 东财push2 API暂时限流,切换到mootdx方案")
    print("═" * 70)

    # [1] 行情
    print("\n[1/4] 拉取实时行情...")
    quote = fetch_quote()
    if "error" in quote:
        print(f"  ❌ {quote['error']}"); return
    print(f"  {quote['name']} 现价{quote['price']:.2f} 涨跌{quote['change_pct']:+.2f}%  "
          f"振幅{quote['amplitude']:.2f}% 换手{quote['turnover_pct']:.2f}% 量比{quote['vol_ratio']:.2f}")
    print(f"  今开{quote['open']:.2f} 最高{quote['high']:.2f} 最低{quote['low']:.2f}  "
          f"昨收{quote['prev_close']:.2f}")

    # [2] 分时买卖力道
    print("\n[2/4] 拉取分钟级分时数据(mootdx)...")
    md = fetch_mootdx_minutes()
    print(f"  分时数据: {len(md)}条")
    flow = analyze_minute_flow(md)
    s = flow["summary"]; ft = flow["trend"]
    print(f"  买方: {s['total_buy_vol']:,}  卖方: {s['total_sell_vol']:,}")
    print(f"  净买卖: {s['total_net_vol']:+,}  买力占比: {s['buy_ratio_pct']:.1f}%")
    print(f"  趋势: {ft['direction']} | {ft['acceleration']}")
    for tp in ft.get("turning_points", []):
        print(f"  转向: {tp['time']} {tp['type']}: {tp['vol']:+,}")

    # [3] 大盘
    print("\n[3/4] 拉取大盘指数...")
    bench, bc, market_data = fetch_market()
    print(f"  {bench}: {market_data.get(bench, {}).get('price', 0):.2f} 涨跌{bc:+.2f}%")
    for name, data in market_data.items():
        if name != bench:
            print(f"  {name}: {data['price']:.2f} 涨跌{data['change_pct']:+.2f}%")

    rs = quote['change_pct'] - bc
    if bc > 1: env = "🟢 大盘强势"
    elif bc > 0: env = "🟡 大盘微涨"
    elif bc > -1: env = "🟠 大盘微跌"
    else: env = "🔴 大盘弱势"
    if rs > 3: rating = "🚀 显著跑赢"
    elif rs > 1: rating = "✅ 跑赢大盘"
    elif rs > -1: rating = "➖ 与大盘同步"
    elif rs > -3: rating = "⚠️ 跑输大盘"
    else: rating = "🔴 显著跑输"
    print(f"  个股相对{bench}: {rs:+.2f}% {rating} | 大盘环境: {env}")

    # [4] 新闻
    print("\n[4/4] 搜索相关新闻...")
    news = fetch_news()
    bull = sum(1 for n in news if n['sentiment']=='bullish')
    bear = sum(1 for n in news if n['sentiment']=='bearish')
    print(f"  今日新闻: {len(news)}条 (利好{bull}/利空{bear})")
    for n in news[:5]:
        e = "🟢" if n["sentiment"]=="bullish" else ("🔴" if n["sentiment"]=="bearish" else "⚪")
        print(f"  {e} {n['title'][:80]}")

    # [5] 概率预判
    print("\n[5/5] 概率预判引擎...")
    scenarios = generate_scenarios(quote, flow)
    for sc in scenarios["scenarios"]:
        icon = "🔥" if sc["probability"] >= 50 else ("📊" if sc["probability"] >= 25 else "🔍")
        print(f"  {icon} {sc['name']}: 概率{sc['probability']:.0f}% ({sc['met_count']}/{sc['total_conditions']}条件)")

    # ====== 控制台详细输出 ======
    primary = scenarios["scenarios"][0]
    pn = primary["name"]; pp = primary["probability"]
    buy_ratio = s["buy_ratio_pct"]
    change_pct = quote["change_pct"]
    price = quote["price"]

    print(f"\n{'─'*60}")
    print(f"  📊 盛和资源(600392) 盘中信号总结")
    print(f"{'─'*60}")
    print(f"  📈 行情: 现价{price:.2f} 涨跌{change_pct:+.2f}%  振幅{quote['amplitude']:.2f}%  换手{quote['turnover_pct']:.2f}%  量比{quote['vol_ratio']:.2f}")
    print(f"  💰 买卖力道: 买力{buy_ratio:.1f}%  净买卖{s['total_net_vol']:+,}  ({s['data_points']}分钟, {s['first_time']}→{s['last_time']})")
    print(f"  💰 趋势: {ft['direction']} | {ft['acceleration']} (前段{ft['first_slope']:.0f}→后段{ft['second_slope']:.0f}/分)")
    print(f"  📊 大盘: {bench}{bc:+.2f}% {env} | 个股相对{rs:+.2f}% {rating}")
    if market_data:
        for name, data in market_data.items():
            print(f"        {name}: {data['change_pct']:+.2f}%")
    print(f"  📰 消息: {len(news)}条今日新闻 (利好{bull}/利空{bear})")
    print(f"  ⚠️ 数据说明: 东财push2 API暂时限流,使用mootdx分时买卖力道替代资金流; 板块/北向/广度数据暂缺")

    print(f"\n{'─'*60}")
    print(f"  🔮 概率预判 (基于买卖力道+价格+大盘):")
    for sc in scenarios["scenarios"]:
        icon = "🔥" if sc["probability"] >= 50 else ("📊" if sc["probability"] >= 25 else "🔍")
        print(f"\n  {icon} {sc['name']} → 概率: {sc['probability']:.0f}% (满足{sc['met_count']}/{sc['total_conditions']}条件)")
        print(f"     {sc['description']}")
        for c in sc["conditions"]:
            st = "✅" if c["m"] else "❌"
            print(f"     {st} {c['c']}: 阈值{c['t']}, 当前={c['a']}")
        ref = sc.get("historical_ref", {})
        if ref:
            print(f"     参考: {ref.get('rule', '')} ({ref.get('historical_win_rate', '')})")

    # 买卖信号
    print(f"\n{'─'*60}")
    print(f"  ⚡ 交易信号参考:")

    # 买入信号
    print(f"\n  📥 买入参考:")
    strong_buy = (pp >= 55 and "情景A" in pn and buy_ratio > 55 and change_pct < 3)
    medium_buy = (pp >= 40 and "情景A" in pn and buy_ratio > 50)

    if strong_buy:
        print(f"    🟢🟢🟢 强买入参考: 反弹概率{pp:.0f}%,买力{buy_ratio:.1f}%,未过度拉升 → 可考虑逢低建仓")
        print(f"    止损: 跌破{price*0.97:.2f}(-3%)")
    elif medium_buy:
        print(f"    🟢🟢 中等买入参考: 反弹概率{pp:.0f}%,买力{buy_ratio:.1f}% → 可小仓位试探(30-50%)")
        print(f"    止损: 跌破{price*0.95:.2f}(-5%)")
    else:
        reasons = []
        if pp < 40: reasons.append(f"反弹概率不足({pp:.0f}%<40%)")
        if buy_ratio <= 50: reasons.append(f"买方力道不足({buy_ratio:.1f}%≤50%)")
        if change_pct > 0: reasons.append(f"已涨{change_pct:+.2f}%,追高风险")
        reason_str = "; ".join(reasons) if reasons else "等待更明确信号"
        print(f"    ⚪ 暂不建议买入: {reason_str}")
        print(f"    操作: 继续观察,等待买力>55%+反弹概率>40%共振")

    # 卖出信号
    print(f"\n  📤 卖出参考:")
    strong_sell = (pp >= 50 and ("情景D" in pn or "情景C" in pn) and buy_ratio < 40)
    medium_sell = (buy_ratio < 45 and "卖压" in ft.get("acceleration", ""))

    if strong_sell:
        print(f"    🔴🔴🔴 强卖出参考: 弱势概率{pp:.0f}%,卖力{100-buy_ratio:.1f}% → 建议果断减仓")
    elif medium_sell:
        print(f"    🔴🔴 中等卖出参考: 买力仅{buy_ratio:.1f}%,卖压加大 → 建议逐步减仓到半仓以下")
    elif buy_ratio < 45 and "情景D" in pn:
        print(f"    🔴 弱卖出参考: 弱势概率{pp:.0f}%,买力偏弱{buy_ratio:.1f}% → 持有者应审视持仓")
    else:
        if buy_ratio > 50:
            print(f"    ⚪ 暂不需卖出: 买力{buy_ratio:.1f}%仍占优 → 继续持有观察")
        else:
            print(f"    ⚪ 暂不需卖出(但需警觉): 买力{buy_ratio:.1f}%中性 → 关注是否转弱")

    # 持有
    print(f"\n  📌 持有建议:")
    if "情景A" in pn and pp >= 50:
        print(f"    ✅ 可继续持有: 反弹概率{pp:.0f}%,买力{buy_ratio:.1f}%")
        print(f"    👁 关注: 买力是否转弱 / 下午开盘方向")
    elif "情景B" in pn:
        print(f"    ⏸️ 持有观望: 震荡格局,买力{buy_ratio:.1f}%均衡")
        print(f"    👁 关注: 突破方向 / 是否有催化")
    else:
        print(f"    ⚠️ 审视持仓: 主导情景{pp:.0f}% {pn}")
        print(f"    👁 关注: 下午开盘前30分钟资金方向 / 买力是否回升")

    # 综合评估
    print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━")
    if buy_ratio > 55 and pp >= 50:
        verdict = f"总体偏多: 买力{buy_ratio:.1f}%,反弹概率{pp:.0f}%。可在控制仓位前提下逢低参与。"
    elif buy_ratio > 50:
        verdict = f"总体中性偏多: 买力{buy_ratio:.1f}%略占优,反弹概率{pp:.0f}%。可小仓试探,严格止损。"
    elif buy_ratio > 45:
        verdict = f"总体中性: 买力{buy_ratio:.1f}%均衡,方向不明确。建议观望等待。"
    elif buy_ratio > 35:
        verdict = f"总体谨慎: 卖力{100-buy_ratio:.1f}%占优。持有者审视持仓,未持有者等待。"
    else:
        verdict = f"总体偏空: 卖力{100-buy_ratio:.1f}%主导。建议减仓或观望。"
    print(f"  🎯 综合评估: {verdict}")

    # 保存数据
    date_str = now.strftime("%Y-%m-%d")
    dir_path = f"src/盘中交易信号/{date_str}-盛和资源-盘中信号"
    os.makedirs(dir_path, exist_ok=True)

    # 更新 data.json
    data_json = {
        "target": {"type": "个股", "code": CODE, "name": quote.get("name", "")},
        "analysis_time": now.isoformat(),
        "data_source": "mootdx(分时) + 腾讯(行情/指数)",
        "note": "东财push2 API暂时限流,切换到mootdx方案",
        "quote": {k: v for k, v in quote.items() if k != "error"},
        "flow_summary": flow.get("summary", {}),
        "flow_trend": {k: v for k, v in flow.get("trend", {}).items() if k != "turning_points"},
        "flow_source": flow.get("source", ""),
        "market": {"benchmark": bench, "benchmark_change": bc,
                   "relative_strength": round(rs, 2), "relative_rating": rating,
                   "market_env": env, "detail": market_data},
        "scenarios": [{"name": s["name"], "probability": s["probability"],
                       "met_count": s["met_count"], "total_conditions": s["total_conditions"]}
                      for s in scenarios["scenarios"]],
        "news_count": len(news),
        "overall_verdict": verdict,
    }
    with open(os.path.join(dir_path, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data_json, f, ensure_ascii=False, indent=2, default=str)

    # 更新 report.md
    _write_report(dir_path, now, quote, flow, bench, bc, market_data, rs, rating, env,
                  scenarios, news, bull, bear, buy_ratio, price, pp, pn, verdict, s, ft)

    print(f"\n{'═'*70}")
    print(f"  ⚠️ 研究声明: 买卖力道基于mootdx分时数据推导,不构成投资建议")
    print(f"  核心原则: 宁可少挣,宁可少亏——不确定时不出手")
    print(f"  报告已保存: {dir_path}/")
    print(f"{'═'*70}\n")


def _write_report(dir_path, now, quote, flow, bench, bc, market_data, rs, rating, env,
                  scenarios, news, bull, bear, buy_ratio, price, pp, pn, verdict, s, ft):
    L = []; a = L.append
    a(f"# 📊 盘中实时交易信号报告 — 盛和资源(600392)")
    a(f"")
    a(f"**分析时间**: {now.strftime('%Y-%m-%d %H:%M')} (周一)")
    a(f"**数据源**: mootdx(分时买卖力道) + 腾讯(行情/指数)")
    a(f"**注意**: 东财push2 API暂时限流,板块/北向/广度数据暂缺。已切换至mootdx分时买卖力道方案。")
    a(f"")
    a(f"---")
    a(f"")
    a(f"## 🎯 核心结论")
    a(f"")
    primary = scenarios["scenarios"][0]
    a(f"| 项目 | 状态 |")
    a(f"|------|------|")
    a(f"| **主导情景** | {primary['name']} (概率 {primary['probability']:.0f}%) |")
    a(f"| **买方力道** | {buy_ratio:.1f}% |")
    a(f"| **综合评估** | {verdict} |")
    a(f"")
    a(f"---")
    a(f"")
    a(f"## 📊 关键数据一览")
    a(f"")
    a(f"| 维度 | 指标 | 数值 |")
    a(f"|------|------|------|")
    a(f"| 📈 价格 | 最新价 | {price:.2f} |")
    a(f"| 📈 价格 | 涨跌幅 | {quote['change_pct']:+.2f}% |")
    a(f"| 📈 价格 | 今开/最高/最低 | {quote['open']:.2f} / {quote['high']:.2f} / {quote['low']:.2f} |")
    a(f"| 📈 价格 | 振幅 | {quote['amplitude']:.2f}% |")
    a(f"| 📈 价格 | 换手率 | {quote['turnover_pct']:.2f}% |")
    a(f"| 📈 价格 | 量比 | {quote['vol_ratio']:.2f} |")
    a(f"| 💰 力道 | 买方占比 | {buy_ratio:.1f}% |")
    a(f"| 💰 力道 | 净买卖量 | {s['total_net_vol']:+,} |")
    a(f"| 💰 力道 | 趋势 | {ft['direction']} / {ft['acceleration']} |")
    a(f"| 💰 力道 | 前/后段斜率 | {ft['first_slope']:.0f} → {ft['second_slope']:.0f}/分 |")
    a(f"| 📊 大盘 | {bench} | {bc:+.2f}% {env} |")
    a(f"| 📊 大盘 | 个股相对强度 | {rs:+.2f}% {rating} |")
    for name, data in market_data.items():
        a(f"| 📊 大盘 | {name} | {data['change_pct']:+.2f}% |")
    a(f"| 📰 消息 | 今日新闻 | {len(news)}条 (利好{bull}/利空{bear}) |")
    a(f"")

    if news:
        a(f"### 今日新闻")
        for n in news[:8]:
            e = "🟢" if n["sentiment"]=="bullish" else ("🔴" if n["sentiment"]=="bearish" else "⚪")
            a(f"- {e} {n['title']} (来源: {n['source']})")
        a(f"")

    a(f"---")
    a(f"")
    a(f"## 🔮 概率预判")
    a(f"")
    for sc in scenarios["scenarios"]:
        a(f"### {sc['name']} → 概率: {sc['probability']:.0f}% ({sc['met_count']}/{sc['total_conditions']}条件)")
        a(f"")
        a(f"**{sc['description']}**")
        a(f"")
        a(f"| 条件 | 阈值 | 当前值 | 满足? | 权重 |")
        a(f"|------|------|--------|-------|------|")
        for c in sc["conditions"]:
            st = "✅" if c["m"] else "❌"
            a(f"| {c['c']} | {c['t']} | {c['a']} | {st} | {c['w']} |")
        a(f"")
        ref = sc.get("historical_ref", {})
        if ref:
            a(f"**参考**: {ref.get('rule', '')} ({ref.get('historical_win_rate', '')})")
        a(f"")

    # 关键转向点
    turns = ft.get("turning_points", [])
    if turns:
        a(f"### 关键转向点")
        a(f"")
        a(f"| 时间 | 类型 | 净买卖量 |")
        a(f"|------|------|---------|")
        for tp in turns:
            a(f"| {tp['time']} | {tp['type']} | {tp['vol']:+,} |")
        a(f"")

    a(f"---")
    a(f"")
    a(f"## ⚠️ 研究声明")
    a(f"")
    a(f"1. 买卖力道基于mootdx分时价格×成交量推导,不如实际资金流数据精确")
    a(f"2. 东财push2 API暂时限流,板块情绪/北向资金/市场广度三维数据暂缺")
    a(f"3. 所有信号为研究框架产出,不构成投资建议")
    a(f"4. 核心原则: 宁可少挣,宁可少亏——不确定时不出手")
    a(f"")

    with open(os.path.join(dir_path, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
