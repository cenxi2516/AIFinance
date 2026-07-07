#!/usr/bin/env python3
"""
A股涨停板全景报告 V2.0
数据源：mootdx(通达信TCP) + 腾讯财经(HTTP) + 同花顺热点 + 东财slist + 龙虎榜
用法：python3 limit_up_daily.py [YYYY-MM-DD]
默认：今天
"""
import time, json, sys, re, os
from datetime import datetime, timedelta
from collections import defaultdict
import urllib.request
import requests

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════
BATCH_SIZE = 50          # 腾讯API每批查询数
BATCH_DELAY = 0.25       # 批次间延迟(秒)
EM_DELAY = 1.5           # 东财API延迟(秒)
SLIST_SAMPLE_MAX = 40    # slist采样最大数量（控制总耗时）
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def parse_date(date_str=None):
    """解析日期参数，返回 (YYYY-MM-DD, YYYYMMDD, datetime)"""
    if date_str:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    else:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d"), dt.strftime("%Y%m%d"), dt

def output_dir(date_str):
    """计算输出目录路径"""
    return os.path.join(REPO_ROOT, "src", "涨停分析", f"{date_str}-涨停复盘")

def prev_report_dir(date_str):
    """查找上一个交易日的 report.json 路径"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    # 向前查找最多5天
    for i in range(1, 6):
        prev = dt - timedelta(days=i)
        prev_str = prev.strftime("%Y-%m-%d")
        path = os.path.join(output_dir(prev_str), "report.json")
        if os.path.exists(path):
            return path, prev_str
    return None, None

# ══════════════════════════════════════════════════════════════
# Step 1: 获取股票列表 (mootdx)
# ══════════════════════════════════════════════════════════════

def get_stock_list():
    """通过 mootdx 获取全A股列表"""
    from mootdx.quotes import Quotes
    client = Quotes.factory(market='std')
    all_stocks = []
    for market in [0, 1]:
        try:
            stocks = client.stocks(market=market)
            for _, row in stocks.iterrows():
                code = str(row['code'])
                if len(code) == 6 and code.isdigit() and not code.startswith('9'):
                    name = row.get('name', '')
                    if name and '指数' not in name and not code.startswith('2'):
                        all_stocks.append(code)
        except Exception as e:
            print(f"  [WARN] mootdx market={market} 失败: {e}")
    return sorted(set(all_stocks))

# ══════════════════════════════════════════════════════════════
# Step 2: 腾讯批量行情
# ══════════════════════════════════════════════════════════════

def qq_batch_quotes(codes: list) -> dict:
    """腾讯股票API批量行情查询，返回 {code: {...}}"""
    results = {}
    for i in range(0, len(codes), BATCH_SIZE):
        batch = codes[i:i + BATCH_SIZE]
        qq_codes = []
        for c in batch:
            if c.startswith('6'):
                qq_codes.append(f'sh{c}')
            elif c.startswith('0') or c.startswith('3'):
                qq_codes.append(f'sz{c}')
            elif c.startswith('4') or c.startswith('8'):
                qq_codes.append(f'bj{c}')
        if not qq_codes:
            continue

        url = f"http://web.sqt.gtimg.cn/q={','.join(qq_codes)}"
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'Referer': 'https://quote.eastmoney.com/',
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                text = r.read().decode('gbk')
        except Exception as e:
            print(f"  [WARN] 腾讯API批次{i//BATCH_SIZE+1}失败: {e}")
            continue

        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or '=' not in line:
                continue
            try:
                var_name, data = line.split('=', 1)
                data = data.strip('"').strip(';')
                fields = data.split('~')
                if len(fields) < 40:
                    continue
                code = fields[2]
                results[code] = {
                    'name': fields[1],
                    'price': float(fields[3]) if fields[3] else 0,
                    'pre_close': float(fields[4]) if fields[4] else 0,
                    'change_pct': float(fields[32]) if fields[32] else 0,
                    'high': float(fields[33]) if fields[33] else 0,
                    'low': float(fields[34]) if fields[34] else 0,
                    'volume': float(fields[6]) if fields[6] else 0,
                    'amount': float(fields[37]) if fields[37] else 0,
                    'turnover': float(fields[38]) if fields[38] else 0,
                    'pe': float(fields[39]) if len(fields) > 39 and fields[39] else 0,
                    'mcap': float(fields[45]) if len(fields) > 45 and fields[45] else 0,
                    'limit_up': float(fields[47]) if len(fields) > 47 and fields[47] else 0,
                    'limit_down': float(fields[48]) if len(fields) > 48 and fields[48] else 0,
                }
            except (ValueError, IndexError):
                continue
        time.sleep(BATCH_DELAY)
    return results

# ══════════════════════════════════════════════════════════════
# Step 3: 涨停筛选
# ══════════════════════════════════════════════════════════════

def is_limit_up(change_pct, price, limit_up_price, code):
    """判断是否涨停"""
    if change_pct >= 9.5:
        return True
    if limit_up_price > 0 and price > 0:
        if abs(price - limit_up_price) / limit_up_price < 0.005:
            return True
    return False

def get_market_type(code):
    if code.startswith('688'):
        return '科创板'
    elif code.startswith('6'):
        return '主板'
    elif code.startswith('0'):
        return '主板'
    elif code.startswith('3'):
        return '创业板'
    elif code.startswith('4') or code.startswith('8'):
        return '北交所'
    return '其他'

def filter_limit_up_stocks(all_quotes):
    """筛选涨停股票，返回基础信息列表"""
    stocks = []
    for code, info in all_quotes.items():
        if is_limit_up(info['change_pct'], info['price'], info['limit_up'], code):
            stocks.append({
                'code': code,
                'name': info['name'],
                'price': info['price'],
                'pre_close': info['pre_close'],
                'change_pct': round(info['change_pct'], 2),
                'limit_up_price': info['limit_up'],
                'volume': info['volume'],
                'amount': info['amount'],
                'turnover': round(info['turnover'], 2),
                'pe': round(info['pe'], 2) if info['pe'] else 0,
                'mcap': info['mcap'],
                'market': get_market_type(code),
            })
    stocks.sort(key=lambda x: x['change_pct'], reverse=True)
    return stocks

# ══════════════════════════════════════════════════════════════
# Step 4: 连板数计算（对比昨日 report.json）
# ══════════════════════════════════════════════════════════════

def calc_consecutive_days(stocks, date_str):
    """
    通过对比历史 report.json 计算连板天数。
    向前回溯最多5天，建立 {code: last_date} 映射。
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    code_days = {}  # code -> 已连续涨停天数（不含今天）

    for i in range(1, 6):
        prev_date = dt - timedelta(days=i)
        prev_str = prev_date.strftime("%Y-%m-%d")
        prev_json = os.path.join(output_dir(prev_str), "report.json")
        if not os.path.exists(prev_json):
            break

        try:
            with open(prev_json) as f:
                prev_data = json.load(f)
            prev_codes = {s['code'] for s in prev_data.get('stocks', [])}

            # 检查当前 stock 中有哪些在 prev_codes 中
            for s in stocks:
                if s['code'] in prev_codes:
                    if s['code'] not in code_days:
                        code_days[s['code']] = 0
                    code_days[s['code']] += 1
        except Exception:
            break

    # 应用到 stocks
    for s in stocks:
        s['consecutive_days'] = code_days.get(s['code'], 0) + 1  # +1 包括今天
        s['prev_day_limit_up'] = code_days.get(s['code'], 0) > 0

    return stocks

