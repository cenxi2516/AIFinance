#!/usr/bin/env python3
"""
A股ETF资金流全景扫描器 V1.1 (修复版)
扫描日期: 2026-07-08
改进: 使用 push2 clist 批量获取当日资金流 + 腾讯实时行情
"""
import time, random, json, requests, urllib.request
from datetime import datetime
from collections import defaultdict

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.5
_em_last_call = [0.0]


def em_get(url, params=None, headers=None, timeout=20):
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last_call[0] = time.time()


# ============================================================
# 核心 ETF 池
# ============================================================
CORE_ETFS = {
    "510050": {"name": "上证50ETF",       "cat": "宽基", "style": "大盘价值"},
    "510300": {"name": "沪深300ETF",      "cat": "宽基", "style": "大盘均衡"},
    "510500": {"name": "中证500ETF",      "cat": "宽基", "style": "中盘成长"},
    "159915": {"name": "创业板ETF",       "cat": "宽基", "style": "成长"},
    "588000": {"name": "科创50ETF",       "cat": "宽基", "style": "硬科技"},
    "510330": {"name": "沪深300ETF华夏",  "cat": "宽基", "style": "大盘均衡"},
    "159845": {"name": "中证1000ETF",     "cat": "宽基", "style": "小盘成长"},
    "512880": {"name": "证券ETF",         "cat": "行业", "style": "券商"},
    "512480": {"name": "半导体ETF",       "cat": "行业", "style": "半导体"},
    "159995": {"name": "芯片ETF",         "cat": "行业", "style": "芯片"},
    "516160": {"name": "新能源ETF",       "cat": "行业", "style": "新能源"},
    "512660": {"name": "军工ETF",         "cat": "行业", "style": "军工"},
    "512690": {"name": "酒ETF",           "cat": "行业", "style": "消费"},
    "512010": {"name": "医药ETF",         "cat": "行业", "style": "医药"},
    "516510": {"name": "云计算ETF",       "cat": "行业", "style": "云计算"},
    "159869": {"name": "游戏ETF",         "cat": "行业", "style": "游戏"},
    "510880": {"name": "红利ETF",         "cat": "策略", "style": "红利防御"},
    "512890": {"name": "红利低波ETF",     "cat": "策略", "style": "红利低波"},
    "513050": {"name": "中概互联ETF",     "cat": "跨境", "style": "中概互联"},
    "513100": {"name": "纳指ETF",         "cat": "跨境", "style": "纳斯达克"},
    "518880": {"name": "黄金ETF",         "cat": "商品", "style": "黄金避险"},
}


