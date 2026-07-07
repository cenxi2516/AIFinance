#!/usr/bin/env python3
"""
A股资金流向全景扫描脚本 V2.1
数据来源: 东财 data.eastmoney.com 官方 API + push2 补充
功能: 概念/行业双维度 + 龙虎榜 + 席位分析 + 个股归因分析
用法: python3 scripts/capital_flow_scan.py
"""
import requests, json, os, time, random, re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

# ============================================================
# 基础工具
# ============================================================
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})
MIN_INTERVAL = 1.0
_last_call = [0.0]

def api_get(url, params=None, timeout=15):
    """统一请求：自动节流"""
    wait = MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.3))
    try:
        return SESSION.get(url, params=params, timeout=timeout,
                          headers={"Referer": "https://data.eastmoney.com/"})
    finally:
        _last_call[0] = time.time()

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
BKZJ_URL = "https://data.eastmoney.com/dataapi/bkzj/getbkzj"
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

def datacenter_get(report_name, filter_str="", page_size=50,
                    sort_columns="", sort_types="-1"):
    """东财数据中心查询"""
    params = {
        "reportName": report_name, "columns": "ALL",
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = api_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []

TODAY = datetime.now().strftime("%Y-%m-%d")

# ============================================================
# Layer 1: 板块级资金流向
# ============================================================

def concept_sector_fund_flow():
    """概念板块资金流向（494个概念），返回按主力净流入降序排列"""
    r = api_get(BKZJ_URL, params={"code": "m:90+t:3", "key": "f62"}, timeout=20)
    d = r.json()
    if d.get("rc") != 0:
        raise Exception(f"API error: rc={d.get('rc')}")
    diff = d["data"]["diff"]
    sectors = []
    for it in diff:
        sectors.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": it.get("f62") or 0,
        })
    return {"total": d["data"]["total"], "sectors": sectors}


def industry_sector_fund_flow():
    """行业板块资金流向（~86个行业）"""
    r = api_get(BKZJ_URL, params={"code": "m:90+t:2", "key": "f62"}, timeout=20)
    d = r.json()
    if d.get("rc") != 0:
        raise Exception(f"API error: rc={d.get('rc')}")
    diff = d["data"]["diff"]
    sectors = []
    for it in diff:
        sectors.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": it.get("f62") or 0,
        })
    return {"total": d["data"]["total"], "sectors": sectors}


def get_sector_rich_data(bk_codes: list[str]) -> dict:
    """通过 data.eastmoney.com 批量获取概念板块丰富数据（逐字段拉取，更稳定）"""
    if not bk_codes:
        return {}
    code_set = set(bk_codes)
    result = {c: {} for c in bk_codes}

    # 使用 data.eastmoney.com API 逐字段拉取（比 push2 更稳定）
    field_configs = [
        ("f3", "change_pct"),
        ("f66", "super_large_net"),
        ("f72", "large_net"),
        ("f78", "mid_net"),
        ("f84", "small_net"),
    ]
    for key, field_name in field_configs:
        try:
            r = api_get(BKZJ_URL, params={"code": "m:90+t:3", "key": key}, timeout=20)
            d = r.json()
            if d.get("rc") == 0:
                for it in d["data"]["diff"]:
                    code = it.get("f12", "")
                    if code in code_set:
                        val = it.get(key) or 0
                        # BKZJ_API 的 f3(涨跌幅)返回基点值，需/100转为百分比
                        if key == "f3":
                            val = val / 100.0
                        result[code][field_name] = val
        except Exception:
            continue

    # push2 补充涨跌家数和领涨股（可选，失败不影响主流程）
    try:
        codes_str = ",".join(bk_codes)
        params = {
            "pn": "1", "pz": str(len(bk_codes) + 10), "po": "0", "np": "1",
            "fltt": "2", "invt": "2",
            "fs": "m:90+t:3",
            "fields": "f12,f104,f105,f128",
        }
        r = api_get(PUSH2_CLIST, params=params, timeout=10)
        d = r.json()
        for it in (d.get("data", {}).get("diff", []) or []):
            code = it.get("f12", "")
            if code in code_set:
                result[code]["up_count"] = it.get("f104", 0)
                result[code]["down_count"] = it.get("f105", 0)
                result[code]["leader_stock"] = it.get("f128", "")
    except Exception:
        pass  # push2 不可用时跳过涨跌家数和领涨股

    return result


# ============================================================
# Layer 2: 板块内个股资金流
# ============================================================

def sector_stock_fund_flow(bk_code: str) -> dict:
    """指定概念板块内个股资金流向（全部个股，含丰富字段）
    优先使用 push2（丰富字段），失败时降级到 data.eastmoney.com（仅主力净流入）"""
    # 方案1: push2（含换手率/量比/市值等丰富字段）
    try:
        params = {
            "pn": "1", "pz": "200", "po": "0", "np": "1",
            "fltt": "2", "invt": "2",
            "fs": f"b:{bk_code}+f:!50",
            "fields": "f2,f3,f8,f10,f12,f14,f20,f21,f62,f66,f72,f78,f84",
            "st": "f62",
        }
        r = api_get(PUSH2_CLIST, params=params, timeout=10)
        d = r.json()
        diff = d.get("data", {}).get("diff", []) or []
        stocks = []
        for it in diff:
            stocks.append({
                "code": it.get("f12", ""),
                "name": it.get("f14", ""),
                "main_net": it.get("f62") or 0,
                "super_large_net": it.get("f66") or 0,
                "large_net": it.get("f72") or 0,
                "mid_net": it.get("f78") or 0,
                "small_net": it.get("f84") or 0,
                "change_pct": it.get("f3", 0),
                "price": it.get("f2", 0),
                "turnover_pct": it.get("f8", 0),
                "volume_ratio": it.get("f10", 0),
                "mcap": it.get("f20") or 0,
                "float_mcap": it.get("f21") or 0,
            })
        stocks.sort(key=lambda x: x["main_net"], reverse=True)
        return {"total": d.get("data", {}).get("total", 0), "stocks": stocks}
    except Exception:
        pass

    # 方案2: 降级到 data.eastmoney.com（仅主力净流入）
    r = api_get(BKZJ_URL, params={
        "code": f"b:{bk_code}+f:!50", "key": "f62",
    }, timeout=20)
    d = r.json()
    if d.get("rc") != 0:
        return {"total": 0, "stocks": []}
    diff = d["data"]["diff"]
    stocks = []
    for it in diff:
        stocks.append({
            "code": it.get("f12", ""),
            "name": it.get("f14", ""),
            "main_net": it.get("f62") or 0,
            "super_large_net": 0,
            "large_net": 0,
            "mid_net": 0,
            "small_net": 0,
            "change_pct": 0,
            "price": 0,
            "turnover_pct": 0,
            "volume_ratio": 0,
            "mcap": 0,
            "float_mcap": 0,
        })
    stocks.sort(key=lambda x: x["main_net"], reverse=True)
    return {"total": d["data"]["total"], "stocks": stocks}