# ══════════════════════════════════════════════════════════════
# Step 5: 同花顺热点归因
# ══════════════════════════════════════════════════════════════

def fetch_ths_hot_reasons(date_compact, timeout=15):
    """
    获取同花顺当日热点原因。
    返回 {code: {reason, market}} 映射。
    """
    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date_compact}/orderby/date/orderway/desc/charset/GBK/"
    try:
        r = requests.get(url, headers={
            "User-Agent": UA,
            "Referer": "http://data.10jqka.com.cn/market/longhu/",
        }, timeout=timeout)
        data = r.json()
        result = {}
        for item in data.get("data", []):
            code = item.get("code", "")
            if code:
                result[code] = {
                    "reason": item.get("reason", ""),
                    "market_tag": item.get("market", ""),
                }
        return result
    except Exception as e:
        print(f"  [WARN] 同花顺热点获取失败: {e}")
        return {}

def parse_concepts_from_reason(reason):
    """
    从同花顺 reason 字段解析概念标签。
    格式如: "光伏+储能+业绩预增+3连板"
    过滤掉连板数字标签（如 "3连板", "5天4板"）。
    """
    if not reason:
        return []
    parts = [p.strip() for p in reason.split('+')]
    concepts = []
    for p in parts:
        # 过滤连板标签: "N连板", "N天N板"
        if re.match(r'^\d+连板$', p):
            continue
        if re.match(r'^\d+天\d+板$', p):
            continue
        if p:
            concepts.append(p)
    return concepts

