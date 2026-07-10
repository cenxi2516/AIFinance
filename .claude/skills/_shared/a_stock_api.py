#!/usr/bin/env python3
"""
A股统一数据接口模块 (Unified A-Stock Data API)
=============================================
版本: V1.0
创建日期: 2026-07-10

本模块从 a-stock-data skill 提取核心 helper 函数，消除各 Skill 中的重复数据拉取代码。

设计原则:
- 所有东财请求必须走 em_get()（内置限流防封）
- mootdx 客户端必须走 tdx_client()（规避 0.11.x BESTIP bug）
- 所有 Skill 和 scripts 统一 import 本模块，不再各自复制粘贴

使用方式:
    import sys
    sys.path.insert(0, '.claude/skills/_shared')
    from a_stock_api import em_get, tencent_quote, eastmoney_datacenter

数据源优先级:
    1. mootdx（通达信 TCP, 不封IP）→ K线/盘口/财务
    2. 腾讯财经（HTTP, 不封IP）→ 行情/PE/PB/市值
    3. 东财（HTTP, 有风控）→ 仅独有数据（资金流/龙虎榜/融资融券等）
"""

import time
import random
import socket
import json
import os
from datetime import datetime, timedelta
from typing import Optional

import requests
import urllib.request

# ============================================================
# 基础配置
# ============================================================

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ============================================================
# 1. 东财统一请求入口 (em_get) — 所有东财接口必须走此函数
# ============================================================

EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})

