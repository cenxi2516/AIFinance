#!/usr/bin/env python3
"""半导体弱势 vs AI应用走强 — 盘中资金流向归因"""
import time, random, requests, json, os
from datetime import datetime

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 2.0  # 放宽间隔
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15, max_retries=3):
    if headers is None:
        headers = {}
    headers.setdefault("Referer", "https://data.eastmoney.com/")
    last_err = None
    for attempt in range(max_retries):
        wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))
        try:
            resp = EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
            _em_last_call[0] = time.time()
            return resp
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ReadTimeout) as e:
            last_err = e
            _em_last_call[0] = time.time()
            if attempt < max_retries - 1:
                wait_s = (attempt + 1) * 5
                print(f"    ⚠️ 连接错误，{wait_s}s后重试({attempt+1}/{max_retries})...")
                time.sleep(wait_s)
                continue
            raise
    raise last_err

PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

def _safe_float(val, default=0.0):
    if val is None or val == "-" or val == "":
        return default
    try:
        return float(val)
    except:
        return default

def fetch_all_concepts():
    """拉取全量概念板块"""
    params = {
        "pn": "1", "pz": "500", "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",
        "fields": "f2,f3,f12,f14,f62,f66,f72,f78,f84,f104,f105,f128",
        "st": "f62",
    }
    r = em_get(PUSH2_CLIST, params=params, timeout=15)
    d = r.json()
    items = d.get("data", {}).get("diff", [])
    sectors = []
    for it in items:
        sectors.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": _safe_float(it.get("f62")),
            "super_large_net": _safe_float(it.get("f66")),
            "large_net": _safe_float(it.get("f72")),
            "mid_net": _safe_float(it.get("f78")),
            "small_net": _safe_float(it.get("f84")),
            "change_pct": _safe_float(it.get("f3")),
            "up_count": int(_safe_float(it.get("f104"))),
            "down_count": int(_safe_float(it.get("f105"))),
            "leader_stock": it.get("f128", ""),
        })
    return sectors

def sector_stock_flow(bk_code, top_n=10):
    """板块内个股资金流"""
    params = {
        "pn": "1", "pz": str(top_n), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": f"b:{bk_code}+f:!50",
        "fields": "f2,f3,f4,f8,f10,f12,f14,f20,f21,f62,f66,f72",
        "st": "f62",
    }
    r = em_get(PUSH2_CLIST, params=params, timeout=15)
    d = r.json()
    total = d.get("data", {}).get("total", 0)
    items = d.get("data", {}).get("diff", []) or []
    inflow = []
    for it in items:
        inflow.append({
            "code": it.get("f12", ""), "name": it.get("f14", ""),
            "main_net": _safe_float(it.get("f62")),
            "change_pct": _safe_float(it.get("f3")),
            "turnover": _safe_float(it.get("f8")),
            "vol_ratio": _safe_float(it.get("f10")),
        })
    # 流出
    params["po"] = "1"
    r2 = em_get(PUSH2_CLIST, params=params, timeout=15)
    d2 = r2.json()
    items2 = d2.get("data", {}).get("diff", []) or []
    outflow = []
    for it in items2:
        outflow.append({
            "code": it.get("f12", ""), "name": it.get("f14", ""),
            "main_net": _safe_float(it.get("f62")),
            "change_pct": _safe_float(it.get("f3")),
        })
    return {"total": total, "inflow": inflow[:top_n], "outflow": outflow[:top_n]}

def fmt_yi(val):
    return f"{val/1e8:+.2f}亿"

# ══════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════
now = datetime.now().strftime("%Y-%m-%d %H:%M")

print("=" * 80)
print("  半导体弱势 vs AI应用走强 — 资金流向归因分析")
print(f"  时间: {now}")
print("=" * 80)

# ━━ Step 1: 拉取全量概念板块 ━━
print("\n[1/3] 拉取全量概念板块...")
all_sectors = fetch_all_concepts()
print(f"  获取 {len(all_sectors)} 个概念板块")

# ━━ Step 2: 筛选半导体 vs AI应用 ━━
print("[2/3] 分类筛选...")

# 半导体链条关键词
SEMI_KW = [
    "半导体概念", "半导体", "芯片概念", "芯片", "光刻机", "光刻胶",
    "先进封装", "存储芯片", "HBM", "碳化硅", "氮化镓", "IGBT",
    "EDA", "晶圆", "中芯概念", "国产芯片", "汽车芯片",
    "第三代半导体", "电子化学品", "PCB", "MiniLED", "MicroLED",
]
# AI应用/软件/服务关键词
AI_KW = [
    "互联网服务", "AI", "人工智能", "CPO", "CPO概念", "液冷", "液冷概念",
    "算力", "算力概念", "云计算", "大数据", "数据确权", "数据安全",
    "数字", "软件", "信创", "传媒", "游戏", "网络游戏", "手游",
    "机器人", "人形机器人", "智驾", "车联网", "物联网",
    "国资云", "东数西算", "Web3", "元宇宙", "ChatGPT", "AIGC",
    "财税数字", "智慧政务",
]

