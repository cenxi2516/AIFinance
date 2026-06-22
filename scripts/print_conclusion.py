#!/usr/bin/env python3
"""
统一结论打印工具 — 确保每次分析完成后最终结论输出到控制台。

设计原则:
  - 分析过程写入文件（markdown/json/csv）
  - 最终结论强制打印到 stdout
  - 支持三种输入方式：markdown 文件路径 / JSON 数据 / 直接文本

用法:
  python scripts/print_conclusion.py --file src/xxx/thesis.md          # 从 markdown 提取结论
  python scripts/print_conclusion.py --json src/xxx/scan_data.json     # 从 JSON 提取结论
  python scripts/print_conclusion.py --text "结论文本" --title "标题"   # 直接打印文本
  python scripts/print_conclusion.py --auto src/xxx/                   # 自动发现目录下的分析文件
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

# ── 终端颜色（跨平台兼容） ──────────────────────────────────────
class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    @staticmethod
    def disable():
        for attr in dir(Color):
            if not attr.startswith("_") and isinstance(getattr(Color, attr), str):
                setattr(Color, attr, "")


# ── 分隔线组件 ──────────────────────────────────────────────────
SEP_HEAVY = "━" * 64
SEP_LIGHT = "─" * 64
SEP_THIN = "·" * 64


def print_header(title: str, subtitle: str = ""):
    """打印结论区块头部"""
    print(f"\n{Color.BOLD}{Color.CYAN}{SEP_HEAVY}{Color.RESET}")
    print(f"{Color.BOLD}{Color.WHITE}  {title}{Color.RESET}")
    if subtitle:
        print(f"  {Color.DIM}{subtitle}{Color.RESET}")
    print(f"{Color.BOLD}{Color.CYAN}{SEP_HEAVY}{Color.RESET}\n")


def print_section(title: str):
    """打印子标题"""
    print(f"\n{Color.BOLD}{Color.YELLOW}▎{title}{Color.RESET}")
    print(f"  {Color.DIM}{SEP_THIN}{Color.RESET}")


def print_risk(level: str, text: str):
    """打印风险项，按级别着色"""
    color_map = {
        "颠覆": Color.RED,
        "重度": Color.RED,
        "中度": Color.YELLOW,
        "轻度": Color.DIM,
        "高": Color.RED,
        "中": Color.YELLOW,
        "低": Color.GREEN,
    }
    c = color_map.get(level, Color.RESET)
    print(f"  {c}[{level}]{Color.RESET} {text}")


def print_kv(key: str, value: str, indent: int = 2):
    """打印键值对"""
    pad = " " * indent
    print(f"{pad}{Color.DIM}{key}:{Color.RESET} {value}")


def print_table(headers: list, rows: list, col_widths: list = None):
    """打印简单表格"""
    if not rows:
        return
    if not col_widths:
        col_widths = [max(len(str(r[i])) for r in [headers] + rows) + 2 for i in range(len(headers))]

    # 表头
    header_line = "  " + "".join(f"{Color.BOLD}{h:<{w}}{Color.RESET}" for h, w in zip(headers, col_widths))
    print(header_line)
    print(f"  {Color.DIM}{'─' * sum(col_widths)}{Color.RESET}")
    # 数据行
    for row in rows:
        line = "  " + "".join(f"{str(c):<{w}}" for c, w in zip(row, col_widths))
        print(line)


# ── Markdown 解析 ───────────────────────────────────────────────
MARKDOWN_SKIP_KEYWORDS = [
    "标的", "优先级", "rank", "candidate", "ticker",
    "---", ":-", "环节", "|------", "约束类型",
    "在手订单", "估值锚点", "------", "触发条件",
]


def _is_data_row(cells: list) -> bool:
    """过滤表格的表头行和分隔符行"""
    first = "".join(cells).strip().lower()
    return not any(kw.lower() in first for kw in MARKDOWN_SKIP_KEYWORDS)


def _has_chinese(cells: list) -> bool:
    """只保留包含中文的数据行"""
    return any("一" <= ch <= "鿿" for ch in "".join(cells))


def extract_from_markdown(filepath: str) -> dict:
    """从 thesis.md / scenario-analysis.md 提取关键结论字段"""
    path = Path(filepath)
    if not path.exists():
        return {"error": f"文件不存在: {filepath}"}

    text = path.read_text(encoding="utf-8")

    result = {"source": str(path), "sections": {}}

    # 提取一级标题（跳过模板提示行）
    h1_pattern = re.findall(r'^# (.+)$', text, re.MULTILINE)
    if h1_pattern:
        result["title"] = h1_pattern[0].strip()

    # ── 提取风险注册表 ──
    # 匹配 risk-register.md 中的风险表格：| 1 | 风险描述 | 类别 | 触发条件 | 影响程度 | 概率 |
    risk_table = re.findall(
        r'\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(?:.+?)\s*\|',
        text
    )
    if risk_table:
        risks = []
        for r in risk_table:
            if _is_data_row(r) and _has_chinese(r):
                risks.append({
                    "priority": r[0], "risk": r[1].strip(),
                    "trigger": r[2].strip() if len(r) > 2 else "",
                    "impact": r[3].strip() if len(r) > 3 else "",
                })
        if risks:
            result["risks"] = risks[:10]

    # ── 提取候选标的 ──
    # 匹配 thesis 中的候选表格：| 标的 | 卡住的环节 | 排序原因 | 证据 | ...
    candidate_table = re.findall(
        r'\|\s*([^|]{2,30})\s*\|\s*([^|]{2,30})\s*\|\s*([^|]{5,80})\s*\|',
        text
    )
    if candidate_table:
        candidates = []
        for c in candidate_table:
            if _is_data_row(c) and _has_chinese(c[:2]):
                candidates.append({
                    "name": c[0].strip(), "position": c[1].strip(),
                    "reason": c[2].strip()[:80],
                })
        if candidates:
            result["candidates"] = candidates[:10]

    # ── 提取定义列表格式的风险（risk-register.md 格式）──
    # 格式: ### R1: 标题  ... - **风险描述**: ...  ... - **影响程度**: **颠覆**
    if not result.get("risks"):
        risk_blocks = re.findall(
            r'###\s*R\d+:\s*(.+?)\n.*?'
            r'\*\*风险描述\*\*[：:]\s*(.+?)(?:\n|$)',
            text, re.DOTALL
        )
        if risk_blocks:
            risks = []
            for i, rb in enumerate(risk_blocks[:10]):
                # 查找影响程度
                impact_match = re.search(
                    r'\*\*影响程度\*\*[：:]\s*\*{0,2}(.+?)\*{0,2}',
                    text[text.find(rb[0]):text.find(rb[0]) + 800]
                )
                impact = impact_match.group(1).split("—")[0].split("，")[0].strip() if impact_match else "待定"
                risks.append({
                    "priority": str(i + 1),
                    "risk": rb[0].strip()[:60],
                    "trigger": rb[1].strip()[:120],
                    "impact": impact,
                })
            if risks:
                result["risks"] = risks

    # 提取综合风险定级
    risk_level = re.search(r'综合风险定级.*?\*{0,2}([高中低]风险)\*{0,2}', text)
    if risk_level and not result.get("risks"):
        result["risks"] = [{"priority": "1", "risk": f"综合风险定级: {risk_level.group(1)}", "impact": risk_level.group(1)}]

    # ── 提取情景概率 ──
    scenario_items = re.findall(
        r'\|\s*(情景\s*[A-D][^|]*?)\s*\|\s*(.+?)\s*\|',
        text
    )
    if scenario_items:
        result["scenarios"] = [
            {"name": s[0].strip(), "probability": s[1].strip()}
            for s in scenario_items if _has_chinese(s)
        ]

    # 提取核心判断（第一个非空段落块）
    paragraphs = [p.strip() for p in re.findall(r'(?:^|\n\n)([^\n#].+?)(?:\n\n|\n#)', text, re.DOTALL) if p.strip()]
    if paragraphs:
        result["summary"] = paragraphs[0][:500]

    return result


# ── JSON 解析 ──────────────────────────────────────────────────
def extract_from_json(filepath: str) -> dict:
    """从 scan_data.json 等结构化数据提取结论"""
    path = Path(filepath)
    if not path.exists():
        return {"error": f"文件不存在: {filepath}"}

    data = json.loads(path.read_text(encoding="utf-8"))
    return data


# ── 自动发现 ───────────────────────────────────────────────────
def auto_discover(dirpath: str) -> dict:
    """自动发现分析目录下的所有文件和关键结论"""
    path = Path(dirpath)
    if not path.is_dir():
        return {"error": f"目录不存在: {dirpath}"}

    result = {"source_dir": str(path), "files_found": []}
    for f in sorted(path.glob("**/*")):
        if f.is_file():
            result["files_found"].append(str(f.relative_to(path)))

    # 按优先级读取：thesis → risk-register → scenario-analysis
    priority_files = ["thesis.md", "risk-register.md", "scenario-analysis.md", "scan_data.json"]
    for pf in priority_files:
        target = path / pf
        if target.exists():
            if pf.endswith(".json"):
                extracted = extract_from_json(str(target))
            else:
                extracted = extract_from_markdown(str(target))
            result.update(extracted)
            result["primary_source"] = pf
            break

    return result


# ── 格式化输出 ──────────────────────────────────────────────────
def format_conclusion(data: dict, title: str = None):
    """将提取的数据格式化为控制台输出"""
    if "error" in data:
        print(f"{Color.RED}[错误] {data['error']}{Color.RESET}")
        return

    # 主标题
    display_title = title or data.get("title", "分析结论")
    print_header(f"📋 {display_title}", f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 数据来源
    if "source" in data:
        print(f"  {Color.DIM}数据来源: {data['source']}{Color.RESET}")
    if "primary_source" in data:
        print(f"  {Color.DIM}主数据文件: {data['primary_source']}{Color.RESET}")

    # 风险排序
    if data.get("risks"):
        print_section("风险排序（前 N 条）")
        for risk in data["risks"][:6]:
            impact = risk.get("impact", "中度")
            print_risk(impact, f"{risk['priority']}. {risk.get('risk', '')}")
            if risk.get("trigger"):
                print(f"     触发条件: {risk['trigger']}")

    # 情景概率
    if data.get("scenarios"):
        print_section("情景概率分布")
        for s in data["scenarios"]:
            print(f"  • {s['name']}: {Color.BOLD}{s['probability']}{Color.RESET}")

    # 候选标的
    if data.get("candidates"):
        print_section("候选标的")
        headers = ["标的", "产业链位置", "排序原因"]
        rows = []
        for c in data["candidates"][:7]:
            rows.append([c.get("name", ""), c.get("position", ""), c.get("reason", "")])
        print_table(headers, rows)

    # 摘要
    if data.get("summary"):
        print_section("核心判断")
        print(f"  {data['summary']}")

    # 全局财经快讯摘要
    if data.get("dimensions", {}).get("sentiment", {}).get("top_themes"):
        print_section("市场情绪 — 热门题材")
        themes = data["dimensions"]["sentiment"]["top_themes"][:8]
        theme_str = "  ".join(f"{t['theme']}({t['count']}只)" for t in themes)
        print(f"  {theme_str}")

    # 四维扫描特化输出
    dims = data.get("dimensions", {})
    if dims:
        print_section("四维扫描摘要")

        # 指数
        if dims.get("industry", {}).get("indices"):
            idx = dims["industry"]["indices"]
            idx_str = "  ".join(f"{n}: {v.get('change_pct', 0):+.2f}%" for n, v in idx.items())
            print(f"  主要指数: {idx_str}")

        # 行业 TOP3
        if dims.get("industry", {}).get("industry_top10"):
            top_ind = dims["industry"]["industry_top10"][:3]
            ind_str = "  ".join(f"{i['name']}{i['change_pct']:+.2f}%" for i in top_ind)
            print(f"  强势行业: {ind_str}")

        # 北向资金
        cf = dims.get("capital_flow", {})
        if cf.get("northbound_total_yi"):
            direction = cf.get("northbound_direction", "")
            print(f"  北向资金: {direction} {cf['northbound_total_yi']:+.1f}亿")

        # 成交额TOP5
        if dims.get("performance", {}).get("top20_by_change"):
            top5 = dims["performance"]["top20_by_change"][:5]
            top5_str = "  ".join(
                f"{s['name']}({s['code']}){s['change_pct']:+.1f}%"
                for s in top5
            )
            print(f"  强势股 TOP5: {top5_str}")

    # 生成的文件清单
    if data.get("files_found"):
        print_section("分析过程文件")
        for f in data["files_found"][:12]:
            print(f"  {Color.DIM}📄{Color.RESET} {f}")

    # ── 底部风险声明 ──
    print(f"\n{Color.DIM}{SEP_LIGHT}{Color.RESET}")
    print(f"{Color.DIM}  ⚠ 研究边界声明{Color.RESET}")
    print(f"{Color.DIM}  以上结论基于可验证的公开数据，标注为研究框架产出。{Color.RESET}")
    print(f"{Color.DIM}  不构成买卖指令。最终交易决策、时机和仓位由您自行判断。{Color.RESET}")
    print(f"{Color.DIM}{SEP_LIGHT}{Color.RESET}\n")


# ── 入口 ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="统一结论打印工具 — 分析过程写文件，最终结论打印到控制台",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --file src/AI半导体/产业链扫描/2026-06-13-A股AI半导体/thesis.md
  %(prog)s --json src/2026-06-15-全市场四维扫描/scan_data.json
  %(prog)s --text "最终结论: xxx" --title "2026-06-15 四维扫描结论"
  %(prog)s --auto src/有色金属/黄金铜矿/2026-06-15-紫金矿业/
        """
    )
    parser.add_argument("--file", help="从 markdown 文件提取结论并打印")
    parser.add_argument("--json", help="从 JSON 文件提取结论并打印")
    parser.add_argument("--text", help="直接打印文本结论")
    parser.add_argument("--title", help="结论标题（配合 --text 使用）")
    parser.add_argument("--auto", help="自动发现目录下的分析文件并提取结论")
    parser.add_argument("--no-color", action="store_true", help="禁用颜色输出")

    args = parser.parse_args()

    if args.no_color:
        Color.disable()

    if args.file:
        data = extract_from_markdown(args.file)
        format_conclusion(data, title=args.title)

    elif args.json:
        data = extract_from_json(args.json)
        format_conclusion(data, title=args.title)

    elif args.text:
        format_conclusion({"summary": args.text}, title=args.title or "分析结论")

    elif args.auto:
        data = auto_discover(args.auto)
        format_conclusion(data, title=args.title)

    else:
        parser.print_help()
        print(f"\n{Color.YELLOW}提示: 至少需要 --file / --json / --text / --auto 中的一个参数{Color.RESET}")


if __name__ == "__main__":
    main()