# 连接级自动重试
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _em_adapter = HTTPAdapter(max_retries=Retry(
        total=3, connect=3, backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    EM_SESSION.mount("https://", _em_adapter)
    EM_SESSION.mount("http://", _em_adapter)
except Exception:
    pass

EM_MIN_INTERVAL = 1.0          # 两次东财请求最小间隔(秒)
_em_last_call = [0.0]

def em_get(url: str, params: dict | None = None, headers: dict | None = None,
           timeout: int = 15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。
    所有 eastmoney.com 接口都应通过它请求，避免高频被封 IP。"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


# ============================================================
# 2. 东财数据中心统一查询
# ============================================================

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
PUSH2_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"
PUSH2EX = "https://push2ex.eastmoney.com/api/qt/clist/get"

def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                          filter_str: str = "", page_size: int = 50,
                          sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    """东财数据中心统一查询 — 龙虎榜/解禁/融资融券/大宗交易/股东户数/分红共用"""
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


def eastmoney_datacenter_paged(report_name: str, columns: str = "ALL",
                                filter_str: str = "", page_size: int = 50,
                                max_pages: int = 5, sort_columns: str = "",
                                sort_types: str = "-1") -> list[dict]:
    """东财数据中心分页查询"""
    all_data = []
    for page in range(1, max_pages + 1):
        params = {
            "reportName": report_name, "columns": columns,
            "filter": filter_str, "pageNumber": str(page), "pageSize": str(page_size),
            "sortColumns": sort_columns, "sortTypes": sort_types,
            "source": "WEB", "client": "WEB",
        }
        r = em_get(DATACENTER_URL, params=params, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            data = d["result"]["data"]
            all_data.extend(data)
            if len(data) < page_size:
                break
        else:
            break
    return all_data


# ============================================================
# 3. mootdx 客户端（通达信 TCP）
# ============================================================

_TDX_SERVERS = [
    ('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709),
    ('123.60.73.44', 7709),  ('116.205.163.254', 7709), ('121.36.225.169', 7709),
    ('123.60.70.228', 7709), ('124.71.9.153', 7709),    ('110.41.147.114', 7709),
    ('124.71.187.122', 7709),
]

def _probe(ip, port, timeout=2.0):
    """TCP 握手探测"""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def tdx_client(market='std'):
    """创建 mootdx 客户端，规避 0.11.x BESTIP.HQ 空串 bug"""
    from mootdx.quotes import Quotes
    for ip, port in _TDX_SERVERS:
        if _probe(ip, port):
            return Quotes.factory(market=market, server=(ip, port))
    try:
        return Quotes.factory(market=market, bestip=True)
    except Exception:
        pass
    try:
        return Quotes.factory(market=market)
    except Exception as e:
        raise RuntimeError(
            "所有 mootdx 服务器均不可达。海外网络通常全部超时（TCP 7709），"
            "请走国内代理或更新 _TDX_SERVERS 列表。原始错误：%s" % e
        )


# ============================================================
# 4. 市场前缀 + Ticker 归一化
# ============================================================

def get_prefix(code: str) -> str:
    """6位代码 → 市场前缀 (sh/sz/bj)"""
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    else:
        return "sz"


def normalize_code(raw: str) -> str:
    """Ticker 格式归一化为纯 6 位数字"""
    raw = raw.upper().strip()
    for prefix in ["SH", "SZ", "BJ"]:
        if raw.startswith(prefix):
            raw = raw[2:]
    if "." in raw:
        raw = raw.split(".")[0]
    return raw


# ============================================================
# 5. 腾讯财经行情（不封IP）
# ============================================================

def tencent_quote(codes: list[str]) -> dict[str, dict]:
    """
    批量拉取腾讯财经实时行情。
    支持个股/指数/ETF。返回 {code: {name, price, pe_ttm, pb, mcap, ...}}
    """
    prefixed = []
    for c in codes:
        c = normalize_code(c)
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    if not prefixed:
        return {}

    url = f"http://qt.gtimg.cn/q={','.join(prefixed)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk")
    except Exception as e:
        print(f"[tencent_quote] 请求失败: {e}")
        return {}

    FIELDS = [
        "name", "code", "price", "last_close", "open", "volume",
        "bid_vol", "ask_vol", "bid1", "bid1_vol", "bid2", "bid2_vol",
        "bid3", "bid3_vol", "bid4", "bid4_vol", "bid5", "bid5_vol",
        "ask1", "ask1_vol", "ask2", "ask2_vol", "ask3", "ask3_vol",
        "ask4", "ask4_vol", "ask5", "ask5_vol",
        "recent_trade", "change", "change_pct", "high", "low",
        "amount", "turnover", "pe_ttm", "unknown1", "pb", "mcap",
        "circ_mcap", "unknown2", "unknown3", "unknown4", "unknown5",
        "unknown6", "amplitude", "circulation", "total_share", "high52w",
        "low52w", "limit_up", "limit_down",
    ]

    results = {}
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line or '="' not in line:
            continue
        try:
            # 提取 var 名和值: v_sh600519="1~贵州茅台~..."
            var_name = line.split('="', 1)[0].strip()
            var_part = line.split('="', 1)[1].rstrip('";')
            values = var_part.split("~")

            # 从 var 名提取纯代码 (如 v_sh600519 → 600519)
            stock_code = ""
            for prefix in ["v_sh", "v_sz", "v_bj"]:
                if var_name.startswith(prefix):
                    stock_code = var_name[len(prefix):]
                    break

            if not stock_code:
                continue

            item = {}
            for i, fname in enumerate(FIELDS):
                item[fname] = values[i] if i < len(values) else ""

            # 数值字段类型转换
            num_fields = [
                "price", "last_close", "open", "high", "low",
                "change", "change_pct", "volume", "amount", "turnover",
                "pe_ttm", "pb", "mcap", "circ_mcap", "amplitude",
                "limit_up", "limit_down",
            ]
            for fname in num_fields:
                try:
                    item[fname] = float(item[fname]) if item[fname] else 0.0
                except (ValueError, TypeError):
                    item[fname] = 0.0

            results[stock_code] = item
        except Exception:
            continue

    return results


# ============================================================
# 6. 个股资金流 (东财独有)
# ============================================================

def stock_fund_flow_120d(code: str) -> list[dict]:
    """
    个股资金流日级数据（最近120个交易日）。
    数据源: 东财 push2his
    返回: [{date, main_net_yi, super_large_net, large_net, mid_net, small_net}]
    """
    code = normalize_code(code)
    if code.startswith("6"):
        secid = f"1.{code}"
    else:
        secid = f"0.{code}"

    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62",
        "lmt": "120",
        "klt": "101",
    }
    try:
        r = em_get(url, params=params, timeout=15)
        data = r.json()
        if data.get("data") and data["data"].get("klines"):
            flows = []
            for line in data["data"]["klines"]:
                parts = line.split(",")
                if len(parts) >= 6:
                    flows.append({
                        "date": parts[0],
                        "main_net_yi": float(parts[1]) / 10000 if parts[1] != "-" else 0,
                        "small_net_yi": float(parts[2]) / 10000 if parts[2] != "-" else 0,
                        "mid_net_yi": float(parts[3]) / 10000 if parts[3] != "-" else 0,
                        "large_net_yi": float(parts[4]) / 10000 if len(parts) > 4 and parts[4] != "-" else 0,
                        "super_large_net": float(parts[5]) / 10000 if len(parts) > 5 and parts[5] != "-" else 0,
                    })
            return flows
    except Exception as e:
        print(f"[stock_fund_flow_120d] {code} 失败: {e}")
    return []


def eastmoney_fund_flow_minute(code: str) -> dict:
    """
    个股资金流向（分钟级，当日盘中）。
    数据源: 东财 push2
    """
    code = normalize_code(code)
    if code.startswith("6"):
        secid = f"1.{code}"
    else:
        secid = f"0.{code}"

    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "lmt": "60",
        "klt": "1",
    }
    try:
        r = em_get(url, params=params, timeout=10)
        data = r.json()
        if data.get("data") and data["data"].get("klines"):
            lines = data["data"]["klines"]
            latest = lines[-1].split(",") if lines else []
            return {
                "available": True,
                "main_net_yi": float(latest[1]) / 10000 if len(latest) > 1 and latest[1] != "-" else 0,
                "small_net_yi": float(latest[2]) / 10000 if len(latest) > 2 and latest[2] != "-" else 0,
                "mid_net_yi": float(latest[3]) / 10000 if len(latest) > 3 and latest[3] != "-" else 0,
                "large_net_yi": float(latest[4]) / 10000 if len(latest) > 4 and latest[4] != "-" else 0,
                "super_large_net": float(latest[5]) / 10000 if len(latest) > 5 and latest[5] != "-" else 0,
            }
    except Exception as e:
        print(f"[eastmoney_fund_flow_minute] {code} 失败: {e}")
    return {"available": False}


# ============================================================
# 7. 行业/板块数据
# ============================================================

def industry_comparison(top_n: int = 50) -> list[dict]:
    """
    行业板块涨跌排名（东财行业分类）。
    数据源: 东财 push2
    """
    url = PUSH2_CLIST
    params = {
        "pn": "1", "pz": str(top_n),
        "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fid": "f3", "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18,f20,f21,f62,f184,f185",
    }
    try:
        r = em_get(url, params=params, timeout=15)
        data = r.json()
        if data.get("data") and data["data"].get("diff"):
            sectors = []
            for it in data["data"]["diff"]:
                sectors.append({
                    "code": it.get("f12", ""),
                    "name": it.get("f14", ""),
                    "change_pct": it.get("f3", 0),
                    "up_count": it.get("f185", 0),
                    "down_count": it.get("f184", 0),
                    "main_net": it.get("f62", 0),
                })
            return sectors
    except Exception as e:
        print(f"[industry_comparison] 失败: {e}")
    return []


def concept_sector_fund_flow(top_n: int = 100) -> list[dict]:
    """
    概念板块资金流向。
    数据源: 东财 bkzj
    """
    url = "https://data.eastmoney.com/dataapi/bkzj/getbkzj"
    params = {"code": "m:90+t:3", "key": "f62"}
    try:
        r = em_get(url, params=params, timeout=20)
        d = r.json()
        if d.get("rc") != 0:
            return []
        diff = d["data"]["diff"]
        sectors = []
        for it in diff[:top_n]:
            sectors.append({
                "code": it.get("f12", ""),
                "name": it.get("f14", ""),
                "main_net": it.get("f62", 0),
            })
        return sectors
    except Exception as e:
        print(f"[concept_sector_fund_flow] 失败: {e}")
    return []


def eastmoney_concept_blocks(code: str) -> list[dict]:
    """
    个股所属板块/概念归属（含BK码+涨跌幅+龙头股）。
    数据源: 东财 slist
    """
    code = normalize_code(code)
    if code.startswith("6"):
        secid = f"1.{code}"
    else:
        secid = f"0.{code}"

    url = "https://push2.eastmoney.com/api/qt/slist/get"
    params = {"spt": "3", "secid": secid, "fields": "f12,f14,f3,f128,f129,f130"}
    try:
        r = em_get(url, params=params, timeout=10)
        data = r.json()
        if data.get("data") and data["data"].get("diff"):
            blocks = []
            for it in data["data"]["diff"]:
                blocks.append({
                    "bk_code": it.get("f12", ""),
                    "bk_name": it.get("f14", ""),
                    "change_pct": it.get("f3", 0),
                    "leading_stock": it.get("f128", ""),
                    "leading_change": it.get("f129", 0),
                })
            return blocks
    except Exception as e:
        print(f"[eastmoney_concept_blocks] {code} 失败: {e}")
    return []


# ============================================================
# 8. 打板数据
# ============================================================

def em_zt_pool(date: str = None) -> list[dict]:
    """
    涨停池 — 连板数/封板资金/封板时间/炸板次数/行业/N天M板。
    date: YYYYMMDD, 默认今日
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    url = PUSH2EX
    params = {
        "pn": "1", "pz": "500",
        "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fid": "f3", "fs": f"m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,date:{date}",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18,f20,f21,f62,f184,f185",
    }
    try:
        r = em_get(url, params=params, timeout=15)
        data = r.json()
        if data.get("data") and data["data"].get("diff"):
            return data["data"]["diff"]
    except Exception as e:
        print(f"[em_zt_pool] 失败: {e}")
    return []


# ============================================================
# 9. 北向资金
# ============================================================

def hsgt_realtime() -> dict:
    """
    沪深股通当日实时分钟流向（含集合竞价 09:10-15:00）。
    数据源: 同花顺 hsgtApi
    """
    url = "https://hsgt.10jqka.com.cn/v1/data/hsgt/get_min_nets"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        data = r.json()
        if data.get("data"):
            items = data["data"]
            if items:
                latest = items[-1]
                return {
                    "available": True,
                    "hgt_net_yi": float(latest.get("hgt", 0)) / 1e8,
                    "sgt_net_yi": float(latest.get("sgt", 0)) / 1e8,
                    "total_net_yi": float(latest.get("hgt", 0) + latest.get("sgt", 0)) / 1e8,
                    "timestamp": latest.get("t", ""),
                }
    except Exception as e:
        print(f"[hsgt_realtime] 失败: {e}")
    return {"available": False}


# ============================================================
# 10. 新闻
# ============================================================

def eastmoney_stock_news(code: str, page_size: int = 20) -> list[dict]:
    """
    东财个股相关新闻。
    数据源: 东财 search-api-web
    """
    code = normalize_code(code)
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    params = {
        "cb": "jQuery",
        "param": json.dumps({
            "uid": "",
            "keyword": code,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "pageSize": page_size,
            "pageNum": 1,
        }),
    }
    try:
        r = em_get(url, params=params, timeout=10)
        text = r.text
        if "jQuery(" in text:
            text = text[text.index("(") + 1 : text.rindex(")")]
        data = json.loads(text)
        if data.get("result") and data["result"].get("cmsArticleWebOld"):
            articles = []
            for art in data["result"]["cmsArticleWebOld"][:page_size]:
                articles.append({
                    "title": art.get("title", ""),
                    "date": art.get("date", ""),
                    "url": art.get("url", ""),
                    "summary": art.get("content", ""),
                })
            return articles
    except Exception as e:
        print(f"[eastmoney_stock_news] {code} 失败: {e}")
    return []


# ============================================================
# 11. 完整估值分析
# ============================================================

def full_valuation(code: str) -> dict:
    """
    单票完整估值分析：腾讯行情 + 同花顺一致预期 + PE_fwd/PEG/PE消化。
    """
    code = normalize_code(code)
    quote = tencent_quote([code])
    if not quote or code not in quote:
        return {"available": False, "reason": "行情数据获取失败"}

    q = quote[code]
    price = q.get("price", 0)
    pe_ttm = q.get("pe_ttm", 0)
    pb = q.get("pb", 0)
    mcap = q.get("mcap", 0)

    # 同花顺一致预期EPS
    eps_forecast = None
    try:
        import pandas as pd
        url = f"https://basic.10jqka.com.cn/{code}/worth.html"
        dfs = pd.read_html(url)
        for df in dfs:
            if df.shape[1] >= 2:
                header = str(df.iloc[0, 0]) if len(df) > 0 else ""
                if "EPS" in header or "每股收益" in header:
                    eps_val = str(df.iloc[-1, -1]) if len(df) > 0 else ""
                    try:
                        eps_forecast = float(eps_val)
                    except (ValueError, TypeError):
                        pass
                    break
    except Exception:
        pass

    result = {
        "available": True,
        "code": code,
        "name": q.get("name", ""),
        "price": price,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "mcap_yi": round(mcap / 1e8, 2) if mcap else 0,
    }

    if eps_forecast and eps_forecast > 0 and price > 0:
        pe_fwd = price / eps_forecast
        result["eps_forecast"] = eps_forecast
        result["pe_fwd"] = round(pe_fwd, 2)

    return result


# ============================================================
# 12. K线数据 (mootdx / 东财)
# ============================================================

def stock_kline(code: str, days: int = 500) -> list[dict]:
    """
    个股日K线数据。
    优先用东财 push2his (前复权), 失败则回退 mootdx。

    返回: [{date, open, close, high, low, volume, amount, change_pct, turnover}]
    """
    code = normalize_code(code)
    if code.startswith("6"):
        secid = f"1.{code}"
    else:
        secid = f"0.{code}"

    # 优先: 东财 push2his (前复权)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": str(days),
    }
    try:
        r = em_get(url, params=params, timeout=15)
        data = r.json()
        if data.get("data") and data["data"].get("klines"):
            klines = []
            for line in data["data"]["klines"]:
                parts = line.split(",")
                if len(parts) >= 11:
                    klines.append({
                        "date": parts[0],
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "volume": float(parts[5]),
                        "amount": float(parts[6]),
                        "change_pct": float(parts[8]) if parts[8] != "-" else 0,
                        "turnover": float(parts[10]) if len(parts) > 10 and parts[10] != "-" else 0,
                    })
            return klines
    except Exception:
        pass

    # 回退: mootdx (TCP, 不封IP)
    try:
        client = tdx_client()
        bars = client.bars(symbol=code, frequency=9, offset=days)
        klines = []
        for bar in bars:
            klines.append({
                "date": str(bar.get("datetime", ""))[:10],
                "open": float(bar.get("open", 0)),
                "close": float(bar.get("close", 0)),
                "high": float(bar.get("high", 0)),
                "low": float(bar.get("low", 0)),
                "volume": float(bar.get("vol", 0)),
                "amount": float(bar.get("amount", 0)),
                "change_pct": 0,
                "turnover": 0,
            })
        return klines
    except Exception as e:
        print(f"[stock_kline] {code} 东财+mootdx均失败: {e}")

    return []


# ============================================================
# 自检
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("A股统一数据接口模块 V1.0 — 自检")
    print("=" * 60)

    # 测试腾讯行情
    print("\n[1/3] 测试腾讯行情...")
    quotes = tencent_quote(["600519", "000858"])
    for code, q in quotes.items():
        print(f"  {code} {q.get('name', '?')}: price={q.get('price')}, PE={q.get('pe_ttm')}, PB={q.get('pb')}")

    # 测试行业板块
    print("\n[2/3] 测试行业板块排名...")
    sectors = industry_comparison(10)
    for s in sectors[:5]:
        print(f"  {s['name']}: {s['change_pct']:.2f}%")

    # 测试个股资金流
    print("\n[3/3] 测试个股资金流...")
    flows = stock_fund_flow_120d("600519")
    if flows:
        latest = flows[-1]
        print(f"  600519 最新: date={latest['date']}, 主力净额={latest['main_net_yi']:.2f}亿")
        print(f"  共 {len(flows)} 日数据")

    print("\n✅ 自检完成")