def enrich_ths_reasons(stocks, date_compact):
    """将同花顺热点归因匹配到涨停股"""
    ths_data = fetch_ths_hot_reasons(date_compact)
    matched = 0
    for s in stocks:
        ths_info = ths_data.get(s['code'])
        if ths_info:
            s['limit_up_reason'] = ths_info['reason']
            s['reason_src'] = '同花顺热点'
            s['concepts'] = parse_concepts_from_reason(ths_info['reason'])
            s['concepts_src'] = '同花顺reason解析'
            matched += 1
        else:
            s['limit_up_reason'] = ''
            s['reason_src'] = '未匹配'
            s['concepts'] = []
            s['concepts_src'] = '未匹配'
    print(f"  → 同花顺归因匹配: {matched}/{len(stocks)} 只")
    return stocks

# ══════════════════════════════════════════════════════════════
# Step 6: 龙虎榜交叉验证
# ══════════════════════════════════════════════════════════════

def fetch_dragon_tiger(date_str, timeout=15):
    """
    获取全市场龙虎榜数据。
    返回 {code: {reason, net_buy_wan, buy_wan, sell_wan, change_pct, turnover}} 映射。
    """
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "ALL",
        "filter": f"(TRADE_DATE='{date_str}')",
        "pageNumber": 1,
        "pageSize": 500,
        "sortColumns": "BILLBOARD_NET_AMT",
        "sortTypes": "-1",
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, headers={
            "User-Agent": UA,
            "Referer": "https://data.eastmoney.com/",
        }, timeout=timeout)
        d = r.json()
        data_list = d.get("result", {}).get("data", [])
        result = {}
        for item in data_list:
            code = item.get("SECURITY_CODE", "")
            if code:
                result[code] = {
                    "reason": item.get("EXPLAIN", ""),
                    "net_buy_wan": round((item.get("BILLBOARD_NET_AMT", 0) or 0) / 10000, 2),
                    "buy_wan": round((item.get("BILLBOARD_BUY_AMT", 0) or 0) / 10000, 2),
                    "sell_wan": round((item.get("BILLBOARD_SELL_AMT", 0) or 0) / 10000, 2),
                    "change_pct": item.get("CHANGE_RATE", 0) or 0,
                    "turnover": item.get("TURNOVERRATE", 0) or 0,
                    "close_price": item.get("CLOSE_PRICE", 0),
                }
        return result
    except Exception as e:
        print(f"  [WARN] 龙虎榜获取失败: {e}")
        return {}

def enrich_dragon_tiger(stocks, date_str):
    """将龙虎榜数据交叉匹配到涨停股"""
    dt_data = fetch_dragon_tiger(date_str)
    matched = 0
    for s in stocks:
        dt_info = dt_data.get(s['code'])
        if dt_info:
            s['on_dragon_tiger_board'] = True
            s['dragon_tiger_detail'] = dt_info
            matched += 1
        else:
            s['on_dragon_tiger_board'] = False
            s['dragon_tiger_detail'] = None
    print(f"  → 龙虎榜匹配: {matched}/{len(stocks)} 只（全市场共{len(dt_data)}只上榜）")
    return stocks

