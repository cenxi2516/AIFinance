#!/usr/bin/env python3
"""从 JSON 生成详细的涨停分析报告"""
import json
from datetime import datetime
from collections import defaultdict

# 加载数据
with open("/Users/lishunxiang/Cenxi/learn/Finance/src/涨停分析/2026-07-02-涨停复盘/report.json") as f:
    data = json.load(f)

stocks = data['stocks']

# 过滤新股（N前缀、C前缀为首日/前几日无涨跌停限制）
real_limit_ups = [s for s in stocks if not s['name'].startswith('N') and not s['name'].startswith('C')]
new_listings = [s for s in stocks if s['name'].startswith('N') or s['name'].startswith('C')]

print("=" * 80)
print(f"  📊 A股涨停板全景报告 — 2026-07-02")
print(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"  数据源: mootdx(通达信TCP) + 腾讯财经(HTTP)")
print("=" * 80)

# ━━ 概览 ━━
print(f"\n{'─' * 80}")
print(f"  📋 全市场涨停概览")
print(f"{'─' * 80}")
print(f"  真实涨停(剔除新股): {len(real_limit_ups)} 只")
if new_listings:
    print(f"  新股首日(不计入): {len(new_listings)} 只")
    for s in new_listings:
        print(f"    {s['code']} {s['name']} {s['change_pct']:+.1f}%")

# 市场分布
by_market = defaultdict(list)
for s in real_limit_ups:
    by_market[s['market']].append(s)

for mkt in ['主板', '创业板', '科创板', '北交所']:
    cnt = len(by_market.get(mkt, []))
    bar = "█" * min(cnt, 40)
    print(f"    {mkt}: {cnt:>4d} 只 {bar}")

# ━━ 涨幅分段 ━━
print(f"\n{'─' * 80}")
print(f"  📊 涨幅分段统计")
print(f"{'─' * 80}")

ranges = [
    ("涨超100%(新股)", lambda s: s['change_pct'] > 50),
    ("涨停10%(±0.5%)", lambda s: 9.5 <= s['change_pct'] <= 10.5),
    ("涨停20%(±0.5%)", lambda s: 19.5 <= s['change_pct'] <= 20.5),
    ("涨停30%(±1%)", lambda s: 29.0 <= s['change_pct'] <= 31.0),
    ("准涨停(5-9.5%)", lambda s: 5 <= s['change_pct'] < 9.5),
    ("涨停价格匹配", lambda s: s['limit_up_price'] > 0 and abs(s['price'] - s['limit_up_price']) / s['limit_up_price'] < 0.01),
]

for label, fn in ranges:
    matches = [s for s in real_limit_ups if fn(s)]
    print(f"  {label:<20s}: {len(matches):>4d} 只")

# ━━ 市值分布 ━━
print(f"\n{'─' * 80}")
print(f"  💰 市值分布")
print(f"{'─' * 80}")

mcap_bins = [
    ("超大市值(>1000亿)", lambda s: s['mcap'] > 1000),
    ("大市值(500-1000亿)", lambda s: 500 < s['mcap'] <= 1000),
    ("中市值(100-500亿)", lambda s: 100 < s['mcap'] <= 500),
    ("小市值(30-100亿)", lambda s: 30 < s['mcap'] <= 100),
    ("微小市值(<30亿)", lambda s: s['mcap'] <= 30),
]

for label, fn in mcap_bins:
    matches = [s for s in real_limit_ups if fn(s)]
    print(f"  {label:<22s}: {len(matches):>4d} 只")

# ━━ 涨停详细列表 ━━
print(f"\n{'─' * 80}")
print(f"  📋 涨停个股明细（按涨幅排序）")
print(f"{'─' * 80}")
print(f"  {'代码':<8s} {'名称':<10s} {'最新价':>8s} {'涨幅':>8s} {'市值(亿)':>10s} {'换手%':>7s} {'PE':>8s} {'市场':<8s}")
print(f"  {'─' * 80}")

for s in sorted(real_limit_ups, key=lambda x: x['change_pct'], reverse=True):
    pe_str = f"{s['pe']:.1f}" if s['pe'] > 0 else "-"
    print(f"  {s['code']:<8s} {s['name']:<10s} {s['price']:>8.2f} {s['change_pct']:>+7.2f}% "
          f"{s['mcap']:>10.1f} {s['turnover']:>7.2f} {pe_str:>8s} {s['market']:<8s}")