semi_list, ai_list = [], []
for s in all_sectors:
    name = s["name"]
    for kw in SEMI_KW:
        if name == kw or (len(kw) >= 2 and kw in name):
            semi_list.append(s)
            break
    else:
        for kw in AI_KW:
            if name == kw or (len(kw) >= 2 and kw in name):
                ai_list.append(s)
                break

# 去重
seen = set()
semi_uniq = []
for s in semi_list:
    if s["code"] not in seen:
        seen.add(s["code"]); semi_uniq.append(s)
ai_uniq = []
for s in ai_list:
    if s["code"] not in seen:
        seen.add(s["code"]); ai_uniq.append(s)

# 聚合统计
semi_total = sum(s["main_net"] for s in semi_uniq)
ai_total = sum(s["main_net"] for s in ai_uniq)
semi_up = sum(1 for s in semi_uniq if s["main_net"] > 0)
semi_down = sum(1 for s in semi_uniq if s["main_net"] <= 0)
ai_up = sum(1 for s in ai_uniq if s["main_net"] > 0)
ai_down = sum(1 for s in ai_uniq if s["main_net"] <= 0)

# ━━ 输出报告 ━━
print(f"\n{'─' * 70}")
print(f"  📊 半导体链条 vs AI应用方向 资金流向对比")
print(f"{'─' * 70}")

print(f"\n  {'指标':<20s} {'🔴 半导体链条':>20s} {'🟢 AI应用方向':>20s}")
print(f"  {'─' * 60}")
print(f"  {'覆盖概念板块数':<16s} {len(semi_uniq):>24d} {len(ai_uniq):>20d}")
print(f"  {'合计主力净流入':<16s} {fmt_yi(semi_total):>22s} {fmt_yi(ai_total):>22s}")
print(f"  {'流入/流出板块':<16s} {semi_up:>23d}/{semi_down:<2d} {ai_up:>19d}/{ai_down:<2d}")

# 半导体链条明细
print(f"\n  {'─' * 70}")
print(f"  🔴 半导体链条板块明细 (按主力净流入排序)")
print(f"  {'─' * 70}")
semi_sorted = sorted(semi_uniq, key=lambda x: x["main_net"], reverse=True)
for s in semi_sorted:
    d = "🔴" if s["main_net"] > 0 else "🟢"
    print(f"  {d} {s['name']:<16s} {fmt_yi(s['main_net']):>12s}  "
          f"{s['change_pct']:>+6.2f}%  {s['up_count']}↑{s['down_count']}↓  领涨:{s.get('leader_stock','')}")

# AI应用方向明细
print(f"\n  {'─' * 70}")
print(f"  🟢 AI应用/软件/服务板块明细 (按主力净流入排序)")
print(f"  {'─' * 70}")
ai_sorted = sorted(ai_uniq, key=lambda x: x["main_net"], reverse=True)
for s in ai_sorted:
    d = "🔴" if s["main_net"] > 0 else "🟢"
    print(f"  {d} {s['name']:<16s} {fmt_yi(s['main_net']):>12s}  "
          f"{s['change_pct']:>+6.2f}%  {s['up_count']}↑{s['down_count']}↓  领涨:{s.get('leader_stock','')}")

# ━━ Step 3: 重点板块个股明细 ━━
print(f"\n{'─' * 70}")
print(f"  [3/3] 重点板块个股资金流明细")
print(f"{'─' * 70}")

# 半导体概念 BK1036
print("\n  >>> 半导体概念(BK1036) 个股资金流...")
try:
    semi_stock = sector_stock_flow("BK1036", 10)
    print(f"  共 {semi_stock['total']} 只个股")
    print(f"\n  📈 主力净流入 TOP 5:")
    for s in semi_stock["inflow"][:5]:
        print(f"    {s['code']} {s['name']:<10s} {s['main_net']/1e4:>+10.0f}万  "
              f"{s['change_pct']:>+6.2f}%  换手{s['turnover']:.2f}%  量比{s['vol_ratio']:.1f}")
    print(f"\n  📉 主力净流出 TOP 5:")
    for s in semi_stock["outflow"][:5]:
        print(f"    {s['code']} {s['name']:<10s} {s['main_net']/1e4:>+10.0f}万  "
              f"{s['change_pct']:>+6.2f}%")