# ══════════════════════════════════════════════════════════════
# Step 7: 行业/概念补充（东财 slist 采样）
# ══════════════════════════════════════════════════════════════

def fetch_slist_boards(code, timeout=15):
    """
    获取单只股票的东财板块归属（行业+概念+地域混合）。
    返回 [(name, code), ...] 列表。
    """
    market_code = "0" if code.startswith("0") or code.startswith("3") else "1"
    url = "https://push2.eastmoney.com/api/qt/slist/get"
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3",
        "pi": "0", "pz": "50",
        "fields": "f12,f14,f3,f128",
    }
    try:
        r = requests.get(url, params=params, headers={
            "User-Agent": UA,
            "Referer": "https://quote.eastmoney.com/",
        }, timeout=timeout)
        d = r.json()
        diff = d.get("data", {}).get("diff", {})
        boards = []
        for k, v in diff.items():
            if isinstance(v, dict):
                boards.append((v.get("f14", ""), v.get("f12", "")))
        return boards
    except Exception as e:
        return []

def enrich_industry_slist_sample(stocks, max_sample=SLIST_SAMPLE_MAX):
    """
    对关键股票采样获取东财板块归属。
    优先级：连板高标 > 大市值 > 随机补充
    """
    # 建立采样优先级列表
    priority = []
    for s in stocks:
        score = s.get('consecutive_days', 1) * 10 + min(s.get('mcap', 0) / 10, 100)
        priority.append((score, s))
    priority.sort(key=lambda x: x[0], reverse=True)

    to_sample = [s for _, s in priority[:max_sample]]

    # 检查哪些需要补充（同花顺已经给了概念的就不重复采样）
    need_sample = []
    for s in to_sample:
        if len(s.get('concepts', [])) < 3:
            need_sample.append(s)

    print(f"  → slist 采样目标: {len(need_sample)} 只（优先高标+大市值）...")

    sampled = 0
    for i, s in enumerate(need_sample):
        boards = fetch_slist_boards(s['code'])
        if boards:
            # 分离行业和概念
            industries = []
            concepts_from_slist = []
            for name, code in boards:
                # 东财板块代码规则: BK开头是行业/概念板块
                if code.startswith("BK"):
                    # 带"板块"后缀的通常是地域
                    if "板块" in name:
                        concepts_from_slist.append(name)
                    elif any(kw in name for kw in ["行业", "制造", "科技", "金融", "医药", "化工",
                                                      "食品", "饮料", "汽车", "地产", "能源", "材料",
                                                      "通信", "电子", "软件", "互联网", "传媒", "农业"]):
                        industries.append(name)
                    else:
                        concepts_from_slist.append(name)

            if industries:
                s['industry'] = industries[0]  # 取第一个行业
                s['industry_src'] = '东财slist'
            if concepts_from_slist:
                # 合并到已有概念
                existing = set(s.get('concepts', []))
                for c in concepts_from_slist:
                    if c not in existing and len(s.get('concepts', [])) < 10:
                        s['concepts'].append(c)
                s['concepts_src'] = (s.get('concepts_src', '') + '+东财slist').strip('+')
            sampled += 1

        if i < len(need_sample) - 1:
            time.sleep(EM_DELAY)

    print(f"  → slist 成功采样: {sampled} 只")
    return stocks

# ══════════════════════════════════════════════════════════════
# Step 8: 聚合分析
# ══════════════════════════════════════════════════════════════