# ============================================================
# Layer 3: 龙虎榜
# ============================================================

def daily_dragon_tiger_scan(date=None, min_net_buy_wan=1000):
    """全市场龙虎榜扫描"""
    if date is None:
        date = TODAY
    data = datacenter_get(
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


def dragon_tiger_seat_analysis(code, lookback_days=30):
    """个股龙虎榜机构/游资席位分析"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    records = datacenter_get(
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
            detail = datacenter_get(
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
                    "name": seat_name, "date": trade_date,
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
        cat["seats"] = _merge_seats(cat["seats"])

    return {
        "code": code, "records_count": len(records),
        "institution": institution, "hot_money": hot_money,
    }


def _merge_seats(seats):
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


# ============================================================
# Layer 4: 个股今日走势归因分析
# ============================================================

def stock_daily_attribution(code, name=""):
    """五维度交叉验证：资金面+板块面+消息面+席位面+技术面"""
    attr = {
        "code": code, "name": name,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dimensions": {}, "verdict": {},
    }

    # 维度1: 资金面（分钟级 push2）
    fund = _fetch_today_fund_flow(code)
    if fund:
        inst_net = fund.get("super_large_net", 0)
        hm_net = fund.get("large_net", 0)
        retail = (fund.get("mid_net", 0) or 0) + (fund.get("small_net", 0) or 0)
        d = "流入" if fund["main_net"] > 0 else "流出"
        attr["dimensions"]["fund_flow"] = {
            "main_net_wan": round(fund["main_net"] / 1e4, 1),
            "direction": d,
            "institution_net_wan": round(inst_net / 1e4, 1),
            "hot_money_net_wan": round(hm_net / 1e4, 1),
            "retail_net_wan": round(retail / 1e4, 1),
            "data_points": fund.get("minutes", 0),
        }

    # 维度2: 板块面（所属概念板块资金流）
    try:
        blocks = _get_stock_concept_blocks(code)
        bff = []
        for bk in blocks[:6]:
            try:
                r = api_get(BKZJ_URL, params={"code": f"b:{bk['code']}+f:!50", "key": "f62"}, timeout=10)
                d = r.json()
                if d.get("rc") == 0 and d["data"]["diff"]:
                    net = d["data"]["diff"][0].get("f62") or 0
                    bff.append({
                        "name": bk["name"], "code": bk["code"],
                        "main_net_wan": round(net / 1e4, 1),
                        "direction": "流入" if net > 0 else "流出",
                    })
            except Exception:
                continue
        if bff:
            inflow_n = len([b for b in bff if b["main_net_wan"] > 0])
            outflow_n = len([b for b in bff if b["main_net_wan"] < 0])
            attr["dimensions"]["sector"] = {
                "blocks": bff, "inflow_count": inflow_n, "outflow_count": outflow_n,
            }
    except Exception:
        attr["dimensions"]["sector"] = {"error": "板块数据获取失败"}

    # 维度3: 消息面（东财个股新闻）
    try:
        news = _fetch_stock_news(code)
        if news:
            today_news = [n for n in news if n.get("time", "").startswith(TODAY)]
            attr["dimensions"]["news"] = {
                "today_count": len(today_news), "recent_count": len(news),
                "today_highlights": [
                    {"title": n["title"], "time": n["time"], "source": n["source"]}
                    for n in today_news[:5]
                ],
                "recent_highlights": [
                    {"title": n["title"], "time": n["time"], "source": n["source"]}
                    for n in news[:5]
                ],
            }
    except Exception:
        attr["dimensions"]["news"] = {"today_count": 0}

    # 维度4: 席位面（龙虎榜）
    try:
        dt_data = datacenter_get(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f"(TRADE_DATE='{TODAY}')(SECURITY_CODE='{code}')",
            page_size=5,
        )
        if dt_data:
            row = dt_data[0]
            attr["dimensions"]["dragon_tiger"] = {
                "on_board": True,
                "reason": row.get("EXPLANATION", ""),
                "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 1e4, 1),
                "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
            }
        else:
            attr["dimensions"]["dragon_tiger"] = {"on_board": False}
    except Exception:
        attr["dimensions"]["dragon_tiger"] = {"on_board": False}

    # 维度5: 技术面（腾讯行情）
    try:
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
            attr["dimensions"]["technical"] = {
                "price": price, "change_pct": change_pct,
                "turnover_pct": turnover, "vol_ratio": vol_ratio,
                "amplitude_pct": amplitude,
            }
    except Exception:
        attr["dimensions"]["technical"] = {"error": "行情获取失败"}

    # 综合归因
    attr["verdict"] = _generate_verdict(attr["dimensions"])
    return attr


def _fetch_today_fund_flow(code):
    """获取今日资金流：优先分钟级API（盘中），失败则尝试日级API（盘后），最终降级到push2 clist"""
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"

    # 方案1: 分钟级 push2 fflow kline（仅盘中有效，盘后可能返回空）
    try:
        params = {
            "secid": secid, "klt": "1",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "lmt": "250",
        }
        r = api_get("https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
                    params=params, timeout=10)
        d = r.json()
        klines = d.get("data", {}).get("klines", []) or []
        if klines:
            # 分钟级数据为日内累计值，取最后一条即为当日总额
            last = klines[-1]
            parts = last.split(",")
            if len(parts) >= 6:
                return {
                    "main_net": float(parts[1]) if parts[1] != "-" else 0,
                    "super_large_net": float(parts[5]) if parts[5] != "-" else 0,
                    "large_net": float(parts[4]) if parts[4] != "-" else 0,
                    "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                    "small_net": float(parts[2]) if parts[2] != "-" else 0,
                    "minutes": len(klines),
                }
    except Exception:
        pass

    # 方案2: 日级 push2his fflow（盘后可取昨日数据）
    try:
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "lmt": "5",
        }
        r = api_get("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                    params=params, timeout=10)
        d = r.json()
        klines = d.get("data", {}).get("klines", []) or []
        if klines:
            # 取最新一条日级数据
            last = klines[-1]
            parts = last.split(",")
            if len(parts) >= 7:
                return {
                    "main_net": float(parts[1]) if parts[1] != "-" else 0,
                    "small_net": float(parts[2]) if parts[2] != "-" else 0,
                    "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                    "large_net": float(parts[4]) if parts[4] != "-" else 0,
                    "super_large_net": float(parts[5]) if parts[5] != "-" else 0,
                    "days": 1,
                }
    except Exception:
        pass

    # 方案3: 降级到 push2 clist 获取个股当日主力净流入（仅 main_net，无明细拆分）
    try:
        prefixed = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
        params = {
            "pn": "1", "pz": "1", "po": "0", "np": "1",
            "fltt": "2", "invt": "2",
            "fs": f"b:04700101",  # 全市场
            "fields": "f12,f62",
        }
        r = api_get(PUSH2_CLIST, params=params, timeout=10)
        d = r.json()
        items = d.get("data", {}).get("diff", []) or []
        for it in items:
            if it.get("f12") == code:
                main_net = it.get("f62") or 0
                return {
                    "main_net": main_net, "super_large_net": 0,
                    "large_net": 0, "mid_net": 0, "small_net": 0,
                    "source": "push2_clist",
                }
    except Exception:
        pass

    return None


def _get_stock_concept_blocks(code):
    """获取个股所属概念板块"""
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3", "pi": "0", "pz": "200", "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    try:
        r = api_get("https://push2.eastmoney.com/api/qt/slist/get",
                    params=params, timeout=10)
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


def _fetch_stock_news(code):
    """获取个股近期新闻"""
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
    params = {"cb": cb, "param": inner}
    try:
        r = api_get("https://search-api-web.eastmoney.com/search/jsonp",
                    params=params, timeout=10)
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = json.loads(json_str)
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


def _generate_verdict(dims):
    """综合五维度数据生成归因结论"""
    verdict = {
        "primary_cause": "", "confidence": "",
        "supporting_evidence": [], "counter_evidence": [], "uncertainties": [],
    }
    fund = dims.get("fund_flow", {})
    sector = dims.get("sector", {})
    news = dims.get("news", {})
    dt = dims.get("dragon_tiger", {})
    tech = dims.get("technical", {})

    change_pct = tech.get("change_pct", 0)
    direction = "涨" if change_pct > 0 else "跌"
    causes = []

    # Rule 1: 龙虎榜
    if dt.get("on_board"):
        net_buy = dt.get("net_buy_wan", 0)
        reason = dt.get("reason", "")
        if net_buy > 5000 and abs(change_pct) > 5:
            causes.append({
                "cause": f"龙虎榜大额买入驱动{direction}停",
                "confidence": "高",
                "evidence": f"龙虎榜净买入{net_buy:.0f}万, 上榜原因: {reason}",
                "source": "东财龙虎榜 (一级来源)",
            })
        elif abs(net_buy) > 1000:
            causes.append({
                "cause": "龙虎榜资金博弈驱动波动",
                "confidence": "中",
                "evidence": f"龙虎榜净买卖{net_buy:.0f}万",
                "source": "东财龙虎榜 (一级来源)",
            })

    # Rule 2: 消息面
    if news.get("today_count", 0) > 0:
        highlights = news.get("today_highlights", [])
        if highlights:
            causes.append({
                "cause": f"消息面催化: {highlights[0]['title'][:60]}",
                "confidence": "中",
                "evidence": f"今日{news['today_count']}条新闻, 来源: {highlights[0]['source']}",
                "source": "东财个股新闻 (二级来源)",
            })

    # Rule 3: 主力资金
    if fund:
        inst_net = fund.get("institution_net_wan", 0)
        hm_net = fund.get("hot_money_net_wan", 0)
        retail_net = fund.get("retail_net_wan", 0)
        if abs(inst_net) > abs(hm_net) and abs(inst_net) > abs(retail_net) and abs(inst_net) > 100:
            causes.append({
                "cause": f"机构资金主导{direction}势",
                "confidence": "中",
                "evidence": f"机构(超大单)净{inst_net:.0f}万, 游资净{hm_net:.0f}万, 散户净{retail_net:.0f}万",
                "source": "push2 分钟级资金流 (二级来源)",
            })
        elif abs(hm_net) > abs(inst_net) and abs(hm_net) > abs(retail_net) and abs(hm_net) > 100:
            causes.append({
                "cause": f"游资主导炒作{direction}势",
                "confidence": "中",
                "evidence": f"游资(大单)净{hm_net:.0f}万, 机构净{inst_net:.0f}万",
                "source": "push2 分钟级资金流 (二级来源)",
            })
        # 机构vs散户反向
        if inst_net > 100 and retail_net < -100:
            causes.append({
                "cause": "机构吸筹中, 散户恐慌出局",
                "confidence": "中",
                "evidence": f"机构净流入{inst_net:.0f}万 vs 散户净流出{abs(retail_net):.0f}万",
                "source": "push2 分钟级资金流",
            })
        elif inst_net < -100 and retail_net > 100:
            causes.append({
                "cause": "机构派发中, 散户接盘",
                "confidence": "中",
                "evidence": f"机构净流出{abs(inst_net):.0f}万 vs 散户净流入{retail_net:.0f}万",
                "source": "push2 分钟级资金流",
            })

    # Rule 4: 板块联动
    if sector and "blocks" in sector:
        blocks = sector.get("blocks", [])
        if blocks:
            same_dir = [b for b in blocks
                       if (b["direction"] == "流入" and change_pct > 0) or
                          (b["direction"] == "流出" and change_pct < 0)]
            if len(same_dir) >= max(len(blocks) * 0.6, 2):
                causes.append({
                    "cause": f"板块联动效应: {len(same_dir)}/{len(blocks)}个概念板块同向",
                    "confidence": "中",
                    "evidence": f"同向板块: {', '.join(b['name'] for b in same_dir[:3])}",
                    "source": "东财概念板块资金流",
                })

    if causes:
        high_conf = [c for c in causes if c["confidence"] == "高"]
        main = high_conf[0] if high_conf else causes[0]
        verdict["primary_cause"] = main["cause"]
        verdict["confidence"] = main["confidence"]
        verdict["supporting_evidence"] = [
            {"dimension": c["cause"], "fact": c["evidence"], "source": c["source"]}
            for c in causes
        ]
    else:
        verdict["primary_cause"] = "多因素交织, 无单一明确主因, 建议持续跟踪"
        verdict["confidence"] = "低"
        verdict["uncertainties"].append("五维度中无显著信号, 可能为正常市场波动")

    if not dt.get("on_board"):
        verdict["uncertainties"].append("未上龙虎榜, 席位级别数据缺失")
    if not news.get("today_count", 0):
        verdict["uncertainties"].append("今日无明确消息催化")

    return verdict


# ============================================================
# 报告生成
# ============================================================

def format_yi(amount):
    """元转亿，保留2位小数"""
    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(amount)/1e8:.2f}亿"


def format_wan(amount):
    """元转万，整数"""
    return f"{amount/1e4:.0f}万"


def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'=' * 80}")
    print(f"  A股资金流向全景扫描 V2.1")
    print(f"  生成时间: {now_str}")
    print(f"  数据来源: 东方财富 data.eastmoney.com + push2.eastmoney.com")
    print(f"{'=' * 80}")

    # ━━━ 1. 概念板块资金流 ━━━
    print("\n[1/7] 拉取概念板块资金流...")
    concept_data = concept_sector_fund_flow()
    all_sectors = concept_data["sectors"]
    inflow_top20 = all_sectors[:20]
    outflow_top20 = all_sectors[-20:][::-1]

    # 补全丰富字段（涨跌幅/超大单/大单/中单/小单/涨跌家数/领涨股）
    print("  补全概念板块丰富字段...")
    bk_need = {s["code"] for s in all_sectors[:50]} | {s["code"] for s in all_sectors[-50:]}
    rich_map = get_sector_rich_data(bk_need)

    for s in inflow_top20 + outflow_top20:
        rich = rich_map.get(s["code"], {})
        s.update(rich)

    print(f"\n{'─' * 70}")
    print(f"  📊 概念板块主力净流入 TOP 20（共 {concept_data['total']} 个板块）")
    print(f"{'─' * 70}")
    for i, s in enumerate(inflow_top20):
        emoji = "🔥" if i < 3 else ("📈" if i < 10 else "  ")
        pct = s.get("change_pct", 0)
        up = s.get("up_count", 0)
        down = s.get("down_count", 0)
        leader = s.get("leader_stock", "")
        print(f"  {emoji} {i+1:2d}. {s['name']:<14s} 主力={format_yi(s['main_net']):>10s}  "
              f"涨跌={pct:>+6.2f}%  涨{up}跌{down}  领涨:{leader}")

    print(f"\n{'─' * 70}")
    print(f"  📉 概念板块主力净流出 TOP 20")
    print(f"{'─' * 70}")
    for i, s in enumerate(outflow_top20):
        emoji = "⚠️" if i < 3 else ("🔻" if i < 10 else "  ")
        pct = s.get("change_pct", 0)
        print(f"  {emoji} {i+1:2d}. {s['name']:<14s} 主力={format_yi(s['main_net']):>10s}  "
              f"涨跌={pct:>+6.2f}%")

    # ━━━ 2. 行业板块资金流 ━━━
    print("\n[2/7] 拉取行业板块资金流...")
    ind_data = industry_sector_fund_flow()
    ind_sectors = ind_data["sectors"]
    ind_inflow = ind_sectors[:10]
    ind_outflow = ind_sectors[-10:][::-1]

    print(f"\n{'─' * 70}")
    print(f"  🏢 行业板块主力净流入 TOP 10（共 {ind_data['total']} 个行业）")
    print(f"{'─' * 70}")
    for i, s in enumerate(ind_inflow):
        emoji = "🔥" if i < 3 else "  "
        print(f"  {emoji} {i+1:2d}. {s['name']:<12s} 主力={format_yi(s['main_net']):>10s}")

    print(f"\n{'─' * 70}")
    print(f"  📉 行业板块主力净流出 TOP 10")
    print(f"{'─' * 70}")
    for i, s in enumerate(ind_outflow):
        emoji = "⚠️" if i < 3 else "  "
        print(f"  {emoji} {i+1:2d}. {s['name']:<12s} 主力={format_yi(s['main_net']):>10s}")

    # ━━━ 3. 前5流入概念板块内个股 TOP10 ━━━
    print("\n[3/7] 拉取前5流入概念板块个股资金流...")
    sector_details = {}
    for rank, sec in enumerate(inflow_top20[:5]):
        sec_name = sec["name"]
        sec_code = sec["code"]
        print(f"  [{rank+1}/5] 分析 {sec_name}({sec_code})...")
        try:
            detail = sector_stock_fund_flow(sec_code)
            sector_details[sec_code] = {"sector_name": sec_name, **detail}

            top10 = detail["stocks"][:10]
            bottom5 = detail["stocks"][-5:][::-1] if len(detail["stocks"]) >= 5 else detail["stocks"][-len(detail["stocks"]):][::-1]

            print(f"\n{'─' * 70}")
            print(f"  🏭 {sec_name}({sec_code}) — 个股主力净流入 TOP 10（共 {detail['total']} 只）")
            print(f"{'─' * 70}")
            print(f"  {'代码':<8s} {'名称':<10s} {'主力净流入':>12s}  {'涨跌幅':>8s}  {'换手率':>8s}")
            print(f"  {'─' * 52}")
            for s in top10:
                print(f"  {s['code']:<8s} {s['name']:<10s} "
                      f"{format_wan(s['main_net']):>12s}  "
                      f"{s['change_pct']:>+7.2f}%  {s['turnover_pct']:>7.2f}%")

            print(f"\n  📉 主力净流出 TOP {len(bottom5)}:")
            for s in bottom5:
                print(f"  {s['code']:<8s} {s['name']:<10s} {format_wan(s['main_net']):>12s}  "
                      f"{s['change_pct']:>+7.2f}%")
        except Exception as e:
            print(f"    ⚠️ {sec_name} 个股数据获取失败: {e}")
            sector_details[sec_code] = {"sector_name": sec_name, "error": str(e)}

    # ━━━ 4. 龙虎榜 ━━━
    print("\n[4/7] 拉取全市场龙虎榜...")
    dt = daily_dragon_tiger_scan(date=TODAY, min_net_buy_wan=1000)

    print(f"\n{'─' * 70}")
    print(f"  🐉 全市场龙虎榜 ({dt['date']}) — 共 {dt['total']} 条（净买≥1000万）")
    print(f"{'─' * 70}")
    if dt["stocks"]:
        for i, s in enumerate(dt["stocks"][:15]):
            emoji = "🔴" if s['net_buy_wan'] > 10000 else "🟡"
            print(f"  {emoji} {i+1:2d}. {s['code']} {s['name']:<8s} "
                  f"净买={s['net_buy_wan']:>8.0f}万  "
                  f"涨跌={s['change_pct']:>+7.2f}%  "
                  f"换手={s['turnover_pct']}%")
            print(f"       上榜原因: {s['reason'][:60]}")
    else:
        print(f"  ⚠️ 今日暂无符合条件(净买≥1000万)的龙虎榜数据")

    # ━━━ 5. 重点个股席位分析 ━━━
    print("\n[5/7] 重点个股席位分析...")
    seat_results = {}
    top_dt = dt["stocks"][:5]
    if top_dt:
        print(f"\n{'─' * 70}")
        print("  🏦 重点龙虎榜个股 机构 vs 游资 席位分析")
        print(f"{'─' * 70}")
        for stock in top_dt:
            code = stock["code"]
            try:
                analysis = dragon_tiger_seat_analysis(code, lookback_days=30)
                seat_results[code] = analysis

                print(f"\n  【{code} {stock['name']}】")
                print(f"    龙虎榜净买: {stock['net_buy_wan']:.0f}万 | 涨跌: {stock['change_pct']:+.2f}%")
                print(f"    上榜原因: {stock['reason'][:60]}")
                print(f"    近30日上榜 {analysis['records_count']} 次")

                inst = analysis["institution"]
                hm = analysis["hot_money"]

                if inst["seats"]:
                    print(f"    🔴 机构: 买{inst['buy_total']:.0f}万 卖{inst['sell_total']:.0f}万 "
                          f"净持仓={inst['net_total']:.0f}万(还剩)")
                    for s in inst["seats"][:3]:
                        print(f"       {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")
                else:
                    print(f"    🔴 机构: 近30日无机构专用席位参与")

                if hm["seats"]:
                    print(f"    🟡 游资: 买{hm['buy_total']:.0f}万 卖{hm['sell_total']:.0f}万 "
                          f"净持仓={hm['net_total']:.0f}万(还剩)")
                    for s in hm["seats"][:5]:
                        print(f"       {s['name']}: 买{s['buy_wan']:.0f}万 卖{s['sell_wan']:.0f}万 净{s['net_wan']:.0f}万")
                else:
                    print(f"    🟡 游资: 近30日无游资营业部数据")
            except Exception as e:
                print(f"\n  【{code} {stock['name']}】席位分析失败: {e}")
                seat_results[code] = {"error": str(e)}

    # ━━━ 6. 个股归因分析 ━━━
    print("\n[6/7] 个股走势归因分析...")
    attr_results = {}
    attr_stocks = []

    # 龙虎榜前5
    for s in dt["stocks"][:5]:
        attr_stocks.append((s["code"], s["name"]))

    # 前3概念板块的流入TOP1
    for sec_code, detail in list(sector_details.items())[:3]:
        if detail.get("stocks") and not detail.get("error"):
            top = detail["stocks"][0]
            if (top["code"], top["name"]) not in attr_stocks:
                attr_stocks.append((top["code"], top["name"]))

    # 去重
    seen = set()
    unique = []
    for code, name in attr_stocks:
        if code not in seen:
            seen.add(code)
            unique.append((code, name))

    for i, (code, name) in enumerate(unique[:8]):
        print(f"  [{i+1}/{len(unique[:8])}] 归因分析 {name}({code})...")
        try:
            attr_results[code] = stock_daily_attribution(code, name)
        except Exception as e:
            print(f"    ⚠️ {code} 归因分析失败: {e}")
            attr_results[code] = {"error": str(e)}

    # 打印归因结果
    print(f"\n{'─' * 70}")
    print("  🔍 个股走势归因分析结果")
    print(f"{'─' * 70}")
    for code, attr in attr_results.items():
        if "error" in attr:
            print(f"  ⚠️ {code}: {attr['error']}")
            continue
        name = attr.get("name", "")
        dims = attr.get("dimensions", {})
        verdict = attr.get("verdict", {})
        tech = dims.get("technical", {})
        fund = dims.get("fund_flow", {})
        news = dims.get("news", {})
        dt_dim = dims.get("dragon_tiger", {})

        print(f"\n  【{code} {name}】")
        if tech:
            print(f"    行情: {tech.get('price', '?')}元  涨跌{tech.get('change_pct', 0):+.2f}%  "
                  f"换手{tech.get('turnover_pct', 0):.2f}%  量比{tech.get('vol_ratio', 0):.2f}")
        if fund:
            print(f"    资金: 主力净{fund.get('direction', '?')}{abs(fund.get('main_net_wan', 0)):.0f}万  "
                  f"机构{fund.get('institution_net_wan', 0):.0f}万 "
                  f"游资{fund.get('hot_money_net_wan', 0):.0f}万 "
                  f"散户{fund.get('retail_net_wan', 0):.0f}万")
        if news and news.get("today_highlights"):
            print(f"    新闻: {news['today_highlights'][0]['title'][:60]}")
        if dt_dim.get("on_board"):
            print(f"    龙虎榜: {dt_dim.get('reason', '')[:50]}")
        print(f"    🎯 归因: {verdict.get('primary_cause', '?')}  [置信度: {verdict.get('confidence', '?')}]")
        if verdict.get("supporting_evidence"):
            for ev in verdict["supporting_evidence"][:2]:
                print(f"      ✅ {ev['fact'][:80]}")
        if verdict.get("uncertainties"):
            for u in verdict["uncertainties"][:2]:
                print(f"      ❓ {u}")

    # ━━━ 7. 板块轮动速览 ━━━
    print(f"\n{'─' * 70}")
    print(f"  🔄 板块轮动速览")
    print(f"{'─' * 70}")

    inflowing = [s["name"] for s in inflow_top20[:5]]
    outflowing = [s["name"] for s in outflow_top20[:5]]
    total_in = sum(s["main_net"] for s in inflow_top20)
    total_out = sum(s["main_net"] for s in outflow_top20)

    print(f"  💰 资金主要流入: {', '.join(inflowing)}")
    print(f"  💸 资金主要流出: {', '.join(outflowing)}")

    if total_in > abs(total_out):
        print(f"  📊 倾向: 主力资金整体偏积极 "
              f"(TOP20流入 {total_in/1e8:.0f}亿 vs 流出 {abs(total_out)/1e8:.0f}亿)")
    else:
        print(f"  📊 倾向: 主力资金整体偏谨慎 "
              f"(TOP20流入 {total_in/1e8:.0f}亿 vs 流出 {abs(total_out)/1e8:.0f}亿)")

    # 主题分类
    top5_names = {s["name"] for s in inflow_top20[:5]}
    tech_themes = [n for n in top5_names if any(kw in n for kw in
        ["AI", "芯片", "半导体", "算力", "数据", "软件", "机器人", "智能", "互联", "通信",
         "5G", "6G", "光刻", "存储", "封装", "CPO", "液冷", "鸿蒙", "华为", "电子", "汽车"])]
    resource_themes = [n for n in top5_names if any(kw in n for kw in
        ["金属", "矿", "黄金", "铜", "锂", "稀土", "煤炭", "石油", "化工", "钢铁"])]
    finance_themes = [n for n in top5_names if any(kw in n for kw in
        ["金融", "证券", "银行", "保险", "券商", "地产"])]
    if tech_themes:
        print(f"  🖥️  科技方向活跃: {', '.join(tech_themes)}")
    if resource_themes:
        print(f"  ⛏️  资源方向活跃: {', '.join(resource_themes)}")
    if finance_themes:
        print(f"  💳 金融方向活跃: {', '.join(finance_themes)}")

    # ━━━ 风险声明 ━━━
    print(f"\n{'=' * 80}")
    print(f"  ⚠️ 研究声明")
    print(f"{'=' * 80}")
    print(f"  1. 数据来源: 东方财富 data.eastmoney.com + push2.eastmoney.com 公开API")
    print(f"  2. 龙虎榜仅覆盖触发涨跌停/振幅异常/换手异常的交易日")
    print(f"  3. 机构/游资分类基于龙虎榜席位代码(OPERATEDEPT_CODE='0'为机构专用席位)")
    print(f"  4. 归因分析为多维度交叉验证后的最大概率推断，不构成投资建议")
    print(f"  5. 所有数据仅供参考，资金流向 ≠ 未来涨跌方向")
    print(f"{'=' * 80}")

    # ━━━ 保存报告 ━━━
    report_dir = f"src/资金流向/{TODAY}-资金流向扫描"
    os.makedirs(report_dir, exist_ok=True)
    os.makedirs(f"{report_dir}/attribution", exist_ok=True)

    # 构建报告数据
    report = {
        "scan_time": now_str,
        "version": "V2.1",
        "concept_total": concept_data["total"],
        "concept_inflow_top20": inflow_top20,
        "concept_outflow_top20": outflow_top20,
        "industry_total": ind_data["total"],
        "industry_inflow": ind_inflow,
        "industry_outflow": ind_outflow,
        "sector_details": sector_details,
        "dragon_tiger": dt,
        "seat_analysis": seat_results,
        "attributions": attr_results,
    }

    # 保存 JSON
    json_path = os.path.join(report_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 JSON 数据已保存: {json_path}")

    # 保存 Markdown 报告
    md_path = os.path.join(report_dir, "report.md")
    save_markdown(report, md_path)
    print(f"📁 Markdown 报告已保存: {md_path}")

    # 更新 _index.md
    index_path = "src/资金流向/_index.md"
    os.makedirs("src/资金流向", exist_ok=True)
    index_entry = f"- [{TODAY}-资金流向扫描]({TODAY}-资金流向扫描/report.md) — 概念{concept_data['total']}个 + 行业{ind_data['total']}个 + 龙虎榜{dt['total']}条 + 归因{len(attr_results)}只"
    if not os.path.exists(index_path):
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(f"# 资金流向分析\n\n{index_entry}\n")
    else:
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        if index_entry not in content:
            with open(index_path, "a", encoding="utf-8") as f:
                f.write(f"\n{index_entry}")
    print(f"📁 索引已更新: {index_path}")

    return report


def save_markdown(report, md_path):
    """生成 Markdown 报告"""
    lines = []
    lines.append(f"# A股资金流向全景报告")
    lines.append(f"")
    lines.append(f"> 生成时间: {report['scan_time']}")
    lines.append(f"> 版本: {report['version']}")
    lines.append(f"> 数据来源: 东方财富 data.eastmoney.com + push2.eastmoney.com")
    lines.append(f"> 工具: capital-flow-tracker V2.1")
    lines.append(f"")

    # ━━━ 一、概念板块 ━━━
    lines.append(f"## 一、概念板块资金流向")
    lines.append(f"")
    lines.append(f"全市场共 **{report.get('concept_total', '?')}** 个概念板块。")
    lines.append(f"")

    lines.append(f"### 主力净流入 TOP 10")
    lines.append(f"")
    lines.append(f"| 排名 | 概念板块 | 主力净流入(亿) | 超大单(亿) | 涨跌幅(%) | 涨/跌家数 | 领涨股 |")
    lines.append(f"|------|---------|---------------|-----------|----------|----------|--------|")
    for i, s in enumerate(report["concept_inflow_top20"][:10]):
        pct = s.get("change_pct", 0)
        up = s.get("up_count", 0)
        down = s.get("down_count", 0)
        super_net = s.get("super_large_net", 0)
        leader = s.get("leader_stock", "")
        lines.append(f"| {i+1} | {s['name']} | {s['main_net']/1e8:.2f} | {super_net/1e8:.2f} | {pct:+.2f} | {up}/{down} | {leader} |")

    lines.append(f"")
    lines.append(f"### 主力净流出 TOP 10")
    lines.append(f"")
    lines.append(f"| 排名 | 概念板块 | 主力净流入(亿) | 涨跌幅(%) |")
    lines.append(f"|------|---------|---------------|----------|")
    for i, s in enumerate(report["concept_outflow_top20"][:10]):
        pct = s.get("change_pct", 0)
        lines.append(f"| {i+1} | {s['name']} | {s['main_net']/1e8:.2f} | {pct:+.2f} |")

    # ━━━ 二、行业板块 ━━━
    lines.append(f"")
    lines.append(f"## 二、行业板块资金流向")
    lines.append(f"")
    lines.append(f"全市场共 **{report.get('industry_total', '?')}** 个行业板块。")
    lines.append(f"")

    lines.append(f"### 主力净流入 TOP 10")
    lines.append(f"")
    lines.append(f"| 排名 | 行业板块 | 主力净流入(亿) |")
    lines.append(f"|------|---------|---------------|")
    for i, s in enumerate(report["industry_inflow"]):
        lines.append(f"| {i+1} | {s['name']} | {s['main_net']/1e8:.2f} |")

    lines.append(f"")
    lines.append(f"### 主力净流出 TOP 10")
    lines.append(f"")
    lines.append(f"| 排名 | 行业板块 | 主力净流入(亿) |")
    lines.append(f"|------|---------|---------------|")
    for i, s in enumerate(report["industry_outflow"]):
        lines.append(f"| {i+1} | {s['name']} | {s['main_net']/1e8:.2f} |")

    # ━━━ 三、重点板块个股 ━━━
    lines.append(f"")
    lines.append(f"## 三、重点概念板块个股资金流")
    lines.append(f"")
    for bk_code, detail in list(report.get("sector_details", {}).items()):
        sec_name = detail.get("sector_name", bk_code)
        if detail.get("error"):
            lines.append(f"### {sec_name}: ⚠️ 数据获取失败")
            continue
        lines.append(f"### {sec_name}({bk_code}) — 共{detail.get('total', '?')}只个股")
        lines.append(f"")
        lines.append(f"**主力净流入 TOP 10:**")
        lines.append(f"")
        lines.append(f"| 排名 | 代码 | 名称 | 主力净流入(万) | 涨跌幅(%) | 换手率(%) |")
        lines.append(f"|------|------|------|--------------|----------|----------|")
        for i, s in enumerate(detail.get("stocks", [])[:10]):
            lines.append(f"| {i+1} | {s['code']} | {s['name']} | {s['main_net']/1e4:.0f} | {s['change_pct']:+.2f} | {s['turnover_pct']:.2f} |")
        lines.append(f"")
        lines.append(f"**主力净流出 TOP 5:**")
        lines.append(f"")
        lines.append(f"| 排名 | 代码 | 名称 | 主力净流入(万) | 涨跌幅(%) |")
        lines.append(f"|------|------|------|--------------|----------|")
        stocks = detail.get("stocks", [])
        bottom5 = stocks[-5:][::-1] if len(stocks) >= 5 else stocks[::-1]
        for i, s in enumerate(bottom5):
            lines.append(f"| {i+1} | {s['code']} | {s['name']} | {s['main_net']/1e4:.0f} | {s['change_pct']:+.2f} |")
        lines.append(f"")

    # ━━━ 四、龙虎榜 ━━━
    lines.append(f"## 四、龙虎榜全市场扫描")
    lines.append(f"")
    dt = report.get("dragon_tiger", {})
    lines.append(f"日期: **{dt.get('date', '?')}** | 上榜: **{dt.get('total', 0)}** 条")
    lines.append(f"")
    lines.append(f"| 代码 | 名称 | 净买入(万) | 涨跌幅(%) | 换手率(%) | 上榜原因 |")
    lines.append(f"|------|------|-----------|----------|----------|---------|")
    for s in dt.get("stocks", [])[:15]:
        lines.append(f"| {s['code']} | {s['name']} | {s['net_buy_wan']:.0f} | {s['change_pct']:+.2f} | {s['turnover_pct']:.2f} | {s['reason'][:30]} |")

    # ━━━ 五、席位分析 ━━━
    lines.append(f"")
    lines.append(f"## 五、重点个股席位分析（机构 vs 游资）")
    lines.append(f"")
    for code, analysis in report.get("seat_analysis", {}).items():
        if "error" in analysis:
            lines.append(f"### {code}: ⚠️ {analysis['error']}")
            continue
        lines.append(f"### {code} (近30日上榜{analysis['records_count']}次)")
        lines.append(f"")
        inst = analysis["institution"]
        hm = analysis["hot_money"]
        lines.append(f"#### 🔴 机构资金")
        lines.append(f"- 累计买入: **{inst['buy_total']:.0f}万** | 累计卖出: **{inst['sell_total']:.0f}万** | 净持仓: **{inst['net_total']:.0f}万**")
        if inst["seats"]:
            lines.append(f"")
            lines.append(f"| 席位名称 | 买入(万) | 卖出(万) | 净持仓(万) |")
            lines.append(f"|---------|---------|---------|----------|")
            for s in inst["seats"][:5]:
                lines.append(f"| {s['name']} | {s['buy_wan']:.0f} | {s['sell_wan']:.0f} | {s['net_wan']:.0f} |")
        lines.append(f"")
        lines.append(f"#### 🟡 游资资金")
        lines.append(f"- 累计买入: **{hm['buy_total']:.0f}万** | 累计卖出: **{hm['sell_total']:.0f}万** | 净持仓: **{hm['net_total']:.0f}万**")
        if hm["seats"]:
            lines.append(f"")
            lines.append(f"| 席位名称 | 买入(万) | 卖出(万) | 净持仓(万) |")
            lines.append(f"|---------|---------|---------|----------|")
            for s in hm["seats"][:5]:
                lines.append(f"| {s['name']} | {s['buy_wan']:.0f} | {s['sell_wan']:.0f} | {s['net_wan']:.0f} |")
        lines.append(f"")

    # ━━━ 六、个股归因 ━━━
    lines.append(f"## 六、个股走势归因分析")
    lines.append(f"")
    lines.append(f"> 归因逻辑: 五维度交叉验证 — 资金面(30%) + 板块面(20%) + 消息面(25%) + 席位面(15%) + 技术面(10%)")
    lines.append(f"")
    for code, attr in report.get("attributions", {}).items():
        if "error" in attr:
            lines.append(f"### {code}: ⚠️ {attr['error']}")
            continue
        name = attr.get("name", "")
        dims = attr.get("dimensions", {})
        verdict = attr.get("verdict", {})

        lines.append(f"### {code} {name}")
        lines.append(f"")

        tech = dims.get("technical", {})
        fund = dims.get("fund_flow", {})
        news = dims.get("news", {})
        dt_dim = dims.get("dragon_tiger", {})
        sector_dim = dims.get("sector", {})

        lines.append(f"| 维度 | 关键数据 |")
        lines.append(f"|------|---------|")
        if tech:
            lines.append(f"| 📈 技术面 | {tech.get('price', '?')}元, 涨跌{tech.get('change_pct', 0):+.2f}%, 换手{tech.get('turnover_pct', 0):.2f}%, 量比{tech.get('vol_ratio', 0):.2f} |")
        if fund:
            lines.append(f"| 💰 资金面 | 主力净{fund.get('direction', '?')}{abs(fund.get('main_net_wan', 0)):.0f}万, 机构{fund.get('institution_net_wan', 0):.0f}万, 游资{fund.get('hot_money_net_wan', 0):.0f}万, 散户{fund.get('retail_net_wan', 0):.0f}万 |")
        if news:
            highlights = news.get("today_highlights", [])
            news_text = "; ".join(h["title"][:40] for h in highlights[:2]) if highlights else f"近7日{news.get('recent_count', 0)}条新闻"
            lines.append(f"| 📰 消息面 | {news_text} |")
        if dt_dim.get("on_board"):
            lines.append(f"| 🐉 席位面 | 上榜! {dt_dim.get('reason', '')[:40]} 净买{dt_dim.get('net_buy_wan', 0):.0f}万 |")
        if sector_dim.get("blocks"):
            blocks_text = ", ".join(f"{b['name']}({b['direction']})" for b in sector_dim["blocks"][:4])
            lines.append(f"| 🏭 板块面 | {blocks_text} |")

        lines.append(f"")
        lines.append(f"**🎯 归因结论:** {verdict.get('primary_cause', '?')}")
        lines.append(f"")
        lines.append(f"**置信度:** {verdict.get('confidence', '?')}")
        lines.append(f"")

        if verdict.get("supporting_evidence"):
            lines.append(f"**支撑证据:**")
            for ev in verdict["supporting_evidence"]:
                lines.append(f"- [{ev['dimension']}] {ev['fact']}")
            lines.append(f"")

        if verdict.get("uncertainties"):
            lines.append(f"**不确定因素:**")
            for u in verdict["uncertainties"]:
                lines.append(f"- {u}")
            lines.append(f"")

        lines.append(f"---")
        lines.append(f"")

    # ━━━ 结尾 ━━━
    lines.append(f"## ⚠️ 研究声明")
    lines.append(f"")
    lines.append(f"- 以上数据基于东方财富公开API（data.eastmoney.com / push2.eastmoney.com），延迟约3-5秒")
    lines.append(f"- 龙虎榜席位数据仅覆盖触发龙虎榜的交易日（涨跌停/振幅异常/换手异常），非日常全覆盖")
    lines.append(f"- '游资'和'机构'的区分基于龙虎榜席位代码（OPERATEDEPT_CODE='0'为机构专用席位），可能不完全准确")
    lines.append(f"- 归因分析为多维度交叉验证后的最大概率推断，行情受多重因素影响，单一归因无法覆盖所有可能")
    lines.append(f"- 所有数据仅供参考，**不构成投资建议**。资金流向 ≠ 未来涨跌方向")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"*Generated by capital-flow-tracker V2.1 on {report['scan_time']}*")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
    except Exception as e:
        print(f"\n\n❌ 扫描出错: {e}")
        import traceback
        traceback.print_exc()