# ━━ 换手率分析 ━━
print(f"\n{'─' * 80}")
print(f"  📊 换手率分析")
print(f"{'─' * 80}")

turnover_bins = [
    ("僵尸板(<2%)", lambda s: s['turnover'] < 2),
    ("强封板(2-5%)", lambda s: 2 <= s['turnover'] < 5),
    ("充分换手(5-15%)", lambda s: 5 <= s['turnover'] < 15),
    ("分歧加大(15-25%)", lambda s: 15 <= s['turnover'] < 25),
    ("过度换手(>25%)", lambda s: s['turnover'] >= 25),
]

for label, fn in turnover_bins:
    matches = [s for s in real_limit_ups if fn(s)]
    print(f"  {label:<22s}: {len(matches):>4d} 只")

# ━━ PE 分析 ━━
print(f"\n{'─' * 80}")
print(f"  📊 估值分析（PE）")
print(f"{'─' * 80}")

pe_bins = [
    ("负PE(亏损)", lambda s: s['pe'] <= 0),
    ("低PE(<20)", lambda s: 0 < s['pe'] <= 20),
    ("中PE(20-50)", lambda s: 20 < s['pe'] <= 50),
    ("高PE(50-100)", lambda s: 50 < s['pe'] <= 100),
    ("极高PE(>100)", lambda s: s['pe'] > 100),
]

for label, fn in pe_bins:
    matches = [s for s in real_limit_ups if fn(s)]
    print(f"  {label:<22s}: {len(matches):>4d} 只")

# ━━ TOP 市值涨停股 ━━
print(f"\n{'─' * 80}")
print(f"  🏢 大市值涨停股（市值>100亿）")
print(f"{'─' * 80}")
big_caps = sorted([s for s in real_limit_ups if s['mcap'] > 100], key=lambda x: x['mcap'], reverse=True)
if big_caps:
    print(f"  {'代码':<8s} {'名称':<10s} {'涨幅':>8s} {'市值(亿)':>10s} {'PE':>8s} {'换手%':>7s}")
    print(f"  {'─' * 55}")
    for s in big_caps:
        pe_str = f"{s['pe']:.1f}" if s['pe'] > 0 else "-"
        print(f"  {s['code']:<8s} {s['name']:<10s} {s['change_pct']:>+7.2f}% "
              f"{s['mcap']:>10.1f} {pe_str:>8s} {s['turnover']:>7.2f}")
else:
    print(f"  (无100亿以上市值涨停股)")

# ━━ 高换手涨停股(需警惕) ━━
print(f"\n{'─' * 80}")
print(f"  ⚠️ 高换手涨停股（换手>20%，需警惕）")
print(f"{'─' * 80}")
high_turnover = sorted([s for s in real_limit_ups if s['turnover'] > 20], key=lambda x: x['turnover'], reverse=True)
if high_turnover:
    print(f"  {'代码':<8s} {'名称':<10s} {'涨幅':>8s} {'换手%':>7s} {'市值(亿)':>10s} {'PE':>8s}")
    print(f"  {'─' * 55}")
    for s in high_turnover:
        pe_str = f"{s['pe']:.1f}" if s['pe'] > 0 else "-"
        print(f"  {s['code']:<8s} {s['name']:<10s} {s['change_pct']:>+7.2f}% "
              f"{s['turnover']:>7.2f} {s['mcap']:>10.1f} {pe_str:>8s}")
else:
    print(f"  (无高换手涨停股)")

# ━━ 声明 ━━
print(f"\n{'─' * 80}")
print(f"  ⚠️ 重要说明:")
print(f"{'─' * 80}")
print(f"  1. 数据源: 腾讯财经 API (东财 push2ex 今日返回 rc=102 不可用)")
print(f"  2. 缺失字段: 涨停时间、炸板次数、封单金额、连板数、行业/概念分类")
print(f"  3. 这些字段需要东财 push2ex 接口或 alternative API 补充")
print(f"  4. 涨幅阈值: 主板±10% / 创业板±20% / 科创板±20% / 北交所±30%")
print(f"  5. 已剔除新股首日(N前缀)")
print(f"{'─' * 80}")

print(f"\n{'=' * 80}")
print(f"  ⚠️ 研究声明: 以上数据基于公开API，仅供参考。")
print(f"     涨停板分析不构成任何投资建议。打板有风险，追高需谨慎。")
print(f"{'=' * 80}")
