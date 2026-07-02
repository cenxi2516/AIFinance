#!/usr/bin/env python3
"""
A股涨停板全景报告 V1.0
数据源：mootdx(TCP通达信) + 腾讯财经(HTTP不封IP)
日期：2026-07-02
"""
import time, json, sys, re
from datetime import datetime, timedelta
from collections import defaultdict

# ━━━ 腾讯财经 API（不封IP，批量查询）━━━
import urllib.request

def qq_batch_quotes(codes: list) -> dict:
    """
    腾讯股票API批量行情查询
    返回: {code: {name, price, pre_close, change_pct, high, low, volume, amount, turnover, pe, mcap, limit_up, limit_down}}
    """
    # 腾讯API单次最多约60只股票，需分批
    results = {}
    batch_size = 50
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        # 腾讯格式: sh600519,sz000858
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
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://quote.eastmoney.com/',
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                text = r.read().decode('gbk')
        except Exception as e:
            print(f"  [WARN] 腾讯API请求失败: {e}")
            continue
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or '=' not in line:
                continue
            try:
                # 格式: v_sh600519="1~贵州茅台~600519~1203.00~..."
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
                    'volume': float(fields[6]) if fields[6] else 0,  # 手
                    'amount': float(fields[37]) if fields[37] else 0,  # 万元
                    'turnover': float(fields[38]) if fields[38] else 0,
                    'pe': float(fields[39]) if len(fields) > 39 and fields[39] else 0,
                    'mcap': float(fields[45]) if len(fields) > 45 and fields[45] else 0,  # 亿
                    'limit_up': float(fields[47]) if len(fields) > 47 and fields[47] else 0,
                    'limit_down': float(fields[48]) if len(fields) > 48 and fields[48] else 0,
                }
            except (ValueError, IndexError) as e:
                continue
        time.sleep(0.3)  # 温和节流
    return results

# ━━━ mootdx 获取股票列表 ━━━
def get_stock_list():
    """通过 mootdx 获取全A股列表"""
    from mootdx.quotes import Quotes
    client = Quotes.factory(market='std')
    all_stocks = []
    # 深圳 + 上海
    for market in [0, 1]:
        stocks = client.stocks(market=market)
        for _, row in stocks.iterrows():
            code = str(row['code'])
            # 过滤指数和B股
            if len(code) == 6 and code.isdigit() and not code.startswith('9'):
                name = row.get('name', '')
                if name and '指数' not in name and not code.startswith('2'):
                    all_stocks.append(code)
    return sorted(set(all_stocks))

# ━━━ 涨停判定 ━━━
def is_limit_up(change_pct, price, limit_up_price, market_code):
    """判断是否涨停（允许±0.5%容差，因为行情可能有微小延迟）"""
    if change_pct >= 9.5:
        return True
    if limit_up_price > 0 and price > 0:
        if abs(price - limit_up_price) / limit_up_price < 0.005:
            return True
    return False

def get_market_type(code):
    if code.startswith('6'):
        if code.startswith('688'):
            return '科创板'
        return '主板'
    elif code.startswith('0'):
        return '主板'
    elif code.startswith('3'):
        return '创业板'
    elif code.startswith('4') or code.startswith('8'):
        return '北交所'
    return '其他'

# ━━━ 行业/概念映射 ━━━
# 东财行业映射表（基于常见分类）
INDUSTRY_MAP = {}  # 从 stock data 动态填充

# ━━━ 分析函数 ━━━
def analyze_limit_up(stocks_data):
    """对涨停股票进行分析"""
    limit_up_stocks = []

    for code, info in stocks_data.items():
        if is_limit_up(info['change_pct'], info['price'], info['limit_up'], code):
            limit_up_stocks.append({
                'code': code,
                'name': info['name'],
                'price': info['price'],
                'pre_close': info['pre_close'],
                'change_pct': info['change_pct'],
                'limit_up_price': info['limit_up'],
                'volume': info['volume'],
                'amount': info['amount'],
                'turnover': info['turnover'],
                'pe': info['pe'],
                'mcap': info['mcap'],
                'market': get_market_type(code),
            })

    # 按涨跌幅排序
    limit_up_stocks.sort(key=lambda x: x['change_pct'], reverse=True)

    # 市场分布
    by_market = defaultdict(int)
    for s in limit_up_stocks:
        by_market[s['market']] += 1

    # 按照概念板块分析需要额外API，这里先做基础统计
    return {
        'total': len(limit_up_stocks),
        'stocks': limit_up_stocks,
        'by_market': dict(by_market),
    }

