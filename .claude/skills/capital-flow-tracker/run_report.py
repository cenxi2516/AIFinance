#!/usr/bin/env python3
"""全市场资金流向全景报告 — 一次性运行脚本"""

import time, random, json, re
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ━━━ 基础设施（从 a-stock-data 继承）━━━
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def _create_session():
    """创建带重试机制的 Session"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    })
    # 配置重试策略: 最多3次，退避因子 1.5
    retry_strategy = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=5, pool_maxsize=5)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

EM_SESSION = _create_session()
EM_MIN_INTERVAL = 2.0  # 增加间隔防封
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=20, retries=3):
    """东财统一请求：自动节流 + 重试 + 连接恢复"""
    global EM_SESSION

    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.2, 0.8))

    extra_headers = headers or {}
    extra_headers.setdefault("Referer", "https://data.eastmoney.com/")

    last_err = None
    for attempt in range(retries):
        try:
            resp = EM_SESSION.get(url, params=params, headers=extra_headers, timeout=timeout)
            _em_last_call[0] = time.time()
            return resp
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                ConnectionError) as e:
            last_err = e
            print(f"    ⚠️ 请求失败 (尝试 {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                wait_s = (2 ** attempt) * 2 + random.uniform(0, 1)
                print(f"    ⏳ {wait_s:.0f}s 后重试...")
                time.sleep(wait_s)
                # 重建 session（连接可能已断开）
                EM_SESSION = _create_session()
            else:
                raise last_err
        finally:
            _em_last_call[0] = time.time()

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def eastmoney_datacenter(report_name, columns="ALL", filter_str="",
                          page_size=50, sort_columns="", sort_types="-1"):
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []

PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"
PUSH2_HIS = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

PERIOD_MAP = {
    "today": 0, "1w": 5, "2w": 10, "1m": 22, "2m": 44,
    "3m": 66, "4m": 88, "5m": 110, "6m": 125, "1y": 250,
}

def period_to_days(period: str) -> int:
    return PERIOD_MAP.get(period, 22)

# ━━━ Layer 1: 板块级资金流向 ━━━

def concept_sector_fund_flow(sort_by: str = "f62", top_n: int = 30) -> dict:
    params = {
        "pn": "1", "pz": str(min(top_n, 500)), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:3",
        "fields": "f2,f3,f12,f14,f62,f66,f72,f78,f84,f104,f105,f128",
        "st": sort_by,
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    r = em_get(PUSH2_CLIST, params=params, headers=headers, timeout=15)
    d = r.json()
    items = d.get("data", {}).get("diff", [])
    total = d.get("data", {}).get("total", 0)
    sectors = []
    for it in items:
        sectors.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": it.get("f62") or 0,
            "super_large_net": it.get("f66") or 0,
            "large_net": it.get("f72") or 0,
            "mid_net": it.get("f78") or 0,
            "small_net": it.get("f84") or 0,
            "change_pct": it.get("f3", 0),
            "up_count": it.get("f104", 0),
            "down_count": it.get("f105", 0),
            "leader_stock": it.get("f128", ""),
        })
    return {"total": total, "sectors": sectors}


def industry_sector_fund_flow(top_n: int = 86) -> dict:
    params = {
        "pn": "1", "pz": str(top_n), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f12,f14,f62,f66,f72,f78,f84,f104,f105",
        "st": "f62",
    }
    r = em_get(PUSH2_CLIST, params=params,
               headers={"Referer": "https://data.eastmoney.com/"}, timeout=15)
    d = r.json()
    items = d.get("data", {}).get("diff", [])
    sectors = []
    for it in items:
        sectors.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": it.get("f62") or 0,
            "change_pct": it.get("f3", 0),
            "super_large_net": it.get("f66") or 0,
            "large_net": it.get("f72") or 0,
            "mid_net": it.get("f78") or 0,
            "small_net": it.get("f84") or 0,
        })
    return {"total": len(sectors), "sectors": sectors}


# ━━━ Layer 2: 板块内个股资金流 ━━━

def _parse_stock_fund_flow(d: dict) -> list[dict]:
    items = d.get("data", {}).get("diff", []) or []
    stocks = []
    for it in items:
        stocks.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": it.get("f62") or 0,
            "super_large_net": it.get("f66") or 0,
            "large_net": it.get("f72") or 0,
            "change_pct": it.get("f3", 0),
            "price": it.get("f2", 0),
            "turnover_pct": it.get("f8", 0),
            "volume_ratio": it.get("f10", 0),
            "mcap": it.get("f20") or 0,
            "float_mcap": it.get("f21") or 0,
        })
    return stocks


def sector_stock_fund_flow(bk_code: str, top_n: int = 10) -> dict:
    params_in = {
        "pn": "1", "pz": str(top_n), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": f"b:{bk_code}+f:!50",
        "fields": "f2,f3,f4,f8,f10,f12,f14,f20,f21,f62,f66,f72",
        "st": "f62",
    }
    headers = {"Referer": "https://data.eastmoney.com/"}
    r_in = em_get(PUSH2_CLIST, params=params_in, headers=headers, timeout=15)
    d_in = r_in.json()
    total = d_in.get("data", {}).get("total", 0)
    inflow = _parse_stock_fund_flow(d_in)

    params_out = {**params_in, "st": "f62", "po": "1"}
    r_out = em_get(PUSH2_CLIST, params=params_out, headers=headers, timeout=15)
    d_out = r_out.json()
    outflow = _parse_stock_fund_flow(d_out)

    return {
        "total": total,
        "inflow_top10": inflow[:top_n],
        "outflow_top10": outflow[:top_n],
    }


# ━━━ Layer 3: 龙虎榜 ━━━

def daily_dragon_tiger_scan(date: str = None, min_net_buy_wan: float = 0) -> dict:
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{date}')(TRADE_DATE<='{date}')",
        page_size=500,
        sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    stocks = []
    for row in data:
        net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
        if net_buy < min_net_buy_wan:
            continue
        stocks.append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "reason": row.get("EXPLANATION", ""),
            "close": row.get("CLOSE_PRICE") or 0,
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
            "net_buy_wan": round(net_buy, 1),
            "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
            "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
        })
    return {"date": date, "total": len(stocks), "stocks": stocks}


def _merge_seat_positions(seats: list[dict]) -> list[dict]:
    merged = {}
    for s in seats:
        key = s["name"]
        if key not in merged:
            merged[key] = {**s, "dates": [s["date"]]}
        else:
            merged[key]["buy_wan"] += s["buy_wan"]
            merged[key]["sell_wan"] += s["sell_wan"]
            merged[key]["net_wan"] += s["net_wan"]
            merged[key]["dates"].append(s["date"])
    result = list(merged.values())
    result.sort(key=lambda x: x["net_wan"], reverse=True)
    for s in result:
        s["buy_wan"] = round(s["buy_wan"], 1)
        s["sell_wan"] = round(s["sell_wan"], 1)
        s["net_wan"] = round(s["net_wan"], 1)
    return result


def dragon_tiger_seat_analysis(code: str, lookback_days: int = 30) -> dict:
    from datetime import timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    records = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start_date}')(TRADE_DATE<='{end_date}')(SECURITY_CODE='{code}')",
        page_size=50,
        sort_columns="TRADE_DATE", sort_types="-1",
    )

    institution = {"buy_total": 0, "sell_total": 0, "net_total": 0, "seats": []}
    hot_money = {"buy_total": 0, "sell_total": 0, "net_total": 0, "seats": []}

    for record in records[:5]:
        trade_date = str(record.get("TRADE_DATE", ""))[:10]
        for side, report_name in [("buy", "RPT_BILLBOARD_DAILYDETAILSBUY"),
                                    ("sell", "RPT_BILLBOARD_DAILYDETAILSSELL")]:
            detail = eastmoney_datacenter(
                report_name,
                filter_str=f"(TRADE_DATE='{trade_date}')(SECURITY_CODE='{code}')",
                page_size=20,
                sort_columns="BUY" if side == "buy" else "SELL",
                sort_types="-1",
            )
            for row in detail:
                seat_code = str(row.get("OPERATEDEPT_CODE", ""))
                seat_name = row.get("OPERATEDEPT_NAME", "")
                buy_amt = (row.get("BUY") or 0) / 10000
                sell_amt = (row.get("SELL") or 0) / 10000
                net_amt = (row.get("NET") or 0) / 10000

                seat_info = {
                    "name": seat_name,
                    "date": trade_date,
                    "buy_wan": round(buy_amt, 1),
                    "sell_wan": round(sell_amt, 1),
                    "net_wan": round(net_amt, 1),
                }

                if seat_code == "0":
                    institution["buy_total"] += buy_amt
                    institution["sell_total"] += sell_amt
                    institution["net_total"] += net_amt
                    institution["seats"].append(seat_info)
                else:
                    hot_money["buy_total"] += buy_amt
                    hot_money["sell_total"] += sell_amt
                    hot_money["net_total"] += net_amt
                    hot_money["seats"].append(seat_info)

    for cat in [institution, hot_money]:
        for k in ["buy_total", "sell_total", "net_total"]:
            cat[k] = round(cat[k], 1)
        cat["seats"] = _merge_seat_positions(cat["seats"])

    return {
        "code": code,
        "records_count": len(records),
        "institution": institution,
        "hot_money": hot_money,
    }


# ━━━ Layer 4: 个股多周期资金流 ━━━

def _fetch_today_fund_flow(code: str) -> dict | None:
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    params = {
        "secid": secid, "klt": "1",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "lmt": "250",
    }
    headers = {"Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
                   params=params, headers=headers, timeout=15)
        d = r.json()
        klines = d.get("data", {}).get("klines", []) or []
    except Exception:
        return None

    if not klines:
        return None

    main_net = super_net = large_net = mid_net = small_net = 0.0
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 6:
            main_net += float(parts[1]) if parts[1] != "-" else 0
            small_net += float(parts[2]) if parts[2] != "-" else 0
            mid_net += float(parts[3]) if parts[3] != "-" else 0
            large_net += float(parts[4]) if parts[4] != "-" else 0
            super_net += float(parts[5]) if parts[5] != "-" else 0

    return {
        "main_net": main_net, "super_large_net": super_net,
        "large_net": large_net, "mid_net": mid_net, "small_net": small_net,
        "minutes": len(klines),
    }


# ━━━ Layer 5: 个股归因分析 ━━━

def _get_stock_concept_blocks(code: str) -> list[dict]:
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3", "pi": "0", "pz": "200", "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/slist/get",
                   params=params, headers=headers, timeout=10)
        d = r.json()
        diff = (d.get("data") or {}).get("diff") or {}
        items = diff.values() if isinstance(diff, dict) else diff
        return [
            {"code": it.get("f12", ""), "name": it.get("f14", ""),
             "change_pct": it.get("f3", 0), "leader": it.get("f128", "")}
            for it in items
        ]
    except Exception:
        return []


def _fetch_stock_news(code: str, days: int = 7) -> list[dict]:
    import json as _json
    cb = "jQuery_news"
    inner = _json.dumps({
        "uid": "", "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {
            "searchScope": "default", "sort": "default",
            "pageIndex": 1, "pageSize": 20, "preTag": "", "postTag": "",
        }},
    }, separators=(',', ':'))
    params = {"cb": cb, "param": inner}
    headers = {"Referer": "https://so.eastmoney.com/"}
    try:
        r = em_get("https://search-api-web.eastmoney.com/search/jsonp",
                   params=params, headers=headers, timeout=10)
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = _json.loads(json_str)
        articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
        news = []
        for a in articles:
            news.append({
                "title": re.sub(r'<[^>]+>', '', a.get("title", "")),
                "content": re.sub(r'<[^>]+>', '', a.get("content", ""))[:200],
                "time": a.get("date", ""),
                "source": a.get("mediaName", ""),
                "url": a.get("url", ""),
            })
        return news
    except Exception:
        return []


def stock_daily_attribution(code: str) -> dict:
    attribution = {
        "code": code,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dimensions": {},
        "verdict": {},
    }

    # 维度1: 资金面
    today_flow = _fetch_today_fund_flow(code)
    if today_flow:
        inst_net = today_flow.get("super_large_net", 0)
        hm_net = today_flow.get("large_net", 0)
        retail_net = (today_flow.get("mid_net", 0) or 0) + (today_flow.get("small_net", 0) or 0)
        main_dir = "流入" if today_flow["main_net"] > 0 else "流出"
        attribution["dimensions"]["fund_flow"] = {
            "main_net_wan": round(today_flow["main_net"] / 1e4, 1),
            "direction": main_dir,
            "institution_net_wan": round(inst_net / 1e4, 1),
            "hot_money_net_wan": round(hm_net / 1e4, 1),
            "retail_net_wan": round(retail_net / 1e4, 1),
            "data_points": today_flow.get("minutes", 0),
            "source": f"push2 分钟级资金流 ({today_flow.get('minutes', 0)}个时间点)",
        }

    # 维度2: 板块面
    try:
        blocks_data = _get_stock_concept_blocks(code)
        blocks_fund_flow = []
        for bk in blocks_data[:5]:
            try:
                params_bk = {
                    "pn": "1", "pz": "1", "po": "0", "np": "1",
                    "fltt": "2", "invt": "2",
                    "fs": f"b:{bk['code']}+f:!50",
                    "fields": "f2,f3,f62",
                }
                r_bk = em_get(PUSH2_CLIST, params=params_bk,
                           headers={"Referer": "https://data.eastmoney.com/"}, timeout=10)
                d_bk = r_bk.json()
                items_bk = d_bk.get("data", {}).get("diff", [])
                if items_bk:
                    bk_flow = (items_bk[0].get("f62") or 0) if isinstance(items_bk, list) else 0
                    blocks_fund_flow.append({
                        "name": bk["name"],
                        "code": bk["code"],
                        "main_net_wan": round(bk_flow / 1e4, 1),
                        "direction": "流入" if bk_flow > 0 else "流出",
                    })
            except Exception:
                continue

        if blocks_fund_flow:
            inflow_blocks = [b for b in blocks_fund_flow if b["main_net_wan"] > 0]
            outflow_blocks = [b for b in blocks_fund_flow if b["main_net_wan"] < 0]
            attribution["dimensions"]["sector"] = {
                "blocks": blocks_fund_flow,
                "inflow_count": len(inflow_blocks),
                "outflow_count": len(outflow_blocks),
                "source": "东财 push2 概念板块资金流",
            }
    except Exception:
        attribution["dimensions"]["sector"] = {"error": "板块数据获取失败"}

    # 维度3: 消息面
    try:
        news = _fetch_stock_news(code, days=7)
        if news:
            today_str = datetime.now().strftime("%Y-%m-%d")
            today_news = [n for n in news if n.get("time", "").startswith(today_str)]
            attribution["dimensions"]["news"] = {
                "today_count": len(today_news),
                "recent_count": len(news),
                "today_highlights": [
                    {"title": n["title"], "time": n["time"], "source": n["source"]}
                    for n in today_news[:5]
                ],
                "recent_highlights": [
                    {"title": n["title"], "time": n["time"], "source": n["source"]}
                    for n in news[:5]
                ],
                "source": "东财个股新闻 (search-api-web)",
            }
    except Exception:
        attribution["dimensions"]["news"] = {"today_count": 0, "error": "新闻数据获取失败"}

    # 维度4: 席位面
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        dt_data = eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f"(TRADE_DATE='{today_str}')(SECURITY_CODE='{code}')",
            page_size=5,
        )
        if dt_data:
            row = dt_data[0]
            attribution["dimensions"]["dragon_tiger"] = {
                "on_board": True,
                "reason": row.get("EXPLANATION", ""),
                "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 1e4, 1),
                "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
                "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
                "source": "东财龙虎榜 (RPT_DAILYBILLBOARD_DETAILSNEW)",
            }
        else:
            attribution["dimensions"]["dragon_tiger"] = {"on_board": False}
    except Exception:
        attribution["dimensions"]["dragon_tiger"] = {"on_board": False, "error": "龙虎榜获取失败"}

    # 维度5: 技术面
    try:
        from urllib.request import Request, urlopen
        prefixed = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
        url = f"https://qt.gtimg.cn/q={prefixed}"
        req = Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
        vals = data.split('"')[1].split("~") if '"' in data else []
        if len(vals) >= 53:
            change_pct = float(vals[32]) if vals[32] else 0
            turnover = float(vals[38]) if vals[38] else 0
            vol_ratio = float(vals[49]) if vals[49] else 0
            amplitude = float(vals[43]) if vals[43] else 0
            price = float(vals[3]) if vals[3] else 0
            attribution["dimensions"]["technical"] = {
                "price": price,
                "change_pct": change_pct,
                "turnover_pct": turnover,
                "vol_ratio": vol_ratio,
                "amplitude_pct": amplitude,
                "source": "腾讯财经行情 (qt.gtimg.cn)",
            }
    except Exception:
        attribution["dimensions"]["technical"] = {"error": "行情数据获取失败"}

    return attribution


# ━━━ 综合报告生成 ━━━

def capital_flow_report(top_sectors: int = 10, seats_top_n: int = 5) -> dict:
    report = {}

    # 1. 概念板块
    print("[1/5] 拉取概念板块资金流...")
    sectors = concept_sector_fund_flow(top_n=top_sectors * 2)
    inflow_sectors = sectors["sectors"][:top_sectors]
    outflow_sectors = sorted(sectors["sectors"], key=lambda x: x["main_net"])[:top_sectors]
    report["top_inflow_sectors"] = inflow_sectors
    report["top_outflow_sectors"] = outflow_sectors

    # 2. 行业板块（粗粒度）
    print("[1b/5] 拉取行业板块资金流...")
    report["industry_sectors"] = industry_sector_fund_flow(86)

    # 3. 前 3 流入板块的个股 TOP10
    report["sector_stock_detail"] = {}
    for i, sec in enumerate(inflow_sectors[:3]):
        print(f"[2.{i+1}/5] 分析 {sec['name']}({sec['code']}) 个股...")
        try:
            detail = sector_stock_fund_flow(sec["code"], top_n=10)
            report["sector_stock_detail"][sec["code"]] = {
                "sector_name": sec["name"],
                **detail,
            }
        except Exception as e:
            report["sector_stock_detail"][sec["code"]] = {"error": str(e)}

    # 4. 全市场龙虎榜
    print("[3/5] 拉取全市场龙虎榜...")
    report["dragon_tiger"] = daily_dragon_tiger_scan(min_net_buy_wan=5000)

    # 5. 重点个股席位分析
    report["seat_analysis"] = {}
    top_stocks = report["dragon_tiger"]["stocks"][:seats_top_n]
    for i, stock in enumerate(top_stocks):
        print(f"[4.{i+1}/5] 分析 {stock['name']}({stock['code']}) 席位...")
        try:
            report["seat_analysis"][stock["code"]] = dragon_tiger_seat_analysis(
                stock["code"], lookback_days=30
            )
        except Exception as e:
            report["seat_analysis"][stock["code"]] = {"error": str(e)}

    print("[5/5] 报告生成完成!")
    return report


# ━━━ 输出 ━━━

def print_capital_flow_report(report: dict):
    print("=" * 80)
    print("  A股资金流向全景报告")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"  生成时间: {now}")
    print("=" * 80)

    # 概念板块 TOP 流入
    print(f"\n{'─' * 60}")
    print("  📊 概念板块主力净流入 TOP 10")
    print(f"{'─' * 60}")
    for i, s in enumerate(report["top_inflow_sectors"][:10]):
        emoji = "🔥" if i < 3 else "  "
        print(f"  {emoji} {i+1:2d}. {s['name']:<12s} 主力={s['main_net']/1e8:>8.2f}亿  "
              f"涨跌={s['change_pct']:>6.2f}%  涨{s['up_count']}跌{s['down_count']}")

    # 概念板块 TOP 流出
    print(f"\n{'─' * 60}")
    print("  📉 概念板块主力净流出 TOP 10")
    print(f"{'─' * 60}")
    for i, s in enumerate(report["top_outflow_sectors"][:10]):
        emoji = "⚠️" if i < 3 else "  "
        print(f"  {emoji} {i+1:2d}. {s['name']:<12s} 主力={s['main_net']/1e8:>8.2f}亿")

    # 行业板块 TOP 流入
    ind_sectors = report.get("industry_sectors", {}).get("sectors", [])
    ind_inflow = sorted(ind_sectors, key=lambda x: x.get("main_net", 0) or 0, reverse=True)[:10]
    print(f"\n{'─' * 60}")
    print("  🏢 行业板块主力净流入 TOP 10")
    print(f"{'─' * 60}")
    for i, s in enumerate(ind_inflow):
        emoji = "🔥" if i < 3 else "  "
        print(f"  {emoji} {i+1:2d}. {s['name']:<12s} 主力={s['main_net']/1e8:>8.2f}亿  "
              f"涨跌={s['change_pct']:>6.2f}%")

    # 前3板块个股 TOP10
    for bk_code, detail in list(report.get("sector_stock_detail", {}).items())[:3]:
        sec_name = detail.get("sector_name", bk_code)
        if "error" in detail:
            print(f"\n  ⚠️ {sec_name}: {detail['error']}")
            continue
        print(f"\n{'─' * 60}")
        print(f"  🏭 {sec_name} — 个股资金流 TOP 10")
        print(f"{'─' * 60}")
        print(f"  {'代码':<8s} {'名称':<10s} {'主力净流入':>12s}  {'涨跌幅':>8s}  {'换手率':>8s}")
        print(f"  {'─' * 50}")
        for s in detail.get("inflow_top10", [])[:10]:
            print(f"  {s['code']:<8s} {s['name']:<10s} {s['main_net']/1e4:>10.0f}万  "
                  f"{s['change_pct']:>7.2f}%  {s['turnover_pct']:>7.2f}%")

        print(f"\n  主力净流出 TOP 5:")
        for s in detail.get("outflow_top10", [])[:5]:
            print(f"  {s['code']:<8s} {s['name']:<10s} {s['main_net']/1e4:>10.0f}万")

    # 龙虎榜
    dt = report.get("dragon_tiger", {})
    print(f"\n{'─' * 60}")
    print(f"  🐉 全市场龙虎榜 ({dt.get('date', '')}) — 共{dt.get('total', 0)}条")
    print(f"{'─' * 60}")
    for s in dt.get("stocks", [])[:15]:
        print(f"  {s['code']} {s['name']:<8s} 净买={s['net_buy_wan']:.0f}万  "
              f"涨跌={s['change_pct']}% 换手={s['turnover_pct']}%  {s['reason'][:30]}")

    # 重点个股席位分析
    print(f"\n{'─' * 60}")
    print("  🏦 重点个股机构 vs 游资分析")
    print(f"{'─' * 60}")
    for code, analysis in report.get("seat_analysis", {}).items():
        if "error" in analysis:
            print(f"  ⚠️ {code}: {analysis['error']}")
            continue
        stock_name = ""
        for s in dt.get("stocks", []):
            if s["code"] == code:
                stock_name = s["name"]
                break
        print(f"\n  【{code} {stock_name}】(近30日上榜{analysis['records_count']}次)")
        inst = analysis["institution"]
        hm = analysis["hot_money"]
        print(f"  🔴 机构: 买{inst['buy_total']:.0f}万 卖{inst['sell_total']:.0f}万  "
              f"净持仓={inst['net_total']:.0f}万(还剩)")
        for s in inst["seats"][:3]:
            print(f"      {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")
        print(f"  🟡 游资: 买{hm['buy_total']:.0f}万 卖{hm['sell_total']:.0f}万  "
              f"净持仓={hm['net_total']:.0f}万(还剩)")
        for s in hm["seats"][:3]:
            print(f"      {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")

    print(f"\n{'=' * 80}")
    print("  ⚠️ 研究声明: 以上数据基于公开API，仅供参考。不构成任何投资建议。")
    print(f"{'=' * 80}")


# ━━━ 主流程 ━━━

def main():
    print("╔══════════════════════════════════════════════════╗")
    print("║   A股资金流向全景扫描 — 2026-07-01              ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    report = capital_flow_report(top_sectors=10, seats_top_n=5)

    # 打印到控制台
    print_capital_flow_report(report)

    # 保存 JSON
    out_dir = "/Users/lishunxiang/Cenxi/learn/Finance/src/资金流向/2026-07-01-资金流向全景扫描"
    json_path = f"{out_dir}/report.json"

    # 转成可序列化的格式
    def make_serializable(obj):
        if isinstance(obj, dict):
            return {k: make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [make_serializable(v) for v in obj]
        elif isinstance(obj, float):
            return round(obj, 2)
        return obj

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(make_serializable(report), f, ensure_ascii=False, indent=2)
    print(f"\n📁 报告已保存: {json_path}")


if __name__ == "__main__":
    main()
