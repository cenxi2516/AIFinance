#!/usr/bin/env python3
"""
A股涨停板全景报告打印 V2.0
读取 enhanced report.json 并生成格式化文本 + Markdown 报告。
用法: python3 print_limit_up_report.py --input <report.json路径>
      python3 print_limit_up_report.py --date 2026-07-03
"""
import json, sys, os, argparse
from datetime import datetime
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_report(input_path=None, date_str=None):
    """加载 report.json"""
    if input_path:
        path = input_path
    elif date_str:
        path = os.path.join(REPO_ROOT, "src", "涨停分析", f"{date_str}-涨停复盘", "report.json")
    else:
        print("ERROR: 请提供 --input 或 --date 参数")
        sys.exit(1)

    if not os.path.exists(path):
        print(f"ERROR: 文件不存在: {path}")
        sys.exit(1)

    with open(path, encoding='utf-8') as f:
        return json.load(f), path

def fmt_amount(wan):
    """格式化金额(万元)"""
    if abs(wan) >= 10000:
        return f"{wan/10000:.2f}亿"
    return f"{wan:.0f}万"

def fmt_mcap(yi):
    """格式化市值(亿元)"""
    if yi >= 10000:
        return f"{yi/10000:.2f}万亿"
    return f"{yi:.1f}亿"

def fmt_pe(pe):
    """格式化PE"""
    if pe <= 0:
        return "-"
    return f"{pe:.1f}"

def print_header(title, width=80):
    """打印分隔标题"""
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}")