def build_aggregations(stocks):
    """构建行业排名、概念排名、连板分布等聚合数据"""
    # 市场分布
    by_market = defaultdict(int)
    for s in stocks:
        by_market[s['market']] += 1

    # 连板分布
    by_consecutive = {"1": 0, "2": 0, "3": 0, "4+": 0}
    for s in stocks:
        d = s.get('consecutive_days', 1)
        if d >= 4:
            by_consecutive["4+"] += 1
        else:
            by_consecutive[str(d)] = by_consecutive.get(str(d), 0) + 1

    # 行业排名
    industry_map = defaultdict(list)
    for s in stocks:
        ind = s.get('industry', '')
        if ind:
            industry_map[ind].append(s)
        else:
            industry_map['未分类'].append(s)

    industry_ranking = []
    for ind_name, ind_stocks in industry_map.items():
        industry_ranking.append({
            "industry": ind_name,
            "count": len(ind_stocks),
            "top_stocks": [s['code'] for s in sorted(ind_stocks, key=lambda x: x['consecutive_days'], reverse=True)[:5]],
        })
    industry_ranking.sort(key=lambda x: x['count'], reverse=True)

    # 概念排名
    concept_map = defaultdict(list)
    for s in stocks:
        for c in s.get('concepts', []):
            concept_map[c].append(s)

    concept_ranking = []
    for cn_name, cn_stocks in concept_map.items():
        concept_ranking.append({
            "concept": cn_name,
            "count": len(cn_stocks),
            "top_stocks": [s['code'] for s in sorted(cn_stocks, key=lambda x: x['consecutive_days'], reverse=True)[:5]],
        })
    concept_ranking.sort(key=lambda x: x['count'], reverse=True)

    # 高标追踪
    high_mark = [s for s in stocks if s.get('consecutive_days', 1) >= 3]
    high_mark.sort(key=lambda x: x['consecutive_days'], reverse=True)

    # 龙虎榜汇总
    dt_stocks = [s for s in stocks if s.get('on_dragon_tiger_board')]
    dt_top_buy = sorted(dt_stocks, key=lambda x: x.get('dragon_tiger_detail', {}).get('net_buy_wan', 0), reverse=True)[:10]

    # 数据质量
    total = len(stocks)
    industry_cov = sum(1 for s in stocks if s.get('industry')) / max(total, 1) * 100
    concept_cov = sum(1 for s in stocks if s.get('concepts')) / max(total, 1) * 100
    reason_cov = sum(1 for s in stocks if s.get('limit_up_reason')) / max(total, 1) * 100

    return {
        "by_market": dict(by_market),
        "by_consecutive": by_consecutive,
        "industry_ranking": industry_ranking,
        "concept_ranking": concept_ranking,
        "high_mark_tracking": high_mark,
        "dragon_tiger_cross": {
            "total_on_board": len(dt_stocks),
            "top_net_buy": [
                {
                    "code": s['code'],
                    "name": s['name'],
                    "net_buy_wan": s.get('dragon_tiger_detail', {}).get('net_buy_wan', 0),
                }
                for s in dt_top_buy
            ],
        },
        "data_quality": {
            "industry_coverage_pct": round(industry_cov, 1),
            "concept_coverage_pct": round(concept_cov, 1),
            "reason_coverage_pct": round(reason_cov, 1),
            "dragon_tiger_coverage_pct": round(len(dt_stocks) / max(total, 1) * 100, 1),
            "missing_fields": ["seal_amount", "first_limit_time", "reopen_count"],
            "missing_reason": "东财push2ex涨停池API失效(rc=102)，盘中动态字段不可获取",
        },
    }

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main(date_str=None):
    date_ymd, date_compact, dt = parse_date(date_str)

    print("=" * 70)
    print(f"  📊 A股涨停板全景分析 V2.0 — {date_ymd}")
    print(f"  数据源: mootdx(TCP) + 腾讯(HTTP) + 同花顺热点 + 东财slist + 龙虎榜")
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # ━━ Step 1: 获取股票列表 ━━
    print(f"\n[1/7] 获取全A股列表 (mootdx)...")
    try:
        all_codes = get_stock_list()
        print(f"  → 共 {len(all_codes)} 只A股")
    except Exception as e:
        print(f"  [ERROR] mootdx 失败: {e}")
        print(f"  使用备用静态列表...")
        all_codes = ['600519', '000858', '601318', '300750', '688981',
                     '601398', '600036', '000333', '002415', '601012']

    # ━━ Step 2: 批量获取行情 ━━
    print(f"\n[2/7] 批量获取行情 (腾讯API, {len(all_codes)}只, {BATCH_SIZE}只/批)...")
    all_quotes = qq_batch_quotes(all_codes)
    print(f"  → 成功获取 {len(all_quotes)} 只行情")

    # ━━ Step 3: 涨停筛选 ━━
    print(f"\n[3/7] 筛选涨停股票...")
    stocks = filter_limit_up_stocks(all_quotes)
    real_stocks = [s for s in stocks if not s['name'].startswith('N') and not s['name'].startswith('C')]
    new_stocks = [s for s in stocks if s['name'].startswith('N') or s['name'].startswith('C')]
    print(f"  → 涨停: {len(stocks)} 只（真实涨停: {len(real_stocks)}，新股: {len(new_stocks)}）")

    # ━━ Step 4: 连板计算 ━━
    print(f"\n[4/7] 计算连板数 (对比历史report.json)...")
    real_stocks = calc_consecutive_days(real_stocks, date_ymd)
    by_cons = defaultdict(int)
    for s in real_stocks:
        d = s.get('consecutive_days', 1)
        key = str(d) if d < 4 else '4+'
        by_cons[key] += 1
    cons_summary = ', '.join(f"{k}连板:{v}" for k, v in sorted(by_cons.items()))
    print(f"  → 连板分布: {cons_summary}")

    # ━━ Step 5: 同花顺热点归因 ━━
    print(f"\n[5/7] 获取涨停归因 (同花顺热点)...")
    real_stocks = enrich_ths_reasons(real_stocks, date_compact)

    # ━━ Step 6: 龙虎榜交叉 ━━
    print(f"\n[6/7] 龙虎榜交叉验证...")
    real_stocks = enrich_dragon_tiger(real_stocks, date_ymd)

    # ━━ Step 7: 行业/概念采样补充 ━━
    print(f"\n[7/7] 行业/概念补充 (东财slist采样)...")
    real_stocks = enrich_industry_slist_sample(real_stocks)

    # ━━ 聚合分析 ━━
    aggregations = build_aggregations(real_stocks)

    # ━━ 组装报告 ━━
    report = {
        "report_date": date_compact,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_sources": {
            "quotes": "腾讯财经(web.sqt.gtimg.cn)",
            "stock_list": "mootdx(通达信TCP:7709)",
            "reasons": "同花顺热点(zx.10jqka.com.cn)",
            "dragon_tiger": "东财datacenter",
            "industry_concept": "东财slist(采样) + 同花顺reason解析",
        },
        "total": len(real_stocks),
        "new_listings": len(new_stocks),
        "stocks": real_stocks,
        **aggregations,
    }

    # ━━ 输出 ━━
    out_dir = output_dir(date_ymd)
    os.makedirs(out_dir, exist_ok=True)

    report_path = os.path.join(out_dir, "report.json")
    with open(report_path, "w", encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 数据已保存: {report_path}")
    print(f"  📊 涨停总数: {len(real_stocks)} 只 (新股 {len(new_stocks)} 只不计入)")
    print(f"  📊 连板: {cons_summary}")
    print(f"  📊 龙虎榜上榜: {aggregations['dragon_tiger_cross']['total_on_board']}/{len(real_stocks)} 只")
    print(f"  📊 数据覆盖率: 归因{aggregations['data_quality']['reason_coverage_pct']}% "
          f"行业{aggregations['data_quality']['industry_coverage_pct']}% "
          f"概念{aggregations['data_quality']['concept_coverage_pct']}%")

    print(f"\n{'=' * 70}")
    print(f"  ✅ 数据采集完成！")
    print(f"  下一步: python3 scripts/print_limit_up_report.py --input {report_path}")
    print(f"{'=' * 70}")

    return report

if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(date_arg)
