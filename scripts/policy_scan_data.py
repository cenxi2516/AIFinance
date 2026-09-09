#!/usr/bin/env python3
"""政策事件扫描辅助脚本 — 拉取东财全球快讯 + 同花顺热点归因 + 概念板块资金流"""
import time, random, uuid, requests, pandas as pd
from datetime import date, timedelta

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── 东财防封 ──
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15, **kwargs):
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


# ═══════════════════════════════════════════
# 1. 东财全球资讯快讯 (7×24)
# ═══════════════════════════════════════════
def eastmoney_global_news(page_size=80):
    url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    params = {
        "client": "web", "biz": "web_724",
        "fastColumn": "102", "sortEnd": "",
        "pageSize": str(page_size),
        "req_trace": str(uuid.uuid4()),
    }
    headers = {"User-Agent": UA, "Referer": "https://kuaixun.eastmoney.com/"}
    r = em_get(url, params=params, headers=headers, timeout=10)
    d = r.json()
    rows = []
    for item in d.get("data", {}).get("fastNewsList", []):
        rows.append({
            "title": item.get("title", ""),
            "summary": (item.get("summary", "") or "")[:200],
            "time": item.get("showTime", ""),
        })
    return rows


# ═══════════════════════════════════════════
# 2. 同花顺当日强势股归因
# ═══════════════════════════════════════════
def ths_hot_reason(date_str=None):
    if date_str is None:
        date_str = date.today().strftime("%Y-%m-%d")
    url = (
        f"http://zx.10jqka.com.cn/event/api/getharden/"
        f"date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"
    }
    r = requests.get(url, headers=headers, timeout=10)
    data = r.json()
    if data.get("errocode", 0) != 0:
        raise RuntimeError(f"同花顺热点错误: {data.get('errormsg', '')}")
    rows = data.get("data") or []
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    rename_map = {
        "name": "名称", "code": "代码", "reason": "题材归因",
        "close": "收盘价", "zhangdie": "涨跌额", "zhangfu": "涨幅%",
        "huanshou": "换手率%", "chengjiaoe": "成交额",
        "chengjiaoliang": "成交量", "ddejingliang": "大单净量",
        "market": "市场",
    }
    df = df.rename(columns=rename_map)
    return df


# ═══════════════════════════════════════════
# 3. 东财概念板块资金流 (短期)
# ═══════════════════════════════════════════
def concept_capital_flow():
    """东财概念板块当日资金流向"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "fid": "f62", "po": "1", "pz": "30",
        "pn": "1", "np": "1", "fltt": "2",
        "invt": "2", "fs": "m:90+t:3",  # 概念板块
        "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f72",
    }
    headers = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}
    r = em_get(url, params=params, headers=headers, timeout=10)
    d = r.json()
    rows = d.get("data", {}).get("diff", [])
    result = []
    for item in rows:
        result.append({
            "代码": item.get("f12", ""),
            "名称": item.get("f14", ""),
            "最新价": item.get("f2", ""),
            "涨跌幅%": item.get("f3", ""),
            "主力净流入(元)": item.get("f62", ""),
            "主力净流入占比%": item.get("f184", ""),
        })
    return result


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 80)
    print("📰 东财全球资讯快讯（最近 80 条）")
    print("=" * 80)
    try:
        news = eastmoney_global_news(80)
        # 只显示 7/18 之后的关键新闻
        keywords = ["政策", "芯片", "AI", "半导体", "制裁", "关税", "美联储", "央行",
                    "商业航天", "低空", "机器人", "光伏", "储能", "锂电池", "新能源",
                    "医药", "创新药", "稀土", "黄金", "石油", "军工", "通信", "6G",
                    "政治局", "国常会", "消费", "地产", "茅台", "解禁", "中报",
                    "出口管制", "增持", "回购", "券商", "保险"]
        count = 0
        for n in news:
            title = n["title"]
            if any(k in title for k in keywords):
                print(f"  {n['time']} | {title}")
                if n["summary"]:
                    print(f"    → {n['summary'][:120]}")
                count += 1
        if count == 0:
            print("  (无匹配关键词新闻，打印全部)")
            for n in news[:30]:
                print(f"  {n['time']} | {n['title']}")
        print(f"\n共 {len(news)} 条新闻，筛选显示 {count} 条")
    except Exception as e:
        print(f"  ❌ 东财快讯拉取失败: {e}")

    print()
    print("=" * 80)
    print("🔥 同花顺当日强势股归因（最近交易日）")
    print("=" * 80)
    try:
        for day_offset in [0, 1, 2]:
            dt = date.today() - timedelta(days=day_offset)
            dt_str = dt.strftime("%Y-%m-%d")
            df = ths_hot_reason(dt_str)
            if df.empty:
                print(f"  {dt_str}: 无数据（非交易日）")
                continue
            print(f"\n--- {dt_str}（共 {len(df)} 只）---")
            # 提取题材频率
            reasons = df["题材归因"].dropna().tolist()
            # 按题材归因关键词聚拢
            tag_count = {}
            for r in reasons:
                for tag in r.split("+"):
                    tag = tag.strip()
                    if len(tag) >= 2:
                        tag_count[tag] = tag_count.get(tag, 0) + 1
            top_tags = sorted(tag_count.items(), key=lambda x: x[1], reverse=True)[:20]
            print("  Top 20 热门题材:")
            for tag, cnt in top_tags:
                print(f"    {tag}: {cnt}只")
            break  # 只取最近一个有数据的交易日
    except Exception as e:
        print(f"  ❌ 同花顺热点归因失败: {e}")

    print()
    print("=" * 80)
    print("💰 东财概念板块主力资金流 Top 30（当日）")
    print("=" * 80)
    try:
        flows = concept_capital_flow()
        print(f"{'名称':<12} {'涨跌幅%':>8} {'主力净流入(亿)':>14} {'净流入占比%':>12}")
        print("-" * 50)
        for f in flows:
            name = f["名称"]
            chg = f["涨跌幅%"]
            inflow = f["主力净流入(元)"]
            if inflow and float(inflow) != 0:
                inflow_e = float(inflow) / 1e8
            else:
                inflow_e = 0
            ratio = f.get("主力净流入占比%", "") or ""
            print(f"  {name:<12} {chg:>8} {inflow_e:>12.2f}亿 {ratio:>10}")
    except Exception as e:
        print(f"  ❌ 概念资金流失败: {e}")

    print()
    print("=" * 80)
    print("✅ 数据拉取完成")
    print("=" * 80)