def generate_report(report, report_path):
    """生成格式化报告（控制台 + .md + .txt）"""
    date_str = report.get("report_date", "")
    date_ymd = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}" if len(date_str) == 8 else date_str
    stocks = report.get("stocks", [])
    aggregations = report
    total = len(stocks)

    out_dir = os.path.dirname(report_path)

    # ══════════════════════════════════════════════════════════
    # 控制台输出
    # ══════════════════════════════════════════════════════════

    print("=" * 80)
    print(f"  📊 A股涨停板全景报告 — {date_ymd}")
    print(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    sources = report.get('data_sources', {})
    src_summary = '+'.join(sources.values()) if sources else '多源'
    print(f"  数据源: {src_summary}")
    print("=" * 80)

    # ━━ 概览 ━━
    print_header("📋 全市场涨停概览")
    print(f"  真实涨停(剔除新股): {total} 只")
    if report.get('new_listings', 0) > 0:
        print(f"  新股首日(不计入): {report['new_listings']} 只")

    by_market = report.get("by_market", {})
    for mkt in ['主板', '创业板', '科创板', '北交所']:
        cnt = by_market.get(mkt, 0)
        bar = "█" * min(cnt, 40)
        print(f"    {mkt}: {cnt:>4d} 只 {bar}")

    by_consecutive = report.get("by_consecutive", {})
    print(f"\n  连板分布:")
    for key in ['1', '2', '3', '4+']:
        cnt = by_consecutive.get(key, 0)
        label = f"{key}连板" if key.isdigit() else "高标(4+)"
        bar = "█" * min(cnt, 20)
        print(f"    {label:<10s}: {cnt:>4d} 只 {bar}")

    # ━━ 涨停归因 ━━
    print_header("🔍 涨停归因 TOP 20（同花顺热点）")
    reason_map = defaultdict(list)
    for s in stocks:
        reason = s.get('limit_up_reason', '')
        if reason:
            reason_map[reason].append(s)
    for i, (reason, r_stocks) in enumerate(sorted(reason_map.items(), key=lambda x: len(x[1]), reverse=True)[:20]):
        print(f"  {i+1:2d}. {reason:<50s} {len(r_stocks)}只")

    # ━━ 行业排名 ━━
    print_header("🏭 行业涨停数排名 TOP 15")
    ind_rank = report.get("industry_ranking", [])
    if ind_rank:
        for i, ind in enumerate(ind_rank[:15]):
            bar = "█" * min(ind['count'], 25)
            print(f"  {i+1:2d}. {ind['industry']:<18s} {bar} {ind['count']}只")
    else:
        print(f"  (暂无行业分类数据)")

    # ━━ 概念排名 ━━
    print_header("🔥 概念涨停数排名 TOP 20")
    concept_rank = report.get("concept_ranking", [])
    if concept_rank:
        for i, c in enumerate(concept_rank[:20]):
            bar = "█" * min(c['count'], 20)
            print(f"  {i+1:2d}. {c['concept']:<18s} {bar} {c['count']}只")
    else:
        print(f"  (暂无概念分类数据)")

    # ━━ 高标追踪 ━━
    print_header("🏆 连板高标追踪 (3连板及以上)")
    high_mark = report.get("high_mark_tracking", [])
    if high_mark:
        print(f"  {'代码':<8s} {'名称':<10s} {'连板':>4s} {'涨幅':>8s} {'市值':>10s} {'换手%':>7s} {'PE':>8s} {'归因'}")
        print(f"  {'─' * 80}")
        for s in high_mark[:30]:
            reason_short = s.get('limit_up_reason', '')[:30]
            print(f"  {s['code']:<8s} {s['name']:<10s} {s['consecutive_days']:>4d}天 "
                  f"{s['change_pct']:>+7.2f}% {fmt_mcap(s['mcap']):>10s} "
                  f"{s['turnover']:>6.1f}% {fmt_pe(s['pe']):>8s} {reason_short}")
    else:
        print(f"  (无3连板及以上高标)")

    # ━━ 涨幅分段 ━━
    print_header("📊 涨幅分段统计")
    ranges = [
        ("涨停10%(±0.5%)", lambda s: 9.5 <= s['change_pct'] <= 10.5),
        ("涨停20%(±0.5%)", lambda s: 19.5 <= s['change_pct'] <= 20.5),
        ("涨停30%(±1%)", lambda s: 29.0 <= s['change_pct'] <= 31.0),
        ("准涨停(5-9.5%)", lambda s: 5 <= s['change_pct'] < 9.5),
    ]
    for label, fn in ranges:
        matches = [s for s in stocks if fn(s)]
        bar = "█" * min(len(matches), 30)
        print(f"  {label:<20s}: {len(matches):>4d} 只 {bar}")

    # ━━ 市值分布 ━━
    print_header("💰 市值分布")
    mcap_bins = [
        ("超大市值(>1000亿)", lambda s: s['mcap'] > 1000),
        ("大市值(500-1000亿)", lambda s: 500 < s['mcap'] <= 1000),
        ("中市值(100-500亿)", lambda s: 100 < s['mcap'] <= 500),
        ("小市值(30-100亿)", lambda s: 30 < s['mcap'] <= 100),
        ("微小市值(<30亿)", lambda s: s['mcap'] <= 30),
    ]
    for label, fn in mcap_bins:
        matches = [s for s in stocks if fn(s)]
        print(f"  {label:<22s}: {len(matches):>4d} 只")

    # ━━ 换手率分析 ━━
    print_header("📊 换手率分析")
    turnover_bins = [
        ("僵尸板(<2%)", lambda s: s['turnover'] < 2),
        ("强封板(2-5%)", lambda s: 2 <= s['turnover'] < 5),
        ("充分换手(5-15%)", lambda s: 5 <= s['turnover'] < 15),
        ("分歧加大(15-25%)", lambda s: 15 <= s['turnover'] < 25),
        ("过度换手(>25%)", lambda s: s['turnover'] >= 25),
    ]
    for label, fn in turnover_bins:
        matches = [s for s in stocks if fn(s)]
        signal = ""
        if "过度" in label:
            signal = "🚨"
        elif "分歧" in label:
            signal = "⚠️"
        elif "充分" in label:
            signal = "✅"
        elif "强封" in label:
            signal = "✅"
        elif "僵尸" in label:
            signal = "🔻"
        print(f"  {label:<22s}: {len(matches):>4d} 只 {signal}")

    # ━━ PE 分析 ━━
    print_header("📊 估值分析（PE）")
    pe_bins = [
        ("负PE(亏损)", lambda s: s['pe'] <= 0),
        ("低PE(<20)", lambda s: 0 < s['pe'] <= 20),
        ("中PE(20-50)", lambda s: 20 < s['pe'] <= 50),
        ("高PE(50-100)", lambda s: 50 < s['pe'] <= 100),
        ("极高PE(>100)", lambda s: s['pe'] > 100),
    ]
    for label, fn in pe_bins:
        matches = [s for s in stocks if fn(s)]
        print(f"  {label:<22s}: {len(matches):>4d} 只")
    neg_pe_pct = sum(1 for s in stocks if s['pe'] <= 0) / max(total, 1) * 100
    if neg_pe_pct > 50:
        print(f"  ⚠️ 超半数({neg_pe_pct:.1f}%)涨停股处于亏损状态，市场情绪偏投机")

    # ━━ 龙虎榜 ━━
    print_header("🐉 龙虎榜交叉验证")
    dt_cross = report.get("dragon_tiger_cross", {})
    print(f"  龙虎榜上榜: {dt_cross.get('total_on_board', 0)}/{total} 只")
    top_buy = dt_cross.get("top_net_buy", [])
    if top_buy:
        print(f"\n  净买入 TOP 10:")
        for i, s in enumerate(top_buy[:10]):
            print(f"  {i+1:2d}. {s['code']} {s['name']:<10s} 净买={fmt_amount(s['net_buy_wan'])}")
    else:
        print(f"  (龙虎榜数据暂无或盘后未更新)")

    # ━━ 大市值涨停 ━━
    print_header("🏢 大市值涨停股（>100亿）")
    big_caps = sorted([s for s in stocks if s['mcap'] > 100], key=lambda x: x['mcap'], reverse=True)
    if big_caps:
        print(f"  {'代码':<8s} {'名称':<10s} {'涨幅':>8s} {'市值':>10s} {'PE':>8s} {'换手%':>7s} {'连板':>4s} {'归因'}")
        print(f"  {'─' * 80}")
        for s in big_caps:
            reason_short = s.get('limit_up_reason', '')[:25]
            print(f"  {s['code']:<8s} {s['name']:<10s} {s['change_pct']:>+7.2f}% "
                  f"{fmt_mcap(s['mcap']):>10s} {fmt_pe(s['pe']):>8s} {s['turnover']:>6.1f}% "
                  f"{s.get('consecutive_days',1):>4d}天 {reason_short}")
    else:
        print(f"  (无100亿以上市值涨停股)")

    # ━━ 高换手警示 ━━
    print_header("⚠️ 高换手警示股（换手>20%）")
    high_turnover = sorted([s for s in stocks if s['turnover'] > 20], key=lambda x: x['turnover'], reverse=True)
    if high_turnover:
        print(f"  {'代码':<8s} {'名称':<10s} {'涨幅':>8s} {'换手%':>7s} {'市值':>10s} {'PE':>8s}")
        print(f"  {'─' * 55}")
        for s in high_turnover:
            print(f"  {s['code']:<8s} {s['name']:<10s} {s['change_pct']:>+7.2f}% "
                  f"{s['turnover']:>7.2f} {fmt_mcap(s['mcap']):>10s} {fmt_pe(s['pe']):>8s}")
    else:
        print(f"  (无高换手涨停股)")

    # ━━ 完整清单（按市场分组） ━━
    for mkt in ['创业板', '科创板', '北交所']:
        mkt_stocks = [s for s in stocks if s['market'] == mkt]
        if mkt_stocks:
            print_header(f"📋 {mkt}涨停股详情 ({len(mkt_stocks)}只)")
            print(f"  {'代码':<8s} {'名称':<10s} {'价格':>8s} {'涨幅':>8s} {'市值':>10s} {'换手%':>7s} {'PE':>8s} {'连板':>4s} {'归因'}")
            print(f"  {'─' * 90}")
            for s in mkt_stocks:
                reason_short = s.get('limit_up_reason', '')[:20]
                print(f"  {s['code']:<8s} {s['name']:<10s} {s['price']:>8.2f} {s['change_pct']:>+7.2f}% "
                      f"{fmt_mcap(s['mcap']):>10s} {s['turnover']:>6.1f}% {fmt_pe(s['pe']):>8s} "
                      f"{s.get('consecutive_days',1):>4d}天 {reason_short}")

    # ━━ 主板（分页显示） ━━
    main_stocks = [s for s in stocks if s['market'] == '主板']
    if main_stocks:
        print_header(f"📋 主板涨停股详情 ({len(main_stocks)}只，显示前50)")
        print(f"  {'代码':<8s} {'名称':<10s} {'价格':>8s} {'涨幅':>8s} {'市值':>10s} {'换手%':>7s} {'PE':>8s} {'连板':>4s} {'归因'}")
        print(f"  {'─' * 90}")
        for s in main_stocks[:50]:
            reason_short = s.get('limit_up_reason', '')[:20]
            print(f"  {s['code']:<8s} {s['name']:<10s} {s['price']:>8.2f} {s['change_pct']:>+7.2f}% "
                  f"{fmt_mcap(s['mcap']):>10s} {s['turnover']:>6.1f}% {fmt_pe(s['pe']):>8s} "
                  f"{s.get('consecutive_days',1):>4d}天 {reason_short}")
        if len(main_stocks) > 50:
            print(f"  ... 还有 {len(main_stocks)-50} 只主板涨停股")

    # ━━ 数据质量 ━━
    print_header("📋 数据质量说明")
    dq = report.get("data_quality", {})
    print(f"  行业覆盖率: {dq.get('industry_coverage_pct', 0)}%")
    print(f"  概念覆盖率: {dq.get('concept_coverage_pct', 0)}%")
    print(f"  归因覆盖率: {dq.get('reason_coverage_pct', 0)}%")
    print(f"  龙虎榜交叉: {dq.get('dragon_tiger_coverage_pct', 0)}%")
    missing = dq.get('missing_fields', [])
    if missing:
        print(f"  缺失字段: {', '.join(missing)}")
        print(f"  缺失原因: {dq.get('missing_reason', '未知')}")
    src = report.get('data_sources', {})
    print(f"\n  数据源详情:")
    for k, v in src.items():
        print(f"    {k}: {v}")

    # ━━ 声明 ━━
    print(f"\n{'=' * 80}")
    print(f"  ⚠️ 研究声明: 以上数据基于公开API，仅供参考。")
    print(f"     涨停板分析不构成任何投资建议。打板有风险，追高需谨慎。")
    print(f"     涨停板次日走势受多重因素影响，历史规律不保证未来结果。")
    print(f"{'=' * 80}")

    # ══════════════════════════════════════════════════════════
    # 保存 Markdown 报告
    # ══════════════════════════════════════════════════════════
    md_path = os.path.join(out_dir, "report.md")
    save_markdown_report(report, md_path, date_ymd)
    print(f"\n  ✅ Markdown 报告已保存: {md_path}")

    # ══════════════════════════════════════════════════════════
    # 保存文本报告
    # ══════════════════════════════════════════════════════════
    txt_path = os.path.join(out_dir, "report.txt")
    save_text_report(report, txt_path, date_ymd)
    print(f"  ✅ 文本报告已保存: {txt_path}")


def save_markdown_report(report, path, date_ymd):
    """生成 Markdown 格式报告"""
    stocks = report.get("stocks", [])
    total = len(stocks)
    lines = []

    lines.append(f"# 📊 A股涨停板全景报告 — {date_ymd}\n")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 数据源: mootdx + 腾讯财经 + 同花顺热点 + 东财slist + 龙虎榜\n")
    lines.append("---\n")

    # 概览
    lines.append("## 📋 全市场涨停概览\n")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| **真实涨停(剔除新股)** | **{total} 只** |")
    if report.get('new_listings', 0) > 0:
        lines.append(f"| 新股首日(不计入) | {report['new_listings']} 只 |")
    for mkt in ['主板', '创业板', '科创板', '北交所']:
        cnt = report.get("by_market", {}).get(mkt, 0)
        lines.append(f"| {mkt} | {cnt} 只 |")
    lines.append("")

    # 连板分布
    lines.append("### 连板分布\n")
    lines.append(f"| 类型 | 数量 |")
    lines.append(f"|------|------|")
    for key in ['1', '2', '3', '4+']:
        cnt = report.get("by_consecutive", {}).get(key, 0)
        label = f"{key}连板" if key.isdigit() else "高标(4+)"
        lines.append(f"| {label} | {cnt} 只 |")
    lines.append("")

    # 归因 TOP 20
    lines.append("---\n")
    lines.append("## 🔍 涨停归因 TOP 20（同花顺热点）\n")
    reason_map = defaultdict(list)
    for s in stocks:
        reason = s.get('limit_up_reason', '')
        if reason:
            reason_map[reason].append(s)
    lines.append(f"| 排名 | 涨停原因 | 数量 |")
    lines.append(f"|------|---------|------|")
    for i, (reason, r_stocks) in enumerate(sorted(reason_map.items(), key=lambda x: len(x[1]), reverse=True)[:20]):
        lines.append(f"| {i+1} | {reason} | {len(r_stocks)}只 |")
    lines.append("")

    # 行业排名
    lines.append("---\n")
    lines.append("## 🏭 行业涨停数排名 TOP 15\n")
    ind_rank = report.get("industry_ranking", [])
    if ind_rank:
        lines.append(f"| 排名 | 行业 | 涨停数 |")
        lines.append(f"|------|------|--------|")
        for i, ind in enumerate(ind_rank[:15]):
            lines.append(f"| {i+1} | {ind['industry']} | {ind['count']}只 |")
    lines.append("")

    # 概念排名
    lines.append("---\n")
    lines.append("## 🔥 概念涨停数排名 TOP 20\n")
    concept_rank = report.get("concept_ranking", [])
    if concept_rank:
        lines.append(f"| 排名 | 概念 | 涨停数 |")
        lines.append(f"|------|------|--------|")
        for i, c in enumerate(concept_rank[:20]):
            lines.append(f"| {i+1} | {c['concept']} | {c['count']}只 |")
    lines.append("")

    # 高标追踪
    lines.append("---\n")
    lines.append("## 🏆 连板高标追踪 (3连板及以上)\n")
    high_mark = report.get("high_mark_tracking", [])
    if high_mark:
        lines.append(f"| 代码 | 名称 | 连板 | 涨幅 | 市值(亿) | 换手% | PE | 归因 |")
        lines.append(f"|------|------|------|------|----------|-------|-----|------|")
        for s in high_mark[:30]:
            lines.append(f"| {s['code']} | {s['name']} | {s['consecutive_days']}天 | {s['change_pct']:+.2f}% | {s['mcap']:.1f} | {s['turnover']:.1f}% | {fmt_pe(s['pe'])} | {s.get('limit_up_reason','')[:30]} |")
    else:
        lines.append("(无3连板及以上高标)")
    lines.append("")

    # 市值分布
    lines.append("---\n")
    lines.append("## 💰 市值分布\n")
    lines.append(f"| 市值区间 | 数量 |")
    lines.append(f"|----------|------|")
    for label, lo, hi in [("超大市值(>1000亿)", 1000, float('inf')), ("大市值(500-1000亿)", 500, 1000),
                           ("中市值(100-500亿)", 100, 500), ("小市值(30-100亿)", 30, 100), ("微小市值(<30亿)", 0, 30)]:
        cnt = sum(1 for s in stocks if lo < s['mcap'] <= hi)
        lines.append(f"| {label} | {cnt} 只 |")
    lines.append("")

    # 换手率分析
    lines.append("---\n")
    lines.append("## 📊 换手率分析\n")
    lines.append(f"| 换手率区间 | 数量 | 信号 |")
    lines.append(f"|-----------|------|------|")
    for label, lo, hi, sig in [("僵尸板(<2%)", 0, 2, "🔻"), ("强封板(2-5%)", 2, 5, "✅"),
                                  ("充分换手(5-15%)", 5, 15, "✅"), ("分歧加大(15-25%)", 15, 25, "⚠️"),
                                  ("过度换手(>25%)", 25, 999, "🚨")]:
        cnt = sum(1 for s in stocks if lo <= s['turnover'] < hi)
        lines.append(f"| {label} | {cnt} 只 | {sig} |")
    lines.append("")

    # PE 分析
    lines.append("---\n")
    lines.append("## 📊 估值分析（PE）\n")
    lines.append(f"| PE 区间 | 数量 |")
    lines.append(f"|---------|------|")
    for label, lo, hi in [("负PE(亏损)", -float('inf'), 0), ("低PE(<20)", 0, 20),
                           ("中PE(20-50)", 20, 50), ("高PE(50-100)", 50, 100), ("极高PE(>100)", 100, float('inf'))]:
        cnt = sum(1 for s in stocks if lo < s['pe'] <= hi)
        lines.append(f"| {label} | {cnt} 只 |")
    neg_pct = sum(1 for s in stocks if s['pe'] <= 0) / max(total, 1) * 100
    if neg_pct > 50:
        lines.append(f"\n> ⚠️ 超半数({neg_pct:.1f}%)涨停股处于亏损状态，市场情绪偏投机")
    lines.append("")

    # 龙虎榜
    lines.append("---\n")
    lines.append("## 🐉 龙虎榜交叉验证\n")
    dt_cross = report.get("dragon_tiger_cross", {})
    lines.append(f"龙虎榜上榜: {dt_cross.get('total_on_board', 0)}/{total} 只")
    top_buy = dt_cross.get("top_net_buy", [])
    if top_buy:
        lines.append(f"\n| 排名 | 代码 | 名称 | 净买入 |")
        lines.append(f"|------|------|------|--------|")
        for i, s in enumerate(top_buy[:10]):
            lines.append(f"| {i+1} | {s['code']} | {s['name']} | {fmt_amount(s['net_buy_wan'])} |")
    lines.append("")

    # 大市值涨停
    lines.append("---\n")
    lines.append("## 🏢 大市值涨停股（>100亿）\n")
    big_caps = sorted([s for s in stocks if s['mcap'] > 100], key=lambda x: x['mcap'], reverse=True)
    if big_caps:
        lines.append(f"| 代码 | 名称 | 涨幅 | 市值(亿) | PE | 换手% | 连板 | 归因 |")
        lines.append(f"|------|------|------|----------|-----|-------|------|------|")
        for s in big_caps:
            lines.append(f"| {s['code']} | {s['name']} | {s['change_pct']:+.2f}% | {s['mcap']:.1f} | {fmt_pe(s['pe'])} | {s['turnover']:.1f}% | {s.get('consecutive_days',1)}天 | {s.get('limit_up_reason','')[:25]} |")
    lines.append("")

    # 声明
    lines.append("---\n")
    lines.append("## ⚠️ 研究声明\n")
    lines.append("以上数据基于公开API，仅供参考。涨停板分析不构成任何投资建议。")
    lines.append("打板有风险，追高需谨慎。涨停板次日走势受多重因素影响，历史规律不保证未来结果。")

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def save_text_report(report, path, date_ymd):
    """保存纯文本报告（简化版）"""
    stocks = report.get("stocks", [])
    total = len(stocks)
    lines = []
    lines.append(f"A股涨停板全景报告 — {date_ymd}")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)
    lines.append(f"\n涨停总数: {total} 只")
    lines.append(f"连板分布: {report.get('by_consecutive', {})}")
    lines.append(f"市场分布: {report.get('by_market', {})}")
    lines.append(f"\n完整个股清单:")
    lines.append(f"{'代码':<8s} {'名称':<10s} {'价格':>8s} {'涨幅':>8s} {'连板':>4s} {'归因'}")
    lines.append('-' * 60)
    for s in stocks:
        lines.append(f"{s['code']:<8s} {s['name']:<10s} {s['price']:>8.2f} {s['change_pct']:>+7.2f}% {s.get('consecutive_days',1):>4d}天 {s.get('limit_up_reason','')[:30]}")
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="涨停板全景报告打印")
    parser.add_argument("--input", help="report.json 路径")
    parser.add_argument("--date", help="日期 YYYY-MM-DD")
    args = parser.parse_args()

    report, report_path = load_report(args.input, args.date)
    generate_report(report, report_path)