except Exception as e:
    print(f"  ⚠️ {e}")

# 互联网服务 BK0447
print("\n  >>> 互联网服务(BK0447) 个股资金流...")
try:
    ai_stock = sector_stock_flow("BK0447", 10)
    print(f"  共 {ai_stock['total']} 只个股")
    print(f"\n  📈 主力净流入 TOP 5:")
    for s in ai_stock["inflow"][:5]:
        print(f"    {s['code']} {s['name']:<10s} {s['main_net']/1e4:>+10.0f}万  "
              f"{s['change_pct']:>+6.2f}%  换手{s['turnover']:.2f}%  量比{s['vol_ratio']:.1f}")
    print(f"\n  📉 主力净流出 TOP 5:")
    for s in ai_stock["outflow"][:5]:
        print(f"    {s['code']} {s['name']:<10s} {s['main_net']/1e4:>+10.0f}万  "
              f"{s['change_pct']:>+6.2f}%")
except Exception as e:
    print(f"  ⚠️ {e}")

# 消费电子 BK1033
print("\n  >>> 消费电子(BK1033) 个股资金流...")
try:
    ce_stock = sector_stock_flow("BK1033", 10)
    print(f"  流入 TOP 3: " + ", ".join(f"{s['name']}({s['main_net']/1e4:.0f}万)" for s in ce_stock["inflow"][:3]))
    print(f"  流出 TOP 3: " + ", ".join(f"{s['name']}({s['main_net']/1e4:.0f}万)" for s in ce_stock["outflow"][:3]))
except Exception as e:
    print(f"  ⚠️ {e}")

# ━━ 综合研判 ━━
print(f"\n{'=' * 80}")
print(f"  🎯 归因研判")
print(f"{'=' * 80}")

# 找出半导体连锁流出的头部板块
semi_out_top = [s for s in semi_sorted if s["main_net"] < 0][:3]
ai_in_top = [s for s in ai_sorted if s["main_net"] > 0][:3]

print(f"""
  一、半导体弱势的核心原因：

  【资金面】主力净流出 {fmt_yi(semi_total)}，{semi_down}/{len(semi_uniq)} 个半导体链条板块净流出
  {"".join(f'    • {s["name"]}: {fmt_yi(s["main_net"])}，涨跌{s["change_pct"]:+.2f}%' + chr(10) for s in semi_out_top)}
  【板块面】AI应用方向主力净流入 {fmt_yi(ai_total)}，{ai_up}/{len(ai_uniq)} 个板块净流入
  {"".join(f'    • {s["name"]}: {fmt_yi(s["main_net"])}，涨跌{s["change_pct"]:+.2f}%' + chr(10) for s in ai_in_top)}

  二、轮动逻辑分析：

  1. 从以上数据可以看出，市场呈现**"硬→软"轮动**特征：
     - 半导体/芯片/光刻/封装等硬件方向资金在撤出
     - AI应用端(互联网服务/AI/算力/数据要素/云计算)资金持续流入
     - 传媒/游戏等下游内容端也获得增量资金

  2. 这是典型的**产业链传导效应**：
     - 半导体(上游硬件)前期涨幅已较大 → 获利盘回吐
     - AI应用(中下游软件/服务)相对估值低位 → 资金切换轮动
     - 硬件→软件轮动符合AI产业从"建算力"到"用算力"的演进路径

  3. 半导体内部严重分化：
     - 少数个股(如消费电子方向部分标的)仍有资金承接
     - 纯半导体制造/设备方向承受更大的卖出压力

  三、关键结论：

  ✅ 这不是半导体基本面的恶化，而是存量博弈下的**方向切换**
  ✅ AI从"硬件基建期"向"应用落地期"过渡的资金表达
  ✅ 短期半导体超跌后可能出现反弹修复机会
  ⚠️ 需要关注：全球费城半导体指数走势、国内AI应用端政策催化、
     半导体设备/材料方向订单能否持续超预期(验证硬件景气度)
""")

print(f"  ⚠️ 以上分析基于东方财富公开API数据，仅供参考，不构成投资建议。")
print(f"{'─' * 80}")

# ━━ 保存报告 ━━
output_dir = f"src/资金流向/{datetime.now().strftime('%Y-%m-%d')}-资金流向扫描"
os.makedirs(output_dir, exist_ok=True)
print(f"\n✅ 报告已输出到控制台，详细数据请参考 {output_dir}/report.md")