# ============================================================
# 方法1: 腾讯实时行情 (首选，不封IP)
# ============================================================
def tencent_etf_quotes(codes: list) -> dict:
    prefixed = []
    for c in codes:
        if c.startswith(("5", "6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
    except Exception as e:
        print(f"  [ERR] 腾讯行情: {e}")
        return {}

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name":         vals[1],
            "price":        float(vals[3]) if vals[3] else 0,
            "last_close":   float(vals[4]) if vals[4] else 0,
            "open":         float(vals[5]) if vals[5] else 0,
            "change_pct":   float(vals[32]) if vals[32] else 0,
            "high":         float(vals[33]) if vals[33] else 0,
            "low":          float(vals[34]) if vals[34] else 0,
            "amount_wan":   float(vals[37]) if vals[37] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm":       float(vals[39]) if vals[39] else 0,
            "mcap_yi":      float(vals[44]) if vals[44] else 0,
            "vol_ratio":    float(vals[49]) if vals[49] else 0,
        }
    return result


# ============================================================
# 方法2: push2 clist 批量获取当日主力资金流 (一次请求获取全部ETF)
# ============================================================
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

def batch_etf_day_fund_flow(top_n: int = 500) -> dict:
    """批量获取全市场ETF当日行情+主力资金流 (一次API调用)"""
    params = {
        "pn": "1", "pz": str(min(top_n, 500)), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:1+t:1",
        "fields": "f2,f3,f4,f12,f14,f20,f21,f62,f66,f72,f8,f10",
        "st": "f20",  # 按总市值排序
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    try:
        r = em_get(PUSH2_CLIST, params=params, headers=headers, timeout=20)
        d = r.json()
    except Exception as e:
        print(f"  [ERR] clist请求失败: {e}")
        return {}

    items = d.get("data", {}).get("diff", []) or []
    result = {}
    for it in items:
        code = it.get("f12", "")
        result[code] = {
            "name": it.get("f14", ""),
            "price": it.get("f2") or 0,
            "change_pct": it.get("f3") or 0,
            "mcap": it.get("f20") or 0,
            "float_mcap": it.get("f21") or 0,
            "main_net": it.get("f62") or 0,      # 当日主力净流入
            "super_large_net": it.get("f66") or 0, # 当日超大单净流入
            "large_net": it.get("f72") or 0,       # 当日大单净流入
            "turnover_pct": it.get("f8") or 0,
            "vol_ratio": it.get("f10") or 0,
        }
    return result


# ============================================================
# 方法3: push2his 获取历史日级资金流 (带重试)
# ============================================================
PUSH2_HIS = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

PERIOD_DAYS = {"1w": 5, "2w": 10, "1m": 22, "3m": 66, "6m": 125}

def etf_historical_fund_flow(code: str, max_retries: int = 2) -> dict:
    """获取ETF历史日级资金流 (带重试)"""
    secid = f"1.{code}" if code.startswith(("5", "6", "9")) else f"0.{code}"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "lmt": "250",
    }
    headers = {"Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}

    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait = 2.0 * attempt + random.uniform(0.5, 1.5)
                # print(f"    重试 {code} (第{attempt}次, 等待{wait:.1f}s)...")
                time.sleep(wait)
            r = em_get(PUSH2_HIS, params=params, headers=headers, timeout=20)
            d = r.json()
            klines = d.get("data", {}).get("klines", []) or []
            daily = []
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 7:
                    daily.append({
                        "date": parts[0],
                        "main_net": float(parts[1]) if parts[1] != "-" else 0,
                        "small_net": float(parts[2]) if parts[2] != "-" else 0,
                        "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                        "large_net": float(parts[4]) if parts[4] != "-" else 0,
                        "super_net": float(parts[5]) if parts[5] != "-" else 0,
                    })

            result = {}
            if daily:
                result["_latest_date"] = daily[-1]["date"]
                result["_total_days"] = len(daily)

            for period, days in PERIOD_DAYS.items():
                window = daily[-min(days, len(daily)):] if daily else []
                result[period] = {
                    "main_net": sum(d["main_net"] for d in window),
                    "super_large_net": sum(d["super_net"] for d in window),
                    "large_net": sum(d["large_net"] for d in window),
                    "mid_net": sum(d["mid_net"] for d in window),
                    "small_net": sum(d["small_net"] for d in window),
                    "days": len(window),
                }
            return result
        except Exception as e:
            if attempt < max_retries:
                continue
            # print(f"  [SKIP] 历史资金流 {code}: {e}")
            pass
    return {}


# ============================================================
# 综合收集: 当日(push2 clist) + 历史(push2his) + 实时行情(Tencent)
# ============================================================
def collect_all_data() -> dict:
    """三路数据综合收集"""
    all_codes = list(CORE_ETFS.keys())
    print(f"核心池 ETF 总数: {len(all_codes)}")

    # Step 1: 批量获取当日资金流 (一次请求)
    print("\n[Step 1] 批量获取全市场ETF当日行情+资金流...")
    all_etf_day = batch_etf_day_fund_flow(500)
    print(f"  获取到 {len(all_etf_day)} 只ETF当日数据")

    # Step 2: 腾讯实时行情 (宽基+行业核心)
    print("\n[Step 2] 腾讯实时行情...")
    quotes = tencent_etf_quotes(all_codes)
    print(f"  获取到 {len(quotes)} 只ETF实时行情")

    # Step 3: 历史日级资金流 (逐只，带重试)
    print("\n[Step 3] 历史日级资金流 (逐只获取，带重试)...")
    hist_data = {}
    for i, code in enumerate(all_codes):
        info = CORE_ETFS[code]
        hist = etf_historical_fund_flow(code, max_retries=2)
        if hist and hist.get("_total_days", 0) > 0:
            hist_data[code] = hist
            latest = hist.get("_latest_date", "?")
            print(f"  ✓ [{i+1:2d}/{len(all_codes)}] {code} {info['name']:<14s} "
                  f"({hist['_total_days']}天, 最新={latest})")
        else:
            print(f"  ✗ [{i+1:2d}/{len(all_codes)}] {code} {info['name']:<14s} 历史数据获取失败")
        time.sleep(0.3)
    print(f"  历史数据覆盖: {len(hist_data)}/{len(all_codes)}")

    return {
        "day_data": all_etf_day,      # 全市场当日行情+资金流
        "quotes": quotes,              # 核心ETF腾讯实时行情
        "hist_data": hist_data,        # 核心ETF历史资金流
    }


# ============================================================
# 分析引擎
# ============================================================
def analyze(data: dict) -> dict:
    """基于收集数据进行多维分析"""
    day_data = data["day_data"]
    quotes = data["quotes"]
    hist_data = data["hist_data"]

    analysis = {
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "实时行情": {},
        "当日资金流排名": [],
        "宽基风格对比": {},
        "行业轮动": {},
        "多周期趋势": {},
        "增量资金检测": {},
        "综合研判": [],
    }

    # ━━━ 1. 实时行情 ━━━
    for code, info in CORE_ETFS.items():
        q = quotes.get(code, {})
        d = day_data.get(code, {})
        analysis["实时行情"][code] = {
            "name": info["name"],
            "cat": info["cat"],
            "style": info["style"],
            "price": q.get("price", d.get("price", 0)),
            "change_pct": q.get("change_pct", d.get("change_pct", 0)),
            "mcap_yi": q.get("mcap_yi", d.get("mcap", 0) / 1e8 if d.get("mcap", 0) else 0),
            "turnover_pct": q.get("turnover_pct", d.get("turnover_pct", 0)),
            "vol_ratio": q.get("vol_ratio", d.get("vol_ratio", 0)),
            "amount_wan": q.get("amount_wan", 0),
            "pe_ttm": q.get("pe_ttm", 0),
        }

    # ━━━ 2. 当日资金流排名 (基于 push2 clist 批量数据) ━━━
    day_ranking = []
    for code, info in CORE_ETFS.items():
        d = day_data.get(code, {})
        main_net = d.get("main_net", 0)
        super_net = d.get("super_large_net", 0)
        large_net = d.get("large_net", 0)
        day_ranking.append({
            "code": code,
            "name": info["name"],
            "cat": info["cat"],
            "style": info["style"],
            "main_net": main_net,
            "super_large_net": super_net,
            "large_net": large_net,
        })
    day_ranking.sort(key=lambda x: x["main_net"], reverse=True)
    analysis["当日资金流排名"] = day_ranking

    # ━━━ 3. 多周期聚合 (当日 + 历史) ━━━
    periods = ["1w", "2w", "1m", "3m", "6m"]
    multi_period = {}
    for code in CORE_ETFS:
        mp = {}
        # 当日
        dd = day_data.get(code, {})
        mp["today"] = {
            "main_net": dd.get("main_net", 0),
            "super_large_net": dd.get("super_large_net", 0),
            "large_net": dd.get("large_net", 0),
        }
        # 历史周期
        hist = hist_data.get(code, {})
        for period in periods:
            hp = hist.get(period, {})
            mp[period] = {
                "main_net": hp.get("main_net", 0) if hp else 0,
                "super_large_net": hp.get("super_large_net", 0) if hp else 0,
                "days": hp.get("days", 0) if hp else 0,
            }
        multi_period[code] = mp
    analysis["多周期趋势"] = multi_period

    # ━━━ 4. 宽基风格对比 ━━━
    style_groups = {
        "large_cap":  ("大盘蓝筹", ["510050", "510300"]),
        "small_cap":  ("中小盘",   ["510500", "159845"]),
        "growth":     ("成长科技", ["588000", "159915"]),
        "value":      ("价值防御", ["510050", "510880"]),
        "tech":       ("科技成长", ["588000", "159995", "512480"]),
        "traditional":("传统行业", ["510050", "512880", "512690"]),
    }

    for gname, (glabel, codes) in style_groups.items():
        group_analysis = {}
        for period in ["today", "1w", "1m"]:
            net = sum(
                multi_period.get(c, {}).get(period, {}).get("main_net", 0)
                for c in codes
            )
            group_analysis[period] = net
        analysis["宽基风格对比"][gname] = {
            "label": glabel,
            "codes": codes,
            "flows": group_analysis,
        }

    # ━━━ 5. 增量资金检测 ━━━
    big_four = ["510050", "510300", "510500", "159915"]
    for period in ["today", "1w", "1m"]:
        flows = [
            multi_period.get(c, {}).get(period, {}).get("main_net", 0)
            for c in big_four
        ]
        total = sum(flows)
        all_in = all(f > 0 for f in flows)
        if all_in and total > 1e8:
            signal = "🚀 增量资金入场"
        elif all_in and total > 0:
            signal = "✅ 四大宽基同向流入"
        elif total > 1e8:
            signal = "✅ 净流入(非同步)"
        elif total > 0:
            signal = "➖ 小幅净流入"
        elif total > -1e8:
            signal = "➖ 小幅净流出"
        elif total > -5e8:
            signal = "⚠️ 净流出"
        else:
            signal = "🔴 显著流出"
        analysis["增量资金检测"][period] = {
            "total": total,
            "all_inflow": all_in,
            "signal": signal,
            "details": {c: flows[i] for i, c in enumerate(big_four)},
        }

    # ━━━ 6. 行业ETF轮动 ━━━
    industry_codes = [c for c, info in CORE_ETFS.items() if info["cat"] in ("行业", "主题")]
    ind_flows = []
    for code in industry_codes:
        info = CORE_ETFS[code]
        main_1w = multi_period.get(code, {}).get("1w", {}).get("main_net", 0)
        main_today = multi_period.get(code, {}).get("today", {}).get("main_net", 0)
        ind_flows.append({
            "code": code,
            "name": info["name"],
            "style": info["style"],
            "main_net_1w": main_1w,
            "main_net_today": main_today,
        })
    ind_flows.sort(key=lambda x: x["main_net_1w"], reverse=True)

    inf_count = sum(1 for f in ind_flows if f["main_net_1w"] > 0)
    total_ind = len(ind_flows)
    if inf_count >= total_ind * 0.7:
        rot_sig = "🔥 行业全面流入——情绪高涨"
    elif inf_count <= total_ind * 0.3:
        rot_sig = "❄️ 行业全面流出——情绪低迷"
    else:
        top3 = [f["name"] for f in ind_flows[:3]]
        bot3 = [f["name"] for f in ind_flows[-3:]]
        rot_sig = f"🔄 轮动分化: {', '.join(bot3)} → {', '.join(top3)}"

    analysis["行业轮动"] = {
        "total": total_ind,
        "inflow_count": inf_count,
        "outflow_count": total_ind - inf_count,
        "rotation_signal": rot_sig,
        "top_inflow": ind_flows[:5],
        "top_outflow": ind_flows[-5:][::-1],
    }

    # ━━━ 7. 综合研判 ━━━
    signals = []

    # 增量资金判断
    inc = analysis["增量资金检测"]
    total_wide_1w = inc.get("1w", {}).get("total", 0)
    if inc.get("1w", {}).get("all_inflow"):
        signals.append("🟢 四大宽基同向流入——增量资金确认入场")
    elif total_wide_1w > 1e8:
        signals.append("🟡 宽基整体净流入但未形成四线合力")
    elif total_wide_1w > -1e8:
        signals.append("➖ 宽基资金基本平衡，无明确方向信号")
    else:
        signals.append("🔴 宽基资金整体流出，市场承压")

    # 风格判断
    growth_1w = analysis["宽基风格对比"]["growth"]["flows"].get("1w", 0)
    value_1w = analysis["宽基风格对比"]["value"]["flows"].get("1w", 0)
    if growth_1w > value_1w and growth_1w > 1e8:
        signals.append("🟢 资金偏好成长/科技，风险偏好回升")
    elif value_1w > growth_1w and value_1w > 1e8:
        signals.append("🟡 资金偏向价值/防御，避险情绪占优")
    elif growth_1w > value_1w:
        signals.append("🟡 成长略优于价值但幅度有限")
    else:
        signals.append("🟡 价值略优于成长，市场偏谨慎")

    # 行业轮动判断
    if "全面流入" in rot_sig:
        signals.append("🟢 行业ETF全面流入，板块共振向上")
    elif "全面流出" in rot_sig:
        signals.append("🔴 行业ETF全面流出，缺乏赚钱效应")
    else:
        signals.append("🟡 行业轮动分化，结构性行情为主")

    # 背离检测
    tech_1w = analysis["宽基风格对比"]["tech"]["flows"].get("1w", 0)
    trad_1w = analysis["宽基风格对比"]["traditional"]["flows"].get("1w", 0)
    if tech_1w > 1e8 and trad_1w < -1e8:
        signals.append("⚠️ 科技大幅流入+传统大幅流出，风格剧烈切换中")
    elif tech_1w < -1e8 and trad_1w > 1e8:
        signals.append("⚠️ 科技大幅流出+传统流入，防御模式启动")

    # 资金面与行情背离
    total_day_net = sum(f["main_net"] for f in day_ranking)
    up_count = sum(1 for code, q in analysis["实时行情"].items() if q["change_pct"] > 0)
    down_count = sum(1 for code, q in analysis["实时行情"].items() if q["change_pct"] < 0)
    if total_day_net > 1e8 and down_count > up_count:
        signals.append("⚠️ ETF资金流入但价格多数下跌——可能是托底资金而非进攻")
    elif total_day_net < -1e8 and up_count > down_count:
        signals.append("⚠️ ETF资金流出但价格多数上涨——反弹减仓信号")

    analysis["综合研判"] = signals
    return analysis


# ============================================================
# 打印报告
# ============================================================
def print_report(analysis: dict):
    print()
    print("=" * 80)
    print("  📊 A股ETF资金流全景报告")
    print(f"  生成时间: {analysis['scan_time']}")
    print("  数据来源: 腾讯财经(实时行情) + 东方财富push2(当日资金流) + push2his(历史资金流)")
    print("=" * 80)

    # ━━━ PART 1: 核心宽基ETF实时行情 ━━━
    print("\n" + "─" * 70)
    print("  🏛️  核心宽基ETF实时行情")
    print("─" * 70)
    wide_codes = ["510050", "510300", "510500", "588000", "159915", "159845"]
    print(f"  {'代码':<8s} {'名称':<16s} {'价格':>8s} {'涨跌幅':>8s} {'市值(亿)':>10s} {'换手率':>8s} {'量比':>6s}")
    print(f"  {'─'*8} {'─'*16} {'─'*8} {'─'*8} {'─'*10} {'─'*8} {'─'*6}")
    for code in wide_codes:
        q = analysis["实时行情"].get(code, {})
        if q:
            color = "🔴" if q["change_pct"] < 0 else ("🟢" if q["change_pct"] > 0 else "⚪")
            print(f"  {color} {code:<6s} {q['name']:<16s} {q['price']:>8.3f} {q['change_pct']:>+7.2f}% "
                  f"{q['mcap_yi']:>10.2f} {q['turnover_pct']:>7.2f}% {q['vol_ratio']:>6.2f}")

    # ━━━ PART 2: 当日资金流排名 ━━━
    print("\n" + "─" * 70)
    print("  💰 核心ETF当日主力资金流排名")
    print("─" * 70)
    ranking = analysis["当日资金流排名"]
    print(f"  {'排名':<4s} {'类别':<6s} {'名称':<16s} {'风格':<10s} {'主力净流入':>12s} {'超大单':>10s}")
    print(f"  {'─'*4} {'─'*6} {'─'*16} {'─'*10} {'─'*12} {'─'*10}")
    for i, etf in enumerate(ranking):
        direction = "🔥" if etf["main_net"] > 0 else "💧"
        print(f"  {direction} {i+1:<2d} [{etf['cat']:<4s}] {etf['name']:<16s} "
              f"{etf['style']:<10s} {etf['main_net']/1e8:>+10.2f}亿 {etf['super_large_net']/1e8:>+8.2f}亿")

    total_day = sum(f["main_net"] for f in ranking)
    inflow_count_day = sum(1 for f in ranking if f["main_net"] > 0)
    print(f"  {'─'*70}")
    print(f"  当日合计: {total_day/1e8:+.2f}亿 | 流入{inflow_count_day}只 / 流出{len(ranking)-inflow_count_day}只")

    # ━━━ PART 3: 宽基风格对比 ━━━
    print("\n" + "=" * 70)
    print("  🏛️  宽基ETF风格对比分析")
    print("=" * 70)

    sg = analysis["宽基风格对比"]
    comparisons = [
        ("大盘 vs 中小盘", "large_cap", "small_cap",
         "大盘蓝筹占优 (防御)", "中小盘占优 (进攻)"),
        ("成长 vs 价值", "growth", "value",
         "成长占优 (风险偏好高)", "价值占优 (避险)"),
        ("科技 vs 传统", "tech", "traditional",
         "科技成长驱动", "传统估值修复驱动"),
    ]

    for label, g1, g2, g1_win, g2_win in comparisons:
        g1_1w = sg[g1]["flows"].get("1w", 0)
        g2_1w = sg[g2]["flows"].get("1w", 0)
        verdict = g1_win if g1_1w > g2_1w else g2_win
        print(f"\n  📊 {label} (近1周):")
        print(f"     {sg[g1]['label']}={g1_1w/1e8:+.2f}亿 vs "
              f"{sg[g2]['label']}={g2_1w/1e8:+.2f}亿 → {verdict}")

        # 近1月趋势
        g1_1m = sg[g1]["flows"].get("1m", 0)
        g2_1m = sg[g2]["flows"].get("1m", 0)
        print(f"     近1月: {sg[g1]['label']}={g1_1m/1e8:+.2f}亿 vs "
              f"{sg[g2]['label']}={g2_1m/1e8:+.2f}亿")

    # ━━━ PART 4: 增量资金检测 ━━━
    print(f"\n  🚦 增量资金检测 (四大宽基: 510050+510300+510500+159915):")
    inc = analysis["增量资金检测"]
    for period in ["today", "1w", "1m"]:
        p = inc.get(period, {})
        details_str = " | ".join(f"{c}={v/1e8:+.2f}亿" for c, v in p.get("details", {}).items())
        print(f"     {period:>5s}: {p.get('signal','?')} (合计={p.get('total',0)/1e8:+.2f}亿) [{details_str}]")

    # ━━━ PART 5: 行业ETF轮动 ━━━
    rot = analysis["行业轮动"]
    print("\n" + "─" * 70)
    print(f"  🏭  行业ETF资金轮动 (近1周)")
    print("─" * 70)
    print(f"  轮动信号: {rot['rotation_signal']}")
    print(f"  流入: {rot['inflow_count']}只 / 流出: {rot['outflow_count']}只 / 总计: {rot['total']}只")
    print(f"\n  🔥 流入 TOP 5:")
    for etf in rot["top_inflow"]:
        print(f"    {etf['name']:<14s} ({etf['style']:<8s}): 1w={etf['main_net_1w']/1e8:>+8.2f}亿 "
              f"今日={etf['main_net_today']/1e8:>+8.2f}亿")
    print(f"\n  💧 流出 TOP 5:")
    for etf in rot["top_outflow"]:
        print(f"    {etf['name']:<14s} ({etf['style']:<8s}): 1w={etf['main_net_1w']/1e8:>+8.2f}亿 "
              f"今日={etf['main_net_today']/1e8:>+8.2f}亿")

    # ━━━ PART 6: 核心ETF多周期资金流一览 ━━━
    print("\n" + "─" * 70)
    print("  📅 核心ETF多周期资金流一览")
    print("─" * 70)
    mp = analysis["多周期趋势"]
    periods_display = ["today", "1w", "2w", "1m", "3m"]
    # 表头
    header = f"  {'代码':<8s} {'名称':<14s}"
    for p in periods_display:
        header += f" {p:>10s}"
    print(header)
    print(f"  {'─'*8} {'─'*14}" + f" {'─'*10}" * len(periods_display))

    for code in CORE_ETFS:
        info = CORE_ETFS[code]
        flows = mp.get(code, {})
        row = f"  {code:<8s} {info['name']:<14s}"
        for p in periods_display:
            net = flows.get(p, {}).get("main_net", 0)
            row += f" {net/1e8:>+10.2f}"
        print(row)

    # ━━━ PART 7: 综合研判 ━━━
    print("\n" + "=" * 70)
    print("  🧠  盘面综合研判")
    print("=" * 70)
    for sig in analysis["综合研判"]:
        print(f"  {sig}")

    # 资金流向TOP概念
    print(f"\n  📌 核心发现:")
    # 找出当日流入最多的方向
    top_in = [f for f in ranking[:3] if f["main_net"] > 0]
    top_out = [f for f in ranking[-3:] if f["main_net"] < 0]
    if top_in:
        names = [f"{f['name']}({f['style']})" for f in top_in]
        print(f"     资金流入方向: {', '.join(names)}")
    if top_out:
        names = [f"{f['name']}({f['style']})" for f in top_out]
        print(f"     资金流出方向: {', '.join(names)}")

    # 数据质量报告
    hist_codes = set(analysis["多周期趋势"].keys())
    hist_valid = sum(1 for c in hist_codes
                     if analysis["多周期趋势"][c].get("1w", {}).get("days", 0) > 0)
    print(f"\n  📊 数据质量: 实时行情{len(analysis['实时行情'])}只 | "
          f"当日资金流{len(ranking)}只 | 历史资金流{hist_valid}只有效")

    print()
    print("=" * 80)
    print("  ⚠️ 研究声明: 数据基于公开API，仅供参考，不构成投资建议。")
    print(f"  扫描时间: {analysis['scan_time']}")
    print("=" * 80)


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    start = time.time()
    print("╔══════════════════════════════════════════════════════╗")
    print("║   A股ETF资金流全景扫描器 V1.1                        ║")
    print("║   扫描日期: 2026-07-08                                ║")
    print("║   数据: 腾讯行情 + 东财push2(当日) + push2his(历史)  ║")
    print("╚══════════════════════════════════════════════════════╝")

    data = collect_all_data()
    analysis = analyze(data)
    print_report(analysis)

    elapsed = time.time() - start
    print(f"\n⏱️ 总耗时: {elapsed:.1f}秒")

    # 保存JSON
    output_path = "/Users/lishunxiang/Cenxi/learn/Finance/src/宏观经济/2026-07-08-ETF资金流分析/etf_flow_data.json"
    # 仅保存可序列化的部分
    save_data = {
        "scan_time": analysis["scan_time"],
        "宽基风格对比": analysis["宽基风格对比"],
        "增量资金检测": analysis["增量资金检测"],
        "行业轮动": analysis["行业轮动"],
        "当日资金流排名": analysis["当日资金流排名"],
        "综合研判": analysis["综合研判"],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"📁 分析数据已保存: {output_path}")