# ━━━ MAIN ━━━
def main():
    print("=" * 70)
    print("  📊 A股涨停板全景分析")
    print(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("  数据源: mootdx(通达信TCP) + 腾讯财经(HTTP)")
    print("=" * 70)

    # 1. 获取股票列表
    print("\n[1/4] 获取全A股列表...")
    try:
        all_codes = get_stock_list()
        print(f"  → 共 {len(all_codes)} 只A股")
    except Exception as e:
        print(f"  [ERROR] mootdx 获取股票列表失败: {e}")
        print("  尝试备用方案：使用静态股票列表...")
        # 备用：只检查主要指数成分股
        all_codes = ['600519', '000858', '601318', '300750', '688981',
                     '601398', '600036', '000333', '002415', '601012']

    # 2. 批量获取行情
    print(f"\n[2/4] 批量获取行情数据 ({len(all_codes)} 只)...")
    all_quotes = {}
    batch_size = 50
    total_batches = (len(all_codes) + batch_size - 1) // batch_size

    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i+batch_size]
        batch_num = i // batch_size + 1
        if batch_num % 10 == 0 or batch_num == 1:
            print(f"    批次 {batch_num}/{total_batches}...")
        quotes = qq_batch_quotes(batch)
        all_quotes.update(quotes)
        time.sleep(0.2)

    print(f"  → 成功获取 {len(all_quotes)} 只股票行情")

    # 3. 涨停筛选
    print(f"\n[3/4] 筛选涨停股票...")
    result = analyze_limit_up(all_quotes)
    print(f"  → 涨停: {result['total']} 只")
    for mkt, cnt in sorted(result['by_market'].items()):
        print(f"     {mkt}: {cnt} 只")

    # 4. 输出报告
    print(f"\n[4/4] 生成报告...")

    output_dir = "/Users/lishunxiang/Cenxi/learn/Finance/src/涨停分析/2026-07-02-涨停复盘"

    # 保存完整数据
    report = {
        "report_date": "20260702",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": result['total'],
        "stocks": result['stocks'],
        "by_market": result['by_market'],
    }

    with open(f"{output_dir}/report.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 数据已保存: {output_dir}/report.json")

    # ━━ 打印报告 ━━
    print("\n" + "=" * 80)
    print(f"  📊 A股涨停板全景报告 — 2026-07-02")
    print(f"  数据源: 腾讯财经 (东财push2今日不可用)")
    print(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    print(f"\n{'─' * 80}")
    print(f"  📋 全市场涨停概览")
    print(f"{'─' * 80}")
    print(f"  涨停总数: {result['total']} 只")
    for mkt, cnt in sorted(result['by_market'].items()):
        print(f"    {mkt}: {cnt} 只")

    if result['stocks']:
        print(f"\n{'─' * 80}")
        print(f"  📋 涨停个股明细")
        print(f"{'─' * 80}")
        print(f"  {'代码':<8s} {'名称':<10s} {'价格':>8s} {'涨幅':>8s} {'市值(亿)':>10s} {'换手%':>7s} {'市场':<8s}")
        print(f"  {'─' * 70}")
        for s in result['stocks'][:50]:
            print(f"  {s['code']:<8s} {s['name']:<10s} {s['price']:>8.2f} {s['change_pct']:>+7.2f}% "
                  f"{s['mcap']:>10.1f} {s['turnover']:>7.2f} {s['market']:<8s}")
        if len(result['stocks']) > 50:
            print(f"  ... 还有 {len(result['stocks'])-50} 只")
    else:
        print(f"\n  ⚠️ 今日未检测到涨停股票。")
        print(f"  可能原因：")
        print(f"  1. 今日为非交易日或市场休市")
        print(f"  2. 腾讯API数据精度不足（涨跌幅四舍五入）")
        print(f"  3. 全市场确实没有涨停股票（极小概率）")
        print(f"\n  实际行情抽样 (涨幅前10):")
        sorted_all = sorted(all_quotes.items(), key=lambda x: x[1]['change_pct'], reverse=True)
        for code, info in sorted_all[:10]:
            print(f"    {code} {info['name']:<10s} {info['price']:>8.2f} {info['change_pct']:>+7.2f}%")

    print(f"\n{'─' * 80}")
    print(f"  ⚠️ 注意:")
    print(f"  1. 东财 push2ex API 当前返回 rc=102（可能需更新 token 或接口已迁移）")
    print(f"  2. 改用腾讯财经 API 提供基础行情数据（涨幅/价格/市值/换手率）")
    print(f"  3. 腾讯 API 不提供：涨停时间、炸板次数、封单金额、连板数、行业概念分类")
    print(f"  4. 这些数据需要东财 push2ex API 修复后才能获取")
    print(f"{'─' * 80}")

    print(f"\n{'=' * 80}")
    print(f"  ⚠️ 研究声明: 以上数据基于公开API，仅供参考。涨停板分析不构成任何投资建议。")
    print(f"{'=' * 80}")

if __name__ == "__main__":
    main()
